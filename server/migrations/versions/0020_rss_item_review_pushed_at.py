"""rss_items: add review_pushed_at column for feishu review card push tracking

Revision ID: 0020_rss_item_review_pushed_at
Revises: 0019_brand_import_run_outcome
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_rss_item_review_pushed_at"
down_revision = "0019_brand_import_run_outcome"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rss_items", sa.Column("review_pushed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("rss_items", "review_pushed_at")
