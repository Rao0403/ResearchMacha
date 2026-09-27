from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.api.routes import papers as paper_routes
from app.models.paper import Job, Paper
from app.services import storage


def pdf_bytes(page_count: int = 1) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    ("filename", "content", "expected_code"),
    [
        ("empty.pdf", b"", "invalid_pdf"),
        ("spoofed.pdf", b"This is not a PDF", "invalid_pdf"),
        ("malformed.pdf", b"%PDF-1.7 malformed", "invalid_pdf"),
    ],
)
def test_invalid_pdf_uploads_create_no_state(
    api_client: TestClient,
    db_session,
    tmp_path,
    filename: str,
    content: bytes,
    expected_code: str,
) -> None:
    response = api_client.post(
        "/api/papers/upload",
        files={"file": (filename, content, "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == expected_code
    assert db_session.query(Paper).count() == 0
    assert db_session.query(Job).count() == 0
    assert list(tmp_path.iterdir()) == []


def test_oversized_upload_returns_413_and_creates_no_state(api_client, db_session, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(storage.settings, "max_upload_bytes", 20, raising=False)

    response = api_client.post(
        "/api/papers/upload",
        files={"file": ("large.pdf", pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "pdf_too_large"
    assert db_session.query(Paper).count() == 0
    assert list(tmp_path.iterdir()) == []


def test_over_page_limit_upload_is_rejected(api_client, db_session, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(storage.settings, "max_pdf_pages", 1, raising=False)

    response = api_client.post(
        "/api/papers/upload",
        files={"file": ("two-pages.pdf", pdf_bytes(2), "application/pdf")},
    )

    assert response.status_code == 422
    assert "page limit" in response.json()["detail"]["message"]
    assert db_session.query(Paper).count() == 0
    assert list(tmp_path.iterdir()) == []


def test_metadata_is_validated_before_file_staging(api_client, db_session, tmp_path) -> None:
    response = api_client.post(
        "/api/papers/upload",
        data={"title": "x" * 513},
        files={"file": ("valid.pdf", pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_metadata"
    assert db_session.query(Paper).count() == 0
    assert list(tmp_path.iterdir()) == []


def test_mixed_validity_batch_is_atomic(api_client, db_session, tmp_path) -> None:
    response = api_client.post(
        "/api/papers/batch-upload",
        files=[
            ("files", ("valid.pdf", pdf_bytes(), "application/pdf")),
            ("files", ("invalid.pdf", b"not a pdf", "application/pdf")),
        ],
    )

    assert response.status_code == 422
    assert db_session.query(Paper).count() == 0
    assert db_session.query(Job).count() == 0
    assert list(tmp_path.iterdir()) == []


def test_batch_file_count_limit_is_checked_before_staging(api_client, db_session, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(paper_routes.settings, "max_batch_files", 1)

    response = api_client.post(
        "/api/papers/batch-upload",
        files=[
            ("files", ("first.pdf", pdf_bytes(), "application/pdf")),
            ("files", ("second.pdf", pdf_bytes(), "application/pdf")),
        ],
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "batch_too_large"
    assert db_session.query(Paper).count() == 0
    assert db_session.query(Job).count() == 0
    assert list(tmp_path.iterdir()) == []


def test_database_failure_removes_published_file(api_client, db_session, monkeypatch, tmp_path) -> None:
    def fail_persistence(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(paper_routes, "create_uploaded_papers_with_jobs", fail_persistence)

    response = api_client.post(
        "/api/papers/upload",
        files={"file": ("valid.pdf", pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "upload_persistence_failed"
    assert db_session.query(Paper).count() == 0
    assert db_session.query(Job).count() == 0
    assert list(tmp_path.iterdir()) == []


def test_valid_batch_publishes_all_files_and_records_in_one_transaction(api_client, db_session, tmp_path) -> None:
    response = api_client.post(
        "/api/papers/batch-upload",
        files=[
            ("files", ("first.pdf", pdf_bytes(), "application/pdf")),
            ("files", ("second.pdf", pdf_bytes(), "application/pdf")),
        ],
    )

    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
    assert db_session.query(Paper).count() == 2
    assert db_session.query(Job).count() == 2
    assert len(list(tmp_path.glob("*.pdf"))) == 2
    assert list(tmp_path.glob("*.part")) == []
