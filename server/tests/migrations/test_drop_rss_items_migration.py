"""0029 迁移回归：drop rss_items（#226 Commit 5）。

升级后 rss_items 表及全部历史候选数据删除（不归档、不迁移）；downgrade 不可逆，
与 0021「不恢复历史资料」先例一致，恢复须使用升级前的数据库备份。
"""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).parents[3]
PRE_REVISION = "0028_feishu_resource_bindings"
DROP_REVISION = "0029_drop_rss_items"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "server" / "migrations" / "alembic.ini"))
    os.environ["DATABASE_URL"] = database_url
    return config


async def _table_exists(database_url: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.scalar(text("SELECT to_regclass('public.rss_items')")) is not None
    finally:
        await engine.dispose()


def test_migration_0029_drops_rss_items_irrecoverably() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping migration regression test")
    config = _alembic_config(database_url)

    try:
        command.upgrade(config, PRE_REVISION)
        assert asyncio.run(_table_exists(database_url))

        command.upgrade(config, DROP_REVISION)
        assert not asyncio.run(_table_exists(database_url))

        with pytest.raises(RuntimeError, match="无法降级"):
            command.downgrade(config, PRE_REVISION)
        assert not asyncio.run(_table_exists(database_url))
    finally:
        command.upgrade(config, "head")
