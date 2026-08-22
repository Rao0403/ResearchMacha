from __future__ import annotations

import re
from typing import Any

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session, object_session, selectinload

from app.ai import BatchSummary, MockProvider, ResearchBrief, get_ai_provider
from app.models.paper import AgentRun, Paper, PaperChunk, PaperSummary, ResearchCandidate, ResearchProject, ResearchProjectPaper
from app.schemas.memory import ResearchMemoryRead
from app.schemas.paper import LibraryPaperRead
from app.schemas.research import AgentRunRead, AgentStepRead, ResearchCandidateRead, ResearchProjectRead
from app.services.agent_trace import (
    complete_agent_step,
    create_agent_run,
    fail_agent_step,
    latest_agent_run,
    set_agent_run_status,
    start_agent_step,
    summarize_candidates_for_trace,
)
from app.services.analysis import enqueue_analysis_job
from app.services.arxiv import ArxivEntry, fetch_arxiv_entry, search_arxiv
from app.services.fallbacks import record_fallback
from app.services.memory import create_memory, latest_memories, memory_payload, retrieve_memories
from app.services.papers import create_or_update_paper_from_arxiv
from app.services.vector_store import get_vector_store

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
            selectinload(ResearchProject.agent_runs).selectinload(AgentRun.steps),
        )
        .filter(ResearchProject.id == project_id)
        .one_or_none()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Research project not found")
    return project


def serialize_project(project: ResearchProject) -> ResearchProjectRead:
    papers = [LibraryPaperRead.model_validate(link.paper) for link in project.papers if link.paper is not None]
    latest_run = sorted(project.agent_runs, key=lambda run: run.created_at, reverse=True)[0] if project.agent_runs else None
    db = object_session(project)
    if db is not None:
        memories = latest_memories(db, project_id=project.id, limit=8)
    else:
        memories = sorted(project.memories, key=lambda memory: memory.updated_at, reverse=True)[:8]
    agent_run = None
    if latest_run is not None:
        agent_run = AgentRunRead(
            id=latest_run.id,
            project_id=latest_run.project_id,
            status=latest_run.status,
            goal=latest_run.goal,
            error_message=latest_run.error_message,
            created_at=latest_run.created_at,
            updated_at=latest_run.updated_at,
            started_at=latest_run.started_at,
            finished_at=latest_run.finished_at,
            steps=[AgentStepRead.model_validate(step) for step in sorted(latest_run.steps, key=lambda item: item.position)],
        )
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
        agent_run=agent_run,
        memory_signals=[ResearchMemoryRead.model_validate(memory) for memory in memories],
    )


def start_research_workflow(db: Session, question: str) -> ResearchProject:
    project = create_project(db, question)
    agent_run = create_agent_run(db, project.id, question)
    try:
        project = plan_project(db, project.id, agent_run)
        project = discover_candidates(db, project.id, agent_run=agent_run)
        project = select_recommended_candidates(db, project.id, agent_run)
        set_agent_run_status(db, agent_run, project.status)
        return project
    except Exception as exc:
        set_agent_run_status(db, agent_run, "failed", str(exc))
        raise


