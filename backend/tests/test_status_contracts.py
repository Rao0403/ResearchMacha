from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.models.paper import Highlight, Job, Paper, PaperChunk, PaperSummary, ResearchProject, ResearchProjectPaper
from app.models.states import JobStatus


def test_paper_status_is_lightweight_and_gets_are_read_only(
    api_client: TestClient,
    db_session,
    monkeypatch,
    tmp_path,
) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.7 test")
    opened_at = datetime(2025, 1, 2, 3, 4, 5)
    project = ResearchProject(question="How does retrieval improve factuality?", status="blocked")
    paper = Paper(
        source="upload",
        title="Grounded paper",
        authors=[],
        pdf_path=str(pdf_path),
        status="processing",
        analysis_generation=1,
        analysis_mode="ai",
        last_opened_at=opened_at,
    )
    db_session.add_all([project, paper])
    db_session.flush()
    db_session.add_all(
        [
            ResearchProjectPaper(project_id=project.id, paper_id=paper.id),
            PaperChunk(
                paper_id=paper.id,
                analysis_generation=1,
                chunk_index=0,
                page_start=1,
                page_end=1,
                text="Private chunk text must not appear in status polling.",
            ),
            PaperSummary(
                paper_id=paper.id,
                problem_or_hypothesis="Problem",
                approach="Approach",
                experiments="Experiments",
                results="Results",
                conclusion="Conclusion",
                limitations_or_notes="Limitations",
                section_citations={},
                generation_mode="ai",
            ),
            Highlight(paper_id=paper.id, position=0, label="Finding", explanation="Evidence", citations=[]),
        ]
    )
    failed_job = Job(
        paper_id=paper.id,
        project_id=project.id,
        job_type="analysis",
        status=JobStatus.FAILED,
        idempotency_key=f"analysis:{paper.id}:1:failed",
        requested_generation=1,
        error_message="Previous analysis failed",
    )
    active_job = Job(
        paper_id=paper.id,
        project_id=project.id,
        job_type="analysis",
        status=JobStatus.QUEUED,
        idempotency_key=f"analysis:{paper.id}:2",
        requested_generation=2,
    )
    db_session.add_all([failed_job, active_job])
    db_session.commit()
    paper_id = paper.id
    project_id = project.id

    def fail_commit() -> None:
        raise AssertionError("GET endpoint attempted a database commit")

    monkeypatch.setattr(db_session, "commit", fail_commit)

    status_response = api_client.get(f"/api/papers/{paper_id}/status")
    detail_response = api_client.get(f"/api/papers/{paper_id}")
    summary_response = api_client.get(f"/api/papers/{paper_id}/summary")
    file_response = api_client.get(f"/api/papers/{paper_id}/file")
    project_response = api_client.get(f"/api/research-workflows/{project_id}")
    project_status_response = api_client.get(f"/api/research-workflows/{project_id}/status")

    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert set(status_payload) == {
        "id",
        "status",
        "analysis_generation",
        "analysis_mode",
        "analysis_warning",
        "active_job",
    }
    assert status_payload["active_job"]["id"] == active_job.id
    assert "chunks" not in status_payload
    assert "summary" not in status_payload
    assert "highlights" not in status_payload
    assert "Private chunk text" not in status_response.text

    assert detail_response.status_code == 200
    assert detail_response.json()["chunks"][0]["text"].startswith("Private chunk text")
    assert summary_response.status_code == 200
    assert file_response.status_code == 200
    assert file_response.content == b"%PDF-1.7 test"

    assert project_response.status_code == 200
    project_payload = project_response.json()
    assert {job["id"] for job in project_payload["recent_jobs"]} == {failed_job.id, active_job.id}
    assert project_payload["blocking_items"][0]["job_id"] == failed_job.id
    assert project_status_response.status_code == 200
    assert set(project_status_response.json()) == {"id", "status", "synthesis_generation", "updated_at"}
    assert project_status_response.json()["id"] == project_id
    assert "candidates" not in project_status_response.text
    assert "papers" not in project_status_response.text
    assert "recent_jobs" not in project_status_response.text
    db_session.expire_all()
    assert db_session.get(Paper, paper_id).last_opened_at == opened_at


def test_status_warning_generation_and_blocker_schemas_are_public(api_client: TestClient) -> None:
    response = api_client.get("/openapi.json")

    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]
    assert {"PaperStatusRead", "ResearchProjectStatusRead", "BlockingItemRead", "WarningRead", "GenerationMode"} <= set(schemas)
