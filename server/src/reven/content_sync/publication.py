"""Bind one publication job to the current immutable content snapshot."""

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.content_sync.domain import ContentSyncStatus
from reven.content_sync.gate import CurrentSnapshotView, SnapshotUnavailableError
from reven.domain import AutomationStatus, JobStatus
from reven.jobs.errors import BlockedPublishError, TransientPublishError
from reven.jobs.locking import lock_article_job
from reven.jobs.preparation_models import PrepareResult
from reven.jobs.repository import JobClaim, JobRepository


class SnapshotGate(Protocol):
    async def require(self, article_id: UUID) -> CurrentSnapshotView: ...


@dataclass(frozen=True)
class PreparedPublicationSnapshot:
    source_markdown: str
    metadata: dict[str, object]


class PublicationSnapshotMaterializer(Protocol):
    async def materialize(
        self,
        job_id: UUID,
        snapshot: CurrentSnapshotView,
    ) -> PreparedPublicationSnapshot: ...


class SnapshotPublicationMaterializer:
    def __init__(
        self,
        data_root: Path,
        public_base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.data_root = data_root
        self.public_base_url = public_base_url.rstrip("/")
        self.transport = transport

    async def materialize(
        self,
        job_id: UUID,
        snapshot: CurrentSnapshotView,
    ) -> PreparedPublicationSnapshot:
        root, final_dir, staging_dir = self._directories(job_id)
        paths = _asset_paths(final_dir, snapshot)
        if final_dir.exists():
            _verify_cached_assets(final_dir, paths, snapshot)
            return _prepared_snapshot(snapshot, paths)
        staging_dir.mkdir(parents=True, exist_ok=False)
        staging_paths = _asset_paths(staging_dir, snapshot)
        try:
            await self._fetch_all(snapshot, staging_paths)
            staging_dir.replace(final_dir)
            _remove_empty(staging_dir.parent, root / "jobs")
        except BaseException:
            shutil.rmtree(staging_dir, ignore_errors=True)
            _remove_empty(staging_dir.parent, root / "jobs")
            raise
        return _prepared_snapshot(snapshot, paths)

    async def _fetch_all(self, snapshot: CurrentSnapshotView, paths: dict[int, Path]) -> None:
        total = 0
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30),
            trust_env=False,
            transport=self.transport,
        ) as client:
            for asset in snapshot.assets:
                content = await self._fetch(client, asset)
                total += len(content)
                if total > 200 * 1024 * 1024:
                    raise BlockedPublishError("内容快照媒体总大小超过 200 MiB")
                _write_exclusive(paths[asset.ordinal], content)

    async def _fetch(self, client: httpx.AsyncClient, asset) -> bytes:  # type: ignore[no-untyped-def]
        expected_url = f"{self.public_base_url}/{asset.storage_key}"
        if asset.public_url != expected_url:
            raise BlockedPublishError("内容快照包含非受信对象存储地址")
        try:
            async with client.stream("GET", expected_url, follow_redirects=False) as response:
                if response.status_code != 200:
                    _raise_asset_status(response.status_code)
                mime_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if mime_type != asset.mime_type:
                    raise BlockedPublishError("对象存储媒体 MIME 与快照不一致")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > asset.byte_size:
                        raise BlockedPublishError("对象存储媒体大小与快照不一致")
        except httpx.TransportError as exc:
            raise TransientPublishError("对象存储暂时不可用") from exc
        value = bytes(content)
        if len(value) != asset.byte_size or hashlib.sha256(value).hexdigest() != asset.sha256:
            raise BlockedPublishError("对象存储媒体完整性校验失败")
        return value

    def _directories(self, job_id: UUID) -> tuple[Path, Path, Path]:
        root = self.data_root.resolve()
        if self.data_root.is_symlink():
            raise BlockedPublishError("发布素材根目录不能是符号链接")
        root.mkdir(parents=True, exist_ok=True)
        job_root = root / "jobs" / str(job_id)
        final_dir = job_root / "snapshot"
        staging_dir = job_root / "staging" / str(uuid4())
        if not staging_dir.resolve(strict=False).is_relative_to(root):
            raise BlockedPublishError("发布素材目录越界")
        if final_dir.is_symlink() or job_root.is_symlink():
            raise BlockedPublishError("发布素材目录不能是符号链接")
        return root, final_dir, staging_dir


