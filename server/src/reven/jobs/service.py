"""Freeze validated Notion content into an idempotent publication job."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.articles.models import Article
from reven.domain import AutomationStatus, JobStatus, TargetChannel, parse_target_channels
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
    async def materialize(self, job_id: str, image_urls: list[str], cover_url: str) -> MaterializedAssets: ...


@dataclass(frozen=True)
class PrepareResult:
    job_id: UUID
    reused: bool = False
    blocked: bool = False
    validation: ValidationResult | None = None


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
        try:
            return await self._prepare_transaction(job_id)
        except _FreezeConflictError as conflict:
            return await self._resolve_unique_conflict(job_id, conflict)

    async def _prepare_transaction(self, job_id: UUID) -> PrepareResult:
        async with self.session_factory.begin() as session:
            job = await _locked_job(session, job_id)
            if job is None:
                raise PublicationPreparationError("发布任务不存在")
            if job.content_hash is not None:
                return PrepareResult(job.id)
            article = await session.get(Article, job.article_id)
            if article is None:
                raise PublicationPreparationError("发布任务关联的稿件不存在")
            try:
                raw_page = await self.notion.retrieve_page(article.notion_page_id)
                markdown = await self.notion.retrieve_page_markdown(article.notion_page_id)
                mapped = map_notion_page(raw_page)
            except Exception as exc:
                validation = _source_failure(type(exc).__name__)
                await self._block(job, article, validation)
                return PrepareResult(job.id, blocked=True, validation=validation)
            selection = parse_target_channels(mapped.target_channels)
            channels = tuple(channel for channel in TargetChannel if channel in selection.channels)
            assets, asset_errors = await self._materialize(job, markdown, mapped.cover.url if mapped.cover else None)
            candidate = await _candidate(
                session, mapped, markdown, channels, selection.unsupported, assets, asset_errors
            )
            validation = validate_candidate(candidate)
            _refresh_article(article, mapped)
            if not validation.is_valid or assets is None:
                await self._block(job, article, validation)
                return PrepareResult(job.id, blocked=True, validation=validation)
            return await self._freeze_validated(session, job, article, mapped, markdown, channels, assets)

    async def _freeze_validated(
        self,
        session: AsyncSession,
        job: PublicationJob,
        article: Article,
        mapped: MappedNotionPage,
        markdown: str,
        channels: tuple[TargetChannel, ...],
        assets: MaterializedAssets,
    ) -> PrepareResult:
        snapshot = build_snapshot(
            markdown,
            image_sha256=tuple(asset.sha256 for asset in assets.images),
            cover_sha256=assets.cover.sha256,
            title=mapped.title,
            summary=mapped.summary,
            categories=tuple(mapped.categories),
            image_paths=tuple(asset.path for asset in assets.images),
        )
        existing = await _existing_frozen(session, article.id, snapshot.content_hash, channels)
        if existing is not None:
            job.overall_status = JobStatus.CANCELLED
            return PrepareResult(existing.id, reused=True)
        metadata = _snapshot_metadata(snapshot.metadata(), assets)
        _freeze(job, snapshot.content_hash, snapshot.markdown, metadata, channels)
        article.automation_status = AutomationStatus.PROCESSING
        article.last_error = None
        try:
            await session.flush()
        except IntegrityError as exc:
            raise _FreezeConflictError(article.id, snapshot.content_hash, channels) from exc
        await self._write_notion(article.notion_page_id, AutomationStatus.PROCESSING, None)
        return PrepareResult(job.id)

    async def _materialize(
        self, job: PublicationJob, markdown: str, cover_url: str | None
    ) -> tuple[MaterializedAssets | None, tuple[ValidationError, ...]]:
        if cover_url is None:
            return None, ()
        try:
            assets = await self.materializer.materialize(str(job.id), list(image_urls(markdown)), cover_url)
            return assets, ()
        except AssetDownloadError as exc:
            issue = ValidationError(exc.code, str(exc), exc.field)
            return None, (issue,)

    async def _block(self, job: PublicationJob, article: Article, validation: ValidationResult) -> None:
        reason = _error_summary(validation)
        job.overall_status = JobStatus.BLOCKED
        job.lease_expires_at = None
        article.automation_status = AutomationStatus.BLOCKED
        article.last_error = reason
        await self._write_notion(article.notion_page_id, AutomationStatus.BLOCKED, reason)

    async def _write_notion(self, page_id: str, status: AutomationStatus, reason: str | None) -> None:
        properties: dict[str, Any] = {"自动化状态": {"select": {"name": status.value}}}
        if reason is not None:
            properties["失败原因"] = {"rich_text": [{"text": {"content": reason}}]}
        try:
            await self.notion.update_page(page_id, properties=properties)
        except Exception as exc:
            raise PublicationPreparationError(f"Notion 状态回写失败（{type(exc).__name__}），可重试") from exc

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
            current.overall_status = JobStatus.CANCELLED
            return PrepareResult(existing.id, reused=True)


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
        cover=mapped.cover,
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
    job.snapshot_metadata = metadata
    job.overall_status = JobStatus.PROCESSING
    job.lease_expires_at = None
    job.started_at = utc_now()


def _snapshot_metadata(metadata: dict[str, object], assets: MaterializedAssets) -> dict[str, object]:
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


def _source_failure(error_type: str) -> ValidationResult:
    issue = ValidationError(
        "source_sync_failed",
        f"无法获取最新 Notion 内容（{error_type}），请检查连接后重试",
        "notion",
    )
    return ValidationResult((issue,))
