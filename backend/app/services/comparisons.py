from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai import AIProviderError, EvidenceValidationError, build_extractive_batch, get_ai_provider, validate_batch_output
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.paper import Comparison, ComparisonPaper, Job, Paper
from app.models.states import JobStatus
from app.schemas.paper import JobRead, LibraryPaperRead
from app.services.analysis import begin_job_phase, now
from app.services.research import build_paper_contexts_by_ids


def get_comparison(db: Session, ident: str, *, lock=False) -> Comparison:
    query = db.query(Comparison).filter(Comparison.id == ident).populate_existing()
    if lock: query = query.with_for_update()
    row = query.one_or_none()
    if row is None: raise HTTPException(404, "Comparison not found")
    return row


def validate_papers(db: Session, paper_ids: list[str]) -> None:
    if not 2 <= len(paper_ids) <= get_settings().max_batch_files or len(set(paper_ids)) != len(paper_ids):
        raise HTTPException(422, "Select 2 to 10 distinct papers")
    found = db.query(Paper).filter(Paper.id.in_(paper_ids)).with_for_update().all()
    if len(found) != len(paper_ids): raise HTTPException(404, "A selected paper no longer exists")


def paper_ids(row: Comparison) -> list[str]:
    return [link.paper_id for link in sorted(row.papers, key=lambda link: link.position)]


def create_comparison(db: Session, *, name: str, goal: str, ids: list[str], request_id: str) -> Comparison:
    if not name.strip() or len(goal.strip()) < 3:
        raise HTTPException(422, "Provide a name and comparison goal")
    existing = db.query(Comparison).filter_by(creation_key=request_id).one_or_none()
    if existing:
        if existing.goal != goal or paper_ids(existing) != ids:
            raise HTTPException(409, "Request ID already belongs to another comparison")
        generate_comparison(db, existing.id, request_id, existing.version)
        return get_comparison(db, existing.id)
    validate_papers(db, ids)
    row = Comparison(creation_key=request_id, name=name, goal=goal)
    db.add(row); db.flush()
    row.papers = [ComparisonPaper(paper_id=ident, position=position) for position, ident in enumerate(ids)]
    try: db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(Comparison).filter_by(creation_key=request_id).one_or_none()
        if existing is None: raise
        return create_comparison(db, name=name, goal=goal, ids=ids, request_id=request_id)
    generate_comparison(db, row.id, request_id, row.version)
    return get_comparison(db, row.id)


def update_comparison(db: Session, ident: str, *, name: str, goal: str, ids: list[str], version: int) -> Comparison:
    if not name.strip() or len(goal.strip()) < 3:
        raise HTTPException(422, "Provide a name and comparison goal")
    row = get_comparison(db, ident, lock=True)
    if row.version != version: raise HTTPException(409, "Comparison changed. Reload before editing.")
    validate_papers(db, ids)
    content_changed = goal != row.goal or ids != paper_ids(row)
    row.name = name
    row.version += 1
    if content_changed:
        row.goal = goal
        row.generation += 1
        row.status = "draft"
        row.error_message = None
        # Running calls may finish, but generation checks prevent their results from replacing this edit.
        for job in row.jobs:
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job.finished_at = now()
        row.papers.clear()
        db.flush()
        row.papers = [ComparisonPaper(paper_id=pid, position=i) for i, pid in enumerate(ids)]
    db.commit()
    return get_comparison(db, ident)


def generate_comparison(db: Session, ident: str, request_id: str, version: int) -> Job:
    row = get_comparison(db, ident, lock=True)
    key = f"comparison:{ident}:{request_id}"
    existing = db.query(Job).filter_by(idempotency_key=key).one_or_none()
    if existing: return existing
    if row.version != version: raise HTTPException(409, "Comparison changed. Reload before generating.")
    active = db.query(Job).filter(Job.comparison_id == ident, Job.requested_generation == row.generation,
        Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING])).first()
    if active: return active
    row.generation += 1
    row.status = "waiting_for_papers"
    row.error_message = None
    job = Job(comparison_id=ident, job_type="comparison", status=JobStatus.QUEUED,
              requested_generation=row.generation, idempotency_key=key,
              payload={"ai_provider":get_settings().ai_provider, "goal":row.goal, "paper_ids":paper_ids(row)})
    db.add(job); db.commit()
    reconcile_comparison(db, ident)
    return job


def reconcile_comparison(db: Session, ident: str) -> None:
    row = get_comparison(db, ident, lock=True)
    job = db.query(Job).filter_by(comparison_id=ident, requested_generation=row.generation).order_by(Job.created_at.desc()).first()
    if job is not None and job.status == JobStatus.FAILED:
        row.status="failed"
        row.error_message=job.error_message
        db.commit()
        return
    if job is None or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
        return
    if job.status == JobStatus.RUNNING: return
    papers = [link.paper for link in row.papers]
    row.status = ("blocked" if any(p.status == "failed" for p in papers) else
                  "queued" if papers and all(p.status in {"ready","degraded"} for p in papers) else "waiting_for_papers")
    row.updated_at = now()
    db.commit()


