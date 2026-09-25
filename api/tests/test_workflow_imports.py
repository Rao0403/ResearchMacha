from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.models.paper import AgentStep, Job, Paper, ResearchCandidate, ResearchMemory, ResearchProject, ResearchProjectPaper
from app.models.states import JobStatus
from app.services import memory as memory_service
from app.services import papers as paper_service
from app.services import research
from app.services.arxiv import ArxivEntry
from app.services.jobs import dispatch_job
from app.services.vector_store import MySQLVectorStore


def workflow_database(tmp_path):
    path = tmp_path / "workflow.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = Settings(database_url=f"sqlite:///{path.as_posix()}", job_worker_enabled=False)
    return engine, factory, settings


def seed_project(factory, count: int = 2) -> tuple[str, list[str]]:
    with factory() as db:
        project = ResearchProject(question="How does grounded retrieval improve factuality?", status="awaiting_approval")
        db.add(project)
        db.flush()
        candidates = []
        for index in range(count):
            candidate = ResearchCandidate(
                project_id=project.id,
                arxiv_id=f"2401.0000{index}",
                title=f"Candidate {index}",
                authors=[],
                abstract="Grounded retrieval evidence",
                year=2024,
                pdf_url=f"https://example.test/{index}.pdf",
                entry_url=f"https://example.test/{index}",
                score=100 - index,
                rationale="Relevant",
                selected=index < 2,
            )
            db.add(candidate)
            candidates.append(candidate)
        db.commit()
        return project.id, [candidate.id for candidate in candidates]


def test_approval_validates_membership_and_five_candidate_cap(tmp_path) -> None:
    engine, factory, _ = workflow_database(tmp_path)
    project_id, candidate_ids = seed_project(factory, count=6)
    with factory() as db:
        with pytest.raises(HTTPException, match="Candidates do not belong"):
            research.import_selected_candidates(db, project_id, ["not-in-project"])
        with pytest.raises(HTTPException, match="at most five"):
            research.import_selected_candidates(db, project_id, candidate_ids)
    engine.dispose()


def test_repeated_approval_deduplicates_jobs_traces_and_memories(tmp_path, monkeypatch) -> None:
    engine, factory, _ = workflow_database(tmp_path)
    project_id, candidate_ids = seed_project(factory)
    monkeypatch.setattr(memory_service, "get_vector_store", lambda: MySQLVectorStore())

    with factory() as db:
        research.approve_research_workflow(db, project_id, candidate_ids)
        research.approve_research_workflow(db, project_id, candidate_ids)

    with factory() as db:
        assert db.query(Job).filter(Job.project_id == project_id, Job.job_type == "import").count() == 2
        assert db.query(AgentStep).filter(AgentStep.project_id == project_id, AgentStep.tool_name == "import_papers").count() == 1
        keys = [row[0] for row in db.query(ResearchMemory.dedupe_key).filter(ResearchMemory.project_id == project_id).all()]
        assert len(keys) == len(set(keys))
        assert set(keys) >= {f"approval:{project_id}:{candidate_id}" for candidate_id in candidate_ids}
    engine.dispose()


def test_concurrent_approval_creates_one_import_job_per_candidate(tmp_path) -> None:
    engine, factory, _ = workflow_database(tmp_path)
    project_id, candidate_ids = seed_project(factory)

    def approve() -> None:
        with factory() as db:
            research.import_selected_candidates(db, project_id, candidate_ids)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: approve(), range(2)))

    with factory() as db:
        jobs = db.query(Job).filter(Job.project_id == project_id, Job.job_type == "import").all()
        assert len(jobs) == 2
        assert {job.candidate_id for job in jobs} == set(candidate_ids)
    engine.dispose()


