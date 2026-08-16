from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.paper import PaperChunk
from app.services.retrieval import top_k_chunks

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels
except ImportError:  # pragma: no cover - exercised only when qdrant-client is not installed
    QdrantClient = None
    qmodels = None


class VectorStore(Protocol):
    name: str

    def upsert_chunks(self, chunks: list[PaperChunk]) -> None:
        raise NotImplementedError

    def delete_paper_chunks(self, paper_id: str) -> None:
        raise NotImplementedError

    def search_paper_chunks(
        self,
        db: Session,
        paper_id: str,
        query_embedding: list[float],
        limit: int = 4,
    ) -> list[PaperChunk]:
        raise NotImplementedError


class MySQLVectorStore:
    name = "mysql"

    def upsert_chunks(self, chunks: list[PaperChunk]) -> None:
        return None

    def delete_paper_chunks(self, paper_id: str) -> None:
        return None

    def search_paper_chunks(
        self,
        db: Session,
        paper_id: str,
        query_embedding: list[float],
        limit: int = 4,
    ) -> list[PaperChunk]:
        chunks = (
            db.query(PaperChunk)
            .filter(PaperChunk.paper_id == paper_id)
            .order_by(PaperChunk.chunk_index.asc())
            .all()
        )
        return top_k_chunks(query_embedding, chunks, limit=limit)


class QdrantVectorStore:
    name = "qdrant"

    def __init__(self) -> None:
        if QdrantClient is None or qmodels is None:
            raise RuntimeError("qdrant-client is not installed")
        settings = get_settings()
        self.collection = settings.qdrant_collection
        self.vector_size = settings.qdrant_vector_size
        self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)

    def upsert_chunks(self, chunks: list[PaperChunk]) -> None:
        ready_chunks = [chunk for chunk in chunks if chunk.embedding]
        if not ready_chunks:
            return

        vector_size = self.vector_size or len(ready_chunks[0].embedding or [])
        self.ensure_collection(vector_size)
        points = [
            qmodels.PointStruct(
                id=chunk.id,
                vector=chunk.embedding,
                payload={
                    "paper_id": chunk.paper_id,
                    "chunk_id": chunk.id,
                    "chunk_index": chunk.chunk_index,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "section_label": chunk.section_label,
                },
            )
            for chunk in ready_chunks
        ]
        self.client.upsert(collection_name=self.collection, points=points)

    def delete_paper_chunks(self, paper_id: str) -> None:
        if not self.client.collection_exists(collection_name=self.collection):
            return
        self.client.delete(
            collection_name=self.collection,
            points_selector=qmodels.FilterSelector(filter=self.paper_filter(paper_id)),
        )

    def search_paper_chunks(
        self,
        db: Session,
        paper_id: str,
        query_embedding: list[float],
        limit: int = 4,
    ) -> list[PaperChunk]:
        if not query_embedding:
            return []

        self.ensure_collection(self.vector_size or len(query_embedding))
        points = self.query_points(paper_id, query_embedding, limit)
        chunk_ids = [self.extract_chunk_id(point) for point in points]
        chunk_ids = [chunk_id for chunk_id in chunk_ids if chunk_id]
        if not chunk_ids:
            return MySQLVectorStore().search_paper_chunks(db, paper_id, query_embedding, limit)

        chunks = db.query(PaperChunk).filter(PaperChunk.id.in_(chunk_ids)).all()
        chunks_by_id = {chunk.id: chunk for chunk in chunks}
        ordered_chunks = [chunks_by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in chunks_by_id]
        if not ordered_chunks:
            return MySQLVectorStore().search_paper_chunks(db, paper_id, query_embedding, limit)
        return ordered_chunks

    def ensure_collection(self, vector_size: int) -> None:
        if self.client.collection_exists(collection_name=self.collection):
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
        )

    def query_points(self, paper_id: str, query_embedding: list[float], limit: int) -> list[Any]:
        query_filter = self.paper_filter(paper_id)
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=self.collection,
                query=query_embedding,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            return list(response.points)
        return list(
            self.client.search(
                collection_name=self.collection,
                query_vector=query_embedding,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
        )

    def paper_filter(self, paper_id: str) -> Any:
        return qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="paper_id",
                    match=qmodels.MatchValue(value=paper_id),
                )
            ]
        )

    def extract_chunk_id(self, point: Any) -> str | None:
        payload = getattr(point, "payload", None) or {}
        return payload.get("chunk_id") or str(getattr(point, "id", "")) or None


class FallbackVectorStore:
    name = "fallback"

    def __init__(self, primary: VectorStore, fallback: VectorStore | None = None) -> None:
        self.primary = primary
        self.fallback = fallback or MySQLVectorStore()

    def upsert_chunks(self, chunks: list[PaperChunk]) -> None:
        try:
            self.primary.upsert_chunks(chunks)
        except Exception:
            self.fallback.upsert_chunks(chunks)

    def delete_paper_chunks(self, paper_id: str) -> None:
        try:
            self.primary.delete_paper_chunks(paper_id)
        except Exception:
            self.fallback.delete_paper_chunks(paper_id)

    def search_paper_chunks(
        self,
        db: Session,
        paper_id: str,
        query_embedding: list[float],
        limit: int = 4,
    ) -> list[PaperChunk]:
        try:
            results = self.primary.search_paper_chunks(db, paper_id, query_embedding, limit)
            if results:
                return results
        except Exception:
            pass
        return self.fallback.search_paper_chunks(db, paper_id, query_embedding, limit)


@lru_cache
def get_vector_store() -> VectorStore:
    settings = get_settings()
    if settings.vector_provider == "qdrant":
        try:
            return FallbackVectorStore(QdrantVectorStore())
        except Exception:
            return MySQLVectorStore()
    return MySQLVectorStore()
