from __future__ import annotations

import re
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.ai import BatchSummary, MockProvider, ResearchBrief, get_ai_provider
from app.models.paper import Paper, PaperChunk, PaperSummary, ResearchCandidate, ResearchProject, ResearchProjectPaper
from app.schemas.paper import LibraryPaperRead
from app.schemas.research import ResearchCandidateRead, ResearchProjectRead
from app.services.analysis import enqueue_analysis_job
from app.services.arxiv import ArxivEntry, fetch_arxiv_entry, search_arxiv
from app.services.papers import create_or_update_paper_from_arxiv

DEMO_QUESTION = "How can retrieval augmented generation improve factuality in domain-specific question answering?"
DEMO_ARXIV_IDS = ["2005.11401", "2310.11511", "2403.10131"]


def create_project(db: Session, question: str) -> ResearchProject:
    project = ResearchProject(question=question, status="draft")
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session) -> list[ResearchProject]:
    return db.query(ResearchProject).order_by(ResearchProject.updated_at.desc()).all()


def get_project_or_404(db: Session, project_id: str) -> ResearchProject:
    project = (
        db.query(ResearchProject)
        .populate_existing()
        .options(
            selectinload(ResearchProject.candidates),
            selectinload(ResearchProject.papers).selectinload(ResearchProjectPaper.paper),
        )
        .filter(ResearchProject.id == project_id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Research project not found")
    return project


def serialize_project(project: ResearchProject) -> ResearchProjectRead:
    papers = [LibraryPaperRead.model_validate(link.paper) for link in project.papers if link.paper is not None]
    return ResearchProjectRead(
        id=project.id,
        question=project.question,
        status=project.status,
        generated_queries=project.generated_queries or [],
        inclusion_criteria=project.inclusion_criteria or [],
        synthesis_json=project.synthesis_json,
        created_at=project.created_at,
        updated_at=project.updated_at,
        candidates=[ResearchCandidateRead.model_validate(candidate) for candidate in sorted(project.candidates, key=lambda item: item.score, reverse=True)],
        papers=papers,
    )


def start_research_workflow(db: Session, question: str) -> ResearchProject:
    project = create_project(db, question)
    project = plan_project(db, project.id)
    project = discover_candidates(db, project.id)
    return select_recommended_candidates(db, project.id)


def select_recommended_candidates(db: Session, project_id: str) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    candidates = (
        db.query(ResearchCandidate)
        .filter(ResearchCandidate.project_id == project_id)
        .order_by(ResearchCandidate.score.desc())
        .all()
    )
    if not candidates:
        project.status = "no_candidates"
        db.add(project)
        db.commit()
        return get_project_or_404(db, project_id)

    candidate_payloads = [candidate_to_payload(candidate) for candidate in candidates]

    try:
        selection = get_ai_provider().select_relevant_candidates(project.question, candidate_payloads)
        selected_ids = {choice.arxiv_id for choice in selection.selected}
        rationales = {choice.arxiv_id: choice.rationale for choice in selection.selected}
    except Exception:
        selected_ids = {candidate.arxiv_id for candidate in candidates[:3]}
        rationales = {candidate.arxiv_id: "Selected as one of the highest-ranked candidates." for candidate in candidates[:3]}

    if not selected_ids:
        selected_ids = {candidate.arxiv_id for candidate in candidates[:3]}

    for candidate in candidates:
        candidate.selected = candidate.arxiv_id in selected_ids
        if candidate.selected and candidate.arxiv_id in rationales:
            candidate.rationale = rationales[candidate.arxiv_id]
        db.add(candidate)

    project.status = "awaiting_approval"
    db.add(project)
    db.commit()
    return get_project_or_404(db, project_id)


def plan_project(db: Session, project_id: str) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    plan = get_ai_provider().plan_research(project.question)
    project.generated_queries = plan.search_queries
    project.inclusion_criteria = plan.inclusion_criteria
    project.status = "planned"
    db.add(project)
    db.commit()
    return get_project_or_404(db, project.id)


def discover_candidates(db: Session, project_id: str, max_per_query: int = 6) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    if not project.generated_queries:
        project = plan_project(db, project_id)

    seen = {candidate.arxiv_id: candidate for candidate in project.candidates}
    for query in project.generated_queries[:4]:
        for entry in search_arxiv(query, max_results=max_per_query):
            score, rationale = score_candidate(project.question, entry)
            candidate = seen.get(entry.arxiv_id)
            if candidate is None:
                candidate = ResearchCandidate(
                    project_id=project.id,
                    arxiv_id=entry.arxiv_id,
                    title=entry.title,
                    authors=entry.authors,
                    abstract=entry.abstract,
                    year=entry.year,
                    pdf_url=entry.pdf_url,
                    entry_url=entry.entry_url,
                    score=score,
                    rationale=rationale,
                    selected=False,
                )
                seen[entry.arxiv_id] = candidate
            else:
                candidate.score = max(candidate.score, score)
                candidate.rationale = rationale if score >= candidate.score else candidate.rationale
            db.add(candidate)

    project.status = "discovered"
    db.add(project)
    db.commit()
    return get_project_or_404(db, project.id)


def import_selected_candidates(
    db: Session,
    project_id: str,
    candidate_ids: list[str],
    background_tasks: BackgroundTasks,
) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    if not candidate_ids:
        candidate_ids = [candidate.id for candidate in project.candidates if candidate.selected]
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="Select at least one candidate to import")

    candidates = db.query(ResearchCandidate).filter(ResearchCandidate.project_id == project_id, ResearchCandidate.id.in_(candidate_ids)).all()
    if not candidates:
        raise HTTPException(status_code=404, detail="No matching candidates found")

    for candidate in candidates:
        entry = fetch_arxiv_entry(candidate.arxiv_id)
        paper, _ = create_or_update_paper_from_arxiv(db, entry)
        candidate.selected = True
        link_exists = (
            db.query(ResearchProjectPaper)
            .filter(ResearchProjectPaper.project_id == project_id, ResearchProjectPaper.paper_id == paper.id)
            .first()
        )
        if link_exists is None:
            db.add(ResearchProjectPaper(project_id=project_id, paper_id=paper.id, role="evidence"))
        enqueue_analysis_job(db, paper.id, background_tasks, auto_reset=True)

    project.status = "importing"
    db.add(project)
    db.commit()
    return get_project_or_404(db, project_id)


def approve_research_workflow(
    db: Session,
    project_id: str,
    candidate_ids: list[str],
    background_tasks: BackgroundTasks,
) -> ResearchProject:
    project = import_selected_candidates(db, project_id, candidate_ids, background_tasks)
    project.status = "analyzing"
    db.add(project)
    db.commit()
    return get_project_or_404(db, project_id)


def get_workflow_status(db: Session, project_id: str) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    if project.status in {"analyzing", "synthesizing"}:
        project = maybe_synthesize_ready_project(db, project)
    return project


def maybe_synthesize_ready_project(db: Session, project: ResearchProject) -> ResearchProject:
    papers = [link.paper for link in project.papers if link.paper is not None]
    if not papers:
        return project
    if any(paper.status == "failed" for paper in papers):
        project.status = "failed"
        db.add(project)
        db.commit()
        return get_project_or_404(db, project.id)
    if all(paper.status == "ready" for paper in papers) and not project.synthesis_json:
        project.status = "synthesizing"
        db.add(project)
        db.commit()
        return synthesize_project(db, project.id)
    return project


def synthesize_project(db: Session, project_id: str) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    contexts = build_paper_contexts(project)
    if not contexts:
        raise HTTPException(status_code=400, detail="No analyzed paper evidence is available for synthesis")

    brief = get_ai_provider().synthesize_collection(project.question, contexts)
    ensure_cited_brief(brief)
    project.synthesis_json = brief.model_dump()
    project.status = "done"
    db.add(project)
    db.commit()
    return get_project_or_404(db, project.id)


def build_paper_contexts(project: ResearchProject) -> list[dict[str, Any]]:
    contexts = []
    for link in project.papers:
        paper = link.paper
        if paper is None:
            continue
        summary = paper.summary
        chunks = sorted(paper.chunks, key=lambda chunk: chunk.chunk_index)[:8]
        if summary is None and not chunks:
            continue
        contexts.append(
            {
                "paper_id": paper.id,
                "title": paper.title,
                "summary": summarize_existing_paper(summary, paper),
                "chunks": [chunk_to_payload(chunk) for chunk in chunks],
            }
        )
    return contexts


def build_paper_contexts_by_ids(db: Session, paper_ids: list[str]) -> list[dict[str, Any]]:
    if not paper_ids:
        return []
    papers = (
        db.query(Paper)
        .options(selectinload(Paper.chunks), selectinload(Paper.summary))
        .filter(Paper.id.in_(paper_ids))
        .all()
    )
    contexts = []
    for paper in papers:
        chunks = sorted(paper.chunks, key=lambda chunk: chunk.chunk_index)[:8]
        if paper.summary is None and not chunks:
            continue
        contexts.append(
            {
                "paper_id": paper.id,
                "title": paper.title,
                "summary": summarize_existing_paper(paper.summary, paper),
                "chunks": [chunk_to_payload(chunk) for chunk in chunks],
            }
        )
    return contexts


def summarize_batch_papers(db: Session, paper_ids: list[str], goal: str) -> BatchSummary:
    contexts = build_paper_contexts_by_ids(db, paper_ids)
    if not contexts:
        raise HTTPException(status_code=400, detail="No analyzed paper evidence is available for batch summary")
    try:
        return get_ai_provider().summarize_batch(goal, contexts)
    except Exception:
        return MockProvider().summarize_batch(goal, contexts)


def summarize_existing_paper(summary: PaperSummary | None, paper: Paper) -> str:
    if summary is None:
        return paper.abstract or "No paper summary is available yet."
    return " ".join(
        [
            summary.problem_or_hypothesis,
            summary.approach,
            summary.experiments,
            summary.results,
            summary.conclusion,
            summary.limitations_or_notes,
        ]
    )


def chunk_to_payload(chunk: PaperChunk) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "section_label": chunk.section_label,
        "text": chunk.text,
    }


