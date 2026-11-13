"""Add saved research workspaces without regenerating or removing existing work."""
from alembic import op
import sqlalchemy as sa

revision = "20261113_0006"
down_revision = "20260925_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("research_projects", sa.Column("name", sa.String(255), nullable=True))
    op.add_column("research_projects", sa.Column("selection_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("comparisons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("creation_key", sa.String(64), unique=True, nullable=True),
        sa.Column("name", sa.String(255), nullable=False), sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_json", sa.JSON(), nullable=True), sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_comparisons_status", "comparisons", ["status"])
    op.create_table("comparison_papers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("comparison_id", sa.String(36), sa.ForeignKey("comparisons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paper_id", sa.String(36), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("comparison_id", "paper_id", name="uq_comparison_paper"))
    for field in ("comparison_id", "paper_id"):
        op.create_index(f"ix_comparison_papers_{field}", "comparison_papers", [field])
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("comparison_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_jobs_comparison", "comparisons", ["comparison_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_jobs_comparison_id", ["comparison_id"])
    with op.batch_alter_table("chat_messages") as batch:
        batch.add_column(sa.Column("position", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("request_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("status", sa.String(32), nullable=False, server_default="completed"))
        batch.add_column(sa.Column("error_message", sa.Text(), nullable=True))
    connection = op.get_bind()
    # Legacy timestamps may tie at MySQL's second precision. Keep ties deterministic,
    # with user messages before assistant messages, without rewriting their contents.
    rows = connection.execute(sa.text("SELECT id, session_id FROM chat_messages ORDER BY session_id, created_at, CASE WHEN role='user' THEN 0 ELSE 1 END, id")).mappings()
    positions = {}
    for row in rows:
        position = positions.get(row["session_id"], 0)
        connection.execute(sa.text("UPDATE chat_messages SET position=:position WHERE id=:id"), {"position":position,"id":row["id"]})
        positions[row["session_id"]] = position + 1
    with op.batch_alter_table("chat_messages") as batch:
        batch.create_unique_constraint("uq_chat_message_position", ["session_id", "position"])
        batch.create_unique_constraint("uq_chat_message_request_role", ["session_id", "request_id", "role"])
    op.create_table("paper_reading_states",
        sa.Column("paper_id", sa.String(36), sa.ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("page", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active_session_id", sa.String(36), sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("paper_notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("paper_id", sa.String(36), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True), sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_paper_notes_paper_id", "paper_notes", ["paper_id"])


def downgrade():
    op.drop_table("paper_notes")
    op.drop_table("paper_reading_states")
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_constraint("uq_chat_message_request_role", type_="unique")
        batch.drop_constraint("uq_chat_message_position", type_="unique")
        for name in ("error_message", "status", "request_id", "position"):
            batch.drop_column(name)
    with op.batch_alter_table("jobs") as batch:
        batch.drop_index("ix_jobs_comparison_id")
        batch.drop_constraint("fk_jobs_comparison", type_="foreignkey")
        batch.drop_column("comparison_id")
    op.drop_table("comparison_papers")
    op.drop_table("comparisons")
    op.drop_column("research_projects", "selection_version")
    op.drop_column("research_projects", "name")