class SnapshotPublicationPreparationService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        gate: SnapshotGate,
        materializer: PublicationSnapshotMaterializer,
    ) -> None:
        self.factory = factory
        self.gate = gate
        self.materializer = materializer

    async def prepare_claim(self, claim: JobClaim) -> PrepareResult:
        article_id, pinned = await self._preflight(claim)
        if pinned:
            return PrepareResult(claim.job_id)
        try:
            snapshot = await self.gate.require(article_id)
        except SnapshotUnavailableError as exc:
            raise BlockedPublishError(exc.message) from exc
        prepared = await self.materializer.materialize(claim.job_id, snapshot)
        await self._pin(claim, snapshot, prepared)
        return PrepareResult(claim.job_id)

    async def _preflight(self, claim: JobClaim) -> tuple[UUID, bool]:
        async with self.factory.begin() as session:
            pair = await lock_article_job(session, claim.job_id)
            if pair is None:
                raise BlockedPublishError("发布任务不存在")
            article, job = pair
            if not await JobRepository(session).assert_lease(claim):
                raise TransientPublishError("发布任务租约已失效")
            if job.overall_status == JobStatus.CANCELLED:
                raise BlockedPublishError("发布任务已取消")
            return article.id, job.snapshot_id is not None

    async def _pin(
        self,
        claim: JobClaim,
        snapshot: CurrentSnapshotView,
        prepared: PreparedPublicationSnapshot,
    ) -> None:
        async with self.factory.begin() as session:
            pair = await lock_article_job(session, claim.job_id, article_id=snapshot.article_id)
            if pair is None or not await JobRepository(session).assert_lease(claim):
                raise TransientPublishError("发布任务租约已失效")
            article, job = pair
            if job.snapshot_id is not None:
                if job.snapshot_id != snapshot.id:
                    raise BlockedPublishError("发布任务已绑定其他内容快照")
                return
            if (
                article.content_sync_status != ContentSyncStatus.SYNCED
                or article.current_snapshot_id != snapshot.id
                or article.notion_last_edited_at != snapshot.source_last_edited_at
            ):
                raise BlockedPublishError("内容快照已失效，请重新同步后重试发布")
            job.snapshot_id = snapshot.id
            job.content_hash = snapshot.content_hash
            job.source_markdown = prepared.source_markdown
            job.snapshot_metadata = {**job.snapshot_metadata, **prepared.metadata}
            article.automation_status = AutomationStatus.PROCESSING
            article.last_error = None


def _asset_paths(directory: Path, snapshot: CurrentSnapshotView) -> dict[int, Path]:
    return {
        asset.ordinal: directory / _asset_filename(asset.ordinal, asset.kind, asset.mime_type)
        for asset in snapshot.assets
    }


def _asset_filename(ordinal: int, kind: str, mime_type: str) -> str:
    extensions = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
        "application/zip": ".zip",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
        "text/plain": ".txt",
    }
    prefix = "cover" if kind == "封面" else f"asset-{ordinal:04d}"
    return prefix + extensions.get(mime_type, ".bin")


def _write_exclusive(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise BlockedPublishError("发布素材文件不能是符号链接")
    try:
        with path.open("xb") as output:
            output.write(content)
    except OSError as exc:
        raise TransientPublishError("发布素材缓存写入失败") from exc


def _verify_cached_assets(
    directory: Path,
    paths: dict[int, Path],
    snapshot: CurrentSnapshotView,
) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise BlockedPublishError("发布素材缓存目录无效")
    expected_names = {path.name for path in paths.values()}
    actual_names = {path.name for path in directory.iterdir() if path.is_file()}
    if expected_names != actual_names:
        raise BlockedPublishError("发布素材缓存清单与快照不一致")
    for asset in snapshot.assets:
        path = paths[asset.ordinal]
        if path.is_symlink() or not path.is_file():
            raise BlockedPublishError("发布素材缓存缺失")
        content = path.read_bytes()
        if len(content) != asset.byte_size or hashlib.sha256(content).hexdigest() != asset.sha256:
            raise BlockedPublishError("发布素材缓存完整性校验失败")


def _prepared_snapshot(
    snapshot: CurrentSnapshotView,
    paths: dict[int, Path],
) -> PreparedPublicationSnapshot:
    cover = next((asset for asset in snapshot.assets if asset.kind == "封面"), None)
    if cover is None:
        raise BlockedPublishError("内容快照缺少封面")
    body = snapshot.source_markdown
    for asset in snapshot.assets:
        body = body.replace(f"reven-asset://sha256/{asset.sha256}", asset.public_url)
    if "reven-asset://" in body:
        raise BlockedPublishError("内容快照包含未解析的媒体地址")
    images = [_asset_metadata(asset, paths[asset.ordinal]) for asset in snapshot.assets if asset.embedded]
    metadata = {
        **snapshot.metadata,
        "title": snapshot.title,
        "images": images,
        "cover": _asset_metadata(cover, paths[cover.ordinal]),
        "cover_sha256": cover.sha256,
        "content_snapshot_id": str(snapshot.id),
        "source_last_edited_at": snapshot.source_last_edited_at.isoformat(),
    }
    return PreparedPublicationSnapshot(body, metadata)


def _asset_metadata(asset, path: Path) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {
        "ordinal": asset.ordinal,
        "original_url": asset.public_url,
        "path": str(path),
        "sha256": asset.sha256,
        "mime_type": asset.mime_type,
        "size": asset.byte_size,
    }


def _raise_asset_status(status_code: int) -> None:
    if status_code in {408, 425, 429} or status_code >= 500:
        raise TransientPublishError("对象存储暂时不可用")
    raise BlockedPublishError("对象存储媒体缺失或无权访问")


def _remove_empty(directory: Path, stop: Path) -> None:
    while directory != stop and directory.is_relative_to(stop):
        try:
            directory.rmdir()
        except OSError:
            return
        directory = directory.parent
