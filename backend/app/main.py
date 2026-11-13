from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.services.storage import ensure_storage_dirs
from app.services.jobs import JobWorker
from app.ai import validate_ai_configuration

settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI):
    validate_ai_configuration()
    ensure_storage_dirs()
    worker = None
    if settings.job_worker_enabled:
        from app.core.database import SessionLocal
        from app.models.paper import ChatMessage
        with SessionLocal() as db:
            db.query(ChatMessage).filter(ChatMessage.status == "pending").update({
                "status": "failed", "error_message": "Backend restarted before this answer finished. Retry this question."
            })
            db.commit()
        worker = JobWorker(settings=settings)
        worker.start()
    application.state.job_worker = worker
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()

app = FastAPI(
    title="ResearchMacha API",
    version="0.1.0",
    description="Backend service for paper discovery, analysis, and grounded chat.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_router)
