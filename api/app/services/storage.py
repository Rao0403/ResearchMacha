from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import httpx
from fastapi import UploadFile
from pypdf import PdfReader

from app.core.config import get_settings

settings = get_settings()

DEFAULT_MAX_UPLOAD_BYTES = 50_000_000
DEFAULT_MAX_PDF_PAGES = 500
STREAM_CHUNK_BYTES = 64 * 1024


class PdfIngestionError(ValueError):
    status_code = 422
    code = "invalid_pdf"


class PdfTooLargeError(PdfIngestionError):
    status_code = 413
    code = "pdf_too_large"


class PdfStreamError(PdfIngestionError):
    status_code = 422
    code = "incomplete_pdf"


@dataclass
class StagedPdf:
    staged_path: Path
    final_path: Path
    byte_count: int = 0
    page_count: int = 0
    published: bool = False

    def publish(self) -> str:
        self.final_path.parent.mkdir(parents=True, exist_ok=True)
        self.staged_path.replace(self.final_path)
        self.published = True
        return str(self.final_path)

    def cleanup(self) -> None:
        self.staged_path.unlink(missing_ok=True)
        if self.published:
            self.final_path.unlink(missing_ok=True)
            self.published = False


def ensure_storage_dirs() -> None:
    settings.resolved_upload_dir.mkdir(parents=True, exist_ok=True)


def stage_upload_pdf(file: UploadFile) -> StagedPdf:
    return _stage_stream(file.file, f"{uuid.uuid4()}.pdf")


def stage_remote_pdf(url: str, filename: str) -> StagedPdf:
    ensure_storage_dirs()
    safe_name = Path(filename).name
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{safe_name}.pdf"
    staged = _new_staged_pdf(safe_name)
    try:
        with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
            response.raise_for_status()
            content_length = getattr(response, "headers", {}).get("content-length")
            if content_length and int(content_length) > max_upload_bytes():
                raise PdfTooLargeError(f"PDF exceeds the {max_upload_bytes()} byte limit")
            byte_count = _write_bounded(response.iter_bytes(), staged.staged_path)
        return _validate_staged_pdf(staged, byte_count)
    except PdfIngestionError:
        staged.cleanup()
        raise
    except Exception as exc:
        staged.cleanup()
        raise PdfStreamError("Remote PDF download was interrupted or invalid") from exc


def save_remote_pdf(url: str, filename: str) -> str:
    staged = stage_remote_pdf(url, filename)
    try:
        return staged.publish()
    except Exception:
        staged.cleanup()
        raise


def max_upload_bytes() -> int:
    return int(getattr(settings, "max_upload_bytes", DEFAULT_MAX_UPLOAD_BYTES))


def max_pdf_pages() -> int:
    return int(getattr(settings, "max_pdf_pages", DEFAULT_MAX_PDF_PAGES))


def _stage_stream(stream: BinaryIO, final_name: str) -> StagedPdf:
    ensure_storage_dirs()
    staged = _new_staged_pdf(final_name)
    try:
        byte_count = _write_bounded(iter(lambda: stream.read(STREAM_CHUNK_BYTES), b""), staged.staged_path)
        return _validate_staged_pdf(staged, byte_count)
    except PdfIngestionError:
        staged.cleanup()
        raise
    except Exception as exc:
        staged.cleanup()
        raise PdfStreamError("PDF upload was interrupted or invalid") from exc


def _new_staged_pdf(final_name: str) -> StagedPdf:
    final_path = settings.resolved_upload_dir / final_name
    if final_path.exists():
        final_path = settings.resolved_upload_dir / f"{uuid.uuid4()}-{final_name}"
    return StagedPdf(
        staged_path=settings.resolved_upload_dir / f"{uuid.uuid4()}.part",
        final_path=final_path,
    )


def _write_bounded(chunks: Iterable[bytes], destination: Path) -> int:
    byte_count = 0
    with destination.open("wb") as handle:
        for chunk in chunks:
            if not chunk:
                continue
            byte_count += len(chunk)
            if byte_count > max_upload_bytes():
                raise PdfTooLargeError(f"PDF exceeds the {max_upload_bytes()} byte limit")
            handle.write(chunk)
    return byte_count


def _validate_staged_pdf(staged: StagedPdf, byte_count: int) -> StagedPdf:
    if byte_count == 0:
        raise PdfIngestionError("PDF is empty")
    with staged.staged_path.open("rb") as handle:
        if b"%PDF-" not in handle.read(1024):
            raise PdfIngestionError("PDF header was not found within the first 1024 bytes")
    try:
        page_count = len(PdfReader(staged.staged_path).pages)
    except Exception as exc:  # pypdf exposes several parser-specific exception types
        raise PdfIngestionError("PDF is malformed or unreadable") from exc
    if page_count == 0:
        raise PdfIngestionError("PDF contains no pages")
    if page_count > max_pdf_pages():
        raise PdfIngestionError(f"PDF exceeds the {max_pdf_pages()} page limit")
    staged.byte_count = byte_count
    staged.page_count = page_count
    return staged
