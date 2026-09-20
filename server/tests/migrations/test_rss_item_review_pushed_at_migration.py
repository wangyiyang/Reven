"""0020 迁移：rss_items 表新增 review_pushed_at 可空列。"""

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


async def _column_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'rss_items'")
            )
            return {row[0] for row in rows.all()}
    finally:
        await engine.dispose()


def test_migration_0020_adds_nullable_review_pushed_at() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping migration regression test")
    config = _alembic_config(database_url)

    try:
        command.upgrade(config, "head")
        assert "review_pushed_at" in asyncio.run(_column_names(database_url))

        command.downgrade(config, "0019_brand_import_run_outcome")
        assert "review_pushed_at" not in asyncio.run(_column_names(database_url))

        command.upgrade(config, "head")
        assert "review_pushed_at" in asyncio.run(_column_names(database_url))
    finally:
        command.upgrade(config, "head")
