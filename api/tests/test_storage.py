from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from pypdf import PdfWriter

from app.services import storage


class FakeSettings:
    def __init__(self, upload_dir: Path) -> None:
        self.resolved_upload_dir = upload_dir
        self.max_upload_bytes = 50_000_000
        self.max_pdf_pages = 500


class FakeResponse:
    headers = {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self):
        yield b"%PDF-1.7"


def test_save_remote_pdf_follows_redirects(monkeypatch, tmp_path) -> None:
    calls = []

    def fake_stream(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(storage, "settings", FakeSettings(tmp_path))
    monkeypatch.setattr(storage.httpx, "stream", fake_stream)
    monkeypatch.setattr(storage, "PdfReader", lambda path: SimpleNamespace(pages=[object()]))

    saved_path = storage.save_remote_pdf("https://arxiv.org/pdf/2606.05868v1.pdf", "paper.pdf")

    assert Path(saved_path).read_bytes() == b"%PDF-1.7"
    assert calls[0]["follow_redirects"] is True


def test_upload_stream_is_bounded_and_interrupted_files_are_removed(monkeypatch, tmp_path) -> None:
    settings = FakeSettings(tmp_path)
    settings.max_upload_bytes = 8
    monkeypatch.setattr(storage, "settings", settings)
    oversized = UploadFile(filename="large.pdf", file=BytesIO(b"%PDF-1.7 too large"))

    with pytest.raises(storage.PdfTooLargeError):
        storage.stage_upload_pdf(oversized)

    assert list(tmp_path.iterdir()) == []

    settings.max_upload_bytes = 50_000_000
    interrupted = UploadFile(filename="partial.pdf", file=InterruptedStream())
    with pytest.raises(storage.PdfStreamError):
        storage.stage_upload_pdf(interrupted)
    assert list(tmp_path.iterdir()) == []


def test_page_limit_is_enforced_before_publish(monkeypatch, tmp_path) -> None:
    settings = FakeSettings(tmp_path)
    settings.max_pdf_pages = 1
    monkeypatch.setattr(storage, "settings", settings)
    upload = UploadFile(filename="two-pages.pdf", file=BytesIO(pdf_bytes(page_count=2)))

    with pytest.raises(storage.PdfIngestionError, match="page limit"):
        storage.stage_upload_pdf(upload)

    assert list(tmp_path.iterdir()) == []


def test_remote_content_length_limit_is_enforced_without_partial_file(monkeypatch, tmp_path) -> None:
    settings = FakeSettings(tmp_path)
    settings.max_upload_bytes = 10
    monkeypatch.setattr(storage, "settings", settings)
    response = FakeResponse()
    response.headers = {"content-length": "11"}
    monkeypatch.setattr(storage.httpx, "stream", lambda *args, **kwargs: response)

    with pytest.raises(storage.PdfTooLargeError):
        storage.stage_remote_pdf("https://example.test/paper.pdf", "paper.pdf")

    assert list(tmp_path.iterdir()) == []


class InterruptedStream:
    def __init__(self) -> None:
        self.calls = 0

    def read(self, size: int = -1) -> bytes:
        self.calls += 1
        if self.calls == 1:
            return b"%PDF-1.7 partial"
        raise OSError("connection interrupted")


def pdf_bytes(page_count: int = 1) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    writer.write(output)
    return output.getvalue()
