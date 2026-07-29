from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from reven.articles.models import Article
from reven.domain import JobStatus
from reven.integrations.models import Integration
from reven.jobs.models import PublicationJob
from reven.jobs.repository import compute_target_channels_hash
from reven.jobs.service import PublicationJobService
from reven.publishing.assets import MaterializedAsset, MaterializedAssets
from reven.publishing.snapshot import build_snapshot
from sqlalchemy.ext.asyncio import async_sessionmaker


def test_target_channels_hash_is_order_independent() -> None:
    assert compute_target_channels_hash(["个人博客", "微信公众号"]) == compute_target_channels_hash(
        ["微信公众号", "个人博客"]
    )


def _page(*, cover: bool = True) -> dict[str, Any]:
    now = datetime.now(tz=UTC).isoformat()
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "url": "https://notion.so/page",
        "last_edited_time": now,
        "properties": {
            "标题": {"type": "title", "title": [{"plain_text": "标题"}]},
            "状态": {"type": "status", "status": {"name": "待发布"}},
            "目标渠道": {"type": "multi_select", "multi_select": [{"name": "个人博客"}]},
            "摘要": {"type": "rich_text", "rich_text": [{"plain_text": "摘要"}]},
            "封面": {
                "type": "files",
                "files": (
                    [{"type": "external", "name": "cover", "external": {"url": "https://example.com/cover.png"}}]
                    if cover
                    else []
                ),
            },
        },
    }


class FakeNotion:
    def __init__(self, page: dict[str, Any]) -> None:
        self.page = page
        self.updates: list[dict[str, Any]] = []

    async def retrieve_page(self, page_id: str) -> dict[str, Any]:
        del page_id
        return self.page

    async def retrieve_page_markdown(self, page_id: str) -> str:
        del page_id
        return "正文"

    async def update_page(self, page_id: str, *, properties: dict[str, Any]) -> dict[str, Any]:
        del page_id
        self.updates.append(properties)
        return {}


class FailingUpdateNotion(FakeNotion):
    async def update_page(self, page_id: str, *, properties: dict[str, Any]) -> dict[str, Any]:
        del page_id, properties
        raise RuntimeError("secret=https://signed.example/?token=sensitive")


class FailingRetrieveNotion(FakeNotion):
    async def retrieve_page(self, page_id: str) -> dict[str, Any]:
        del page_id
        raise RuntimeError("token=sensitive")


class FakeMaterializer:
    async def materialize(self, job_id: str, image_urls: list[str], cover_url: str) -> MaterializedAssets:
        del job_id, image_urls, cover_url
        cover = MaterializedAsset("cover", Path("/tmp/cover.png"), "b" * 64, "image/png", 10)
        return MaterializedAssets((), cover)


async def _seed_job(db_session) -> PublicationJob:  # type: ignore[no-untyped-def]
    now = datetime.now(tz=UTC)
    article = Article(
        notion_page_id="11111111-1111-1111-1111-111111111111",
        notion_url="https://notion.so/page",
        title="旧标题",
        notion_status="待发布",
        automation_status="等待中",
        target_channels=["个人博客"],
        notion_last_edited_at=now,
        last_synced_at=now,
    )
    db_session.add(article)
    db_session.add(
        Integration(
            provider="github",
            encrypted_secret="encrypted",
            connection_status="连接正常",
            last_tested_at=now,
        )
    )
    await db_session.flush()
    job = PublicationJob(
        article_id=article.id,
        content_hash=None,
        target_channels=["个人博客"],
        target_channels_hash=compute_target_channels_hash(["个人博客"]),
        overall_status=JobStatus.WAITING,
        blog_status="待处理",
        wechat_status="待处理",
        scheduled_at=now,
    )
    db_session.add(job)
    await db_session.commit()
    return job


@pytest.mark.anyio
async def test_prepare_freezes_latest_page_and_marks_processing(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    notion = FakeNotion(_page())
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    result = await PublicationJobService(factory, notion, FakeMaterializer()).prepare(job.id)

    assert result.job_id == job.id
    assert result.reused is False
    await db_session.refresh(job)
    assert job.content_hash is not None
    assert job.source_markdown == "正文"
    assert job.overall_status == JobStatus.PROCESSING
    assert notion.updates[-1]["自动化状态"]["select"]["name"] == "处理中"


@pytest.mark.anyio
async def test_prepare_missing_cover_blocks_job_and_writes_reason(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    notion = FakeNotion(_page(cover=False))
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    result = await PublicationJobService(factory, notion, FakeMaterializer()).prepare(job.id)

    assert result.blocked is True
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.BLOCKED
    assert notion.updates[-1]["自动化状态"]["select"]["name"] == "阻塞"


@pytest.mark.anyio
async def test_notion_write_failure_rolls_back_freeze_without_leaking_detail(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    notion = FailingUpdateNotion(_page())
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    with pytest.raises(Exception) as caught:
        await PublicationJobService(factory, notion, FakeMaterializer()).prepare(job.id)

    assert "sensitive" not in str(caught.value)
    await db_session.refresh(job)
    assert job.content_hash is None
    assert job.overall_status == JobStatus.WAITING


@pytest.mark.anyio
async def test_prepare_reuses_existing_frozen_job(db_session) -> None:  # type: ignore[no-untyped-def]
    current = await _seed_job(db_session)
    snapshot = build_snapshot(
        "正文",
        image_sha256=(),
        cover_sha256="b" * 64,
        title="标题",
        summary="摘要",
    )
    existing = PublicationJob(
        article_id=current.article_id,
        content_hash=snapshot.content_hash,
        target_channels=["个人博客"],
        target_channels_hash=compute_target_channels_hash(["个人博客"]),
        source_markdown=snapshot.markdown,
        overall_status=JobStatus.COMPLETED,
        blog_status="已上线",
        wechat_status="待处理",
        scheduled_at=datetime.now(tz=UTC),
    )
    db_session.add(existing)
    await db_session.commit()
    notion = FakeNotion(_page())
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    result = await PublicationJobService(factory, notion, FakeMaterializer()).prepare(current.id)

    assert result.job_id == existing.id
    assert result.reused is True
    await db_session.refresh(current)
    assert current.overall_status == JobStatus.CANCELLED


@pytest.mark.anyio
async def test_source_refresh_failure_blocks_with_redacted_reason(db_session) -> None:  # type: ignore[no-untyped-def]
    job = await _seed_job(db_session)
    notion = FailingRetrieveNotion(_page())
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    result = await PublicationJobService(factory, notion, FakeMaterializer()).prepare(job.id)

    assert result.blocked is True
    await db_session.refresh(job)
    assert job.overall_status == JobStatus.BLOCKED
    assert "sensitive" not in str(result.validation)
