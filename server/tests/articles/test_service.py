from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from reven.articles.repository import ArticleRepository
from reven.content_sync.domain import ContentSyncStatus, SyncRunStatus
from reven.content_sync.models import ContentSnapshot, ContentSyncRun
from reven.integrations.notion.models import MappedNotionPage, NotionFile


def _mapped_page(*, title: str = "首版标题", edited_at: datetime | None = None) -> MappedNotionPage:
    return MappedNotionPage(
        page_id="11111111-1111-1111-1111-111111111111",
        url="https://www.notion.so/11111111111111111111111111111111",
        title=title,
        status="待发布",
        automation_status=None,
        target_channels=["个人博客"],
        planned_raw="2026-08-01",
        categories=["工程"],
        summary="摘要",
        cover=None,
        last_edited_at=edited_at or datetime(2026, 7, 29, tzinfo=UTC),
    )


@pytest.mark.anyio
async def test_upsert_from_notion_is_idempotent(db_session) -> None:  # type: ignore[no-untyped-def]
    repository = ArticleRepository(db_session)

    first = await repository.upsert_from_notion(_mapped_page())
    second = await repository.upsert_from_notion(_mapped_page(title="修订标题"))

    assert second.id == first.id
    assert second.title == "修订标题"
    assert second.planned_at == datetime(2026, 8, 1, 0, 1, tzinfo=UTC)
    assert second.last_synced_at.tzinfo is not None


@pytest.mark.anyio
async def test_upsert_serializes_cover_expiry_as_json(db_session) -> None:  # type: ignore[no-untyped-def]
    page = _mapped_page()
    page = MappedNotionPage(
        **{
            **page.__dict__,
            "cover": NotionFile(
                name="cover.png",
                url="https://example.com/cover.png",
                expiry_time=datetime(2026, 7, 30, tzinfo=UTC),
            ),
        }
    )

    article = await ArticleRepository(db_session).upsert_from_notion(page)
    await db_session.commit()

    assert article.cover_metadata["expiry_time"] == "2026-07-30T00:00:00+00:00"


@pytest.mark.anyio
async def test_upsert_marks_current_snapshot_stale_when_notion_version_changes(db_session) -> None:  # type: ignore[no-untyped-def]
    repository = ArticleRepository(db_session)
    original = _mapped_page()
    article = await repository.upsert_from_notion(original)
    run = ContentSyncRun(
        id=uuid4(),
        article_id=article.id,
        status=SyncRunStatus.SUCCEEDED,
        next_attempt_at=original.last_edited_at,
    )
    db_session.add(run)
    await db_session.flush()
    snapshot = ContentSnapshot(
        id=uuid4(),
        article_id=article.id,
        sync_run_id=run.id,
        source_last_edited_at=original.last_edited_at,
        title=original.title,
        source_markdown="# source",
        portable_markdown="# source",
        content_hash="a" * 64,
        snapshot_metadata={},
    )
    db_session.add(snapshot)
    await db_session.flush()
    article.current_snapshot_id = snapshot.id
    article.content_sync_status = ContentSyncStatus.SYNCED

    changed = _mapped_page(edited_at=original.last_edited_at + timedelta(minutes=1))
    await repository.upsert_from_notion(changed)

    assert article.content_sync_status == ContentSyncStatus.STALE
    assert article.content_sync_error == "Notion 内容已发生变化"
    assert article.current_snapshot_id == snapshot.id
