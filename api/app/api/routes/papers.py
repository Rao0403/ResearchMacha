from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import get_settings
from app.models.paper import Highlight, Job, Paper, PaperSummary
from app.schemas.paper import (
    ArxivImportRequest,
    BatchSummaryRequest,
    BatchSummaryResponse,
    BatchUploadResponse,
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
    create_uploaded_papers_with_jobs,
    get_paper_or_404,
    validate_paper_metadata,
)
from app.services.research import summarize_batch_papers
from app.services.storage import PdfIngestionError, StagedPdf, stage_upload_pdf

router = APIRouter()
settings = get_settings()


@router.get("/papers/search", response_model=list[PaperSearchResult])
def search_papers(q: str = Query(..., min_length=2, max_length=200)) -> list[PaperSearchResult]:
    return [PaperSearchResult.model_validate(item) for item in search_arxiv(q)]


@router.post("/papers/import/arxiv", response_model=UploadPaperResponse)
def import_arxiv_paper(
    payload: ArxivImportRequest,
    db: Session = Depends(get_db),
) -> UploadPaperResponse:
    try:
        entry = fetch_arxiv_entry(payload.arxiv_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        paper, _ = create_or_update_paper_from_arxiv(db, entry)
    except PdfIngestionError as exc:
        raise ingestion_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_metadata", "message": str(exc)}) from exc
    job = enqueue_analysis_job(db, paper.id, auto_reset=True)
    return UploadPaperResponse(paper=LibraryPaperRead.model_validate(paper), job=job)


@router.post("/papers/upload", response_model=UploadPaperResponse)
def upload_paper(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    authors: str | None = Form(None),
    db: Session = Depends(get_db),
) -> UploadPaperResponse:
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    author_list = [part.strip() for part in (authors or "").split(",") if part.strip()]
    paper_title = title or Path(file.filename or "uploaded-paper").stem
    try:
        paper_title, author_list = validate_paper_metadata(paper_title, author_list)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_metadata", "message": str(exc)}) from exc
    try:
        staged = stage_upload_pdf(file)
    except PdfIngestionError as exc:
        raise ingestion_http_error(exc) from exc
    try:
        stored_path = staged.publish()
        [(paper, job)] = create_uploaded_papers_with_jobs(db, [(paper_title, author_list, stored_path)])
    except Exception as exc:
        staged.cleanup()
        raise HTTPException(
            status_code=500,
            detail={"code": "upload_persistence_failed", "message": "Could not persist uploaded paper"},
        ) from exc
    return UploadPaperResponse(paper=LibraryPaperRead.model_validate(paper), job=job)


@router.post("/papers/batch-upload", response_model=BatchUploadResponse)
def batch_upload_papers(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> BatchUploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one PDF")
    if len(files) > settings.max_batch_files:
        raise HTTPException(
            status_code=400,
            detail={"code": "batch_too_large", "message": f"Upload at most {settings.max_batch_files} PDFs"},
        )

    metadata: list[tuple[str, list[str]]] = []
    for file in files:
        if file.content_type not in {"application/pdf", "application/octet-stream"}:
            raise HTTPException(status_code=400, detail=f"Only PDF uploads are supported: {file.filename}")
        try:
            paper_title, author_list = validate_paper_metadata(Path(file.filename or "uploaded-paper").stem, [])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_metadata", "message": str(exc)}) from exc
        metadata.append((paper_title, author_list))

    staged_pdfs: list[StagedPdf] = []
    try:
        for file in files:
            staged_pdfs.append(stage_upload_pdf(file))
    except PdfIngestionError as exc:
        cleanup_staged_pdfs(staged_pdfs)
        raise ingestion_http_error(exc) from exc

    try:
        stored_items = [
            (paper_title, authors, staged.publish())
            for (paper_title, authors), staged in zip(metadata, staged_pdfs, strict=True)
        ]
        created = create_uploaded_papers_with_jobs(db, stored_items)
    except Exception as exc:
        cleanup_staged_pdfs(staged_pdfs)
        raise HTTPException(
            status_code=500,
            detail={"code": "batch_persistence_failed", "message": "Could not persist PDF batch"},
        ) from exc

    items = [
        UploadPaperResponse(paper=LibraryPaperRead.model_validate(paper), job=job)
        for paper, job in created
    ]

    return BatchUploadResponse(items=items)


def cleanup_staged_pdfs(staged_pdfs: list[StagedPdf]) -> None:
    for staged in staged_pdfs:
        staged.cleanup()


def ingestion_http_error(exc: PdfIngestionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.post("/papers/batch-summary", response_model=BatchSummaryResponse)
def summarize_paper_batch(payload: BatchSummaryRequest, db: Session = Depends(get_db)) -> BatchSummaryResponse:
    return BatchSummaryResponse.model_validate(summarize_batch_papers(db, payload.paper_ids, payload.goal).model_dump())


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
def analyze_paper(paper_id: str, db: Session = Depends(get_db)) -> Job:
    get_paper_or_404(db, paper_id)
    return enqueue_analysis_job(db, paper_id, auto_reset=True)


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
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=file_path.name,
        content_disposition_type="inline",
    )


@router.post("/papers/{paper_id}/chat", response_model=ChatResponse)
def chat_with_paper(
    paper_id: str,
    payload: ChatRequest,
    db: Session = Depends(get_db),
) -> ChatResponse:
    paper = get_paper_or_404(db, paper_id)
    session = create_chat_session_if_missing(db, paper.id, payload.session_id)
    return run_chat_query(db, paper, session, payload.question)
