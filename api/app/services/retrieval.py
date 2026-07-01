from __future__ import annotations

import math

from app.models.paper import PaperChunk


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

