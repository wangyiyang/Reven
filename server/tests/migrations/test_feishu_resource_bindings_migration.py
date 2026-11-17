"""0028 迁移回归：feishu_resource_bindings 建表 + 启用绑定部分唯一索引（#226 Commit 1）。

升级后：表与 FK（级联删除）就位；同一 purpose 仅允许一行 enabled=true，
禁用行不受约束；downgrade 精确 drop 表。
"""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

ROOT = Path(__file__).parents[3]
PRE_REVISION = "0027_unify_follow_up_channel"
BINDINGS_REVISION = "0028_feishu_resource_bindings"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "server" / "migrations" / "alembic.ini"))
    os.environ["DATABASE_URL"] = database_url
    return config


async def _insert_integration(connection: AsyncConnection) -> str:
    integration_id = await connection.scalar(
        text(
            "INSERT INTO integrations (id, provider, public_config, connection_status, created_at, updated_at) "
            "VALUES (:id, 'feishu_bot', '{}', '未测试', now(), now()) RETURNING id"
        ),
        {"id": uuid4()},
    )
    return str(integration_id)


async def _insert_binding(connection: AsyncConnection, integration_id: str, *, enabled: bool) -> None:
    await connection.execute(
        text(
            "INSERT INTO feishu_resource_bindings "
            "(id, integration_id, resource_type, purpose, config, enabled, created_at, updated_at) "
            "VALUES (:id, :integration_id, 'bitable', 'rss_candidates', "
            '\'{"app_token": "bascn_x", "table_id": "tbl_x"}\'::jsonb, :enabled, now(), now())'
        ),
        {"id": uuid4(), "integration_id": integration_id, "enabled": enabled},
    )


async def _enabled_pair_accepted(database_url: str) -> bool:
    """同一事务内插入两个 enabled=true 的同用途绑定；第二个应被部分唯一索引拒绝。"""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            try:
                async with connection.begin():
                    integration_id = await _insert_integration(connection)
                    await _insert_binding(connection, integration_id, enabled=True)
                    await _insert_binding(connection, integration_id, enabled=True)
            except IntegrityError:
                return False
            return True
    finally:
        await engine.dispose()


async def _binding_count(database_url: str) -> int:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            count = await connection.scalar(text("SELECT count(*) FROM feishu_resource_bindings"))
            return int(count or 0)
    finally:
        await engine.dispose()


async def _table_exists(database_url: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.scalar(text("SELECT to_regclass('public.feishu_resource_bindings')")) is not None
    finally:
        await engine.dispose()


def test_migration_0028_creates_bindings_table_with_enabled_purpose_uniqueness() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping migration regression test")
    config = _alembic_config(database_url)

    try:
        command.upgrade(config, BINDINGS_REVISION)
        assert asyncio.run(_table_exists(database_url))

        # 同一 purpose：两个禁用绑定可共存；两个启用绑定被部分唯一索引拒绝
        assert not asyncio.run(_enabled_pair_accepted(database_url))

        async def seed_mixed() -> None:
            engine = create_async_engine(database_url)
            try:
                async with engine.begin() as connection:
                    integration_id = await _insert_integration(connection)
                    await _insert_binding(connection, integration_id, enabled=False)
                    await _insert_binding(connection, integration_id, enabled=False)
                    await _insert_binding(connection, integration_id, enabled=True)
            finally:
                await engine.dispose()

        asyncio.run(seed_mixed())
        assert asyncio.run(_binding_count(database_url)) == 3

        # 级联删除：删 integrations 行后绑定随之消失
        async def drop_integration() -> None:
            engine = create_async_engine(database_url)
            try:
                async with engine.begin() as connection:
                    await connection.execute(text("DELETE FROM integrations WHERE provider = 'feishu_bot'"))
            finally:
                await engine.dispose()

        asyncio.run(drop_integration())
        assert asyncio.run(_binding_count(database_url)) == 0

        command.downgrade(config, PRE_REVISION)
        assert not asyncio.run(_table_exists(database_url))
    finally:
        command.upgrade(config, "head")
