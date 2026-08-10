from datetime import UTC, datetime
from uuid import uuid4

import pytest
from reven.articles.models import Article
from reven.content_sync.domain import ContentSyncStatus, SyncRunStatus, SyncStage
from reven.content_sync.models import ContentSnapshot, ContentSyncRun
from reven.content_sync.requests import ContentSyncRequestService
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest.mark.anyio
async def test_duplicate_requests_share_the_active_sync_run(db_session) -> None:  # type: ignore[no-untyped-def]
    article = _article()
    db_session.add(article)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    service = ContentSyncRequestService(factory)

    first = await service.request(article.id)
    second = await service.request(article.id)

    assert first.created is True
    assert second.created is False
    assert second.run.id == first.run.id
    assert second.run.status == SyncRunStatus.WAITING
    state = await service.get_article_state(article.id)
    assert state is not None
    assert state.status == ContentSyncStatus.SYNCING
    assert state.latest_run_id == first.run.id


@pytest.mark.anyio
async def test_request_reuses_success_only_after_confirming_the_live_notion_version(db_session) -> None:  # type: ignore[no-untyped-def]
    article = _article()
    run = ContentSyncRun(
        id=uuid4(),
        article_id=article.id,
        status=SyncRunStatus.SUCCEEDED,
        stage=SyncStage.COMPLETED,
        next_attempt_at=article.notion_last_edited_at,
    )
    db_session.add_all([article, run])
    await db_session.flush()
    snapshot = ContentSnapshot(
        id=uuid4(),
        article_id=article.id,
        sync_run_id=run.id,
        source_last_edited_at=article.notion_last_edited_at,
        title=article.title,
        source_markdown="正文",
        portable_markdown="# 标题\n\n正文",
        content_hash="a" * 64,
    )
    db_session.add(snapshot)
    await db_session.flush()
    article.current_snapshot_id = snapshot.id
    article.content_sync_status = ContentSyncStatus.SYNCED
    await db_session.commit()

    class VersionSource:
        async def current_version(self, page_id: str) -> datetime:
            assert page_id == article.notion_page_id
            return article.notion_last_edited_at

    service = ContentSyncRequestService(
        async_sessionmaker(db_session.bind, expire_on_commit=False),
        VersionSource(),
    )

    result = await service.request(article.id)

    assert result.created is False
    assert result.run.id == run.id


def _article() -> Article:
    now = datetime.now(tz=UTC)
    return Article(
        id=uuid4(),
        notion_page_id=str(uuid4()),
        notion_url="https://www.notion.so/page",
        title="原子同步",
        notion_status="待发布",
        automation_status="未开始",
        notion_last_edited_at=now,
        last_synced_at=now,
    )
