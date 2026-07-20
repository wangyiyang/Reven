"""importing: create job table for SKIP LOCKED queue"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "importing_0002"
down_revision: str = "importing_0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "importing_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(64), nullable=False, index=True),
        sa.Column(
            "status",
            sa.Enum(
                "queued", "running", "completed", "failed", name="importing_job_status"
            ),
            nullable=False,
            server_default="queued",
            index=True,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            onupdate=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["importing_import_batch.id"],
            ondelete="SET NULL",
        ),
    )


def downgrade() -> None:
    op.drop_table("importing_job")
    op.execute("DROP TYPE IF EXISTS importing_job_status")
