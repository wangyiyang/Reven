from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from reven.articles.models import Article
from reven.content_sync.domain import SyncRunStatus, SyncStage
from reven.content_sync.models import ContentSyncRun
from reven.content_sync.repository import ContentSyncRepository
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest.mark.anyio
async def test_claim_allows_only_one_global_content_sync_worker(db_session) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(tz=UTC)
    articles = [_article(now), _article(now)]
    db_session.add_all(articles)
    await db_session.flush()
    db_session.add_all(ContentSyncRun(article_id=item.id, next_attempt_at=now) for item in articles)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async with factory.begin() as session:
        first = await ContentSyncRepository(session).claim_next(lease_seconds=120)
    async with factory.begin() as session:
        second = await ContentSyncRepository(session).claim_next(lease_seconds=120)

    assert first is not None
    assert second is None


@pytest.mark.anyio
async def test_claim_clears_stale_progress_before_a_retry(db_session) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(tz=UTC)
    article = _article(now)
    run = ContentSyncRun(
        article_id=article.id,
        status=SyncRunStatus.WAITING,
        stage=SyncStage.WAITING,
        progress_current=2,
        progress_total=4,
        current_media="旧附件.pdf",
        error_stage=SyncStage.DOWNLOADING_MEDIA,
        error_code="MEDIA_DOWNLOAD_FAILED",
        error_message="下载失败",
        error_media="旧附件.pdf",
        retryable=True,
        next_attempt_at=now,
    )
    db_session.add_all([article, run])
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async with factory.begin() as session:
        claim = await ContentSyncRepository(session).claim_next(lease_seconds=120)
    async with factory() as session:
        persisted = await session.get(ContentSyncRun, run.id)

    assert claim is not None
    assert persisted is not None
    assert (persisted.progress_current, persisted.progress_total, persisted.current_media) == (0, 0, None)
    assert (persisted.error_stage, persisted.error_code, persisted.error_message, persisted.error_media) == (
        None,
        None,
        None,
        None,
    )


def _article(now: datetime) -> Article:
    page_id = str(uuid4())
    return Article(
        id=uuid4(),
        notion_page_id=page_id,
        notion_url=f"https://www.notion.so/{page_id}",
        title="串行同步",
        notion_status="待发布",
        notion_last_edited_at=now,
        last_synced_at=now + timedelta(microseconds=1),
    )