def select_recommended_candidates(db: Session, project_id: str, agent_run: AgentRun | None = None) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    candidates = (
        db.query(ResearchCandidate)
        .filter(ResearchCandidate.project_id == project_id)
        .order_by(ResearchCandidate.score.desc())
        .all()
    )
    memory_signals = retrieve_memories(db, project.question, limit=6)
    memory_payloads = [memory_payload(memory) for memory in memory_signals]
    step = start_agent_step(
        db,
        agent_run,
        "select_candidates",
        {
            "candidate_count": len(candidates),
            "question": project.question,
            "memory_count": len(memory_payloads),
        },
    )
    if not candidates:
        project.status = "no_candidates"
        db.add(project)
        db.commit()
        complete_agent_step(db, step, {"selected_count": 0, "status": project.status})
        return get_project_or_404(db, project_id)

    candidate_payloads = apply_memory_bias([candidate_to_payload(candidate) for candidate in candidates], memory_payloads)

    try:
        selection = get_ai_provider().select_relevant_candidates(project.question, candidate_payloads, memory_payloads)
        selected_ids = {choice.arxiv_id for choice in selection.selected}
        rationales = {choice.arxiv_id: choice.rationale for choice in selection.selected}
    except Exception as exc:
        record_fallback("research.select_candidates", "top_3_by_score", str(exc), {"candidate_count": len(candidates)})
        selected_ids = fallback_selected_arxiv_ids(candidate_payloads)
        rationales = {arxiv_id: "Selected by memory-adjusted deterministic ranking." for arxiv_id in selected_ids}

    if not selected_ids:
        record_fallback("research.select_candidates", "top_3_by_score", "LLM candidate selection returned no selected papers.", {"candidate_count": len(candidates)})
        selected_ids = fallback_selected_arxiv_ids(candidate_payloads)

    for candidate in candidates:
        candidate.selected = candidate.arxiv_id in selected_ids
        if candidate.selected and candidate.arxiv_id in rationales:
            candidate.rationale = rationales[candidate.arxiv_id]
        db.add(candidate)

    project.status = "awaiting_approval"
    db.add(project)
    db.commit()
    complete_agent_step(
        db,
        step,
        {
            "selected_count": sum(1 for candidate in candidates if candidate.selected),
            "selected_arxiv_ids": [candidate.arxiv_id for candidate in candidates if candidate.selected],
            "top_candidates": summarize_candidates_for_trace(candidates),
            "memory_count": len(memory_payloads),
            "memory_adjusted_candidates": [
                {
                    "arxiv_id": candidate["arxiv_id"],
                    "base_score": candidate.get("base_score", candidate.get("score")),
                    "score": candidate.get("score"),
                    "memory_signal": candidate.get("memory_signal"),
                }
                for candidate in candidate_payloads
                if candidate.get("memory_signal")
            ],
            "status": project.status,
        },
    )
    return get_project_or_404(db, project_id)


def plan_project(db: Session, project_id: str, agent_run: AgentRun | None = None) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    step = start_agent_step(db, agent_run, "plan_search", {"question": project.question})
    try:
        plan = get_ai_provider().plan_research(project.question)
    except Exception as exc:
        fail_agent_step(db, step, exc)
        raise
    project.generated_queries = plan.search_queries
    project.inclusion_criteria = plan.inclusion_criteria
    project.status = "planned"
    db.add(project)
    db.commit()
    complete_agent_step(
        db,
        step,
        {
            "search_queries": plan.search_queries,
            "inclusion_criteria": plan.inclusion_criteria,
            "status": project.status,
        },
    )
    return get_project_or_404(db, project.id)


def discover_candidates(db: Session, project_id: str, max_per_query: int = 6, agent_run: AgentRun | None = None) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    if not project.generated_queries:
        project = plan_project(db, project_id, agent_run)

    seen = {candidate.arxiv_id: candidate for candidate in project.candidates}
    search_step = start_agent_step(
        db,
        agent_run,
        "search_arxiv",
        {"queries": project.generated_queries[:4], "max_per_query": max_per_query},
    )
    rank_step = None
    query_counts: list[dict[str, Any]] = []
    try:
        for query in project.generated_queries[:4]:
            entries = search_arxiv(query, max_results=max_per_query)
            query_counts.append({"query": query, "result_count": len(entries)})
            for entry in entries:
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
                    previous_score = candidate.score
                    candidate.score = max(candidate.score, score)
                    candidate.rationale = rationale if score >= previous_score else candidate.rationale
                db.add(candidate)
        complete_agent_step(
            db,
            search_step,
            {
                "queries": query_counts,
                "unique_candidate_count": len(seen),
            },
        )
        rank_step = start_agent_step(
            db,
            agent_run,
            "rank_candidates",
            {"candidate_count": len(seen), "ranking_method": "keyword overlap + recency boost"},
        )
    except Exception as exc:
        fail_agent_step(db, search_step, exc)
        raise

    project.status = "discovered"
    db.add(project)
    db.commit()
    project = get_project_or_404(db, project.id)
    complete_agent_step(
        db,
        rank_step,
        {
            "candidate_count": len(project.candidates),
            "top_candidates": summarize_candidates_for_trace(
                sorted(project.candidates, key=lambda candidate: candidate.score, reverse=True)
            ),
            "status": project.status,
        },
    )
    return project


