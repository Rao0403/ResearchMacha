from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ResearchMemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scope: str
    memory_type: str
    text: str
    importance: int
    metadata_json: dict[str, Any] | None
    project_id: str | None
    paper_id: str | None
    source: str
    status: str
    created_at: datetime
    updated_at: datetime
