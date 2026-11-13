from pypdf import PdfWriter
from app.models.paper import Paper, ChatMessage, ChatSession
from app.ai import ChatPayload
from app.services import analysis


def reader_paper(db, tmp_path):
    path = tmp_path / "reader.pdf"
    pdf = PdfWriter()
    for _ in range(3): pdf.add_blank_page(width=100, height=100)
    with path.open("wb") as file: pdf.write(file)
    paper = Paper(source="upload", title="Reader", pdf_path=str(path), status="ready")
    db.add(paper); db.commit()
    return paper


def test_reader_position_sessions_and_chat_request_identity(api_client, db_session, tmp_path, monkeypatch):
    paper = reader_paper(db_session, tmp_path)
    base = f"/api/papers/{paper.id}"
    assert api_client.get(base+"/workspace").json()["page"] == 1
    state = api_client.put(base+"/reading-state", json={"page":3,"version":0})
    assert state.status_code == 200
    assert api_client.put(base+"/reading-state", json={"page":2,"version":0}).status_code == 409
    assert api_client.put(base+"/reading-state", json={"page":9,"version":1}).status_code == 422
    session = api_client.post(base+"/chat-sessions").json()["active_session_id"]
    calls=[]
    class Provider:
        def answer_question(self,*args):
            calls.append(args)
            return ChatPayload(answer="Supported answer",citations=[],generation_mode="ai")
    monkeypatch.setattr(analysis,"retrieve_paper_chunks",lambda *a,**kw: [])
    monkeypatch.setattr(analysis,"get_ai_provider",lambda: Provider())
    payload={"question":"What did it find?","session_id":session,"request_id":"turn-1"}
    assert api_client.post(base+"/chat",json=payload).status_code == 200
    assert api_client.post(base+"/chat",json=payload).status_code == 200
    assert len(calls)==1
    saved=api_client.get(base+"/workspace").json()
    assert saved["page"]==3
    assert [m["role"] for m in saved["messages"]]==["user","assistant"]
    assert [m["content"] for m in saved["messages"]]==["What did it find?","Supported answer"]
    other=Paper(source="upload",title="Other",pdf_path=str(tmp_path/"other.pdf"),status="ready")
    db_session.add(other);db_session.commit()
    assert api_client.get(f"/api/papers/{other.id}/workspace?session_id={session}").status_code==404
    assert api_client.post(f"/api/papers/{other.id}/chat",json=payload).status_code==404


def test_chat_failure_keeps_question_and_retry_reuses_the_turn(api_client, db_session, tmp_path, monkeypatch):
    paper=reader_paper(db_session,tmp_path)
    session=ChatSession(paper_id=paper.id,title="Saved")
    db_session.add(session);db_session.commit()
    monkeypatch.setattr(analysis,"complete_chat_query",lambda *args: (_ for _ in ()).throw(RuntimeError("interrupted")))
    try: analysis.run_chat_query(db_session,paper,session,"Preserve this question",request_id="turn")
    except RuntimeError: pass
    rows=db_session.query(ChatMessage).order_by(ChatMessage.position).all()
    assert rows[0].content=="Preserve this question"
    assert rows[1].status=="failed"
    def complete(db,paper,session,question,history,answer):
        answer.content="Recovered";answer.status="completed";answer.generation_mode="ai";db.commit()
        return analysis.cached_chat_response(session.id,answer)
    monkeypatch.setattr(analysis,"complete_chat_query",complete)
    result=analysis.run_chat_query(db_session,paper,session,"Preserve this question",request_id="turn",retry=True)
    assert result.answer.content=="Recovered"
    assert db_session.query(ChatMessage).count()==2
