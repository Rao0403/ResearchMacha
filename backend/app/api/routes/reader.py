from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.paper import ChatMessage, ChatSession, Paper, PaperReadingState
from app.schemas.paper import ChatMessageRead
from app.services.papers import get_paper_or_404

router = APIRouter()


class ReadingUpdate(BaseModel):
    page: int = Field(ge=1)
    version: int = Field(ge=0)
    active_session_id: str | None = None


def validate_session(db: Session, paper_id: str, session_id: str) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None or session.paper_id != paper_id:
        raise HTTPException(404, "Conversation does not belong to this paper")
    return session


@router.get("/papers/{paper_id}/workspace")
def reader_workspace(paper_id: str, session_id: str | None = Query(None), db: Session = Depends(get_db)):
    get_paper_or_404(db, paper_id)
    state = db.get(PaperReadingState, paper_id)
    sessions = db.query(ChatSession).filter(ChatSession.paper_id == paper_id).order_by(ChatSession.updated_at.desc(), ChatSession.id).all()
    active = session_id or (state.active_session_id if state else None) or (sessions[0].id if sessions else None)
    if active:
        validate_session(db, paper_id, active)
    messages = db.query(ChatMessage).filter(ChatMessage.session_id == active).order_by(ChatMessage.position, ChatMessage.created_at, ChatMessage.id).all() if active else []
    return {"page": state.page if state else 1, "version": state.version if state else 0,
            "active_session_id": active,
            "sessions": [{"id": s.id, "title": s.title} for s in sessions],
            "messages": [ChatMessageRead.model_validate(m).model_dump() for m in messages]}


@router.put("/papers/{paper_id}/reading-state")
def save_reading_state(paper_id: str, payload: ReadingUpdate, db: Session = Depends(get_db)):
    paper = db.scalar(select(Paper).where(Paper.id == paper_id).with_for_update())
    if paper is None:
        raise HTTPException(404, "Paper not found")
    try:
        count = len(PdfReader(paper.pdf_path).pages)
    except Exception as error:
        raise HTTPException(422, "PDF is unavailable; reading position was not changed") from error
    if payload.page > count:
        raise HTTPException(422, "Page is outside this PDF")
    state = db.get(PaperReadingState, paper_id)
    if (state.version if state else 0) != payload.version:
        raise HTTPException(409, "Reading position changed in another request. Reload the saved position.")
    if state is None:
        state = PaperReadingState(paper_id=paper_id, version=0)
    state.page = payload.page
    state.version += 1
    if "active_session_id" in payload.model_fields_set:
        if payload.active_session_id:
            validate_session(db, paper_id, payload.active_session_id)
        state.active_session_id = payload.active_session_id
    db.add(state)
    db.commit()
    return {"page": state.page, "version": state.version}


@router.post("/papers/{paper_id}/chat-sessions")
def new_chat_session(paper_id: str, db: Session = Depends(get_db)):
    paper = db.scalar(select(Paper).where(Paper.id == paper_id).with_for_update())
    if paper is None:
        raise HTTPException(404, "Paper not found")
    session = ChatSession(paper_id=paper_id, title="Paper chat")
    db.add(session)
    db.flush()
    state = db.get(PaperReadingState, paper_id)
    if state is None:
        state = PaperReadingState(paper_id=paper_id, page=1, version=0)
    state.active_session_id = session.id
    state.version += 1
    db.add(state)
    db.commit()
    return reader_workspace(paper_id, session.id, db)
