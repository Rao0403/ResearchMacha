from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.paper import AgentRun, AgentStep, utc_now


def create_agent_run(db: Session, project_id: str, goal: str) -> AgentRun:
    run = AgentRun(project_id=project_id, goal=goal, status="running", started_at=utc_now())
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def latest_agent_run(db: Session, project_id: str) -> AgentRun | None:
    return (
        db.query(AgentRun)
        .filter(AgentRun.project_id == project_id)
        .order_by(AgentRun.created_at.desc())
        .first()
    )


def set_agent_run_status(db: Session, run: AgentRun | None, status: str, error_message: str | None = None) -> None:
    if run is None:
        return
    run.status = status
    run.error_message = error_message
    if status in {"done", "failed"}:
        run.finished_at = utc_now()
    db.add(run)
    db.commit()


def start_agent_step(db: Session, run: AgentRun | None, tool_name: str, input_json: dict[str, Any] | None = None) -> AgentStep | None:
    if run is None:
        return None
    position = db.query(AgentStep).filter(AgentStep.run_id == run.id).count() + 1
    step = AgentStep(
        run_id=run.id,
        project_id=run.project_id,
        position=position,
        tool_name=tool_name,
        status="running",
        input_json=input_json,
        started_at=utc_now(),
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def complete_agent_step(db: Session, step: AgentStep | None, output_json: dict[str, Any] | None = None) -> None:
    if step is None:
        return
    step.status = "completed"
    step.output_json = output_json
    step.finished_at = utc_now()
    db.add(step)
    db.commit()


def fail_agent_step(db: Session, step: AgentStep | None, error: Exception) -> None:
    if step is None:
        return
    step.status = "failed"
    step.error_message = str(error)
    step.finished_at = utc_now()
    db.add(step)
    db.commit()


def summarize_candidates_for_trace(candidates: list[Any], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "id": getattr(candidate, "id", None),
            "arxiv_id": getattr(candidate, "arxiv_id", None),
            "title": getattr(candidate, "title", "")[:240],
            "score": getattr(candidate, "score", None),
            "selected": getattr(candidate, "selected", None),
        }
        for candidate in candidates[:limit]
    ]
