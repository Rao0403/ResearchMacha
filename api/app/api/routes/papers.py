from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.paper import Highlight, Job, Paper, PaperSummary
from app.schemas.paper import (
    ArxivImportRequest,
    ChatRequest,
    ChatResponse,
    HighlightRead,
    JobRead,
    LibraryPaperRead,
    PaperDetailRead,
    PaperSearchResult,
    PaperSummaryResponse,
    UploadPaperResponse,
)
from app.services.analysis import enqueue_analysis_job, run_chat_query
from app.services.arxiv import fetch_arxiv_entry, search_arxiv
from app.services.papers import (
    create_chat_session_if_missing,
    create_or_update_paper_from_arxiv,
    create_uploaded_paper,
    get_paper_or_404,
)
from app.services.storage import save_upload_file

router = APIRouter()


@router.get("/papers/search", response_model=list[PaperSearchResult])
def search_papers(q: str = Query(..., min_length=2, max_length=200)) -> list[PaperSearchResult]:
    return [PaperSearchResult.model_validate(item) for item in search_arxiv(q)]


@router.post("/papers/import/arxiv", response_model=UploadPaperResponse)
def import_arxiv_paper(
    payload: ArxivImportRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> UploadPaperResponse:
    try:
        entry = fetch_arxiv_entry(payload.arxiv_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    paper, _ = create_or_update_paper_from_arxiv(db, entry)
    job = enqueue_analysis_job(db, paper.id, background_tasks, auto_reset=True)
    return UploadPaperResponse(paper=LibraryPaperRead.model_validate(paper), job=job)


@router.post("/papers/upload", response_model=UploadPaperResponse)
def upload_paper(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    authors: str | None = Form(None),
    db: Session = Depends(get_db),
) -> UploadPaperResponse:
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    stored_path = save_upload_file(file)
    author_list = [part.strip() for part in (authors or "").split(",") if part.strip()]
    paper = create_uploaded_paper(db, title=title or Path(file.filename or "uploaded-paper").stem, authors=author_list, pdf_path=stored_path)
    job = enqueue_analysis_job(db, paper.id, background_tasks, auto_reset=True)
    return UploadPaperResponse(paper=LibraryPaperRead.model_validate(paper), job=job)


@router.get("/papers", response_model=list[LibraryPaperRead])
def list_papers(db: Session = Depends(get_db)) -> list[Paper]:
    return db.query(Paper).order_by(Paper.updated_at.desc()).all()


@router.get("/papers/{paper_id}", response_model=PaperDetailRead)
def get_paper(paper_id: str, db: Session = Depends(get_db)) -> Paper:
    paper = get_paper_or_404(db, paper_id)
    paper.last_opened_at = datetime.now(UTC).replace(tzinfo=None)
    db.add(paper)
    db.commit()
    db.refresh(paper)
    return paper


@router.post("/papers/{paper_id}/analyze", response_model=JobRead)
def analyze_paper(paper_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> Job:
    get_paper_or_404(db, paper_id)
    return enqueue_analysis_job(db, paper_id, background_tasks, auto_reset=True)


@router.get("/papers/{paper_id}/summary", response_model=PaperSummaryResponse)
def get_summary(paper_id: str, db: Session = Depends(get_db)) -> PaperSummaryResponse:
    paper = get_paper_or_404(db, paper_id)
    summary = db.query(PaperSummary).filter(PaperSummary.paper_id == paper_id).one_or_none()
    highlights = db.query(Highlight).filter(Highlight.paper_id == paper_id).order_by(Highlight.position.asc()).all()
    if summary is None:
        raise HTTPException(status_code=404, detail="Summary not available")
    return PaperSummaryResponse(
        paper=PaperDetailRead.model_validate(paper),
        summary=summary,
        highlights=[HighlightRead.model_validate(item) for item in highlights],
    )


@router.get("/papers/{paper_id}/file")
def get_paper_file(paper_id: str, db: Session = Depends(get_db)) -> FileResponse:
    paper = get_paper_or_404(db, paper_id)
    file_path = Path(paper.pdf_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="PDF not found on disk")
    return FileResponse(file_path, media_type="application/pdf", filename=file_path.name)


@router.post("/papers/{paper_id}/chat", response_model=ChatResponse)
def chat_with_paper(
    paper_id: str,
    payload: ChatRequest,
    db: Session = Depends(get_db),
) -> ChatResponse:
    paper = get_paper_or_404(db, paper_id)
    session = create_chat_session_if_missing(db, paper.id, payload.session_id)
    return run_chat_query(db, paper, session, payload.question)
