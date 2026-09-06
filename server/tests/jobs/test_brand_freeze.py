"""品牌绑定在准备冻结阶段的落库行为。"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from reven.articles.actions import ArticleActionService
from reven.articles.models import Article
from reven.brand.domain import BrandAssetPurpose
from reven.brand.models import BrandAsset, BrandVersion, ChannelTemplateVersion
from reven.domain import JobStatus
from reven.integrations.models import Integration
from reven.jobs.models import PublicationJob
from reven.jobs.repository import compute_target_channels_hash
from reven.jobs.service import PublicationJobService
from reven.publishing.assets import MaterializedAsset, MaterializedAssets
from sqlalchemy.ext.asyncio import async_sessionmaker

from .test_service import FakeNotion, _page


class UrlEchoMaterializer:
    """按 URL 确定性生成素材记录（不落盘），用于冻结绑定测试。"""

    def __init__(self) -> None:
        self.urls: list[str] = []

    async def materialize(self, job_id: str, image_urls: list[str], cover_url: str | None) -> MaterializedAssets:
        del job_id
        self.urls.extend(image_urls)
        images = tuple(
            MaterializedAsset(
                url,
                Path(f"/tmp/echo-{index}.png"),
                hashlib.sha256(url.encode()).hexdigest(),
                "image/png",
                10,
            )
            for index, url in enumerate(image_urls)
        )
        cover = (
            MaterializedAsset(cover_url, Path("/tmp/echo-cover.png"), "b" * 64, "image/png", 10)
            if cover_url is not None
            else None
        )
        return MaterializedAssets(images, cover)


async def _seed_article(db_session, channels: list[str]) -> Article:  # type: ignore[no-untyped-def]
    now = datetime.now(tz=UTC)
    article = Article(
        notion_page_id="11111111-1111-1111-1111-111111111111",
        notion_url="https://notion.so/page",
        title="旧标题",
        notion_status="待发布",
        automation_status="等待中",
        target_channels=channels,
        notion_last_edited_at=now,
        last_synced_at=now,
    )
    db_session.add(article)
    for provider in ("github", "wechat"):
        db_session.add(
            Integration(
                provider=provider,
                encrypted_secret="encrypted",
                connection_status="连接正常",
                last_tested_at=now,
            )
        )
    await db_session.flush()
    return article


async def _seed_waiting_job(db_session, article: Article, channels: list[str]) -> PublicationJob:  # type: ignore[no-untyped-def]
    job = PublicationJob(
        article_id=article.id,
        content_hash=None,
        target_channels=channels,
        target_channels_hash=compute_target_channels_hash(channels),
        overall_status=JobStatus.WAITING,
        blog_status="待处理",
        wechat_status="待处理",
        scheduled_at=datetime.now(tz=UTC),
    )
    db_session.add(job)
    await db_session.commit()
    return job


async def _seed_published_brand(db_session, *, version: int = 1, author: str = "王一羊") -> BrandVersion:  # type: ignore[no-untyped-def]
    brand = BrandVersion(
        version=version,
        status="已发布",
        source="手工创建",
        payload={
            "name": "翊行代码",
            "default_author": author,
            "colors": {"primary": "#0F4C81"},
            "fonts": {"body": "sans-serif"},
        },
        published_at=datetime.now(tz=UTC),
    )
    db_session.add(brand)
    await db_session.flush()
    return brand


def _page_with_channels(channels: list[str]) -> dict[str, Any]:
    page = _page()
    page["properties"]["目标渠道"] = {
        "type": "multi_select",
        "multi_select": [{"name": channel} for channel in channels],
    }
    return page


@pytest.mark.anyio
async def test_freeze_binds_published_brand(db_session) -> None:  # type: ignore[no-untyped-def]
    article = await _seed_article(db_session, ["个人博客"])
    brand = await _seed_published_brand(db_session)
    job = await _seed_waiting_job(db_session, article, ["个人博客"])
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    result = await PublicationJobService(factory, FakeNotion(_page()), UrlEchoMaterializer()).prepare(job.id)

    assert result.blocked is False
    await db_session.refresh(job)
    assert job.brand_version_id == brand.id
    assert job.brand_binding_key == hashlib.sha256(f"{brand.id}:None:None".encode()).hexdigest()
    brand_meta = job.snapshot_metadata.get("brand")
    assert isinstance(brand_meta, dict)
    assert brand_meta["version_fingerprint"]["brand_version"] == 1
    assert job.snapshot_metadata["blog_fields"] == {"author": "王一羊", "og_image_url": None}


@pytest.mark.anyio
async def test_freeze_without_brand_keeps_legacy_binding(db_session) -> None:  # type: ignore[no-untyped-def]
    article = await _seed_article(db_session, ["个人博客"])
    job = await _seed_waiting_job(db_session, article, ["个人博客"])
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    await PublicationJobService(factory, FakeNotion(_page()), UrlEchoMaterializer()).prepare(job.id)

    await db_session.refresh(job)
    assert job.brand_version_id is None
    assert job.brand_binding_key == "legacy"
    assert "brand" not in job.snapshot_metadata


@pytest.mark.anyio
async def test_wechat_template_footer_asset_frozen_with_snapshot(db_session) -> None:  # type: ignore[no-untyped-def]
    channels = ["个人博客", "微信公众号"]
    article = await _seed_article(db_session, channels)
    brand = await _seed_published_brand(db_session)
    asset = BrandAsset(
        purpose=BrandAssetPurpose.QRCODE,
        label="公众号二维码",
        storage_key="brand/qr.png",
        public_url="https://cdn.example.com/qr.png",
        sha256="d" * 64,
        mime_type="image/png",
        byte_size=10,
    )
    db_session.add(asset)
    await db_session.flush()
    db_session.add(
        ChannelTemplateVersion(
            channel="微信公众号",
            version=1,
            status="已发布",
            payload={
                "theme": {"primary_color": "#00E676"},
                "footer_modules": [{"key": "qr", "type": "image", "asset_id": str(asset.id), "enabled": True}],
            },
            published_at=datetime.now(tz=UTC),
        )
    )
    await db_session.flush()
    job = await _seed_waiting_job(db_session, article, channels)
    materializer = UrlEchoMaterializer()
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    page = _page_with_channels(channels)

    result = await PublicationJobService(factory, FakeNotion(page), materializer).prepare(job.id)

    assert result.blocked is False
    await db_session.refresh(job)
    assert job.wechat_template_version_id is not None
    assert materializer.urls == ["https://cdn.example.com/qr.png"]
    footer = job.snapshot_metadata.get("footer_assets")
    assert isinstance(footer, list) and len(footer) == 1
    entry = footer[0]
    assert entry["public_url"] == "https://cdn.example.com/qr.png"
    assert entry["sha256"] == hashlib.sha256(b"https://cdn.example.com/qr.png").hexdigest()
    assert entry["asset_id"] == str(asset.id)
    assert job.brand_version_id == brand.id


@pytest.mark.anyio
async def test_regenerate_after_brand_republish_creates_distinct_binding(db_session) -> None:  # type: ignore[no-untyped-def]
    article = await _seed_article(db_session, ["个人博客"])
    brand_v1 = await _seed_published_brand(db_session, version=1)
    job1 = await _seed_waiting_job(db_session, article, ["个人博客"])
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    notion = FakeNotion(_page())

    await PublicationJobService(factory, notion, UrlEchoMaterializer()).prepare(job1.id)
    await db_session.refresh(job1)
    assert job1.brand_version_id == brand_v1.id

    # 品牌发新版：v1 归档，v2 发布
    brand_v1.status = "已归档"
    brand_v2 = await _seed_published_brand(db_session, version=2)
    await db_session.commit()

    job2_id = await ArticleActionService(factory).regenerate(article.id)
    assert job2_id != job1.id
    await PublicationJobService(factory, notion, UrlEchoMaterializer()).prepare(job2_id)

    job2 = await db_session.get(PublicationJob, job2_id)
    assert job2 is not None
    assert job2.brand_version_id == brand_v2.id
    assert job2.brand_binding_key != job1.brand_binding_key
    # 两个不同绑定的冻结任务共存（追溯性）
    assert job1.content_hash == job2.content_hash


@pytest.mark.anyio
async def test_selected_cover_asset_overrides_notion_cover(db_session) -> None:  # type: ignore[no-untyped-def]
    article = await _seed_article(db_session, ["个人博客"])
    await _seed_published_brand(db_session)
    asset = BrandAsset(
        purpose=BrandAssetPurpose.COVER,
        label="选定封面",
        storage_key="brand/cover.png",
        public_url="https://cdn.example.com/selected-cover.png",
        sha256="e" * 64,
        mime_type="image/png",
        byte_size=10,
    )
    db_session.add(asset)
    await db_session.flush()
    article.selected_cover_asset_id = asset.id
    await db_session.commit()
    job = await _seed_waiting_job(db_session, article, ["个人博客"])
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    captured = UrlEchoMaterializer()

    class CaptureCover(UrlEchoMaterializer):
        async def materialize(self, job_id: str, image_urls: list[str], cover_url: str | None) -> MaterializedAssets:
            captured.cover_url = cover_url  # type: ignore[attr-defined]
            return await super().materialize(job_id, image_urls, cover_url)

    await PublicationJobService(factory, FakeNotion(_page()), CaptureCover()).prepare(job.id)

    assert captured.cover_url == "https://cdn.example.com/selected-cover.png"  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_wechat_store_resolves_brand_author_and_theme(db_session) -> None:  # type: ignore[no-untyped-def]
    """交付侧读取冻结绑定：品牌署名优先于集成配置，主题参数随任务数据下发。"""
    channels = ["个人博客", "微信公众号"]
    article = await _seed_article(db_session, channels)
    await _seed_published_brand(db_session, author="品牌署名")
    db_session.add(
        ChannelTemplateVersion(
            channel="微信公众号",
            version=1,
            status="已发布",
            payload={"theme": {"primary_color": "#00E676", "font_size": 17}},
            published_at=datetime.now(tz=UTC),
        )
    )
    await db_session.flush()
    job = await _seed_waiting_job(db_session, article, channels)
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    await PublicationJobService(factory, FakeNotion(_page_with_channels(channels)), UrlEchoMaterializer()).prepare(
        job.id
    )

    from reven.jobs.repository import JobClaim
    from reven.publishing.wechat.store import SqlAlchemyWeChatResultStore

    data = await SqlAlchemyWeChatResultStore(factory, author="集成署名").load(JobClaim(job.id, uuid4()))
    assert data["author"] == "品牌署名"
    brand = data["brand"]
    assert isinstance(brand, dict)
    assert brand["theme"] == {"primaryColor": "#00E676", "fontFamily": "sans-serif", "fontSize": 17}


@pytest.mark.anyio
async def test_cover_fallback_asset_used_when_notion_cover_missing(db_session) -> None:  # type: ignore[no-untyped-def]
    article = await _seed_article(db_session, ["个人博客"])
    await _seed_published_brand(db_session)
    fallback = BrandAsset(
        purpose=BrandAssetPurpose.COVER,
        label="默认封面",
        storage_key="brand/default-cover.png",
        public_url="https://cdn.example.com/default-cover.png",
        sha256="f" * 64,
        mime_type="image/png",
        byte_size=10,
    )
    db_session.add(fallback)
    await db_session.flush()
    db_session.add(
        ChannelTemplateVersion(
            channel="个人博客",
            version=1,
            status="已发布",
            payload={"author": "博客署名", "cover_fallback_asset_id": str(fallback.id)},
            published_at=datetime.now(tz=UTC),
        )
    )
    await db_session.commit()
    job = await _seed_waiting_job(db_session, article, ["个人博客"])
    factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)

    captured = UrlEchoMaterializer()

    class CaptureCover(UrlEchoMaterializer):
        async def materialize(self, job_id: str, image_urls: list[str], cover_url: str | None) -> MaterializedAssets:
            captured.cover_url = cover_url  # type: ignore[attr-defined]
            return await super().materialize(job_id, image_urls, cover_url)

    # Notion 页面无封面也能发布（回落素材兜底）
    result = await PublicationJobService(factory, FakeNotion(_page(cover=False)), CaptureCover()).prepare(job.id)

    assert result.blocked is False
    assert captured.cover_url == "https://cdn.example.com/default-cover.png"  # type: ignore[attr-defined]
    await db_session.refresh(job)
    assert job.snapshot_metadata["blog_fields"] == {"author": "博客署名", "og_image_url": None}
