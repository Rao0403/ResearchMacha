from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import httpx
from fastapi import UploadFile

from app.core.config import get_settings

settings = get_settings()


def ensure_storage_dirs() -> None:
    settings.resolved_upload_dir.mkdir(parents=True, exist_ok=True)


def save_upload_file(file: UploadFile) -> str:
    ensure_storage_dirs()
    suffix = Path(file.filename or "paper.pdf").suffix or ".pdf"
    destination = settings.resolved_upload_dir / f"{uuid.uuid4()}{suffix}"
    with destination.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    return str(destination)


def save_remote_pdf(url: str, filename: str) -> str:
    ensure_storage_dirs()
    destination = settings.resolved_upload_dir / filename
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
    return str(destination)
