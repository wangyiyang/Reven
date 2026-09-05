"""add brand domain: versioned brand profiles, channel templates, brand assets, import runs

Revision ID: 0017_brand_foundation
Revises: 0016_merge_talents_tencent
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_brand_foundation"
down_revision = "0016_merge_talents_tencent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _create_brand_versions()
    _create_channel_template_versions()
    _create_brand_assets()
    _create_brand_import_runs()
    _extend_publication_jobs()


def downgrade() -> None:
    op.drop_constraint("uq_job_article_version_channels", "publication_jobs", type_="unique")
    op.create_unique_constraint(
        "uq_job_article_version_channels",
        "publication_jobs",
        ["article_id", "content_hash", "target_channels_hash"],
    )
    op.drop_constraint("fk_publication_jobs_blog_template_version_id", "publication_jobs", type_="foreignkey")
    op.drop_constraint("fk_publication_jobs_wechat_template_version_id", "publication_jobs", type_="foreignkey")
    op.drop_constraint("fk_publication_jobs_brand_version_id", "publication_jobs", type_="foreignkey")
    op.drop_column("publication_jobs", "brand_binding_key")
    op.drop_column("publication_jobs", "blog_template_version_id")
    op.drop_column("publication_jobs", "wechat_template_version_id")
    op.drop_column("publication_jobs", "brand_version_id")
    op.drop_table("brand_import_runs")
    op.drop_index("uq_brand_assets_sha256", table_name="brand_assets")
    op.drop_table("brand_assets")
    op.drop_index("uq_one_draft_channel_template", table_name="channel_template_versions")
    op.drop_index("uq_one_published_channel_template", table_name="channel_template_versions")
    op.drop_table("channel_template_versions")
    op.drop_index("uq_one_draft_brand", table_name="brand_versions")
    op.drop_index("uq_one_published_brand", table_name="brand_versions")
    op.drop_table("brand_versions")


def _create_brand_versions() -> None:
    op.create_table(
        "brand_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="手动"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version", name="uq_brand_versions_version"),
    )
    op.create_index(
        "uq_one_published_brand",
        "brand_versions",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = '已发布'"),
    )
    op.create_index(
        "uq_one_draft_brand",
        "brand_versions",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = '草稿'"),
    )
    op.execute("ALTER TABLE brand_versions ENABLE ROW LEVEL SECURITY")


def _create_channel_template_versions() -> None:
    op.create_table(
        "channel_template_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel", "version", name="uq_channel_template_version"),
    )
    op.create_index(
        "uq_one_published_channel_template",
        "channel_template_versions",
        ["channel", "status"],
        unique=True,
        postgresql_where=sa.text("status = '已发布'"),
    )
    op.create_index(
        "uq_one_draft_channel_template",
        "channel_template_versions",
        ["channel", "status"],
        unique=True,
        postgresql_where=sa.text("status = '草稿'"),
    )
    op.execute("ALTER TABLE channel_template_versions ENABLE ROW LEVEL SECURITY")


def _create_brand_assets() -> None:
    op.create_table(
        "brand_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("public_url", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="上传"),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_brand_assets_sha256", "brand_assets", ["sha256"], unique=True)
    op.execute("ALTER TABLE brand_assets ENABLE ROW LEVEL SECURITY")


def _create_brand_import_runs() -> None:
    op.create_table(
        "brand_import_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("notion_page_id", sa.String(length=64), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_import_runs_page", "brand_import_runs", ["notion_page_id", "created_at"])
    op.execute("ALTER TABLE brand_import_runs ENABLE ROW LEVEL SECURITY")


def _extend_publication_jobs() -> None:
    op.add_column("publication_jobs", sa.Column("brand_version_id", sa.Uuid(), nullable=True))
    op.add_column("publication_jobs", sa.Column("wechat_template_version_id", sa.Uuid(), nullable=True))
    op.add_column("publication_jobs", sa.Column("blog_template_version_id", sa.Uuid(), nullable=True))
    op.add_column(
        "publication_jobs",
        sa.Column("brand_binding_key", sa.String(length=64), nullable=False, server_default="legacy"),
    )
    op.create_foreign_key(
        "fk_publication_jobs_brand_version_id",
        "publication_jobs",
        "brand_versions",
        ["brand_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_publication_jobs_wechat_template_version_id",
        "publication_jobs",
        "channel_template_versions",
        ["wechat_template_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_publication_jobs_blog_template_version_id",
        "publication_jobs",
        "channel_template_versions",
        ["blog_template_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("uq_job_article_version_channels", "publication_jobs", type_="unique")
    op.create_unique_constraint(
        "uq_job_article_version_channels",
        "publication_jobs",
        ["article_id", "content_hash", "target_channels_hash", "brand_binding_key"],
    )
