from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast
from uuid import UUID, uuid4

from reven.integrations.wechat.models import (
    WeChatBlockedError,
    WeChatPermanentError,
    WeChatPublishResult,
    WeChatTransientError,
)
from reven.jobs.errors import BlockedPublishError, PermanentPublishError, TransientPublishError
from reven.jobs.repository import JobClaim
from reven.publishing.assets import MaterializedAsset, MaterializedAssets
from reven.publishing.validation import (
    WECHAT_AUTHOR_MAX,
    WECHAT_BODY_MAX,
    WECHAT_SUMMARY_MAX,
    WECHAT_TITLE_MAX,
)
from reven.publishing.wechat.images import (
    SnapshotAssetRecoverer,
    SnapshotAssetsMissingError,
    replace_placeholders,
    validate_placeholders,
    verify_snapshot_file_set,
)

T = TypeVar("T")


class LeaseLost(RuntimeError):  # noqa: N818 - 公开契约明确使用 LeaseLost
    """当前 worker 已失去任务租约，必须立即停止外部副作用。"""


class WeChatApi(Protocol):
    async def get_token(self) -> str: ...
    async def upload_body_image(self, path: Path) -> str: ...
    async def upload_cover_material(self, path: Path) -> str: ...
    async def create_draft(self, payload: dict[str, object]) -> str: ...


class Renderer(Protocol):
    async def render(self, markdown: str) -> str: ...


class ResultStore(Protocol):
    async def load(self, claim: JobClaim) -> dict[str, object]: ...
    async def assert_lease(self, claim: JobClaim) -> bool: ...
    async def save_result(self, claim: JobClaim, patch: dict[str, object]) -> bool: ...
    async def clear_inflight_if_operation_matches(
        self,
        job_id: UUID,
        operation_key: str,
        operation_id: str,
    ) -> bool: ...


@dataclass(frozen=True)
class _Context:
    markdown: str
    metadata: dict[str, object]
    result: dict[str, object]
    title: str
    author: str
    digest: str
    source_url: str


