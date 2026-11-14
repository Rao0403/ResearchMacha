"""Read-only exports of saved artifacts. No retrieval, inference, or file writes."""
from __future__ import annotations

import csv
import html
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.paper import Comparison, Job, Paper, PaperNote, ResearchProject
from app.services.provenance import brief_is_outdated, paper_metadata
from app.services.arxiv import normalize_arxiv_id

PAPER_SECTIONS = (("problem_or_hypothesis", "Problem or hypothesis"), ("approach", "Approach"),
                  ("experiments", "Experiments"), ("results", "Results"), ("conclusion", "Conclusion"),
                  ("limitations_or_notes", "Limitations and notes"))
BRIEF_SECTIONS = (("key_findings", "Key findings"), ("evidence_table", "Evidence"),
                  ("conflicts_or_gaps", "Conflicts and gaps"), ("suggested_experiments", "Suggested experiments"),
                  ("suggested_research_directions", "Research directions"))
COMPARISON_FIELDS = (("main_idea", "Main idea"), ("problem_or_hypothesis", "Problem / hypothesis"),
                     ("experiments", "Experiments"), ("models_and_datasets", "Models / datasets"),
                     ("results", "Results"), ("conclusions", "Conclusions"),
                     ("limitations", "Limitations"), ("comparability", "Evaluation conditions"))


@dataclass
class Artifact:
    kind: str
    ident: str
    title: str
    question: str | None
    result: dict | None
    papers: list[dict]
    mode: str
    generated_at: str | None
    warnings: list[str]
    outdated: bool | None = False


def utc_stamp(value=None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat(timespec="seconds")
    return value.isoformat()+"Z" if isinstance(value, datetime) and value.tzinfo is None else str(value)


def all_citations(result: dict) -> list[dict]:
    return [citation for field, _ in BRIEF_SECTIONS for finding in result.get(field, [])
            for citation in finding.get("citations", [])]


def legacy_sources(db: Session, citations: list[dict]) -> list[dict]:
    sources = {}
    for citation in citations:
        ident = citation.get("paper_id")
        if ident and ident not in sources:
            paper = db.get(Paper, ident)
            sources[ident] = paper_metadata(paper) if paper else {"paper_id":ident,"title":citation.get("title") or "Unavailable source record"}
            if citation.get("title"):
                sources[ident]["title"] = citation["title"]
    return list(sources.values())


def load_artifact(db: Session, kind: str, ident: str) -> Artifact:
    model = {"paper":Paper,"research":ResearchProject,"comparison":Comparison}[kind]
    row = db.get(model, ident)
    if row is None:
        raise HTTPException(404, "Saved workspace not found")
    if kind == "paper":
        summary = row.summary
        result = ({**{key:getattr(summary,key) for key,_ in PAPER_SECTIONS}, "section_citations":summary.section_citations,
                   "highlights":[{"label":h.label,"explanation":h.explanation,"citations":h.citations} for h in sorted(row.highlights,key=lambda h:h.position)]}
                  if summary else None)
        return Artifact(kind,ident,row.title,None,result,[paper_metadata(row)],summary.generation_mode if summary else row.analysis_mode,
                        utc_stamp(summary.updated_at) if summary else None,
                        [w for w in (row.analysis_warning,summary.warning if summary else "No generated notes are stored yet.") if w])
    if kind == "research":
        result = row.synthesis_json
        snapshot = (result or {}).get("artifact") or {}
        sources = snapshot.get("papers") if snapshot else legacy_sources(db,all_citations(result or {}))
        if not result:
            sources = [paper_metadata(link.paper) for link in row.papers]
        warnings = list((result or {}).get("warnings") or [])
        if result and not snapshot:
            warnings.append("Legacy brief has no full evidence snapshot. Sources are recovered from its citations using available library metadata; generation date is unknown.")
        return Artifact(kind,ident,row.name or "Research brief",snapshot.get("question") or row.question,result,sources or [],
                        (result or {}).get("generation_mode","unknown_legacy"),snapshot.get("generated_at"),warnings,brief_is_outdated(row))
    result = row.result_json
    snapshot = row.evidence_json or {}
    job = db.query(Job).filter(Job.comparison_id==ident,Job.requested_generation==row.result_generation,
        Job.status.in_(["completed","completed_with_warnings"])).order_by(Job.finished_at.desc()).first() if result else None
    original_goal = snapshot.get("goal") or ((job.payload or {}).get("goal") if job else None)
    sources = snapshot.get("papers", [])
    warnings = list((result or {}).get("warnings") or [])
    if result and not sources:
        citations = [c for paper in result.get("papers",[]) for values in paper.get("citations",{}).values() for c in values]
        sources = legacy_sources(db,citations)
        if not sources:
            sources = [{"paper_id":p["paper_id"],"title":p["title"]} for p in result.get("papers",[])]
        warnings.append("Legacy comparison has no complete evidence snapshot. Unrecorded metadata has not been inferred.")
    if result and original_goal is None:
        warnings.append("The goal used by this saved result was not recorded; the current edited goal has not been substituted.")
    if row.error_message:
        warnings.append(row.error_message)
    if not result:
        sources = [paper_metadata(link.paper) for link in row.papers]
    generations = {p["paper_id"]:p.get("analysis_generation") for p in sources}
    outdated = bool(result and (row.result_generation != row.generation or set(generations) != {l.paper_id for l in row.papers}
        or any(generations.get(l.paper_id) != l.paper.analysis_generation for l in row.papers)))
    return Artifact(kind,ident,row.name,original_goal if result else row.goal,result,sources,
                    (result or {}).get("generation_mode","unknown_legacy"),snapshot.get("generated_at") or (utc_stamp(job.finished_at) if job and job.finished_at else None),warnings,outdated)


def notes_for_artifact(db: Session, artifact: Artifact, ids: list[str] | None = None) -> list[PaperNote]:
    query = db.query(PaperNote).filter(PaperNote.paper_id.in_([p["paper_id"] for p in artifact.papers]))
    if ids is not None:
        if len(ids) != len(set(ids)):
            raise HTTPException(422,"Select each personal note once")
        query = query.filter(PaperNote.id.in_(ids))
    notes = query.order_by(PaperNote.created_at,PaperNote.id).all()
    if ids is not None and {note.id for note in notes} != set(ids):
        raise HTTPException(404,"A selected note does not belong to this result's evidence set")
    return notes


def warnings_for(artifact: Artifact) -> list[str]:
    warnings = list(artifact.warnings)
    if artifact.outdated:
        warnings.append("This is a previous saved result. The workspace question, evidence selection or analysis generation has changed; this export retains the saved result's recorded sources.")
    if artifact.mode != "ai":
        warnings.append({"mock":"Mock demonstration output; do not treat it as research evidence.",
                         "extractive":"Extractive output assembled from stored source material; not a completed AI synthesis.",
                         "unknown_legacy":"Generation provenance is unknown for this legacy result."}.get(artifact.mode,"Generation provenance is unavailable."))
    for paper in artifact.papers:
        if paper.get("analysis_warning"):
            warnings.append(f"{paper['title']}: {paper['analysis_warning']}")
        if paper.get("analysis_mode") in {"mock","extractive","unknown_legacy"}:
            warnings.append(f"{paper['title']}: source analysis mode is {paper['analysis_mode']}.")
    return list(dict.fromkeys(warnings))


def md(value) -> str:
    text = html.escape(str(value),quote=False).replace("\\","\\\\")
    return re.sub(r"([`*_{}\[\]()#!|])",r"\\\1",text)


def public_url(paper: dict) -> str | None:
    value = normalize_arxiv_id(paper.get("arxiv_id") or "")
    if re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})",value):
        return "https://arxiv.org/abs/"+value
    return None


