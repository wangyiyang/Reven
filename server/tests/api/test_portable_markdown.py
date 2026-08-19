import asyncio
import base64
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import respx
from reven.articles.models import Article
from reven.config import get_settings
from reven.content_sync.domain import ContentSyncStatus, SyncRunStatus, SyncStage
from reven.content_sync.models import ContentSnapshot, ContentSyncRun
from reven.integrations.models import Integration
from reven.security.secrets import SecretBox


@pytest.fixture(autouse=True)
def _clear_settings_cache():  # type: ignore[no-untyped-def]
    yield
    get_settings.cache_clear()


def test_copy_markdown_returns_the_current_portable_snapshot_without_reading_notion_body(
    workbench,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    version = datetime(2026, 8, 11, 1, 2, tzinfo=UTC)
    article = asyncio.run(_seed_current_snapshot(factory, version))
    _configure_notion(factory, monkeypatch)
    with respx.mock(assert_all_called=True) as notion_api:
        page_request = notion_api.get(f"https://api.notion.com/v1/pages/{article.notion_page_id}").mock(
            return_value=_notion_page_response(article, version)
        )
        response = client.post(f"/api/articles/{article.id}/portable-markdown")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "markdown": "# 可移植稿件\n\n![架构图](https://assets.example/diagram.png)\n\n"
        "[YouTube](https://youtube.com/watch?v=1)\n"
    }
    assert page_request.call_count == 1


def test_copy_markdown_blocks_the_old_snapshot_when_notion_has_changed(workbench, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    snapshot_version = datetime(2026, 8, 11, 1, 2, tzinfo=UTC)
    current_version = datetime(2026, 8, 11, 1, 3, tzinfo=UTC)
    article = asyncio.run(_seed_current_snapshot(factory, snapshot_version))
    _configure_notion(factory, monkeypatch)

    with respx.mock(assert_all_called=True) as notion_api:
        notion_api.get(f"https://api.notion.com/v1/pages/{article.notion_page_id}").mock(
            return_value=_notion_page_response(article, current_version)
        )
        response = client.post(f"/api/articles/{article.id}/portable-markdown")

    assert response.status_code == 409
    assert response.json() == {
        "code": "SNAPSHOT_STALE",
        "message": "Notion 内容已变化，请重新同步",
    }
    content_sync = client.get(f"/api/articles/{article.id}").json()["content_sync"]
    assert content_sync["status"] == "已过期"
    assert content_sync["outputs_enabled"] is False


def test_copy_markdown_does_not_fall_back_to_an_old_snapshot_after_sync_failure(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    version = datetime(2026, 8, 11, 1, 2, tzinfo=UTC)
    article = asyncio.run(_seed_current_snapshot(factory, version))
    asyncio.run(_mark_sync_failed(factory, article.id))

    response = client.post(f"/api/articles/{article.id}/portable-markdown")

    assert response.status_code == 409
    assert response.json() == {
        "code": "SNAPSHOT_UNAVAILABLE",
        "message": "稿件没有可输出的有效快照",
    }
    assert "可移植稿件" not in response.text


async def _seed_current_snapshot(factory, version: datetime) -> Article:  # type: ignore[no-untyped-def]
    article = Article(
        id=uuid4(),
        notion_page_id=str(uuid4()),
        notion_url="https://www.notion.so/page",
        title="可移植稿件",
        notion_status="待发布",
        automation_status="等待中",
        notion_last_edited_at=version,
        last_synced_at=version,
        content_sync_status=ContentSyncStatus.SYNCED,
    )
    run = ContentSyncRun(
        article_id=article.id,
        status=SyncRunStatus.SUCCEEDED,
        stage=SyncStage.COMPLETED,
        source_last_edited_at=version,
        next_attempt_at=version,
        finished_at=version,
    )
    async with factory.begin() as session:
        session.add_all([article, run])
        await session.flush()
        snapshot = ContentSnapshot(
            article_id=article.id,
            sync_run_id=run.id,
            source_last_edited_at=version,
            title=article.title,
            source_markdown="正文",
            portable_markdown=(
                "# 可移植稿件\n\n![架构图](https://assets.example/diagram.png)\n\n"
                "[YouTube](https://youtube.com/watch?v=1)\n"
            ),
            content_hash="a" * 64,
            synced_at=version,
            created_at=version,
        )
        session.add(snapshot)
        await session.flush()
        article.current_snapshot_id = snapshot.id
    return article


async def _mark_sync_failed(factory, article_id) -> None:  # type: ignore[no-untyped-def]
    async with factory.begin() as session:
        article = await session.get(Article, article_id)
        assert article is not None
        article.content_sync_status = ContentSyncStatus.FAILED
        article.content_sync_error = "最新版本同步失败"


def _configure_notion(factory, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    master_key = base64.urlsafe_b64encode(b"m" * 32).decode()
    monkeypatch.setenv("REVEN_MASTER_KEY", master_key)
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")
    get_settings.cache_clear()

    async def seed() -> None:
        async with factory.begin() as session:
            session.add(
                Integration(
                    provider="notion",
                    public_config={"data_source_id": "source-id"},
                    encrypted_secret=SecretBox.from_base64(master_key).encrypt({"token": "notion-token"}),
                )
            )

    asyncio.run(seed())


def _notion_page_response(article: Article, version: datetime):  # type: ignore[no-untyped-def]
    import httpx

    return httpx.Response(
        200,
        json={
            "id": article.notion_page_id,
            "url": article.notion_url,
            "last_edited_time": version.isoformat(),
            "properties": {
                "标题": {"type": "title", "title": [{"plain_text": article.title}]},
                "状态": {"type": "status", "status": {"name": article.notion_status}},
            },
        },
    )
