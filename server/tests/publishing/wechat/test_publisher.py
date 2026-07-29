import hashlib
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from reven.articles.models import Article
from reven.integrations.models import Integration
from reven.integrations.notion.mapper import map_notion_page
from reven.integrations.wechat.models import WeChatPermanentError, WeChatTransientError
from reven.jobs.errors import BlockedPublishError, TransientPublishError
from reven.jobs.repository import JobClaim, JobRepository
from reven.publishing.assets import MaterializedAsset, MaterializedAssets
from reven.publishing.snapshot import build_snapshot
from reven.publishing.wechat.factory import ConfiguredWeChatPublisher
from reven.publishing.wechat.images import (
    SnapshotAssetRecoverer,
    _repair_existing_snapshot,
)
from reven.publishing.wechat.publisher import LeaseLost, WeChatPublisher
from reven.publishing.wechat.store import SqlAlchemyWeChatResultStore
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import async_sessionmaker


class FakeRenderer:
    async def render(self, markdown: str) -> str:
        return '<section><img src="reven-asset://image/1"></section>'


class TrackingTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler) -> None:  # type: ignore[no-untyped-def]
        self.inner = httpx.MockTransport(handler)
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        self.closed = True
        await self.inner.aclose()


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

    async def clear_inflight_if_operation_matches(
        self,
        job_id,  # type: ignore[no-untyped-def]
        operation_key: str,
        operation_id: str,
    ) -> bool:
        operations = dict(self.result.get("operations_in_flight", {}))
        marker = operations.get(operation_key)
        if not isinstance(marker, dict) or marker.get("operation_id") != operation_id:
            return False
        if operation_key == "draft" and self.result.get("media_id"):
            return False
        operations.pop(operation_key)
        self.result["operations_in_flight"] = operations
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
async def test_token_prefetch_uses_domain_error_mapping(tmp_path: Path) -> None:
    materialized, metadata = assets(tmp_path)

    class TokenTimeout(FakeWeChat):
        async def get_token(self) -> str:
            raise WeChatTransientError(
                "network_error",
                "微信网络请求失败",
                outcome_uncertain=True,
            )

    publisher = WeChatPublisher(
        TokenTimeout(),
        FakeRenderer(),
        FakeStore(metadata),
        assets_loader=lambda _: materialized,
    )
    with pytest.raises(TransientPublishError) as raised:
        await publisher.publish(JobClaim(uuid4(), uuid4()))
    assert "secret" not in str(raised.value)


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
    assert store.result["draft_creation_uncertain"]["phase"] == "draft"

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
    assert store.result["operations_in_flight"] == {}
    assert store.result.get("draft_creation_uncertain") is not True


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["body", "cover", "draft"])
async def test_definite_failure_clears_own_operation_after_lease_loss(
    tmp_path: Path,
    phase: str,
) -> None:
    materialized, metadata = assets(tmp_path)
    saved: dict[str, object] = {}
    if phase in {"cover", "draft"}:
        saved["uploaded_images"] = {"a" * 64: "https://mmbiz.qpic.cn/body"}
    if phase == "draft":
        saved["thumb_media_id"] = "thumb-id"
    store = FakeStore(metadata, saved)

    class DefiniteFailure(FakeWeChat):
        async def upload_body_image(self, path: Path) -> str:
            if phase == "body":
                store.lease = False
                raise WeChatPermanentError("40007", "明确拒绝")
            return await super().upload_body_image(path)

        async def upload_cover_material(self, path: Path) -> str:
            if phase == "cover":
                store.lease = False
                raise WeChatPermanentError("40007", "明确拒绝")
            return await super().upload_cover_material(path)

        async def create_draft(self, payload: dict[str, object]) -> str:
            if phase == "draft":
                store.lease = False
                raise WeChatPermanentError("40007", "明确拒绝")
            return await super().create_draft(payload)

    publisher = WeChatPublisher(
        DefiniteFailure(),
        FakeRenderer(),
        store,
        assets_loader=lambda _: materialized,
    )
    with pytest.raises(Exception):
        await publisher.publish(JobClaim(uuid4(), uuid4()))
    assert store.result["operations_in_flight"] == {}


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
    body_marker = store.result["operations_in_flight"]["body:" + "a" * 64]
    assert body_marker["phase"] == "body"
    assert body_marker["asset_sha"] == "a" * 64

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
    cover_marker = store.result["operations_in_flight"]["cover:" + "b" * 64]
    assert cover_marker["phase"] == "cover"
    assert cover_marker["asset_sha"] == "b" * 64

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