def local_url(ident: str, page: int | None = None) -> str:
    from urllib.parse import quote
    return "/reader/"+quote(ident,safe="")+(f"?page={page}" if page else "")


def citation_lines(citations: list[dict], fallback_id: str | None = None) -> list[str]:
    lines = []
    for citation in citations:
        ident = citation.get("paper_id") or fallback_id
        title = citation.get("title") or "Source paper"
        label = f"{md(title)}, p.{md(citation.get('page','?'))}"
        lines += [f"- {label}"+(f" — [local PDF]({local_url(ident,citation.get('page'))})" if ident else ""),
                  f"  - Chunk: {md(citation.get('chunk_id') or 'not recorded')}"]
        lines += ["> "+md(line) for line in str(citation.get("excerpt") or "No excerpt recorded.").splitlines()]
        lines.append("")
    return lines


def markdown(artifact: Artifact, notes: list[PaperNote]) -> str:
    lines = ["# "+md(artifact.title),"",f"Exported at (UTC): {utc_stamp()}",
             f"Saved result date: {artifact.generated_at or 'Not recorded'}",f"Generation mode: {md(artifact.mode)}","",
             "Local workspace links require this ResearchMacha installation. Public references remain usable elsewhere.",""]
    if artifact.question is not None:
        lines += ["## Question / comparison goal","",md(artifact.question),""]
    for warning in warnings_for(artifact):
        lines += ["> Warning: "+md(warning),""]
    result = artifact.result or {}
    if artifact.kind == "paper":
        lines += ["## Generated reading notes",""]
        if not result:
            lines += ["No generated notes stored.",""]
        for key,label in PAPER_SECTIONS if result else []:
            lines += ["### "+label,"",md(result.get(key,"Not recorded.")),""]
            lines += citation_lines(result.get("section_citations",{}).get(key,[]),artifact.ident)
        if result.get("highlights"):
            lines += ["## Generated highlights",""]
            for highlight in result["highlights"]:
                lines += ["### "+md(highlight["label"]),"",md(highlight["explanation"]),""]
                lines += citation_lines(highlight.get("citations",[]),artifact.ident)
    elif artifact.kind == "research":
        lines += ["## Executive summary","",md(result.get("executive_summary","Not recorded.")),""]
        for field,label in BRIEF_SECTIONS:
            lines += ["## "+label,""]
            for finding in result.get(field,[]):
                lines += ["### "+md(finding["label"]),"",md(finding["summary"]),""]
                lines += citation_lines(finding.get("citations",[]))
            if not result.get(field):
                lines += ["No supported entries recorded in this saved result.",""]
    else:
        lines += ["## Overall takeaway","",md(result.get("overall_takeaway","Not recorded.")),""]
        for paper in result.get("papers",[]):
            lines += ["## "+md(paper["title"]),""]
            for key,label in COMPARISON_FIELDS:
                lines += ["### "+label,"",md(paper.get(key,"Not recorded in this saved result.")),""]
                lines += citation_lines(paper.get("citations",{}).get(key,[]),paper["paper_id"])
    if notes:
        lines += ["## My Notes — personal commentary","","These are user-authored notes, exported as they are now; they are not model-generated evidence.",""]
        titles={paper["paper_id"]:paper["title"] for paper in artifact.papers}
        for note in notes:
            lines += ["### "+md(titles[note.paper_id])+" — personal note","",md(note.body),"",f"Saved: {utc_stamp(note.updated_at)}",""]
            if note.page:
                lines += [f"[Local PDF, page {note.page}]({local_url(note.paper_id,note.page)})",""]
            if note.excerpt:
                lines += ["> Selected passage (user supplied):",*["> "+md(line) for line in note.excerpt.splitlines()],""]
    lines += ["## References",""]
    for index,paper in enumerate(artifact.papers,1):
        authors = ", ".join(paper.get("authors") or []) or "Authors not recorded"
        lines += [f"{index}. **{md(paper['title'])}**. {md(authors)}. {md(paper.get('year') or 'Year not recorded')}.",
                  f"   Local paper ID: {md(paper['paper_id'])}; analysis generation: {md(paper.get('analysis_generation','not recorded'))}."]
        url=public_url(paper)
        lines += [f"   [arXiv source]({url})" if url else "   Uploaded or unverified publication metadata; review the reference before submission.",""]
    return "\n".join(lines)+"\n"


