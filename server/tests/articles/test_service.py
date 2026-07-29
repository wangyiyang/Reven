from datetime import UTC, datetime

import pytest
from reven.articles.repository import ArticleRepository
from reven.integrations.notion.models import MappedNotionPage, NotionFile


def _mapped_page(*, title: str = "首版标题") -> MappedNotionPage:
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
        last_edited_at=datetime(2026, 7, 29, tzinfo=UTC),
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
