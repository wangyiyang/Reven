from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import SecretStr
from reven.articles.models import Article
from reven.config import Settings
from reven.domain import AutomationStatus, JobStatus, TargetChannel
from reven.integrations.models import Integration
from reven.integrations.notion.sync import NotionSyncService
from reven.jobs.errors import TransientPublishError
from reven.jobs.models import PublicationJob
from reven.jobs.notification_outbox import PreparationNotificationOutbox, PreparationNotificationTick
from reven.jobs.repository import JobClaim, JobRepository
from reven.jobs.runner import PublicationJobTick
from reven.jobs.service import PreparationConflictError, PublicationJobService
from reven.publishing.blog.converter import BlogConverter
from reven.publishing.blog.publisher import BlogPublisher
from reven.publishing.blog.store import SqlAlchemyBlogResultStore
from reven.publishing.delivery_store import SqlAlchemyDeliveryStore
from reven.publishing.factory import _notion_properties, build_configured_orchestrator
from reven.publishing.orchestrator import PublicationOrchestrator
from reven.publishing.wechat.publisher import WeChatPublisher
from reven.publishing.wechat.store import SqlAlchemyWeChatResultStore
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .fakes import FakeDeliveryWriter, FakeMaterializer, FakeNotifier, FakeNotion, FakePublisher, notion_page
from .publisher_fakes import ContractBlogWorkspace, ContractGitHub, ContractRenderer, ContractWeChat


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
        self.notification_tick = PreparationNotificationTick(factory, self.feishu)

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
        await self.run_turns(2)

    async def run_turns(self, count: int) -> None:
        tick = PublicationJobTick(
            self.factory,
            self.preparation,
            self.orchestrator,
            lease_seconds=30,
            heartbeat_seconds=10,
        )
        for _ in range(count):
            await asyncio.wait_for(tick(), timeout=5)
            await self.notification_tick()

    async def make_notification_due(self) -> None:
        async with self.factory.begin() as session:
            outbox = await session.scalar(select(PreparationNotificationOutbox))
            now = await session.scalar(select(func.clock_timestamp()))
            assert outbox is not None and now is not None
            outbox.next_attempt_at = now - timedelta(seconds=1)

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
async def test_production_publishers_consume_one_frozen_snapshot(e2e_system: E2ESystem, tmp_path: Path) -> None:
    claim = await _prepared_claim(e2e_system)
    github = ContractGitHub()
    workspace = ContractBlogWorkspace(tmp_path / "contract", github)
    renderer = ContractRenderer()
    wechat = ContractWeChat()
    blog_publisher = BlogPublisher(
        github,
        workspace,
        BlogConverter("https://blog.example"),
        SqlAlchemyBlogResultStore(e2e_system.factory),
        remote_url="https://github.com/example/blog.git",
        token="contract-token",
        poll_interval=0,
        max_polls=1,
    )
    wechat_publisher = WeChatPublisher(
        wechat,
        renderer,
        SqlAlchemyWeChatResultStore(e2e_system.factory, author="测试作者"),
    )
    delivery_store = SqlAlchemyDeliveryStore(e2e_system.factory, tmp_path, "https://reven.example")
    record = await delivery_store.load(claim)
    notion_payload = _notion_properties(record, JobStatus.COMPLETED, "")
    assert notion_payload["状态"] == {"status": {"name": "已交付"}}
    assert notion_payload["自动化状态"] == {"select": {"name": "已完成"}}
    orchestrator = PublicationOrchestrator(
        delivery_store,
        blog_publisher,
        wechat_publisher,
        e2e_system.delivery_writer,
        e2e_system.feishu,
    )

    await orchestrator.execute(claim)

    article, job = await e2e_system.article_and_job()
    assert article.automation_status == AutomationStatus.COMPLETED
    assert job.blog_result["pull_request_number"] == 7
    assert job.blog_result["merge_sha"] == "b" * 40
    assert job.wechat_result["media_id"] == "draft-media-id"
    assert github.pr_creations == workspace.pushes == 1
    assert wechat.calls == ["get_token", "upload_cover_material", "create_draft"]
    assert renderer.markdown == [job.source_markdown]
    assert any("第一版正文".encode() in content for content in workspace.captured.values())
    assert github.pushed_branch is not None
    assert job.content_hash is not None and job.content_hash[:12] in github.pushed_branch


