from app.services.pdf import chunk_pages


def test_chunk_pages_preserves_page_bounds() -> None:
    pages = [
        {"page_number": 1, "text": "Intro paragraph.\n\nMore intro."},
        {"page_number": 2, "text": "Method paragraph.\n\nResults paragraph."},
    ]

    chunks = chunk_pages(pages, max_chars=40)

    assert chunks
    assert chunks[0]["page_start"] == 1
    assert chunks[-1]["page_end"] == 2

