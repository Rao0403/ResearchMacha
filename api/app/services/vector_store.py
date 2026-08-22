from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.paper import PaperChunk, ResearchMemory
from app.services.fallbacks import record_fallback
from app.services.retrieval import cosine_similarity, top_k_chunks

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

    def upsert_memories(self, memories: list[ResearchMemory]) -> None:
        raise NotImplementedError

    def delete_memory(self, memory_id: str) -> None:
        raise NotImplementedError

    def search_memories(
        self,
        db: Session,
        query_embedding: list[float],
        scope: str | None = None,
        limit: int = 5,
    ) -> list[ResearchMemory]:
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

    def upsert_memories(self, memories: list[ResearchMemory]) -> None:
        return None

    def delete_memory(self, memory_id: str) -> None:
        return None

    def search_memories(
        self,
        db: Session,
        query_embedding: list[float],
        scope: str | None = None,
        limit: int = 5,
    ) -> list[ResearchMemory]:
        query = db.query(ResearchMemory).filter(ResearchMemory.status == "active")
        if scope:
            query = query.filter(ResearchMemory.scope == scope)
        memories = query.order_by(ResearchMemory.updated_at.desc()).all()
        ranked = sorted(
            memories,
            key=lambda memory: (
                cosine_similarity(query_embedding, memory.embedding or []),
                memory.importance,
            ),
            reverse=True,
        )
        return ranked[:limit]


class QdrantVectorStore:
    name = "qdrant"

    def __init__(self) -> None:
        if QdrantClient is None or qmodels is None:
            raise RuntimeError("qdrant-client is not installed")
        settings = get_settings()
        self.collection = settings.qdrant_collection
        self.memory_collection = settings.qdrant_memory_collection
        self.vector_size = settings.qdrant_vector_size
        self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)

    def upsert_chunks(self, chunks: list[PaperChunk]) -> None:
        ready_chunks = [chunk for chunk in chunks if chunk.embedding]
        if not ready_chunks:
            return

        vector_size = self.vector_size or len(ready_chunks[0].embedding or [])
        self.ensure_collection(self.collection, vector_size)
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

        self.ensure_collection(self.collection, self.vector_size or len(query_embedding))
        points = self.query_points(self.collection, query_embedding, limit, self.paper_filter(paper_id))
        chunk_ids = [self.extract_chunk_id(point) for point in points]
        chunk_ids = [chunk_id for chunk_id in chunk_ids if chunk_id]
        if not chunk_ids:
            return []

        chunks = db.query(PaperChunk).filter(PaperChunk.id.in_(chunk_ids)).all()
        chunks_by_id = {chunk.id: chunk for chunk in chunks}
        ordered_chunks = [chunks_by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in chunks_by_id]
        return ordered_chunks

    def upsert_memories(self, memories: list[ResearchMemory]) -> None:
        ready_memories = [memory for memory in memories if memory.embedding]
        if not ready_memories:
            return

        vector_size = self.vector_size or len(ready_memories[0].embedding or [])
        self.ensure_collection(self.memory_collection, vector_size)
        points = [
            qmodels.PointStruct(
                id=memory.id,
                vector=memory.embedding,
                payload={
                    "memory_id": memory.id,
                    "scope": memory.scope,
                    "memory_type": memory.memory_type,
                    "project_id": memory.project_id,
                    "paper_id": memory.paper_id,
                    "importance": memory.importance,
                    "source": memory.source,
                },
            )
            for memory in ready_memories
        ]
        self.client.upsert(collection_name=self.memory_collection, points=points)

    def delete_memory(self, memory_id: str) -> None:
        if not self.client.collection_exists(collection_name=self.memory_collection):
            return
        self.client.delete(
            collection_name=self.memory_collection,
            points_selector=qmodels.FilterSelector(filter=self.memory_id_filter(memory_id)),
        )

    def search_memories(
        self,
        db: Session,
        query_embedding: list[float],
        scope: str | None = None,
        limit: int = 5,
    ) -> list[ResearchMemory]:
        if not query_embedding:
            return []

        self.ensure_collection(self.memory_collection, self.vector_size or len(query_embedding))
        points = self.query_points(self.memory_collection, query_embedding, limit, self.memory_scope_filter(scope))
        memory_ids = [self.extract_memory_id(point) for point in points]
        memory_ids = [memory_id for memory_id in memory_ids if memory_id]
        if not memory_ids:
            return []

        memories = db.query(ResearchMemory).filter(ResearchMemory.id.in_(memory_ids)).all()
        memories_by_id = {memory.id: memory for memory in memories if memory.status == "active"}
        return [memories_by_id[memory_id] for memory_id in memory_ids if memory_id in memories_by_id]

    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        if self.client.collection_exists(collection_name=collection_name):
            return
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
        )

    def query_points(
        self,
        collection_name: str,
        query_embedding: list[float],
        limit: int,
        query_filter: Any | None = None,
    ) -> list[Any]:
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=collection_name,
                query=query_embedding,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            return list(response.points)
        return list(
            self.client.search(
                collection_name=collection_name,
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

    def memory_scope_filter(self, scope: str | None) -> Any | None:
        if not scope:
            return None
        return qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="scope",
                    match=qmodels.MatchValue(value=scope),
                )
            ]
        )

    def memory_id_filter(self, memory_id: str) -> Any:
        return qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="memory_id",
                    match=qmodels.MatchValue(value=memory_id),
                )
            ]
        )

    def extract_chunk_id(self, point: Any) -> str | None:
        payload = getattr(point, "payload", None) or {}
        return payload.get("chunk_id") or str(getattr(point, "id", "")) or None

    def extract_memory_id(self, point: Any) -> str | None:
        payload = getattr(point, "payload", None) or {}
        return payload.get("memory_id") or str(getattr(point, "id", "")) or None


