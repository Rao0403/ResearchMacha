from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai import EvidenceCitation, PaperFinding, ResearchBrief
from app.core.database import Base
from app.models.paper import Job, Paper, ResearchCandidate, ResearchProject, ResearchProjectPaper
from app.models.states import JobStatus
from app.services import research


def workflow_database(tmp_path):
    path = tmp_path / "reconcile.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, factory


def seed_ready_project(factory, *, paper_count: int = 1) -> tuple[str, list[str]]:
    with factory() as db:
        project = ResearchProject(question="How does retrieval improve factuality?", status="analyzing")
        db.add(project)
        db.flush()
        paper_ids = []
        for index in range(paper_count):
            paper = Paper(
                source="upload",
                title=f"Paper {index}",
                authors=[],
                pdf_path=f"paper-{index}.pdf",
                status="ready",
                analysis_generation=1,
            )
            db.add(paper)
            db.flush()
            db.add(ResearchProjectPaper(project_id=project.id, paper_id=paper.id))
            paper_ids.append(paper.id)
        db.commit()
        return project.id, paper_ids


def test_workflow_get_is_read_only_and_never_queues_synthesis(api_client, db_session, monkeypatch) -> None:
    project = ResearchProject(question="How does retrieval improve factuality?", status="analyzing")
    paper = Paper(source="upload", title="Ready", authors=[], pdf_path="paper.pdf", status="ready", analysis_generation=1)
    db_session.add_all([project, paper])
    db_session.flush()
    db_session.add(ResearchProjectPaper(project_id=project.id, paper_id=paper.id))
    db_session.commit()
    monkeypatch.setattr(research, "synthesize_project", lambda *args, **kwargs: pytest.fail("GET invoked synthesis"))

    for _ in range(100):
        response = api_client.get(f"/api/research-workflows/{project.id}")
        assert response.status_code == 200

    assert db_session.query(Job).filter(Job.project_id == project.id).count() == 0
    db_session.refresh(project)
    assert project.status == "analyzing"


def test_concurrent_reconciliation_creates_one_synthesis_job(tmp_path) -> None:
    engine, factory = workflow_database(tmp_path)
    project_id, _ = seed_ready_project(factory)

    def reconcile() -> None:
        with factory() as db:
            research.reconcile_project(db, project_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: reconcile(), range(2)))

    with factory() as db:
        jobs = db.query(Job).filter(Job.project_id == project_id, Job.job_type == "synthesis").all()
        assert len(jobs) == 1
        assert jobs[0].status == JobStatus.QUEUED
        assert db.get(ResearchProject, project_id).status == "synthesis_queued"
    engine.dispose()


def test_failed_import_blocks_and_exclusion_returns_to_approval(tmp_path) -> None:
    engine, factory = workflow_database(tmp_path)
    with factory() as db:
        project = ResearchProject(question="How does retrieval improve factuality?", status="importing")
        db.add(project)
        db.flush()
        candidate = ResearchCandidate(
            project_id=project.id,
            arxiv_id="2401.00001",
            title="Failed candidate",
            authors=[],
            abstract="Evidence",
            year=2024,
            pdf_url="pdf",
            entry_url="entry",
            score=90,
            rationale="Relevant",
            selected=True,
        )
        db.add(candidate)
        db.flush()
        job = Job(
            project_id=project.id,
            candidate_id=candidate.id,
            job_type="import",
            status=JobStatus.FAILED,
            idempotency_key=f"import:{project.id}:{candidate.id}",
            error_message="download failed",
        )
        db.add(job)
        db.commit()
        project_id, candidate_id = project.id, candidate.id

    with factory() as db:
        blocked = research.reconcile_project(db, project_id)
        assert blocked.status == "blocked"
        blockers = research.project_blocking_items(blocked)
        assert blockers[0]["target_type"] == "candidate"
        assert blockers[0]["job_id"] is not None
        after_exclusion = research.exclude_candidate(db, project_id, candidate_id)
        assert after_exclusion.status == "awaiting_approval"
        assert db.query(Job).filter(Job.project_id == project_id, Job.job_type == "synthesis").count() == 0
    engine.dispose()