class WeChatPublisher:
    def __init__(
        self,
        client: WeChatApi,
        renderer: Renderer,
        store: ResultStore,
        *,
        assets_loader: Callable[[dict[str, object]], MaterializedAssets] | None = None,
        assets_recoverer: SnapshotAssetRecoverer | None = None,
    ) -> None:
        self.client = client
        self.renderer = renderer
        self.store = store
        self.assets_loader = assets_loader or load_snapshot_assets
        self.assets_recoverer = assets_recoverer

    async def publish(self, claim: JobClaim) -> WeChatPublishResult:
        context = _parse_context(await self.store.load(claim))
        media_id = context.result.get("media_id")
        if isinstance(media_id, str) and media_id:
            return WeChatPublishResult(media_id, _optional_string(context.result.get("content")))
        _reject_uncertain_draft(context.result)
        _reject_uncertain_uploads(context.result)
        await self._assert_lease(claim)
        assets = await self._load_assets(claim, context)
        html = await self.renderer.render(context.markdown)
        placeholders = validate_placeholders(html, assets.images)
        await self._external(self.client.get_token())
        uploaded = await self._upload_images(claim, context.result, placeholders)
        content = replace_placeholders(html, uploaded)
        thumb_media_id = await self._upload_cover(claim, context.result, assets.cover)
        media_id = await self._create_draft(claim, context, content, thumb_media_id)
        return WeChatPublishResult(media_id, content)

    async def _load_assets(self, claim: JobClaim, context: _Context) -> MaterializedAssets:
        try:
            return self.assets_loader(context.metadata)
        except SnapshotAssetsMissingError:
            if self.assets_recoverer is None:
                raise
            await self._assert_lease(claim)
            assets = await self.assets_recoverer.recover(claim.job_id, context.markdown, context.metadata)
            await self._assert_lease(claim)
            return assets

    async def _upload_images(
        self,
        claim: JobClaim,
        result: dict[str, object],
        placeholders: tuple[Any, ...],
    ) -> dict[int, str]:
        persisted = _uploaded_images(result)
        urls: dict[int, str] = {}
        for placeholder in placeholders:
            sha256 = placeholder.asset.sha256
            url = persisted.get(sha256)
            if url is None:
                await self._assert_lease(claim)
                operation_id = str(uuid4())
                operation_key = f"body:{sha256}"
                await self._start_operation(claim, result, operation_key, operation_id, "body", sha256)
                try:
                    url = await self._external(self.client.upload_body_image(placeholder.asset.path))
                except (BlockedPublishError, PermanentPublishError, TransientPublishError) as exc:
                    await self._clear_definite_operation(claim.job_id, operation_key, operation_id, exc)
                    raise
                persisted[sha256] = url
                completed = _without_operation(result, operation_key)
                await self._save(
                    claim,
                    {
                        "uploaded_images": persisted,
                        "operations_in_flight": completed,
                    },
                )
                result["operations_in_flight"] = completed
            urls[placeholder.ordinal] = url
        return urls

    async def _upload_cover(
        self,
        claim: JobClaim,
        result: dict[str, object],
        cover: MaterializedAsset | None,
    ) -> str:
        existing = result.get("thumb_media_id")
        if isinstance(existing, str) and existing:
            return existing
        if cover is None:
            raise BlockedPublishError("微信草稿缺少冻结封面")
        await self._assert_lease(claim)
        operation_id = str(uuid4())
        operation_key = f"cover:{cover.sha256}"
        await self._start_operation(claim, result, operation_key, operation_id, "cover", cover.sha256)
        try:
            media_id = await self._external(self.client.upload_cover_material(cover.path))
        except (BlockedPublishError, PermanentPublishError, TransientPublishError) as exc:
            await self._clear_definite_operation(claim.job_id, operation_key, operation_id, exc)
            raise
        completed = _without_operation(result, operation_key)
        await self._save(
            claim,
            {
                "thumb_media_id": media_id,
                "cover_sha256": cover.sha256,
                "operations_in_flight": completed,
            },
        )
        result["operations_in_flight"] = completed
        return media_id

    async def _create_draft(
        self,
        claim: JobClaim,
        context: _Context,
        content: str,
        thumb_media_id: str,
    ) -> str:
        payload = _draft_payload(context, content, thumb_media_id)
        operation_id = str(uuid4())
        operation_key = "draft"
        asset_sha = _content_sha(content)
        await self._assert_lease(claim)
        await self._start_operation(claim, context.result, operation_key, operation_id, "draft", asset_sha)
        await self._assert_lease(claim)
        try:
            media_id = await self._external(self.client.create_draft(payload))
        except (BlockedPublishError, PermanentPublishError, TransientPublishError) as exc:
            if _outcome_uncertain(exc):
                await self._mark_uncertain(claim, operation_id)
                raise BlockedPublishError("微信草稿创建结果不确定，请人工核验后处理") from None
            await self.store.clear_inflight_if_operation_matches(claim.job_id, operation_key, operation_id)
            raise
        await self._save(
            claim,
            {
                "media_id": media_id,
                "content": content,
                "operations_in_flight": _without_operation(context.result, operation_key),
            },
        )
        context.result["operations_in_flight"] = _without_operation(context.result, operation_key)
        return media_id

    async def _mark_uncertain(self, claim: JobClaim, operation_id: str) -> None:
        if await self.store.assert_lease(claim):
            await self._save(
                claim,
                {
                    "draft_creation_uncertain": {
                        "operation_id": operation_id,
                        "phase": "draft",
                    }
                },
            )

    async def _clear_definite_operation(
        self,
        job_id: UUID,
        operation_key: str,
        operation_id: str,
        error: Exception,
    ) -> None:
        if _outcome_uncertain(error):
            return
        await self.store.clear_inflight_if_operation_matches(job_id, operation_key, operation_id)

    async def _start_operation(
        self,
        claim: JobClaim,
        result: dict[str, object],
        operation_key: str,
        operation_id: str,
        phase: str,
        asset_sha: str,
    ) -> None:
        operations = _operations_in_flight(result)
        operations[operation_key] = {
            "operation_id": operation_id,
            "phase": phase,
            "asset_sha": asset_sha,
        }
        await self._save(claim, {"operations_in_flight": operations})
        result["operations_in_flight"] = operations

    async def _assert_lease(self, claim: JobClaim) -> None:
        if not await self.store.assert_lease(claim):
            raise LeaseLost("publication lease lost")

    async def _save(self, claim: JobClaim, patch: dict[str, object]) -> None:
        if not await self.store.save_result(claim, patch):
            raise LeaseLost("publication lease lost")

    @staticmethod
    async def _external(operation: Awaitable[T]) -> T:
        try:
            return await operation
        except WeChatBlockedError as exc:
            raise BlockedPublishError(str(exc)) from exc
        except WeChatTransientError as exc:
            error = TransientPublishError(str(exc))
            setattr(error, "outcome_uncertain", exc.outcome_uncertain)
            raise error from exc
        except WeChatPermanentError as exc:
            raise PermanentPublishError(str(exc)) from exc


def load_snapshot_assets(metadata: dict[str, object]) -> MaterializedAssets:
    images_raw = metadata.get("images")
    cover_raw = metadata.get("cover")
    if not isinstance(images_raw, list) or not isinstance(cover_raw, dict):
        raise BlockedPublishError("微信素材冻结清单无效")
    images = tuple(_metadata_asset(item) for item in images_raw)
    cover = _metadata_asset(cover_raw)
    _verify_asset_hashes(images, cover, metadata)
    assets = MaterializedAssets(images, cover)
    verify_snapshot_file_set(assets)
    return assets