@pytest.mark.parametrize("cover_matches", [True, False])
def test_recovery_compares_fresh_mapped_page_and_downloaded_cover_with_frozen_snapshot(
    load_fixture,
    tmp_path: Path,
    cover_matches: bool,  # type: ignore[no-untyped-def]
) -> None:
    materialized, _metadata = assets(tmp_path)
    image_sha = hashlib.sha256(materialized.images[0].path.read_bytes()).hexdigest()
    assert materialized.cover is not None
    cover_sha = hashlib.sha256(materialized.cover.path.read_bytes()).hexdigest()
    image = MaterializedAsset(
        materialized.images[0].original_url,
        materialized.images[0].path,
        image_sha,
        "image/png",
        materialized.images[0].size,
    )
    cover = MaterializedAsset(
        materialized.cover.original_url,
        materialized.cover.path,
        cover_sha,
        "image/png",
        materialized.cover.size,
    )
    mapped = map_notion_page(load_fixture("notion/page.json"))
    fresh_markdown = "# title\n![x](https://fresh.example/image.png)"
    frozen = build_snapshot(
        fresh_markdown,
        image_sha256=(image_sha,),
        cover_sha256=cover_sha,
        title=mapped.title,
        summary=mapped.summary,
        categories=tuple(mapped.categories),
    )
    metadata = frozen.metadata()
    if not cover_matches:
        metadata["cover_sha256"] = "0" * 64

    def operation() -> None:
        SnapshotAssetRecoverer._verify(
            MaterializedAssets((image,), cover),
            fresh_markdown,
            frozen.markdown,
            metadata,
            mapped,
        )

    if cover_matches:
        operation()
    else:
        with pytest.raises(BlockedPublishError):
            operation()


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
    wechat_transport = TrackingTransport(wechat_handler)
    notion_transport = TrackingTransport(lambda _request: httpx.Response(500))
    configured = ConfiguredWeChatPublisher(
        session_factory,
        key_box,
        tmp_path,
        f"{sys.executable} {script}",
        wechat_transport=wechat_transport,
        notion_transport=notion_transport,
    )

    result = await configured.publish(claim)

    assert result.media_id == "draft"
    assert wechat_transport.closed
    assert notion_transport.closed


@pytest.mark.anyio
async def test_operation_scoped_cleanup_ignores_lease_and_preserves_other_result_fields(
    db_session,  # type: ignore[no-untyped-def]
) -> None:
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
        content_hash="e" * 64,
        target_channels=["微信公众号"],
        scheduled_at=now,
    )
    operation_id = str(uuid4())
    sha256 = "a" * 64
    job.wechat_result = {
        "keep": "value",
        "operations_in_flight": {
            f"body:{sha256}": {
                "operation_id": operation_id,
                "phase": "body",
                "asset_sha": sha256,
            },
            "draft": {
                "operation_id": str(uuid4()),
                "phase": "draft",
                "asset_sha": "b" * 64,
            },
        },
    }
    await db_session.commit()
    store = SqlAlchemyWeChatResultStore(async_sessionmaker(db_session.bind, expire_on_commit=False))

    assert await store.clear_inflight_if_operation_matches(job.id, f"body:{sha256}", operation_id)
    await db_session.refresh(job)
    assert job.wechat_result["keep"] == "value"
    assert set(job.wechat_result["operations_in_flight"]) == {"draft"}
    assert not await store.clear_inflight_if_operation_matches(job.id, "draft", str(uuid4()))

    job.wechat_result = {
        **job.wechat_result,
        "media_id": "already-created",
    }
    await db_session.commit()
    draft_op = job.wechat_result["operations_in_flight"]["draft"]["operation_id"]
    assert not await store.clear_inflight_if_operation_matches(job.id, "draft", draft_op)


@pytest.mark.anyio
async def test_recovery_source_uses_fresh_page_cover_and_stable_page_markdown_page(
    db_session,
    load_fixture,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
    now = datetime.now(tz=UTC)
    article = Article(
        notion_page_id=str(uuid4()),
        notion_url="https://notion.so/page",
        title="old",
        notion_status="待发布",
        cover_metadata={"url": "https://old.example/cover.png"},
        notion_last_edited_at=now,
        last_synced_at=now,
    )
    db_session.add(article)
    await db_session.flush()
    repository = JobRepository(db_session)
    job = await repository.create_waiting(
        article_id=article.id,
        content_hash="d" * 64,
        target_channels=["微信公众号"],
        scheduled_at=now,
    )
    await db_session.commit()
    page = load_fixture("notion/page.json")
    page["properties"]["封面"]["files"][0]["file"]["url"] = "https://fresh.example/cover.png"
    calls: list[str] = []

    class FakeNotion:
        async def retrieve_page(self, page_id: str):  # type: ignore[no-untyped-def]
            calls.append("page")
            return deepcopy(page)

        async def retrieve_page_markdown(self, page_id: str) -> str:
            calls.append("markdown")
            return "# fresh"

    configured = ConfiguredWeChatPublisher(
        async_sessionmaker(db_session.bind, expire_on_commit=False),
        SecretBox(b"k" * 32),
        tmp_path,
        "node cli.mjs",
    )
    markdown, mapped = await configured._source(job.id, FakeNotion())  # type: ignore[arg-type]

    assert calls == ["page", "markdown", "page"]
    assert markdown == "# fresh"
    assert mapped.cover is not None
    assert mapped.cover.url == "https://fresh.example/cover.png"


@pytest.mark.anyio
async def test_recovery_source_retries_when_page_changes_during_read(
    db_session,
    load_fixture,
    tmp_path: Path,  # type: ignore[no-untyped-def]
) -> None:
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
    job = await JobRepository(db_session).create_waiting(
        article_id=article.id,
        content_hash="c" * 64,
        target_channels=["微信公众号"],
        scheduled_at=now,
    )
    await db_session.commit()
    page = load_fixture("notion/page.json")
    changed = deepcopy(page)
    changed["last_edited_time"] = "2026-07-30T12:00:00+00:00"

    class ChangingNotion:
        count = 0

        async def retrieve_page(self, page_id: str):  # type: ignore[no-untyped-def]
            self.count += 1
            return deepcopy(page if self.count == 1 else changed)

        async def retrieve_page_markdown(self, page_id: str) -> str:
            return "# mixed"

    configured = ConfiguredWeChatPublisher(
        async_sessionmaker(db_session.bind, expire_on_commit=False),
        SecretBox(b"k" * 32),
        tmp_path,
        "node cli.mjs",
    )
    with pytest.raises(TransientPublishError):
        await configured._source(job.id, ChangingNotion())  # type: ignore[arg-type]
