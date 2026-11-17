"""删除 rss_items 表：RSS 候选唯一权威存储切换为飞书多维表格（#226 Commit 5）

历史候选数据不归档、不迁移，随表一并删除（用户已确认不可逆）。downgrade
不重建空表：数据已不可恢复，代码级回滚 = revert PR + 使用升级前的数据库备份
（对齐 0021「不恢复历史资料」先例）。

Revision ID: 0029_drop_rss_items
Revises: 0028_feishu_resource_bindings
"""

from alembic import op

revision = "0029_drop_rss_items"
down_revision = "0028_feishu_resource_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("rss_items")


def downgrade() -> None:
    raise RuntimeError("0029 已删除 rss_items 表及全部历史候选数据，无法降级；恢复旧版本须使用升级前的数据库备份")
