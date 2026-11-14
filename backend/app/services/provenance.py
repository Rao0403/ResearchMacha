"""Metadata captured with a generated artifact, independent of its current workspace."""
from sqlalchemy.orm import Session
from app.models.paper import Paper


def paper_metadata(paper: Paper) -> dict:
    return {"paper_id": paper.id, "title": paper.title, "authors": list(paper.authors or []),
            "year": paper.year, "arxiv_id": paper.arxiv_id, "analysis_generation": paper.analysis_generation,
            "analysis_mode": paper.analysis_mode, "analysis_warning": paper.analysis_warning}


def capture_evidence(db: Session, contexts: list[dict]) -> list[dict]:
    sources = []
    for context in contexts:
        paper = db.get(Paper, context["paper_id"])
        metadata = paper_metadata(paper) if paper else {"paper_id": context["paper_id"], "title": context["title"]}
        sources.append({**metadata, "chunk_ids": [c["id"] for c in context.get("chunks", [])]})
    return sources


def brief_is_outdated(project) -> bool | None:
    artifact = (project.synthesis_json or {}).get("artifact")
    if not artifact:
        return None
    sources = {p["paper_id"]: p.get("analysis_generation") for p in artifact.get("papers", [])}
    current = {link.paper_id: link.paper.analysis_generation for link in project.papers if link.paper is not None}
    return artifact.get("generation") != project.synthesis_generation or sources != current
