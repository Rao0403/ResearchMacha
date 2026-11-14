from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.exports import load_artifact, notes_for_artifact, markdown, bibtex, comparison_csv, warnings_for

router=APIRouter()
ExportKind=Literal["paper","research","comparison"]


@router.get("/exports/{kind}/{ident}/options")
def export_options(kind: ExportKind, ident: str, db: Session=Depends(get_db)):
    artifact=load_artifact(db,kind,ident)
    titles={p["paper_id"]:p["title"] for p in artifact.papers}
    return {"has_result":artifact.result is not None,"paper_count":len(artifact.papers),"warnings":warnings_for(artifact),
            "notes":[{"id":n.id,"paper_id":n.paper_id,"paper_title":titles[n.paper_id],"page":n.page,"preview":n.body[:240]} for n in notes_for_artifact(db,artifact)]}


@router.get("/exports/{kind}/{ident}")
def export_saved_work(kind: ExportKind, ident: str, format: Literal["markdown","bibtex","csv"]=Query("markdown"),
                      note_ids: list[str]=Query(default=[],max_length=100), db: Session=Depends(get_db)):
    artifact=load_artifact(db,kind,ident)
    if format=="csv" and kind!="comparison":
        raise HTTPException(422,"CSV export is available for comparisons")
    if format!="markdown" and note_ids:
        raise HTTPException(422,"Personal notes can be included in Markdown exports")
    if format!="bibtex" and artifact.result is None and kind!="paper":
        raise HTTPException(409,"No saved result is available to export yet")
    notes=notes_for_artifact(db,artifact,note_ids)
    render={"markdown":lambda:markdown(artifact,notes),"bibtex":lambda:bibtex(artifact),"csv":lambda:comparison_csv(artifact)}
    extension,mime={"markdown":("md","text/markdown"),"bibtex":("bib","application/x-bibtex"),"csv":("csv","text/csv")}[format]
    import re
    safe_id=re.sub(r"[^a-zA-Z0-9_-]","-",ident)[:64]
    return Response(render[format](),media_type=mime,headers={
        "Content-Disposition":f'attachment; filename="research-macha-{kind}-{safe_id}.{extension}"',
        "Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})
