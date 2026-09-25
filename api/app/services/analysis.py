from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.paper import ChatMessage, ChatSession, Highlight, Job, Paper, PaperChunk, PaperSummary, default_id
from app.models.states import JobStatus
from app.schemas.paper import ChatMessageRead, ChatResponse
from app.ai import EvidenceRegistry, get_ai_provider, validate_citations, validate_summary_payload
from app.services.fallbacks import clear_fallback_events, pop_fallback_events, record_fallback
from app.services.memory import create_paper_fact_memory
from app.services.pdf import chunk_pages, extract_pdf_pages
from app.services.retrieval import retrieve_paper_chunks
from app.services.vector_store import get_vector_store


def enqueue_analysis_job(db: Session, paper_id: str, auto_reset: bool) -> Job:
    paper = db.execute(
        select(Paper).where(Paper.id == paper_id).with_for_update()
    ).scalar_one_or_none()
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    active = db.query(Job).filter(
        Job.paper_id == paper_id,
        Job.job_type == "analysis",
        Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
    ).order_by(Job.created_at.desc()).first()
    if active is not None:
        return active

    requested_generation = paper.analysis_generation + 1
    idempotency_key = f"analysis:{paper_id}:{requested_generation}"
    existing = db.query(Job).filter(Job.idempotency_key == idempotency_key).one_or_none()
    if existing is not None:
        return existing

    job = Job(
        paper_id=paper_id,
        job_type="analysis",
        status=JobStatus.QUEUED,
        requested_generation=requested_generation,
        idempotency_key=idempotency_key,
    )
    if paper.analysis_generation == 0:
        paper.status = "queued"
    db.add(job)
    db.add(paper)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(Job).filter(Job.idempotency_key == idempotency_key).one_or_none()
        if existing is None:
            raise
        return existing
    db.refresh(job)
    return job


