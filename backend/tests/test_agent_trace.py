from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.paper import ResearchProject
from app.services.agent_trace import (
    complete_agent_step,
    create_agent_run,
    latest_agent_run,
    set_agent_run_status,
    start_agent_step,
)
from app.services.fallbacks import record_fallback


def test_agent_trace_records_ordered_steps_and_status() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        project = ResearchProject(question="How should RAG systems reduce hallucinations?", status="draft")
        db.add(project)
        db.commit()
        db.refresh(project)

        run = create_agent_run(db, project.id, project.question)
        first = start_agent_step(db, run, "plan_search", {"question": project.question})
        complete_agent_step(db, first, {"search_queries": ["rag hallucination"]})
        second = start_agent_step(db, run, "search_arxiv", {"queries": ["rag hallucination"]})
        complete_agent_step(db, second, {"unique_candidate_count": 3})
        set_agent_run_status(db, run, "awaiting_approval")

        stored_run = latest_agent_run(db, project.id)

        assert stored_run is not None
        assert stored_run.status == "awaiting_approval"
        assert [step.tool_name for step in stored_run.steps] == ["plan_search", "search_arxiv"]
        assert [step.position for step in stored_run.steps] == [1, 2]


def test_agent_step_output_records_fallback_events() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        project = ResearchProject(question="How should RAG systems reduce hallucinations?", status="draft")
        db.add(project)
        db.commit()
        db.refresh(project)

        run = create_agent_run(db, project.id, project.question)
        step = start_agent_step(db, run, "select_candidates", {"candidate_count": 3})
        record_fallback("research.select_candidates", "top_3_by_score", "LLM returned no selected papers.")
        complete_agent_step(db, step, {"selected_count": 3})
        db.refresh(step)

        assert step.output_json["fallback_used"] is True
        assert step.output_json["fallbacks"][0]["component"] == "research.select_candidates"
        assert step.output_json["fallbacks"][0]["fallback"] == "top_3_by_score"
