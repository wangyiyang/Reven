"""Remove retired Feishu webhook credentials; deletion is irreversible.

Revision ID: 0022_remove_feishu_webhook
Revises: 0021_retire_publishing
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_remove_feishu_webhook"
down_revision = "0021_retire_publishing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM integrations WHERE provider = 'feishu'"))


def downgrade() -> None:
    # Deleted credentials cannot be recovered; do not fabricate a configuration.
    pass
