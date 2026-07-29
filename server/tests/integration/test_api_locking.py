import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from reven.articles.actions import ActionConflictError, ArticleActionService
from reven.articles.models import Article
from reven.domain import JobStatus, TargetChannel
from reven.jobs.models import PublicationJob
from reven.jobs.repository import JobClaim, JobRepository, compute_target_channels_hash
from reven.jobs.service import PublicationJobService
from reven.publishing.delivery_store import SqlAlchemyDeliveryStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.anyio
async def test_cancel_serializes_after_preparation_without_deadlock(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    article, job = await _seed(db_session, notion_pending=True)
    article_locked, continue_locking = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(
        "reven.jobs.service._lock_article_job",
        _interleaved_locker(article_locked, continue_locking),
    )
    service = PublicationJobService(factory, object(), object())  # type: ignore[arg-type]

    prepare = asyncio.create_task(service._mark_processing(job.id))
    await asyncio.wait_for(article_locked.wait(), timeout=2)
    cancel = asyncio.create_task(_cancel_result(factory, article.id, job.id))
    await asyncio.sleep(0)
    continue_locking.set()
    cancel_result = await asyncio.wait_for(asyncio.gather(prepare, cancel), timeout=3)

    assert cancel_result[1] == "JOB_NOT_CANCELLABLE"
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.PROCESSING


@pytest.mark.anyio
async def test_retry_serializes_after_delivery_finalization_without_lost_update(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    article, job = await _seed(db_session, leased=True)
    claim = JobClaim(job.id, job.lease_token)
    store = SqlAlchemyDeliveryStore(factory, tmp_path)
    await store.channel_failed(claim, TargetChannel.BLOG, JobStatus.FAILED, "failed", "TEST")
    await store.begin_delivery(claim, JobStatus.FAILED, "failed")
    article_locked, continue_locking = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(
        "reven.publishing.delivery_store.lock_article_job",
        _interleaved_locker(article_locked, continue_locking),
    )

    finish = asyncio.create_task(store.finish_delivery(claim))
    await asyncio.wait_for(article_locked.wait(), timeout=2)
    retry = asyncio.create_task(_retry_result(factory, article.id, job.id))
    await asyncio.sleep(0)
    continue_locking.set()
    results = await asyncio.wait_for(asyncio.gather(finish, retry), timeout=3)
    assert results[1] == "JOB_BUSY"
    async with factory.begin() as session:
        assert await JobRepository(session).release_lease(claim)
    await ArticleActionService(factory).retry(article.id, job.id, [TargetChannel.BLOG])

    await db_session.refresh(job)
    await db_session.refresh(article)
    assert job.overall_status == JobStatus.WAITING
    assert job.blog_status == "待处理"
    assert job.notification_state["_revision"] >= 1
    assert article.automation_status == "等待中"


def _interleaved_locker(
    article_locked: asyncio.Event,
    continue_locking: asyncio.Event,
) -> Callable[..., Awaitable[tuple[Article, PublicationJob] | None]]:
    async def lock(
        session: AsyncSession,
        job_id: UUID,
        *,
        article_id: UUID | None = None,
    ) -> tuple[Article, PublicationJob] | None:
        resolved = await session.scalar(
            select(PublicationJob.article_id).where(PublicationJob.id == job_id)
        )
        if resolved is None or (article_id is not None and resolved != article_id):
            return None
        article = await session.scalar(
            select(Article).where(Article.id == resolved).with_for_update()
        )
        article_locked.set()
        await continue_locking.wait()
        job = await session.scalar(
            select(PublicationJob)
            .where(PublicationJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (article, job) if article is not None and job is not None else None

    return lock


async def _cancel_result(
    factory: async_sessionmaker[AsyncSession],
    article_id: UUID,
    job_id: UUID,
) -> str:
    try:
        await ArticleActionService(factory).cancel(article_id, job_id)
    except ActionConflictError as exc:
        return exc.code
    return "cancelled"


async def _retry_result(
    factory: async_sessionmaker[AsyncSession],
    article_id: UUID,
    job_id: UUID,
) -> str:
    try:
        await ArticleActionService(factory).retry(article_id, job_id, [TargetChannel.BLOG])
    except ActionConflictError as exc:
        return exc.code
    return "retried"


async def _seed(
    session: AsyncSession,
    *,
    notion_pending: bool = False,
    leased: bool = False,
) -> tuple[Article, PublicationJob]:
    now = datetime.now(tz=UTC)
    article = Article(
        id=uuid4(),
        notion_page_id=str(uuid4()),
        notion_url="https://notion.so/page",
        title="锁序测试",
        notion_status="待发布",
        automation_status="等待中",
        target_channels=[TargetChannel.BLOG],
        planned_at=now,
        cover_metadata={},
        notion_metadata={},
        notion_last_edited_at=now,
        last_synced_at=now,
    )
    token = uuid4() if leased else None
    job = PublicationJob(
        id=uuid4(),
        article_id=article.id,
        content_hash="a" * 64,
        target_channels=[TargetChannel.BLOG],
        target_channels_hash=compute_target_channels_hash([TargetChannel.BLOG]),
        source_markdown="# test",
        snapshot_metadata={"notion_write_pending": True} if notion_pending else {},
        overall_status=JobStatus.WAITING if notion_pending else JobStatus.PROCESSING,
        blog_status="待处理",
        wechat_status="待处理",
        scheduled_at=now,
        lease_token=token,
        lease_expires_at=now + timedelta(minutes=5) if token else None,
    )
    session.add_all([article, job])
    await session.commit()
    return article, job
