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
    buffer: list[str] = []
    page_start = None
    page_end = None

    def flush() -> None:
        nonlocal buffer, page_start, page_end
        text = "\n\n".join(buffer).strip()
        if text:
            chunks.append(
                {
                    "page_start": page_start or 1,
                    "page_end": page_end or page_start or 1,
                    "section_label": None,
                    "text": text,
                }
            )
        buffer = []
        page_start = None
        page_end = None

    for page in pages:
        page_number = int(page["page_number"])
        paragraphs = [part.strip() for part in str(page["text"]).split("\n\n") if part.strip()]
        for paragraph in paragraphs:
            prospective = "\n\n".join(buffer + [paragraph]).strip()
            if buffer and len(prospective) > max_chars:
                flush()
            if page_start is None:
                page_start = page_number
            page_end = page_number
            buffer.append(paragraph)

    flush()
    return chunks

