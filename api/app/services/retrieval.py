from __future__ import annotations

import math
import re

from sqlalchemy.orm import Session

from app.ai import get_ai_provider
from app.models.paper import PaperChunk
from app.services.fallbacks import record_fallback


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return -1.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return dot / (left_norm * right_norm)


def top_k_chunks(question_embedding: list[float], chunks: list[PaperChunk], limit: int = 4) -> list[PaperChunk]:
    ranked = sorted(
        chunks,
        key=lambda chunk: cosine_similarity(question_embedding, chunk.embedding or []),
        reverse=True,
    )
    return ranked[:limit]


def keyword_terms(value: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9]+", value.lower()) if len(term) > 1}


def lexical_chunks(query: str, chunks: list[PaperChunk], limit: int = 4) -> tuple[list[PaperChunk], str]:
    terms = keyword_terms(query)
    ranked: list[tuple[int, int, PaperChunk]] = []
    for chunk in chunks:
        overlap = len(terms & keyword_terms(chunk.text))
        if overlap:
            ranked.append((overlap, -chunk.chunk_index, chunk))
    if ranked:
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked[:limit]], "lexical_overlap"
    ordered = sorted(chunks, key=lambda chunk: chunk.chunk_index)
    return ordered[:limit], "initial_chunks"


def retrieve_paper_chunks(
    db: Session,
    paper_id: str,
    query: str,
    *,
    limit: int = 4,
) -> list[PaperChunk]:
    from app.services.vector_store import get_vector_store

    embedding_error: str | None = None
    try:
        result = get_ai_provider().embed_texts([query])
        query_embedding = result.vectors[0]
        compatible = get_vector_store().search_paper_chunks(
            db,
            paper_id,
            query_embedding,
            result.fingerprint,
            limit=limit,
        )
        if compatible:
            return compatible
        embedding_error = "No vectors exist in the active embedding space."
    except Exception as exc:  # noqa: BLE001 - provider/store outages deliberately degrade to lexical retrieval
        embedding_error = str(exc)

    chunks = (
        db.query(PaperChunk)
        .filter(PaperChunk.paper_id == paper_id)
        .order_by(PaperChunk.analysis_generation.desc(), PaperChunk.chunk_index.asc())
        .all()
    )
    if chunks:
        newest_generation = max(chunk.analysis_generation for chunk in chunks)
        chunks = [chunk for chunk in chunks if chunk.analysis_generation == newest_generation]
    selected, fallback = lexical_chunks(query, chunks, limit=limit)
    record_fallback(
        "retrieval.paper_chunks",
        fallback,
        embedding_error or "Compatible vector retrieval returned no chunks.",
        {"paper_id": paper_id, "limit": limit},
    )
    return selected