def test_failed_paper_blocks_until_excluded_then_remaining_paper_synthesizes(tmp_path) -> None:
    engine, factory = workflow_database(tmp_path)
    project_id, paper_ids = seed_ready_project(factory, paper_count=2)
    with factory() as db:
        failed_paper = db.get(Paper, paper_ids[1])
        failed_paper.status = "failed"
        failed_job = Job(
            project_id=project_id,
            paper_id=failed_paper.id,
            job_type="analysis",
            status=JobStatus.FAILED,
            idempotency_key=f"analysis:{failed_paper.id}:2",
            requested_generation=2,
            error_message="extraction failed",
        )
        db.add_all([failed_paper, failed_job])
        db.commit()

        assert research.reconcile_project(db, project_id).status == "blocked"
        project = research.exclude_project_paper(db, project_id, failed_paper.id)
        assert project.status == "synthesis_queued"
        assert db.get(Paper, failed_paper.id) is not None
        assert db.query(Job).filter(Job.project_id == project_id, Job.job_type == "synthesis").count() == 1
    engine.dispose()


def test_retry_failed_import_only_requeues_target(tmp_path) -> None:
    engine, factory = workflow_database(tmp_path)
    with factory() as db:
        project = ResearchProject(question="How does retrieval improve factuality?", status="blocked")
        db.add(project)
        db.flush()
        candidates = []
        for index in range(2):
            candidate = ResearchCandidate(
                project_id=project.id,
                arxiv_id=f"2401.0000{index}",
                title=f"Candidate {index}",
                authors=[],
                abstract="Evidence",
                pdf_url="pdf",
                entry_url="entry",
                score=90,
                rationale="Relevant",
                selected=True,
            )
            db.add(candidate)
            db.flush()
            candidates.append(candidate)
        failed = Job(
            project_id=project.id,
            candidate_id=candidates[0].id,
            job_type="import",
            status=JobStatus.FAILED,
            idempotency_key=f"import:{project.id}:{candidates[0].id}",
        )
        completed = Job(
            project_id=project.id,
            candidate_id=candidates[1].id,
            job_type="import",
            status=JobStatus.COMPLETED,
            idempotency_key=f"import:{project.id}:{candidates[1].id}",
        )
        db.add_all([failed, completed])
        db.commit()

        research.retry_job(db, failed.id)
        assert db.get(Job, failed.id).status == JobStatus.QUEUED
        assert db.get(Job, completed.id).status == JobStatus.COMPLETED
        assert db.get(ResearchProject, project.id).status == "importing"
    engine.dispose()


def test_stale_synthesis_generation_cannot_overwrite_brief(tmp_path, monkeypatch) -> None:
    engine, factory = workflow_database(tmp_path)
    project_id, _ = seed_ready_project(factory)
    with factory() as db:
        project = db.get(ResearchProject, project_id)
        project.synthesis_generation = 2
        project.synthesis_json = {"executive_summary": "Current brief"}
        db.commit()
    citation = EvidenceCitation(paper_id="paper", title="Paper", page=1, excerpt="Evidence", chunk_id="chunk")
    finding = PaperFinding(label="Finding", summary="Grounded", citations=[citation])
    brief = ResearchBrief(
        executive_summary="Stale replacement",
        key_findings=[finding],
        evidence_table=[finding],
        conflicts_or_gaps=[finding],
        suggested_experiments=[finding],
        suggested_research_directions=[finding],
    )
    monkeypatch.setattr(research, "build_paper_contexts", lambda project: [{"paper_id": "paper", "title": "Paper", "summary": "S", "chunks": []}])
    monkeypatch.setattr(research, "retrieve_memories", lambda *args, **kwargs: [])
    monkeypatch.setattr(research, "get_ai_provider", lambda: FakeSynthesisProvider(brief))

    with factory() as db, pytest.raises(research.StaleSynthesisJob):
        research.synthesize_project(db, project_id, expected_generation=1)
    with factory() as db:
        assert db.get(ResearchProject, project_id).synthesis_json["executive_summary"] == "Current brief"
    engine.dispose()


class FakeSynthesisProvider:
    def __init__(self, brief: ResearchBrief) -> None:
        self.brief = brief

    def synthesize_collection(self, question, contexts, memories):
        return self.brief
