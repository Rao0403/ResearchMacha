from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai import AIProviderError, MockProvider
from app.core.database import Base
from app.models.paper import Highlight, Job, Paper, PaperChunk, PaperSummary
from app.models.states import JobStatus
from app.services import analysis
from app.services import memory as memory_service
from app.models.paper import ResearchMemory
from app.services.vector_store import MySQLVectorStore


def analysis_database(tmp_path):
    database_path = tmp_path / "analysis.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, factory


def seed_successful_analysis(factory) -> str:
    with factory() as db:
        paper = Paper(
            source="upload",
            title="Existing paper",
            authors=[],
            pdf_path="paper.pdf",
            status="ready",
            analysis_generation=1,
            analysis_mode="ai",
        )
        db.add(paper)
        db.flush()
        db.add(
            PaperChunk(
                paper_id=paper.id,
                analysis_generation=1,
                chunk_index=0,
                page_start=1,
                page_end=1,
                text="Previous evidence remains available.",
            )
        )
        db.add(
            PaperSummary(
                paper_id=paper.id,
                problem_or_hypothesis="Previous summary",
                approach="Previous approach",
                experiments="Previous experiments",
                results="Previous results",
                conclusion="Previous conclusion",
                limitations_or_notes="Previous limitations",
                section_citations={},
                generation_mode="ai",
            )
        )
        db.add(
            Highlight(
                paper_id=paper.id,
                position=0,
                label="Previous",
                explanation="Previous highlight",
                citations=[],
            )
        )
        db.commit()
        return paper.id


def configure_success(monkeypatch, vector_store=None) -> RecordingVectorStore:
    store = vector_store or RecordingVectorStore()
    monkeypatch.setattr(analysis, "extract_pdf_pages", lambda path: [{"page_number": 4, "text": "New grounded evidence."}])
    monkeypatch.setattr(analysis, "get_ai_provider", lambda: MockProvider())
    monkeypatch.setattr(analysis, "get_vector_store", lambda: store)
    monkeypatch.setattr(analysis, "create_paper_fact_memory", lambda *args, **kwargs: None)
    return store


def test_enqueue_reanalysis_keeps_previous_analysis_and_reuses_active_job(tmp_path) -> None:
    engine, factory = analysis_database(tmp_path)
    paper_id = seed_successful_analysis(factory)
    with factory() as db:
        first = analysis.enqueue_analysis_job(db, paper_id, auto_reset=True)
        second = analysis.enqueue_analysis_job(db, paper_id, auto_reset=True)

        assert first.id == second.id
        assert first.requested_generation == 2
        assert db.query(Job).filter(Job.paper_id == paper_id).count() == 1
        assert db.query(PaperChunk).filter(PaperChunk.paper_id == paper_id).count() == 1
        assert db.query(PaperSummary).filter(PaperSummary.paper_id == paper_id).one().conclusion == "Previous conclusion"
    engine.dispose()


def test_concurrent_analyze_requests_return_one_generation_job(tmp_path) -> None:
    engine, factory = analysis_database(tmp_path)
    paper_id = seed_successful_analysis(factory)

    def enqueue() -> str:
        with factory() as db:
            return analysis.enqueue_analysis_job(db, paper_id, auto_reset=True).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        job_ids = list(executor.map(lambda _: enqueue(), range(2)))

    assert len(set(job_ids)) == 1
    with factory() as db:
        assert db.query(Job).filter(Job.paper_id == paper_id).count() == 1
    engine.dispose()


def test_successful_reanalysis_swaps_generation_atomically(tmp_path, monkeypatch) -> None:
    engine, factory = analysis_database(tmp_path)
    paper_id = seed_successful_analysis(factory)
    store = configure_success(monkeypatch)
    with factory() as db:
        job = analysis.enqueue_analysis_job(db, paper_id, auto_reset=True)

    analysis.process_analysis_job(job.id, session_factory=factory)

    with factory() as db:
        paper = db.get(Paper, paper_id)
        chunks = db.query(PaperChunk).filter(PaperChunk.paper_id == paper_id).all()
        assert paper.analysis_generation == 2
        assert paper.status == "degraded"
        assert paper.analysis_mode == "mock"
        assert {chunk.analysis_generation for chunk in chunks} == {2}
        assert all(chunk.page_start == chunk.page_end == 4 for chunk in chunks)
        assert db.get(Job, job.id).status == JobStatus.COMPLETED_WITH_WARNINGS
        assert db.query(PaperSummary).filter(PaperSummary.paper_id == paper_id).one().conclusion != "Previous conclusion"
    assert len(store.upserted) == 1
    assert len(store.deleted) == 1
    engine.dispose()


