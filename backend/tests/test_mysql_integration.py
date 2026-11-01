from __future__ import annotations

import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ai import AIProviderError, MockProvider
from app.core.config import Settings, get_settings
from app.models.paper import Job, Paper, PaperChunk, PaperSummary, ResearchCandidate, ResearchProject
from app.models.states import JobStatus
from app.services import analysis, memory as memory_service, research, retrieval
from app.services import vector_store as vector_store_service
from app.services.arxiv import ArxivEntry
from app.services.jobs import claim_next_job, dispatch_job, heartbeat_job, recover_interrupted_jobs, utc_now
from app.services.vector_store import FallbackVectorStore, MySQLVectorStore


API_ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.mysql


@pytest.fixture
def mysql_database_url() -> str:
    raw_url = os.getenv("TEST_MYSQL_URL")
    if not raw_url:
        pytest.skip("TEST_MYSQL_URL is not configured")
    source_url = make_url(raw_url)
    if not source_url.drivername.startswith("mysql"):
        pytest.fail("TEST_MYSQL_URL must use a MySQL SQLAlchemy driver")

    database_name = f"research_macha_test_{uuid.uuid4().hex}"
    if not re.fullmatch(r"research_macha_test_[a-f0-9]{32}", database_name):
        pytest.fail("Refusing to create an unexpected test database name")
    admin_url = source_url.set(database="mysql")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    with admin_engine.connect() as connection:
        connection.execute(text(f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))

    database_url = source_url.set(database=database_name).render_as_string(hide_password=False)
    previous_database_url = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = database_url
        get_settings.cache_clear()
        config = Config(str(API_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(API_ROOT / "alembic"))
        command.upgrade(config, "head")
        yield database_url
    finally:
        get_settings.cache_clear()
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        target_engine = create_engine(source_url.set(database=database_name), pool_pre_ping=True)
        target_engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS `{database_name}`"))
        admin_engine.dispose()


@pytest.fixture
def mysql_factory(mysql_database_url: str):
    engine = create_engine(mysql_database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield engine, factory
    finally:
        engine.dispose()


def worker_settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        job_worker_enabled=False,
        job_lease_seconds=60,
        job_max_reclaims=3,
        ai_provider="mock",
        vector_provider="mysql",
    )


def test_mysql_migration_has_reliability_constraints(mysql_factory) -> None:
    engine, _ = mysql_factory
    inspector = inspect(engine)

    assert engine.dialect.name == "mysql"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20260925_0005"
    assert {"project_id", "candidate_id", "lease_expires_at", "warning_message"} <= {
        column["name"] for column in inspector.get_columns("jobs")
    }
    assert "uq_jobs_idempotency_key" in {
        constraint["name"] for constraint in inspector.get_unique_constraints("jobs")
    }
    assert "uq_paper_chunks_generation_index" in {
        constraint["name"] for constraint in inspector.get_unique_constraints("paper_chunks")
    }
    assert {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("jobs")} >= {
        "fk_jobs_project_id",
        "fk_jobs_candidate_id",
    }


def test_mysql_concurrent_claims_and_expired_lease_recovery(mysql_database_url, mysql_factory) -> None:
    _, factory = mysql_factory
    settings = worker_settings(mysql_database_url)
    with factory() as db:
        paper = Paper(source="upload", title="Claimed once", authors=[], pdf_path="paper.pdf", status="queued")
        db.add(paper)
        db.flush()
        job = Job(
            paper_id=paper.id,
            job_type="analysis",
            status=JobStatus.QUEUED,
            idempotency_key=f"analysis:{paper.id}:1",
            requested_generation=1,
        )
        db.add(job)
        db.commit()
        job_id = job.id

    def claim(worker_id: str) -> str | None:
        return claim_next_job(factory, worker_id=worker_id, settings=settings)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ["worker-a", "worker-b"]))

    assert results.count(job_id) == 1
    assert results.count(None) == 1
    with factory() as db:
        claimed = db.get(Job, job_id)
        original_lease = claimed.lease_expires_at
        worker_id = claimed.worker_id
    assert worker_id is not None
    assert heartbeat_job(job_id, worker_id=worker_id, session_factory=factory, settings=settings)
    with factory() as db:
        claimed = db.get(Job, job_id)
        assert claimed.lease_expires_at >= original_lease
        claimed.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()

    assert recover_interrupted_jobs(factory, worker_id="recovery", settings=settings) == (1, 0)
    assert claim_next_job(factory, worker_id="recovery", settings=settings) == job_id
    with factory() as db:
        assert db.get(Job, job_id).attempt_count == 2


