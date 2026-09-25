from __future__ import annotations

import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings
from app.models.paper import AgentStep, Job, Paper, PaperChunk, ResearchCandidate, ResearchMemory, ResearchProjectPaper
from app.models.states import GenerationMode, JobStatus, PaperStatus, ProjectStatus


API_ROOT = Path(__file__).resolve().parents[1]


def upgrade_database(monkeypatch, database_path: Path, revision: str = "head") -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    command.upgrade(config, revision)
    get_settings.cache_clear()


def test_fresh_migration_contains_reliability_schema(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "fresh.db"
    upgrade_database(monkeypatch, database_path)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)

    assert {"source_key", "analysis_generation", "analysis_mode", "analysis_warning"} <= {
        column["name"] for column in inspector.get_columns("papers")
    }
    assert {
        "project_id",
        "candidate_id",
        "idempotency_key",
        "requested_generation",
        "attempt_count",
        "worker_id",
        "claimed_at",
        "lease_expires_at",
        "warning_message",
    } <= {column["name"] for column in inspector.get_columns("jobs")}
    assert any(
        constraint["column_names"] == ["project_id", "paper_id"]
        for constraint in inspector.get_unique_constraints("research_project_papers")
    )
    engine.dispose()


def test_legacy_migration_backfills_and_deduplicates(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "legacy.db"
    upgrade_database(monkeypatch, database_path, "20260822_0004")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    timestamp = "2026-01-01 00:00:00"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO papers "
                "(id, source, title, authors, arxiv_id, pdf_path, status, created_at, updated_at) VALUES "
                "('paper-1', 'arxiv', 'Canonical', :authors, '1234.5678v2', 'one.pdf', 'ready', :ts, :ts), "
                "('paper-2', 'arxiv', 'Duplicate', :authors, '1234.5678v3', 'two.pdf', 'ready', :ts, :ts)"
            ),
            {"authors": json.dumps(["Author"]), "ts": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO jobs (id, paper_id, job_type, status, created_at, updated_at) "
                "VALUES ('job-1', 'paper-1', 'analysis', 'completed', :ts, :ts)"
            ),
            {"ts": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO paper_chunks "
                "(id, paper_id, chunk_index, page_start, page_end, text, embedding, created_at) VALUES "
                "('chunk-b', 'paper-1', 9, 2, 2, 'Second', :vector, :ts), "
                "('chunk-a', 'paper-1', 4, 1, 1, 'First', :vector, :ts)"
            ),
            {"vector": json.dumps([0.1, 0.2]), "ts": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO research_projects "
                "(id, question, status, generated_queries, inclusion_criteria, synthesis_json, created_at, updated_at) "
                "VALUES ('project-1', 'Question?', 'done', :empty, :empty, :brief, :ts, :ts)"
            ),
            {"empty": json.dumps([]), "brief": json.dumps({"executive_summary": "Legacy"}), "ts": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO research_candidates "
                "(id, project_id, arxiv_id, title, authors, abstract, pdf_url, entry_url, score, rationale, selected, created_at) VALUES "
                "('candidate-low', 'project-1', '1234.5678v1', 'Low', :authors, '', '', '', 1, '', 0, :ts), "
                "('candidate-selected', 'project-1', '1234.5678v2', 'Selected', :authors, '', '', '', 2, '', 1, :ts)"
            ),
            {"authors": json.dumps([]), "ts": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO research_project_papers (id, project_id, paper_id, role, created_at) VALUES "
                "('link-1', 'project-1', 'paper-1', 'evidence', :ts), "
                "('link-2', 'project-1', 'paper-1', 'evidence', :ts)"
            ),
            {"ts": timestamp},
        )
        connection.execute(
            text(
                "INSERT INTO research_memories "
                "(id, scope, memory_type, text, importance, metadata_json, embedding, project_id, source, status, created_at, updated_at) "
                "VALUES ('memory-1', 'project', 'approval', 'Approved', 1, :metadata, :vector, 'project-1', 'system', 'active', :ts, :ts)"
            ),
            {
                "metadata": json.dumps({"candidate_id": "candidate-low"}),
                "vector": json.dumps([0.2, 0.4, 0.6]),
                "ts": timestamp,
            },
        )

    engine.dispose()
    upgrade_database(monkeypatch, database_path)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        papers = connection.execute(text("SELECT id, source_key, analysis_generation FROM papers ORDER BY id")).mappings().all()
        assert papers[0]["source_key"] == "arxiv:1234.5678"
        assert papers[1]["source_key"] == "legacy-arxiv:paper-2"
        assert papers[0]["analysis_generation"] == 1
        assert connection.scalar(text("SELECT idempotency_key FROM jobs WHERE id = 'job-1'")) == "legacy:job-1"
        chunks = connection.execute(
            text("SELECT chunk_index, analysis_generation, embedding_fingerprint FROM paper_chunks ORDER BY chunk_index")
        ).mappings().all()
        assert [chunk["chunk_index"] for chunk in chunks] == [0, 1]
        assert all(chunk["analysis_generation"] == 1 for chunk in chunks)
        assert all(chunk["embedding_fingerprint"] == "legacy-unknown:2" for chunk in chunks)
        assert connection.scalar(text("SELECT COUNT(*) FROM research_candidates")) == 1
        assert connection.scalar(text("SELECT id FROM research_candidates")) == "candidate-selected"
        assert connection.scalar(text("SELECT arxiv_id FROM research_candidates")) == "1234.5678"
        assert connection.scalar(text("SELECT COUNT(*) FROM research_project_papers")) == 1
        metadata = json.loads(connection.scalar(text("SELECT metadata_json FROM research_memories")))
        assert metadata["candidate_id"] == "candidate-selected"
        assert connection.scalar(text("SELECT embedding_fingerprint FROM research_memories")) == "legacy-unknown:3"
        brief = json.loads(connection.scalar(text("SELECT synthesis_json FROM research_projects")))
        assert brief["generation_mode"] == "unknown_legacy"
    engine.dispose()


def test_models_expose_typed_states_and_uniqueness() -> None:
    assert PaperStatus.DEGRADED == "degraded"
    assert ProjectStatus.SYNTHESIS_QUEUED == "synthesis_queued"
    assert JobStatus.COMPLETED_WITH_WARNINGS == "completed_with_warnings"
    assert GenerationMode.UNKNOWN_LEGACY == "unknown_legacy"
    assert Job.__table__.c.paper_id.nullable
    assert Paper.__table__.c.source_key.unique
    assert ResearchMemory.__table__.c.dedupe_key.unique
    assert {"paper_id", "analysis_generation", "chunk_index"} == set(
        next(constraint for constraint in PaperChunk.__table__.constraints if constraint.name == "uq_paper_chunks_generation_index").columns.keys()
    )
    assert any(constraint.name == "uq_research_candidates_project_arxiv" for constraint in ResearchCandidate.__table__.constraints)
    assert any(constraint.name == "uq_research_project_papers_project_paper" for constraint in ResearchProjectPaper.__table__.constraints)
    assert any(constraint.name == "uq_agent_steps_run_position" for constraint in AgentStep.__table__.constraints)
