"""品牌领域迁移回归：四张新表、publication_jobs 品牌绑定列与存量 legacy 回填。"""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).parents[3]
BRAND_REVISION = "0017_brand_foundation"
PRIOR_REVISION = "0016_merge_talents_tencent"


def _alembic_config(database_url: str) -> Config:
    os.environ["DATABASE_URL"] = database_url
    return Config(str(ROOT / "server" / "migrations" / "alembic.ini"))


async def _brand_schema_state(database_url: str) -> dict[str, object]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            versions = await connection.execute(text("SELECT version_num FROM alembic_version"))
            tables = await connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename IN "
                    "('brand_versions', 'channel_template_versions', 'brand_assets', 'brand_import_runs')"
                )
            )
            job_columns = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'publication_jobs' "
                    "AND column_name IN ('brand_version_id', 'wechat_template_version_id', "
                    "'blog_template_version_id', 'brand_binding_key')"
                )
            )
            return {
                "versions": {row[0] for row in versions.all()},
                "tables": {row[0] for row in tables.all()},
                "job_columns": {row[0] for row in job_columns.all()},
            }
    finally:
        await engine.dispose()


async def _legacy_binding_keys(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(text("SELECT DISTINCT brand_binding_key FROM publication_jobs"))
            return {row[0] for row in rows.all()}
    finally:
        await engine.dispose()


async def _seed_legacy_job(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE publication_jobs, articles RESTART IDENTITY CASCADE"))
            await connection.execute(
                text(
                    "INSERT INTO articles (id, notion_page_id, notion_url, title, notion_status, "
                    "automation_status, target_channels, cover_metadata, notion_metadata, "
                    "notion_last_edited_at, last_synced_at, content_sync_status, created_at, updated_at) "
                    "VALUES ('00000000-0000-0000-0000-0000000000a1', 'page-legacy', 'https://notion.so/x', "
                    "'旧稿', '已就绪', '未开始', '[]'::jsonb, '{}'::jsonb, '{}'::jsonb, "
                    "now(), now(), '未同步', now(), now())"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO publication_jobs (id, article_id, content_hash, target_channels, "
                    "target_channels_hash, snapshot_metadata, overall_status, blog_status, wechat_status, "
                    "blog_result, wechat_result, notification_state, attempt_count, blog_attempt_count, "
                    "wechat_attempt_count, scheduled_at, created_at, updated_at) "
                    "VALUES ('10000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000a1', "
                    "'aabb', '[\"个人博客\"]'::jsonb, 'ccdd', '{}'::jsonb, '已完成', '已上线', '草稿已生成', "
                    "'{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 1, 1, 1, now(), now(), now())"
                )
            )
    finally:
        await engine.dispose()


def test_brand_foundation_upgrade_and_legacy_backfill() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping migration regression test")
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
        command.downgrade(config, PRIOR_REVISION)
        state = asyncio.run(_brand_schema_state(database_url))
        assert state["versions"] == {PRIOR_REVISION}
        assert state["tables"] == set()
        assert state["job_columns"] == set()

        asyncio.run(_seed_legacy_job(database_url))
        command.upgrade(config, "head")

        state = asyncio.run(_brand_schema_state(database_url))
        assert state["versions"] == {"0020_rss_item_review_pushed_at"}  # head 已前进到 0020
        assert state["tables"] == {
            "brand_versions",
            "channel_template_versions",
            "brand_assets",
            "brand_import_runs",
        }
        assert state["job_columns"] == {
            "brand_version_id",
            "wechat_template_version_id",
            "blog_template_version_id",
            "brand_binding_key",
        }
        # 存量任务回填 legacy 绑定键，保持旧行为可重试（AC9）
        assert asyncio.run(_legacy_binding_keys(database_url)) == {"legacy"}
    finally:
        command.upgrade(config, "head")