def import_selected_candidates(
    db: Session,
    project_id: str,
    candidate_ids: list[str],
    background_tasks: BackgroundTasks,
    agent_run: AgentRun | None = None,
) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    if not candidate_ids:
        candidate_ids = [candidate.id for candidate in project.candidates if candidate.selected]
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="Select at least one candidate to import")

    candidates = db.query(ResearchCandidate).filter(ResearchCandidate.project_id == project_id, ResearchCandidate.id.in_(candidate_ids)).all()
    if not candidates:
        raise HTTPException(status_code=404, detail="No matching candidates found")

    import_step = start_agent_step(
        db,
        agent_run,
        "import_papers",
        {"candidate_ids": candidate_ids, "candidate_count": len(candidates)},
    )
    analyze_step = None
    imported_papers: list[dict[str, Any]] = []
    queued_jobs: list[dict[str, Any]] = []
    for candidate in candidates:
        entry = fetch_arxiv_entry(candidate.arxiv_id)
        paper, _ = create_or_update_paper_from_arxiv(db, entry)
        imported_papers.append({"paper_id": paper.id, "arxiv_id": candidate.arxiv_id, "title": paper.title})
        candidate.selected = True
        link_exists = (
            db.query(ResearchProjectPaper)
            .filter(ResearchProjectPaper.project_id == project_id, ResearchProjectPaper.paper_id == paper.id)
            .first()
        )
        if link_exists is None:
            db.add(ResearchProjectPaper(project_id=project_id, paper_id=paper.id, role="evidence"))
        job = enqueue_analysis_job(db, paper.id, background_tasks, auto_reset=True)
        queued_jobs.append({"paper_id": paper.id, "job_id": job.id, "status": job.status})

    complete_agent_step(db, import_step, {"imported_papers": imported_papers})
    analyze_step = start_agent_step(
        db,
        agent_run,
        "analyze_papers",
        {"paper_ids": [item["paper_id"] for item in imported_papers]},
    )
    complete_agent_step(db, analyze_step, {"queued_jobs": queued_jobs})

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
    agent_run = latest_agent_run(db, project_id) or create_agent_run(db, project_id, f"Approve papers for project {project_id}")
    existing_project = get_project_or_404(db, project_id)
    effective_candidate_ids = candidate_ids or [candidate.id for candidate in existing_project.candidates if candidate.selected]
    project = import_selected_candidates(db, project_id, candidate_ids, background_tasks, agent_run)
    project.status = "analyzing"
    db.add(project)
    db.commit()
    remember_candidate_decisions(db, project_id, effective_candidate_ids)
    set_agent_run_status(db, agent_run, project.status)
    return get_project_or_404(db, project_id)


def get_workflow_status(db: Session, project_id: str) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    if project.status in {"analyzing", "synthesizing"}:
        project = maybe_synthesize_ready_project(db, project)
    return project


def maybe_synthesize_ready_project(db: Session, project: ResearchProject) -> ResearchProject:
    agent_run = latest_agent_run(db, project.id)
    papers = [link.paper for link in project.papers if link.paper is not None]
    if not papers:
        return project
    if any(paper.status == "failed" for paper in papers):
        project.status = "failed"
        db.add(project)
        db.commit()
        set_agent_run_status(db, agent_run, "failed", "At least one imported paper analysis failed.")
        return get_project_or_404(db, project.id)
    if all(paper.status == "ready" for paper in papers) and not project.synthesis_json:
        project.status = "synthesizing"
        db.add(project)
        db.commit()
        set_agent_run_status(db, agent_run, project.status)
        return synthesize_project(db, project.id, agent_run)
    return project


def synthesize_project(db: Session, project_id: str, agent_run: AgentRun | None = None) -> ResearchProject:
    project = get_project_or_404(db, project_id)
    agent_run = agent_run or latest_agent_run(db, project_id)
    contexts = build_paper_contexts(project)
    if not contexts:
        raise HTTPException(status_code=400, detail="No analyzed paper evidence is available for synthesis")

    memory_signals = retrieve_memories(db, project.question, limit=8)
    memory_payloads = [memory_payload(memory) for memory in memory_signals]
    step = start_agent_step(
        db,
        agent_run,
        "synthesize_brief",
        {
            "paper_count": len(contexts),
            "chunk_counts": [len(context.get("chunks", [])) for context in contexts],
            "question": project.question,
            "memory_count": len(memory_payloads),
        },
    )
    try:
        brief = get_ai_provider().synthesize_collection(project.question, contexts, memory_payloads)
        ensure_cited_brief(brief)
    except Exception as exc:
        fail_agent_step(db, step, exc)
        set_agent_run_status(db, agent_run, "failed", str(exc))
        raise
    project.synthesis_json = brief.model_dump()
    project.status = "done"
    db.add(project)
    db.commit()
    complete_agent_step(
        db,
        step,
        {
            "key_findings": len(brief.key_findings),
            "evidence_rows": len(brief.evidence_table),
            "suggested_experiments": len(brief.suggested_experiments),
            "suggested_research_directions": len(brief.suggested_research_directions),
            "memory_count": len(memory_payloads),
            "status": project.status,
        },
    )
    set_agent_run_status(db, agent_run, project.status)
    return get_project_or_404(db, project.id)


