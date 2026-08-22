from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.memory import ResearchMemoryRead
from app.schemas.paper import LibraryPaperRead


class ResearchProjectCreate(BaseModel):
    question: str = Field(min_length=10, max_length=2000)


class ResearchPlanResponse(BaseModel):
    search_queries: list[str]
    inclusion_criteria: list[str]


class ResearchCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    year: int | None
    pdf_url: str
    entry_url: str
    score: int
    rationale: str
    selected: bool
    created_at: datetime


class CandidateSelectionRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)


class AgentStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    project_id: str
    position: int
    tool_name: str
    status: str
    input_json: dict[str, Any] | None
    output_json: dict[str, Any] | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    status: str
    goal: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime
    finished_at: datetime | None
    steps: list[AgentStepRead] = Field(default_factory=list)


class ResearchProjectRead(BaseModel):
    id: str
    question: str
    status: str
    generated_queries: list[str]
    inclusion_criteria: list[str]
    synthesis_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    candidates: list[ResearchCandidateRead] = Field(default_factory=list)
    papers: list[LibraryPaperRead] = Field(default_factory=list)
    agent_run: AgentRunRead | None = None
    memory_signals: list[ResearchMemoryRead] = Field(default_factory=list)
