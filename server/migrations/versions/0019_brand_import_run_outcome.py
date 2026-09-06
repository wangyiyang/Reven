"""brand_import_runs: add error message and finished_at columns

Revision ID: 0019_brand_import_run_outcome
Revises: 0018_article_selected_cover
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_brand_import_run_outcome"
down_revision = "0018_article_selected_cover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brand_import_runs", sa.Column("error", sa.Text(), nullable=True))
    op.add_column("brand_import_runs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("brand_import_runs", "finished_at")
    op.drop_column("brand_import_runs", "error")