def test_import_failure_is_isolated_and_retry_resumes_only_failed_job(tmp_path, monkeypatch) -> None:
    engine, factory, settings = workflow_database(tmp_path)
    project_id, candidate_ids = seed_project(factory)
    with factory() as db:
        research.import_selected_candidates(db, project_id, candidate_ids)
        jobs = db.query(Job).filter(Job.project_id == project_id, Job.job_type == "import").order_by(Job.candidate_id).all()
        failing_candidate_id = jobs[1].candidate_id
        job_ids = [job.id for job in jobs]
        for job in jobs:
            job.status = JobStatus.RUNNING
            job.worker_id = "worker"
        db.commit()

    failed_once = {"value": True}

    def fake_fetch(arxiv_id: str) -> ArxivEntry:
        with factory() as db:
            candidate = db.query(ResearchCandidate).filter(ResearchCandidate.arxiv_id == arxiv_id).one()
        if candidate.id == failing_candidate_id and failed_once["value"]:
            raise RuntimeError("download failed")
        return ArxivEntry(arxiv_id, candidate.title, [], "Abstract", 2024, "https://example.test/p.pdf", "https://example.test/p")

    def fake_create(db, entry):
        paper = db.query(Paper).filter(Paper.source_key == f"arxiv:{entry.arxiv_id}").one_or_none()
        if paper is None:
            paper = Paper(
                source="arxiv",
                source_key=f"arxiv:{entry.arxiv_id}",
                arxiv_id=entry.arxiv_id,
                title=entry.title,
                authors=[],
                abstract=entry.abstract,
                year=entry.year,
                pdf_path=f"{entry.arxiv_id}.pdf",
                status="queued",
            )
            db.add(paper)
            db.commit()
            db.refresh(paper)
            return paper, True
        return paper, False

    monkeypatch.setattr(research, "fetch_arxiv_entry", fake_fetch)
    monkeypatch.setattr(research, "create_or_update_paper_from_arxiv", fake_create)
    for job_id in job_ids:
        dispatch_job(job_id, worker_id="worker", session_factory=factory, settings=settings)

    with factory() as db:
        completed = db.query(Job).filter(Job.project_id == project_id, Job.job_type == "import", Job.status == JobStatus.COMPLETED).one()
        failed = db.query(Job).filter(Job.project_id == project_id, Job.job_type == "import", Job.status == JobStatus.FAILED).one()
        assert completed.candidate_id != failed.candidate_id
        assert db.get(ResearchProject, project_id).status == "blocked"
        assert db.query(ResearchProjectPaper).filter(ResearchProjectPaper.project_id == project_id).count() == 1
        failed_once["value"] = False
        research.retry_job(db, failed.id)
        retried_id = failed.id

    with factory() as db:
        retried = db.get(Job, retried_id)
        retried.status = JobStatus.RUNNING
        retried.worker_id = "worker"
        db.commit()
    dispatch_job(retried_id, worker_id="worker", session_factory=factory, settings=settings)

    with factory() as db:
        assert db.get(Job, retried_id).status == JobStatus.COMPLETED
        assert db.query(Job).filter(Job.project_id == project_id, Job.job_type == "import").count() == 2
        assert db.query(ResearchProjectPaper).filter(ResearchProjectPaper.project_id == project_id).count() == 2
    engine.dispose()


def test_arxiv_source_key_resolves_versions_to_one_paper(db_session, monkeypatch) -> None:
    monkeypatch.setattr(paper_service, "save_remote_pdf", lambda url, filename: filename)
    first = ArxivEntry("2401.12345v1", "First", [], "A", 2024, "pdf", "entry")
    second = ArxivEntry("2401.12345v3", "Updated", [], "B", 2025, "pdf", "entry")

    first_paper, created = paper_service.create_or_update_paper_from_arxiv(db_session, first)
    second_paper, created_again = paper_service.create_or_update_paper_from_arxiv(db_session, second)

    assert created
    assert not created_again
    assert first_paper.id == second_paper.id
    assert second_paper.source_key == "arxiv:2401.12345"
    assert db_session.query(Paper).count() == 1