async def _prepared_claim(e2e_system: E2ESystem) -> JobClaim:
    await e2e_system.sync_once()
    _, initial = await e2e_system.article_and_job()
    await e2e_system.preparation.prepare(initial.id)
    async with e2e_system.factory.begin() as session:
        claim = await JobRepository(session).claim_next(lease_seconds=30)
    assert claim is not None
    async with e2e_system.factory.begin() as session:
        assert await JobRepository(session).begin_execution(claim) == 1
    return claim


@pytest.mark.anyio
async def test_production_factory_wires_configured_channel_publishers(
    e2e_system: E2ESystem,
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_url=SecretStr("postgresql+asyncpg://unused"),
        reven_master_key=SecretStr(base64.b64encode(b"k" * 32).decode()),
        job_data_dir=str(tmp_path),
        renderer_command="node renderer/dist/cli.mjs",
    )

    orchestrator = build_configured_orchestrator(e2e_system.factory, settings)

    assert set(orchestrator.publishers) == {TargetChannel.BLOG, TargetChannel.WECHAT}
    assert orchestrator.store.__class__.__name__ == "SqlAlchemyDeliveryStore"
    assert orchestrator.notion.__class__.__name__ == "ConfiguredNotionDeliveryWriter"
    assert orchestrator.notifier.__class__.__name__ == "ConfiguredFeishuNotifier"


@pytest.mark.anyio
async def test_missing_cover_blocks_all_then_sync_recovers(e2e_system: E2ESystem) -> None:
    e2e_system.notion.replace(edited_at=datetime(2026, 7, 29, 0, 1, tzinfo=UTC), has_cover=False)
    await e2e_system.sync_once()
    await e2e_system.run_turns(3)
    _, blocked = await e2e_system.article_and_job()
    assert blocked.overall_status == JobStatus.BLOCKED
    assert not e2e_system.blog.calls and not e2e_system.wechat.calls
    assert e2e_system.feishu.events == ["preparation_blocked"], blocked.snapshot_metadata

    e2e_system.notion.replace(edited_at=datetime(2026, 7, 29, 0, 2, tzinfo=UTC), has_cover=True)
    await e2e_system.sync_once()
    await e2e_system.make_due()
    await e2e_system.run_once()
    _, recovered = await e2e_system.article_and_job()
    assert recovered.overall_status == JobStatus.COMPLETED
    assert len(e2e_system.blog.calls) == len(e2e_system.wechat.calls) == 1
    assert e2e_system.feishu.events.count("preparation_blocked") == 1


@pytest.mark.anyio
async def test_failed_block_notification_is_recoverable_without_state_change(e2e_system: E2ESystem) -> None:
    e2e_system.feishu.failures = 1
    e2e_system.notion.replace(edited_at=datetime(2026, 7, 29, 0, 1, tzinfo=UTC), has_cover=False)
    await e2e_system.sync_once()
    await e2e_system.run_turns(2)
    article, blocked = await e2e_system.article_and_job()

    assert blocked.overall_status == JobStatus.BLOCKED
    assert article.automation_status == AutomationStatus.BLOCKED
    assert not e2e_system.blog.calls and not e2e_system.wechat.calls
    assert e2e_system.feishu.events == []

    await e2e_system.make_notification_due()
    await e2e_system.run_once()
    _, still_blocked = await e2e_system.article_and_job()
    assert still_blocked.overall_status == JobStatus.BLOCKED
    assert e2e_system.feishu.events == ["preparation_blocked"]


