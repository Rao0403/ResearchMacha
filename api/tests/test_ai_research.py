import pytest
from fastapi import HTTPException

from app.ai import EvidenceCitation, MockProvider, PaperFinding, ResearchBrief
from app.services.arxiv import ARXIV_API, ArxivEntry
from app.services.research import ensure_cited_brief, score_candidate


def test_mock_provider_plans_research_question() -> None:
    plan = MockProvider().plan_research("How can RAG improve factuality in question answering?")

    assert plan.search_queries
    assert "RAG" in plan.search_queries[0]
    assert plan.inclusion_criteria


def test_synthesis_requires_citations() -> None:
    finding = PaperFinding(label="Uncited", summary="This claim has no evidence.", citations=[])
    brief = ResearchBrief(
        executive_summary="Summary",
        key_findings=[finding],
        evidence_table=[],
        conflicts_or_gaps=[],
        suggested_experiments=[],
        suggested_research_directions=[],
    )

    with pytest.raises(HTTPException):
        ensure_cited_brief(brief)


def test_candidate_scoring_rewards_question_overlap() -> None:
    relevant = ArxivEntry(
        arxiv_id="1",
        title="Retrieval augmented generation for factual question answering",
        authors=[],
        abstract="This paper studies retrieval grounding and factuality.",
        year=2024,
        pdf_url="https://arxiv.org/pdf/1.pdf",
        entry_url="https://arxiv.org/abs/1",
    )
    unrelated = ArxivEntry(
        arxiv_id="2",
        title="Graph coloring with local search",
        authors=[],
        abstract="This paper studies combinatorial optimization.",
        year=2024,
        pdf_url="https://arxiv.org/pdf/2.pdf",
        entry_url="https://arxiv.org/abs/2",
    )

    relevant_score, _ = score_candidate("RAG factuality question answering", relevant)
    unrelated_score, _ = score_candidate("RAG factuality question answering", unrelated)

    assert relevant_score > unrelated_score


def test_cited_brief_passes_validation() -> None:
    citation = EvidenceCitation(page=1, excerpt="Evidence", chunk_id="chunk-1")
    finding = PaperFinding(label="Cited", summary="This claim has evidence.", citations=[citation])
    brief = ResearchBrief(
        executive_summary="Summary",
        key_findings=[finding],
        evidence_table=[],
        conflicts_or_gaps=[],
        suggested_experiments=[],
        suggested_research_directions=[],
    )

    ensure_cited_brief(brief)


def test_arxiv_api_uses_https() -> None:
    assert ARXIV_API.startswith("https://")


def test_mock_candidate_selection_uses_top_ranked_papers() -> None:
    candidates = [
        {"arxiv_id": "low", "score": 20, "rationale": "Weak match"},
        {"arxiv_id": "high", "score": 95, "rationale": "Strong match"},
        {"arxiv_id": "mid", "score": 60, "rationale": "Useful background"},
        {"arxiv_id": "extra", "score": 50, "rationale": "Secondary"},
    ]

    selection = MockProvider().select_relevant_candidates("retrieval grounded QA", candidates)

    assert [choice.arxiv_id for choice in selection.selected] == ["high", "mid", "extra"]
    assert selection.selected[0].rationale == "Strong match"


def test_mock_batch_summary_contains_required_fields() -> None:
    summary = MockProvider().summarize_batch(
        "Compare approaches",
        [
            {
                "paper_id": "paper-1",
                "title": "Grounded Reading Systems",
                "summary": "The paper studies retrieval grounded paper reading with benchmark evaluations.",
                "chunks": [],
            }
        ],
    )

    assert summary.overall_takeaway
    assert summary.papers[0].main_idea
    assert summary.papers[0].problem_or_hypothesis
    assert summary.papers[0].experiments
    assert summary.papers[0].models_and_datasets
    assert summary.papers[0].results
    assert summary.papers[0].conclusions
