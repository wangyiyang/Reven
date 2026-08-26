"""Regression tests for merging the CRM and integration migration heads."""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).parents[3]
MERGE_REVISION = "0014_merge_crm_and_integration"
HEAD_REVISION = "0015_talents"


def _alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(ROOT / "server" / "migrations" / "alembic.ini"))
    if database_url is not None:
        os.environ["DATABASE_URL"] = database_url
    return config


async def _schema_state(database_url: str) -> tuple[set[str], bool, bool]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            versions = await connection.execute(text("SELECT version_num FROM alembic_version"))
            customer_table = await connection.scalar(text("SELECT to_regclass('public.crm_customers')"))
            latency_column = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'integrations' AND column_name = 'last_latency_ms')"
                )
            )
            return {row[0] for row in versions.all()}, customer_table is not None, bool(latency_column)
    finally:
        await engine.dispose()


def test_migration_graph_has_one_head() -> None:
    script = ScriptDirectory.from_config(_alembic_config())

    assert script.get_heads() == [HEAD_REVISION]


@pytest.mark.parametrize("starting_revision", ["0013_crm", "0013_integration_last_latency_ms"])
def test_existing_branch_head_upgrades_to_merged_head(starting_revision: str) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping migration regression test")
    config = _alembic_config(database_url)

    try:
        command.upgrade(config, "head")
        command.downgrade(config, "0012_playbooks")
        command.upgrade(config, starting_revision)
        versions, _, _ = asyncio.run(_schema_state(database_url))
        assert versions == {starting_revision}

        command.upgrade(config, "head")
        versions, customer_table, latency_column = asyncio.run(_schema_state(database_url))
        assert versions == {HEAD_REVISION}
        assert customer_table
        assert latency_column
    finally:
        command.upgrade(config, "head")
