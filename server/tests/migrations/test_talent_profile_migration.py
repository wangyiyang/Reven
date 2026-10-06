"""0026 迁移：talents 加画像列与 preferences，新建履历/院校子表（#201 P2）。"""

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


async def _rls_tables(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND rowsecurity = true")
            )
            return {row[0] for row in rows.all()}
    finally:
        await engine.dispose()


async def _indexes(database_url: str, table: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = :table"),
                {"table": table},
            )
            return {row[0] for row in rows.all()}
    finally:
        await engine.dispose()


async def _violating_insert_is_rejected(database_url: str, statement: str, *, seed_talent: bool) -> bool:
    """违反 check 约束的插入应被拒；返回 True 表示约束生效。"""
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            if seed_talent:
                await connection.execute(
                    text(
                        "INSERT INTO talents (id, name, created_at, updated_at) "
                        "VALUES (gen_random_uuid(), '种子人才', now(), now())"
                    )
                )
            try:
                await connection.execute(text(statement))
            except DBAPIError:
                return True
            return False
    finally:
        await engine.dispose()


def test_migration_0026_adds_talent_profile_columns_and_profile_tables() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping migration regression test")
    config = _alembic_config(database_url)

    experience_range_violation = (
        "INSERT INTO talent_experiences (id, talent_id, company, title, start_on, end_on, created_at, updated_at) "
        "SELECT gen_random_uuid(), id, '某设计公司', '视觉设计师', DATE '2026-06-01', DATE '2026-01-01', now(), now() "
        "FROM talents LIMIT 1"
    )
    education_range_violation = (
        "INSERT INTO talent_educations (id, talent_id, school, start_on, end_on, created_at, updated_at) "
        "SELECT gen_random_uuid(), id, '某美术学院', DATE '2020-09-01', DATE '2019-06-01', now(), now() "
        "FROM talents LIMIT 1"
    )
    preferences_non_array_violation = (
        "INSERT INTO talents (id, name, preferences, created_at, updated_at) "
        "VALUES (gen_random_uuid(), '违例人才', '\"非数组\"'::jsonb, now(), now())"
    )

    try:
        command.upgrade(config, "0026_talent_profile")
        talent_columns = asyncio.run(_columns(database_url, "talents"))
        assert {"phone", "email", "wechat", "preferences"} <= talent_columns
        assert "ck_talents_preferences_array" in asyncio.run(_check_constraints(database_url, "talents"))

        experience_columns = asyncio.run(_columns(database_url, "talent_experiences"))
        assert {
            "id",
            "talent_id",
            "company",
            "title",
            "description",
            "start_on",
            "end_on",
            "created_at",
            "updated_at",
        } == experience_columns
        education_columns = asyncio.run(_columns(database_url, "talent_educations"))
        assert {
            "id",
            "talent_id",
            "school",
            "degree",
            "major",
            "start_on",
            "end_on",
            "created_at",
            "updated_at",
        } == education_columns

        assert "ck_talent_experiences_date_range" in asyncio.run(_check_constraints(database_url, "talent_experiences"))
        assert "ck_talent_educations_date_range" in asyncio.run(_check_constraints(database_url, "talent_educations"))
        assert "ix_talent_experiences_talent_id_start_on" in asyncio.run(_indexes(database_url, "talent_experiences"))
        assert "ix_talent_educations_talent_id_start_on" in asyncio.run(_indexes(database_url, "talent_educations"))
        assert {"talent_experiences", "talent_educations"} <= asyncio.run(_rls_tables(database_url))

        # 区间 check 与 preferences 数组 check：违例插入被拒
        assert asyncio.run(_violating_insert_is_rejected(database_url, experience_range_violation, seed_talent=True))
        assert asyncio.run(_violating_insert_is_rejected(database_url, education_range_violation, seed_talent=True))
        assert asyncio.run(
            _violating_insert_is_rejected(database_url, preferences_non_array_violation, seed_talent=False)
        )

        command.downgrade(config, "0025_crm_plan_derive")
        talent_columns = asyncio.run(_columns(database_url, "talents"))
        assert {"phone", "email", "wechat", "preferences"}.isdisjoint(talent_columns)
        dropped = asyncio.run(_columns(database_url, "talent_experiences"))
        assert dropped == set()
        assert asyncio.run(_rls_tables(database_url)).isdisjoint({"talent_experiences", "talent_educations"})

        command.upgrade(config, "0026_talent_profile")
        talent_columns = asyncio.run(_columns(database_url, "talents"))
        assert {"phone", "email", "wechat", "preferences"} <= talent_columns
        assert asyncio.run(_columns(database_url, "talent_educations")) != set()
    finally:
        command.upgrade(config, "0026_talent_profile")
