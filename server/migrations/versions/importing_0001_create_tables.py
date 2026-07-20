"""importing: create source_file, import_batch, raw_row"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "importing_0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # importing_source_file
    op.create_table(
        "importing_source_file",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=False, index=True, unique=True),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "importing",
                "completed",
                "failed",
                name="importing_source_file_status",
            ),
            nullable=False,
            server_default="pending",
        ),
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
    )

    # importing_import_batch
    op.create_table(
        "importing_import_batch",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "completed",
                "failed",
                name="importing_batch_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("total_rows", sa.Numeric(12, 0), nullable=True),
        sa.Column("passed_rows", sa.Numeric(12, 0), nullable=True),
        sa.Column("skipped_rows", sa.Numeric(12, 0), nullable=True),
        sa.Column("error_rows", sa.Numeric(12, 0), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
            ["source_file_id"],
            ["importing_source_file.id"],
            ondelete="CASCADE",
        ),
    )

    # importing_raw_row
    op.create_table(
        "importing_raw_row",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_number", sa.Numeric(12, 0), nullable=False),
        sa.Column("cell_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("coordinates", postgresql.JSONB(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "raw",
                "passed",
                "skipped",
                "error",
                name="importing_row_status",
            ),
            nullable=False,
            server_default="raw",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
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
            ["import_batch_id"],
            ["importing_import_batch.id"],
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("importing_raw_row")
    op.drop_table("importing_import_batch")
    op.drop_table("importing_source_file")
    op.execute("DROP TYPE IF EXISTS importing_source_file_status")
    op.execute("DROP TYPE IF EXISTS importing_batch_status")
    op.execute("DROP TYPE IF EXISTS importing_row_status")
