from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.integrations.wechat.models import (
    WeChatBlockedError,
    WeChatPermanentError,
    WeChatPublishResult,
    WeChatTransientError,
)
from reven.jobs.errors import BlockedPublishError, PermanentPublishError, TransientPublishError
from reven.jobs.models import PublicationJob
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
        await self.client.get_token()
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
        in_flight = _uploads_in_flight(result)
        urls: dict[int, str] = {}
        for placeholder in placeholders:
            sha256 = placeholder.asset.sha256
            url = persisted.get(sha256)
            if url is None:
                await self._assert_lease(claim)
                in_flight[sha256] = "body"
                await self._save(claim, {"uploads_in_flight": in_flight})
                try:
                    url = await self._external(self.client.upload_body_image(placeholder.asset.path))
                except (BlockedPublishError, PermanentPublishError, TransientPublishError) as exc:
                    await self._clear_definite_upload(claim, in_flight, sha256, exc)
                    raise
                persisted[sha256] = url
                completed_in_flight = dict(in_flight)
                completed_in_flight.pop(sha256, None)
                await self._save(
                    claim,
                    {
                        "uploaded_images": persisted,
                        "uploads_in_flight": completed_in_flight,
                    },
                )
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
        in_flight = _uploads_in_flight(result)
        in_flight[cover.sha256] = "cover"
        await self._save(claim, {"uploads_in_flight": in_flight})
        try:
            media_id = await self._external(self.client.upload_cover_material(cover.path))
        except (BlockedPublishError, PermanentPublishError, TransientPublishError) as exc:
            await self._clear_definite_upload(claim, in_flight, cover.sha256, exc)
            raise
        completed_in_flight = dict(in_flight)
        completed_in_flight.pop(cover.sha256, None)
        await self._save(
            claim,
            {
                "thumb_media_id": media_id,
                "cover_sha256": cover.sha256,
                "uploads_in_flight": completed_in_flight,
            },
        )
        return media_id

    async def _create_draft(
        self,
        claim: JobClaim,
        context: _Context,
        content: str,
        thumb_media_id: str,
    ) -> str:
        payload = _draft_payload(context, content, thumb_media_id)
        await self._assert_lease(claim)
        await self._save(claim, {"draft_creation_started": True})
        await self._assert_lease(claim)
        try:
            media_id = await self._external(self.client.create_draft(payload))
        except (BlockedPublishError, PermanentPublishError, TransientPublishError) as exc:
            if _outcome_uncertain(exc):
                await self._mark_uncertain(claim)
                raise BlockedPublishError("微信草稿创建结果不确定，请人工核验后处理") from None
            await self._save(claim, {"draft_creation_started": False})
            raise
        await self._save(claim, {"media_id": media_id, "content": content, "draft_creation_started": False})
        return media_id

    async def _mark_uncertain(self, claim: JobClaim) -> None:
        if await self.store.assert_lease(claim):
            await self._save(claim, {"draft_creation_uncertain": True})

    async def _clear_definite_upload(
        self,
        claim: JobClaim,
        in_flight: dict[str, str],
        sha256: str,
        error: Exception,
    ) -> None:
        if _outcome_uncertain(error):
            return
        cleared = dict(in_flight)
        cleared.pop(sha256, None)
        await self._save(claim, {"uploads_in_flight": cleared})

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


class SqlAlchemyWeChatResultStore:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        author: str = "",
    ) -> None:
        self.session_factory = session_factory
        self.author = author

    async def load(self, claim: JobClaim) -> dict[str, object]:
        async with self.session_factory() as session:
            row = await session.execute(
                select(PublicationJob, Article)
                .join(Article, Article.id == PublicationJob.article_id)
                .where(PublicationJob.id == claim.job_id)
            )
            pair = row.one_or_none()
            if pair is None:
                raise LeaseLost("publication job missing")
            job, article = pair
            return _job_data(job, article, self.author)

    async def assert_lease(self, claim: JobClaim) -> bool:
        async with self.session_factory() as session:
            database_now = func.current_timestamp()
            statement = select(PublicationJob.id).where(
                PublicationJob.id == claim.job_id,
                PublicationJob.lease_token == claim.lease_token,
                PublicationJob.lease_expires_at >= database_now,
            )
            return await session.scalar(statement) is not None

    async def save_result(self, claim: JobClaim, patch: dict[str, object]) -> bool:
        async with self.session_factory.begin() as session:
            job = await session.scalar(
                select(PublicationJob).where(PublicationJob.id == claim.job_id).with_for_update()
            )
            if job is None or not await _lease_matches(session, job, claim):
                return False
            job.wechat_result = {**job.wechat_result, **patch}
            return True


def load_snapshot_assets(metadata: dict[str, object]) -> MaterializedAssets:
    images_raw = metadata.get("images")
    cover_raw = metadata.get("cover")
    if not isinstance(images_raw, list) or not isinstance(cover_raw, dict):
        raise BlockedPublishError("微信素材冻结清单无效")
    images = tuple(_metadata_asset(item) for item in images_raw)
    cover = _metadata_asset(cover_raw)
    _verify_asset_hashes(images, cover, metadata)
    return MaterializedAssets(images, cover)


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
    if result.get("draft_creation_started") is True or result.get("draft_creation_uncertain") is True:
        raise BlockedPublishError("微信草稿创建结果不确定，请人工核验后处理")


def _reject_uncertain_uploads(result: dict[str, object]) -> None:
    if _uploads_in_flight(result):
        raise BlockedPublishError("微信素材上传结果不确定，请人工核验后处理")


def _uploads_in_flight(result: dict[str, object]) -> dict[str, str]:
    raw = result.get("uploads_in_flight", {})
    valid = isinstance(raw, dict) and all(
        isinstance(key, str) and len(key) == 64 and value in {"body", "cover"} for key, value in raw.items()
    )
    if not valid:
        raise BlockedPublishError("微信素材上传阶段记录无效")
    return dict(cast(dict[str, str], raw))


def _outcome_uncertain(error: Exception) -> bool:
    return bool(getattr(error, "outcome_uncertain", False))


async def _lease_matches(session: AsyncSession, job: PublicationJob, claim: JobClaim) -> bool:
    now = await session.scalar(select(func.current_timestamp()))
    return (
        job.lease_token == claim.lease_token
        and job.lease_expires_at is not None
        and now is not None
        and job.lease_expires_at >= now
    )


def _job_data(job: PublicationJob, article: Article, author: str) -> dict[str, object]:
    metadata = job.snapshot_metadata
    notion = article.notion_metadata
    return {
        "source_markdown": job.source_markdown or "",
        "snapshot_metadata": metadata,
        "wechat_result": job.wechat_result,
        "title": metadata.get("title", article.title),
        "author": author or notion.get("author", ""),
        "digest": metadata.get("summary", ""),
        "content_source_url": article.notion_url,
    }


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
