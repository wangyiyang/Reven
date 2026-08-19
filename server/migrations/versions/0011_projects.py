"""add projects table

Revision ID: 0011_projects
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_projects"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("department", sa.String(length=64), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("notion_url", sa.String(length=500), nullable=True),
        sa.Column("github_repo", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("ALTER TABLE projects ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("projects")
