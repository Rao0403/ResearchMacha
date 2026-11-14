"""Exercise upload -> leased analysis -> saved work -> personal notes -> exports offline."""
from io import BytesIO
from uuid import uuid4
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.core.config import get_settings
from app.models.paper import Job
from app.services.jobs import claim_next_job, dispatch_job


def sample_pdf():
    writer=PdfWriter();page=writer.add_blank_page(width=400,height=600)
    font=DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),NameObject("/BaseFont"):NameObject("/Helvetica")})
    page[NameObject("/Resources")]=DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):writer._add_object(font)})})
    content=DecodedStreamObject();content.set_data(b"BT /F1 12 Tf 20 560 Td (Methods: evaluate a fixed classification dataset.) Tj 0 -30 Td (Results: accuracy reached 82 percent.) Tj ET")
    page[NameObject("/Contents")]=writer._add_object(content)
    stream=BytesIO();writer.write(stream);return stream.getvalue()


def test_complete_saved_workspace_journey_has_reusable_evidence_and_exports(api_client,db_session,monkeypatch):
    monkeypatch.setattr(get_settings(),"vector_provider","mysql")
    class Borrowed:
        def __getattr__(self,name):return getattr(db_session,name)
        def __enter__(self):return db_session
        def __exit__(self,*args):pass
        def close(self):pass
    def drain():
        for _ in range(8):
            ident=claim_next_job(Borrowed,worker_id="offline")
            if ident is None:return
            dispatch_job(ident,worker_id="offline",session_factory=Borrowed)
        raise AssertionError("Worker did not drain bounded fixture jobs")
    papers=[]
    for name in ["First study","Second study"]:
        response=api_client.post("/api/papers/upload",data={"title":name},files={"file":("study.pdf",sample_pdf(),"application/pdf")})
        assert response.status_code==200
        papers.append(response.json()["paper"]["id"])
    drain()
    for ident in papers:
        status=api_client.get(f"/api/papers/{ident}/status").json()
        assert status["status"] in {"ready","degraded"}
    analysis_count=db_session.query(Job).filter_by(job_type="analysis").count()
    note=api_client.post(f"/api/papers/{papers[0]}/notes",json={"id":str(uuid4()),"body":"My evaluation critique","page":1}).json()
    comparison=api_client.post("/api/comparisons",json={"name":"Evidence comparison","goal":"Compare evaluation conditions","paper_ids":papers,"request_id":"offline-comparison"}).json()
    research=api_client.post("/api/research-workflows/from-library",json={"question":"What can these evaluations establish?","paper_ids":papers}).json()
    drain()
    assert db_session.query(Job).filter_by(job_type="analysis").count()==analysis_count
    before=db_session.query(Job).count()
    for kind,ident,read_url in [("comparison",comparison["id"],"comparisons"),("research",research["id"],"research-workflows")]:
        reopened=api_client.get(f"/api/{read_url}/{ident}")
        assert reopened.status_code==200 and reopened.json()["status"] in {"done","degraded"}
        markdown=api_client.get(f"/api/exports/{kind}/{ident}",params={"note_ids":note["id"]})
        assert markdown.status_code==200 and "My evaluation critique" in markdown.text
        assert "Mock demonstration output" in markdown.text
        assert api_client.get(f"/api/exports/{kind}/{ident}?format=bibtex").status_code==200
    assert db_session.query(Job).count()==before
