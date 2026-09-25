from __future__ import annotations

from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.core.database import Base
from app.models.paper import Job, Paper
from app.models.states import JobStatus
from app.services.jobs import claim_next_job, recover_interrupted_jobs, utc_now


def worker_database(tmp_path):
    database_path = tmp_path / "worker.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = Settings(
        database_url=f"sqlite:///{database_path.as_posix()}",
        job_worker_enabled=False,
        job_lease_seconds=60,
        job_max_reclaims=3,
    )
    return engine, factory, settings


def add_analysis_job(factory, *, status: str = JobStatus.QUEUED, attempt_count: int = 0) -> str:
    with factory() as db:
        paper = Paper(source="upload", title="Paper", authors=[], pdf_path="paper.pdf", status="queued")
        db.add(paper)
        db.flush()
        job = Job(
            paper_id=paper.id,
            job_type="analysis",
            status=status,
            idempotency_key=f"analysis:{paper.id}:1",
            attempt_count=attempt_count,
        )
        db.add(job)
        db.commit()
        return job.id


def test_two_claimers_cannot_claim_the_same_job(tmp_path) -> None:
    engine, factory, settings = worker_database(tmp_path)
    job_id = add_analysis_job(factory)

    first = claim_next_job(factory, worker_id="worker-a", settings=settings)
    second = claim_next_job(factory, worker_id="worker-b", settings=settings)

    assert first == job_id
    assert second is None
    with factory() as db:
        assert db.get(Job, job_id).attempt_count == 1
    engine.dispose()


def test_running_job_is_requeued_after_restart(tmp_path) -> None:
    engine, factory, settings = worker_database(tmp_path)
    job_id = add_analysis_job(factory)
    assert claim_next_job(factory, worker_id="old-worker", settings=settings) == job_id

    requeued, failed = recover_interrupted_jobs(
        factory,
        worker_id="new-worker",
        settings=settings,
        all_previous_workers=True,
    )

    assert (requeued, failed) == (1, 0)
    assert claim_next_job(factory, worker_id="new-worker", settings=settings) == job_id
    engine.dispose()


def test_expired_jobs_are_reclaimed_until_attempt_limit(tmp_path) -> None:
    engine, factory, settings = worker_database(tmp_path)
    reclaimable_id = add_analysis_job(factory, status=JobStatus.RUNNING, attempt_count=2)
    terminal_id = add_analysis_job(factory, status=JobStatus.RUNNING, attempt_count=3)
    with factory() as db:
        for job_id in (reclaimable_id, terminal_id):
            job = db.get(Job, job_id)
            job.worker_id = "stopped-worker"
            job.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()

    requeued, failed = recover_interrupted_jobs(factory, worker_id="worker", settings=settings)

    assert (requeued, failed) == (1, 1)
    with factory() as db:
        assert db.get(Job, reclaimable_id).status == JobStatus.QUEUED
        assert db.get(Job, terminal_id).status == JobStatus.FAILED
    engine.dispose()


def test_completed_jobs_are_never_replayed(tmp_path) -> None:
    engine, factory, settings = worker_database(tmp_path)
    job_id = add_analysis_job(factory, status=JobStatus.COMPLETED, attempt_count=1)

    recover_interrupted_jobs(factory, worker_id="new-worker", settings=settings, all_previous_workers=True)

    assert claim_next_job(factory, worker_id="new-worker", settings=settings) is None
    with factory() as db:
        assert db.get(Job, job_id).status == JobStatus.COMPLETED
    engine.dispose()
