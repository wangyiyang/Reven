"""Freeze validated Notion content into an idempotent publication job."""

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.domain import AutomationStatus, JobStatus, TargetChannel, parse_target_channels
from reven.integrations.notion.mapper import map_notion_page
from reven.integrations.notion.models import MappedNotionPage
from reven.jobs.locking import lock_article_job as _lock_article_job
from reven.jobs.models import PublicationJob
from reven.jobs.preparation_models import (
    PersistedPreparation as _PersistedPreparation,
)
from reven.jobs.preparation_models import (
    Preflight as _Preflight,
)
from reven.jobs.preparation_models import (
    PreparedWork as _PreparedWork,
)
from reven.jobs.preparation_models import PrepareResult
from reven.jobs.preparation_state import (
    adopt_existing as _adopt_existing,
)
from reven.jobs.preparation_state import candidate as _candidate
from reven.jobs.preparation_state import error_summary as _error_summary
from reven.jobs.preparation_state import existing_frozen as _existing_frozen
from reven.jobs.preparation_state import freeze as _freeze
from reven.jobs.preparation_state import (
    is_idempotency_conflict as _is_idempotency_conflict,
)
from reven.jobs.preparation_state import persist_blocked as _persist_blocked
from reven.jobs.preparation_state import refresh_article as _refresh_article
from reven.jobs.preparation_state import source_failure as _source_failure
from reven.jobs.preparation_state import valid_asset_manifest as _valid_asset_manifest
from reven.jobs.preparation_state import validation_metadata as _validation_metadata
from reven.publishing.assets import AssetDownloadError, MaterializedAssets
from reven.publishing.snapshot import build_snapshot, image_urls
from reven.publishing.validation import (
    ValidationError,
    ValidationResult,
    validate_candidate,
)
from reven.scheduling import utc_now


class PublicationPreparationError(Exception):
    """Preparation could not complete and remains safe to retry."""


class NotionStatusWriteError(PublicationPreparationError):
    """Local state is durable, but the idempotent Notion status write must be retried."""


class PreparationConflictError(PublicationPreparationError):
    """The job or source changed while preparation ran and is safe to retry."""


class _FreezeConflictError(Exception):
    def __init__(self, article_id: UUID, content_hash: str, channels: tuple[TargetChannel, ...]) -> None:
        self.article_id = article_id
        self.content_hash = content_hash
        self.channels = channels


class NotionPreparationClient(Protocol):
    async def retrieve_page(self, page_id: str) -> dict[str, Any]: ...

    async def retrieve_page_markdown(self, page_id: str) -> str: ...

    async def update_page(self, page_id: str, *, properties: dict[str, Any]) -> dict[str, Any]: ...


class Materializer(Protocol):
    async def materialize(self, job_id: UUID, image_urls: list[str], cover_url: str | None) -> MaterializedAssets: ...

    async def finalize(self, assets: MaterializedAssets) -> MaterializedAssets: ...

    async def discard(self, assets: MaterializedAssets) -> None: ...

    async def resume_finalize(
        self,
        job_id: UUID,
        staging_identity: str,
        expected_manifest: list[dict[str, str]],
    ) -> None: ...


