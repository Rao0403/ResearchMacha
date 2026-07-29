from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.jobs import router as jobs_router
from app.api.routes.papers import router as papers_router
from app.api.routes.research import router as research_router

api_router = APIRouter(prefix="/api")
api_router.include_router(research_router, tags=["research"])
api_router.include_router(papers_router, tags=["papers"])
api_router.include_router(jobs_router, tags=["jobs"])