def candidate_to_payload(candidate: ResearchCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "arxiv_id": candidate.arxiv_id,
        "title": candidate.title,
        "authors": candidate.authors,
        "abstract": candidate.abstract,
        "year": candidate.year,
        "score": candidate.score,
        "rationale": candidate.rationale,
    }


def ensure_cited_brief(brief: ResearchBrief) -> None:
    sections = [
        *brief.key_findings,
        *brief.evidence_table,
        *brief.conflicts_or_gaps,
        *brief.suggested_experiments,
        *brief.suggested_research_directions,
    ]
    missing = [finding.label for finding in sections if not finding.citations]
    if missing:
        raise HTTPException(status_code=422, detail=f"Synthesis returned uncited claims: {', '.join(missing)}")


def score_candidate(question: str, entry: ArxivEntry) -> tuple[int, str]:
    question_terms = keyword_set(question)
    document_terms = keyword_set(f"{entry.title} {entry.abstract}")
    overlap = sorted(question_terms & document_terms)
    score = min(100, 35 + (len(overlap) * 8))
    if entry.year and entry.year >= 2020:
        score += 8
    score = min(score, 100)
    rationale = "Matched terms: " + ", ".join(overlap[:8]) if overlap else "Ranked from arXiv query match and metadata."
    return score, rationale


def keyword_set(text: str) -> set[str]:
    stopwords = {"the", "and", "for", "with", "from", "that", "this", "into", "how", "can", "are", "using"}
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2 and token not in stopwords}


def seed_demo_project(db: Session) -> ResearchProject:
    existing = db.query(ResearchProject).filter(ResearchProject.question == DEMO_QUESTION).one_or_none()
    if existing is not None:
        return existing

    project = create_project(db, DEMO_QUESTION)
    plan_project(db, project.id)
    for arxiv_id in DEMO_ARXIV_IDS:
        entry = fetch_arxiv_entry(arxiv_id)
        score, rationale = score_candidate(DEMO_QUESTION, entry)
        db.add(
            ResearchCandidate(
                project_id=project.id,
                arxiv_id=entry.arxiv_id,
                title=entry.title,
                authors=entry.authors,
                abstract=entry.abstract,
                year=entry.year,
                pdf_url=entry.pdf_url,
                entry_url=entry.entry_url,
                score=score,
                rationale=rationale,
                selected=True,
            )
        )
    project.status = "discovered"
    db.add(project)
    db.commit()
    return get_project_or_404(db, project.id)
