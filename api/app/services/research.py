from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session, selectinload

from app.ai import (
    BatchSummary,
    EvidenceRegistry,
    MockProvider,
    ResearchBrief,
    get_ai_provider,
    validate_batch_output,
    validate_brief_evidence,
    validate_candidate_selection,
)
from app.core.database import SessionLocal
from app.models.paper import AgentRun, AgentStep, Job, Paper, PaperChunk, PaperSummary, ResearchCandidate, ResearchProject, ResearchProjectPaper
from app.models.states import JobStatus
from app.schemas.memory import ResearchMemoryRead
from app.schemas.paper import LibraryPaperRead
from app.schemas.research import AgentRunRead, AgentStepRead, ResearchCandidateRead, ResearchProjectRead
from app.services.agent_trace import (
    complete_agent_step,
    create_agent_run,
    fail_agent_step,
    latest_agent_run,
    set_agent_run_status,
    start_agent_step,
    summarize_candidates_for_trace,
)
from app.services.analysis import enqueue_analysis_job, now
from app.services.arxiv import ArxivEntry, fetch_arxiv_entry, search_arxiv
from app.services.fallbacks import record_fallback
from app.services.memory import create_memory, latest_memories, memory_payload, retrieve_memories
from app.services.papers import create_or_update_paper_from_arxiv
from app.services.vector_store import get_vector_store
from app.services.retrieval import retrieve_paper_chunks

DEMO_QUESTION = "How can retrieval augmented generation improve factuality in domain-specific question answering?"
DEMO_ARXIV_IDS = ["2005.11401", "2310.11511", "2403.10131"]


class StaleSynthesisJob(RuntimeError):
    pass


def create_project(db: Session, question: str) -> ResearchProject:
    project = ResearchProject(question=question, status="draft")
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session) -> list[ResearchProject]:
    return db.query(ResearchProject).order_by(ResearchProject.updated_at.desc()).all()


