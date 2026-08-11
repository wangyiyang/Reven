"""add RSS source and keyword settings

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rss_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("feed_url", name="uq_rss_sources_feed_url"),
    )
    op.create_table(
        "rss_keywords",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("term", sa.String(length=200), nullable=False),
        sa.Column("normalized_term", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('positive', 'negative')", name="ck_rss_keywords_kind"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_term", name="uq_rss_keywords_normalized_term"),
    )


def downgrade() -> None:
    op.drop_table("rss_keywords")
    op.drop_table("rss_sources")
