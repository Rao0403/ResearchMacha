from app.services.retrieval import cosine_similarity


def test_cosine_similarity_orders_identical_vectors_highest() -> None:
    left = [1.0, 0.0, 0.0]
    right = [1.0, 0.0, 0.0]
    opposite = [0.0, 1.0, 0.0]

    assert cosine_similarity(left, right) > cosine_similarity(left, opposite)