@pytest.mark.anyio
async def test_persistent_feishu_failure_never_blocks_cover_recovery(e2e_system: E2ESystem) -> None:
    e2e_system.feishu.failures = 10
    e2e_system.notion.replace(edited_at=datetime(2026, 7, 29, 0, 1, tzinfo=UTC), has_cover=False)
    await e2e_system.sync_once()
    await e2e_system.run_turns(2)

    e2e_system.notion.replace(edited_at=datetime(2026, 7, 29, 0, 2, tzinfo=UTC), has_cover=True)
    await e2e_system.sync_once()
    await e2e_system.make_due()
    await e2e_system.run_once()
    _, recovered = await e2e_system.article_and_job()

    assert recovered.overall_status == JobStatus.COMPLETED
    assert len(e2e_system.blog.calls) == len(e2e_system.wechat.calls) == 1
    async with e2e_system.factory() as session:
        outbox = await session.scalar(select(PreparationNotificationOutbox))
        assert outbox is not None and outbox.status == "pending"
        assert outbox.next_attempt_at > datetime.now(tz=UTC)

    e2e_system.feishu.failures = 0
    await e2e_system.make_notification_due()
    await e2e_system.notification_tick()
    await e2e_system.notification_tick()
    assert e2e_system.feishu.events.count("preparation_blocked") == 1


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
        old_claim = await JobRepository(session).claim_next(lease_seconds=30)
    assert old_claim is not None
    async with e2e_system.factory.begin() as session:
        current = await session.get(PublicationJob, old_claim.job_id)
        assert current is not None
        attempt = await JobRepository(session).begin_execution(old_claim)
        assert attempt == 1, (
            current.overall_status,
            current.lease_token,
            current.lease_expires_at,
            current.snapshot_metadata,
        )
        now = await session.scalar(select(func.clock_timestamp()))
        assert now is not None
        current.lease_expires_at = now - timedelta(seconds=1)

    with pytest.raises(TransientPublishError, match="租约"):
        await e2e_system.orchestrator.execute(old_claim)
    assert not e2e_system.blog.calls and not e2e_system.wechat.calls

    class RecordingExecutor:
        def __init__(self, delegate: PublicationOrchestrator) -> None:
            self.delegate = delegate
            self.claims: list[JobClaim] = []

        async def execute(self, claim: JobClaim) -> None:
            self.claims.append(claim)
            await self.delegate.execute(claim)

    executor = RecordingExecutor(e2e_system.orchestrator)
    tick = PublicationJobTick(
        e2e_system.factory,
        e2e_system.preparation,
        executor,
        lease_seconds=30,
        heartbeat_seconds=10,
    )
    await asyncio.wait_for(tick(), timeout=5)
    _, recovered = await e2e_system.article_and_job()
    assert recovered.overall_status == JobStatus.COMPLETED
    assert len(executor.claims) == 1
    assert executor.claims[0].lease_token != old_claim.lease_token
    assert len(e2e_system.blog.calls) == len(e2e_system.wechat.calls) == 1


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
    with pytest.raises(PreparationConflictError, match="发生变化"):
        await e2e_system.preparation.prepare(job.id)
    assert not e2e_system.blog.calls and not e2e_system.wechat.calls

    e2e_system.notion.retrieve_page_markdown = original_retrieve  # type: ignore[method-assign]
    await e2e_system.sync_once()
    await e2e_system.make_due()
    await e2e_system.run_once()
    article, frozen = await e2e_system.article_and_job()
    assert article.title == "第二版标题"
    assert frozen.source_markdown == "第二版正文"
    assert frozen.content_hash is not None
    assert len(e2e_system.blog.calls) == len(e2e_system.wechat.calls) == 1
    cover = frozen.snapshot_metadata["cover"]
    assert isinstance(cover, dict) and len(str(cover["sha256"])) == 64


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
