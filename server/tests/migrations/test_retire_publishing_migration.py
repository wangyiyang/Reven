"""验证退役只清理稿件与指定集成，保留经营模块和 RSS 结构。"""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).parents[3]
RETIRED_TABLES = {
    "articles",
    "publication_jobs",
    "notification_outbox",
    "content_sync_runs",
    "content_snapshots",
    "snapshot_assets",
    "brand_import_runs",
}
RETIRED_PROVIDERS = {"notion", "github", "wechat"}
RETAINED_PROVIDERS = {"feishu", "feishu_bot", "translate_baidu", "embedding", "agent-llm"}


async def _seed_integrations(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            for provider in RETIRED_PROVIDERS | RETAINED_PROVIDERS:
                await connection.execute(
                    text(
                        "INSERT INTO integrations "
                        "(id, provider, public_config, encrypted_secret, connection_status, created_at, updated_at) "
                        "VALUES (:id, :provider, '{}', 'test-ciphertext', '未测试', now(), now())"
                    ),
                    {"id": uuid4(), "provider": provider},
                )
    finally:
        await engine.dispose()


async def _assert_schema(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            tables = set(await connection.run_sync(lambda conn: inspect(conn).get_table_names()))
            assert not tables & RETIRED_TABLES
            assert {
                "rss_items",
                "rss_sources",
                "rss_keywords",
                "rss_discovery_runs",
                "brand_versions",
                "brand_assets",
                "channel_template_versions",
                "crm_customers",
                "finance_entries",
                "projects",
                "sops",
                "talents",
                "auth_sessions",
            } <= tables
            columns = await connection.run_sync(lambda conn: inspect(conn).get_columns("rss_items"))
            names = {column["name"] for column in columns}
            assert {"saved_at", "review_pushed_at"} <= names
            assert not names & {
                "notion_page_id",
                "notion_url",
                "push_token",
                "push_started_at",
                "push_error",
                "pushed_at",
            }
            project_columns = await connection.run_sync(lambda conn: inspect(conn).get_columns("projects"))
            assert "notion_url" not in {column["name"] for column in project_columns}
            providers = set((await connection.execute(text("SELECT provider FROM integrations"))).scalars())
            assert providers == RETAINED_PROVIDERS
    finally:
        await engine.dispose()


def test_retirement_removes_only_retired_schema_and_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(ROOT / "server/migrations/alembic.ini"))
    command.upgrade(config, "0020_rss_item_review_pushed_at")
    asyncio.run(_seed_integrations(url))
    command.upgrade(config, "head")
    asyncio.run(_assert_schema(url))
    command.upgrade(config, "head")
    with pytest.raises(RuntimeError, match="无法降级"):
        command.downgrade(config, "0020_rss_item_review_pushed_at")
    asyncio.run(_assert_schema(url))
