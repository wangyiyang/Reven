"""0025 迁移：crm_customers 删双写计划列，crm_follow_ups.next_follow_up_on 改名 next_due_on（#201 P1）。"""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
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


async def _check_constraints(database_url: str, table: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT constraint_name FROM information_schema.table_constraints "
                    "WHERE table_name = :table AND constraint_type = 'CHECK'"
                ),
                {"table": table},
            )
            return {row[0] for row in rows.all()}
    finally:
        await engine.dispose()


async def _plan_pair_is_rejected(database_url: str, *, customers_table: bool) -> bool:
    """违反「有日期必须有行动」配对约束的插入应被拒；返回 True 表示约束生效。"""
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            if customers_table:
                statement = text(
                    "INSERT INTO crm_customers (id, name, status, next_follow_up_on, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), '违例客户', '潜在客户', DATE '2026-10-02', now(), now())"
                )
            else:
                statement = text(
                    "INSERT INTO crm_follow_ups "
                    "(id, customer_id, kind, occurred_on, summary, next_due_on, created_at, updated_at) "
                    "SELECT gen_random_uuid(), id, '电话', DATE '2026-10-01', '沟通', DATE '2026-10-02', now(), now() "
                    "FROM crm_customers LIMIT 1"
                )
                await connection.execute(
                    text(
                        "INSERT INTO crm_customers (id, name, status, created_at, updated_at) "
                        "VALUES (gen_random_uuid(), '种子客户', '潜在客户', now(), now())"
                    )
                )
            try:
                await connection.execute(statement)
            except DBAPIError:
                return True
            return False
    finally:
        await engine.dispose()


def test_migration_0025_drops_customer_plan_columns_and_renames_follow_up_due() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping migration regression test")
    config = _alembic_config(database_url)

    try:
        command.upgrade(config, "0025_crm_plan_derive")
        customer_columns = asyncio.run(_columns(database_url, "crm_customers"))
        follow_up_columns = asyncio.run(_columns(database_url, "crm_follow_ups"))
        assert "next_action" not in customer_columns
        assert "next_follow_up_on" not in customer_columns
        assert "next_due_on" in follow_up_columns
        assert "next_follow_up_on" not in follow_up_columns
        customer_checks = asyncio.run(_check_constraints(database_url, "crm_customers"))
        follow_up_checks = asyncio.run(_check_constraints(database_url, "crm_follow_ups"))
        assert "ck_crm_customers_follow_up_action" not in customer_checks
        # rename 后跟进表配对约束保留（PG 自动更新列引用），违配对阵列仍被拒
        assert "ck_crm_follow_ups_follow_up_action" in follow_up_checks
        assert asyncio.run(_plan_pair_is_rejected(database_url, customers_table=False))

        command.downgrade(config, "0024_rss_resilience")
        customer_columns = asyncio.run(_columns(database_url, "crm_customers"))
        follow_up_columns = asyncio.run(_columns(database_url, "crm_follow_ups"))
        assert {"next_action", "next_follow_up_on"} <= customer_columns
        assert "next_follow_up_on" in follow_up_columns
        assert "next_due_on" not in follow_up_columns
        customer_checks = asyncio.run(_check_constraints(database_url, "crm_customers"))
        assert "ck_crm_customers_follow_up_action" in customer_checks
        assert asyncio.run(_plan_pair_is_rejected(database_url, customers_table=True))

        command.upgrade(config, "0025_crm_plan_derive")
        customer_columns = asyncio.run(_columns(database_url, "crm_customers"))
        assert "next_action" not in customer_columns
        assert "next_follow_up_on" not in customer_columns
    finally:
        command.upgrade(config, "0025_crm_plan_derive")
