"""add per-article selected cover asset (brand asset picker)

Revision ID: 0018_article_selected_cover
Revises: 0017_brand_foundation
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018_article_selected_cover"
down_revision = "0017_brand_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "articles",
        sa.Column("selected_cover_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_articles_selected_cover_asset_id",
        "articles",
        "brand_assets",
        ["selected_cover_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_articles_selected_cover_asset_id", "articles", type_="foreignkey")
    op.drop_column("articles", "selected_cover_asset_id")
