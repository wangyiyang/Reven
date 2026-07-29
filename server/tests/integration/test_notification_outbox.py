import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from reven.articles.models import Article
from reven.jobs.models import PublicationJob
from reven.jobs.notification_outbox import (
    NotificationOutbox,
    NotificationOutboxTick,
    enqueue_preparation_notification,
)
from reven.jobs.repository import JobRepository
from reven.publishing.notifications import Notification
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class Notifier:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    async def send(self, notification: Notification) -> None:
        del notification
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise RuntimeError("secret must not persist")


async def _seed(factory: async_sessionmaker[AsyncSession]) -> tuple[Article, PublicationJob]:
    now = datetime.now(tz=UTC)
    async with factory.begin() as session:
        article = Article(
            notion_page_id="outbox-page",
            notion_url="https://notion.so/outbox",
            title="稿件",
            notion_status="待发布",
            notion_last_edited_at=now,
            last_synced_at=now,
        )
        session.add(article)
        await session.flush()
        job = await JobRepository(session).create_waiting(
            article_id=article.id, content_hash="a" * 64, target_channels=["个人博客"], scheduled_at=now
        )
    return article, job


@pytest.mark.anyio
async def test_failure_is_sanitized_and_backed_off_without_hot_loop(db_session) -> None:  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    article, job = await _seed(factory)
    async with factory.begin() as session:
        enqueue_preparation_notification(session, job, article, event="blocked", stage="阻塞", summary="缺封面")
        await session.merge(job)
    notifier = Notifier(failures=1)
    tick = NotificationOutboxTick(factory, notifier)

    await tick()
    await tick()

    async with factory() as session:
        row = await session.scalar(select(NotificationOutbox))
        now = await session.scalar(select(func.clock_timestamp()))
        assert row is not None and now is not None
        assert row.attempts == 1 and row.next_attempt_at > now
        assert row.last_error == "RuntimeError" and notifier.calls == 1


@pytest.mark.anyio
async def test_concurrent_ticks_send_once(db_session) -> None:  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    article, job = await _seed(factory)
    async with factory.begin() as session:
        enqueue_preparation_notification(session, job, article, event="blocked", stage="阻塞", summary="缺封面")
        await session.merge(job)
    notifier = Notifier()

    await asyncio.gather(
        NotificationOutboxTick(factory, notifier)(),
        NotificationOutboxTick(factory, notifier)(),
    )

    assert notifier.calls == 1


@pytest.mark.anyio
async def test_lost_lease_cannot_mark_new_claim_sent(db_session) -> None:  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    article, job = await _seed(factory)
    async with factory.begin() as session:
        enqueue_preparation_notification(session, job, article, event="blocked", stage="阻塞", summary="缺封面")
        await session.merge(job)
    first_tick = NotificationOutboxTick(factory, Notifier(), lease_seconds=30)
    first = await first_tick._claim()
    assert first is not None
    async with factory.begin() as session:
        row = await session.get(NotificationOutbox, first.id)
        assert row is not None
        row.lease_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
    second = await NotificationOutboxTick(factory, Notifier())._claim()
    assert second is not None and second.lease_token != first.lease_token

    await first_tick._sent(first)

    async with factory() as session:
        row = await session.get(NotificationOutbox, first.id)
        assert row is not None and row.status == "pending" and row.lease_token == second.lease_token


@pytest.mark.anyio
async def test_manual_retry_versions_same_error_but_automatic_repeat_deduplicates(db_session) -> None:  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    article, job = await _seed(factory)
    async with factory.begin() as session:
        enqueue_preparation_notification(session, job, article, event="blocked", stage="阻塞", summary="缺封面")
        await session.merge(job)
    async with factory.begin() as session:
        assert await JobRepository(session).bump_notification_revision_for_retry(job.id) == 2
        current = await session.get(PublicationJob, job.id)
        current_article = await session.get(Article, article.id)
        assert current is not None and current_article is not None
        enqueue_preparation_notification(
            session, current, current_article, event="blocked", stage="阻塞", summary="缺封面"
        )
        enqueue_preparation_notification(
            session, current, current_article, event="blocked", stage="阻塞", summary="缺封面"
        )

    async with factory() as session:
        rows = list((await session.scalars(select(NotificationOutbox))).all())
        assert len(rows) == 2
        assert {row.revision for row in rows} == {1, 3}
        assert len({row.fingerprint for row in rows}) == 2