def serialize_comparison(db: Session, row: Comparison, *, include_result=True) -> dict:
    sources = {p["paper_id"]:p.get("analysis_generation") for p in (row.evidence_json or {}).get("papers",[])}
    blockers=[]
    for link in row.papers:
        if link.paper.status == "failed":
            job=db.query(Job).filter_by(paper_id=link.paper_id,job_type="analysis").order_by(Job.created_at.desc()).first()
            blockers.append({"paper_id":link.paper_id,"title":link.paper.title,"job_id":job.id if job else None,
                             "error":job.error_message if job else link.paper.analysis_warning})
    return {"id":row.id,"name":row.name,"goal":row.goal,"status":row.status,"version":row.version,
            "generation":row.generation,"result_generation":row.result_generation,
            "result_json":row.result_json if include_result else None,
            "outdated":bool(row.result_json and (row.result_generation != row.generation or any(sources.get(l.paper_id) != l.paper.analysis_generation for l in row.papers))),
            "error_message":row.error_message,"created_at":row.created_at,"updated_at":row.updated_at,
            "papers":[LibraryPaperRead.model_validate(l.paper).model_dump() for l in row.papers],
            "blocking_items":blockers,
            "jobs":[JobRead.model_validate(j).model_dump() for j in sorted(row.jobs,key=lambda j:j.created_at,reverse=True)[:5]]}


def process_comparison_job(job_id: str, *, heartbeat: Callable[[], bool] | None=None, session_factory=SessionLocal) -> None:
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != JobStatus.RUNNING: return
        row = get_comparison(db, job.comparison_id, lock=True)
        generation = job.requested_generation
        if row.generation != generation:
            job.status=JobStatus.CANCELLED; job.finished_at=now(); db.commit(); return
        if row.result_generation == generation and row.result_json:
            job.status=JobStatus.COMPLETED;job.finished_at=now();job.lease_expires_at=None;db.commit();return
        row.status="running"
        db.commit()
        if heartbeat and not heartbeat(): raise RuntimeError("Comparison lease was lost")
        snapshot=(job.payload or {}).get("evidence_snapshot")
        if snapshot is None:
            begin_job_phase(db,job,"retrieving_evidence")
            contexts=build_paper_contexts_by_ids(db,job.payload["paper_ids"],query=job.payload["goal"])
            by_id={context["paper_id"]:context for context in contexts}
            if set(by_id) != set(job.payload["paper_ids"]): raise RuntimeError("Required comparison evidence is unavailable")
            snapshot=[]
            for pid in job.payload["paper_ids"]:
                paper=db.get(Paper,pid)
                if paper.status not in {"ready","degraded"}: raise RuntimeError("Paper analysis changed before comparison generation")
                snapshot.append({**by_id[pid],"chunks":by_id[pid]["chunks"][:4],"analysis_generation":paper.analysis_generation,
                                 "authors":paper.authors,"year":paper.year,"arxiv_id":paper.arxiv_id,"analysis_mode":paper.analysis_mode})
            job.payload={**job.payload,"evidence_snapshot":snapshot}
            db.commit()
        if heartbeat and not heartbeat(): raise RuntimeError("Comparison lease was lost")
        begin_job_phase(db,job,"generating_comparison")
        try:
            output=get_ai_provider().summarize_batch(job.payload["goal"],snapshot)
            validate_batch_output(output,{p["paper_id"] for p in snapshot})
        except (AIProviderError,EvidenceValidationError) as error:
            output=build_extractive_batch(job.payload["goal"],snapshot,str(error))
        if heartbeat and not heartbeat(): raise RuntimeError("Comparison lease was lost")
        row=get_comparison(db,row.id,lock=True)
        if row.generation != generation:
            job.status=JobStatus.CANCELLED
        else:
            warnings=list(output.warnings)
            if any(p["analysis_mode"] != "ai" for p in snapshot): warnings.append("One or more source analyses have limitations.")
            output.warnings=warnings
            if row.result_json and output.generation_mode != "ai":
                row.error_message="Replacement generation was unavailable; previous result retained."
            else:
                row.result_json=output.model_dump()
                row.evidence_json={"papers":snapshot}
                row.result_generation=generation
            row.status="done" if output.generation_mode=="ai" and not warnings else "degraded"
            job.status=JobStatus.COMPLETED if row.status=="done" else JobStatus.COMPLETED_WITH_WARNINGS
            job.warning_message="; ".join(warnings) or row.error_message
        job.finished_at=now();job.lease_expires_at=None
        db.commit()
