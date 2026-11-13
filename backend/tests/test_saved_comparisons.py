from datetime import timedelta
from io import BytesIO
from pypdf import PdfWriter
import pytest
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from test_mysql_integration import mysql_database_url
from app.ai import MockProvider
from app.core.config import Settings
from app.models.paper import Paper,PaperChunk,PaperSummary,Comparison,Job
from app.models.states import JobStatus
from app.services import comparisons
from app.services.jobs import claim_next_job,dispatch_job,recover_interrupted_jobs,utc_now


def seed_papers(db):
    papers=[]
    for title in ["First","Second"]:
        p=Paper(source="upload",title=title,pdf_path="paper.pdf",status="ready",analysis_generation=1,analysis_mode="ai")
        db.add(p);db.flush()
        db.add(PaperChunk(paper_id=p.id,chunk_index=0,page_start=1,page_end=1,text="Reported experiment.",analysis_generation=1))
        db.add(PaperSummary(paper_id=p.id,problem_or_hypothesis="Problem",approach="Method",experiments="Experiment",results="Result",conclusion="Conclusion",limitations_or_notes="Limits",section_citations={},generation_mode="ai"))
        papers.append(p)
    db.commit()
    return papers


def setup_provider(monkeypatch):
    calls=[]
    class Provider(MockProvider):
        def summarize_batch(self,goal,contexts):
            calls.append(contexts)
            result=super().summarize_batch(goal,contexts)
            result.generation_mode="ai";result.warnings=[]
            return result
    monkeypatch.setattr(comparisons,"get_ai_provider",lambda:Provider())
    monkeypatch.setattr(comparisons,"build_paper_contexts_by_ids",lambda db,ids,query: [
        {"paper_id":pid,"title":db.get(Paper,pid).title,"summary":"Stored summary", "chunks":[{"id":"chunk","page_start":1,"page_end":1,"text":"Actual source."}]} for pid in ids])
    return calls


def run_job(db,job):
    job.status=JobStatus.RUNNING;job.worker_id="test";job.attempt_count+=1;db.commit()
    comparisons.process_comparison_job(job.id,session_factory=lambda: Borrowed(db))


class Borrowed:
    def __init__(self,db):self.db=db
    def __enter__(self):return self.db
    def __exit__(self,*args):pass


def test_comparison_is_saved_idempotent_and_read_only_on_reopen(api_client,db_session,monkeypatch):
    papers=seed_papers(db_session);calls=setup_provider(monkeypatch)
    payload={"name":"Saved comparison","goal":"Compare methods","paper_ids":[p.id for p in papers],"request_id":"create"}
    created=api_client.post("/api/comparisons",json=payload).json()
    ident=created["id"]
    assert api_client.post("/api/comparisons",json=payload).json()["id"]==ident
    assert db_session.query(Job).filter_by(comparison_id=ident).count()==1
    assert not calls
    job=db_session.query(Job).filter_by(comparison_id=ident).one()
    run_job(db_session,job)
    for _ in range(3):
        detail=api_client.get(f"/api/comparisons/{ident}").json()
        assert detail["status"]=="done" and detail["result_json"]["papers"][0]["title"]=="First"
        assert "result_json" not in api_client.get(f"/api/comparisons/{ident}/status").json()
    assert len(calls)==1
    assert db_session.get(Comparison,ident).evidence_json["papers"][0]["analysis_generation"]==1
    api_client.post(f"/api/comparisons/{ident}/generate",json={"request_id":"create","version":0})
    assert db_session.query(Job).count()==1
    edited=api_client.patch(f"/api/comparisons/{ident}",json={**payload,"goal":"Changed emphasis","version":0}).json()
    assert edited["outdated"] and edited["result_json"]==detail["result_json"]
    assert api_client.patch(f"/api/comparisons/{ident}",json={**payload,"version":0}).status_code==409


def test_waiting_papers_do_not_block_worker_and_readiness_queues_once(db_session):
    papers=seed_papers(db_session);papers[0].status="processing";db_session.commit()
    row=comparisons.create_comparison(db_session,name="Waiting",goal="Compare",ids=[p.id for p in papers],request_id="wait")
    assert row.status=="waiting_for_papers"
    # Use a non-closing session wrapper for the worker's transaction helpers.
    assert claim_next_job(lambda:Borrowed(db_session),worker_id="w",settings=Settings(_env_file=None,ai_provider="mock")) is None
    papers[0].status="ready";db_session.commit()
    comparisons.reconcile_comparison(db_session,row.id)
    assert db_session.get(Comparison,row.id).status=="queued"
    assert claim_next_job(lambda:Borrowed(db_session),worker_id="w",settings=Settings(_env_file=None,ai_provider="mock")) is not None


