"""0028 Agent 应用表迁移；框架检查点表由独立升级入口管理。"""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from reven.agent.repository import AgentRepository
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).parents[3]
AGENT_TABLES = {"agent_config_revisions", "agent_sessions", "agent_runs", "agent_operations", "agent_approvals"}


def _config(database_url: str) -> Config:
    os.environ["DATABASE_URL"] = database_url
    return Config(str(ROOT / "server/migrations/alembic.ini"))


async def _schema(database_url: str) -> dict[str, object]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:

            def schema(sync_connection):  # type: ignore[no-untyped-def]
                inspector = inspect(sync_connection)
                return {
                    "tables": set(inspector.get_table_names()),
                    "run_indexes": {index["name"] for index in inspector.get_indexes("agent_runs")},
                    "operation_constraints": {
                        row["name"] for row in inspector.get_unique_constraints("agent_operations")
                    },
                    "approval_checks": {row["name"] for row in inspector.get_check_constraints("agent_approvals")},
                }

            state = await connection.run_sync(schema)
            rls = await connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND rowsecurity")
            )
            state["rls"] = {row[0] for row in rls}
            return state
    finally:
        await engine.dispose()


async def _business_row(database_url: str, *, seed: bool) -> str:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            if seed:
                await connection.execute(
                    text(
                        "INSERT INTO crm_customers (id, name, status, created_at, updated_at) "
                        "VALUES (gen_random_uuid(), '迁移前虚构客户', '潜在客户', now(), now())"
                    )
                )
            return str(await connection.scalar(text("SELECT name FROM crm_customers LIMIT 1")))
    finally:
        await engine.dispose()


async def _constraints_reject_invalid_rows(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            repository = AgentRepository(db)
            session = await repository.ensure_session("migration-session", owner_id="admin", channel="rest")
            revision = await repository.create_revision(prompt="迁移测试", tool_names=[])
            claim = await repository.create_run(
                session=session,
                revision=revision,
                message="测试",
                model_ref="deepseek-official/test",
                snapshot={},
                is_override=False,
            )
            await db.commit()
            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    await db.execute(
                        text("UPDATE agent_runs SET status = 'unknown' WHERE id = :id"), {"id": claim.run.id}
                    )
            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    await db.execute(
                        text("UPDATE agent_runs SET snapshot = '[]'::jsonb WHERE id = :id"), {"id": claim.run.id}
                    )
            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    await db.execute(
                        text("UPDATE agent_runs SET owner_id = 'forged' WHERE id = :id"), {"id": claim.run.id}
                    )
    finally:
        await engine.dispose()


def test_agent_persistence_upgrade_and_round_trip_preserve_business_data() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    config = _config(database_url)
    command.upgrade(config, "0027_unify_follow_up_channel")
    assert asyncio.run(_business_row(database_url, seed=True)) == "迁移前虚构客户"
    command.upgrade(config, "head")
    state = asyncio.run(_schema(database_url))
    assert AGENT_TABLES <= state["tables"]
    assert AGENT_TABLES <= state["rls"]
    assert "uq_agent_runs_busy_session" in state["run_indexes"]
    assert "uq_agent_operations_run_call" in state["operation_constraints"]
    assert "ck_agent_approvals_status" in state["approval_checks"]
    assert not {"checkpoints", "checkpoint_blobs", "checkpoint_writes"} & state["tables"]
    asyncio.run(_constraints_reject_invalid_rows(database_url))
    command.downgrade(config, "0027_unify_follow_up_channel")
    assert asyncio.run(_business_row(database_url, seed=False)) == "迁移前虚构客户"
    command.upgrade(config, "head")
    assert AGENT_TABLES <= asyncio.run(_schema(database_url))["tables"]
    assert asyncio.run(_business_row(database_url, seed=False)) == "迁移前虚构客户"
