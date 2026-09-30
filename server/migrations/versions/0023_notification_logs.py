"""add notification_logs for scheduled proactive push idempotency (#171)

Revision ID: 0023_notification_logs
Revises: 0022_remove_feishu_webhook
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_notification_logs"
down_revision = "0022_remove_feishu_webhook"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("biz_key", sa.String(length=200), nullable=False),
        sa.Column("notified_on", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("biz_key", "notified_on", name="uq_notification_logs_biz_key_on"),
    )
    op.execute("ALTER TABLE notification_logs ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("notification_logs")
