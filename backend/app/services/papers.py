from __future__ import annotations
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.paper import ChatSession, Job, Paper
from app.models.states import JobStatus
from app.services.arxiv import ArxivEntry, normalize_arxiv_id
from app.services.storage import save_remote_pdf


def get_paper_or_404(db: Session, paper_id: str) -> Paper:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


def create_or_update_paper_from_arxiv(db: Session, entry: ArxivEntry) -> tuple[Paper, bool]:
    normalized_id = normalize_arxiv_id(entry.arxiv_id)
    title, authors = validate_paper_metadata(entry.title, entry.authors)
    source_key = f"arxiv:{normalized_id}"
    paper = db.query(Paper).filter(Paper.source_key == source_key).one_or_none()
    if paper is None:
        paper = db.query(Paper).filter(Paper.arxiv_id == normalized_id).order_by(Paper.created_at.asc()).first()
    if paper is None:
        pdf_path = save_remote_pdf(entry.pdf_url, f"{normalized_id.replace('/', '_')}.pdf")
        paper = Paper(
            source="arxiv",
            title=title,
            authors=authors,
            abstract=entry.abstract,
            year=entry.year,
            arxiv_id=normalized_id,
            source_key=source_key,
            pdf_path=pdf_path,
            status="queued",
        )
        db.add(paper)
        try:
            db.commit()
        except Exception:
            db.rollback()
            Path(pdf_path).unlink(missing_ok=True)
            raise
        db.refresh(paper)
        return paper, True

    paper.title = title
    paper.authors = authors
    paper.abstract = entry.abstract
    paper.year = entry.year
    paper.arxiv_id = normalized_id
    paper.source_key = source_key
    downloaded_path = None
    if not paper.pdf_path:
        downloaded_path = save_remote_pdf(entry.pdf_url, f"{normalized_id.replace('/', '_')}.pdf")
        paper.pdf_path = downloaded_path
    db.add(paper)
    try:
        db.commit()
    except Exception:
        db.rollback()
        if downloaded_path:
            Path(downloaded_path).unlink(missing_ok=True)
        raise
    db.refresh(paper)
    return paper, False


def create_uploaded_papers_with_jobs(
    db: Session,
    items: list[tuple[str, list[str], str]],
) -> list[tuple[Paper, Job]]:
    created: list[tuple[Paper, Job]] = []
    try:
        for raw_title, raw_authors, pdf_path in items:
            title, authors = validate_paper_metadata(raw_title, raw_authors)
            paper = Paper(
                source="upload",
                title=title,
                authors=authors,
                abstract=None,
                year=None,
                arxiv_id=None,
                pdf_path=pdf_path,
                status="queued",
            )
            db.add(paper)
            db.flush()
            job = Job(
                paper_id=paper.id,
                job_type="analysis",
                status=JobStatus.QUEUED,
                requested_generation=1,
                idempotency_key=f"analysis:{paper.id}:1",
            )
            db.add(job)
            created.append((paper, job))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return created


def validate_paper_metadata(title: str, authors: list[str]) -> tuple[str, list[str]]:
    clean_title = " ".join(title.split())
    clean_authors = [" ".join(author.split()) for author in authors if author.strip()]
    if not clean_title:
        raise ValueError("Paper title must not be empty")
    if len(clean_title) > 512:
        raise ValueError("Paper title must be at most 512 characters")
    if len(clean_authors) > 100:
        raise ValueError("A paper may contain at most 100 authors")
    if any(len(author) > 255 for author in clean_authors):
        raise ValueError("Each author name must be at most 255 characters")
    return clean_title, clean_authors


def create_chat_session_if_missing(db: Session, paper_id: str, session_id: str | None) -> ChatSession:
    if session_id:
        session = db.get(ChatSession, session_id)
        if session and session.paper_id == paper_id:
            return session

    session = (
        db.query(ChatSession)
        .filter(ChatSession.paper_id == paper_id)
        .order_by(ChatSession.updated_at.desc())
        .first()
    )
    if session:
        return session

    session = ChatSession(paper_id=paper_id, title="Paper chat")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session
