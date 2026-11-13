from io import BytesIO
from pypdf import PdfWriter

from app.models.paper import Job, Paper, ResearchProject, ResearchProjectPaper
from app.services import research
from app.services.jobs import reconcile_job_project


def ready_paper(db, title="Reusable"):
    paper = Paper(source="upload", title=title, pdf_path="existing.pdf", status="ready", analysis_generation=1, analysis_mode="ai")
    db.add(paper)
    db.commit()
    return paper


def test_research_reuses_papers_without_analysis_and_requires_explicit_synthesis(api_client, db_session):
    paper = ready_paper(db_session)
    project = ResearchProject(question="How does this method perform?", status="done", synthesis_json={"executive_summary":"Keep"})
    db_session.add(project); db_session.commit()
    url = f"/api/research-workflows/{project.id}/papers"
    response = api_client.post(url, json={"paper_ids":[paper.id], "version":0})
    assert response.status_code == 200
    assert response.json()["synthesis_json"]["executive_summary"] == "Keep"
    assert response.json()["papers"][0]["id"] == paper.id
    assert db_session.query(Job).count() == 0
    assert api_client.post(url, json={"paper_ids":[paper.id], "version":0}).status_code == 409
    assert api_client.post(url, json={"paper_ids":[paper.id], "version":1}).status_code == 200
    assert db_session.query(ResearchProjectPaper).count() == 1


def test_library_only_research_queues_synthesis_not_analysis(api_client, db_session):
    paper = ready_paper(db_session)
    response = api_client.post("/api/research-workflows/from-library", json={"question":"How effective is this method?", "paper_ids":[paper.id]})
    assert response.status_code == 200
    assert response.json()["status"] == "synthesis_queued"
    assert [j.job_type for j in db_session.query(Job).all()] == ["synthesis"]


def test_mixed_comparison_validates_library_before_upload(api_client, db_session):
    paper = ready_paper(db_session)
    pdf = PdfWriter(); pdf.add_blank_page(width=100,height=100)
    stream = BytesIO(); pdf.write(stream)
    data={"name":"Mixed", "goal":"Compare evidence", "request_id":"mixed", "library_paper_ids":f'["{paper.id}"]'}
    response=api_client.post("/api/comparisons/upload", data=data, files=[("files",("new.pdf",stream.getvalue(),"application/pdf"))])
    assert response.status_code == 200
    assert len(response.json()["papers"]) == 2
    assert db_session.query(Job).filter_by(paper_id=paper.id).count() == 0
    before=db_session.query(Paper).count()
    data.update(request_id="invalid",library_paper_ids='["missing"]')
    assert api_client.post("/api/comparisons/upload", data=data, files=[("files",("new.pdf",stream.getvalue(),"application/pdf"))]).status_code == 404
    assert db_session.query(Paper).count() == before


def test_shared_analysis_notifies_every_project_and_exclusion_keeps_it_running(db_session, monkeypatch):
    paper=ready_paper(db_session)
    projects=[ResearchProject(question="A research question", status="analyzing") for _ in range(2)]
    db_session.add_all(projects); db_session.flush()
    for project in projects: db_session.add(ResearchProjectPaper(project_id=project.id,paper_id=paper.id,role="evidence"))
    job=Job(paper_id=paper.id,project_id=projects[0].id,job_type="analysis",status="running",idempotency_key="shared")
    db_session.add(job);db_session.commit()
    notified=[]
    monkeypatch.setattr(research,"reconcile_project",lambda db,ident: notified.append(ident))
    class Borrowed:
        def __enter__(self): return db_session
        def __exit__(self,*args): pass
    reconcile_job_project(job.id,session_factory=Borrowed)
    assert set(notified)=={p.id for p in projects}
    research.exclude_project_paper(db_session,projects[0].id,paper.id)
    assert db_session.get(Job,job.id).status == "running"
    assert db_session.get(Job,job.id).project_id is None
