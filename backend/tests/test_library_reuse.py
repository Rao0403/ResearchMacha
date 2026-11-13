from io import BytesIO
from pypdf import PdfWriter

from app.models.paper import Job, Paper, ResearchCandidate, ResearchProject, ResearchProjectPaper
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


def test_library_edits_cannot_change_active_evidence_or_exceed_combined_limit(api_client,db_session):
    papers=[ready_paper(db_session,str(index)) for index in range(2)]
    project=ResearchProject(question="How effective is adaptation?",status="synthesizing")
    db_session.add(project);db_session.commit()
    url=f"/api/research-workflows/{project.id}/papers"
    assert api_client.post(url,json={"paper_ids":[p.id for p in papers],"version":0}).status_code==409
    project.status="awaiting_approval";db_session.commit()
    assert api_client.post(url,json={"paper_ids":[p.id for p in papers],"version":0}).status_code==200
    for index in range(4):
        db_session.add(ResearchCandidate(project_id=project.id,arxiv_id=f"2401.0000{index}",title="Discovered",authors=[],abstract="",pdf_url="",entry_url="",score=1,rationale="",selected=True))
    db_session.commit()
    response=api_client.post(f"/api/research-workflows/{project.id}/approve",json={"candidate_ids":[]})
    assert response.status_code==400 and "five evidence" in response.json()["detail"]
    assert db_session.query(Job).count()==0


def test_ready_arxiv_import_reuses_analysis_without_external_calls(db_session,monkeypatch):
    paper=ready_paper(db_session)
    paper.source_key="arxiv:2401.00001";paper.arxiv_id="2401.00001"
    project=ResearchProject(question="How effective is this method?",status="awaiting_approval")
    db_session.add(project);db_session.flush()
    candidate=ResearchCandidate(project_id=project.id,arxiv_id=paper.arxiv_id,title="Existing",authors=[],abstract="",pdf_url="",entry_url="",score=1,rationale="",selected=True)
    db_session.add(candidate);db_session.commit()
    def unexpected(*args,**kwargs): raise AssertionError("Reuse must not fetch metadata, download or analyze")
    monkeypatch.setattr(research,"fetch_arxiv_entry",unexpected)
    monkeypatch.setattr(research,"enqueue_analysis_job",unexpected)
    research.import_selected_candidates(db_session,project.id,[candidate.id])
    job=db_session.query(Job).filter_by(job_type="import").one()
    job.status="running";db_session.commit()
    class Borrowed:
        def __getattr__(self,name): return getattr(db_session,name)
        def close(self): pass
    research.process_import_job(job.id,session_factory=Borrowed)
    assert job.status=="completed" and job.payload["reused_analysis"] is True
    assert db_session.query(Paper).count()==1
    assert db_session.query(Job).filter_by(job_type="analysis").count()==0
    project=db_session.get(ResearchProject,project.id);project.status="done";db_session.commit()
    research.import_selected_candidates(db_session,project.id,[candidate.id])
    assert db_session.get(ResearchProject,project.id).status=="done"


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