class PublicationJobService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        notion: NotionPreparationClient,
        materializer: Materializer,
    ) -> None:
        self.session_factory = session_factory
        self.notion = notion
        self.materializer = materializer

    async def prepare(self, job_id: UUID) -> PrepareResult:
        preflight, already_persisted = await self._preflight(job_id)
        if already_persisted is not None:
            return await self._resume_persisted(job_id, already_persisted)
        assert preflight is not None
        work = await self._prepare_external(preflight)
        try:
            persisted = await self._persist_prepared(work)
        except _FreezeConflictError as conflict:
            await self._discard(work.assets)
            return await self._resolve_unique_conflict(job_id, conflict)
        except BaseException:
            await self._discard(work.assets)
            raise
        if persisted.result.job_id != job_id or persisted.result.blocked:
            await self._discard(work.assets)
        elif work.assets is not None:
            try:
                await self._finalize(work.assets)
            except BaseException:
                await self._record_finalize_failure(job_id)
                raise
            if work.assets.staging_dir is not None:
                await self._mark_assets_finalized(job_id)
        return await self._complete_status_write(persisted.result.job_id, persisted)

    async def _resume_persisted(self, job_id: UUID, persisted: _PersistedPreparation) -> PrepareResult:
        if persisted.staging_identity is not None and persisted.asset_manifest is not None:
            try:
                resume = getattr(self.materializer, "resume_finalize")
                await resume(job_id, persisted.staging_identity, persisted.asset_manifest)
                await self._mark_assets_finalized(job_id)
            except BaseException:
                await self._record_finalize_failure(job_id)
                raise
        return await self._complete_status_write(job_id, persisted)

    async def _complete_status_write(self, job_id: UUID, persisted: _PersistedPreparation) -> PrepareResult:
        if persisted.status is None or persisted.page_id is None:
            return persisted.result
        try:
            await self._write_notion(persisted.page_id, persisted.status, persisted.reason)
        except NotionStatusWriteError as exc:
            await self._record_status_write_failure(job_id, str(exc))
            raise
        if persisted.status == AutomationStatus.PROCESSING:
            await self._mark_processing(job_id)
        return persisted.result

    async def _preflight(self, job_id: UUID) -> tuple[_Preflight | None, _PersistedPreparation | None]:
        async with self.session_factory.begin() as session:
            pair = await _lock_article_job(session, job_id)
            if pair is None:
                raise PublicationPreparationError("发布任务不存在")
            article, job = pair
            if job.content_hash is not None:
                if job.snapshot_metadata.get("asset_finalize_pending") is True:
                    identity = job.snapshot_metadata.get("asset_staging_identity")
                    manifest = job.snapshot_metadata.get("asset_manifest")
                    if not isinstance(identity, str) or not _valid_asset_manifest(manifest):
                        issue = ValidationError(
                            "asset_finalize_metadata_invalid",
                            "冻结任务的素材恢复信息无效，禁止进入执行队列",
                            "assets",
                        )
                        validation = ValidationResult((issue,))
                        reason = _error_summary(validation)
                        job.overall_status = JobStatus.BLOCKED
                        article.automation_status = AutomationStatus.BLOCKED
                        article.last_error = reason
                        return None, _PersistedPreparation(PrepareResult(job.id, blocked=True, validation=validation))
                    return None, _PersistedPreparation(
                        PrepareResult(job.id),
                        article.notion_page_id,
                        AutomationStatus.PROCESSING,
                        staging_identity=identity,
                        asset_manifest=manifest,
                    )
                if (
                    job.overall_status != JobStatus.WAITING
                    or job.snapshot_metadata.get("notion_write_pending") is not True
                ):
                    return None, _adopt_existing(job, job, article)
                if job.snapshot_metadata.get("notion_write_pending") is True:
                    job.overall_status = JobStatus.WAITING
                    return None, _PersistedPreparation(
                        PrepareResult(job.id),
                        article.notion_page_id,
                        AutomationStatus.PROCESSING,
                    )
                return None, _PersistedPreparation(PrepareResult(job.id))
            if job.overall_status == JobStatus.CANCELLED:
                raise PreparationConflictError("发布任务已取消")
            return (
                _Preflight(job.id, article.id, article.notion_page_id, article.updated_at),
                None,
            )

    async def _prepare_external(self, preflight: _Preflight) -> _PreparedWork:
        try:
            raw_page = await self.notion.retrieve_page(preflight.notion_page_id)
            markdown = await self.notion.retrieve_page_markdown(preflight.notion_page_id)
            mapped = map_notion_page(raw_page)
        except Exception as exc:
            return _PreparedWork(preflight, None, "", (), (), None, _source_failure(type(exc).__name__))
        selection = parse_target_channels(mapped.target_channels)
        channels = tuple(channel for channel in TargetChannel if channel in selection.channels)
        assets, asset_errors = await self._materialize(
            preflight.job_id, markdown, mapped.cover.url if mapped.cover else None
        )
        try:
            async with self.session_factory() as session:
                candidate = await _candidate(
                    session, mapped, markdown, channels, selection.unsupported, assets, asset_errors
                )
            validation = validate_candidate(candidate)
            latest = map_notion_page(await self.notion.retrieve_page(preflight.notion_page_id))
            if latest.last_edited_at != mapped.last_edited_at:
                raise PreparationConflictError("Notion 内容在准备期间发生变化，请重试")
        except BaseException:
            await self._discard(assets)
            raise
        return _PreparedWork(
            preflight,
            mapped,
            markdown,
            channels,
            selection.unsupported,
            assets,
            validation,
        )

    async def _persist_prepared(self, work: _PreparedWork) -> _PersistedPreparation:
        async with self.session_factory.begin() as session:
            pair = await _lock_article_job(
                session,
                work.preflight.job_id,
                article_id=work.preflight.article_id,
            )
            if pair is None:
                raise PreparationConflictError("发布任务在准备期间被删除")
            article, job = pair
            article_changed = article.updated_at != work.preflight.article_updated_at and (
                work.mapped is None or article.notion_last_edited_at != work.mapped.last_edited_at
            )
            if job.content_hash is not None or job.overall_status == JobStatus.CANCELLED or article_changed:
                raise PreparationConflictError("发布任务或稿件在准备期间发生变化，请重试")
            if work.mapped is None:
                return _persist_blocked(session, job, article, work.validation)
            mapped = work.mapped
            _refresh_article(article, mapped)
            if not work.validation.is_valid or work.assets is None:
                return _persist_blocked(session, job, article, work.validation)
            return await self._freeze_validated(
                session,
                job,
                article,
                mapped,
                work.markdown,
                work.channels,
                work.assets,
                work.validation,
            )

    async def _freeze_validated(
        self,
        session: AsyncSession,
        job: PublicationJob,
        article: Article,
        mapped: MappedNotionPage,
        markdown: str,
        channels: tuple[TargetChannel, ...],
        assets: MaterializedAssets,
        validation: ValidationResult,
    ) -> _PersistedPreparation:
        if assets.cover is None:
            raise PublicationPreparationError("校验器错误地放行了缺少封面的快照")
        final_assets = assets.final_view()
        try:
            snapshot = build_snapshot(
                markdown,
                image_sha256=tuple(asset.sha256 for asset in final_assets.images),
                cover_sha256=final_assets.cover.sha256 if final_assets.cover else "",
                title=mapped.title,
                summary=mapped.summary,
                categories=tuple(mapped.categories),
                image_paths=tuple(asset.path for asset in final_assets.images),
            )
        except ValueError:
            issue = ValidationError(
                "snapshot_conversion_failed",
                "正文图片无法安全转换，请检查 Markdown 图片语法",
                "markdown",
            )
            return _persist_blocked(session, job, article, ValidationResult((issue,)))
        existing = await _existing_frozen(session, article.id, snapshot.content_hash, channels)
        if existing is not None:
            return _adopt_existing(job, existing, article)
        metadata = _asset_finalize_metadata(
            _snapshot_metadata(snapshot.metadata(), final_assets),
            assets,
        )
        metadata["validation"] = _validation_metadata(validation)
        _freeze(job, snapshot.content_hash, snapshot.markdown, metadata, channels)
        article.automation_status = AutomationStatus.WAITING
        article.last_error = None
        article_id = article.id
        try:
            await session.flush()
        except IntegrityError as exc:
            if _is_idempotency_conflict(exc):
                raise _FreezeConflictError(article_id, snapshot.content_hash, channels) from exc
            raise
        return _PersistedPreparation(PrepareResult(job.id), article.notion_page_id, AutomationStatus.PROCESSING)

    async def _materialize(
        self, job_id: UUID, markdown: str, cover_url: str | None
    ) -> tuple[MaterializedAssets | None, tuple[ValidationError, ...]]:
        try:
            assets = await self.materializer.materialize(job_id, list(image_urls(markdown)), cover_url)
            return assets, ()
        except AssetDownloadError as exc:
            issue = ValidationError(exc.code, str(exc), exc.field)
            return None, (issue,)

    async def _finalize(self, assets: MaterializedAssets) -> None:
        finalize = getattr(self.materializer, "finalize", None)
        if finalize is not None:
            await finalize(assets)

    async def _discard(self, assets: MaterializedAssets | None) -> None:
        if assets is None:
            return
        discard = getattr(self.materializer, "discard", None)
        if discard is not None:
            await discard(assets)

    async def _write_notion(self, page_id: str, status: AutomationStatus, reason: str | None) -> None:
        properties: dict[str, Any] = {"自动化状态": {"select": {"name": status.value}}}
        if reason is not None:
            properties["失败原因"] = {"rich_text": [{"text": {"content": reason}}]}
        try:
            await self.notion.update_page(page_id, properties=properties)
        except Exception as exc:
            raise NotionStatusWriteError(f"Notion 状态回写失败（{type(exc).__name__}），可重试") from exc

    async def _record_status_write_failure(self, job_id: UUID, error: str) -> None:
        async with self.session_factory.begin() as session:
            pair = await _lock_article_job(session, job_id)
            if pair is None:
                return
            article, _job = pair
            article.last_error = error

    async def _record_finalize_failure(self, job_id: UUID) -> None:
        reason = "素材快照最终化失败，任务保持阻塞，可安全重试"
        async with self.session_factory.begin() as session:
            pair = await _lock_article_job(session, job_id)
            if pair is None:
                return
            article, job = pair
            job.overall_status = JobStatus.BLOCKED
            job.lease_expires_at = None
            article.automation_status = AutomationStatus.BLOCKED
            article.last_error = reason

    async def _mark_assets_finalized(self, job_id: UUID) -> None:
        async with self.session_factory.begin() as session:
            pair = await _lock_article_job(session, job_id)
            if pair is None:
                return
            article, job = pair
            if job.snapshot_metadata.get("asset_finalize_pending") is not True:
                return
            metadata = dict(job.snapshot_metadata)
            metadata.pop("asset_finalize_pending", None)
            metadata.pop("asset_staging_identity", None)
            metadata.pop("asset_manifest", None)
            job.snapshot_metadata = metadata
            job.overall_status = JobStatus.WAITING
            article.automation_status = AutomationStatus.WAITING
            article.last_error = None

    async def _mark_processing(self, job_id: UUID) -> None:
        async with self.session_factory.begin() as session:
            pair = await _lock_article_job(session, job_id)
            if pair is None:
                return
            article, job = pair
            if job.snapshot_metadata.get("notion_write_pending") is not True:
                return
            metadata = dict(job.snapshot_metadata)
            metadata.pop("notion_write_pending", None)
            job.snapshot_metadata = metadata
            job.overall_status = JobStatus.PROCESSING
            job.started_at = utc_now()
            article.automation_status = AutomationStatus.PROCESSING
            article.last_error = None

    async def _resolve_unique_conflict(self, job_id: UUID, conflict: _FreezeConflictError) -> PrepareResult:
        async with self.session_factory.begin() as session:
            pair = await _lock_article_job(session, job_id, article_id=conflict.article_id)
            if pair is None:
                raise PublicationPreparationError("唯一冲突后无法找到当前任务")
            article, current = pair
            existing = await _existing_frozen(
                session,
                conflict.article_id,
                conflict.content_hash,
                conflict.channels,
                exclude_id=current.id,
            )
            if existing is None:
                raise PublicationPreparationError("唯一冲突后无法找到已冻结任务")
            existing = await session.scalar(
                select(PublicationJob)
                .where(PublicationJob.id == existing.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if existing is None or existing.article_id != article.id:
                raise PublicationPreparationError("唯一冲突后已冻结任务发生变化")
            return _adopt_existing(current, existing, article).result


def _snapshot_metadata(metadata: dict[str, object], assets: MaterializedAssets) -> dict[str, object]:
    if assets.cover is None:
        raise PublicationPreparationError("缺少封面时不能生成快照元数据")
    metadata["cover"] = {
        "original_url": assets.cover.original_url,
        "path": str(assets.cover.path),
        "sha256": assets.cover.sha256,
        "mime_type": assets.cover.mime_type,
        "size": assets.cover.size,
    }
    return metadata


def _asset_finalize_metadata(
    metadata: dict[str, object],
    staged_assets: MaterializedAssets,
) -> dict[str, object]:
    if staged_assets.staging_dir is None:
        return metadata
    identity = staged_assets.staging_dir.name
    try:
        UUID(identity)
    except ValueError as exc:
        raise PublicationPreparationError("素材 staging 标识无效") from exc
    assets = (*staged_assets.images, *((staged_assets.cover,) if staged_assets.cover else ()))
    metadata["asset_finalize_pending"] = True
    metadata["asset_staging_identity"] = identity
    metadata["asset_manifest"] = [{"name": asset.path.name, "sha256": asset.sha256} for asset in assets]
    return metadata
