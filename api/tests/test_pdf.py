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
    assert all(chunk["page_start"] == chunk["page_end"] for chunk in chunks)


def test_chunk_pages_hard_splits_oversized_paragraphs() -> None:
    chunks = chunk_pages([{"page_number": 7, "text": "x" * 105}], max_chars=40)

    assert [len(chunk["text"]) for chunk in chunks] == [40, 40, 25]
    assert all(chunk["page_start"] == chunk["page_end"] == 7 for chunk in chunks)
