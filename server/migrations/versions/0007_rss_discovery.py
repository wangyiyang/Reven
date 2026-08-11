"""add RSS discovery runs and items

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rss_keywords", sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True))
    op.add_column("rss_keywords", sa.Column("embedding_model", sa.String(length=100), nullable=True))
    op.add_column("rss_keywords", sa.Column("embedding_dimension", sa.Integer(), nullable=True))
    op.add_column("rss_keywords", sa.Column("embedding_term_hash", sa.String(length=64), nullable=True))
    op.add_column("rss_keywords", sa.Column("embedding_generated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("rss_keywords", sa.Column("embedding_error", sa.Text(), nullable=True))
    op.create_table(
        "rss_discovery_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("new_count", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("errors", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("notification_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_date", name="uq_rss_discovery_runs_run_date"),
    )
    op.create_table(
        "rss_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("first_seen_run_id", sa.Uuid(), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("guid", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("url_key", sa.String(length=64), nullable=True),
        sa.Column("guid_key", sa.String(length=64), nullable=True),
        sa.Column("title_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("title_zh", sa.Text(), nullable=False),
        sa.Column("summary_zh", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("positive_literal_matches", postgresql.JSONB(), nullable=False),
        sa.Column("negative_literal_matches", postgresql.JSONB(), nullable=False),
        sa.Column("bm25_score", sa.Float(), nullable=False),
        sa.Column("positive_embedding_score", sa.Float(), nullable=False),
        sa.Column("negative_embedding_score", sa.Float(), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
        sa.Column("embedding_status", sa.String(length=24), nullable=False),
        sa.Column("model_status", sa.String(length=24), nullable=False),
        sa.Column("model_score", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("rules_version", sa.String(length=32), nullable=True),
        sa.Column("screening_error", sa.Text(), nullable=True),
        sa.Column("screened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notion_page_id", sa.Uuid(), nullable=True),
        sa.Column("notion_url", sa.Text(), nullable=True),
        sa.Column("push_token", sa.Uuid(), nullable=True),
        sa.Column("push_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("push_error", sa.Text(), nullable=True),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["first_seen_run_id"], ["rss_discovery_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_id"], ["rss_sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notion_page_id", name="uq_rss_items_notion_page_id"),
    )
    op.create_index(
        "uq_rss_items_url_key",
        "rss_items",
        ["url_key"],
        unique=True,
        postgresql_where=sa.text("url_key IS NOT NULL"),
    )
    op.create_index(
        "uq_rss_items_guid_key",
        "rss_items",
        ["guid_key"],
        unique=True,
        postgresql_where=sa.text("guid_key IS NOT NULL"),
    )
    op.create_index("uq_rss_items_title_key", "rss_items", ["title_key"], unique=True)
    op.create_index("ix_rss_items_candidate_scan", "rss_items", ["status", "published_at"])
    op.execute("ALTER TABLE rss_discovery_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE rss_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE rss_sources ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE rss_keywords ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE rss_keywords DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE rss_sources DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_rss_items_candidate_scan", table_name="rss_items")
    op.drop_index("uq_rss_items_title_key", table_name="rss_items")
    op.drop_index("uq_rss_items_guid_key", table_name="rss_items")
    op.drop_index("uq_rss_items_url_key", table_name="rss_items")
    op.drop_table("rss_items")
    op.drop_table("rss_discovery_runs")
    op.drop_column("rss_keywords", "embedding_error")
    op.drop_column("rss_keywords", "embedding_generated_at")
    op.drop_column("rss_keywords", "embedding_term_hash")
    op.drop_column("rss_keywords", "embedding_dimension")
    op.drop_column("rss_keywords", "embedding_model")
    op.drop_column("rss_keywords", "embedding")
