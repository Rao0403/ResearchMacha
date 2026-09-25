from __future__ import annotations

import hashlib
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

    def delete_chunks(self, chunks: list[PaperChunk]) -> None:
        raise NotImplementedError

    def search_paper_chunks(
        self,
        db: Session,
        paper_id: str,
        query_embedding: list[float],
        embedding_fingerprint: str,
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
        embedding_fingerprint: str,
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

    def delete_chunks(self, chunks: list[PaperChunk]) -> None:
        return None

    def search_paper_chunks(
        self,
        db: Session,
        paper_id: str,
        query_embedding: list[float],
        embedding_fingerprint: str,
        limit: int = 4,
    ) -> list[PaperChunk]:
        chunks = (
            db.query(PaperChunk)
            .filter(
                PaperChunk.paper_id == paper_id,
                PaperChunk.embedding_fingerprint == embedding_fingerprint,
                PaperChunk.embedding_dim == len(query_embedding),
            )
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
        embedding_fingerprint: str,
        scope: str | None = None,
        limit: int = 5,
    ) -> list[ResearchMemory]:
        query = db.query(ResearchMemory).filter(
            ResearchMemory.status == "active",
            ResearchMemory.embedding_fingerprint == embedding_fingerprint,
            ResearchMemory.embedding_dim == len(query_embedding),
        )
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
        fingerprints = {chunk.embedding_fingerprint for chunk in chunks if chunk.embedding and chunk.embedding_fingerprint}
        for fingerprint in fingerprints:
            ready_chunks = [
                chunk for chunk in chunks if chunk.embedding and chunk.embedding_fingerprint == fingerprint
            ]
            vector_size = self.vector_size or len(ready_chunks[0].embedding or [])
            collection = self.collection_for(self.collection, fingerprint)
            self.ensure_collection(collection, vector_size)
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
                        "embedding_fingerprint": fingerprint,
                    },
                )
                for chunk in ready_chunks
            ]
            self.client.upsert(collection_name=collection, points=points)

    def delete_paper_chunks(self, paper_id: str) -> None:
        for collection in self.namespaced_collections(self.collection):
            self.client.delete(
                collection_name=collection,
                points_selector=qmodels.FilterSelector(filter=self.paper_filter(paper_id)),
            )

    def delete_chunks(self, chunks: list[PaperChunk]) -> None:
        fingerprints = {chunk.embedding_fingerprint for chunk in chunks if chunk.embedding_fingerprint}
        for fingerprint in fingerprints:
            ids = [chunk.id for chunk in chunks if chunk.embedding_fingerprint == fingerprint]
            if not ids:
                continue
            collection = self.collection_for(self.collection, fingerprint)
            if self.client.collection_exists(collection_name=collection):
                self.client.delete(
                    collection_name=collection,
                    points_selector=qmodels.PointIdsList(points=ids),
                )

    def search_paper_chunks(
        self,
        db: Session,
        paper_id: str,
        query_embedding: list[float],
        embedding_fingerprint: str,
        limit: int = 4,
    ) -> list[PaperChunk]:
        if not query_embedding:
            return []

        collection = self.collection_for(self.collection, embedding_fingerprint)
        if not self.client.collection_exists(collection_name=collection):
            return []
        points = self.query_points(collection, query_embedding, limit, self.paper_filter(paper_id))
        chunk_ids = [self.extract_chunk_id(point) for point in points]
        chunk_ids = [chunk_id for chunk_id in chunk_ids if chunk_id]
        if not chunk_ids:
            return []

        chunks = db.query(PaperChunk).filter(
            PaperChunk.id.in_(chunk_ids),
            PaperChunk.embedding_fingerprint == embedding_fingerprint,
            PaperChunk.embedding_dim == len(query_embedding),
        ).all()
        chunks_by_id = {chunk.id: chunk for chunk in chunks}
        ordered_chunks = [chunks_by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in chunks_by_id]
        return ordered_chunks

    def upsert_memories(self, memories: list[ResearchMemory]) -> None:
        fingerprints = {memory.embedding_fingerprint for memory in memories if memory.embedding and memory.embedding_fingerprint}
        for fingerprint in fingerprints:
            ready_memories = [
                memory for memory in memories if memory.embedding and memory.embedding_fingerprint == fingerprint
            ]
            vector_size = self.vector_size or len(ready_memories[0].embedding or [])
            collection = self.collection_for(self.memory_collection, fingerprint)
            self.ensure_collection(collection, vector_size)
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
                        "embedding_fingerprint": fingerprint,
                    },
                )
                for memory in ready_memories
            ]
            self.client.upsert(collection_name=collection, points=points)

    def delete_memory(self, memory_id: str) -> None:
        for collection in self.namespaced_collections(self.memory_collection):
            self.client.delete(
                collection_name=collection,
                points_selector=qmodels.FilterSelector(filter=self.memory_id_filter(memory_id)),
            )

    def search_memories(
        self,
        db: Session,
        query_embedding: list[float],
        embedding_fingerprint: str,
        scope: str | None = None,
        limit: int = 5,
    ) -> list[ResearchMemory]:
        if not query_embedding:
            return []

        collection = self.collection_for(self.memory_collection, embedding_fingerprint)
        if not self.client.collection_exists(collection_name=collection):
            return []
        points = self.query_points(collection, query_embedding, limit, self.memory_scope_filter(scope))
        memory_ids = [self.extract_memory_id(point) for point in points]
        memory_ids = [memory_id for memory_id in memory_ids if memory_id]
        if not memory_ids:
            return []

        memories = db.query(ResearchMemory).filter(
            ResearchMemory.id.in_(memory_ids),
            ResearchMemory.embedding_fingerprint == embedding_fingerprint,
            ResearchMemory.embedding_dim == len(query_embedding),
        ).all()
        memories_by_id = {memory.id: memory for memory in memories if memory.status == "active"}
        return [memories_by_id[memory_id] for memory_id in memory_ids if memory_id in memories_by_id]

    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        if self.client.collection_exists(collection_name=collection_name):
            return
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
        )

    @staticmethod
    def collection_for(base_name: str, embedding_fingerprint: str) -> str:
        suffix = hashlib.sha256(embedding_fingerprint.encode("utf-8")).hexdigest()[:12]
        return f"{base_name}_{suffix}"

    def namespaced_collections(self, base_name: str) -> list[str]:
        response = self.client.get_collections()
        return [item.name for item in response.collections if item.name.startswith(f"{base_name}_")]

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

    def delete_chunks(self, chunks: list[PaperChunk]) -> None:
        try:
            self.primary.delete_chunks(chunks)
        except Exception as exc:
            record_fallback(
                "vector_store.delete_chunks",
                f"{self.fallback.name}.delete_chunks",
                str(exc),
                {"primary": self.primary.name, "chunk_count": len(chunks)},
            )
            self.fallback.delete_chunks(chunks)

    def search_paper_chunks(
        self,
        db: Session,
        paper_id: str,
        query_embedding: list[float],
        embedding_fingerprint: str,
        limit: int = 4,
    ) -> list[PaperChunk]:
        try:
            results = self.primary.search_paper_chunks(
                db, paper_id, query_embedding, embedding_fingerprint, limit
            )
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
        return self.fallback.search_paper_chunks(
            db, paper_id, query_embedding, embedding_fingerprint, limit
        )

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
        embedding_fingerprint: str,
        scope: str | None = None,
        limit: int = 5,
    ) -> list[ResearchMemory]:
        try:
            results = self.primary.search_memories(
                db, query_embedding, embedding_fingerprint, scope, limit
            )
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
        return self.fallback.search_memories(
            db, query_embedding, embedding_fingerprint, scope, limit
        )


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