def _metadata_asset(raw: object) -> MaterializedAsset:
    if not isinstance(raw, dict):
        raise BlockedPublishError("微信素材冻结清单无效")
    path, sha256 = raw.get("path"), raw.get("sha256")
    if not isinstance(path, str) or not isinstance(sha256, str) or len(sha256) != 64:
        raise BlockedPublishError("微信素材冻结清单无效")
    file_path = Path(path)
    if file_path.is_symlink() or not file_path.is_file():
        raise SnapshotAssetsMissingError("微信素材快照文件缺失，必须安全恢复")
    return MaterializedAsset(
        str(raw.get("original_url", "")),
        file_path,
        sha256,
        str(raw.get("mime_type", "")),
        file_path.stat().st_size,
    )


def _verify_asset_hashes(
    images: tuple[MaterializedAsset, ...],
    cover: MaterializedAsset,
    metadata: dict[str, object],
) -> None:
    import hashlib

    for asset in (*images, cover):
        if hashlib.sha256(asset.path.read_bytes()).hexdigest() != asset.sha256:
            raise BlockedPublishError("微信素材快照哈希不一致")
    if metadata.get("cover_sha256") != cover.sha256:
        raise BlockedPublishError("微信封面快照哈希不一致")


def _parse_context(raw: dict[str, object]) -> _Context:
    markdown = raw.get("source_markdown")
    metadata = raw.get("snapshot_metadata")
    result = raw.get("wechat_result")
    if not isinstance(markdown, str) or not isinstance(metadata, dict) or not isinstance(result, dict):
        raise BlockedPublishError("微信发布冻结快照无效")
    return _Context(
        markdown,
        cast(dict[str, object], metadata),
        cast(dict[str, object], result),
        str(raw.get("title", "")),
        str(raw.get("author", "")),
        str(raw.get("digest", "")),
        str(raw.get("content_source_url", "")),
    )


def _draft_payload(context: _Context, content: str, thumb_media_id: str) -> dict[str, object]:
    limits = (
        ("title", context.title, WECHAT_TITLE_MAX),
        ("author", context.author, WECHAT_AUTHOR_MAX),
        ("digest", context.digest, WECHAT_SUMMARY_MAX),
        ("content", content, WECHAT_BODY_MAX),
    )
    if any(not value.strip() for field, value, _limit in limits if field in {"title", "content"}):
        raise PermanentPublishError("微信草稿标题与正文不能为空")
    if any(len(value) > limit for _field, value, limit in limits):
        raise PermanentPublishError("微信草稿字段超过接口限制")
    article = {
        "title": context.title,
        "author": context.author,
        "digest": context.digest,
        "content": content,
        "thumb_media_id": thumb_media_id,
        "content_source_url": context.source_url,
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }
    return {"articles": [article]}


def _uploaded_images(result: dict[str, object]) -> dict[str, str]:
    raw = result.get("uploaded_images", {})
    valid_entries = isinstance(raw, dict) and all(
        isinstance(key, str) and isinstance(value, str) for key, value in raw.items()
    )
    if not valid_entries:
        raise BlockedPublishError("微信已上传图片记录无效")
    return dict(cast(dict[str, str], raw))


def _reject_uncertain_draft(result: dict[str, object]) -> None:
    if result.get("draft_creation_uncertain"):
        raise BlockedPublishError("微信草稿创建结果不确定，请人工核验后处理")


def _reject_uncertain_uploads(result: dict[str, object]) -> None:
    if _operations_in_flight(result):
        raise BlockedPublishError("微信素材上传结果不确定，请人工核验后处理")


def _operations_in_flight(
    result: dict[str, object],
) -> dict[str, dict[str, str]]:
    raw = result.get("operations_in_flight", {})
    valid = isinstance(raw, dict) and all(_valid_operation(key, value) for key, value in raw.items())
    if not valid:
        raise BlockedPublishError("微信素材上传阶段记录无效")
    return {key: dict(value) for key, value in cast(dict[str, dict[str, str]], raw).items()}


def _valid_operation(key: object, value: object) -> bool:
    if not isinstance(key, str) or not isinstance(value, dict):
        return False
    operation_id = value.get("operation_id")
    phase = value.get("phase")
    asset_sha = value.get("asset_sha")
    try:
        UUID(str(operation_id))
    except ValueError:
        return False
    return phase in {"body", "cover", "draft"} and isinstance(asset_sha, str) and len(asset_sha) == 64


def _without_operation(
    result: dict[str, object],
    operation_key: str,
) -> dict[str, dict[str, str]]:
    operations = _operations_in_flight(result)
    operations.pop(operation_key, None)
    return operations


def _content_sha(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode()).hexdigest()


def _outcome_uncertain(error: Exception) -> bool:
    return bool(getattr(error, "outcome_uncertain", False))


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
