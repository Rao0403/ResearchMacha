from types import SimpleNamespace

from app.services.retrieval import cosine_similarity
from app.services.vector_store import FallbackVectorStore, MySQLVectorStore


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

    results = MySQLVectorStore().search_paper_chunks(FakeDb(chunks), "paper-1", [1.0, 0.0], limit=1)

    assert results[0].id == "high"


def test_vector_store_fallback_uses_mysql_when_primary_fails() -> None:
    chunks = [
        SimpleNamespace(id="low", paper_id="paper-1", chunk_index=0, embedding=[0.0, 1.0]),
        SimpleNamespace(id="high", paper_id="paper-1", chunk_index=1, embedding=[1.0, 0.0]),
    ]
    store = FallbackVectorStore(FailingVectorStore(), fallback=MySQLVectorStore())

    results = store.search_paper_chunks(FakeDb(chunks), "paper-1", [1.0, 0.0], limit=1)

    assert results[0].id == "high"


def test_mysql_vector_store_returns_top_matching_memories() -> None:
    memories = [
        SimpleNamespace(id="low", scope="user", status="active", importance=1, embedding=[0.0, 1.0]),
        SimpleNamespace(id="high", scope="user", status="active", importance=1, embedding=[1.0, 0.0]),
    ]

    results = MySQLVectorStore().search_memories(FakeDb(memories), [1.0, 0.0], scope="user", limit=1)

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

    def search_paper_chunks(self, db, paper_id, query_embedding, limit=4):
        raise RuntimeError("primary unavailable")

    def upsert_memories(self, memories):
        raise RuntimeError("primary unavailable")

    def delete_memory(self, memory_id):
        raise RuntimeError("primary unavailable")

    def search_memories(self, db, query_embedding, scope=None, limit=5):
        raise RuntimeError("primary unavailable")
