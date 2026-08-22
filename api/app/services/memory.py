from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.ai import get_ai_provider
from app.models.paper import ResearchMemory
from app.services.fallbacks import record_fallback
from app.services.vector_store import get_vector_store


def create_memory(
    db: Session,
    *,
    scope: str,
    memory_type: str,
    text: str,
    project_id: str | None = None,
    paper_id: str | None = None,
    metadata_json: dict[str, Any] | None = None,
    importance: int = 1,
    source: str = "system",
) -> ResearchMemory:
    memory = ResearchMemory(
        scope=scope,
        memory_type=memory_type,
        text=text,
        project_id=project_id,
        paper_id=paper_id,
        metadata_json=metadata_json or {},
        importance=importance,
        source=source,
        status="active",
    )
    db.add(memory)
    db.flush()

    try:
        memory.embedding = get_ai_provider().embed_texts([text])[0]
    except Exception as exc:
        record_fallback(
            "memory.embed",
            "mysql_unembedded_memory",
            str(exc),
            {"scope": scope, "memory_type": memory_type, "project_id": project_id, "paper_id": paper_id},
        )

    db.commit()
    db.refresh(memory)
    index_memories([memory])
    return memory


def index_memories(memories: list[ResearchMemory]) -> None:
    if not memories:
        return
    try:
        get_vector_store().upsert_memories(memories)
    except Exception as exc:
        record_fallback(
            "memory.index",
            "mysql_memory_only",
            str(exc),
            {"memory_count": len(memories)},
        )


def retrieve_memories(
    db: Session,
    query: str,
    *,
    scope: str | None = None,
    limit: int = 5,
) -> list[ResearchMemory]:
    if not query.strip():
        return []
    try:
        query_embedding = get_ai_provider().embed_texts([query])[0]
        return get_vector_store().search_memories(db, query_embedding, scope=scope, limit=limit)
    except Exception as exc:
        record_fallback(
            "memory.retrieve",
            "mysql_latest_memories",
            str(exc),
            {"scope": scope, "limit": limit},
        )
        return latest_memories(db, scope=scope, limit=limit)


def latest_memories(
    db: Session,
    *,
    scope: str | None = None,
    project_id: str | None = None,
    paper_id: str | None = None,
    limit: int = 5,
) -> list[ResearchMemory]:
    query = db.query(ResearchMemory).filter(ResearchMemory.status == "active")
    if scope:
        query = query.filter(ResearchMemory.scope == scope)
    if project_id:
        query = query.filter(or_(ResearchMemory.project_id == project_id, ResearchMemory.scope == "user"))
    if paper_id:
        query = query.filter(ResearchMemory.paper_id == paper_id)
    return query.order_by(ResearchMemory.updated_at.desc()).limit(limit).all()


def memory_payload(memory: ResearchMemory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "scope": memory.scope,
        "memory_type": memory.memory_type,
        "text": memory.text,
        "importance": memory.importance,
        "metadata_json": memory.metadata_json or {},
        "project_id": memory.project_id,
        "paper_id": memory.paper_id,
        "source": memory.source,
        "status": memory.status,
    }


def format_memory_context(memories: list[ResearchMemory]) -> str:
    if not memories:
        return "No prior memory signals are available."
    lines = []
    for memory in memories:
        lines.append(
            f"- [{memory.scope}/{memory.memory_type}/importance={memory.importance}] "
            f"{memory.text[:700]}"
        )
    return "\n".join(lines)
