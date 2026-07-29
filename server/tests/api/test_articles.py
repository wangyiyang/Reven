import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from reven.articles.models import Article
from reven.articles.query import ARTICLE_DETAIL_JOB_LIMIT
from reven.jobs.models import PublicationJob
from reven.jobs.repository import compute_target_channels_hash
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_list_articles_supports_filters_sorting_and_pagination(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    now = datetime.now(tz=UTC)

    async def seed() -> None:
        async with factory.begin() as session:
            session.add_all(
                [
                    _article("测试稿件", now, planned_at=now),
                    _article("不匹配", now + timedelta(minutes=1), channels=["个人博客"]),
                ]
            )

    asyncio.run(seed())
    response = client.get(
        "/api/articles",
        params={"status": "待发布", "channel": "微信公众号", "query": "测试"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["title"] == "测试稿件"
    assert response.json()["items"][0]["cover_valid"] is True
    assert response.json()["items"][0]["last_synced_at"] is not None


def test_detail_exposes_only_safe_results_and_wechat_html_only_on_job(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    article, job = asyncio.run(_seed_pair(factory, status="已完成", blog_status="已上线"))
    job.blog_result = {
        "article_url": "https://example.com/post",
        "commit_sha": "a" * 40,
        "operation": {"token": "secret"},
    }
    asyncio.run(_merge(factory, job))

    article_response = client.get(f"/api/articles/{article.id}")
    job_response = client.get(f"/api/articles/{article.id}/jobs/{job.id}")

    assert article_response.status_code == 200
    assert "wechat_html" not in article_response.json()
    assert "operation" not in article_response.json()["blog"]["result"]
    assert job_response.json()["wechat_html"] == "<p>wechat</p>"
    assert "source_markdown" not in job_response.json()


def test_list_exposes_latest_channel_statuses(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    article, _job = asyncio.run(_seed_pair(factory, status="处理中", blog_status="构建中"))

    payload = client.get("/api/articles").json()
    item = next(value for value in payload["items"] if value["id"] == str(article.id))

    assert item["blog_status"] == "构建中"
    assert item["wechat_status"] == "草稿已生成"


def test_preview_uses_injected_latest_source_service_without_state_write(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    article = _article("预览", datetime.now(tz=UTC))
    asyncio.run(_merge(factory, article))

    response = client.post(f"/api/articles/{article.id}/preview/wechat")

    assert response.status_code == 200
    assert response.json() == {"html": f"<p>{article.notion_page_id}</p>"}


def test_article_detail_bounds_recent_job_history(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    article = _article("历史", datetime.now(tz=UTC))
    asyncio.run(_seed_job_history(factory, article, ARTICLE_DETAIL_JOB_LIMIT + 3))

    payload = client.get(f"/api/articles/{article.id}").json()

    assert len(payload["jobs"]) == ARTICLE_DETAIL_JOB_LIMIT
    assert payload["jobs_total"] == ARTICLE_DETAIL_JOB_LIMIT + 3
    assert payload["jobs_has_more"] is True
    assert payload["jobs"][0]["content_hash"] == f"{ARTICLE_DETAIL_JOB_LIMIT + 2:064x}"


def _article(
    title: str,
    edited_at: datetime,
    *,
    planned_at: datetime | None = None,
    channels: list[str] | None = None,
) -> Article:
    return Article(
        id=uuid4(),
        notion_page_id=str(uuid4()),
        notion_url="https://www.notion.so/page",
        title=title,
        notion_status="待发布",
        automation_status="等待中",
        target_channels=channels or ["个人博客", "微信公众号"],
        planned_at=planned_at,
        cover_metadata={"name": "cover", "url": "https://signed.example/secret"},
        notion_metadata={"summary": "摘要"},
        notion_last_edited_at=edited_at,
        last_error=None,
        last_synced_at=edited_at,
    )


async def _seed_pair(
    factory: async_sessionmaker,
    *,
    status: str,
    blog_status: str,
) -> tuple[Article, PublicationJob]:
    now = datetime.now(tz=UTC)
    article = _article("动作", now)
    job = PublicationJob(
        id=uuid4(),
        article_id=article.id,
        content_hash="b" * 64,
        target_channels=["个人博客", "微信公众号"],
        target_channels_hash=compute_target_channels_hash(["个人博客", "微信公众号"]),
        source_markdown="# source",
        snapshot_metadata={},
        wechat_html="<p>wechat</p>",
        overall_status=status,
        blog_status=blog_status,
        wechat_status="草稿已生成",
        scheduled_at=now,
    )
    async with factory.begin() as session:
        session.add_all([article, job])
    return article, job


async def _merge(factory: async_sessionmaker, value: object) -> None:
    async with factory.begin() as session:
        await session.merge(value)


async def _seed_job_history(
    factory: async_sessionmaker,
    article: Article,
    count: int,
) -> None:
    now = datetime.now(tz=UTC)
    async with factory.begin() as session:
        session.add(article)
        for index in range(count):
            channels = ["个人博客"]
            session.add(
                PublicationJob(
                    article_id=article.id,
                    content_hash=f"{index:064x}",
                    target_channels=channels,
                    target_channels_hash=compute_target_channels_hash(channels),
                    snapshot_metadata={},
                    overall_status="已完成",
                    blog_status="已上线",
                    wechat_status="待处理",
                    scheduled_at=now,
                    created_at=now + timedelta(seconds=index),
                    updated_at=now + timedelta(seconds=index),
                )
            )
