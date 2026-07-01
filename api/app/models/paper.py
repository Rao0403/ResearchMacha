from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def default_id() -> str:
    return str(uuid.uuid4())


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=default_id)
    source: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(512))
    authors: Mapped[list[str]] = mapped_column(JSON, default=list)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    pdf_path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    chunks: Mapped[list["PaperChunk"]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    summary: Mapped["PaperSummary | None"] = relationship(back_populates="paper", cascade="all, delete-orphan")
    highlights: Mapped[list["Highlight"]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(back_populates="paper", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="paper", cascade="all, delete-orphan")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=default_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    job_type: Mapped[str] = mapped_column(String(32), default="analysis")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    paper: Mapped[Paper] = relationship(back_populates="jobs")


class PaperChunk(Base):
    __tablename__ = "paper_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=default_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    section_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    paper: Mapped[Paper] = relationship(back_populates="chunks")


class PaperSummary(Base):
    __tablename__ = "paper_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=default_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), unique=True)
    problem_or_hypothesis: Mapped[str] = mapped_column(Text)
    approach: Mapped[str] = mapped_column(Text)
    experiments: Mapped[str] = mapped_column(Text)
    results: Mapped[str] = mapped_column(Text)
    conclusion: Mapped[str] = mapped_column(Text)
    limitations_or_notes: Mapped[str] = mapped_column(Text)
    section_citations: Mapped[dict[str, list[dict[str, str | int]]]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    paper: Mapped[Paper] = relationship(back_populates="summary")


class Highlight(Base):
    __tablename__ = "highlights"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=default_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    label: Mapped[str] = mapped_column(String(255))
    explanation: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict[str, str | int]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    paper: Mapped[Paper] = relationship(back_populates="highlights")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=default_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255), default="Paper chat")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    paper: Mapped[Paper] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=default_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict[str, str | int]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    session: Mapped[ChatSession] = relationship(back_populates="messages")

