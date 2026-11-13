import pytest
from app import ai
from test_batch_generation import contexts, draft_row


def test_unknown_wrong_paper_and_missing_cell_evidence_are_rejected():
    evidence={"e1":{"paper_id":"p0"},"e2":{"paper_id":"p1"}}
    row=draft_row("p0")
    output=ai.BatchComparisonDraft(overall_takeaway="Evidence",papers=[row])
    output.papers[0].sources.results=["invented"]
    with pytest.raises(ai.EvidenceValidationError,match="unknown or wrong-paper"):
        ai.validate_batch_draft(output,{"p0"},300,evidence)
    output.papers[0].sources.results=["e2"]
    with pytest.raises(ai.EvidenceValidationError,match="wrong-paper"):
        ai.validate_batch_draft(output,{"p0"},300,evidence)
    output.papers[0].sources.results=[]
    with pytest.raises(ai.EvidenceValidationError,match="requires a source"):
        ai.validate_batch_draft(output,{"p0"},300,evidence)
    output.papers[0].results="Not reported in supplied evidence."
    ai.validate_batch_draft(output,{"p0"},300,evidence)


def test_citations_are_revalidated_before_persistence():
    sources=contexts(2)
    output=ai.MockProvider().summarize_batch("Compare",sources)
    output.generation_mode="ai"
    registry=ai.EvidenceRegistry.from_paper_contexts(sources)
    ai.validate_batch_evidence(output,registry)
    output.papers[0].citations["results"][0].paper_id="p1"
    with pytest.raises(ai.EvidenceValidationError,match="paper does not match"):
        ai.validate_batch_evidence(output,registry)


def test_excerpt_selects_relevant_verbatim_sentence():
    chunk={"id":"original","text":"An introduction to the task. Accuracy reached 82 percent on Dataset A. Future work remains.","page_start":7}
    citation=ai.comparison_citation(chunk,"Accuracy on Dataset A reached 82 percent")
    assert citation["excerpt"] == "Accuracy reached 82 percent on Dataset A."
    assert citation["chunk_id"] == "original" and citation["page"] == 7