def process_analysis_job(
    job_id: str,
    *,
    heartbeat: Callable[[], bool] | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
) -> None:
    db = session_factory()
    try:
        job = db.get(Job, job_id)
        if job is None or job.paper_id is None:
            return

        paper = db.get(Paper, job.paper_id)
        if paper is None:
            raise RuntimeError("Analysis target no longer exists")

        requested_generation = job.requested_generation or (paper.analysis_generation + 1)
        if paper.analysis_generation >= requested_generation:
            job.status = JobStatus.COMPLETED
            job.finished_at = now()
            job.lease_expires_at = None
            db.add(job)
            db.commit()
            return

        previous_status = paper.status if paper.analysis_generation > 0 else None
        payload = dict(job.payload or {})
        payload["previous_status"] = previous_status
        job.payload = payload
        job.status = JobStatus.RUNNING
        job.started_at = job.started_at or now()
        paper.status = "processing"
        db.add_all([job, paper])
        db.commit()

        if heartbeat:
            heartbeat()
        pages = extract_pdf_pages(paper.pdf_path)
        chunks = chunk_pages(pages)
        if heartbeat:
            heartbeat()
        clear_fallback_events()
        provider = get_ai_provider()
        embedding_result = None
        if chunks:
            try:
                embedding_result = provider.embed_texts([chunk["text"] for chunk in chunks])
            except Exception as exc:  # noqa: BLE001 - unembedded chunks remain usable through lexical retrieval
                record_fallback(
                    "analysis.embed_chunks",
                    "unembedded_chunks_with_lexical_retrieval",
                    str(exc),
                    {"paper_id": paper.id, "chunk_count": len(chunks)},
                )

        replacement_chunks = [
            PaperChunk(
                id=default_id(),
                paper_id=paper.id,
                analysis_generation=requested_generation,
                chunk_index=index,
                page_start=int(chunk["page_start"]),
                page_end=int(chunk["page_end"]),
                section_label=chunk.get("section_label"),
                text=str(chunk["text"]),
                embedding=(
                    embedding_result.vectors[index]
                    if embedding_result is not None and index < len(embedding_result.vectors)
                    else None
                ),
                embedding_fingerprint=embedding_result.fingerprint if embedding_result is not None else None,
                embedding_dim=embedding_result.dimension if embedding_result is not None else None,
            )
            for index, chunk in enumerate(chunks)
        ]
        old_chunks = (
            db.query(PaperChunk)
            .filter(PaperChunk.paper_id == paper.id)
            .order_by(PaperChunk.chunk_index.asc())
            .all()
        )
        get_vector_store().upsert_chunks(replacement_chunks)
        if heartbeat:
            heartbeat()
        chunk_payload = [
            {
                "id": chunk.id,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section_label": chunk.section_label,
                "text": chunk.text,
            }
            for chunk in replacement_chunks
        ]
        summary_payload = provider.generate_summary(paper.title, chunk_payload)
        validate_summary_payload(summary_payload, chunk_payload)
        if heartbeat:
            heartbeat()
        fallback_events = pop_fallback_events()

        replacement_summary = PaperSummary(
            paper_id=paper.id,
            problem_or_hypothesis=summary_payload.sections["problem_or_hypothesis"],
            approach=summary_payload.sections["approach"],
            experiments=summary_payload.sections["experiments"],
            results=summary_payload.sections["results"],
            conclusion=summary_payload.sections["conclusion"],
            limitations_or_notes=summary_payload.sections["limitations_or_notes"],
            section_citations=summary_payload.section_citations,
        )
        replacement_highlights = [
            Highlight(
                paper_id=paper.id,
                position=highlight.get("position", 0),
                label=highlight.get("label", "Key highlight"),
                explanation=highlight.get("explanation", ""),
                citations=highlight.get("citations", []),
            )
            for highlight in summary_payload.highlights
        ]

        db.query(PaperChunk).filter(PaperChunk.paper_id == paper.id).delete(synchronize_session=False)
        db.query(Highlight).filter(Highlight.paper_id == paper.id).delete(synchronize_session=False)
        db.query(PaperSummary).filter(PaperSummary.paper_id == paper.id).delete(synchronize_session=False)
        db.add_all([*replacement_chunks, replacement_summary, *replacement_highlights])
        paper.analysis_generation = requested_generation
        paper.analysis_warning = None
        paper.status = "ready"
        if fallback_events:
            payload = dict(job.payload or {})
            payload.update({"fallback_used": True, "fallbacks": fallback_events})
            job.payload = payload
        db.add_all([paper, job])
        db.commit()

        try:
            get_vector_store().delete_chunks(old_chunks)
        except Exception as exc:  # noqa: BLE001 - stale vector points cannot resolve without database rows
            record_fallback(
                "analysis.delete_old_vectors",
                "ignore_unresolvable_stale_points",
                str(exc),
                {"paper_id": paper.id, "old_chunk_count": len(old_chunks)},
            )
        try:
            create_paper_fact_memory(
                db,
                paper_id=paper.id,
                title=paper.title,
                sections=summary_payload.sections,
            )
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            record_fallback("memory.paper_fact", "skip_memory_write", str(exc), {"paper_id": paper.id})
        memory_fallback_events = pop_fallback_events()
        job = db.get(Job, job_id)
        if job is not None:
            if memory_fallback_events:
                payload = dict(job.payload or {})
                payload["fallback_used"] = True
                payload["fallbacks"] = [*(payload.get("fallbacks") or []), *memory_fallback_events]
                job.payload = payload
            job.status = JobStatus.COMPLETED
            job.finished_at = now()
            job.lease_expires_at = None
            db.add(job)
            db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            paper = db.get(Paper, job.paper_id) if job.paper_id else None
            if paper is not None and job.requested_generation and paper.analysis_generation >= job.requested_generation:
                job.status = JobStatus.COMPLETED
                job.warning_message = f"Analysis committed; post-processing was interrupted: {exc}"
            else:
                job.status = JobStatus.FAILED
                job.error_message = str(exc)
            job.finished_at = now()
            job.lease_expires_at = None
            db.add(job)
            if paper is not None:
                if job.status == JobStatus.FAILED:
                    previous_status = (job.payload or {}).get("previous_status")
                    paper.status = previous_status or "failed"
                    paper.analysis_warning = f"Analysis generation {job.requested_generation or 'unknown'} failed: {exc}"
                db.add(paper)
        db.commit()
    finally:
        db.close()


def run_chat_query(db: Session, paper: Paper, session: ChatSession, question: str) -> ChatResponse:
    history = [{"role": message.role, "content": message.content} for message in session.messages]
    clear_fallback_events()
    provider = get_ai_provider()
    retrieved = retrieve_paper_chunks(db, paper.id, question, limit=4)

    chunk_payload = [
        {
            "id": chunk.id,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "text": chunk.text,
            "section_label": chunk.section_label,
        }
        for chunk in retrieved
    ]
    answer_payload = provider.answer_question(paper.title, question, chunk_payload, history)
    validate_citations(
        answer_payload.citations,
        EvidenceRegistry.from_chunks(chunk_payload),
        require_at_least_one=False,
    )
    fallback_events = pop_fallback_events()
    if fallback_events:
        answer_payload.answer = (
            "Fallback notice: part of this answer used a deterministic fallback because the primary path failed. "
            f"Reason: {fallback_events[0]['reason']}\n\n{answer_payload.answer}"
        )

    user_message = ChatMessage(session_id=session.id, role="user", content=question, citations=[])
    assistant_message = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=answer_payload.answer,
        citations=answer_payload.citations,
    )
    db.add_all([user_message, assistant_message])
    db.commit()
    db.refresh(assistant_message)

    return ChatResponse(
        session_id=session.id,
        answer=ChatMessageRead.model_validate(assistant_message),
        citations=assistant_message.citations,
        retrieved_chunk_ids=[chunk.id for chunk in retrieved],
    )


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
