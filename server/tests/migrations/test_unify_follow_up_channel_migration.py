"""0027 迁移回归：两域跟进/互动方式 check 约束改写为 电话/面谈/微信/邮件/其他（#201 P3）。

升级后旧值（会议 / 电话语音）被 check 约束拒绝、新集合五值可写；
downgrade 恢复旧字面量（crm 含会议、talents 含电话语音且无其他）。
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
PRE_REVISION = "0026_talent_profile"
UNIFY_REVISION = "0027_unify_follow_up_channel"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "server" / "migrations" / "alembic.ini"))
    os.environ["DATABASE_URL"] = database_url
    return config


async def _insert_follow_up(connection: AsyncConnection, kind: str) -> None:
    customer_id = await connection.scalar(
        text(
            "INSERT INTO crm_customers (id, name, status, created_at, updated_at) "
            "VALUES (:id, '迁移客户', '潜在客户', now(), now()) RETURNING id"
        ),
        {"id": uuid4()},
    )
    await connection.execute(
        text(
            "INSERT INTO crm_follow_ups (id, customer_id, kind, occurred_on, summary, created_at, updated_at) "
            "VALUES (:id, :customer_id, :kind, current_date, '迁移跟进', now(), now())"
        ),
        {"id": uuid4(), "customer_id": customer_id, "kind": kind},
    )


async def _insert_interaction(connection: AsyncConnection, channel: str) -> None:
    talent_id = await connection.scalar(
        text(
            "INSERT INTO talents (id, name, created_at, updated_at) VALUES (:id, '迁移人才', now(), now()) RETURNING id"
        ),
        {"id": uuid4()},
    )
    await connection.execute(
        text(
            "INSERT INTO talent_interactions (id, talent_id, occurred_on, channel, created_at) "
            "VALUES (:id, :talent_id, current_date, :channel, now())"
        ),
        {"id": uuid4(), "talent_id": talent_id, "channel": channel},
    )


async def _kind_accepted(database_url: str, kind: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            try:
                async with connection.begin():
                    await _insert_follow_up(connection, kind)
            except IntegrityError:
                return False
            return True
    finally:
        await engine.dispose()


async def _channel_accepted(database_url: str, channel: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            try:
                async with connection.begin():
                    await _insert_interaction(connection, channel)
            except IntegrityError:
                return False
            return True
    finally:
        await engine.dispose()


async def _truncate_follow_up_tables(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE crm_follow_ups, crm_customers, talent_interactions, talents CASCADE")
            )
    finally:
        await engine.dispose()


def test_migration_0027_unifies_follow_up_channel_check_constraints() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping migration regression test")
    config = _alembic_config(database_url)

    try:
        command.upgrade(config, UNIFY_REVISION)

        # 新集合：两域五值一致，旧值被拒
        for kind in ["电话", "面谈", "微信", "邮件", "其他"]:
            assert asyncio.run(_kind_accepted(database_url, kind)), f"crm kind={kind} 应可写入"
            assert asyncio.run(_channel_accepted(database_url, kind)), f"talents channel={kind} 应可写入"
        assert not asyncio.run(_kind_accepted(database_url, "会议"))
        assert not asyncio.run(_channel_accepted(database_url, "电话语音"))

        # downgrade 恢复旧字面量（docstring 已注明 downgrade 假设无新值存量，先清空两表）
        asyncio.run(_truncate_follow_up_tables(database_url))
        command.downgrade(config, PRE_REVISION)
        assert asyncio.run(_kind_accepted(database_url, "会议"))
        assert asyncio.run(_channel_accepted(database_url, "电话语音"))
        assert not asyncio.run(_kind_accepted(database_url, "面谈"))
        assert not asyncio.run(_channel_accepted(database_url, "电话"))
        assert not asyncio.run(_channel_accepted(database_url, "其他"))

        # 再升级：新约束重新生效（0027 假设无旧值存量，先清掉 downgrade 阶段写入的旧值行）
        asyncio.run(_truncate_follow_up_tables(database_url))
        command.upgrade(config, UNIFY_REVISION)
        assert asyncio.run(_kind_accepted(database_url, "面谈"))
        assert asyncio.run(_channel_accepted(database_url, "电话"))
        assert not asyncio.run(_kind_accepted(database_url, "会议"))
        assert not asyncio.run(_channel_accepted(database_url, "电话语音"))
    finally:
        command.upgrade(config, "head")
