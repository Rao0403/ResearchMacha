from __future__ import annotations
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.paper import ChatSession, Paper
from app.services.arxiv import ArxivEntry
from app.services.storage import save_remote_pdf


def get_paper_or_404(db: Session, paper_id: str) -> Paper:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


def create_or_update_paper_from_arxiv(db: Session, entry: ArxivEntry) -> tuple[Paper, bool]:
    paper = db.query(Paper).filter(Paper.arxiv_id == entry.arxiv_id).one_or_none()
    if paper is None:
        pdf_path = save_remote_pdf(entry.pdf_url, f"{entry.arxiv_id}.pdf")
        paper = Paper(
            source="arxiv",
            title=entry.title,
            authors=entry.authors,
            abstract=entry.abstract,
            year=entry.year,
            arxiv_id=entry.arxiv_id,
            pdf_path=pdf_path,
            status="queued",
        )
        db.add(paper)
        db.commit()
        db.refresh(paper)
        return paper, True

    paper.title = entry.title
    paper.authors = entry.authors
    paper.abstract = entry.abstract
    paper.year = entry.year
    if not paper.pdf_path:
        paper.pdf_path = save_remote_pdf(entry.pdf_url, f"{entry.arxiv_id}.pdf")
    db.add(paper)
    db.commit()
    db.refresh(paper)
    return paper, False


def create_uploaded_paper(db: Session, title: str, authors: list[str], pdf_path: str) -> Paper:
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
    db.commit()
    db.refresh(paper)
    return paper


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
