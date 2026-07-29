"""Freeze validated Notion content into an idempotent publication job."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.domain import (
    AutomationStatus,
    BlogStage,
    JobStatus,
    TargetChannel,
    WechatStage,
    parse_target_channels,
)
from reven.integrations.models import Integration
from reven.integrations.notion.mapper import map_notion_page
from reven.integrations.notion.models import MappedNotionPage
from reven.jobs.models import PublicationJob
from reven.jobs.repository import compute_target_channels_hash
from reven.publishing.assets import AssetDownloadError, MaterializedAssets
from reven.publishing.snapshot import build_snapshot, image_urls
from reven.publishing.validation import (
    PublicationCandidate,
    ValidationError,
    ValidationResult,
    validate_candidate,
)
from reven.scheduling import resolve_scheduled_at, utc_now

CONNECTION_TEST_MAX_AGE = timedelta(days=7)


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


@dataclass(frozen=True)
class PrepareResult:
    job_id: UUID
    reused: bool = False
    blocked: bool = False
    validation: ValidationResult | None = None


@dataclass(frozen=True)
class _PersistedPreparation:
    result: PrepareResult
    page_id: str | None = None
    status: AutomationStatus | None = None
    reason: str | None = None


@dataclass(frozen=True)
class _Preflight:
    job_id: UUID
    article_id: UUID
    notion_page_id: str
    article_updated_at: datetime


@dataclass(frozen=True)
class _PreparedWork:
    preflight: _Preflight
    mapped: MappedNotionPage | None
    markdown: str
    channels: tuple[TargetChannel, ...]
    unsupported: tuple[str, ...]
    assets: MaterializedAssets | None
    validation: ValidationResult


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
            return await self._complete_status_write(job_id, already_persisted)
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
                await self._discard(work.assets)
                raise
        return await self._complete_status_write(persisted.result.job_id, persisted)

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
            job = await _locked_job(session, job_id)
            if job is None:
                raise PublicationPreparationError("发布任务不存在")
            article = await session.get(Article, job.article_id)
            if article is None:
                raise PublicationPreparationError("发布任务关联的稿件不存在")
            if job.content_hash is not None:
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
            job = await _locked_job(session, work.preflight.job_id)
            if job is None:
                raise PreparationConflictError("发布任务在准备期间被删除")
            article = await session.get(Article, work.preflight.article_id)
            if article is None:
                raise PreparationConflictError("稿件在准备期间被删除")
            if (
                job.content_hash is not None
                or job.overall_status == JobStatus.CANCELLED
                or article.updated_at != work.preflight.article_updated_at
            ):
                raise PreparationConflictError("发布任务或稿件在准备期间发生变化，请重试")
            if work.mapped is None:
                return _persist_blocked(job, article, work.validation)
            mapped = work.mapped
            _refresh_article(article, mapped)
            if not work.validation.is_valid or work.assets is None:
                return _persist_blocked(job, article, work.validation)
            return await self._freeze_validated(
                session, job, article, mapped, work.markdown, work.channels, work.assets
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
            return _persist_blocked(job, article, ValidationResult((issue,)))
        existing = await _existing_frozen(session, article.id, snapshot.content_hash, channels)
        if existing is not None:
            return _adopt_existing(job, existing, article)
        metadata = _snapshot_metadata(snapshot.metadata(), final_assets)
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
            job = await _locked_job(session, job_id)
            if job is None:
                return
            article = await session.get(Article, job.article_id)
            if article is not None:
                article.last_error = error

    async def _mark_processing(self, job_id: UUID) -> None:
        async with self.session_factory.begin() as session:
            job = await _locked_job(session, job_id)
            if job is None or job.snapshot_metadata.get("notion_write_pending") is not True:
                return
            metadata = dict(job.snapshot_metadata)
            metadata.pop("notion_write_pending", None)
            job.snapshot_metadata = metadata
            job.overall_status = JobStatus.PROCESSING
            job.started_at = utc_now()
            article = await session.get(Article, job.article_id)
            if article is not None:
                article.automation_status = AutomationStatus.PROCESSING
                article.last_error = None

    async def _resolve_unique_conflict(self, job_id: UUID, conflict: _FreezeConflictError) -> PrepareResult:
        async with self.session_factory.begin() as session:
            current = await _locked_job(session, job_id)
            if current is None:
                raise PublicationPreparationError("唯一冲突后无法找到当前任务")
            existing = await _existing_frozen(
                session,
                conflict.article_id,
                conflict.content_hash,
                conflict.channels,
                exclude_id=current.id,
            )
            if existing is None:
                raise PublicationPreparationError("唯一冲突后无法找到已冻结任务")
            article = await session.get(Article, current.article_id)
            if article is None:
                raise PublicationPreparationError("唯一冲突后无法找到关联稿件")
            return _adopt_existing(current, existing, article).result


async def _locked_job(session: AsyncSession, job_id: UUID) -> PublicationJob | None:
    job: PublicationJob | None = await session.scalar(
        select(PublicationJob).where(PublicationJob.id == job_id).with_for_update()
    )
    return job


async def _integration_status(session: AsyncSession) -> tuple[dict[str, bool], str, str | None]:
    rows = list(await session.scalars(select(Integration)))
    integrations = {row.provider: row for row in rows}
    now = datetime.now(tz=UTC)
    status: dict[str, bool] = {}
    for provider in ("github", "wechat"):
        item = integrations.get(provider)
        recent = (
            item is not None
            and item.last_tested_at is not None
            and now - item.last_tested_at <= CONNECTION_TEST_MAX_AGE
        )
        status[provider] = bool(item and item.encrypted_secret and item.connection_status == "连接正常" and recent)
    wechat = integrations.get("wechat")
    author = str(wechat.public_config.get("author", "")) if wechat else ""
    feishu = integrations.get("feishu")
    feishu_error = "unavailable" if feishu is not None and feishu.connection_status == "连接失败" else None
    return status, author, feishu_error


async def _candidate(
    session: AsyncSession,
    mapped: MappedNotionPage,
    markdown: str,
    channels: tuple[TargetChannel, ...],
    unsupported: tuple[str, ...],
    assets: MaterializedAssets | None,
    asset_errors: tuple[ValidationError, ...],
) -> PublicationCandidate:
    integration_status, author, feishu_error = await _integration_status(session)
    count = len(image_urls(markdown))
    return PublicationCandidate(
        title=mapped.title,
        markdown=markdown,
        summary=mapped.summary,
        author=author,
        cover=assets.cover if assets else None,
        image_count=count,
        materialized_image_count=len(assets.images) if assets else 0,
        channels=channels,
        unsupported_channels=unsupported,
        integration_status=integration_status,
        materialization_errors=asset_errors,
        feishu_error=feishu_error,
    )


def _refresh_article(article: Article, mapped: MappedNotionPage) -> None:
    article.title = mapped.title
    article.notion_status = mapped.status
    article.target_channels = mapped.target_channels
    article.planned_at = resolve_scheduled_at(mapped.planned_raw) if mapped.planned_raw else None
    article.notion_last_edited_at = mapped.last_edited_at
    article.last_synced_at = utc_now()


def _freeze(
    job: PublicationJob,
    content_hash: str,
    markdown: str,
    metadata: dict[str, object],
    channels: tuple[TargetChannel, ...],
) -> None:
    values = [channel.value for channel in channels]
    job.content_hash = content_hash
    job.target_channels = values
    job.target_channels_hash = compute_target_channels_hash(values)
    job.source_markdown = markdown
    metadata["notion_write_pending"] = True
    job.snapshot_metadata = metadata
    job.overall_status = JobStatus.WAITING
    job.lease_expires_at = None


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


async def _existing_frozen(
    session: AsyncSession,
    article_id: UUID,
    content_hash: str | None,
    channels: tuple[TargetChannel, ...],
    *,
    exclude_id: UUID | None = None,
) -> PublicationJob | None:
    if content_hash is None:
        return None
    statement = select(PublicationJob).where(
        PublicationJob.article_id == article_id,
        PublicationJob.content_hash == content_hash,
        PublicationJob.target_channels_hash == compute_target_channels_hash([item.value for item in channels]),
    )
    if exclude_id is not None:
        statement = statement.where(PublicationJob.id != exclude_id)
    job: PublicationJob | None = await session.scalar(statement.order_by(PublicationJob.created_at).limit(1))
    return job


def _error_summary(validation: ValidationResult) -> str:
    return "；".join(f"{error.field}：{error.message}" for error in validation.errors)[:1000]


def _persist_blocked(job: PublicationJob, article: Article, validation: ValidationResult) -> _PersistedPreparation:
    reason = _error_summary(validation)
    job.overall_status = JobStatus.BLOCKED
    job.lease_expires_at = None
    article.automation_status = AutomationStatus.BLOCKED
    article.last_error = reason
    result = PrepareResult(job.id, blocked=True, validation=validation)
    return _PersistedPreparation(result, article.notion_page_id, AutomationStatus.BLOCKED, reason)


def _adopt_existing(current: PublicationJob, existing: PublicationJob, article: Article) -> _PersistedPreparation:
    status = JobStatus(existing.overall_status)
    if current.id != existing.id:
        current.overall_status = JobStatus.CANCELLED
    notion_status: AutomationStatus | None = None
    if status in {JobStatus.FAILED, JobStatus.CANCELLED}:
        existing.overall_status = JobStatus.WAITING
        existing.lease_expires_at = None
        if existing.blog_status != BlogStage.ONLINE:
            existing.blog_error = None
        if existing.wechat_status != WechatStage.DRAFT_CREATED:
            existing.wechat_error = None
        article.automation_status = AutomationStatus.WAITING
        article.last_error = None
        if existing.snapshot_metadata.get("notion_write_pending") is True:
            notion_status = AutomationStatus.PROCESSING
    elif status == JobStatus.COMPLETED:
        article.automation_status = AutomationStatus.COMPLETED
        article.last_error = None
    elif status == JobStatus.PROCESSING:
        article.automation_status = AutomationStatus.PROCESSING
        article.last_error = None
    elif status == JobStatus.WAITING:
        article.automation_status = AutomationStatus.WAITING
        article.last_error = None
        if existing.snapshot_metadata.get("notion_write_pending") is True:
            notion_status = AutomationStatus.PROCESSING
    else:
        article.automation_status = AutomationStatus.BLOCKED
    return _PersistedPreparation(
        PrepareResult(existing.id, reused=True),
        article.notion_page_id if notion_status else None,
        notion_status,
    )


def _is_idempotency_conflict(exc: IntegrityError) -> bool:
    original = exc.orig
    cause = getattr(original, "__cause__", None)
    constraint = getattr(cause, "constraint_name", None) or getattr(original, "constraint_name", None)
    sqlstate = getattr(cause, "sqlstate", None) or getattr(original, "sqlstate", None)
    return constraint == "uq_job_article_version_channels" and sqlstate == "23505"


def _source_failure(error_type: str) -> ValidationResult:
    issue = ValidationError(
        "source_sync_failed",
        f"无法获取最新 Notion 内容（{error_type}），请检查连接后重试",
        "notion",
    )
    return ValidationResult((issue,))