def bib_escape(value) -> str:
    escapes={"\\":r"\textbackslash{}","{":r"\{","}":r"\}","%":r"\%","&":r"\&","_":r"\_",
             "#":r"\#","$":r"\$","~":r"\textasciitilde{}","^":r"\textasciicircum{}"}
    return "".join(escapes.get(char,char) for char in " ".join(str(value).split()))


def bibtex(artifact: Artifact) -> str:
    lines=["% ResearchMacha references. Only stored metadata is used; verify before submission.",f"% Exported at (UTC): {utc_stamp()}"]
    for warning in warnings_for(artifact): lines.append("% "+" ".join(warning.split()))
    for paper in artifact.papers:
        key="rm_"+re.sub(r"[^a-zA-Z0-9]","",paper["paper_id"])
        fields={"title":paper["title"]}
        if paper.get("authors"): fields["author"]=" and ".join(paper["authors"])
        if paper.get("year"): fields["year"]=str(paper["year"])
        url=public_url(paper)
        if url:
            fields.update(eprint=normalize_arxiv_id(paper["arxiv_id"]),archivePrefix="arXiv",url=url)
        else:
            fields["note"]="Publication metadata unverified; local ResearchMacha paper ID: "+paper["paper_id"]
        lines += ["",f"@misc{{{key},",*[("  "+name+" = {"+bib_escape(value)+"},") for name,value in fields.items()],"}"]
    return "\n".join(lines)+"\n"


def spreadsheet_cell(value) -> str:
    text=str(value)
    return "'"+text if text.lstrip().startswith(("=","+","-","@")) or text.startswith(("\t","\r")) else text


def comparison_csv(artifact: Artifact) -> str:
    output=io.StringIO(newline="")
    writer=csv.writer(output)
    writer.writerow(["Paper ID","Paper",*[label for _,label in COMPARISON_FIELDS],"Sources","Goal used","Generation mode","Saved result date","Warnings"])
    for paper in (artifact.result or {}).get("papers",[]):
        sources="\n".join(f"{field}: {c.get('title') or paper['title']}, p.{c.get('page')}, chunk {c.get('chunk_id')}: {c.get('excerpt')} [local {local_url(c.get('paper_id') or paper['paper_id'],c.get('page'))}]"
                          for field,values in paper.get("citations",{}).items() for c in values)
        writer.writerow([spreadsheet_cell(value) for value in [paper["paper_id"],paper["title"],*[paper.get(key,"Not recorded in saved result.") for key,_ in COMPARISON_FIELDS],
                         sources,artifact.question or "Not recorded",artifact.mode,artifact.generated_at or "Not recorded","; ".join(warnings_for(artifact))]])
    return "\ufeff"+output.getvalue()
