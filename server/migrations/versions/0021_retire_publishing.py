"""移除稿件发布与 Notion 集成，RSS 采纳保存在本地。

Revision ID: 0021_retire_publishing
Revises: 0020_rss_item_review_pushed_at
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_retire_publishing"
down_revision = "0020_rss_item_review_pushed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("fk_articles_current_snapshot_id", "articles", type_="foreignkey")
    for table in (
        "notification_outbox",
        "publication_jobs",
        "snapshot_assets",
        "content_snapshots",
        "content_sync_runs",
        "articles",
        "brand_import_runs",
    ):
        op.drop_table(table)
    op.execute("DELETE FROM rss_items WHERE status IN ('pushing', 'pushed')")
    for column in ("notion_page_id", "notion_url", "push_token", "push_started_at", "push_error", "pushed_at"):
        op.drop_column("rss_items", column)
    op.add_column("rss_items", sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_column("projects", "notion_url")
    op.execute("DELETE FROM integrations WHERE provider IN ('notion', 'github', 'wechat')")
    op.execute("DELETE FROM system_state WHERE key IN ('notion_sync', 'scheduler')")


def downgrade() -> None:
    raise RuntimeError("0021 已删除稿件发布数据与集成凭据，无法降级；恢复旧版本须使用升级前的数据库备份")