def get_project_or_404(db: Session, project_id: str) -> ResearchProject:
    project = (
        db.query(ResearchProject)
        .populate_existing()
        .options(
            selectinload(ResearchProject.candidates),
            selectinload(ResearchProject.papers).selectinload(ResearchProjectPaper.paper),
            selectinload(ResearchProject.agent_runs).selectinload(AgentRun.steps),
            selectinload(ResearchProject.jobs),
        )
        .filter(ResearchProject.id == project_id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Research project not found")
    return project


def serialize_project(project: ResearchProject) -> ResearchProjectRead:
    papers = [LibraryPaperRead.model_validate(link.paper) for link in project.papers if link.paper is not None]
    latest_run = sorted(project.agent_runs, key=lambda run: run.created_at, reverse=True)[0] if project.agent_runs else None
    db = object_session(project)
    if db is not None:
        memories = latest_memories(db, project_id=project.id, limit=8)
    else:
        memories = sorted(project.memories, key=lambda memory: memory.updated_at, reverse=True)[:8]
    agent_run = None
    if latest_run is not None:
        agent_run = AgentRunRead(
            id=latest_run.id,
            project_id=latest_run.project_id,
            status=latest_run.status,
            goal=latest_run.goal,
            error_message=latest_run.error_message,
            created_at=latest_run.created_at,
            updated_at=latest_run.updated_at,
            started_at=latest_run.started_at,
            finished_at=latest_run.finished_at,
            steps=[AgentStepRead.model_validate(step) for step in sorted(latest_run.steps, key=lambda item: item.position)],
        )
    return ResearchProjectRead(
        id=project.id,
        question=project.question,
        status=project.status,
        generated_queries=project.generated_queries or [],
        inclusion_criteria=project.inclusion_criteria or [],
        synthesis_json=project.synthesis_json,
        synthesis_generation=project.synthesis_generation,
        created_at=project.created_at,
        updated_at=project.updated_at,
        candidates=[ResearchCandidateRead.model_validate(candidate) for candidate in sorted(project.candidates, key=lambda item: item.score, reverse=True)],
        papers=papers,
        agent_run=agent_run,
        memory_signals=[ResearchMemoryRead.model_validate(memory) for memory in memories],
        recent_jobs=sorted(project.jobs, key=lambda job: job.created_at, reverse=True)[:20],
        blocking_items=project_blocking_items(project),
    )


def project_blocking_items(project: ResearchProject) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    candidates = {candidate.id: candidate for candidate in project.candidates}
    linked_papers = {link.paper_id: link.paper for link in project.papers}
    for job in sorted(project.jobs, key=lambda item: item.created_at):
        if job.status != JobStatus.FAILED:
            continue
        if job.job_type == "import" and job.candidate_id in candidates:
            candidate = candidates[job.candidate_id]
            blockers.append(
                {
                    "target_type": "candidate",
                    "target_id": candidate.id,
                    "title": candidate.title,
                    "job_id": job.id,
                    "error": job.error_message,
                }
            )
        elif job.job_type == "analysis" and job.paper_id in linked_papers:
            paper = linked_papers[job.paper_id]
            blockers.append(
                {
                    "target_type": "paper",
                    "target_id": job.paper_id,
                    "title": paper.title if paper else "Paper",
                    "job_id": job.id,
                    "error": job.error_message,
                }
            )
        elif job.job_type == "synthesis" and job.requested_generation == project.synthesis_generation:
            blockers.append(
                {
                    "target_type": "synthesis",
                    "target_id": project.id,
                    "title": "Research synthesis",
                    "job_id": job.id,
                    "error": job.error_message,
                }
            )
    for paper_id, paper in linked_papers.items():
        if paper is not None and paper.status == "failed" and not any(
            blocker["target_type"] == "paper" and blocker["target_id"] == paper_id for blocker in blockers
        ):
            blockers.append(
                {
                    "target_type": "paper",
                    "target_id": paper_id,
                    "title": paper.title,
                    "job_id": None,
                    "error": paper.analysis_warning or "Paper analysis failed.",
                }
            )
    return blockers


def start_research_workflow(db: Session, question: str) -> ResearchProject:
    project = create_project(db, question)
    agent_run = create_agent_run(db, project.id, question)
    try:
        project = plan_project(db, project.id, agent_run)
        project = discover_candidates(db, project.id, agent_run=agent_run)
        project = select_recommended_candidates(db, project.id, agent_run)
        set_agent_run_status(db, agent_run, project.status)
        return project
    except Exception as exc:
        set_agent_run_status(db, agent_run, "failed", str(exc))
        raise


def select_recommended_candidates(db: Session, project_id: str, agent_run: AgentRun | None = None) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    candidates = (
        db.query(ResearchCandidate)
        .filter(ResearchCandidate.project_id == project_id)
        .order_by(ResearchCandidate.score.desc())
        .all()
    )
    memory_signals = retrieve_memories(db, project.question, limit=6)
    memory_payloads = [memory_payload(memory) for memory in memory_signals]
    step = start_agent_step(
        db,
        agent_run,
        "select_candidates",
        {
            "candidate_count": len(candidates),
            "question": project.question,
            "memory_count": len(memory_payloads),
        },
    )
    if not candidates:
        project.status = "no_candidates"
        db.add(project)
        db.commit()
        complete_agent_step(db, step, {"selected_count": 0, "status": project.status})
        return get_project_or_404(db, project_id)

    candidate_payloads = apply_memory_bias([candidate_to_payload(candidate) for candidate in candidates], memory_payloads)

    try:
        selection = get_ai_provider().select_relevant_candidates(project.question, candidate_payloads, memory_payloads)
        validate_candidate_selection(selection, {candidate["arxiv_id"] for candidate in candidate_payloads})
        selected_ids = {choice.arxiv_id for choice in selection.selected}
        rationales = {choice.arxiv_id: choice.rationale for choice in selection.selected}
    except Exception as exc:
        record_fallback("research.select_candidates", "top_3_by_score", str(exc), {"candidate_count": len(candidates)})
        selected_ids = fallback_selected_arxiv_ids(candidate_payloads)
        rationales = {arxiv_id: "Selected by memory-adjusted deterministic ranking." for arxiv_id in selected_ids}

    if not selected_ids:
        record_fallback("research.select_candidates", "top_3_by_score", "LLM candidate selection returned no selected papers.", {"candidate_count": len(candidates)})
        selected_ids = fallback_selected_arxiv_ids(candidate_payloads)

    for candidate in candidates:
        candidate.selected = candidate.arxiv_id in selected_ids
        if candidate.selected and candidate.arxiv_id in rationales:
            candidate.rationale = rationales[candidate.arxiv_id]
        db.add(candidate)

    project.status = "awaiting_approval"
    db.add(project)
    db.commit()
    complete_agent_step(
        db,
        step,
        {
            "selected_count": sum(1 for candidate in candidates if candidate.selected),
            "selected_arxiv_ids": [candidate.arxiv_id for candidate in candidates if candidate.selected],
            "top_candidates": summarize_candidates_for_trace(candidates),
            "memory_count": len(memory_payloads),
            "memory_adjusted_candidates": [
                {
                    "arxiv_id": candidate["arxiv_id"],
                    "base_score": candidate.get("base_score", candidate.get("score")),
                    "score": candidate.get("score"),
                    "memory_signal": candidate.get("memory_signal"),
                }
                for candidate in candidate_payloads
                if candidate.get("memory_signal")
            ],
            "status": project.status,
        },
    )
    return get_project_or_404(db, project_id)


def plan_project(db: Session, project_id: str, agent_run: AgentRun | None = None) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    step = start_agent_step(db, agent_run, "plan_search", {"question": project.question})
    try:
        plan = get_ai_provider().plan_research(project.question)
    except Exception as exc:
        fail_agent_step(db, step, exc)
        raise
    project.generated_queries = plan.search_queries
    project.inclusion_criteria = plan.inclusion_criteria
    project.status = "planned"
    db.add(project)
    db.commit()
    complete_agent_step(
        db,
        step,
        {
            "search_queries": plan.search_queries,
            "inclusion_criteria": plan.inclusion_criteria,
            "status": project.status,
        },
    )
    return get_project_or_404(db, project.id)


def discover_candidates(db: Session, project_id: str, max_per_query: int = 6, agent_run: AgentRun | None = None) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    if not project.generated_queries:
        project = plan_project(db, project_id, agent_run)

    seen = {candidate.arxiv_id: candidate for candidate in project.candidates}
    search_step = start_agent_step(
        db,
        agent_run,
        "search_arxiv",
        {"queries": project.generated_queries[:4], "max_per_query": max_per_query},
    )
    rank_step = None
    query_counts: list[dict[str, Any]] = []
    try:
        for query in project.generated_queries[:4]:
            entries = search_arxiv(query, max_results=max_per_query)
            query_counts.append({"query": query, "result_count": len(entries)})
            for entry in entries:
                score, rationale = score_candidate(project.question, entry)
                candidate = seen.get(entry.arxiv_id)
                if candidate is None:
                    candidate = ResearchCandidate(
                        project_id=project.id,
                        arxiv_id=entry.arxiv_id,
                        title=entry.title,
                        authors=entry.authors,
                        abstract=entry.abstract,
                        year=entry.year,
                        pdf_url=entry.pdf_url,
                        entry_url=entry.entry_url,
                        score=score,
                        rationale=rationale,
                        selected=False,
                    )
                    seen[entry.arxiv_id] = candidate
                else:
                    previous_score = candidate.score
                    candidate.score = max(candidate.score, score)
                    candidate.rationale = rationale if score >= previous_score else candidate.rationale
                db.add(candidate)
        complete_agent_step(
            db,
            search_step,
            {
                "queries": query_counts,
                "unique_candidate_count": len(seen),
            },
        )
        rank_step = start_agent_step(
            db,
            agent_run,
            "rank_candidates",
            {"candidate_count": len(seen), "ranking_method": "keyword overlap + recency boost"},
        )
    except Exception as exc:
        fail_agent_step(db, search_step, exc)
        raise

    project.status = "discovered"
    db.add(project)
    db.commit()
    project = get_project_or_404(db, project.id)
    complete_agent_step(
        db,
        rank_step,
        {
            "candidate_count": len(project.candidates),
            "top_candidates": summarize_candidates_for_trace(
                sorted(project.candidates, key=lambda candidate: candidate.score, reverse=True)
            ),
            "status": project.status,
        },
    )
    return project


def import_selected_candidates(
    db: Session,
    project_id: str,
    candidate_ids: list[str],
    agent_run: AgentRun | None = None,
) -> ResearchProject:
    project = db.execute(
        select(ResearchProject).where(ResearchProject.id == project_id).with_for_update()
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Research project not found")
    project_candidates = db.query(ResearchCandidate).filter(
        ResearchCandidate.project_id == project_id
    ).all()
    if not candidate_ids:
        candidate_ids = [candidate.id for candidate in project_candidates if candidate.selected]
    candidate_ids = list(dict.fromkeys(candidate_ids))
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="Select at least one candidate to import")

    candidates_by_id = {candidate.id: candidate for candidate in project_candidates}
    unknown_ids = [candidate_id for candidate_id in candidate_ids if candidate_id not in candidates_by_id]
    if unknown_ids:
        raise HTTPException(status_code=400, detail={"message": "Candidates do not belong to this project", "candidate_ids": unknown_ids})
    candidates = [candidates_by_id[candidate_id] for candidate_id in candidate_ids]
    existing_approved_ids = {
        candidate_id
        for (candidate_id,) in db.query(Job.candidate_id)
        .filter(Job.project_id == project_id, Job.job_type == "import", Job.candidate_id.is_not(None))
        .all()
    }
    if len(existing_approved_ids | set(candidate_ids)) > 5:
        raise HTTPException(status_code=400, detail="A project can have at most five approved candidates")

    for candidate in candidates:
        candidate.selected = True
        key = f"import:{project_id}:{candidate.id}"
        job = db.query(Job).filter(Job.idempotency_key == key).one_or_none()
        if job is None:
            job = Job(
                project_id=project_id,
                candidate_id=candidate.id,
                job_type="import",
                status=JobStatus.QUEUED,
                idempotency_key=key,
                payload={"arxiv_id": candidate.arxiv_id},
            )
            db.add(job)

    project.status = "importing"
    db.add(project)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    reconcile_workflow_trace_steps(db, project_id, agent_run)
    return get_project_or_404(db, project_id)


def approve_research_workflow(
    db: Session,
    project_id: str,
    candidate_ids: list[str],
) -> ResearchProject:
    agent_run = latest_agent_run(db, project_id) or create_agent_run(db, project_id, f"Approve papers for project {project_id}")
    existing_project = get_project_or_404(db, project_id)
    effective_candidate_ids = candidate_ids or [candidate.id for candidate in existing_project.candidates if candidate.selected]
    project = import_selected_candidates(db, project_id, candidate_ids, agent_run)
    remember_candidate_decisions(db, project_id, effective_candidate_ids)
    set_agent_run_status(db, agent_run, project.status)
    return get_project_or_404(db, project_id)


def process_import_job(
    job_id: str,
    *,
    heartbeat: Callable[[], bool] | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> None:
    db = session_factory()
    try:
        job = db.get(Job, job_id)
        if job is None or job.status != JobStatus.RUNNING:
            return
        candidate = db.get(ResearchCandidate, job.candidate_id)
        project = db.get(ResearchProject, job.project_id)
        if candidate is None or project is None:
            raise RuntimeError("Import target no longer exists")

        entry = fetch_arxiv_entry(candidate.arxiv_id)
        if heartbeat:
            heartbeat()
        paper, _ = create_or_update_paper_from_arxiv(db, entry)
        link = db.query(ResearchProjectPaper).filter(
            ResearchProjectPaper.project_id == project.id,
            ResearchProjectPaper.paper_id == paper.id,
        ).one_or_none()
        if link is None:
            db.add(ResearchProjectPaper(project_id=project.id, paper_id=paper.id, role="evidence"))
        candidate.selected = True
        job.paper_id = paper.id
        db.add_all([candidate, job])
        db.commit()
        if heartbeat:
            heartbeat()
        analysis_job = enqueue_analysis_job(db, paper.id, auto_reset=True)
        if analysis_job.project_id is None:
            analysis_job.project_id = project.id
            analysis_job.candidate_id = candidate.id
            db.add(analysis_job)
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.COMPLETED
            job.finished_at = now()
            job.lease_expires_at = None
            payload = dict(job.payload or {})
            payload["analysis_job_id"] = analysis_job.id
            job.payload = payload
            db.add(job)
        project = db.get(ResearchProject, project.id)
        if project is not None:
            project.status = "analyzing"
            db.add(project)
        db.commit()
        reconcile_workflow_trace_steps(db, project.id, latest_agent_run(db, project.id))
    finally:
        db.close()


def retry_job(db: Session, job_id: str) -> Job:
    job = db.execute(select(Job).where(Job.id == job_id).with_for_update()).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
        return job
    if job.status not in {JobStatus.FAILED, JobStatus.COMPLETED_WITH_WARNINGS}:
        raise HTTPException(status_code=409, detail="Only failed or warning-completed jobs can be retried")
    if job.job_type == "import" and (
        job.project_id is None
        or job.candidate_id is None
        or db.get(ResearchProject, job.project_id) is None
        or db.get(ResearchCandidate, job.candidate_id) is None
    ):
        raise HTTPException(status_code=409, detail="Import target no longer exists")
    if job.job_type == "analysis" and (job.paper_id is None or db.get(Paper, job.paper_id) is None):
        raise HTTPException(status_code=409, detail="Analysis target no longer exists")
    if job.job_type == "synthesis" and (job.project_id is None or db.get(ResearchProject, job.project_id) is None):
        raise HTTPException(status_code=409, detail="Synthesis target no longer exists")
    if job.job_type not in {"import", "analysis", "synthesis"}:
        raise HTTPException(status_code=409, detail="This job type cannot be retried")
    if job.job_type == "synthesis":
        project = db.execute(
            select(ResearchProject).where(ResearchProject.id == job.project_id).with_for_update()
        ).scalar_one()
        project.synthesis_generation += 1
        db.add(project)
        db.commit()
        return _create_synthesis_job(db, project)
    job.status = JobStatus.QUEUED
    job.error_message = None
    job.warning_message = None
    job.worker_id = None
    job.claimed_at = None
    job.lease_expires_at = None
    job.started_at = None
    job.finished_at = None
    job.attempt_count = 0
    db.add(job)
    db.commit()
    db.refresh(job)
    if job.project_id:
        reconcile_workflow_trace_steps(db, job.project_id, latest_agent_run(db, job.project_id))
        reconcile_project(db, job.project_id)
    return job


def _supersede_synthesis(db: Session, project: ResearchProject) -> None:
    project.synthesis_generation += 1
    synthesis_jobs = db.query(Job).filter(
        Job.project_id == project.id,
        Job.job_type == "synthesis",
        Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
    ).all()
    for job in synthesis_jobs:
        job.status = JobStatus.CANCELLED
        job.warning_message = "Cancelled because the project evidence set changed."
        job.finished_at = now()
        job.lease_expires_at = None
        db.add(job)
    db.add(project)


def exclude_candidate(db: Session, project_id: str, candidate_id: str) -> ResearchProject:
    project = db.execute(
        select(ResearchProject).where(ResearchProject.id == project_id).with_for_update()
    ).scalar_one_or_none()
    candidate = db.query(ResearchCandidate).filter(
        ResearchCandidate.id == candidate_id,
        ResearchCandidate.project_id == project_id,
    ).one_or_none()
    if project is None or candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found in this project")
    jobs = db.query(Job).filter(Job.project_id == project_id, Job.candidate_id == candidate_id).all()
    paper_ids = {job.paper_id for job in jobs if job.paper_id}
    for job in jobs:
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            job.status = JobStatus.CANCELLED
            job.warning_message = "Candidate was excluded from the project."
            job.finished_at = now()
            job.lease_expires_at = None
        payload = dict(job.payload or {})
        payload.update({"excluded_candidate_id": candidate.id, "excluded_candidate_title": candidate.title})
        job.payload = payload
        job.candidate_id = None
        db.add(job)
    if paper_ids:
        db.query(ResearchProjectPaper).filter(
            ResearchProjectPaper.project_id == project_id,
            ResearchProjectPaper.paper_id.in_(paper_ids),
        ).delete(synchronize_session=False)
        analysis_jobs = db.query(Job).filter(
            Job.project_id == project_id,
            Job.paper_id.in_(paper_ids),
            Job.job_type == "analysis",
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        ).all()
        for analysis_job in analysis_jobs:
            analysis_job.status = JobStatus.CANCELLED
            analysis_job.warning_message = "Paper was excluded with its candidate."
            analysis_job.finished_at = now()
            analysis_job.lease_expires_at = None
            db.add(analysis_job)
    db.delete(candidate)
    _supersede_synthesis(db, project)
    db.commit()
    db.expunge_all()
    return reconcile_project(db, project_id)


def exclude_project_paper(db: Session, project_id: str, paper_id: str) -> ResearchProject:
    project = db.execute(
        select(ResearchProject).where(ResearchProject.id == project_id).with_for_update()
    ).scalar_one_or_none()
    link = db.query(ResearchProjectPaper).filter(
        ResearchProjectPaper.project_id == project_id,
        ResearchProjectPaper.paper_id == paper_id,
    ).one_or_none()
    if project is None or link is None:
        raise HTTPException(status_code=404, detail="Paper is not part of this project")
    jobs = db.query(Job).filter(
        Job.project_id == project_id,
        Job.paper_id == paper_id,
        Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
    ).all()
    for job in jobs:
        job.status = JobStatus.CANCELLED
        job.warning_message = "Paper was excluded from the project."
        job.finished_at = now()
        job.lease_expires_at = None
        db.add(job)
    db.delete(link)
    _supersede_synthesis(db, project)
    db.commit()
    db.expunge_all()
    return reconcile_project(db, project_id)


def reconcile_workflow_trace_steps(
    db: Session,
    project_id: str,
    agent_run: AgentRun | None,
) -> None:
    if agent_run is None:
        return
    definitions = (
        ("import_papers", ["import"]),
        ("analyze_papers", ["analysis"]),
    )
    for tool_name, job_types in definitions:
        jobs = db.query(Job).filter(Job.project_id == project_id, Job.job_type.in_(job_types)).order_by(Job.created_at).all()
        if not jobs:
            continue
        step = db.query(AgentStep).filter(
            AgentStep.run_id == agent_run.id,
            AgentStep.tool_name == tool_name,
        ).order_by(AgentStep.position.asc()).first()
        if step is None:
            position = (db.query(func.max(AgentStep.position)).filter(AgentStep.run_id == agent_run.id).scalar() or 0) + 1
            step = AgentStep(
                run_id=agent_run.id,
                project_id=project_id,
                position=position,
                tool_name=tool_name,
                status="running",
                input_json={"job_ids": [job.id for job in jobs]},
            )
        statuses = {job.status for job in jobs}
        if JobStatus.FAILED in statuses:
            step.status = "failed"
            step.error_message = "One or more durable jobs failed."
            step.finished_at = now()
        elif statuses <= {JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_WARNINGS, JobStatus.CANCELLED}:
            step.status = "completed"
            step.finished_at = now()
        else:
            step.status = "running"
            step.finished_at = None
            step.error_message = None
        step.output_json = {
            "jobs": [
                {"job_id": job.id, "target_id": job.paper_id or job.candidate_id, "status": job.status}
                for job in jobs
            ]
        }
        db.add(step)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()


def _create_synthesis_job(db: Session, project: ResearchProject) -> Job:
    if project.synthesis_generation == 0:
        project.synthesis_generation = 1
    key = f"synthesis:{project.id}:{project.synthesis_generation}"
    existing = db.query(Job).filter(Job.idempotency_key == key).one_or_none()
    if existing is not None:
        return existing
    job = Job(
        project_id=project.id,
        job_type="synthesis",
        status=JobStatus.QUEUED,
        idempotency_key=key,
        requested_generation=project.synthesis_generation,
    )
    project.status = "synthesis_queued"
    db.add_all([project, job])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(Job).filter(Job.idempotency_key == key).one_or_none()
        if existing is None:
            raise
        return existing
    db.refresh(job)
    return job


def enqueue_synthesis_job(db: Session, project_id: str) -> Job:
    project = reconcile_project(db, project_id)
    active = db.query(Job).filter(
        Job.project_id == project_id,
        Job.job_type == "synthesis",
        Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
    ).order_by(Job.created_at.desc()).first()
    if active is not None:
        return active
    if project.status in {"importing", "analyzing", "blocked", "awaiting_approval"}:
        raise HTTPException(status_code=409, detail="Synthesis cannot start until all remaining papers are ready")
    current = db.query(Job).filter(
        Job.project_id == project_id,
        Job.job_type == "synthesis",
        Job.requested_generation == project.synthesis_generation,
    ).one_or_none()
    if current is not None:
        project.synthesis_generation += 1
    elif project.synthesis_generation == 0:
        project.synthesis_generation = 1
    return _create_synthesis_job(db, project)


def process_synthesis_job(
    job_id: str,
    *,
    heartbeat: Callable[[], bool] | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> None:
    db = session_factory()
    try:
        job = db.get(Job, job_id)
        if job is None or job.status != JobStatus.RUNNING or job.project_id is None:
            return
        project = db.get(ResearchProject, job.project_id)
        if project is None:
            raise RuntimeError("Synthesis target no longer exists")
        if job.requested_generation != project.synthesis_generation:
            job.status = JobStatus.CANCELLED
            job.warning_message = "Superseded by a newer synthesis generation."
            job.finished_at = now()
            job.lease_expires_at = None
            db.add(job)
            db.commit()
            return
        project.status = "synthesizing"
        db.add(project)
        db.commit()
        if heartbeat:
            heartbeat()
        try:
            synthesize_project(db, project.id, expected_generation=job.requested_generation)
        except StaleSynthesisJob as exc:
            db.rollback()
            job = db.get(Job, job_id)
            if job is not None:
                job.status = JobStatus.CANCELLED
                job.warning_message = str(exc)
                job.finished_at = now()
                job.lease_expires_at = None
                db.add(job)
                db.commit()
            return
        if heartbeat:
            heartbeat()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.COMPLETED
            job.finished_at = now()
            job.lease_expires_at = None
            db.add(job)
            db.commit()
    finally:
        db.close()


def get_workflow_status(db: Session, project_id: str) -> ResearchProject:
    return get_project_or_404(db, project_id)


def maybe_synthesize_ready_project(db: Session, project: ResearchProject) -> ResearchProject:
    return reconcile_project(db, project.id)


def reconcile_project(
    db: Session,
    project_id: str,
    *,
    enqueue_synthesis: bool = True,
) -> ResearchProject:
    project = db.execute(
        select(ResearchProject).where(ResearchProject.id == project_id).with_for_update()
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Research project not found")
    import_jobs = db.query(Job).filter(
        Job.project_id == project_id,
        Job.job_type == "import",
        Job.candidate_id.is_not(None),
    ).all()
    links = db.query(ResearchProjectPaper).filter(ResearchProjectPaper.project_id == project_id).all()
    papers = [db.get(Paper, link.paper_id) for link in links]
    papers = [paper for paper in papers if paper is not None]
    analysis_jobs = db.query(Job).filter(
        Job.project_id == project_id,
        Job.job_type == "analysis",
        Job.paper_id.in_([paper.id for paper in papers]) if papers else Job.id.is_(None),
    ).all()

    if not import_jobs and not papers:
        project.status = "awaiting_approval"
    elif (
        any(job.status == JobStatus.FAILED for job in import_jobs)
        or any(job.status == JobStatus.FAILED for job in analysis_jobs)
        or any(paper.status == "failed" for paper in papers)
    ):
        project.status = "blocked"
    elif any(job.status in {JobStatus.QUEUED, JobStatus.RUNNING} for job in import_jobs):
        project.status = "importing"
    elif not papers:
        project.status = "blocked"
    elif any(job.status in {JobStatus.QUEUED, JobStatus.RUNNING} for job in analysis_jobs) or any(
        paper.status not in {"ready", "degraded"} for paper in papers
    ):
        project.status = "analyzing"
    else:
        current_synthesis = db.query(Job).filter(
            Job.project_id == project_id,
            Job.job_type == "synthesis",
            Job.requested_generation == project.synthesis_generation,
        ).order_by(Job.created_at.desc()).first()
        if current_synthesis is not None and current_synthesis.status == JobStatus.RUNNING:
            project.status = "synthesizing"
        elif current_synthesis is not None and current_synthesis.status == JobStatus.QUEUED:
            project.status = "synthesis_queued"
        elif current_synthesis is not None and current_synthesis.status == JobStatus.FAILED:
            project.status = "failed"
        elif current_synthesis is not None and current_synthesis.status in {
            JobStatus.COMPLETED,
            JobStatus.COMPLETED_WITH_WARNINGS,
        }:
            project.status = "degraded" if any(paper.status == "degraded" for paper in papers) else "done"
        elif enqueue_synthesis:
            db.add(project)
            db.commit()
            _create_synthesis_job(db, project)
            reconcile_workflow_trace_steps(db, project_id, latest_agent_run(db, project_id))
            return get_project_or_404(db, project_id)
        else:
            project.status = "analyzing"
    db.add(project)
    db.commit()
    reconcile_workflow_trace_steps(db, project_id, latest_agent_run(db, project_id))
    return get_project_or_404(db, project_id)


def synthesize_project(
    db: Session,
    project_id: str,
    agent_run: AgentRun | None = None,
    *,
    expected_generation: int | None = None,
) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    if expected_generation is not None and project.synthesis_generation != expected_generation:
        raise StaleSynthesisJob(
            f"Synthesis generation {expected_generation} was superseded by {project.synthesis_generation}."
        )
    agent_run = agent_run or latest_agent_run(db, project_id)
    contexts = build_paper_contexts(project)
    if not contexts:
        raise HTTPException(status_code=400, detail="No analyzed paper evidence is available for synthesis")

    memory_signals = retrieve_memories(db, project.question, limit=8)
    memory_payloads = [memory_payload(memory) for memory in memory_signals]
    step = start_agent_step(
        db,
        agent_run,
        "synthesize_brief",
        {
            "paper_count": len(contexts),
            "chunk_counts": [len(context.get("chunks", [])) for context in contexts],
            "question": project.question,
            "memory_count": len(memory_payloads),
        },
    )
    try:
        brief = get_ai_provider().synthesize_collection(project.question, contexts, memory_payloads)
        ensure_cited_brief(brief)
        validate_brief_evidence(brief, EvidenceRegistry.from_paper_contexts(contexts))
    except Exception as exc:
        fail_agent_step(db, step, exc)
        set_agent_run_status(db, agent_run, "failed", str(exc))
        raise
    project = db.execute(
        select(ResearchProject).where(ResearchProject.id == project_id).with_for_update()
    ).scalar_one()
    if expected_generation is not None and project.synthesis_generation != expected_generation:
        raise StaleSynthesisJob(
            f"Synthesis generation {expected_generation} was superseded by {project.synthesis_generation}."
        )
    project.synthesis_json = brief.model_dump()
    project.status = "done"
    db.add(project)
    db.commit()
    complete_agent_step(
        db,
        step,
        {
            "key_findings": len(brief.key_findings),
            "evidence_rows": len(brief.evidence_table),
            "suggested_experiments": len(brief.suggested_experiments),
            "suggested_research_directions": len(brief.suggested_research_directions),
            "memory_count": len(memory_payloads),
            "status": project.status,
        },
    )
    set_agent_run_status(db, agent_run, project.status)
    return get_project_or_404(db, project.id)


def build_paper_contexts(project: ResearchProject) -> list[dict[str, Any]]:
    contexts = []
    db = object_session(project)
    for link in project.papers:
        paper = link.paper
        if paper is None:
            continue
        summary = paper.summary
        chunks = select_context_chunks(db, paper, project.question, limit=8) if db is not None else first_chunks(paper, limit=8)
        if summary is None and not chunks:
            continue
        contexts.append(
            {
                "paper_id": paper.id,
                "title": paper.title,
                "summary": summarize_existing_paper(summary, paper),
                "chunks": [chunk_to_payload(chunk) for chunk in chunks],
            }
        )
    return contexts


def build_paper_contexts_by_ids(db: Session, paper_ids: list[str], query: str | None = None) -> list[dict[str, Any]]:
    if not paper_ids:
        return []
    papers = (
        db.query(Paper)
        .options(selectinload(Paper.chunks), selectinload(Paper.summary))
        .filter(Paper.id.in_(paper_ids))
        .all()
    )
    contexts = []
    for paper in papers:
        chunks = select_context_chunks(db, paper, query or paper.title, limit=8)
        if paper.summary is None and not chunks:
            continue
        contexts.append(
            {
                "paper_id": paper.id,
                "title": paper.title,
                "summary": summarize_existing_paper(paper.summary, paper),
                "chunks": [chunk_to_payload(chunk) for chunk in chunks],
            }
        )
    return contexts


def summarize_batch_papers(db: Session, paper_ids: list[str], goal: str) -> BatchSummary:
    requested_ids = set(paper_ids)
    ready_ids = {
        paper_id
        for (paper_id,) in db.query(Paper.id)
        .filter(Paper.id.in_(requested_ids), Paper.status.in_(["ready", "degraded"]))
        .all()
    }
    if ready_ids != requested_ids:
        raise HTTPException(status_code=400, detail="Every requested batch paper must be ready or degraded")
    contexts = build_paper_contexts_by_ids(db, list(requested_ids), query=goal)
    if not contexts:
        raise HTTPException(status_code=400, detail="No analyzed paper evidence is available for batch summary")
    try:
        output = get_ai_provider().summarize_batch(goal, contexts)
        validate_batch_output(output, requested_ids)
        return output
    except Exception as exc:
        record_fallback("research.summarize_batch", "mock.summarize_batch", str(exc), {"paper_count": len(contexts)})
        output = MockProvider().summarize_batch(goal, contexts)
        validate_batch_output(output, requested_ids)
        return output


def select_context_chunks(db: Session, paper: Paper, query: str, limit: int) -> list[PaperChunk]:
    return retrieve_paper_chunks(db, paper.id, query, limit=limit)


def first_chunks(paper: Paper, limit: int) -> list[PaperChunk]:
    return sorted(paper.chunks, key=lambda chunk: chunk.chunk_index)[:limit]


def summarize_existing_paper(summary: PaperSummary | None, paper: Paper) -> str:
    if summary is None:
        return paper.abstract or "No paper summary is available yet."
    return " ".join(
        [
            summary.problem_or_hypothesis,
            summary.approach,
            summary.experiments,
            summary.results,
            summary.conclusion,
            summary.limitations_or_notes,
        ]
    )


def chunk_to_payload(chunk: PaperChunk) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "section_label": chunk.section_label,
        "text": chunk.text,
    }


def candidate_to_payload(candidate: ResearchCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "arxiv_id": candidate.arxiv_id,
        "title": candidate.title,
        "authors": candidate.authors,
        "abstract": candidate.abstract,
        "year": candidate.year,
        "score": candidate.score,
        "rationale": candidate.rationale,
    }


def apply_memory_bias(candidates: list[dict[str, Any]], memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positive_terms, negative_terms = memory_term_sets(memories)
    adjusted_candidates = []
    for candidate in candidates:
        adjusted = dict(candidate)
        candidate_terms = keyword_set(f"{candidate.get('title', '')} {candidate.get('abstract', '')}")
        positive_hits = sorted(candidate_terms & positive_terms)
        negative_hits = sorted(candidate_terms & negative_terms)
        score_adjustment = min(12, len(positive_hits) * 3) - min(12, len(negative_hits) * 4)
        adjusted["base_score"] = candidate.get("score", 0)
        adjusted["score"] = max(0, min(100, int(candidate.get("score", 0)) + score_adjustment))
        if score_adjustment:
            signal_parts = []
            if positive_hits:
                signal_parts.append(f"positive: {', '.join(positive_hits[:5])}")
            if negative_hits:
                signal_parts.append(f"negative: {', '.join(negative_hits[:5])}")
            adjusted["memory_signal"] = "; ".join(signal_parts)
        adjusted_candidates.append(adjusted)
    return sorted(adjusted_candidates, key=lambda candidate: candidate.get("score", 0), reverse=True)


def memory_term_sets(memories: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    positive_terms: set[str] = set()
    negative_terms: set[str] = set()
    for memory in memories:
        metadata = memory.get("metadata_json") or {}
        term_source = str(memory.get("text") or "")
        if memory.get("memory_type") == "rejected_paper":
            term_source = f"{metadata.get('title', '')} {metadata.get('rationale', '')}"
        terms = keyword_set(term_source)
        if memory.get("memory_type") == "rejected_paper":
            negative_terms.update(terms)
        else:
            positive_terms.update(terms)
    return positive_terms, negative_terms


def fallback_selected_arxiv_ids(candidates: list[dict[str, Any]]) -> set[str]:
    return {candidate["arxiv_id"] for candidate in sorted(candidates, key=lambda item: item.get("score", 0), reverse=True)[:3]}


def ensure_cited_brief(brief: ResearchBrief) -> None:
    sections = [
        *brief.key_findings,
        *brief.evidence_table,
        *brief.conflicts_or_gaps,
        *brief.suggested_experiments,
        *brief.suggested_research_directions,
    ]
    missing = [finding.label for finding in sections if not finding.citations]
    if missing:
        raise HTTPException(status_code=422, detail=f"Synthesis returned uncited claims: {', '.join(missing)}")


def score_candidate(question: str, entry: ArxivEntry) -> tuple[int, str]:
    question_terms = keyword_set(question)
    document_terms = keyword_set(f"{entry.title} {entry.abstract}")
    overlap = sorted(question_terms & document_terms)
    score = min(100, 35 + (len(overlap) * 8))
    if entry.year and entry.year >= 2020:
        score += 8
    score = min(score, 100)
    rationale = "Matched terms: " + ", ".join(overlap[:8]) if overlap else "Ranked from arXiv query match and metadata."
    return score, rationale


def keyword_set(text: str) -> set[str]:
    stopwords = {"the", "and", "for", "with", "from", "that", "this", "into", "how", "can", "are", "using"}
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2 and token not in stopwords}


def remember_candidate_decisions(db: Session, project_id: str, approved_candidate_ids: list[str]) -> None:
    approved_ids = set(approved_candidate_ids)
    if not approved_ids:
        return

    try:
        project = get_project_or_404(db, project_id)
        candidates = sorted(project.candidates, key=lambda candidate: candidate.score, reverse=True)
        selected_candidates = [candidate for candidate in candidates if candidate.id in approved_ids]
        for candidate in candidates:
            accepted = candidate.id in approved_ids
            decision = "accepted" if accepted else "rejected"
            create_memory(
                db,
                scope="project",
                memory_type=f"{decision}_paper",
                text=(
                    f"{decision.title()} paper for research question '{project.question}': {candidate.title}. "
                    f"Rationale: {candidate.rationale}"
                ),
                project_id=project.id,
                metadata_json={
                    "decision": decision,
                    "candidate_id": candidate.id,
                    "arxiv_id": candidate.arxiv_id,
                    "title": candidate.title,
                    "score": candidate.score,
                    "rationale": candidate.rationale,
                    "year": candidate.year,
                },
                importance=3 if accepted else 2,
                source="approval",
                dedupe_key=f"approval:{project.id}:{candidate.id}",
            )

        if selected_candidates:
            profile = infer_preference_profile(project.question, selected_candidates)
            create_memory(
                db,
                scope="user",
                memory_type="preference",
                text=(
                    "User preference inferred from approved research papers. "
                    f"Domains: {', '.join(profile['domains']) or 'unspecified'}. "
                    f"Methods: {', '.join(profile['methods']) or 'unspecified'}. "
                    f"Datasets: {', '.join(profile['datasets']) or 'unspecified'}. "
                    f"Recency preference: {profile['recency_preference']}. "
                    f"Keywords: {', '.join(profile['keywords'][:10])}. "
                    f"Accepted papers: {', '.join(candidate.title for candidate in selected_candidates[:4])}."
                ),
                project_id=project.id,
                metadata_json=profile,
                importance=3,
                source="approval",
                dedupe_key=f"approval-preference:{project.id}",
            )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        record_fallback("memory.candidate_decisions", "skip_memory_write", str(exc), {"project_id": project_id})


def infer_preference_profile(question: str, candidates: list[ResearchCandidate]) -> dict[str, Any]:
    combined = " ".join([question, *[candidate.title for candidate in candidates], *[candidate.abstract for candidate in candidates]])
    terms = keyword_set(combined)
    years = [candidate.year for candidate in candidates if candidate.year]
    return {
        "domains": infer_domains(terms),
        "methods": sorted(terms & METHOD_TERMS)[:10],
        "datasets": infer_datasets(combined),
        "recency_preference": infer_recency_preference(question, years),
        "keywords": sorted(terms)[:20],
        "accepted_arxiv_ids": [candidate.arxiv_id for candidate in candidates],
        "accepted_titles": [candidate.title for candidate in candidates],
        "year_range": [min(years), max(years)] if years else None,
    }


def infer_domains(terms: set[str]) -> list[str]:
    domains = []
    if terms & {"rag", "retrieval", "language", "llm", "nlp", "question", "answering", "summarization"}:
        domains.append("natural language processing")
    if terms & {"vision", "image", "visual", "diffusion", "segmentation", "detection"}:
        domains.append("computer vision")
    if terms & {"clinical", "medical", "health", "biomedical", "ehr"}:
        domains.append("healthcare ai")
    if terms & {"robot", "robotics", "control", "planning"}:
        domains.append("robotics")
    if terms & {"graph", "network", "node", "edge"}:
        domains.append("graph learning")
    return domains or ["general ai research"]


def infer_datasets(text: str) -> list[str]:
    blocked = {"The", "This", "These", "They", "Abstract", "Introduction", "Results", "Conclusion"}
    candidates = re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", text)
    datasets = []
    for candidate in candidates:
        if candidate in blocked or candidate.lower() in keyword_set(" ".join(blocked)):
            continue
        if candidate not in datasets:
            datasets.append(candidate)
    return datasets[:10]


def infer_recency_preference(question: str, years: list[int]) -> str:
    question_terms = keyword_set(question)
    if question_terms & {"recent", "latest", "new", "current", "modern"}:
        return "explicit_recent"
    if years and min(years) >= 2020:
        return "recent"
    if years and max(years) < 2020:
        return "foundational_or_older"
    return "mixed_or_unspecified"


METHOD_TERMS = {
    "ablation",
    "agent",
    "alignment",
    "benchmark",
    "chain",
    "contrastive",
    "diffusion",
    "embedding",
    "evaluation",
    "finetuning",
    "generation",
    "graph",
    "hallucination",
    "language",
    "llm",
    "memory",
    "prompting",
    "rag",
    "ranking",
    "reasoning",
    "retrieval",
    "rlhf",
    "transformer",
}


def seed_demo_project(db: Session) -> ResearchProject:
    existing = db.query(ResearchProject).filter(ResearchProject.question == DEMO_QUESTION).one_or_none()
    if existing is not None:
        return existing

    project = create_project(db, DEMO_QUESTION)
    plan_project(db, project.id)
    for arxiv_id in DEMO_ARXIV_IDS:
        entry = fetch_arxiv_entry(arxiv_id)
        score, rationale = score_candidate(DEMO_QUESTION, entry)
        db.add(
            ResearchCandidate(
                project_id=project.id,
                arxiv_id=entry.arxiv_id,
                title=entry.title,
                authors=entry.authors,
                abstract=entry.abstract,
                year=entry.year,
                pdf_url=entry.pdf_url,
                entry_url=entry.entry_url,
                score=score,
                rationale=rationale,
                selected=True,
            )
        )
    project.status = "discovered"
    db.add(project)
    db.commit()
    return get_project_or_404(db, project.id)
