from app.models.paper import ResearchProject, ResearchCandidate, Job


def test_saved_projects_restore_and_selection_does_not_enqueue(api_client, db_session):
    project = ResearchProject(question="A saved research question", status="awaiting_approval", synthesis_json={"executive_summary":"Keep"})
    db_session.add(project)
    db_session.flush()
    candidate = ResearchCandidate(project_id=project.id, arxiv_id="2601.00001", title="Paper", authors=[], abstract="", pdf_url="",entry_url="",score=1,rationale="",selected=True)
    db_session.add(candidate)
    db_session.commit()
    assert api_client.get("/api/research-workflows").json()[0]["id"] == project.id
    assert api_client.get(f"/api/research-workflows/{project.id}").json()["synthesis_json"]["executive_summary"] == "Keep"
    changed = api_client.put(f"/api/research-workflows/{project.id}/selection", json={"candidate_ids":[],"version":0})
    assert changed.status_code == 200
    assert changed.json()["selection_version"] == 1
    assert changed.json()["candidates"][0]["selected"] is False
    assert api_client.put(f"/api/research-workflows/{project.id}/selection", json={"candidate_ids":[],"version":0}).status_code == 409
    assert api_client.put(f"/api/research-workflows/{project.id}/selection", json={"candidate_ids":["foreign"],"version":1}).status_code == 400
    renamed = api_client.patch(f"/api/research-workflows/{project.id}", json={"name":"My project"})
    assert renamed.json()["name"] == "My project"
    assert renamed.json()["question"] == project.question
    assert db_session.query(Job).count() == 0
