import hashlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from reven.articles.models import Article
from reven.integrations.models import Integration
from reven.integrations.wechat.models import WeChatPermanentError, WeChatTransientError
from reven.jobs.errors import BlockedPublishError
from reven.jobs.repository import JobClaim, JobRepository
from reven.publishing.assets import MaterializedAsset, MaterializedAssets
from reven.publishing.wechat.factory import ConfiguredWeChatPublisher
from reven.publishing.wechat.images import _repair_existing_snapshot
from reven.publishing.wechat.publisher import LeaseLost, WeChatPublisher
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import async_sessionmaker


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
            raise WeChatTransientError("network_error", "微信网络请求失败", outcome_uncertain=True)

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


@pytest.mark.anyio
async def test_definite_draft_failure_clears_started_marker(tmp_path: Path) -> None:
    materialized, metadata = assets(tmp_path)
    store = FakeStore(metadata)

    class RejectedWeChat(FakeWeChat):
        async def create_draft(self, payload: dict[str, object]) -> str:
            raise WeChatPermanentError("40007", "微信请求参数无效")

    publisher = WeChatPublisher(RejectedWeChat(), FakeRenderer(), store, assets_loader=lambda _: materialized)
    with pytest.raises(Exception):
        await publisher.publish(JobClaim(uuid4(), uuid4()))
    assert store.result["draft_creation_started"] is False
    assert store.result.get("draft_creation_uncertain") is not True


@pytest.mark.anyio
async def test_body_upload_marker_blocks_new_worker_after_successful_call_loses_lease(
    tmp_path: Path,
) -> None:
    materialized, metadata = assets(tmp_path)
    store = FakeStore(metadata)

    class LosingWeChat(FakeWeChat):
        async def upload_body_image(self, path: Path) -> str:
            result = await super().upload_body_image(path)
            store.lease = False
            return result

    publisher = WeChatPublisher(LosingWeChat(), FakeRenderer(), store, assets_loader=lambda _: materialized)
    with pytest.raises(LeaseLost):
        await publisher.publish(JobClaim(uuid4(), uuid4()))
    assert store.result["uploads_in_flight"] == {"a" * 64: "body"}

    store.lease = True
    with pytest.raises(BlockedPublishError):
        await WeChatPublisher(FakeWeChat(), FakeRenderer(), store, assets_loader=lambda _: materialized).publish(
            JobClaim(uuid4(), uuid4())
        )


@pytest.mark.anyio
async def test_cover_upload_marker_blocks_new_worker_after_successful_call_loses_lease(
    tmp_path: Path,
) -> None:
    materialized, metadata = assets(tmp_path)
    store = FakeStore(
        metadata,
        {"uploaded_images": {"a" * 64: "https://mmbiz.qpic.cn/body"}},
    )

    class LosingWeChat(FakeWeChat):
        async def upload_cover_material(self, path: Path) -> str:
            result = await super().upload_cover_material(path)
            store.lease = False
            return result

    publisher = WeChatPublisher(LosingWeChat(), FakeRenderer(), store, assets_loader=lambda _: materialized)
    with pytest.raises(LeaseLost):
        await publisher.publish(JobClaim(uuid4(), uuid4()))
    assert store.result["uploads_in_flight"] == {"b" * 64: "cover"}

    store.lease = True
    with pytest.raises(BlockedPublishError):
        await WeChatPublisher(FakeWeChat(), FakeRenderer(), store, assets_loader=lambda _: materialized).publish(
            JobClaim(uuid4(), uuid4())
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "html",
    [
        '<img src="https://example.com/a.png">',
        '<img src="data:image/png;base64,AA">',
        '<img src="/relative.png">',
        "<img>",
    ],
)
async def test_all_renderer_images_must_be_frozen_placeholders(tmp_path: Path, html: str) -> None:
    materialized, metadata = assets(tmp_path)

    class UnsafeRenderer:
        async def render(self, markdown: str) -> str:
            return html

    publisher = WeChatPublisher(
        FakeWeChat(), UnsafeRenderer(), FakeStore(metadata), assets_loader=lambda _: materialized
    )
    with pytest.raises(BlockedPublishError):
        await publisher.publish(JobClaim(uuid4(), uuid4()))


