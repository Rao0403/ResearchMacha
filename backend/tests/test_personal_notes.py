from uuid import uuid4
from app.models.paper import Paper, PaperNote
from app.services import analysis
from test_reader_workspace import reader_paper
from test_analysis_generations import analysis_database, seed_successful_analysis, configure_success
from test_mysql_integration import mysql_database_url
from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest


def test_notes_crud_replay_validation_and_conflicts(api_client, db_session, tmp_path):
    paper=reader_paper(db_session,tmp_path)
    base=f"/api/papers/{paper.id}/notes"
    payload={"id":str(uuid4()),"body":"My critique, not generated text.","page":2,"excerpt":"A selected passage"}
    first=api_client.post(base,json=payload)
    assert first.status_code==200 and first.json()["version"]==1
    assert api_client.post(base,json=payload).json()==first.json()
    assert db_session.query(PaperNote).count()==1
    url=base+"/"+payload["id"]
    changed=api_client.put(url,json={**payload,"body":"Updated thinking","version":1})
    assert changed.status_code==200 and changed.json()["version"]==2
    assert api_client.put(url,json={**payload,"version":1}).status_code==409
    assert api_client.delete(url+"?version=1").status_code==409
    assert api_client.get(base).json()[0]["body"]=="Updated thinking"
    assert api_client.post(base,json={**payload,"id":str(uuid4()),"page":4}).status_code==422
    assert api_client.post(base,json={**payload,"id":str(uuid4()),"body":"  "}).status_code==422
    other=Paper(source="upload",title="Other",pdf_path="other.pdf",status="ready")
    db_session.add(other);db_session.commit()
    other_url=f"/api/papers/{other.id}/notes/{payload['id']}"
    assert api_client.put(other_url,json={**payload,"version":2}).status_code==404
    assert api_client.delete(other_url+"?version=2").status_code==404
    assert api_client.delete(url+"?version=2").status_code==200
    assert api_client.get(base).json()==[]


def test_failed_reanalysis_does_not_touch_personal_notes(db_session,tmp_path,monkeypatch):
    paper=reader_paper(db_session,tmp_path)
    note=PaperNote(paper_id=paper.id,body="Keep my experiment idea",page=1)
    db_session.add(note);db_session.commit()
    job=analysis.enqueue_analysis_job(db_session,paper.id,auto_reset=True)
    monkeypatch.setattr(analysis,"extract_pdf_pages",lambda *a,**kw: (_ for _ in ()).throw(ValueError("No text")))
    class Borrowed:
        def __getattr__(self,name): return getattr(db_session,name)
        def close(self): pass
    try:
        analysis.process_analysis_job(job.id,session_factory=Borrowed)
    except ValueError:
        pass
    assert db_session.get(PaperNote,note.id).body=="Keep my experiment idea"


def test_successful_reanalysis_does_not_touch_personal_notes(tmp_path,monkeypatch):
    engine,factory=analysis_database(tmp_path)
    paper_id=seed_successful_analysis(factory)
    configure_success(monkeypatch)
    with factory() as db:
        note=PaperNote(paper_id=paper_id,body="My reproducibility question",page=1)
        db.add(note);db.commit();note_id=note.id
        job_id=analysis.enqueue_analysis_job(db,paper_id,auto_reset=True).id
    analysis.process_analysis_job(job_id,session_factory=factory)
    with factory() as db:
        assert db.get(Paper,paper_id).analysis_generation==2
        assert db.get(PaperNote,note_id).body=="My reproducibility question"
    engine.dispose()


@pytest.mark.mysql
def test_mysql_concurrent_note_edits_do_not_overwrite(mysql_database_url):
    from app.api.routes.reader import NoteUpdate, update_note
    engine=create_engine(mysql_database_url)
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    with factory() as db:
        paper=Paper(source="upload",title="Notes",pdf_path="unused.pdf",status="ready")
        db.add(paper);db.flush()
        note=PaperNote(paper_id=paper.id,body="Initial")
        db.add(note);db.commit();paper_id,note_id=paper.id,note.id
    def edit(body):
        with factory() as db:
            try:
                update_note(paper_id,note_id,NoteUpdate(body=body,version=1),db)
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit,["First edit","Second edit"]))==[200,409]
    with factory() as db: assert db.get(PaperNote,note_id).version==2
    engine.dispose()
