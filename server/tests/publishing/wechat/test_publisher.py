from pathlib import Path
from uuid import uuid4

import pytest
from reven.integrations.wechat.models import WeChatTransientError
from reven.jobs.errors import BlockedPublishError
from reven.jobs.repository import JobClaim
from reven.publishing.assets import MaterializedAsset, MaterializedAssets
from reven.publishing.wechat.publisher import LeaseLost, WeChatPublisher


class FakeRenderer:
    async def render(self, markdown: str) -> str:
        return '<section><img src="reven-asset://image/1"></section>'


class FakeWeChat:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.draft_content = ""

    async def get_token(self) -> str:
        self.calls.append("get_token")
        return "token"

    async def upload_body_image(self, path: Path) -> str:
        self.calls.append("upload_body_image")
        return "https://mmbiz.qpic.cn/body"

    async def upload_cover_material(self, path: Path) -> str:
        self.calls.append("upload_cover_material")
        return "thumb-id"

    async def create_draft(self, payload: dict[str, object]) -> str:
        self.calls.append("create_draft")
        articles = payload["articles"]
        assert isinstance(articles, list)
        self.draft_content = str(articles[0]["content"])
        return "draft-media-id"


class FakeStore:
    def __init__(self, metadata: dict[str, object], result: dict[str, object] | None = None) -> None:
        self.metadata = metadata
        self.result = result or {}
        self.lease = True
        self.commits: list[str] = []

    async def load(self, claim: JobClaim):  # type: ignore[no-untyped-def]
        return {
            "source_markdown": "# title\n![x](reven-asset://image/1)",
            "snapshot_metadata": self.metadata,
            "wechat_result": self.result,
            "title": "title",
            "author": "author",
            "digest": "digest",
            "content_source_url": "",
        }

    async def assert_lease(self, claim: JobClaim) -> bool:
        return self.lease

    async def save_result(self, claim: JobClaim, patch: dict[str, object]) -> bool:
        if not self.lease:
            return False
        self.result.update(patch)
        self.commits.extend(patch)
        return True


def assets(tmp_path: Path) -> tuple[MaterializedAssets, dict[str, object]]:
    image = tmp_path / "image-1.png"
    cover = tmp_path / "cover.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    cover.write_bytes(b"\x89PNG\r\n\x1a\ncover")
    image_asset = MaterializedAsset("https://n/image", image, "a" * 64, "image/png", image.stat().st_size)
    cover_asset = MaterializedAsset("https://n/cover", cover, "b" * 64, "image/png", cover.stat().st_size)
    metadata = {
        "images": [{"ordinal": 1, "path": str(image), "sha256": "a" * 64}],
        "cover": {"path": str(cover), "sha256": "b" * 64},
        "cover_sha256": "b" * 64,
    }
    return MaterializedAssets((image_asset,), cover_asset), metadata


@pytest.mark.anyio
async def test_publish_uploads_body_images_before_creating_draft(tmp_path: Path) -> None:
    materialized, metadata = assets(tmp_path)
    store = FakeStore(metadata)
    wechat = FakeWeChat()
    publisher = WeChatPublisher(wechat, FakeRenderer(), store, assets_loader=lambda _: materialized)

    result = await publisher.publish(JobClaim(uuid4(), uuid4()))

    assert wechat.calls == [
        "get_token",
        "upload_body_image",
        "upload_cover_material",
        "create_draft",
    ]
    assert "reven-asset://" not in wechat.draft_content
    assert "mmbiz.qpic.cn" in wechat.draft_content
    assert result.media_id == "draft-media-id"


@pytest.mark.anyio
async def test_retry_reuses_uploaded_image_cover_and_media_id(tmp_path: Path) -> None:
    materialized, metadata = assets(tmp_path)
    saved = {
        "uploaded_images": {"a" * 64: "https://mmbiz.qpic.cn/body"},
        "thumb_media_id": "thumb-id",
        "media_id": "existing-id",
    }
    wechat = FakeWeChat()
    publisher = WeChatPublisher(
        wechat,
        FakeRenderer(),
        FakeStore(metadata, saved),
        assets_loader=lambda _: materialized,
    )

    result = await publisher.publish(JobClaim(uuid4(), uuid4()))

    assert result.media_id == "existing-id"
    assert wechat.calls == []


@pytest.mark.anyio
async def test_unknown_or_duplicate_image_index_is_blocked(tmp_path: Path) -> None:
    materialized, metadata = assets(tmp_path)

    class BadRenderer:
        async def render(self, markdown: str) -> str:
            return '<img src="reven-asset://image/2"><img src="reven-asset://image/2">'

    publisher = WeChatPublisher(FakeWeChat(), BadRenderer(), FakeStore(metadata), assets_loader=lambda _: materialized)
    with pytest.raises(BlockedPublishError):
        await publisher.publish(JobClaim(uuid4(), uuid4()))


@pytest.mark.anyio
async def test_lost_lease_stops_before_next_external_call(tmp_path: Path) -> None:
    materialized, metadata = assets(tmp_path)
    store = FakeStore(metadata)

    class LosingWeChat(FakeWeChat):
        async def upload_body_image(self, path: Path) -> str:
            result = await super().upload_body_image(path)
            store.lease = False
            return result

    wechat = LosingWeChat()
    publisher = WeChatPublisher(wechat, FakeRenderer(), store, assets_loader=lambda _: materialized)
    with pytest.raises(LeaseLost):
        await publisher.publish(JobClaim(uuid4(), uuid4()))
    assert wechat.calls == ["get_token", "upload_body_image"]


@pytest.mark.anyio
async def test_uncertain_draft_is_never_retried(tmp_path: Path) -> None:
    materialized, metadata = assets(tmp_path)
    store = FakeStore(metadata, {"draft_creation_uncertain": True})
    wechat = FakeWeChat()
    publisher = WeChatPublisher(wechat, FakeRenderer(), store, assets_loader=lambda _: materialized)

    with pytest.raises(BlockedPublishError):
        await publisher.publish(JobClaim(uuid4(), uuid4()))
    assert wechat.calls == []


@pytest.mark.anyio
async def test_lost_draft_response_persists_uncertain_and_next_worker_blocks(tmp_path: Path) -> None:
    materialized, metadata = assets(tmp_path)
    store = FakeStore(metadata)

    class LostResponseWeChat(FakeWeChat):
        async def create_draft(self, payload: dict[str, object]) -> str:
            await super().create_draft(payload)
            raise WeChatTransientError("network_error", "微信网络请求失败")

    first = WeChatPublisher(
        LostResponseWeChat(),
        FakeRenderer(),
        store,
        assets_loader=lambda _: materialized,
    )
    with pytest.raises(BlockedPublishError):
        await first.publish(JobClaim(uuid4(), uuid4()))
    assert store.result["draft_creation_uncertain"] is True

    second_wechat = FakeWeChat()
    second = WeChatPublisher(
        second_wechat,
        FakeRenderer(),
        store,
        assets_loader=lambda _: materialized,
    )
    with pytest.raises(BlockedPublishError):
        await second.publish(JobClaim(uuid4(), uuid4()))
    assert second_wechat.calls == []
