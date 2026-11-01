"""add research memories

Revision ID: 20260822_0004
Revises: 20260822_0003
Create Date: 2026-08-22 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260822_0004"
down_revision = "20260822_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_memories",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("memory_type", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("importance", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("paper_id", sa.String(length=36), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_research_memories_memory_type", "research_memories", ["memory_type"], unique=False)
    op.create_index("ix_research_memories_paper_id", "research_memories", ["paper_id"], unique=False)
    op.create_index("ix_research_memories_project_id", "research_memories", ["project_id"], unique=False)
    op.create_index("ix_research_memories_scope", "research_memories", ["scope"], unique=False)
    op.create_index("ix_research_memories_status", "research_memories", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_research_memories_status", table_name="research_memories")
    op.drop_index("ix_research_memories_scope", table_name="research_memories")
    op.drop_index("ix_research_memories_project_id", table_name="research_memories")
    op.drop_index("ix_research_memories_paper_id", table_name="research_memories")
    op.drop_index("ix_research_memories_memory_type", table_name="research_memories")
    op.drop_table("research_memories")