def test_mysql_row_locks_and_unique_keys_deduplicate_analysis(mysql_factory) -> None:
    _, factory = mysql_factory
    with factory() as db:
        paper = Paper(source="upload", title="One generation", authors=[], pdf_path="paper.pdf", status="ready")
        db.add(paper)
        db.commit()
        paper_id = paper.id

    def enqueue() -> str:
        with factory() as db:
            return analysis.enqueue_analysis_job(db, paper_id, auto_reset=True).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        job_ids = list(executor.map(lambda _: enqueue(), range(2)))

    assert len(set(job_ids)) == 1
    with factory() as db:
        assert db.query(Job).filter(Job.paper_id == paper_id, Job.job_type == "analysis").count() == 1
        db.add(Job(paper_id=paper_id, job_type="analysis", idempotency_key=f"analysis:{paper_id}:1"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_mysql_concurrent_approval_and_blocker_recovery(mysql_factory) -> None:
    _, factory = mysql_factory
    with factory() as db:
        project = ResearchProject(question="How does retrieval improve factuality?", status="awaiting_approval")
        db.add(project)
        db.flush()
        candidates = [
            ResearchCandidate(
                project_id=project.id,
                arxiv_id=f"2601.0000{index}",
                title=f"Candidate {index}",
                authors=[],
                abstract="Grounded retrieval evidence",
                pdf_url="https://example.test/paper.pdf",
                entry_url="https://example.test/paper",
                score=90 - index,
                rationale="Relevant",
                selected=True,
            )
            for index in range(2)
        ]
        db.add_all(candidates)
        db.commit()
        project_id = project.id
        candidate_ids = [candidate.id for candidate in candidates]

    def approve() -> None:
        with factory() as db:
            research.import_selected_candidates(db, project_id, candidate_ids)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: approve(), range(2)))

    with factory() as db:
        jobs = db.query(Job).filter(Job.project_id == project_id, Job.job_type == "import").all()
        assert len(jobs) == 2
        first, second = jobs
        first.status = JobStatus.FAILED
        first.error_message = "temporary download failure"
        second.status = JobStatus.FAILED
        second.error_message = "unwanted paper"
        db.commit()
        first_id, second_id, second_candidate_id = first.id, second.id, second.candidate_id

    with factory() as db:
        research.retry_job(db, first_id)
    with factory() as db:
        project = research.exclude_candidate(db, project_id, second_candidate_id)
        assert project.status == "importing"
        assert db.get(Job, first_id).status == JobStatus.QUEUED
        excluded = db.get(Job, second_id)
        assert excluded.candidate_id is None
        assert excluded.payload["excluded_candidate_id"] == second_candidate_id


