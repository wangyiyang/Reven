"""0024 迁移：rss_discovery_runs 增 processed_source_ids，rss_sources 增死源治理列（#178）。"""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).parents[3]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "server" / "migrations" / "alembic.ini"))
    os.environ["DATABASE_URL"] = database_url
    return config


async def _columns(database_url: str, table: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :table"),
                {"table": table},
            )
            return {row[0] for row in rows.all()}
    finally:
        await engine.dispose()


def test_migration_0024_adds_checkpoint_and_source_governance_columns() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping migration regression test")
    config = _alembic_config(database_url)
    source_columns = {
        "consecutive_failures",
        "last_fetched_at",
        "last_error",
        "disabled_at",
        "disabled_reason",
    }

    try:
        command.upgrade(config, "0024_rss_resilience")
        run_columns = asyncio.run(_columns(database_url, "rss_discovery_runs"))
        rss_source_columns = asyncio.run(_columns(database_url, "rss_sources"))
        assert "processed_source_ids" in run_columns
        assert source_columns <= rss_source_columns

        command.downgrade(config, "0023_notification_logs")
        run_columns = asyncio.run(_columns(database_url, "rss_discovery_runs"))
        rss_source_columns = asyncio.run(_columns(database_url, "rss_sources"))
        assert "processed_source_ids" not in run_columns
        assert source_columns.isdisjoint(rss_source_columns)

        command.upgrade(config, "0024_rss_resilience")
        run_columns = asyncio.run(_columns(database_url, "rss_discovery_runs"))
        rss_source_columns = asyncio.run(_columns(database_url, "rss_sources"))
        assert "processed_source_ids" in run_columns
        assert source_columns <= rss_source_columns
    finally:
        command.upgrade(config, "0024_rss_resilience")
