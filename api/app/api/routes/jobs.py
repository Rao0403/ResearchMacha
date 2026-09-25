from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.paper import Job
from app.schemas.paper import JobRead
from app.services.research import retry_job

router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(get_db)) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/retry", response_model=JobRead)
def retry_failed_job(job_id: str, db: Session = Depends(get_db)) -> Job:
    return retry_job(db, job_id)