@pytest.mark.parametrize(
    ("provider", "expected_summary_mode"),
    [
        pytest.param(MockProvider(), "mock", id="mock-provider-with-vector-outage"),
        pytest.param(None, "extractive", id="provider-outage"),
        pytest.param("invalid-citations", "extractive", id="invalid-citations"),
    ],
)
def test_mysql_full_workflow_dispatches_once_and_degrades_safely(
    mysql_database_url,
    mysql_factory,
    monkeypatch,
    provider,
    expected_summary_mode,
) -> None:
    _, factory = mysql_factory
    configured_provider = (
        UnavailableProvider()
        if provider is None
        else InvalidCitationProvider()
        if provider == "invalid-citations"
        else provider
    )
    vector_store = FallbackVectorStore(UnavailableVectorStore(), MySQLVectorStore())
    settings = worker_settings(mysql_database_url)

    monkeypatch.setattr(research, "fetch_arxiv_entry", fake_arxiv_entry)
    monkeypatch.setattr(research, "create_or_update_paper_from_arxiv", fake_create_arxiv_paper)
    monkeypatch.setattr(analysis, "extract_pdf_pages", lambda path: [
        {"page_number": 1, "text": "The study evaluates retrieval grounding."},
        {"page_number": 2, "text": "Results show improved factual accuracy over the baseline."},
    ])
    monkeypatch.setattr(research, "get_ai_provider", lambda: configured_provider)
    monkeypatch.setattr(analysis, "get_ai_provider", lambda: configured_provider)
    monkeypatch.setattr(memory_service, "get_ai_provider", lambda: configured_provider)
    monkeypatch.setattr(retrieval, "get_ai_provider", lambda: configured_provider)
    monkeypatch.setattr(research, "get_vector_store", lambda: vector_store)
    monkeypatch.setattr(analysis, "get_vector_store", lambda: vector_store)
    monkeypatch.setattr(memory_service, "get_vector_store", lambda: vector_store)
    monkeypatch.setattr(vector_store_service, "get_vector_store", lambda: vector_store)

    with factory() as db:
        project = ResearchProject(question="Does retrieval improve factual accuracy?", status="awaiting_approval")
        db.add(project)
        db.flush()
        candidate = ResearchCandidate(
            project_id=project.id,
            arxiv_id="2601.12345",
            title="Retrieval Grounding",
            authors=["Researcher"],
            abstract="An evaluation of grounded retrieval.",
            year=2026,
            pdf_url="https://example.test/paper.pdf",
            entry_url="https://example.test/paper",
            score=98,
            rationale="Directly evaluates factuality.",
            selected=True,
        )
        db.add(candidate)
        db.commit()
        project_id, candidate_id = project.id, candidate.id

        research.approve_research_workflow(db, project_id, [candidate_id])
        research.approve_research_workflow(db, project_id, [candidate_id])
        assert db.query(Job).filter(Job.project_id == project_id, Job.job_type == "import").count() == 1

    processed_types: list[str] = []
    for _ in range(6):
        job_id = claim_next_job(factory, worker_id="integration-worker", settings=settings)
        if job_id is None:
            break
        with factory() as db:
            processed_types.append(db.get(Job, job_id).job_type)
        dispatch_job(job_id, worker_id="integration-worker", session_factory=factory, settings=settings)

    assert processed_types == ["import", "analysis", "synthesis"]
    with factory() as db:
        project = db.get(ResearchProject, project_id)
        paper = db.query(Paper).filter(Paper.source_key == "arxiv:2601.12345").one()
        summary = db.query(PaperSummary).filter(PaperSummary.paper_id == paper.id).one()
        chunks = db.query(PaperChunk).filter(PaperChunk.paper_id == paper.id).all()
        jobs = db.query(Job).filter(Job.project_id == project_id).all()

        assert project.status == "degraded"
        assert project.synthesis_json["generation_mode"] in {"mock", "extractive"}
        assert summary.generation_mode == expected_summary_mode
        assert chunks and all(chunk.page_start == chunk.page_end for chunk in chunks)
        assert {job.job_type for job in jobs} == {"import", "analysis", "synthesis"}
        assert all(job.status in {JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_WARNINGS} for job in jobs)
        persisted_chunk_ids = {chunk.id for chunk in chunks}
        cited_chunk_ids = {
            citation["chunk_id"]
            for citations in summary.section_citations.values()
            for citation in citations
        }
        assert cited_chunk_ids <= persisted_chunk_ids
        assert "invented-chunk" not in cited_chunk_ids


def fake_arxiv_entry(arxiv_id: str) -> ArxivEntry:
    return ArxivEntry(
        arxiv_id=arxiv_id,
        title="Retrieval Grounding",
        authors=["Researcher"],
        abstract="An evaluation of grounded retrieval.",
        year=2026,
        pdf_url="https://example.test/paper.pdf",
        entry_url="https://example.test/paper",
    )


def fake_create_arxiv_paper(db: Session, entry: ArxivEntry) -> tuple[Paper, bool]:
    paper = db.query(Paper).filter(Paper.source_key == f"arxiv:{entry.arxiv_id}").one_or_none()
    if paper is not None:
        return paper, False
    paper = Paper(
        source="arxiv",
        source_key=f"arxiv:{entry.arxiv_id}",
        arxiv_id=entry.arxiv_id,
        title=entry.title,
        authors=entry.authors,
        abstract=entry.abstract,
        year=entry.year,
        pdf_path="integration-paper.pdf",
        status="queued",
    )
    db.add(paper)
    db.flush()
    return paper, True


class UnavailableVectorStore:
    name = "qdrant"

    def __getattr__(self, name):
        def unavailable(*args, **kwargs):
            raise RuntimeError(f"Qdrant unavailable during {name}")

        return unavailable


class UnavailableProvider(MockProvider):
    def embed_texts(self, texts):
        raise AIProviderError("provider embeddings unavailable")

    def generate_summary(self, paper_title, chunks):
        raise AIProviderError("provider summary unavailable")

    def synthesize_collection(self, question, paper_contexts, memory_context=None):
        raise AIProviderError("provider synthesis unavailable")


class InvalidCitationProvider(MockProvider):
    def generate_summary(self, paper_title, chunks):
        payload = super().generate_summary(paper_title, chunks)
        first_section = next(iter(payload.section_citations))
        payload.section_citations[first_section][0] = {
            "page": 999,
            "excerpt": "Fabricated evidence",
            "chunk_id": "invented-chunk",
        }
        return payload
