from __future__ import annotations

from datetime import UTC, datetime

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.paper import ChatMessage, ChatSession, Highlight, Job, Paper, PaperChunk, PaperSummary
from app.schemas.paper import ChatMessageRead, ChatResponse
from app.ai import get_ai_provider
from app.services.fallbacks import clear_fallback_events, pop_fallback_events, record_fallback
from app.services.memory import create_paper_fact_memory
from app.services.pdf import chunk_pages, extract_pdf_pages
from app.services.vector_store import get_vector_store


def enqueue_analysis_job(db: Session, paper_id: str, background_tasks: BackgroundTasks, auto_reset: bool) -> Job:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    if auto_reset:
        get_vector_store().delete_paper_chunks(paper_id)
        db.query(PaperChunk).filter(PaperChunk.paper_id == paper_id).delete()
        db.query(Highlight).filter(Highlight.paper_id == paper_id).delete()
        db.query(PaperSummary).filter(PaperSummary.paper_id == paper_id).delete()
        paper.status = "queued"

    job = Job(paper_id=paper_id, job_type="analysis", status="queued")
    db.add(job)
    db.add(paper)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(process_analysis_job, job.id)
    return job


def process_analysis_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return

        paper = db.get(Paper, job.paper_id)
        if paper is None:
            return

        job.status = "running"
        job.started_at = now()
        paper.status = "processing"
        db.add_all([job, paper])
        db.commit()

        pages = extract_pdf_pages(paper.pdf_path)
        chunks = chunk_pages(pages)
        clear_fallback_events()
        provider = get_ai_provider()
        embeddings = provider.embed_texts([chunk["text"] for chunk in chunks]) if chunks else []

        for index, chunk in enumerate(chunks):
            db.add(
                PaperChunk(
                    paper_id=paper.id,
                    chunk_index=index,
                    page_start=chunk["page_start"],
                    page_end=chunk["page_end"],
                    section_label=chunk.get("section_label"),
                    text=chunk["text"],
                    embedding=embeddings[index] if index < len(embeddings) else None,
                )
            )

        db.commit()

        stored_chunks = (
            db.query(PaperChunk)
            .filter(PaperChunk.paper_id == paper.id)
            .order_by(PaperChunk.chunk_index.asc())
            .all()
        )
        get_vector_store().upsert_chunks(stored_chunks)
        chunk_payload = [
            {
                "id": chunk.id,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section_label": chunk.section_label,
                "text": chunk.text,
            }
            for chunk in stored_chunks
        ]
        summary_payload = provider.generate_summary(paper.title, chunk_payload)
        fallback_events = pop_fallback_events()

        db.add(
            PaperSummary(
                paper_id=paper.id,
                problem_or_hypothesis=summary_payload.sections["problem_or_hypothesis"],
                approach=summary_payload.sections["approach"],
                experiments=summary_payload.sections["experiments"],
                results=summary_payload.sections["results"],
                conclusion=summary_payload.sections["conclusion"],
                limitations_or_notes=summary_payload.sections["limitations_or_notes"],
                section_citations=summary_payload.section_citations,
            )
        )

        for highlight in summary_payload.highlights:
            db.add(
                Highlight(
                    paper_id=paper.id,
                    position=highlight.get("position", 0),
                    label=highlight.get("label", "Key highlight"),
                    explanation=highlight.get("explanation", ""),
                    citations=highlight.get("citations", []),
                )
            )

        paper.status = "ready"
        job.status = "completed"
        if fallback_events:
            job.payload = {"fallback_used": True, "fallbacks": fallback_events}
        job.finished_at = now()
        db.add_all([paper, job])
        db.commit()
        try:
            create_paper_fact_memory(db, paper_id=paper.id, title=paper.title, sections=summary_payload.sections)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            record_fallback("memory.paper_fact", "skip_memory_write", str(exc), {"paper_id": paper.id})
        memory_fallback_events = pop_fallback_events()
        if memory_fallback_events:
            job = db.get(Job, job_id)
            if job is not None:
                payload = dict(job.payload or {})
                payload["fallback_used"] = True
                payload["fallbacks"] = [*(payload.get("fallbacks") or []), *memory_fallback_events]
                job.payload = payload
                db.add(job)
                db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(Job, job_id)
        if job is not None:
            job.status = "failed"
            job.error_message = str(exc)
            job.finished_at = now()
            db.add(job)
        if job is not None:
            paper = db.get(Paper, job.paper_id)
            if paper is not None:
                paper.status = "failed"
                db.add(paper)
        db.commit()
    finally:
        db.close()


def run_chat_query(db: Session, paper: Paper, session: ChatSession, question: str) -> ChatResponse:
    history = [{"role": message.role, "content": message.content} for message in session.messages]
    clear_fallback_events()
    provider = get_ai_provider()
    question_embedding = provider.embed_texts([question])[0]
    retrieved = get_vector_store().search_paper_chunks(db, paper.id, question_embedding, limit=4)

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
