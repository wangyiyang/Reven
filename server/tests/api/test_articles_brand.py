"""稿件级品牌动作端点：重新生成任务、封面选择。"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from reven.articles.models import Article
from reven.brand.domain import BrandAssetPurpose
from reven.brand.models import BrandAsset

pytestmark = pytest.mark.anyio


async def _seed_article(factory, channels: list[str]) -> Article:  # type: ignore[no-untyped-def]
    now = datetime.now(tz=UTC)
    article = Article(
        notion_page_id=str(uuid4()),
        notion_url="https://notion.so/page",
        title="标题",
        notion_status="待发布",
        automation_status="未开始",
        target_channels=channels,
        notion_last_edited_at=now,
        last_synced_at=now,
    )
    async with factory.begin() as session:
        session.add(article)
    return article


async def _seed_asset(factory, *, purpose: str = BrandAssetPurpose.COVER, enabled: bool = True) -> BrandAsset:  # type: ignore[no-untyped-def]
    asset = BrandAsset(
        purpose=purpose,
        label="封面素材",
        enabled=enabled,
        storage_key=f"brand/{uuid4()}.png",
        public_url=f"https://cdn.example.com/{uuid4()}.png",
        sha256=f"{uuid4().hex}{uuid4().hex}",
        mime_type="image/png",
        byte_size=10,
    )
    async with factory.begin() as session:
        session.add(asset)
    return asset


async def test_regenerate_creates_waiting_job_idempotently(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    article = await _seed_article(factory, ["个人博客", "微信公众号"])

    first = client.post(f"/api/articles/{article.id}/jobs")
    assert first.status_code == 200, first.text
    second = client.post(f"/api/articles/{article.id}/jobs")
    assert second.status_code == 200
    assert second.json()["job_id"] == first.json()["job_id"]  # 幂等复用未开始的等待任务

    async with factory.begin() as session:
        from reven.jobs.models import PublicationJob

        job = await session.get(PublicationJob, first.json()["job_id"])
        assert job is not None
        assert job.overall_status == "等待中"
        assert job.content_hash is None
        assert job.brand_binding_key == "legacy"  # 绑定发生在准备冻结时


async def test_regenerate_unknown_article_404(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    response = client.post(f"/api/articles/{uuid4()}/jobs")
    assert response.status_code == 404


async def test_cover_selection_roundtrip(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    article = await _seed_article(factory, ["个人博客"])
    asset = await _seed_asset(factory)

    selected = client.post(f"/api/articles/{article.id}/cover", json={"asset_id": str(asset.id)})
    assert selected.status_code == 200, selected.text

    detail = client.get(f"/api/articles/{article.id}")
    assert detail.status_code == 200
    assert detail.json()["selected_cover_asset_id"] == str(asset.id)

    cleared = client.post(f"/api/articles/{article.id}/cover", json={"asset_id": None})
    assert cleared.status_code == 200
    detail = client.get(f"/api/articles/{article.id}")
    assert detail.json()["selected_cover_asset_id"] is None


async def test_cover_selection_rejects_unavailable_or_wrong_purpose(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    article = await _seed_article(factory, ["个人博客"])
    disabled = await _seed_asset(factory, enabled=False)
    qrcode = await _seed_asset(factory, purpose=BrandAssetPurpose.QRCODE)

    assert client.post(f"/api/articles/{article.id}/cover", json={"asset_id": str(disabled.id)}).status_code == 409
    assert client.post(f"/api/articles/{article.id}/cover", json={"asset_id": str(qrcode.id)}).status_code == 409
    assert client.post(f"/api/articles/{article.id}/cover", json={"asset_id": str(uuid4())}).status_code == 409
