from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.research import CandidateSelectionRequest, ResearchPlanResponse, ResearchProjectCreate, ResearchProjectRead
from app.services.research import (
    create_project,
    discover_candidates,
    get_project_or_404,
    import_selected_candidates,
    list_projects,
    plan_project,
    seed_demo_project,
    serialize_project,
    synthesize_project,
)

router = APIRouter()


@router.post("/research-projects", response_model=ResearchProjectRead)
def create_research_project(payload: ResearchProjectCreate, db: Session = Depends(get_db)) -> ResearchProjectRead:
    return serialize_project(create_project(db, payload.question))


@router.get("/research-projects", response_model=list[ResearchProjectRead])
def get_research_projects(db: Session = Depends(get_db)) -> list[ResearchProjectRead]:
    return [serialize_project(project) for project in list_projects(db)]


@router.get("/research-projects/{project_id}", response_model=ResearchProjectRead)
def get_research_project(project_id: str, db: Session = Depends(get_db)) -> ResearchProjectRead:
    return serialize_project(get_project_or_404(db, project_id))


@router.post("/research-projects/demo", response_model=ResearchProjectRead)
def create_demo_project(db: Session = Depends(get_db)) -> ResearchProjectRead:
    return serialize_project(seed_demo_project(db))


@router.post("/research-projects/{project_id}/plan", response_model=ResearchPlanResponse)
def plan_research_project(project_id: str, db: Session = Depends(get_db)) -> ResearchPlanResponse:
    project = plan_project(db, project_id)
    return ResearchPlanResponse(search_queries=project.generated_queries, inclusion_criteria=project.inclusion_criteria)


@router.post("/research-projects/{project_id}/discover", response_model=ResearchProjectRead)
def discover_research_candidates(project_id: str, db: Session = Depends(get_db)) -> ResearchProjectRead:
    return serialize_project(discover_candidates(db, project_id))


@router.post("/research-projects/{project_id}/import-selected", response_model=ResearchProjectRead)
def import_research_candidates(
    project_id: str,
    payload: CandidateSelectionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ResearchProjectRead:
    return serialize_project(import_selected_candidates(db, project_id, payload.candidate_ids, background_tasks))


@router.post("/research-projects/{project_id}/synthesize", response_model=ResearchProjectRead)
def synthesize_research_project(project_id: str, db: Session = Depends(get_db)) -> ResearchProjectRead:
    return serialize_project(synthesize_project(db, project_id))


@router.get("/research-projects/{project_id}/brief", response_model=dict)
def get_research_brief(project_id: str, db: Session = Depends(get_db)) -> dict:
    project = get_project_or_404(db, project_id)
    return project.synthesis_json or {}