def test_failed_reanalysis_preserves_previous_notes(tmp_path, monkeypatch) -> None:
    engine, factory = analysis_database(tmp_path)
    paper_id = seed_successful_analysis(factory)
    configure_success(monkeypatch)
    monkeypatch.setattr(analysis, "get_ai_provider", lambda: FailingSummaryProvider())
    with factory() as db:
        job = analysis.enqueue_analysis_job(db, paper_id, auto_reset=True)

    analysis.process_analysis_job(job.id, session_factory=factory)

    with factory() as db:
        paper = db.get(Paper, paper_id)
        assert paper.analysis_generation == 1
        assert paper.status == "ready"
        assert "source-extractive fallback" in paper.analysis_warning
        assert db.get(Job, job.id).status == JobStatus.COMPLETED_WITH_WARNINGS
        assert db.query(PaperChunk).filter(PaperChunk.paper_id == paper_id).one().text.startswith("Previous")
        assert db.query(PaperSummary).filter(PaperSummary.paper_id == paper_id).one().conclusion == "Previous conclusion"
    engine.dispose()


def test_first_analysis_provider_failure_persists_extractive_result(tmp_path, monkeypatch) -> None:
    engine, factory = analysis_database(tmp_path)
    with factory() as db:
        paper = Paper(source="upload", title="New paper", authors=[], pdf_path="paper.pdf", status="queued")
        db.add(paper)
        db.commit()
        paper_id = paper.id
        job = analysis.enqueue_analysis_job(db, paper_id, auto_reset=True)
        job_id = job.id
    store = configure_success(monkeypatch)
    monkeypatch.setattr(analysis, "get_ai_provider", lambda: FailingSummaryProvider())

    analysis.process_analysis_job(job_id, session_factory=factory)

    with factory() as db:
        paper = db.get(Paper, paper_id)
        summary = db.query(PaperSummary).filter(PaperSummary.paper_id == paper_id).one()
        completed_job = db.get(Job, job_id)
        assert paper.status == "degraded"
        assert paper.analysis_mode == "extractive"
        assert summary.generation_mode == "extractive"
        assert summary.warning and "summary provider failed" in summary.warning
        assert all(summary.section_citations.values())
        assert completed_job.status == JobStatus.COMPLETED_WITH_WARNINGS
        assert completed_job.warning_message
    assert store.upserted
    engine.dispose()


def test_resume_after_database_swap_skips_model_work(tmp_path, monkeypatch) -> None:
    engine, factory = analysis_database(tmp_path)
    paper_id = seed_successful_analysis(factory)
    with factory() as db:
        paper = db.get(Paper, paper_id)
        paper.analysis_generation = 2
        job = Job(
            paper_id=paper_id,
            job_type="analysis",
            status=JobStatus.RUNNING,
            requested_generation=2,
            idempotency_key=f"analysis:{paper_id}:2",
        )
        db.add_all([paper, job])
        db.commit()
        job_id = job.id
    monkeypatch.setattr(analysis, "get_ai_provider", lambda: ModelMustNotRun())

    analysis.process_analysis_job(job_id, session_factory=factory)

    with factory() as db:
        assert db.get(Job, job_id).status == JobStatus.COMPLETED
    engine.dispose()


def test_paper_fact_memory_is_replaced_instead_of_duplicated(db_session, monkeypatch) -> None:
    paper = Paper(source="upload", title="Paper", authors=[], pdf_path="paper.pdf", status="ready")
    db_session.add(paper)
    db_session.commit()
    monkeypatch.setattr(memory_service, "get_vector_store", lambda: MySQLVectorStore())

    memory_service.create_paper_fact_memory(
        db_session,
        paper_id=paper.id,
        title=paper.title,
        sections={"conclusion": "First conclusion"},
    )
    memory_service.create_paper_fact_memory(
        db_session,
        paper_id=paper.id,
        title=paper.title,
        sections={"conclusion": "Replacement conclusion"},
    )

    memories = db_session.query(ResearchMemory).filter(ResearchMemory.paper_id == paper.id).all()
    assert len(memories) == 1
    assert "Replacement conclusion" in memories[0].text


class RecordingVectorStore:
    def __init__(self) -> None:
        self.upserted = []
        self.deleted = []

    def upsert_chunks(self, chunks):
        self.upserted.extend(chunks)

    def delete_chunks(self, chunks):
        self.deleted.extend(chunks)


class FailingSummaryProvider(MockProvider):
    def generate_summary(self, paper_title, chunks):
        raise AIProviderError("summary provider failed")


class ModelMustNotRun:
    def __getattr__(self, name):
        raise AssertionError(f"model method {name} must not run")
