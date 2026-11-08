import pytest

from app.services.pdf import chunk_pages, trim_reference_section


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


@pytest.mark.parametrize("heading", ["References", "7 REFERENCES", "7. References", "7.2 Bibliography",
                                      "VIII. References", "Literature Cited", "References and Notes:"])
def test_chunking_stops_at_bibliography_and_keeps_body_on_the_same_page(heading):
    pages = [
        {"page_number": 1, "text": "Introduction and methods."},
        {"page_number": 9, "text": f"Final result and limitations.\n{heading}\nBibliographic entries."},
        {"page_number": 10, "text": "More bibliography."},
        {"page_number": 11, "text": "Appendix after references."},
    ]
    chunks = chunk_pages(pages, max_chars=20)
    assert max(chunk["page_end"] for chunk in chunks) == 9
    combined = " ".join(chunk["text"] for chunk in chunks)
    assert "Final result" in combined
    assert not any(term in combined for term in ["Bibliographic", "bibliography", "Appendix", "References"])
    assert "Bibliographic" in pages[1]["text"]  # Input PDF text is not mutated.


def test_contents_and_prose_mentions_do_not_truncate_body():
    pages = [
        {"page_number": 1, "text": "Table of Contents\nIntroduction\nReferences\n12"},
        {"page_number": 2, "text": "References to prior studies are discussed here.\nThe method uses references."},
        {"page_number": 3, "text": "References ........ 12\nActual experiments and results."},
        {"page_number": 12, "text": "References\nBibliography entry."},
    ]
    chunks = chunk_pages(pages)
    assert [chunk["page_start"] for chunk in chunks] == [1, 2, 3]
    assert "Actual experiments" in chunks[-1]["text"]


def test_legacy_chunked_contents_page_is_recognized_across_chunks():
    parts = [
        {"page_start": 1, "text": "Contents"},
        {"page_start": 1, "text": "References\n12"},
        {"page_start": 2, "text": "Real body."},
        {"page_start": 12, "text": "References\nCitation."},
    ]
    assert trim_reference_section(parts) == parts[:3]


def test_short_body_before_a_long_bibliography_is_still_trimmed():
    pages = [{"page_number": 1, "text": "Short main body."},
             {"page_number": 2, "text": "References\nCitation."}]
    pages.extend({"page_number": page, "text": "More citations."} for page in range(3, 30))
    assert [chunk["text"] for chunk in chunk_pages(pages)] == ["Short main body."]


def test_reference_only_document_has_no_main_body_chunks():
    assert chunk_pages([{"page_number": 1, "text": "References\nOnly citations."}]) == []
