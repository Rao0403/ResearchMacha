from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from app import ai
from test_openai_provider import completed_response, fake_client


def contexts(count):
    return [{"paper_id": f"p{index}", "title": f"Source title {index}", "summary": "Source summary.",
             "chunks": [{"id": f"real-chunk-{index}", "page_start": 4, "page_end": 4, "text": "Evidence-backed result. Evaluation uses a fixed benchmark."}]}
            for index in range(count)]


def draft_row(paper_id, text="Evidence-backed result."):
    return {"paper_id": paper_id, **{field: text for field in ai.BATCH_COMPARISON_FIELDS},
            "sources": {field: [f"e{int(paper_id[1:])+1}"] if paper_id[1:].isdigit() else ["e1"] for field in ai.BATCH_COMPARISON_FIELDS}}


@pytest.mark.parametrize("count", [1, 2, 10])
def test_batch_request_is_bounded_and_metadata_is_added_locally(count):
    sources = contexts(count)
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json=completed_response(json.dumps({
            "overall_takeaway": "Different benchmarks prevent a direct comparison.",
            "papers": [draft_row(source["paper_id"]) for source in reversed(sources)],
        })))

    provider = object.__new__(ai.OpenAIProvider)
    with fake_client(handler) as client:
        provider.chat_model = client
        output = provider.summarize_batch("Compare results", sources)

    assert len(bodies) == 1
    body = bodies[0]
    assert body["max_output_tokens"] == 6000
    assert body["reasoning"] == {"effort": "none"}
    schema = body["text"]["format"]["schema"]
    assert set(schema["properties"]) == {"overall_takeaway", "papers"}
    assert schema["properties"]["overall_takeaway"]["maxLength"] == 600
    assert schema["properties"]["papers"]["minItems"] == count
    assert schema["properties"]["papers"]["maxItems"] == count
    row = schema["$defs"]["BatchPaperDraft"]["properties"]
    assert row["paper_id"]["enum"] == [source["paper_id"] for source in sources]
    assert "title" not in row
    for field in ai.BATCH_COMPARISON_FIELDS:
        assert row[field]["maxLength"] == min(300, max(100, 1400 // count))
        assert schema["$defs"]["BatchFieldSources"]["properties"][field]["items"]["enum"] == [f"e{i+1}" for i in range(count)]
    example = json.loads(body["input"][0]["content"].split("Example valid JSON:\n")[1])
    assert [item["paper_id"] for item in example["papers"]] == [source["paper_id"] for source in sources]
    assert [(row.paper_id, row.title) for row in output.papers] == [
        (source["paper_id"], source["title"]) for source in sources
    ]
    assert output.generation_mode == "ai" and output.warnings == []
    for index, paper in enumerate(output.papers):
        citation=paper.citations["results"][0]
        assert citation.chunk_id == f"real-chunk-{index}"
        assert citation.paper_id == paper.paper_id and citation.title == paper.title and citation.page == 4
        assert citation.excerpt in sources[index]["chunks"][0]["text"]
    ai.validate_batch_evidence(output, ai.EvidenceRegistry.from_paper_contexts(sources))


@pytest.mark.parametrize("ids", [["p0"], ["p0", "p0"], ["p0", "invented"]])
def test_invalid_batch_identities_are_repaired_once(ids):
    calls = []

    def handler(request):
        calls.append(request)
        rows = ids if len(calls) == 1 else ["p0", "p1"]
        return httpx.Response(200, json=completed_response(json.dumps({
            "overall_takeaway": "Grounded comparison.", "papers": [draft_row(paper_id) for paper_id in rows],
        })))

    provider = object.__new__(ai.OpenAIProvider)
    with fake_client(handler) as client:
        provider.chat_model = client
        output = provider.summarize_batch("Compare", contexts(2))
    assert len(calls) == 2
    assert [row.paper_id for row in output.papers] == ["p0", "p1"]


def test_large_batch_cell_limit_is_checked_locally_too():
    draft = ai.BatchComparisonDraft(overall_takeaway="Comparison", papers=[draft_row("p0", "x" * 181)])
    with pytest.raises(ai.EvidenceValidationError, match="180 characters"):
        ai.validate_batch_draft(draft, {"p0"}, 180)
    with pytest.raises(ValidationError):
        ai.BatchPaperDraft.model_validate(draft_row("p0", "x" * 361))
    with pytest.raises(ValidationError):
        ai.BatchComparisonDraft(overall_takeaway="x" * 601, papers=[draft_row("p0")])