def build_paper_contexts(project: ResearchProject) -> list[dict[str, Any]]:
    contexts = []
    db = object_session(project)
    for link in project.papers:
        paper = link.paper
        if paper is None:
            continue
        summary = paper.summary
        chunks = select_context_chunks(db, paper, project.question, limit=8) if db is not None else first_chunks(paper, limit=8)
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


def build_paper_contexts_by_ids(db: Session, paper_ids: list[str], query: str | None = None) -> list[dict[str, Any]]:
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
        chunks = select_context_chunks(db, paper, query or paper.title, limit=8)
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
    contexts = build_paper_contexts_by_ids(db, paper_ids, query=goal)
    if not contexts:
        raise HTTPException(status_code=400, detail="No analyzed paper evidence is available for batch summary")
    try:
        return get_ai_provider().summarize_batch(goal, contexts)
    except Exception as exc:
        record_fallback("research.summarize_batch", "mock.summarize_batch", str(exc), {"paper_count": len(contexts)})
        return MockProvider().summarize_batch(goal, contexts)


def select_context_chunks(db: Session, paper: Paper, query: str, limit: int) -> list[PaperChunk]:
    try:
        query_embedding = get_ai_provider().embed_texts([query])[0]
        chunks = get_vector_store().search_paper_chunks(db, paper.id, query_embedding, limit=limit)
        if chunks:
            return chunks
        record_fallback("research.select_context_chunks", "first_chunks", "Vector retrieval returned no chunks.", {"paper_id": paper.id, "limit": limit})
    except Exception as exc:
        record_fallback("research.select_context_chunks", "first_chunks", str(exc), {"paper_id": paper.id, "limit": limit})
    return first_chunks(paper, limit)


def first_chunks(paper: Paper, limit: int) -> list[PaperChunk]:
    return sorted(paper.chunks, key=lambda chunk: chunk.chunk_index)[:limit]


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


