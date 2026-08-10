from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from reven.articles.models import Article
from reven.content_sync.domain import ContentSyncStatus, SyncRunStatus, SyncStage
from reven.content_sync.executor import (
    ArchivedContent,
    ArchivedMedia,
    ContentSyncWorker,
    SourceDocument,
)
from reven.content_sync.models import ContentSnapshot
from reven.content_sync.requests import ContentSyncRequestService
from reven.integrations.notion.models import MappedNotionPage, NotionFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker


class FakeSource:
    def __init__(self, page: MappedNotionPage, markdown: str) -> None:
        self.page = page
        self.markdown = markdown

    async def load(self, page_id: str) -> SourceDocument:
        assert page_id == self.page.page_id
        return SourceDocument(self.page, self.markdown)

    async def current_version(self, page_id: str) -> datetime:
        assert page_id == self.page.page_id
        return self.page.last_edited_at


class FakeMediaArchive:
    async def archive(self, run_id, markdown, cover, *, progress=None):  # type: ignore[no-untyped-def]
        assert markdown == "正文 ![图](https://notion.so/image)"
        assert cover is not None
        if progress is not None:
            await progress(SyncStage.DOWNLOADING_MEDIA, 1, 2, "封面")
        return ArchivedContent(
            canonical_markdown="正文 ![图](reven-asset://image)",
            portable_markdown="正文 ![图](https://assets.example/image)",
            media=(
                ArchivedMedia(
                    ordinal=0,
                    kind="封面",
                    embedded=False,
                    source_url=cover.url,
                    storage_key="assets/sha256/cc/cover",
                    public_url="https://assets.example/cover",
                    sha256="c" * 64,
                    mime_type="image/png",
                    byte_size=7,
                    filename=cover.name,
                ),
                ArchivedMedia(
                    ordinal=1,
                    kind="图片",
                    embedded=True,
                    source_url="https://notion.so/image",
                    storage_key="assets/sha256/ii/image",
                    public_url="https://assets.example/image",
                    sha256="d" * 64,
                    mime_type="image/png",
                    byte_size=9,
                    alt_text="图",
                ),
            ),
        )


@pytest.mark.anyio
async def test_successful_run_atomically_enables_the_complete_snapshot(db_session) -> None:  # type: ignore[no-untyped-def]
    edited_at = datetime.now(tz=UTC)
    article = _article(edited_at)
    db_session.add(article)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    requests = ContentSyncRequestService(factory)
    accepted = await requests.request(article.id)
    worker = ContentSyncWorker(factory, FakeSource(_page(article, edited_at), _MARKDOWN), FakeMediaArchive())

    assert await worker.run_once() is True

    state = await requests.get_article_state(article.id)
    run = await requests.get_run(article.id, accepted.run.id)
    assert state is not None and run is not None
    assert state.status == ContentSyncStatus.SYNCED
    assert state.current_snapshot_id is not None
    assert state.outputs_enabled is True
    assert run.status == SyncRunStatus.SUCCEEDED
    assert run.stage == SyncStage.COMPLETED
    assert (run.progress_current, run.progress_total) == (2, 2)


@pytest.mark.anyio
async def test_failed_run_records_the_exact_stage_and_media(db_session) -> None:  # type: ignore[no-untyped-def]
    edited_at = datetime.now(tz=UTC)
    article = _article(edited_at)
    db_session.add(article)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    accepted = await ContentSyncRequestService(factory).request(article.id)
    page = _page(article, edited_at)
    page = MappedNotionPage(**{**page.__dict__, "cover": None})

    assert await ContentSyncWorker(factory, FakeSource(page, _MARKDOWN), FakeMediaArchive()).run_once() is True

    run = await ContentSyncRequestService(factory).get_run(article.id, accepted.run.id)
    assert run is not None
    assert run.status == SyncRunStatus.FAILED
    assert run.error_stage == SyncStage.READING_NOTION
    assert run.error_media == "封面"


@pytest.mark.anyio
async def test_commit_refuses_to_overwrite_a_newer_indexed_notion_version(db_session) -> None:  # type: ignore[no-untyped-def]
    edited_at = datetime.now(tz=UTC)
    article = _article(edited_at)
    db_session.add(article)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    accepted = await ContentSyncRequestService(factory).request(article.id)

    class RacingSource(FakeSource):
        async def current_version(self, page_id: str) -> datetime:
            async with factory.begin() as session:
                current = await session.get(Article, article.id)
                assert current is not None
                current.notion_last_edited_at = edited_at + timedelta(microseconds=1)
            return await super().current_version(page_id)

    worker = ContentSyncWorker(factory, RacingSource(_page(article, edited_at), _MARKDOWN), FakeMediaArchive())

    assert await worker.run_once() is True

    state = await ContentSyncRequestService(factory).get_article_state(article.id)
    run = await ContentSyncRequestService(factory).get_run(article.id, accepted.run.id)
    assert state is not None and run is not None
    assert state.current_snapshot_id is None
    assert state.status == ContentSyncStatus.FAILED
    assert run.error_code == "SOURCE_CHANGED"


@pytest.mark.anyio
async def test_retry_reuses_an_identical_immutable_snapshot(db_session) -> None:  # type: ignore[no-untyped-def]
    edited_at = datetime.now(tz=UTC)
    article = _article(edited_at)
    db_session.add(article)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    service = ContentSyncRequestService(factory)
    source = FakeSource(_page(article, edited_at), _MARKDOWN)
    await service.request(article.id)
    await ContentSyncWorker(factory, source, FakeMediaArchive()).run_once()
    first = await service.get_article_state(article.id)
    assert first is not None and first.current_snapshot_id is not None
    async with factory.begin() as session:
        persisted = await session.get(Article, article.id)
        assert persisted is not None
        persisted.content_sync_status = ContentSyncStatus.FAILED
        persisted.content_sync_error = "对象存储暂时不可用"

    accepted = await service.request(article.id)
    await ContentSyncWorker(factory, source, FakeMediaArchive()).run_once()

    second = await service.get_article_state(article.id)
    run = await service.get_run(article.id, accepted.run.id)
    async with factory() as session:
        snapshot_count = await session.scalar(select(func.count(ContentSnapshot.id)))
    assert second is not None and run is not None
    assert second.current_snapshot_id == first.current_snapshot_id
    assert second.status == ContentSyncStatus.SYNCED
    assert run.status == SyncRunStatus.SUCCEEDED
    assert snapshot_count == 1


_MARKDOWN = "正文 ![图](https://notion.so/image)"


def _article(edited_at: datetime) -> Article:
    page_id = str(uuid4())
    return Article(
        id=uuid4(),
        notion_page_id=page_id,
        notion_url=f"https://www.notion.so/{page_id}",
        title="旧标题",
        notion_status="待发布",
        automation_status="未开始",
        notion_last_edited_at=edited_at,
        last_synced_at=edited_at,
    )


def _page(article: Article, edited_at: datetime) -> MappedNotionPage:
    return MappedNotionPage(
        page_id=article.notion_page_id,
        url=article.notion_url,
        title="新标题",
        status="待发布",
        automation_status="未开始",
        target_channels=["个人博客", "微信公众号"],
        planned_raw=None,
        categories=["架构"],
        summary="统一快照",
        cover=NotionFile("cover.png", "https://notion.so/cover"),
        last_edited_at=edited_at,
    )
