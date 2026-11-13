from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.api.deps import get_db
from app.schemas.research import (
    ProjectListRead, ProjectRename, ProjectSelection,
    CandidateSelectionRequest,
    ResearchPlanResponse,
    ResearchProjectCreate,
    ResearchProjectRead,
    ResearchProjectStatusRead,
)
from app.services.research import (
    approve_research_workflow,
    attach_library_papers,
    create_project,
    discover_candidates,
    get_project_or_404,
    get_workflow_status,
    enqueue_synthesis_job,
    exclude_candidate,
    exclude_project_paper,
    get_project_polling_status_or_404,
    import_selected_candidates,
    list_projects,
    plan_project,
    seed_demo_project,
    serialize_project,
    start_research_workflow,
    synthesize_project,
)

router = APIRouter()


class LibraryEvidenceRequest(BaseModel):
    paper_ids: list[str] = Field(min_length=1, max_length=5)
    version: int = Field(ge=0)


class LibraryResearchRequest(ResearchProjectCreate):
    paper_ids: list[str] = Field(min_length=1, max_length=5)


@router.post("/research-workflows/from-library", response_model=ResearchProjectRead)
def research_from_library(payload: LibraryResearchRequest, db: Session = Depends(get_db)):
    from app.services.papers import reusable_papers
    reusable_papers(db, payload.paper_ids, maximum=5)
    project = create_project(db, payload.question)
    project = attach_library_papers(db, project.id, payload.paper_ids, 0)
    enqueue_synthesis_job(db, project.id)
    return serialize_project(get_project_or_404(db, project.id))


@router.post("/research-workflows/{project_id}/papers", response_model=ResearchProjectRead)
def add_library_evidence(project_id: str, payload: LibraryEvidenceRequest, db: Session = Depends(get_db)):
    return serialize_project(attach_library_papers(db, project_id, payload.paper_ids, payload.version))


@router.get("/research-workflows", response_model=list[ProjectListRead])
def saved_workflows(db: Session = Depends(get_db)):
    return [ProjectListRead(id=p.id, name=p.name, question=p.question, status=p.status,
                           paper_count=len(p.papers), updated_at=p.updated_at) for p in list_projects(db)]


@router.patch("/research-workflows/{project_id}", response_model=ResearchProjectRead)
def rename_workflow(project_id: str, payload: ProjectRename, db: Session = Depends(get_db)):
    project = get_project_or_404(db, project_id)
    if not payload.name.strip():
        raise HTTPException(422, "Project name cannot be blank")
    project.name = payload.name.strip()
    db.commit()
    return serialize_project(get_project_or_404(db, project_id))


@router.put("/research-workflows/{project_id}/selection", response_model=ResearchProjectRead)
def save_workflow_selection(project_id: str, payload: ProjectSelection, db: Session = Depends(get_db)):
    from app.models.paper import ResearchProject, ResearchCandidate
    project = db.scalar(select(ResearchProject).where(ResearchProject.id == project_id).with_for_update())
    if project is None:
        raise HTTPException(404, "Research project not found")
    if project.status != "awaiting_approval" or project.selection_version != payload.version:
        raise HTTPException(409, "Selection changed or approval has already started. Reload this project.")
    candidates = db.query(ResearchCandidate).filter(ResearchCandidate.project_id == project_id).all()
    selected = set(payload.candidate_ids)
    if not selected <= {c.id for c in candidates}:
        raise HTTPException(400, "Candidates do not belong to this project")
    for candidate in candidates:
        candidate.selected = candidate.id in selected
    project.selection_version += 1
    db.commit()
    return serialize_project(get_project_or_404(db, project_id))


@router.post("/research-workflows", response_model=ResearchProjectRead)
def start_workflow(payload: ResearchProjectCreate, db: Session = Depends(get_db)) -> ResearchProjectRead:
    return serialize_project(start_research_workflow(db, payload.question))


@router.post("/research-workflows/{project_id}/approve", response_model=ResearchProjectRead)
def approve_workflow(
    project_id: str,
    payload: CandidateSelectionRequest,
    db: Session = Depends(get_db),
) -> ResearchProjectRead:
    return serialize_project(approve_research_workflow(db, project_id, payload.candidate_ids))


@router.get("/research-workflows/{project_id}", response_model=ResearchProjectRead)
def get_workflow(project_id: str, db: Session = Depends(get_db)) -> ResearchProjectRead:
    return serialize_project(get_workflow_status(db, project_id))


@router.get("/research-workflows/{project_id}/status", response_model=ResearchProjectStatusRead)
def get_workflow_polling_status(project_id: str, db: Session = Depends(get_db)) -> ResearchProjectStatusRead:
    return ResearchProjectStatusRead.model_validate(get_project_polling_status_or_404(db, project_id))


@router.delete("/research-workflows/{project_id}/candidates/{candidate_id}", response_model=ResearchProjectRead)
def remove_workflow_candidate(
    project_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
) -> ResearchProjectRead:
    return serialize_project(exclude_candidate(db, project_id, candidate_id))


@router.delete("/research-workflows/{project_id}/papers/{paper_id}", response_model=ResearchProjectRead)
def remove_workflow_paper(
    project_id: str,
    paper_id: str,
    db: Session = Depends(get_db),
) -> ResearchProjectRead:
    return serialize_project(exclude_project_paper(db, project_id, paper_id))


@router.post("/research-workflows/{project_id}/synthesize", response_model=ResearchProjectRead)
def synthesize_workflow(project_id: str, db: Session = Depends(get_db)) -> ResearchProjectRead:
    enqueue_synthesis_job(db, project_id)
    return serialize_project(get_project_or_404(db, project_id))


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
    db: Session = Depends(get_db),
) -> ResearchProjectRead:
    return serialize_project(import_selected_candidates(db, project_id, payload.candidate_ids))


@router.post("/research-projects/{project_id}/synthesize", response_model=ResearchProjectRead)
def synthesize_research_project(project_id: str, db: Session = Depends(get_db)) -> ResearchProjectRead:
    enqueue_synthesis_job(db, project_id)
    return serialize_project(get_project_or_404(db, project_id))


@router.get("/research-projects/{project_id}/brief", response_model=dict)
def get_research_brief(project_id: str, db: Session = Depends(get_db)) -> dict:
    project = get_project_or_404(db, project_id)
    return project.synthesis_json or {}
