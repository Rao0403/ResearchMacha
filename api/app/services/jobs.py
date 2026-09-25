from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.models.paper import Job
from app.models.states import JobStatus

logger = logging.getLogger("research_macha.jobs")
SessionFactory = sessionmaker[Session]


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def recover_interrupted_jobs(
    session_factory: Callable[[], Session] = SessionLocal,
    *,
    worker_id: str,
    settings: Settings | None = None,
    all_previous_workers: bool = False,
) -> tuple[int, int]:
    config = settings or get_settings()
    now = utc_now()
    requeued = 0
    failed = 0
    with session_factory() as db:
        query = db.query(Job).filter(Job.status == JobStatus.RUNNING)
        if all_previous_workers:
            query = query.filter(or_(Job.worker_id.is_(None), Job.worker_id != worker_id))
        else:
            query = query.filter(Job.lease_expires_at < now)
        for job in query.with_for_update().all():
            if job.attempt_count >= config.job_max_reclaims:
                job.status = JobStatus.FAILED
                job.error_message = "Job interrupted too many times and exceeded the reclaim limit."
                job.finished_at = now
                failed += 1
            else:
                job.status = JobStatus.QUEUED
                job.worker_id = None
                job.claimed_at = None
                job.lease_expires_at = None
                job.error_message = "Previous worker stopped before the job completed; queued for recovery."
                requeued += 1
            db.add(job)
        db.commit()
    return requeued, failed


def claim_next_job(
    session_factory: Callable[[], Session] = SessionLocal,
    *,
    worker_id: str,
    settings: Settings | None = None,
) -> str | None:
    config = settings or get_settings()
    now = utc_now()
    with session_factory() as db:
        statement = (
            select(Job)
            .where(Job.status == JobStatus.QUEUED)
            .order_by(Job.created_at.asc(), Job.id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = db.execute(statement).scalar_one_or_none()
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        job.worker_id = worker_id
        job.claimed_at = now
        job.lease_expires_at = now + timedelta(seconds=config.job_lease_seconds)
        job.attempt_count += 1
        job.started_at = job.started_at or now
        job.finished_at = None
        db.add(job)
        db.commit()
        return job.id


def heartbeat_job(
    job_id: str,
    *,
    worker_id: str,
    session_factory: Callable[[], Session] = SessionLocal,
    settings: Settings | None = None,
) -> bool:
    config = settings or get_settings()
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != JobStatus.RUNNING or job.worker_id != worker_id:
            return False
        job.lease_expires_at = utc_now() + timedelta(seconds=config.job_lease_seconds)
        db.add(job)
        db.commit()
        return True


def fail_running_job(
    job_id: str,
    error: Exception,
    *,
    worker_id: str,
    session_factory: Callable[[], Session] = SessionLocal,
) -> None:
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != JobStatus.RUNNING or job.worker_id != worker_id:
            return
        job.status = JobStatus.FAILED
        job.error_message = str(error)[:10000]
        job.finished_at = utc_now()
        job.lease_expires_at = None
        db.add(job)
        db.commit()


def dispatch_job(
    job_id: str,
    *,
    worker_id: str,
    session_factory: Callable[[], Session] = SessionLocal,
    settings: Settings | None = None,
) -> None:
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != JobStatus.RUNNING or job.worker_id != worker_id:
            return
        job_type = job.job_type

    heartbeat = lambda: heartbeat_job(
        job_id,
        worker_id=worker_id,
        session_factory=session_factory,
        settings=settings,
    )
    try:
        if job_type == "analysis":
            from app.services.analysis import process_analysis_job

            process_analysis_job(job_id, heartbeat=heartbeat, session_factory=session_factory)
        elif job_type == "import":
            from app.services.research import process_import_job

            process_import_job(job_id, heartbeat=heartbeat, session_factory=session_factory)
        elif job_type == "synthesis":
            from app.services.research import process_synthesis_job

            process_synthesis_job(job_id, heartbeat=heartbeat, session_factory=session_factory)
        else:
            raise RuntimeError(f"Unsupported job type: {job_type}")
    except Exception as exc:  # noqa: BLE001 - worker must persist terminal failure state
        logger.exception("Job %s failed", job_id)
        fail_running_job(job_id, exc, worker_id=worker_id, session_factory=session_factory)


class JobWorker:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory
        self.worker_id = f"local-{uuid.uuid4()}"
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        recover_interrupted_jobs(
            self.session_factory,
            worker_id=self.worker_id,
            settings=self.settings,
            all_previous_workers=True,
        )
        for index in range(max(1, self.settings.job_worker_concurrency)):
            thread = threading.Thread(
                target=self._run,
                name=f"research-macha-job-worker-{index}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=self.settings.job_worker_poll_seconds + 1)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                recover_interrupted_jobs(
                    self.session_factory,
                    worker_id=self.worker_id,
                    settings=self.settings,
                )
                job_id = claim_next_job(
                    self.session_factory,
                    worker_id=self.worker_id,
                    settings=self.settings,
                )
                if job_id is not None:
                    dispatch_job(
                        job_id,
                        worker_id=self.worker_id,
                        session_factory=self.session_factory,
                        settings=self.settings,
                    )
                    continue
            except Exception:  # noqa: BLE001 - transient database failures must not kill the worker
                logger.exception("Job worker polling failed")
            self._stop.wait(self.settings.job_worker_poll_seconds)
