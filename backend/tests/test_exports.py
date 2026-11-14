import csv
import io
from sqlalchemy import event
from app.models.paper import Paper, PaperSummary, PaperNote, ResearchProject, Comparison, ComparisonPaper, Job
from app.services.provenance import paper_metadata


def seed(db):
    paper=Paper(source="arxiv",title='Δ Study, "Quotes" & 50%',authors=["Ada Researcher","Team & Co"],year=2024,
                arxiv_id="2401.00001",pdf_path="private-path.pdf",status="ready",analysis_generation=1,analysis_mode="ai")
    other=Paper(source="upload",title="Unrelated study",authors=[],pdf_path="secret.pdf",status="ready")
    db.add_all([paper,other]);db.flush()
    citation={"paper_id":paper.id,"title":paper.title,"page":2,"chunk_id":"old-source","excerpt":"A measured 82% result."}
    db.add(PaperSummary(paper_id=paper.id,problem_or_hypothesis="A question",approach="A method",experiments="A test",results="82% accuracy",
        conclusion="Qualified evidence",limitations_or_notes="One dataset",section_citations={"results":[citation]},generation_mode="ai"))
    note=PaperNote(paper_id=paper.id,body="My independent critique",page=2,excerpt="A chosen passage")
    foreign=PaperNote(paper_id=other.id,body="Private unrelated note")
    db.add_all([note,foreign]);db.flush()
    finding={"label":"Reported finding","summary":"A measured result","citations":[citation]}
    project=ResearchProject(question="Current research question",status="done",synthesis_generation=2,synthesis_json={
        "executive_summary":"A supported answer", "key_findings":[finding],"evidence_table":[finding],"conflicts_or_gaps":[],
        "suggested_experiments":[],"suggested_research_directions":[],"generation_mode":"ai","warnings":[],
        "artifact":{"question":"Original research question","generation":1,"generated_at":"2026-11-13T12:00:00Z","papers":[paper_metadata(paper)]}})
    comparison=Comparison(name="Saved comparison",goal="Edited goal",status="done",generation=2,result_generation=1,
        evidence_json={"papers":[paper_metadata(paper)],"goal":"Original comparison goal","generated_at":"2026-11-13T12:00:00Z"},result_json={
        "overall_takeaway":"Different evaluations", "generation_mode":"extractive","warnings":["Provider unavailable"],
        "papers":[{"paper_id":paper.id,"title":paper.title,"main_idea":"A method", "results":"82%, measured\non a fixed split", "citations":{"results":[citation]}}]})
    db.add_all([project,comparison]);db.flush()
    db.add(ComparisonPaper(comparison_id=comparison.id,paper_id=paper.id,position=0));db.commit()
    return paper,other,note,foreign,project,comparison


def test_markdown_exports_citations_and_only_selected_personal_notes(api_client,db_session):
    paper,_,note,foreign,_,_=seed(db_session)
    url=f"/api/exports/paper/{paper.id}"
    plain=api_client.get(url)
    assert plain.status_code==200 and "My independent critique" not in plain.text
    response=api_client.get(url,params={"note_ids":note.id})
    assert "82% accuracy" in response.text and "A measured 82% result." in response.text
    assert f"/reader/{paper.id}?page=2" in response.text and "old-source" in response.text
    assert "My Notes — personal commentary" in response.text and "My independent critique" in response.text
    assert "https://arxiv.org/abs/2401.00001" in response.text
    assert "private-path.pdf" not in response.text
    assert response.headers["content-disposition"].endswith('.md"')
    assert response.headers["cache-control"]=="no-store"
    assert api_client.get(url,params={"note_ids":foreign.id}).status_code==404


def test_bibtex_escapes_known_metadata_and_does_not_invent_missing_fields(api_client,db_session):
    paper,other,_,_,_,_=seed(db_session)
    response=api_client.get(f"/api/exports/paper/{paper.id}?format=bibtex")
    assert response.status_code==200
    assert r'Team \& Co' in response.text and r'50\%' in response.text
    assert "year = {2024}" in response.text and "eprint = {2401.00001}" in response.text
    unknown=api_client.get(f"/api/exports/paper/{other.id}?format=bibtex")
    assert "Publication metadata unverified" in unknown.text
    assert "author =" not in unknown.text and "year =" not in unknown.text and "journal =" not in unknown.text


def test_export_uses_saved_goal_sources_and_warnings_after_workspace_edits(api_client,db_session):
    paper,_,note,_,project,comparison=seed(db_session)
    research=api_client.get(f"/api/exports/research/{project.id}",params={"note_ids":note.id})
    assert "Original research question" in research.text and "Current research question" not in research.text
    assert "previous saved result" in research.text and paper.title.replace("&","&amp;") in research.text
    comparison_export=api_client.get(f"/api/exports/comparison/{comparison.id}")
    assert "Original comparison goal" in comparison_export.text and "Edited goal" not in comparison_export.text
    assert "Provider unavailable" in comparison_export.text and "Generation mode: extractive" in comparison_export.text
    assert "2026-11-13T12:00:00Z" in comparison_export.text


def test_csv_round_trips_sources_unicode_commas_quotes_newlines_and_formula_safety(api_client,db_session):
    paper,_,_,_,_,comparison=seed(db_session)
    result={**comparison.result_json,"papers":[{**comparison.result_json["papers"][0],"title":"=HYPERLINK(unsafe)"}]}
    comparison.result_json=result;db_session.commit()
    response=api_client.get(f"/api/exports/comparison/{comparison.id}?format=csv")
    rows=list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))
    assert rows[0]["Paper"]=="'=HYPERLINK(unsafe)"
    assert rows[0]["Results"]=="82%, measured\non a fixed split"
    assert "old-source" in rows[0]["Sources"] and paper.id in rows[0]["Sources"]
    assert rows[0]["Goal used"]=="Original comparison goal"


def test_exports_are_read_only_and_do_not_queue_work(api_client,db_session):
    paper,_,_,_,project,comparison=seed(db_session)
    writes=[]
    def inspect_sql(connection,cursor,statement,*args):
        if statement.lstrip().split(" ",1)[0].upper() in {"INSERT","UPDATE","DELETE"}: writes.append(statement)
    engine=db_session.get_bind();event.listen(engine,"before_cursor_execute",inspect_sql)
    try:
        for kind,ident in [("paper",paper.id),("research",project.id),("comparison",comparison.id)]:
            assert api_client.get(f"/api/exports/{kind}/{ident}/options").status_code==200
            for format in ["markdown","bibtex"]:
                assert api_client.get(f"/api/exports/{kind}/{ident}?format={format}").status_code==200
        assert not writes and db_session.query(Job).count()==0
    finally: event.remove(engine,"before_cursor_execute",inspect_sql)


def test_unavailable_results_and_legacy_provenance_are_explicit(api_client,db_session):
    _,_,_,_,project,comparison=seed(db_session)
    project.synthesis_json={"executive_summary":"Old result","generation_mode":"unknown_legacy"}
    comparison.result_json=None; db_session.commit()
    response=api_client.get(f"/api/exports/research/{project.id}")
    assert "Legacy brief has no full evidence snapshot" in response.text and "unknown" in response.text
    assert api_client.get(f"/api/exports/comparison/{comparison.id}?format=csv").status_code==409
    assert api_client.get(f"/api/exports/comparison/{comparison.id}?format=bibtex").status_code==200
    assert api_client.get("/api/exports/paper/missing").status_code==404