class FallbackVectorStore:
    name = "fallback"

    def __init__(self, primary: VectorStore, fallback: VectorStore | None = None) -> None:
        self.primary = primary
        self.fallback = fallback or MySQLVectorStore()

    def upsert_chunks(self, chunks: list[PaperChunk]) -> None:
        try:
            self.primary.upsert_chunks(chunks)
        except Exception as exc:
            record_fallback(
                "vector_store.upsert_chunks",
                f"{self.fallback.name}.upsert_chunks",
                str(exc),
                {"primary": self.primary.name, "chunk_count": len(chunks)},
            )
            self.fallback.upsert_chunks(chunks)

    def delete_paper_chunks(self, paper_id: str) -> None:
        try:
            self.primary.delete_paper_chunks(paper_id)
        except Exception as exc:
            record_fallback(
                "vector_store.delete_paper_chunks",
                f"{self.fallback.name}.delete_paper_chunks",
                str(exc),
                {"primary": self.primary.name, "paper_id": paper_id},
            )
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
            record_fallback(
                "vector_store.search_paper_chunks",
                f"{self.fallback.name}.search_paper_chunks",
                "Primary vector store returned no chunks.",
                {"primary": self.primary.name, "paper_id": paper_id, "limit": limit},
            )
        except Exception as exc:
            record_fallback(
                "vector_store.search_paper_chunks",
                f"{self.fallback.name}.search_paper_chunks",
                str(exc),
                {"primary": self.primary.name, "paper_id": paper_id, "limit": limit},
            )
        return self.fallback.search_paper_chunks(db, paper_id, query_embedding, limit)

    def upsert_memories(self, memories: list[ResearchMemory]) -> None:
        try:
            self.primary.upsert_memories(memories)
        except Exception as exc:
            record_fallback(
                "vector_store.upsert_memories",
                f"{self.fallback.name}.upsert_memories",
                str(exc),
                {"primary": self.primary.name, "memory_count": len(memories)},
            )
            self.fallback.upsert_memories(memories)

    def delete_memory(self, memory_id: str) -> None:
        try:
            self.primary.delete_memory(memory_id)
        except Exception as exc:
            record_fallback(
                "vector_store.delete_memory",
                f"{self.fallback.name}.delete_memory",
                str(exc),
                {"primary": self.primary.name, "memory_id": memory_id},
            )
            self.fallback.delete_memory(memory_id)

    def search_memories(
        self,
        db: Session,
        query_embedding: list[float],
        scope: str | None = None,
        limit: int = 5,
    ) -> list[ResearchMemory]:
        try:
            results = self.primary.search_memories(db, query_embedding, scope, limit)
            if results:
                return results
            record_fallback(
                "vector_store.search_memories",
                f"{self.fallback.name}.search_memories",
                "Primary vector store returned no memories.",
                {"primary": self.primary.name, "scope": scope, "limit": limit},
            )
        except Exception as exc:
            record_fallback(
                "vector_store.search_memories",
                f"{self.fallback.name}.search_memories",
                str(exc),
                {"primary": self.primary.name, "scope": scope, "limit": limit},
            )
        return self.fallback.search_memories(db, query_embedding, scope, limit)


@lru_cache
def get_vector_store() -> VectorStore:
    settings = get_settings()
    if settings.vector_provider == "qdrant":
        try:
            return FallbackVectorStore(QdrantVectorStore())
        except Exception as exc:
            record_fallback("vector_store.provider", "mysql", str(exc), {"vector_provider": settings.vector_provider})
            return MySQLVectorStore()
    return MySQLVectorStore()
