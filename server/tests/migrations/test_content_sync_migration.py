import asyncio
import os
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

ROOT = Path(__file__).parents[3]
ARTICLE_ID = UUID("00000000-0000-0000-0000-000000000019")
JOB_ID = UUID("10000000-0000-0000-0000-000000000019")
RUN_ID = UUID("20000000-0000-0000-0000-000000000019")
SNAPSHOT_ID = UUID("30000000-0000-0000-0000-000000000019")
ASSET_ID = UUID("40000000-0000-0000-0000-000000000019")


def _run(coroutine: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coroutine)


def _config(database_url: str) -> Config:
    config = Config(str(ROOT / "server" / "migrations" / "alembic.ini"))
    os.environ["DATABASE_URL"] = database_url
    return config


async def _seed_legacy_state(database_url: str) -> None:
    engine = create_async_engine(database_url)
    now = datetime(2026, 8, 10, tzinfo=UTC)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO articles (
                        id, notion_page_id, notion_url, title, notion_status,
                        automation_status, target_channels, planned_at,
                        cover_metadata, notion_metadata, notion_last_edited_at,
                        last_error, last_synced_at, created_at, updated_at
                    ) VALUES (
                        :id, :page_id, :url, '旧稿件', '待发布', '等待中',
                        '["个人博客"]'::jsonb, NULL, '{}'::jsonb, '{}'::jsonb,
                        :now, NULL, :now, :now, :now
                    )
                    """
                ),
                {
                    "id": ARTICLE_ID,
                    "page_id": str(ARTICLE_ID),
                    "url": f"https://notion.so/{ARTICLE_ID.hex}",
                    "now": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO publication_jobs (
                        id, article_id, content_hash, target_channels,
                        target_channels_hash, source_markdown, snapshot_metadata,
                        overall_status, blog_status, wechat_status, blog_result,
                        wechat_result, notification_state, attempt_count,
                        blog_attempt_count, wechat_attempt_count, scheduled_at,
                        created_at, updated_at
                    ) VALUES (
                        :id, :article_id, :hash, '["个人博客"]'::jsonb, :hash,
                        '# legacy', '{}'::jsonb, '等待中', '待处理', '待处理',
                        '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 0, 0, 0,
                        :now, :now, :now
                    )
                    """
                ),
                {"id": JOB_ID, "article_id": ARTICLE_ID, "hash": "a" * 64, "now": now},
            )
    finally:
        await engine.dispose()


async def _truncate_legacy(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    TRUNCATE notification_outbox, publication_jobs, articles,
                             integrations, system_state RESTART IDENTITY CASCADE
                    """
                )
            )
    finally:
        await engine.dispose()


async def _assert_upgrade_contract(database_url: str) -> None:
    engine = create_async_engine(database_url)
    now = datetime(2026, 8, 10, tzinfo=UTC)
    try:
        async with engine.begin() as connection:
            await _assert_legacy_defaults(connection)
            await _insert_run(connection, now)
            await _insert_snapshot(connection, now)
            await _insert_asset(connection, now)
            await _activate_snapshot(connection)
    finally:
        await engine.dispose()


async def _assert_legacy_defaults(connection: AsyncConnection) -> None:
    article = (
        await connection.execute(
            text(
                """
                SELECT content_sync_status, current_snapshot_id,
                       content_sync_error
                FROM articles WHERE id = :id
                """
            ),
            {"id": ARTICLE_ID},
        )
    ).one()
    assert article == ("未同步", None, None)
    snapshot_id = await connection.scalar(
        text("SELECT snapshot_id FROM publication_jobs WHERE id = :id"),
        {"id": JOB_ID},
    )
    assert snapshot_id is None


async def _insert_run(connection: AsyncConnection, now: datetime) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO content_sync_runs (
                id, article_id, status, stage, progress_current,
                progress_total, retryable, attempt_count, created_at,
                updated_at, next_attempt_at
            ) VALUES (
                :id, :article_id, '已同步', '同步完成', 1, 1,
                false, 1, :now, :now, :now
            )
            """
        ),
        {"id": RUN_ID, "article_id": ARTICLE_ID, "now": now},
    )


async def _insert_snapshot(connection: AsyncConnection, now: datetime) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO content_snapshots (
                id, article_id, sync_run_id, source_last_edited_at,
                title, source_markdown, portable_markdown, content_hash,
                metadata, schema_version, synced_at, created_at
            ) VALUES (
                :id, :article_id, :run_id, :now, '新稿件', '# body',
                '# 新稿件\n\nbody', :hash, '{}'::jsonb, 1, :now, :now
            )
            """
        ),
        {
            "id": SNAPSHOT_ID,
            "article_id": ARTICLE_ID,
            "run_id": RUN_ID,
            "now": now,
            "hash": "b" * 64,
        },
    )


async def _insert_asset(connection: AsyncConnection, now: datetime) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO snapshot_assets (
                id, snapshot_id, ordinal, kind, embedded, source_url, storage_key,
                public_url, sha256, mime_type, byte_size, created_at
            ) VALUES (
                :id, :snapshot_id, 0, '封面', false, 'https://notion.so/file',
                'assets/sha256/bb/hash', 'https://assets.example/hash',
                :hash, 'image/png', 3, :now
            )
            """
        ),
        {"id": ASSET_ID, "snapshot_id": SNAPSHOT_ID, "hash": "b" * 64, "now": now},
    )


async def _activate_snapshot(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            """
            UPDATE articles
            SET current_snapshot_id = :snapshot_id,
                content_sync_status = '已同步'
            WHERE id = :article_id
            """
        ),
        {"snapshot_id": SNAPSHOT_ID, "article_id": ARTICLE_ID},
    )
    current_snapshot_id = await connection.scalar(
        text("SELECT current_snapshot_id FROM articles WHERE id = :id"),
        {"id": ARTICLE_ID},
    )
    assert current_snapshot_id == SNAPSHOT_ID


async def _truncate(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    TRUNCATE snapshot_assets, content_snapshots,
                             content_sync_runs, notification_outbox,
                             publication_jobs, articles, integrations,
                             system_state RESTART IDENTITY CASCADE
                    """
                )
            )
    finally:
        await engine.dispose()


def test_upgrade_creates_atomic_content_snapshot_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping migration regression test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = _config(database_url)

    try:
        command.upgrade(config, "head")
        command.downgrade(config, "0004")
        _run(_truncate_legacy(database_url))
        _run(_seed_legacy_state(database_url))
        command.upgrade(config, "0005")
        _run(_assert_upgrade_contract(database_url))
    finally:
        command.upgrade(config, "head")
        _run(_truncate(database_url))
