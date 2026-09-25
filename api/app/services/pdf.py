from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_pdf_pages(pdf_path: str) -> list[dict[str, str | int]]:
    reader = PdfReader(pdf_path)
    pages: list[dict[str, str | int]] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append({"page_number": index, "text": text})
    if not pages:
        raise ValueError("No extractable text was found in the PDF")
    return pages


def chunk_pages(pages: list[dict[str, str | int]], max_chars: int = 1800) -> list[dict[str, str | int | None]]:
    chunks: list[dict[str, str | int | None]] = []
    for page in pages:
        page_number = int(page["page_number"])
        paragraphs = [part.strip() for part in str(page["text"]).split("\n\n") if part.strip()]
        buffer: list[str] = []

        def flush() -> None:
            nonlocal buffer
            text = "\n\n".join(buffer).strip()
            if text:
                chunks.append(
                    {
                        "page_start": page_number,
                        "page_end": page_number,
                        "section_label": None,
                        "text": text,
                    }
                )
            buffer = []

        for paragraph in paragraphs:
            parts = split_oversized_text(paragraph, max_chars)
            for part in parts:
                prospective = "\n\n".join(buffer + [part]).strip()
                if buffer and len(prospective) > max_chars:
                    flush()
                buffer.append(part)
                if len(part) >= max_chars:
                    flush()
        flush()
    return chunks


def split_oversized_text(text: str, max_chars: int) -> list[str]:
    remaining = text.strip()
    parts: list[str] = []
    while len(remaining) > max_chars:
        split_at = remaining.rfind(" ", 0, max_chars + 1)
        if split_at <= 0:
            split_at = max_chars
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts
