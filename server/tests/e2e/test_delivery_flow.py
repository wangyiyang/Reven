from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from reven.articles.models import Article
from reven.domain import AutomationStatus, JobStatus
from reven.integrations.models import Integration
from reven.integrations.notion.sync import NotionSyncService
from reven.jobs.models import PublicationJob
from reven.jobs.runner import PublicationJobTick
from reven.jobs.service import PublicationJobService
from reven.publishing.delivery_store import SqlAlchemyDeliveryStore
from reven.publishing.orchestrator import PublicationOrchestrator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .fakes import FakeDeliveryWriter, FakeMaterializer, FakeNotifier, FakeNotion, FakePublisher, notion_page


class E2ESystem:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
        notion: FakeNotion,
    ) -> None:
        self.factory = factory
        self.notion = notion
        self.materializer = FakeMaterializer(tmp_path)
        self.blog = FakePublisher(
            {"article_url": "https://blog.example/e2e", "pull_request_url": "https://github.example/pr/1"}
        )
        self.wechat = FakePublisher({"media_id": "draft-media-id"})
        self.feishu = FakeNotifier()
        self.delivery_writer = FakeDeliveryWriter(notion)
        self.preparation = PublicationJobService(factory, notion, self.materializer)
        self.orchestrator = PublicationOrchestrator(
            SqlAlchemyDeliveryStore(factory, tmp_path, "https://reven.example"),
            self.blog,
            self.wechat,
            self.delivery_writer,
            self.feishu,
        )

    async def sync_once(self) -> None:
        await self._ensure_integrations()
        await NotionSyncService(self.factory, self.notion, "editorial").sync_once()

    async def _ensure_integrations(self) -> None:
        async with self.factory.begin() as session:
            count = await session.scalar(select(func.count()).select_from(Integration))
            if count:
                return
            tested_at = datetime(2026, 7, 29, tzinfo=UTC)
            session.add_all(
                [
                    Integration(
                        provider=provider,
                        encrypted_secret="e2e-placeholder",
                        connection_status="连接正常",
                        last_tested_at=tested_at,
                    )
                    for provider in ("github", "wechat", "feishu")
                ]
            )

    async def run_once(self) -> None:
        tick = PublicationJobTick(
            self.factory,
            self.preparation,
            self.orchestrator,
            lease_seconds=30,
            heartbeat_seconds=10,
        )
        await asyncio.wait_for(tick(), timeout=5)
        await asyncio.wait_for(tick(), timeout=5)

    async def make_due(self) -> None:
        async with self.factory.begin() as session:
            job = await session.scalar(select(PublicationJob))
            now = await session.scalar(select(func.clock_timestamp()))
            assert job is not None
            assert now is not None
            job.scheduled_at = now - timedelta(seconds=1)

    async def article_and_job(self) -> tuple[Article, PublicationJob]:
        async with self.factory() as session:
            article = await session.scalar(select(Article))
            job = await session.scalar(select(PublicationJob))
            assert article is not None and job is not None
            session.expunge(article)
            session.expunge(job)
            return article, job


@pytest.fixture
def e2e_system(db_session: AsyncSession, tmp_path: Path) -> E2ESystem:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    edited = datetime(2026, 7, 29, 0, 0, tzinfo=UTC)
    return E2ESystem(factory, tmp_path, FakeNotion(notion_page(edited_at=edited)))


@pytest.mark.anyio
async def test_notion_to_blog_and_wechat_delivery(e2e_system: E2ESystem) -> None:
    await e2e_system.sync_once()
    await e2e_system.run_once()

    article, job = await e2e_system.article_and_job()
    assert job.blog_status == "已上线"
    assert job.wechat_status == "草稿已生成"
    assert job.wechat_result["media_id"] == "draft-media-id"
    assert article.automation_status == AutomationStatus.COMPLETED
    assert e2e_system.notion.page["properties"]["状态"]["status"]["name"] == "已交付"
    assert e2e_system.feishu.events == [
        "default_channels",
        "blog_succeeded",
        "wechat_succeeded",
        "delivery_completed",
    ]


@pytest.mark.anyio
async def test_missing_cover_blocks_all_then_sync_recovers(e2e_system: E2ESystem) -> None:
    e2e_system.notion.replace(edited_at=datetime(2026, 7, 29, 0, 1, tzinfo=UTC), has_cover=False)
    await e2e_system.sync_once()
    await e2e_system.run_once()
    _, blocked = await e2e_system.article_and_job()
    assert blocked.overall_status == JobStatus.BLOCKED
    assert not e2e_system.blog.calls and not e2e_system.wechat.calls

    e2e_system.notion.replace(edited_at=datetime(2026, 7, 29, 0, 2, tzinfo=UTC), has_cover=True)
    await e2e_system.sync_once()
    await e2e_system.make_due()
    await e2e_system.run_once()
    _, recovered = await e2e_system.article_and_job()
    assert recovered.overall_status == JobStatus.COMPLETED
    assert len(e2e_system.blog.calls) == len(e2e_system.wechat.calls) == 1


