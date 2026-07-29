"""initial

Revision ID: 0001
Revises:
Create Date: 2026-07-29 16:50:12.718397

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UNFROZEN_JOB_WHERE = "content_hash IS NULL AND overall_status IN ('等待中', '处理中', '阻塞')"


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("notion_page_id", sa.String(length=36), nullable=False),
        sa.Column("notion_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("notion_status", sa.String(length=32), nullable=False),
        sa.Column("automation_status", sa.String(length=32), nullable=False),
        sa.Column("target_channels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cover_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notion_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notion_last_edited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notion_page_id"),
    )
    op.create_index(op.f("ix_articles_automation_status"), "articles", ["automation_status"], unique=False)
    op.create_index(op.f("ix_articles_notion_status"), "articles", ["notion_status"], unique=False)
    op.create_table(
        "integrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("public_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("connection_status", sa.String(length=32), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider"),
    )
    op.create_table(
        "system_state",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "publication_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("target_channels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("target_channels_hash", sa.String(length=64), nullable=False),
        sa.Column("source_markdown", sa.Text(), nullable=True),
        sa.Column("snapshot_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("wechat_html", sa.Text(), nullable=True),
        sa.Column("overall_status", sa.String(length=32), nullable=False),
        sa.Column("blog_status", sa.String(length=32), nullable=False),
        sa.Column("wechat_status", sa.String(length=32), nullable=False),
        sa.Column("blog_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("wechat_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notification_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("blog_attempt_count", sa.Integer(), nullable=False),
        sa.Column("wechat_attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blog_error", sa.Text(), nullable=True),
        sa.Column("wechat_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "article_id",
            "content_hash",
            "target_channels_hash",
            name="uq_job_article_version_channels",
        ),
    )
    op.create_index(
        "ix_publication_jobs_due_scan",
        "publication_jobs",
        ["overall_status", "scheduled_at"],
        unique=False,
    )
    op.create_index(op.f("ix_publication_jobs_overall_status"), "publication_jobs", ["overall_status"], unique=False)
    op.create_index(op.f("ix_publication_jobs_scheduled_at"), "publication_jobs", ["scheduled_at"], unique=False)
    op.create_index(
        "uq_one_unfrozen_job_per_article",
        "publication_jobs",
        ["article_id"],
        unique=True,
        postgresql_where=sa.text(UNFROZEN_JOB_WHERE),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_one_unfrozen_job_per_article",
        table_name="publication_jobs",
        postgresql_where=sa.text(UNFROZEN_JOB_WHERE),
    )
    op.drop_index(op.f("ix_publication_jobs_scheduled_at"), table_name="publication_jobs")
    op.drop_index(op.f("ix_publication_jobs_overall_status"), table_name="publication_jobs")
    op.drop_index("ix_publication_jobs_due_scan", table_name="publication_jobs")
    op.drop_table("publication_jobs")
    op.drop_table("system_state")
    op.drop_table("integrations")
    op.drop_index(op.f("ix_articles_notion_status"), table_name="articles")
    op.drop_index(op.f("ix_articles_automation_status"), table_name="articles")
    op.drop_table("articles")
