"""add last_latency_ms to integrations

Revision ID: 0013_integration_last_latency_ms
Revises: 0012_sops
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_integration_last_latency_ms"
down_revision = "0012_sops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("integrations", sa.Column("last_latency_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("integrations", "last_latency_ms")
