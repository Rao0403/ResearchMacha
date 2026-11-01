"""add durable jobs and generated-data provenance

Revision ID: 20260925_0005
Revises: 20260822_0004
Create Date: 2026-09-25 00:00:00
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260925_0005"
down_revision = "20260822_0004"
branch_labels = None
depends_on = None


def _as_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return fallback
    return value


def _embedding_metadata(value: Any) -> tuple[str | None, int | None]:
    vector = _as_json(value, None)
    if not isinstance(vector, list) or not vector:
        return None, None
    dimension = len(vector)
    return f"legacy-unknown:{dimension}", dimension


def _normalize_arxiv_id(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"^https?://arxiv\.org/(?:abs|pdf)/", "", normalized)
    normalized = normalized.removesuffix(".pdf")
    return re.sub(r"v\d+$", "", normalized)


def _replace_candidate_id(value: Any, old_id: str, new_id: str) -> Any:
    if isinstance(value, dict):
        return {key: _replace_candidate_id(item, old_id, new_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_candidate_id(item, old_id, new_id) for item in value]
    return new_id if value == old_id else value


def _backfill_source_keys(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text("SELECT id, arxiv_id, created_at FROM papers WHERE arxiv_id IS NOT NULL ORDER BY created_at, id")
    ).mappings()
    seen: set[str] = set()
    for row in rows:
        normalized = _normalize_arxiv_id(row["arxiv_id"])
        if not normalized:
            continue
        source_key = f"arxiv:{normalized}" if normalized not in seen else f"legacy-arxiv:{row['id']}"
        seen.add(normalized)
        connection.execute(
            sa.text("UPDATE papers SET source_key = :source_key WHERE id = :id"),
            {"source_key": source_key, "id": row["id"]},
        )


def _backfill_chunks(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text(
            "SELECT id, paper_id, embedding FROM paper_chunks "
            "ORDER BY paper_id, chunk_index, created_at, id"
        )
    ).mappings()
    positions: dict[str, int] = defaultdict(int)
    papers_with_chunks: set[str] = set()
    for row in rows:
        fingerprint, dimension = _embedding_metadata(row["embedding"])
        position = positions[row["paper_id"]]
        positions[row["paper_id"]] += 1
        papers_with_chunks.add(row["paper_id"])
        connection.execute(
            sa.text(
                "UPDATE paper_chunks SET chunk_index = :position, analysis_generation = 1, "
                "embedding_fingerprint = :fingerprint, embedding_dim = :dimension WHERE id = :id"
            ),
            {"position": position, "fingerprint": fingerprint, "dimension": dimension, "id": row["id"]},
        )
    for paper_id in papers_with_chunks:
        connection.execute(
            sa.text("UPDATE papers SET analysis_generation = 1 WHERE id = :id"),
            {"id": paper_id},
        )


def _backfill_memories(connection: sa.Connection) -> None:
    rows = connection.execute(sa.text("SELECT id, embedding FROM research_memories")).mappings()
    for row in rows:
        fingerprint, dimension = _embedding_metadata(row["embedding"])
        connection.execute(
            sa.text(
                "UPDATE research_memories SET embedding_fingerprint = :fingerprint, "
                "embedding_dim = :dimension WHERE id = :id"
            ),
            {"fingerprint": fingerprint, "dimension": dimension, "id": row["id"]},
        )


def _deduplicate_candidates(connection: sa.Connection) -> None:
    rows = list(
        connection.execute(
            sa.text(
                "SELECT id, project_id, arxiv_id, selected, score, created_at FROM research_candidates "
                "ORDER BY project_id, created_at, id"
            )
        ).mappings()
    )
    rows.sort(
        key=lambda row: (
            row["project_id"],
            _normalize_arxiv_id(row["arxiv_id"]),
            -int(bool(row["selected"])),
            -int(row["score"]),
            row["created_at"],
            row["id"],
        )
    )
    survivors: dict[tuple[str, str], str] = {}
    for row in rows:
        normalized_id = _normalize_arxiv_id(row["arxiv_id"])
        key = (row["project_id"], normalized_id)
        survivor_id = survivors.setdefault(key, row["id"])
        if survivor_id == row["id"]:
            connection.execute(
                sa.text("UPDATE research_candidates SET arxiv_id = :arxiv_id WHERE id = :id"),
                {"arxiv_id": normalized_id, "id": row["id"]},
            )
            continue
        memories = connection.execute(
            sa.text("SELECT id, metadata_json FROM research_memories WHERE project_id = :project_id"),
            {"project_id": row["project_id"]},
        ).mappings()
        for memory in memories:
            metadata = _as_json(memory["metadata_json"], {})
            updated = _replace_candidate_id(metadata, row["id"], survivor_id)
            if updated != metadata:
                connection.execute(
                    sa.text("UPDATE research_memories SET metadata_json = :metadata WHERE id = :id"),
                    {"metadata": json.dumps(updated), "id": memory["id"]},
                )
        connection.execute(sa.text("DELETE FROM research_candidates WHERE id = :id"), {"id": row["id"]})


def _deduplicate_project_papers(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text(
            "SELECT id, project_id, paper_id FROM research_project_papers "
            "ORDER BY project_id, paper_id, created_at, id"
        )
    ).mappings()
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["project_id"], row["paper_id"])
        if key in seen:
            connection.execute(sa.text("DELETE FROM research_project_papers WHERE id = :id"), {"id": row["id"]})
        else:
            seen.add(key)


def _renumber_agent_steps(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text("SELECT id, run_id FROM agent_steps ORDER BY run_id, started_at, id")
    ).mappings()
    positions: dict[str, int] = defaultdict(int)
    for row in rows:
        position = positions[row["run_id"]]
        positions[row["run_id"]] += 1
        connection.execute(
            sa.text("UPDATE agent_steps SET position = :position WHERE id = :id"),
            {"position": position, "id": row["id"]},
        )


def _mark_legacy_briefs(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text("SELECT id, synthesis_json FROM research_projects WHERE synthesis_json IS NOT NULL")
    ).mappings()
    for row in rows:
        brief = _as_json(row["synthesis_json"], {})
        if isinstance(brief, dict) and "generation_mode" not in brief:
            brief["generation_mode"] = "unknown_legacy"
            brief.setdefault("warnings", [])
            connection.execute(
                sa.text("UPDATE research_projects SET synthesis_json = :brief WHERE id = :id"),
                {"brief": json.dumps(brief), "id": row["id"]},
            )


def upgrade() -> None:
    op.add_column("papers", sa.Column("source_key", sa.String(length=191), nullable=True))
    op.add_column("papers", sa.Column("analysis_generation", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("papers", sa.Column("analysis_mode", sa.String(length=32), nullable=False, server_default="unknown_legacy"))
    op.add_column("papers", sa.Column("analysis_warning", sa.Text(), nullable=True))

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("paper_id", existing_type=sa.String(length=36), nullable=True)
    op.add_column("jobs", sa.Column("project_id", sa.String(length=36), nullable=True))
    op.add_column("jobs", sa.Column("candidate_id", sa.String(length=36), nullable=True))
    op.add_column("jobs", sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    op.add_column("jobs", sa.Column("requested_generation", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("worker_id", sa.String(length=255), nullable=True))
    op.add_column("jobs", sa.Column("claimed_at", sa.DateTime(), nullable=True))
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
    op.add_column("jobs", sa.Column("warning_message", sa.Text(), nullable=True))

    op.add_column("paper_chunks", sa.Column("analysis_generation", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("paper_chunks", sa.Column("embedding_fingerprint", sa.String(length=255), nullable=True))
    op.add_column("paper_chunks", sa.Column("embedding_dim", sa.Integer(), nullable=True))
    op.add_column("research_memories", sa.Column("dedupe_key", sa.String(length=255), nullable=True))
    op.add_column("research_memories", sa.Column("embedding_fingerprint", sa.String(length=255), nullable=True))
    op.add_column("research_memories", sa.Column("embedding_dim", sa.Integer(), nullable=True))
    op.add_column("paper_summaries", sa.Column("generation_mode", sa.String(length=32), nullable=False, server_default="unknown_legacy"))
    op.add_column("paper_summaries", sa.Column("warning", sa.Text(), nullable=True))
    op.add_column("chat_messages", sa.Column("generation_mode", sa.String(length=32), nullable=True))
    op.add_column("chat_messages", sa.Column("warning", sa.Text(), nullable=True))
    op.add_column("research_projects", sa.Column("synthesis_generation", sa.Integer(), nullable=False, server_default="0"))

    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        connection.execute(sa.text("UPDATE jobs SET idempotency_key = 'legacy:' || id"))
    else:
        connection.execute(sa.text("UPDATE jobs SET idempotency_key = CONCAT('legacy:', id)"))
    _backfill_source_keys(connection)
    _backfill_chunks(connection)
    _backfill_memories(connection)
    _deduplicate_candidates(connection)
    _deduplicate_project_papers(connection)
    _renumber_agent_steps(connection)
    _mark_legacy_briefs(connection)
    connection.execute(sa.text("UPDATE chat_messages SET generation_mode = 'unknown_legacy' WHERE role = 'assistant'"))

    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("idempotency_key", existing_type=sa.String(length=255), nullable=False)
        batch_op.create_foreign_key(
            "fk_jobs_project_id", "research_projects", ["project_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_foreign_key(
            "fk_jobs_candidate_id", "research_candidates", ["candidate_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_unique_constraint("uq_jobs_idempotency_key", ["idempotency_key"])
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"], unique=False)
    op.create_index("ix_jobs_candidate_id", "jobs", ["candidate_id"], unique=False)
    op.create_index("ix_jobs_lease_expires_at", "jobs", ["lease_expires_at"], unique=False)
    with op.batch_alter_table("papers") as batch_op:
        batch_op.create_unique_constraint("uq_papers_source_key", ["source_key"])
    with op.batch_alter_table("paper_chunks") as batch_op:
        batch_op.create_unique_constraint(
            "uq_paper_chunks_generation_index", ["paper_id", "analysis_generation", "chunk_index"]
        )
    with op.batch_alter_table("research_memories") as batch_op:
        batch_op.create_unique_constraint("uq_research_memories_dedupe_key", ["dedupe_key"])
    with op.batch_alter_table("research_candidates") as batch_op:
        batch_op.create_unique_constraint("uq_research_candidates_project_arxiv", ["project_id", "arxiv_id"])
    with op.batch_alter_table("research_project_papers") as batch_op:
        batch_op.create_unique_constraint("uq_research_project_papers_project_paper", ["project_id", "paper_id"])
    with op.batch_alter_table("agent_steps") as batch_op:
        batch_op.create_unique_constraint("uq_agent_steps_run_position", ["run_id", "position"])


def downgrade() -> None:
    op.drop_constraint("uq_agent_steps_run_position", "agent_steps", type_="unique")
    op.drop_constraint("uq_research_project_papers_project_paper", "research_project_papers", type_="unique")
    op.drop_constraint("uq_research_candidates_project_arxiv", "research_candidates", type_="unique")
    op.drop_constraint("uq_research_memories_dedupe_key", "research_memories", type_="unique")
    op.drop_constraint("uq_paper_chunks_generation_index", "paper_chunks", type_="unique")
    op.drop_constraint("uq_jobs_idempotency_key", "jobs", type_="unique")
    op.drop_constraint("uq_papers_source_key", "papers", type_="unique")
    op.drop_index("ix_jobs_lease_expires_at", table_name="jobs")
    op.drop_index("ix_jobs_candidate_id", table_name="jobs")
    op.drop_index("ix_jobs_project_id", table_name="jobs")
    op.drop_constraint("fk_jobs_candidate_id", "jobs", type_="foreignkey")
    op.drop_constraint("fk_jobs_project_id", "jobs", type_="foreignkey")
    op.drop_column("research_projects", "synthesis_generation")
    op.drop_column("chat_messages", "warning")
    op.drop_column("chat_messages", "generation_mode")
    op.drop_column("paper_summaries", "warning")
    op.drop_column("paper_summaries", "generation_mode")
    op.drop_column("research_memories", "embedding_dim")
    op.drop_column("research_memories", "embedding_fingerprint")
    op.drop_column("research_memories", "dedupe_key")
    op.drop_column("paper_chunks", "embedding_dim")
    op.drop_column("paper_chunks", "embedding_fingerprint")
    op.drop_column("paper_chunks", "analysis_generation")
    op.drop_column("jobs", "warning_message")
    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "claimed_at")
    op.drop_column("jobs", "worker_id")
    op.drop_column("jobs", "attempt_count")
    op.drop_column("jobs", "requested_generation")
    op.drop_column("jobs", "idempotency_key")
    op.drop_column("jobs", "candidate_id")
    op.drop_column("jobs", "project_id")
    op.alter_column("jobs", "paper_id", existing_type=sa.String(length=36), nullable=False)
    op.drop_column("papers", "analysis_warning")
    op.drop_column("papers", "analysis_mode")
    op.drop_column("papers", "analysis_generation")
    op.drop_column("papers", "source_key")
