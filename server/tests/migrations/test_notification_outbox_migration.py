import asyncio
import json
import os
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from reven.jobs.notification_outbox import NotificationOutbox
from reven.jobs.repository import JobRepository
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ROOT = Path(__file__).parents[3]
ARTICLE_IDS = [UUID(f"00000000-0000-0000-0000-{index:012d}") for index in range(1, 5)]
JOB_IDS = [UUID(f"10000000-0000-0000-0000-{index:012d}") for index in range(1, 5)]
OLD_FINGERPRINT = "a" * 64
EVENT_FINGERPRINTS = ["b" * 64, "c" * 64]


def _run(coroutine: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coroutine)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "server" / "migrations" / "alembic.ini"))
    os.environ["DATABASE_URL"] = database_url
    return config


async def _truncate(database_url: str, outbox_table: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    f"TRUNCATE {outbox_table}, publication_jobs, articles, integrations, "
                    "system_state RESTART IDENTITY CASCADE"
                )
            )
    finally:
        await engine.dispose()


async def _seed_legacy_state(database_url: str) -> None:
    engine = create_async_engine(database_url)
    now = datetime(2026, 7, 30, tzinfo=UTC)
    try:
        async with engine.begin() as connection:
            for index, article_id in enumerate(ARTICLE_IDS):
                await connection.execute(
                    text(
                        """
                        INSERT INTO articles (
                            id, notion_page_id, notion_url, title, notion_status,
                            automation_status, target_channels, planned_at,
                            cover_metadata, notion_metadata, notion_last_edited_at,
                            last_error, last_synced_at, created_at, updated_at
                        ) VALUES (
                            :id, :notion_page_id, :notion_url, :title, '待发布',
                            '等待中', '[]'::jsonb, NULL, '{}'::jsonb, '{}'::jsonb,
                            :now, NULL, :now, :now, :now
                        )
                        """
                    ),
                    {
                        "id": article_id,
                        "notion_page_id": str(article_id),
                        "notion_url": f"https://notion.so/{article_id.hex}",
                        "title": f"迁移测试稿件 {index}",
                        "now": now,
                    },
                )

            terminal_events = [
                {
                    "fingerprint": EVENT_FINGERPRINTS[0],
                    "event": "blog_online:r7",
                    "stage": "博客发布",
                    "summary": "第一条",
                    "channel": "blog",
                },
                {
                    "fingerprint": EVENT_FINGERPRINTS[1],
                    "event": "wechat_draft:r9",
                    "stage": "微信发布",
                    "summary": "第二条",
                    "error_code": "WX_RETRY",
                    "channel": "wechat",
                },
            ]
            metadata = [
                {
                    "delivery_finalization": {
                        "final_status": "已完成",
                        "notion_pending": False,
                        "cleanup_pending": False,
                    },
                    "delivery_notification_events": terminal_events,
                },
                {
                    "delivery_finalization": {
                        "final_status": "失败",
                        "notion_pending": True,
                        "cleanup_pending": False,
                    }
                },
                {
                    "delivery_finalization": {
                        "final_status": "已完成",
                        "notion_pending": False,
                        "cleanup_pending": True,
                    }
                },
            ]
            statuses = ["已完成", "失败", "已完成"]
            for index, (job_id, job_metadata, status) in enumerate(zip(JOB_IDS[:3], metadata, statuses, strict=True)):
                await connection.execute(
                    text(
                        """
                        INSERT INTO publication_jobs (
                            id, article_id, content_hash, target_channels,
                            target_channels_hash, source_markdown, snapshot_metadata,
                            wechat_html, overall_status, blog_status, wechat_status,
                            blog_result, wechat_result, notification_state,
                            attempt_count, blog_attempt_count, wechat_attempt_count,
                            lease_expires_at, lease_token, scheduled_at, blog_error,
                            wechat_error, started_at, finished_at, created_at, updated_at
                        ) VALUES (
                            :id, :article_id, :content_hash, '["个人博客"]'::jsonb,
                            :channels_hash, '# legacy', CAST(:metadata AS jsonb),
                            NULL, :status, '已完成', '待处理', '{}'::jsonb, '{}'::jsonb,
                            '{}'::jsonb, 0, 0, 0, NULL, NULL,
                            CAST(:scheduled_at AS timestamptz), NULL, NULL, NULL,
                            CAST(:finished_at AS timestamptz), :now, :now
                        )
                        """
                    ),
                    {
                        "id": job_id,
                        "article_id": ARTICLE_IDS[index],
                        "content_hash": str(index + 1) * 64,
                        "channels_hash": str(index + 4) * 64,
                        "metadata": json.dumps(job_metadata, ensure_ascii=False),
                        "status": status,
                        "scheduled_at": now - timedelta(days=9 - index),
                        "finished_at": now,
                        "now": now,
                    },
                )

            await connection.execute(
                text(
                    """
                    INSERT INTO publication_jobs (
                        id, article_id, content_hash, target_channels,
                        target_channels_hash, source_markdown, snapshot_metadata,
                        wechat_html, overall_status, blog_status, wechat_status,
                        blog_result, wechat_result, notification_state,
                        attempt_count, blog_attempt_count, wechat_attempt_count,
                        lease_expires_at, lease_token, scheduled_at, blog_error,
                        wechat_error, started_at, finished_at, created_at, updated_at
                    ) VALUES (
                        :id, :article_id, :content_hash, '["个人博客"]'::jsonb,
                        :channels_hash, '# old outbox', '{}'::jsonb, NULL, '等待中',
                        '待处理', '待处理', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                        0, 0, 0, NULL, NULL, :now, NULL, NULL, NULL, NULL, :now, :now
                    )
                    """
                ),
                {
                    "id": JOB_IDS[3],
                    "article_id": ARTICLE_IDS[3],
                    "content_hash": "4" * 64,
                    "channels_hash": "7" * 64,
                    "now": now,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO preparation_notification_outbox (
                        id, fingerprint, job_id, article_id, event, payload,
                        revision, status, attempts, next_attempt_at, lease_token,
                        lease_expires_at, last_error, sent_at
                    ) VALUES (
                        '20000000-0000-0000-0000-000000000001', :fingerprint,
                        :job_id, :article_id, 'preparation_blocked',
                        '{"summary":"existing"}'::jsonb, 3, 'pending', 2,
                        :now, NULL, NULL, 'legacy error', NULL
                    )
                    """
                ),
                {
                    "fingerprint": OLD_FINGERPRINT,
                    "job_id": JOB_IDS[3],
                    "article_id": ARTICLE_IDS[3],
                    "now": now,
                },
            )
    finally:
        await engine.dispose()


async def _assert_migrated_state(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            old_row = await session.scalar(
                select(NotificationOutbox).where(NotificationOutbox.fingerprint == OLD_FINGERPRINT)
            )
            assert old_row is not None
            assert old_row.id == UUID("20000000-0000-0000-0000-000000000001")
            assert old_row.job_id == JOB_IDS[3]
            assert old_row.article_id == ARTICLE_IDS[3]
            assert old_row.event == "preparation_blocked"
            assert old_row.payload == {"summary": "existing"}
            assert old_row.revision == 3
            assert old_row.status == "pending"
            assert old_row.attempts == 2
            assert old_row.last_error == "legacy error"
            assert old_row.created_at is not None

            migrated = list(
                (
                    await session.scalars(
                        select(NotificationOutbox)
                        .where(NotificationOutbox.fingerprint.in_(EVENT_FINGERPRINTS))
                        .order_by(NotificationOutbox.next_attempt_at)
                    )
                ).all()
            )
            assert [row.fingerprint for row in migrated] == EVENT_FINGERPRINTS
            assert [row.event for row in migrated] == ["blog_online:r7", "wechat_draft:r9"]
            assert [row.revision for row in migrated] == [7, 9]
            assert [row.payload["channel"] for row in migrated] == ["blog", "wechat"]

            metadata_rows = dict(
                (
                    await session.execute(
                        text("SELECT id, snapshot_metadata FROM publication_jobs WHERE id = ANY(:ids)"),
                        {"ids": JOB_IDS[:3]},
                    )
                ).all()
            )
            assert "delivery_finalization" not in metadata_rows[JOB_IDS[0]]
            assert metadata_rows[JOB_IDS[1]]["delivery_finalization"]["notion_pending"] is True
            assert metadata_rows[JOB_IDS[2]]["delivery_finalization"]["cleanup_pending"] is True
            assert all("delivery_notification_events" not in value for value in metadata_rows.values())

            repository = JobRepository(session)
            cleanup_claim = await repository.claim_next(lease_seconds=120)
            assert cleanup_claim is not None
            assert cleanup_claim.job_id == JOB_IDS[2]
            await session.commit()

            await session.execute(
                text(
                    "UPDATE publication_jobs SET scheduled_at = clock_timestamp() + interval '1 day' WHERE id = :job_id"
                ),
                {"job_id": JOB_IDS[3]},
            )
            revision = await repository.bump_notification_revision_for_retry(JOB_IDS[1])
            assert revision == 1
            await session.commit()
            notion_claim = await repository.claim_next(lease_seconds=120)
            assert notion_claim is not None
            assert notion_claim.job_id == JOB_IDS[1]
            await session.commit()

            assert await repository.claim_next(lease_seconds=120) is None
            terminal_lease = await session.scalar(
                text("SELECT lease_token FROM publication_jobs WHERE id = :job_id"),
                {"job_id": JOB_IDS[0]},
            )
            assert terminal_lease is None
    finally:
        await engine.dispose()


async def _assert_rows_survive_round_trip(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with AsyncSession(engine) as session:
            fingerprints = list(
                (
                    await session.scalars(
                        select(NotificationOutbox.fingerprint)
                        .where(NotificationOutbox.fingerprint.in_([OLD_FINGERPRINT, *EVENT_FINGERPRINTS]))
                        .order_by(NotificationOutbox.fingerprint)
                    )
                ).all()
            )
            assert fingerprints == [OLD_FINGERPRINT, *EVENT_FINGERPRINTS]
    finally:
        await engine.dispose()


def test_upgrade_preserves_legacy_notification_and_finalization_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping migration regression test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = _alembic_config(database_url)

    try:
        command.upgrade(config, "head")
        command.downgrade(config, "0003")
        _run(_truncate(database_url, "preparation_notification_outbox"))
        _run(_seed_legacy_state(database_url))

        command.upgrade(config, "0004")
        _run(_assert_migrated_state(database_url))

        command.downgrade(config, "0003")
        command.upgrade(config, "0004")
        _run(_assert_rows_survive_round_trip(database_url))
    finally:
        command.upgrade(config, "head")
        _run(_truncate(database_url, "notification_outbox"))
