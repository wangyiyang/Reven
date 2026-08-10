"""add atomic content synchronization and immutable snapshots

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

ACTIVE_SYNC_WHERE = "status IN ('等待中', '同步中')"


def upgrade() -> None:
    _create_sync_runs()
    _create_snapshots()
    _create_snapshot_assets()
    _add_snapshot_references()


def downgrade() -> None:
    op.drop_constraint("fk_publication_jobs_snapshot_id", "publication_jobs", type_="foreignkey")
    op.drop_column("publication_jobs", "snapshot_id")
    op.drop_constraint("fk_articles_current_snapshot_id", "articles", type_="foreignkey")
    op.drop_index("ix_articles_content_sync_status", table_name="articles")
    op.drop_column("articles", "current_snapshot_id")
    op.drop_column("articles", "content_sync_error")
    op.drop_column("articles", "content_sync_status")
    op.drop_table("snapshot_assets")
    op.drop_table("content_snapshots")
    op.drop_index("ix_content_sync_runs_claim", table_name="content_sync_runs")
    op.drop_index("uq_one_active_content_sync_per_article", table_name="content_sync_runs")
    op.drop_index("ix_content_sync_runs_article_id", table_name="content_sync_runs")
    op.drop_table("content_sync_runs")


def _create_sync_runs() -> None:
    op.create_table(
        "content_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("source_last_edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress_current", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("current_media", sa.Text(), nullable=True),
        sa.Column("error_stage", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_media", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_content_sync_runs_article_id", "content_sync_runs", ["article_id"])
    op.create_index(
        "uq_one_active_content_sync_per_article",
        "content_sync_runs",
        ["article_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_SYNC_WHERE),
    )
    op.create_index(
        "ix_content_sync_runs_claim",
        "content_sync_runs",
        ["status", "next_attempt_at", "created_at"],
    )


def _create_snapshots() -> None:
    op.create_table(
        "content_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_last_edited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_markdown", sa.Text(), nullable=False),
        sa.Column("portable_markdown", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sync_run_id"], ["content_sync_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sync_run_id", name="uq_content_snapshot_sync_run"),
        sa.UniqueConstraint(
            "article_id",
            "source_last_edited_at",
            "content_hash",
            name="uq_content_snapshot_article_version_hash",
        ),
    )
    op.create_index("ix_content_snapshots_article_id", "content_snapshots", ["article_id"])
    op.create_index("ix_content_snapshots_content_hash", "content_snapshots", ["content_hash"])


def _create_snapshot_assets() -> None:
    op.create_table(
        "snapshot_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("embedded", sa.Boolean(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("public_url", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("alt_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["content_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "ordinal", name="uq_snapshot_asset_ordinal"),
    )
    op.create_index("ix_snapshot_assets_snapshot_id", "snapshot_assets", ["snapshot_id"])
    op.create_index("ix_snapshot_assets_sha256", "snapshot_assets", ["sha256"])


def _add_snapshot_references() -> None:
    op.add_column(
        "articles",
        sa.Column("content_sync_status", sa.String(length=32), server_default="未同步", nullable=False),
    )
    op.add_column("articles", sa.Column("content_sync_error", sa.Text(), nullable=True))
    op.add_column("articles", sa.Column("current_snapshot_id", sa.Uuid(), nullable=True))
    op.create_index("ix_articles_content_sync_status", "articles", ["content_sync_status"])
    op.create_foreign_key(
        "fk_articles_current_snapshot_id",
        "articles",
        "content_snapshots",
        ["current_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("publication_jobs", sa.Column("snapshot_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_publication_jobs_snapshot_id",
        "publication_jobs",
        "content_snapshots",
        ["snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
