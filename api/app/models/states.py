from __future__ import annotations

from enum import StrEnum


class PaperStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"


class ProjectStatus(StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"
    IMPORTING = "importing"
    ANALYZING = "analyzing"
    BLOCKED = "blocked"
    SYNTHESIS_QUEUED = "synthesis_queued"
    SYNTHESIZING = "synthesizing"
    DONE = "done"
    DEGRADED = "degraded"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GenerationMode(StrEnum):
    AI = "ai"
    EXTRACTIVE = "extractive"
    MOCK = "mock"
    UNKNOWN_LEGACY = "unknown_legacy"