def test_restart_requeues_comparison_and_completed_generation_is_not_regenerated(db_session,monkeypatch):
    papers=seed_papers(db_session);calls=setup_provider(monkeypatch)
    row=comparisons.create_comparison(db_session,name="Restart",goal="Compare",ids=[p.id for p in papers],request_id="restart")
    job=db_session.query(Job).filter_by(comparison_id=row.id).one()
    job.status="running";job.worker_id="old";job.attempt_count=1;job.lease_expires_at=utc_now()-timedelta(seconds=2);row.status="running";db_session.commit()
    recover_interrupted_jobs(lambda:Borrowed(db_session),worker_id="new",settings=Settings(_env_file=None,ai_provider="mock"))
    assert job.status=="queued" and db_session.get(Comparison,row.id).status=="queued"
    run_job(db_session,job)
    job.status="running";db_session.commit()
    comparisons.process_comparison_job(job.id,session_factory=lambda:Borrowed(db_session))
    assert len(calls)==1 and job.status=="completed"


def test_stale_result_cannot_replace_edited_comparison(db_session,monkeypatch):
    papers=seed_papers(db_session);setup_provider(monkeypatch)
    row=comparisons.create_comparison(db_session,name="Race",goal="Compare",ids=[p.id for p in papers],request_id="race")
    job=db_session.query(Job).filter_by(comparison_id=row.id).one()
    original=comparisons.get_ai_provider()
    class EditingProvider:
        def summarize_batch(self,goal,contexts):
            comparisons.update_comparison(db_session,row.id,name="Edited",goal="New question",ids=[p.id for p in papers],version=0)
            return original.summarize_batch(goal,contexts)
    monkeypatch.setattr(comparisons,"get_ai_provider",lambda:EditingProvider())
    run_job(db_session,job)
    assert job.status=="cancelled"
    assert db_session.get(Comparison,row.id).result_json is None


def test_failed_required_paper_blocks_and_resume_preserves_completed_work(db_session):
    papers=seed_papers(db_session)
    papers[0].status="failed";db_session.commit()
    row=comparisons.create_comparison(db_session,name="Blocked",goal="Compare",ids=[p.id for p in papers],request_id="blocked")
    assert row.status=="blocked"
    assert comparisons.serialize_comparison(db_session,row)["blocking_items"][0]["paper_id"]==papers[0].id
    papers[0].status="ready";db_session.commit()
    comparisons.reconcile_comparison(db_session,row.id)
    assert db_session.get(Comparison,row.id).status=="queued"
    assert db_session.query(Job).count()==1


def test_upload_saves_comparison_and_replay_does_not_duplicate_uploads(api_client,db_session):
    pdf=PdfWriter();pdf.add_blank_page(width=100,height=100)
    stream=BytesIO();pdf.write(stream);content=stream.getvalue()
    def upload(): return api_client.post("/api/comparisons/upload",data={"name":"Upload","goal":"Compare methods","request_id":"upload"},
        files=[("files",("a.pdf",content,"application/pdf")),("files",("b.pdf",content,"application/pdf"))])
    first=upload()
    assert first.status_code==200
    assert first.json()["status"]=="waiting_for_papers"
    assert upload().json()["id"]==first.json()["id"]
    assert db_session.query(Paper).count()==2 and db_session.query(Job).count()==3


@pytest.mark.mysql
def test_mysql_comparison_claims_repeated_generation_and_atomic_result(mysql_database_url,monkeypatch):
    engine=create_engine(mysql_database_url,pool_pre_ping=True)
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    settings=Settings(_env_file=None,ai_provider="mock")
    calls=setup_provider(monkeypatch)
    with factory() as db:
        papers=seed_papers(db)
        ident=comparisons.create_comparison(db,name="MySQL",goal="Compare",ids=[p.id for p in papers],request_id="mysql").id
    job_id=claim_next_job(factory,worker_id="mysql-worker",settings=settings)
    dispatch_job(job_id,worker_id="mysql-worker",session_factory=factory,settings=settings)
    with factory() as db:
        assert db.get(Comparison,ident).status=="done"
    def generate(_):
        with factory() as db: return comparisons.generate_comparison(db,ident,"next",0).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(generate,range(2))))==1
    with factory() as db:
        assert db.query(Job).filter_by(comparison_id=ident).count()==2
    def claim(worker): return claim_next_job(factory,worker_id=worker,settings=settings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(value is not None for value in pool.map(claim,["a","b"]))==1
    assert len(calls)==1
    engine.dispose()
