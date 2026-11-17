"""feishu_resource_bindings：飞书资源绑定表（#226 Commit 1）

通用资源绑定：resource_type（当前仅 bitable）+ purpose（当前仅 rss_candidates）
+ config JSONB（bitable: {"app_token", "table_id"}）。部分唯一索引
uq_feishu_resource_bindings_enabled_purpose（WHERE enabled = true）保证同一用途
同时只有一个启用绑定；integration_id 级联删除跟随 integrations 行。

Revision ID: 0028_feishu_resource_bindings
Revises: 0027_unify_follow_up_channel
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_feishu_resource_bindings"
down_revision = "0027_unify_follow_up_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feishu_resource_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["integration_id"], ["integrations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_feishu_resource_bindings_enabled_purpose",
        "feishu_resource_bindings",
        ["purpose"],
        unique=True,
        postgresql_where=sa.text("enabled = true"),
    )
    op.execute("ALTER TABLE feishu_resource_bindings ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("feishu_resource_bindings")
