"""rss 批韧性：断点续跑 checkpoint + 死源治理字段（#178）

Revision ID: 0024_rss_resilience
Revises: 0023_notification_logs
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0024_rss_resilience"
down_revision = "0023_notification_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rss_discovery_runs",
        sa.Column("processed_source_ids", JSONB, nullable=False, server_default="[]"),
    )
    op.add_column(
        "rss_sources",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("rss_sources", sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("rss_sources", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("rss_sources", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("rss_sources", sa.Column("disabled_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("rss_sources", "disabled_reason")
    op.drop_column("rss_sources", "disabled_at")
    op.drop_column("rss_sources", "last_error")
    op.drop_column("rss_sources", "last_fetched_at")
    op.drop_column("rss_sources", "consecutive_failures")
    op.drop_column("rss_discovery_runs", "processed_source_ids")
