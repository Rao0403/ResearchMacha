from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthcheck(api_client: TestClient) -> None:
    response = api_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_research_project(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/research-projects",
        json={"question": "How can retrieval improve factual question answering?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "draft"
    assert payload["question"] == "How can retrieval improve factual question answering?"
