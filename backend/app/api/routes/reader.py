from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from pydantic import field_validator
from uuid import UUID
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.paper import ChatMessage, ChatSession, Paper, PaperReadingState, PaperNote
from app.schemas.paper import ChatMessageRead
from app.services.papers import get_paper_or_404

router = APIRouter()


class NoteContent(BaseModel):
    body: str = Field(min_length=1, max_length=20_000)
    page: int | None = Field(default=None, ge=1)
    excerpt: str | None = Field(default=None, max_length=4000)

    @field_validator("body")
    @classmethod
    def nonempty_body(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Write a note before saving")
        return value


class NoteCreate(NoteContent):
    id: UUID


class NoteUpdate(NoteContent):
    version: int = Field(ge=1)


def note_json(note: PaperNote) -> dict:
    return {"id": note.id, "paper_id": note.paper_id, "body": note.body, "page": note.page,
            "excerpt": note.excerpt, "version": note.version, "created_at": note.created_at, "updated_at": note.updated_at}


def validate_note_page(paper: Paper, page: int | None) -> None:
    if page is None:
        return
    try:
        count = len(PdfReader(paper.pdf_path).pages)
    except Exception as error:
        raise HTTPException(422, "Cannot attach a page while the PDF is unavailable") from error
    if page > count:
        raise HTTPException(422, "Note page is outside this PDF")


def scoped_note(db: Session, paper_id: str, note_id: str) -> PaperNote:
    note = db.query(PaperNote).filter_by(id=note_id, paper_id=paper_id).with_for_update().populate_existing().one_or_none()
    if note is None:
        raise HTTPException(404, "Note does not belong to this paper")
    return note


@router.get("/papers/{paper_id}/notes")
def list_notes(paper_id: str, db: Session = Depends(get_db)):
    get_paper_or_404(db, paper_id)
    return [note_json(note) for note in db.query(PaperNote).filter_by(paper_id=paper_id).order_by(PaperNote.updated_at.desc(), PaperNote.id).all()]


@router.post("/papers/{paper_id}/notes")
def create_note(paper_id: str, payload: NoteCreate, db: Session = Depends(get_db)):
    paper = db.scalar(select(Paper).where(Paper.id == paper_id).with_for_update())
    if paper is None:
        raise HTTPException(404, "Paper not found")
    existing = db.get(PaperNote, str(payload.id))
    if existing is not None:
        if existing.paper_id != paper_id or any(getattr(existing, field) != getattr(payload, field) for field in ("body", "page", "excerpt")):
            raise HTTPException(409, "Note already exists with different content; reopen it before editing")
        return note_json(existing)
    validate_note_page(paper, payload.page)
    note = PaperNote(id=str(payload.id), paper_id=paper_id, **payload.model_dump(exclude={"id"}))
    db.add(note); db.commit()
    return note_json(note)


@router.put("/papers/{paper_id}/notes/{note_id}")
def update_note(paper_id: str, note_id: str, payload: NoteUpdate, db: Session = Depends(get_db)):
    note = scoped_note(db, paper_id, note_id)
    if note.version != payload.version:
        raise HTTPException(409, "This note changed in another request. Your draft was not saved; reload saved notes before resolving it.")
    validate_note_page(get_paper_or_404(db, paper_id), payload.page)
    note.body, note.page, note.excerpt = payload.body, payload.page, payload.excerpt
    note.version += 1
    db.commit()
    return note_json(note)


@router.delete("/papers/{paper_id}/notes/{note_id}")
def delete_note(paper_id: str, note_id: str, version: int = Query(ge=1), db: Session = Depends(get_db)):
    note = scoped_note(db, paper_id, note_id)
    if note.version != version:
        raise HTTPException(409, "This note changed. Reload it before deleting.")
    db.delete(note); db.commit()
    return {"deleted": note_id}


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
