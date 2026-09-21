"""0015 migration removes only the retired Tencent translation row."""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).parents[3]
_TEST_PROVIDERS = ("translate_tencent", "translate_baidu", "migration_keep_provider")


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "server" / "migrations" / "alembic.ini"))
    os.environ["DATABASE_URL"] = database_url
    return config


async def _seed_rows(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM integrations WHERE provider = ANY(:providers)"),
                {"providers": list(_TEST_PROVIDERS)},
            )
            for provider in _TEST_PROVIDERS:
                await connection.execute(
                    text(
                        """
                        INSERT INTO integrations (
                            id, provider, public_config, encrypted_secret, connection_status,
                            last_tested_at, last_error, last_latency_ms, created_at, updated_at
                        ) VALUES (
                            :id, :provider, CAST(:public_config AS jsonb), :encrypted_secret, '未测试',
                            NULL, NULL, NULL, now(), now()
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "provider": provider,
                        "public_config": json.dumps({"marker": provider}),
                        "encrypted_secret": f"ciphertext-{provider}",
                    },
                )
    finally:
        await engine.dispose()


async def _stored_providers(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT provider FROM integrations WHERE provider = ANY(:providers)"),
                {"providers": list(_TEST_PROVIDERS)},
            )
            return {str(row[0]) for row in rows}
    finally:
        await engine.dispose()


async def _cleanup(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM integrations WHERE provider = ANY(:providers)"),
                {"providers": list(_TEST_PROVIDERS)},
            )
    finally:
        await engine.dispose()


def test_migration_0015_removes_only_tencent_and_downgrade_does_not_restore_it() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping migration regression test")
    config = _alembic_config(database_url)

    try:
        command.upgrade(config, "0020_rss_item_review_pushed_at")
        command.downgrade(config, "0013_integration_last_latency_ms")
        asyncio.run(_seed_rows(database_url))

        command.upgrade(config, "0020_rss_item_review_pushed_at")
        assert asyncio.run(_stored_providers(database_url)) == {
            "translate_baidu",
            "migration_keep_provider",
        }

        command.downgrade(config, "0013_integration_last_latency_ms")
        assert asyncio.run(_stored_providers(database_url)) == {
            "translate_baidu",
            "migration_keep_provider",
        }
    finally:
        asyncio.run(_cleanup(database_url))
        command.upgrade(config, "0020_rss_item_review_pushed_at")
