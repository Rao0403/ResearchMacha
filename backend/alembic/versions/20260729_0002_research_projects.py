"""add research projects

Revision ID: 20260729_0002
Revises: 20260701_0001
Create Date: 2026-07-29 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260729_0002"
down_revision = "20260701_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_projects",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("generated_queries", sa.JSON(), nullable=False),
        sa.Column("inclusion_criteria", sa.JSON(), nullable=False),
        sa.Column("synthesis_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_research_projects_status", "research_projects", ["status"], unique=False)

    op.create_table(
        "research_candidates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("arxiv_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("pdf_url", sa.String(length=1024), nullable=False),
        sa.Column("entry_url", sa.String(length=1024), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_research_candidates_arxiv_id", "research_candidates", ["arxiv_id"], unique=False)
    op.create_index("ix_research_candidates_project_id", "research_candidates", ["project_id"], unique=False)

    op.create_table(
        "research_project_papers",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paper_id", sa.String(length=36), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_research_project_papers_paper_id", "research_project_papers", ["paper_id"], unique=False)
    op.create_index("ix_research_project_papers_project_id", "research_project_papers", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_research_project_papers_project_id", table_name="research_project_papers")
    op.drop_index("ix_research_project_papers_paper_id", table_name="research_project_papers")
    op.drop_table("research_project_papers")
    op.drop_index("ix_research_candidates_project_id", table_name="research_candidates")
    op.drop_index("ix_research_candidates_arxiv_id", table_name="research_candidates")
    op.drop_table("research_candidates")
    op.drop_index("ix_research_projects_status", table_name="research_projects")
    op.drop_table("research_projects")
