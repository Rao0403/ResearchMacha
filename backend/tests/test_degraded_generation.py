from __future__ import annotations

from app.ai import (
    AIProviderError,
    EvidenceRegistry,
    MockProvider,
    validate_brief_evidence,
)
from app.models.paper import AgentStep, Paper, ResearchProject
from app.services import research
from app.services.agent_trace import create_agent_run


def evidence_context(paper_id: str = "paper-1", title: str = "Grounded Paper") -> dict:
    return {
        "paper_id": paper_id,
        "title": title,
        "summary": "Stored grounded summary.",
        "chunks": [
            {
                "id": f"chunk-{paper_id}",
                "page_start": 3,
                "page_end": 3,
                "text": "The evaluation reports grounded evidence from the source paper.",
            }
        ],
    }


class FailingProvider:
    def plan_research(self, question):
        raise AIProviderError("planning unavailable")

    def synthesize_collection(self, question, paper_contexts, memory_context=None):
        raise AIProviderError("synthesis unavailable")

    def summarize_batch(self, goal, paper_contexts):
        raise AIProviderError("batch unavailable")


def test_mock_provider_marks_generated_content_as_mock() -> None:
    provider = MockProvider()
    context = evidence_context()

    assert provider.generate_summary(context["title"], context["chunks"]).generation_mode == "mock"
    assert provider.answer_question(context["title"], "What is reported?", context["chunks"], []).generation_mode == "mock"
    assert provider.summarize_batch("Compare", [context]).generation_mode == "mock"
    assert provider.synthesize_collection("What is reported?", [context]).generation_mode == "mock"


def test_planning_failure_uses_deterministic_plan_and_records_trace_warning(db_session, monkeypatch) -> None:
    project = ResearchProject(question="How does retrieval improve factuality?", status="draft")
    db_session.add(project)
    db_session.commit()
    run = create_agent_run(db_session, project.id, project.question)
    monkeypatch.setattr(research, "get_ai_provider", lambda: FailingProvider())

    planned = research.plan_project(db_session, project.id, run)

    assert planned.status == "planned"
    assert planned.generated_queries
    step = db_session.query(AgentStep).filter(AgentStep.run_id == run.id).one()
    assert step.status == "completed"
    assert step.output_json["fallback_used"] is True
    assert step.output_json["fallbacks"][0]["fallback"] == "deterministic_research_plan"


def test_synthesis_failure_creates_citation_valid_degraded_evidence_packet(db_session, monkeypatch) -> None:
    project = ResearchProject(question="What does the evidence show?", status="synthesizing")
    db_session.add(project)
    db_session.commit()
    context = evidence_context()
    monkeypatch.setattr(research, "build_paper_contexts", lambda value: [context])
    monkeypatch.setattr(research, "retrieve_memories", lambda *args, **kwargs: [])
    monkeypatch.setattr(research, "get_ai_provider", lambda: FailingProvider())

    result = research.synthesize_project(db_session, project.id)

    brief = result.synthesis_json
    assert result.status == "degraded"
    assert brief["generation_mode"] == "extractive"
    assert brief["warnings"]
    assert len(brief["key_findings"]) == 1
    assert len(brief["evidence_table"]) == 1
    assert brief["conflicts_or_gaps"] == []
    assert brief["suggested_experiments"] == []
    assert brief["suggested_research_directions"] == []
    validate_brief_evidence(
        research.ResearchBrief.model_validate(brief),
        EvidenceRegistry.from_paper_contexts([context]),
    )


def test_batch_failure_uses_stored_summaries_in_extractive_mode(db_session, monkeypatch) -> None:
    paper = Paper(source="upload", title="Paper", authors=[], pdf_path="paper.pdf", status="ready")
    db_session.add(paper)
    db_session.commit()
    context = evidence_context(paper.id, paper.title)
    monkeypatch.setattr(research, "build_paper_contexts_by_ids", lambda *args, **kwargs: [context])
    monkeypatch.setattr(research, "get_ai_provider", lambda: FailingProvider())

    output = research.summarize_batch_papers(db_session, [paper.id], "Compare evidence")

    assert output.generation_mode == "extractive"
    assert output.warnings
    assert output.papers[0].paper_id == paper.id
    assert output.papers[0].main_idea == context["summary"]
