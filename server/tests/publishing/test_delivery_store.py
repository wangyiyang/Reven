from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from reven.articles.models import Article
from reven.domain import JobStatus, TargetChannel
from reven.jobs.errors import TransientPublishError
from reven.jobs.models import PublicationJob
from reven.jobs.repository import JobClaim, compute_target_channels_hash
from reven.publishing.delivery_store import SqlAlchemyDeliveryStore
from reven.publishing.orchestrator import Notification, PublicationOrchestrator
from sqlalchemy.ext.asyncio import async_sessionmaker


async def create_job(db_session) -> tuple[PublicationJob, JobClaim]:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    article = Article(
        notion_page_id=str(uuid4()),
        notion_url="https://www.notion.so/page",
        title="稿件",
        notion_status="待发布",
        automation_status="处理中",
        target_channels=[TargetChannel.BLOG, TargetChannel.WECHAT],
        notion_last_edited_at=now,
        last_synced_at=now,
    )
    db_session.add(article)
    await db_session.flush()
    token = uuid4()
    channels = [TargetChannel.BLOG, TargetChannel.WECHAT]
    job = PublicationJob(
        article_id=article.id,
        content_hash="a" * 64,
        target_channels=channels,
        target_channels_hash=compute_target_channels_hash(channels),
        overall_status=JobStatus.PROCESSING,
        blog_status="待处理",
        wechat_status="待处理",
        scheduled_at=now,
        lease_token=token,
        lease_expires_at=now + timedelta(minutes=5),
    )
    db_session.add(job)
    await db_session.commit()
    return job, JobClaim(job.id, token)


@pytest.mark.anyio
async def test_store_fences_channel_completion_and_notification(db_session) -> None:  # type: ignore[no-untyped-def]
    job, claim = await create_job(db_session)
    store = SqlAlchemyDeliveryStore(
        async_sessionmaker(db_session.bind, expire_on_commit=False),
        Path("/tmp/jobs"),
    )

    record = await store.channel_succeeded(
        claim,
        TargetChannel.BLOG,
        {"article_url": "https://www.wangyiyang.cc/post"},
    )
    assert record.channel_statuses[TargetChannel.BLOG] == "已上线"
    assert await store.record_notification(claim, "fingerprint")
    assert await store.has_notification(claim, "fingerprint")

    with pytest.raises(TransientPublishError, match="租约"):
        await store.channel_succeeded(
            JobClaim(job.id, uuid4()),
            TargetChannel.WECHAT,
            {"media_id": "draft"},
        )


@pytest.mark.anyio
async def test_completion_updates_article_and_preserves_pending_until_finish(db_session) -> None:  # type: ignore[no-untyped-def]
    job, claim = await create_job(db_session)
    store = SqlAlchemyDeliveryStore(
        async_sessionmaker(db_session.bind, expire_on_commit=False),
        Path("/tmp/jobs"),
    )
    await store.channel_succeeded(
        claim,
        TargetChannel.BLOG,
        {"article_url": "https://www.wangyiyang.cc/post"},
    )
    await store.channel_succeeded(claim, TargetChannel.WECHAT, {"media_id": "draft"})

    pending = await store.begin_completion(claim)
    assert pending.pending_status == JobStatus.COMPLETED
    await store.finish_completion(claim)

    await db_session.refresh(job)
    article = await db_session.get(Article, job.article_id)
    assert job.overall_status == JobStatus.COMPLETED
    assert article is not None
    assert article.automation_status == "已完成"
    assert article.notion_status == "已交付"
    assert article.last_error is None


class _Publisher:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.calls = 0

    async def publish(self, claim: JobClaim) -> dict[str, object]:
        del claim
        self.calls += 1
        return self.result


class _Notion:
    def __init__(self) -> None:
        self.fail = True

    async def write(self, record, status, reason) -> None:  # type: ignore[no-untyped-def]
        del record, status, reason
        if self.fail:
            raise TransientPublishError("Notion unavailable")


class _Notifier:
    async def send(self, notification: Notification) -> None:
        del notification


@pytest.mark.anyio
async def test_real_store_notion_retry_only_backfills_and_cleans_after_commit(
    db_session,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    job, claim = await create_job(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    workspace = tmp_path / "jobs" / str(job.id)
    workspace.mkdir(parents=True)
    blog = _Publisher({"article_url": "https://www.wangyiyang.cc/post"})
    wechat = _Publisher({"media_id": "draft"})
    notion = _Notion()
    orchestrator = PublicationOrchestrator(
        SqlAlchemyDeliveryStore(factory, tmp_path),
        blog,
        wechat,
        notion,
        _Notifier(),
    )

    with pytest.raises(TransientPublishError):
        await orchestrator.execute(claim)
    assert workspace.exists()

    notion.fail = False
    await orchestrator.execute(claim)

    assert (blog.calls, wechat.calls) == (1, 1)
    assert not workspace.exists()
    async with factory() as session:
        persisted = await session.get(PublicationJob, job.id)
        assert persisted is not None
        assert persisted.overall_status == JobStatus.COMPLETED
