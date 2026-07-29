import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from reven.articles.actions import ActionConflictError, ArticleActionService
from reven.articles.models import Article
from reven.domain import JobStatus, TargetChannel
from reven.integrations.notion.mapper import map_notion_page
from reven.jobs.models import PublicationJob
from reven.jobs.preparation_models import Preflight, PreparedWork
from reven.jobs.repository import JobClaim, JobRepository, compute_target_channels_hash
from reven.jobs.service import PreparationConflictError, PublicationJobService
from reven.publishing.assets import MaterializedAsset, MaterializedAssets
from reven.publishing.delivery_store import SqlAlchemyDeliveryStore
from reven.publishing.validation import ValidationResult
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


@pytest.mark.anyio
async def test_real_prepare_freeze_and_cancel_overlap_without_deadlock_or_lost_cancel(
    db_session: AsyncSession,
) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    article, job = await _seed_unfrozen(db_session)
    materializing, continue_materializing = asyncio.Event(), asyncio.Event()
    materializer = _BlockingMaterializer(materializing, continue_materializing)
    service = PublicationJobService(factory, _FakeNotion(article), materializer)

    prepare = asyncio.create_task(service.prepare(job.id))
    await asyncio.wait_for(materializing.wait(), timeout=2)
    await ArticleActionService(factory).cancel(article.id, job.id)
    continue_materializing.set()
    with pytest.raises(PreparationConflictError, match="已取消|发生变化"):
        await asyncio.wait_for(prepare, timeout=3)

    await db_session.refresh(job)
    await db_session.refresh(article)
    assert job.overall_status == JobStatus.CANCELLED
    assert job.content_hash is None
    assert article.automation_status == "未开始"
    assert materializer.discarded is True


@pytest.mark.anyio
async def test_production_persist_freeze_and_cancel_contend_on_real_rows_without_deadlock(
    db_session: AsyncSession,
) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    article, job = await _seed_unfrozen(db_session)
    work = _prepared_work(article, job)
    service = PublicationJobService(factory, object(), object())  # type: ignore[arg-type]
    persist_entered, cancel_entered = asyncio.Event(), asyncio.Event()

    async with factory.begin() as blocker:
        await blocker.scalar(select(Article).where(Article.id == article.id).with_for_update())
        persist = asyncio.create_task(_entered(persist_entered, service._persist_prepared(work)))
        cancel = asyncio.create_task(_entered(cancel_entered, _cancel_result(factory, article.id, job.id)))
        await asyncio.wait_for(
            asyncio.gather(persist_entered.wait(), cancel_entered.wait()),
            timeout=2,
        )
        await asyncio.sleep(0)
        assert not persist.done()
        assert not cancel.done()

    outcomes = await asyncio.wait_for(
        asyncio.gather(persist, cancel, return_exceptions=True),
        timeout=3,
    )
    await db_session.refresh(job)
    if job.overall_status == JobStatus.CANCELLED:
        assert job.content_hash is None
        assert any(isinstance(item, PreparationConflictError) for item in outcomes)
    else:
        assert job.overall_status == JobStatus.WAITING
        assert job.content_hash is not None
        assert "JOB_NOT_CANCELLABLE" in outcomes


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
        resolved = await session.scalar(select(PublicationJob.article_id).where(PublicationJob.id == job_id))
        if resolved is None or (article_id is not None and resolved != article_id):
            return None
        article = await session.scalar(select(Article).where(Article.id == resolved).with_for_update())
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


async def _entered(event: asyncio.Event, operation):  # type: ignore[no-untyped-def]
    event.set()
    return await operation


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


async def _seed_unfrozen(session: AsyncSession) -> tuple[Article, PublicationJob]:
    article, job = await _seed(session)
    job.content_hash = None
    job.overall_status = JobStatus.WAITING
    await session.commit()
    return article, job


class _FakeNotion:
    def __init__(self, article: Article) -> None:
        self.page = {
            "id": article.notion_page_id,
            "url": article.notion_url,
            "last_edited_time": article.notion_last_edited_at.isoformat(),
            "properties": {
                "标题": {"type": "title", "title": [{"plain_text": article.title}]},
                "状态": {"type": "status", "status": {"name": "待发布"}},
                "目标渠道": {"type": "multi_select", "multi_select": [{"name": "个人博客"}]},
                "摘要": {"type": "rich_text", "rich_text": []},
                "封面": {
                    "type": "files",
                    "files": [
                        {
                            "type": "external",
                            "name": "cover",
                            "external": {"url": "https://example.com/cover.png"},
                        }
                    ],
                },
            },
        }

    async def retrieve_page(self, page_id: str):  # type: ignore[no-untyped-def]
        assert page_id == self.page["id"]
        return self.page

    async def retrieve_page_markdown(self, page_id: str) -> str:
        assert page_id == self.page["id"]
        return "正文"

    async def update_page(self, page_id: str, *, properties):  # type: ignore[no-untyped-def]
        del page_id, properties
        return {}


class _BlockingMaterializer:
    def __init__(self, started: asyncio.Event, proceed: asyncio.Event) -> None:
        self.started = started
        self.proceed = proceed
        self.discarded = False

    async def materialize(
        self,
        job_id: UUID,
        image_urls: list[str],
        cover_url: str | None,
    ) -> MaterializedAssets:
        del job_id, image_urls
        assert cover_url is not None
        self.started.set()
        await self.proceed.wait()
        cover = MaterializedAsset(
            cover_url,
            Path("/tmp/reven-lock-test-cover.png"),
            "b" * 64,
            "image/png",
            10,
        )
        return MaterializedAssets((), cover)

    async def discard(self, assets: MaterializedAssets) -> None:
        del assets
        self.discarded = True


def _prepared_work(article: Article, job: PublicationJob) -> PreparedWork:
    mapped = _FakeNotion(article).page
    cover = MaterializedAsset(
        "https://example.com/cover.png",
        Path("/tmp/reven-lock-test-cover.png"),
        "b" * 64,
        "image/png",
        10,
    )
    return PreparedWork(
        Preflight(job.id, article.id, article.notion_page_id, article.updated_at),
        map_notion_page(mapped),
        "正文",
        (TargetChannel.BLOG,),
        (),
        MaterializedAssets((), cover),
        ValidationResult(()),
    )