@pytest.mark.parametrize("damage", ["missing", "tampered"])
def test_recovery_atomically_repairs_one_file_without_changing_healthy_files(
    tmp_path: Path,
    damage: str,
) -> None:
    staging = tmp_path / "staging"
    final = tmp_path / "snapshot"
    staging.mkdir()
    final.mkdir()
    staged_assets, metadata = assets(staging)
    image_sha = hashlib.sha256((staging / "image-1.png").read_bytes()).hexdigest()
    cover_sha = hashlib.sha256((staging / "cover.png").read_bytes()).hexdigest()
    staged_assets = MaterializedAssets(
        (
            MaterializedAsset(
                "https://n/image",
                staging / "image-1.png",
                image_sha,
                "image/png",
                (staging / "image-1.png").stat().st_size,
            ),
        ),
        MaterializedAsset(
            "https://n/cover",
            staging / "cover.png",
            cover_sha,
            "image/png",
            (staging / "cover.png").stat().st_size,
        ),
    )
    metadata["images"][0]["sha256"] = image_sha  # type: ignore[index]
    metadata["cover"]["sha256"] = cover_sha  # type: ignore[index]
    healthy = final / "cover.png"
    healthy.write_bytes((staging / "cover.png").read_bytes())
    damaged = final / "image-1.png"
    if damage == "tampered":
        damaged.write_bytes(b"tampered")
    metadata["images"][0]["path"] = str(damaged)  # type: ignore[index]
    metadata["cover"]["path"] = str(healthy)  # type: ignore[index]
    staged = MaterializedAssets(
        staged_assets.images,
        staged_assets.cover,
        staging_dir=staging,
        final_dir=final,
    )
    healthy_before = healthy.stat().st_ino

    recovered = _repair_existing_snapshot(staged, metadata)

    assert damaged.read_bytes() == (staging / "image-1.png").read_bytes()
    assert healthy.stat().st_ino == healthy_before
    assert recovered.images[0].path == damaged


@pytest.mark.anyio
async def test_configured_publisher_loads_encrypted_integrations_and_closes_http(
    db_session,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    key_box = SecretBox(b"k" * 32)
    db_session.add_all(
        [
            Integration(
                provider="wechat",
                public_config={"app_id": "appid", "author": "作者"},
                encrypted_secret=key_box.encrypt({"app_secret": "secret"}),
            ),
            Integration(
                provider="notion",
                public_config={"data_source_id": str(uuid4())},
                encrypted_secret=key_box.encrypt({"token": "notion-token"}),
            ),
        ]
    )
    now = datetime.now(tz=UTC)
    article = Article(
        notion_page_id=str(uuid4()),
        notion_url="https://notion.so/page",
        title="title",
        notion_status="待发布",
        notion_last_edited_at=now,
        last_synced_at=now,
    )
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash="f" * 64,
        target_channels=["微信公众号"],
        scheduled_at=now - timedelta(seconds=1),
    )
    materialized, metadata = assets(tmp_path)
    image_sha = hashlib.sha256(materialized.images[0].path.read_bytes()).hexdigest()
    cover_sha = hashlib.sha256(materialized.cover.path.read_bytes()).hexdigest()  # type: ignore[union-attr]
    metadata["images"][0]["sha256"] = image_sha  # type: ignore[index]
    metadata["cover"]["sha256"] = cover_sha  # type: ignore[index]
    metadata["cover_sha256"] = cover_sha
    metadata["title"] = "title"
    metadata["summary"] = "digest"
    job.source_markdown = "# title\n![x](reven-asset://image/1)"
    job.snapshot_metadata = metadata
    await db_session.commit()
    claim = await repository.claim_next(lease_seconds=120)
    await db_session.commit()
    assert claim is not None

    script = tmp_path / "renderer.py"
    script.write_text(
        "import json,sys\n"
        "json.load(sys.stdin)\n"
        'json.dump({"ok":True,"html":"<img src=\\"reven-asset://image/1\\">"},sys.stdout)\n',
        encoding="utf-8",
    )

    async def wechat_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cgi-bin/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
        if request.url.path == "/cgi-bin/media/uploadimg":
            return httpx.Response(200, json={"url": "https://mmbiz.qpic.cn/body"})
        if request.url.path == "/cgi-bin/material/add_material":
            return httpx.Response(200, json={"media_id": "thumb"})
        return httpx.Response(200, json={"media_id": "draft"})

    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    configured = ConfiguredWeChatPublisher(
        session_factory,
        key_box,
        tmp_path,
        f"{sys.executable} {script}",
        wechat_transport=httpx.MockTransport(wechat_handler),
        notion_transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )

    result = await configured.publish(claim)

    assert result.media_id == "draft"