@pytest.mark.anyio
async def test_date_without_time_uses_shanghai_0801(db_session: AsyncSession, tmp_path: Path) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    notion = FakeNotion(notion_page(edited_at=datetime(2026, 7, 29, tzinfo=UTC), planned_at="2026-08-01"))
    system = E2ESystem(factory, tmp_path, notion)
    await system.sync_once()

    _, job = await system.article_and_job()
    assert job.scheduled_at == datetime(2026, 8, 1, 0, 1, tzinfo=UTC)


@pytest.mark.anyio
async def test_retry_only_failed_wechat_channel(e2e_system: E2ESystem) -> None:
    e2e_system.wechat.transient_failures = 1
    await e2e_system.sync_once()
    await e2e_system.run_once()
    assert len(e2e_system.blog.calls) == len(e2e_system.wechat.calls) == 1

    await e2e_system.make_due()
    await e2e_system.run_once()
    _, job = await e2e_system.article_and_job()
    assert job.overall_status == JobStatus.COMPLETED
    assert len(e2e_system.blog.calls) == 1
    assert len(e2e_system.wechat.calls) == 2


@pytest.mark.anyio
async def test_expired_lease_is_recovered_by_new_runner(e2e_system: E2ESystem) -> None:
    await e2e_system.sync_once()
    _, job = await e2e_system.article_and_job()
    await e2e_system.preparation.prepare(job.id)
    async with e2e_system.factory.begin() as session:
        current = await session.get(PublicationJob, job.id)
        now = await session.scalar(select(func.clock_timestamp()))
        assert current is not None
        assert now is not None
        current.lease_expires_at = now - timedelta(seconds=1)
    await e2e_system.make_due()

    await e2e_system.run_once()
    _, recovered = await e2e_system.article_and_job()
    assert recovered.overall_status == JobStatus.COMPLETED
    assert e2e_system.blog.calls[0].lease_token != job.lease_token


@pytest.mark.anyio
async def test_repeated_sync_is_idempotent(e2e_system: E2ESystem) -> None:
    await e2e_system.sync_once()
    await e2e_system.sync_once()
    await e2e_system.run_once()
    await e2e_system.sync_once()
    await e2e_system.run_once()

    async with e2e_system.factory() as session:
        assert await session.scalar(select(func.count()).select_from(PublicationJob)) == 1
    assert len(e2e_system.blog.calls) == len(e2e_system.wechat.calls) == 1


@pytest.mark.anyio
async def test_notion_change_before_freeze_does_not_mix_snapshots(e2e_system: E2ESystem) -> None:
    await e2e_system.sync_once()
    _, job = await e2e_system.article_and_job()
    original_retrieve = e2e_system.notion.retrieve_page_markdown

    async def change_after_markdown(page_id: str) -> str:
        value = await original_retrieve(page_id)
        e2e_system.notion.replace(
            edited_at=datetime(2026, 7, 29, 0, 3, tzinfo=UTC),
            title="第二版标题",
            markdown="第二版正文",
        )
        return value

    e2e_system.notion.retrieve_page_markdown = change_after_markdown  # type: ignore[method-assign]
    with pytest.raises(Exception, match="发生变化"):
        await e2e_system.preparation.prepare(job.id)
    assert not e2e_system.blog.calls and not e2e_system.wechat.calls

    e2e_system.notion.retrieve_page_markdown = original_retrieve  # type: ignore[method-assign]
    await e2e_system.sync_once()
    await e2e_system.make_due()
    await e2e_system.run_once()
    article, frozen = await e2e_system.article_and_job()
    assert article.title == "第二版标题"
    assert frozen.source_markdown == "第二版正文"


@pytest.mark.anyio
async def test_notion_delivery_write_retry_does_not_republish_channels(e2e_system: E2ESystem) -> None:
    e2e_system.notion.fail_delivery_writes = 1
    await e2e_system.sync_once()
    await e2e_system.run_once()
    assert len(e2e_system.blog.calls) == len(e2e_system.wechat.calls) == 1

    await e2e_system.make_due()
    await e2e_system.run_once()
    article, job = await e2e_system.article_and_job()
    assert job.overall_status == JobStatus.COMPLETED
    assert article.automation_status == AutomationStatus.COMPLETED
    assert len(e2e_system.blog.calls) == len(e2e_system.wechat.calls) == 1
    assert len(e2e_system.delivery_writer.calls) == 2
