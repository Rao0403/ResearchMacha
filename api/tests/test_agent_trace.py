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