def apply_memory_bias(candidates: list[dict[str, Any]], memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    positive_terms, negative_terms = memory_term_sets(memories)
    adjusted_candidates = []
    for candidate in candidates:
        adjusted = dict(candidate)
        candidate_terms = keyword_set(f"{candidate.get('title', '')} {candidate.get('abstract', '')}")
        positive_hits = sorted(candidate_terms & positive_terms)
        negative_hits = sorted(candidate_terms & negative_terms)
        score_adjustment = min(12, len(positive_hits) * 3) - min(12, len(negative_hits) * 4)
        adjusted["base_score"] = candidate.get("score", 0)
        adjusted["score"] = max(0, min(100, int(candidate.get("score", 0)) + score_adjustment))
        if score_adjustment:
            signal_parts = []
            if positive_hits:
                signal_parts.append(f"positive: {', '.join(positive_hits[:5])}")
            if negative_hits:
                signal_parts.append(f"negative: {', '.join(negative_hits[:5])}")
            adjusted["memory_signal"] = "; ".join(signal_parts)
        adjusted_candidates.append(adjusted)
    return sorted(adjusted_candidates, key=lambda candidate: candidate.get("score", 0), reverse=True)


def memory_term_sets(memories: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    positive_terms: set[str] = set()
    negative_terms: set[str] = set()
    for memory in memories:
        metadata = memory.get("metadata_json") or {}
        term_source = str(memory.get("text") or "")
        if memory.get("memory_type") == "rejected_paper":
            term_source = f"{metadata.get('title', '')} {metadata.get('rationale', '')}"
        terms = keyword_set(term_source)
        if memory.get("memory_type") == "rejected_paper":
            negative_terms.update(terms)
        else:
            positive_terms.update(terms)
    return positive_terms, negative_terms


def fallback_selected_arxiv_ids(candidates: list[dict[str, Any]]) -> set[str]:
    return {candidate["arxiv_id"] for candidate in sorted(candidates, key=lambda item: item.get("score", 0), reverse=True)[:3]}


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


def remember_candidate_decisions(db: Session, project_id: str, approved_candidate_ids: list[str]) -> None:
    approved_ids = set(approved_candidate_ids)
    if not approved_ids:
        return

    try:
        project = get_project_or_404(db, project_id)
        candidates = sorted(project.candidates, key=lambda candidate: candidate.score, reverse=True)
        selected_candidates = [candidate for candidate in candidates if candidate.id in approved_ids]
        for candidate in candidates:
            accepted = candidate.id in approved_ids
            decision = "accepted" if accepted else "rejected"
            create_memory(
                db,
                scope="project",
                memory_type=f"{decision}_paper",
                text=(
                    f"{decision.title()} paper for research question '{project.question}': {candidate.title}. "
                    f"Rationale: {candidate.rationale}"
                ),
                project_id=project.id,
                metadata_json={
                    "decision": decision,
                    "candidate_id": candidate.id,
                    "arxiv_id": candidate.arxiv_id,
                    "title": candidate.title,
                    "score": candidate.score,
                    "rationale": candidate.rationale,
                    "year": candidate.year,
                },
                importance=3 if accepted else 2,
                source="approval",
            )

        if selected_candidates:
            profile = infer_preference_profile(project.question, selected_candidates)
            create_memory(
                db,
                scope="user",
                memory_type="preference",
                text=(
                    "User preference inferred from approved research papers. "
                    f"Domains: {', '.join(profile['domains']) or 'unspecified'}. "
                    f"Methods: {', '.join(profile['methods']) or 'unspecified'}. "
                    f"Datasets: {', '.join(profile['datasets']) or 'unspecified'}. "
                    f"Recency preference: {profile['recency_preference']}. "
                    f"Keywords: {', '.join(profile['keywords'][:10])}. "
                    f"Accepted papers: {', '.join(candidate.title for candidate in selected_candidates[:4])}."
                ),
                project_id=project.id,
                metadata_json=profile,
                importance=3,
                source="approval",
            )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        record_fallback("memory.candidate_decisions", "skip_memory_write", str(exc), {"project_id": project_id})


def infer_preference_profile(question: str, candidates: list[ResearchCandidate]) -> dict[str, Any]:
    combined = " ".join([question, *[candidate.title for candidate in candidates], *[candidate.abstract for candidate in candidates]])
    terms = keyword_set(combined)
    years = [candidate.year for candidate in candidates if candidate.year]
    return {
        "domains": infer_domains(terms),
        "methods": sorted(terms & METHOD_TERMS)[:10],
        "datasets": infer_datasets(combined),
        "recency_preference": infer_recency_preference(question, years),
        "keywords": sorted(terms)[:20],
        "accepted_arxiv_ids": [candidate.arxiv_id for candidate in candidates],
        "accepted_titles": [candidate.title for candidate in candidates],
        "year_range": [min(years), max(years)] if years else None,
    }


def infer_domains(terms: set[str]) -> list[str]:
    domains = []
    if terms & {"rag", "retrieval", "language", "llm", "nlp", "question", "answering", "summarization"}:
        domains.append("natural language processing")
    if terms & {"vision", "image", "visual", "diffusion", "segmentation", "detection"}:
        domains.append("computer vision")
    if terms & {"clinical", "medical", "health", "biomedical", "ehr"}:
        domains.append("healthcare ai")
    if terms & {"robot", "robotics", "control", "planning"}:
        domains.append("robotics")
    if terms & {"graph", "network", "node", "edge"}:
        domains.append("graph learning")
    return domains or ["general ai research"]


def infer_datasets(text: str) -> list[str]:
    blocked = {"The", "This", "These", "They", "Abstract", "Introduction", "Results", "Conclusion"}
    candidates = re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", text)
    datasets = []
    for candidate in candidates:
        if candidate in blocked or candidate.lower() in keyword_set(" ".join(blocked)):
            continue
        if candidate not in datasets:
            datasets.append(candidate)
    return datasets[:10]


def infer_recency_preference(question: str, years: list[int]) -> str:
    question_terms = keyword_set(question)
    if question_terms & {"recent", "latest", "new", "current", "modern"}:
        return "explicit_recent"
    if years and min(years) >= 2020:
        return "recent"
    if years and max(years) < 2020:
        return "foundational_or_older"
    return "mixed_or_unspecified"


METHOD_TERMS = {
    "ablation",
    "agent",
    "alignment",
    "benchmark",
    "chain",
    "contrastive",
    "diffusion",
    "embedding",
    "evaluation",
    "finetuning",
    "generation",
    "graph",
    "hallucination",
    "language",
    "llm",
    "memory",
    "prompting",
    "rag",
    "ranking",
    "reasoning",
    "retrieval",
    "rlhf",
    "transformer",
}


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
