from types import SimpleNamespace

import pytest

from app.ai import LangChainProvider, MockProvider
from app.models.paper import Paper, PaperChunk
from app.services.fallbacks import clear_fallback_events, pop_fallback_events
from app.services.retrieval import cosine_similarity, lexical_chunks, retrieve_paper_chunks
from app.services.vector_store import FallbackVectorStore, MySQLVectorStore, QdrantVectorStore


def test_cosine_similarity_orders_identical_vectors_highest() -> None:
    left = [1.0, 0.0, 0.0]
    right = [1.0, 0.0, 0.0]
    opposite = [0.0, 1.0, 0.0]

    assert cosine_similarity(left, right) > cosine_similarity(left, opposite)


def test_mysql_vector_store_returns_top_matching_chunks() -> None:
    chunks = [
        SimpleNamespace(id="low", paper_id="paper-1", chunk_index=0, embedding=[0.0, 1.0]),
        SimpleNamespace(id="high", paper_id="paper-1", chunk_index=1, embedding=[1.0, 0.0]),
    ]

    results = MySQLVectorStore().search_paper_chunks(
        FakeDb(chunks), "paper-1", [1.0, 0.0], "mock:hash-v1:2", limit=1
    )

    assert results[0].id == "high"


def test_vector_store_fallback_uses_mysql_when_primary_fails() -> None:
    chunks = [
        SimpleNamespace(id="low", paper_id="paper-1", chunk_index=0, embedding=[0.0, 1.0]),
        SimpleNamespace(id="high", paper_id="paper-1", chunk_index=1, embedding=[1.0, 0.0]),
    ]
    store = FallbackVectorStore(FailingVectorStore(), fallback=MySQLVectorStore())

    results = store.search_paper_chunks(
        FakeDb(chunks), "paper-1", [1.0, 0.0], "mock:hash-v1:2", limit=1
    )

    assert results[0].id == "high"


def test_mysql_vector_store_returns_top_matching_memories() -> None:
    memories = [
        SimpleNamespace(id="low", scope="user", status="active", importance=1, embedding=[0.0, 1.0]),
        SimpleNamespace(id="high", scope="user", status="active", importance=1, embedding=[1.0, 0.0]),
    ]

    results = MySQLVectorStore().search_memories(
        FakeDb(memories), [1.0, 0.0], "mock:hash-v1:2", scope="user", limit=1
    )

    assert results[0].id == "high"


class FakeQuery:
    def __init__(self, chunks):
        self.chunks = chunks

    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return self.chunks


class FakeDb:
    def __init__(self, chunks):
        self.chunks = chunks

    def query(self, model):
        return FakeQuery(self.chunks)


class FailingVectorStore:
    name = "failing"

    def upsert_chunks(self, chunks):
        raise RuntimeError("primary unavailable")

    def delete_paper_chunks(self, paper_id):
        raise RuntimeError("primary unavailable")

    def delete_chunks(self, chunks):
        raise RuntimeError("primary unavailable")

    def search_paper_chunks(self, db, paper_id, query_embedding, embedding_fingerprint, limit=4):
        raise RuntimeError("primary unavailable")

    def upsert_memories(self, memories):
        raise RuntimeError("primary unavailable")

    def delete_memory(self, memory_id):
        raise RuntimeError("primary unavailable")

    def search_memories(self, db, query_embedding, embedding_fingerprint, scope=None, limit=5):
        raise RuntimeError("primary unavailable")


def test_mock_embeddings_are_explicitly_fingerprinted() -> None:
    result = MockProvider().embed_texts(["evidence"])

    assert result.fingerprint.startswith("mock:hash-v1:")
    assert result.dimension == len(result.vectors[0])


def test_provider_embedding_failure_does_not_return_hash_vectors() -> None:
    provider = object.__new__(LangChainProvider)
    provider.embedding_model = FailingEmbeddingModel()
    provider.embedding_fingerprint = "ollama:test-model"

    with pytest.raises(RuntimeError, match="provider unavailable"):
        provider.embed_texts(["evidence"])


def test_mysql_vector_store_never_mixes_embedding_spaces(db_session) -> None:
    paper = Paper(source="upload", title="Paper", authors=[], pdf_path="paper.pdf", status="ready")
    db_session.add(paper)
    db_session.flush()
    db_session.add_all(
        [
            PaperChunk(
                paper_id=paper.id,
                chunk_index=0,
                page_start=1,
                page_end=1,
                text="compatible",
                embedding=[1.0, 0.0],
                embedding_fingerprint="openai:model-a",
                embedding_dim=2,
            ),
            PaperChunk(
                paper_id=paper.id,
                chunk_index=1,
                page_start=2,
                page_end=2,
                text="incompatible",
                embedding=[1.0, 0.0, 0.0],
                embedding_fingerprint="ollama:model-b",
                embedding_dim=3,
            ),
        ]
    )
    db_session.commit()

    results = MySQLVectorStore().search_paper_chunks(
        db_session, paper.id, [1.0, 0.0], "openai:model-a", limit=4
    )

    assert [chunk.text for chunk in results] == ["compatible"]


def test_lexical_fallback_prefers_keyword_overlap() -> None:
    chunks = [
        SimpleNamespace(text="unrelated graph theory", chunk_index=0),
        SimpleNamespace(text="retrieval improves grounded factuality", chunk_index=1),
    ]

    selected, fallback = lexical_chunks("retrieval factuality", chunks, limit=1)

    assert selected[0].chunk_index == 1
    assert fallback == "lexical_overlap"


def test_retrieval_uses_initial_chunks_and_records_warning_when_no_terms_match(db_session, monkeypatch) -> None:
    paper = Paper(source="upload", title="Paper", authors=[], pdf_path="paper.pdf", status="ready")
    db_session.add(paper)
    db_session.flush()
    db_session.add(
        PaperChunk(
            paper_id=paper.id,
            chunk_index=0,
            page_start=1,
            page_end=1,
            text="alpha beta",
            embedding=None,
        )
    )
    db_session.commit()
    monkeypatch.setattr("app.services.retrieval.get_ai_provider", lambda: FailingProvider())
    clear_fallback_events()

    selected = retrieve_paper_chunks(db_session, paper.id, "zzz", limit=1)
    events = pop_fallback_events()

    assert [chunk.text for chunk in selected] == ["alpha beta"]
    assert events[-1]["fallback"] == "initial_chunks"


def test_qdrant_collection_names_are_namespaced_by_fingerprint() -> None:
    first = QdrantVectorStore.collection_for("chunks", "openai:model-a")
    second = QdrantVectorStore.collection_for("chunks", "ollama:model-b")

    assert first.startswith("chunks_")
    assert first != second


class FailingEmbeddingModel:
    def embed_documents(self, texts):
        raise RuntimeError("provider unavailable")


class FailingProvider:
    def embed_texts(self, texts):
        raise RuntimeError("provider unavailable")
