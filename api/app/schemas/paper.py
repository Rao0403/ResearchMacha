from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Citation(BaseModel):
    page: int
    excerpt: str
    chunk_id: str | None = None


class HighlightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    label: str
    explanation: str
    citations: list[Citation]


class PaperSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    year: int | None = None
    pdf_url: str
    entry_url: str


class LibraryPaperRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    title: str
    authors: list[str]
    abstract: str | None
    year: int | None
    arxiv_id: str | None
    source_key: str | None
    status: str
    analysis_generation: int
    analysis_mode: str
    analysis_warning: str | None
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None


class PaperChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chunk_index: int
    page_start: int
    page_end: int
    section_label: str | None
    text: str
    analysis_generation: int


class PaperSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    problem_or_hypothesis: str
    approach: str
    experiments: str
    results: str
    conclusion: str
    limitations_or_notes: str
    section_citations: dict[str, list[Citation]]
    generation_mode: str
    warning: str | None


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    paper_id: str | None
    project_id: str | None
    candidate_id: str | None
    job_type: str
    status: str
    idempotency_key: str
    requested_generation: int | None
    attempt_count: int
    worker_id: str | None
    claimed_at: datetime | None
    lease_expires_at: datetime | None
    error_message: str | None
    warning_message: str | None
    payload: dict | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class PaperDetailRead(LibraryPaperRead):
    chunks: list[PaperChunkRead] = Field(default_factory=list)
    summary: PaperSummaryRead | None = None
    highlights: list[HighlightRead] = Field(default_factory=list)


class PaperSummaryResponse(BaseModel):
    paper: PaperDetailRead
    summary: PaperSummaryRead
    highlights: list[HighlightRead]


class UploadPaperResponse(BaseModel):
    paper: LibraryPaperRead
    job: JobRead


class BatchUploadResponse(BaseModel):
    items: list[UploadPaperResponse]


class BatchSummaryRequest(BaseModel):
    paper_ids: list[str] = Field(min_length=1)
    goal: str = Field(default="Summarize the uploaded research papers.", min_length=3, max_length=2000)


class BatchPaperSummaryRead(BaseModel):
    paper_id: str
    title: str
    main_idea: str
    problem_or_hypothesis: str
    experiments: str
    models_and_datasets: str
    results: str
    conclusions: str


class BatchSummaryResponse(BaseModel):
    overall_takeaway: str
    papers: list[BatchPaperSummaryRead]
    generation_mode: str
    warnings: list[str] = Field(default_factory=list)


class ArxivImportRequest(BaseModel):
    arxiv_id: str = Field(min_length=3, max_length=64)


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    session_id: str | None = None


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    citations: list[Citation]
    generation_mode: str | None = None
    warning: str | None = None
    created_at: datetime


class ChatResponse(BaseModel):
    session_id: str
    answer: ChatMessageRead
    citations: list[Citation]
    retrieved_chunk_ids: list[str]
    generation_mode: str
    warnings: list[str] = Field(default_factory=list)
