"""Database state transitions and candidate assembly for job preparation."""

from datetime import UTC, datetime, timedelta
from typing import TypeGuard
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from reven.articles.models import Article
from reven.domain import AutomationStatus, BlogStage, JobStatus, TargetChannel, WechatStage
from reven.integrations.models import Integration
from reven.integrations.notion.models import MappedNotionPage
from reven.jobs.models import PublicationJob
from reven.jobs.preparation_models import PersistedPreparation, PrepareResult
from reven.jobs.repository import compute_target_channels_hash
from reven.publishing.assets import MaterializedAssets
from reven.publishing.snapshot import image_urls
from reven.publishing.validation import PublicationCandidate, ValidationError, ValidationResult
from reven.scheduling import resolve_scheduled_at, utc_now

CONNECTION_TEST_MAX_AGE = timedelta(days=7)


async def candidate(
    session: AsyncSession,
    mapped: MappedNotionPage,
    markdown: str,
    channels: tuple[TargetChannel, ...],
    unsupported: tuple[str, ...],
    assets: MaterializedAssets | None,
    asset_errors: tuple[ValidationError, ...],
) -> PublicationCandidate:
    integration_status, author, feishu_error = await _integration_status(session)
    return PublicationCandidate(
        title=mapped.title,
        markdown=markdown,
        summary=mapped.summary,
        author=author,
        cover=assets.cover if assets else None,
        image_count=len(image_urls(markdown)),
        materialized_image_count=len(assets.images) if assets else 0,
        channels=channels,
        unsupported_channels=unsupported,
        integration_status=integration_status,
        materialization_errors=asset_errors,
        feishu_error=feishu_error,
    )


async def _integration_status(
    session: AsyncSession,
) -> tuple[dict[str, bool], str, str | None]:
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


def refresh_article(article: Article, mapped: MappedNotionPage) -> None:
    article.title = mapped.title
    article.notion_status = mapped.status
    article.target_channels = mapped.target_channels
    article.planned_at = resolve_scheduled_at(mapped.planned_raw) if mapped.planned_raw else None
    article.notion_last_edited_at = mapped.last_edited_at
    article.last_synced_at = utc_now()


def freeze(
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
    metadata["target_channels_used_default"] = job.snapshot_metadata.get("target_channels_used_default", False)
    job.snapshot_metadata = metadata
    job.overall_status = JobStatus.WAITING
    job.lease_expires_at = None


async def existing_frozen(
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
    job: PublicationJob | None = await session.scalar(
        statement.order_by(PublicationJob.created_at).with_for_update().limit(1)
    )
    return job


def persist_blocked(
    job: PublicationJob,
    article: Article,
    validation: ValidationResult,
) -> PersistedPreparation:
    reason = error_summary(validation)
    job.snapshot_metadata = {
        **job.snapshot_metadata,
        "validation": validation_metadata(validation),
    }
    job.overall_status = JobStatus.BLOCKED
    job.lease_expires_at = None
    article.automation_status = AutomationStatus.BLOCKED
    article.last_error = reason
    result = PrepareResult(job.id, blocked=True, validation=validation)
    return PersistedPreparation(result, article.notion_page_id, AutomationStatus.BLOCKED, reason)


def adopt_existing(
    current: PublicationJob,
    existing: PublicationJob,
    article: Article,
) -> PersistedPreparation:
    status = JobStatus(existing.overall_status)
    if current.id != existing.id:
        current.overall_status = JobStatus.CANCELLED
    notion_status = _apply_existing_status(existing, article, status)
    return PersistedPreparation(
        PrepareResult(existing.id, reused=True),
        article.notion_page_id if notion_status else None,
        notion_status,
    )


def _apply_existing_status(
    existing: PublicationJob,
    article: Article,
    status: JobStatus,
) -> AutomationStatus | None:
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
    elif status == JobStatus.COMPLETED:
        article.automation_status = AutomationStatus.COMPLETED
        article.last_error = None
    elif status == JobStatus.PROCESSING:
        article.automation_status = AutomationStatus.PROCESSING
        article.last_error = None
    elif status == JobStatus.WAITING:
        article.automation_status = AutomationStatus.WAITING
        article.last_error = None
    else:
        article.automation_status = AutomationStatus.BLOCKED
    if (
        status in {JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.WAITING}
        and existing.snapshot_metadata.get("notion_write_pending") is True
    ):
        notion_status = AutomationStatus.PROCESSING
    return notion_status


def error_summary(validation: ValidationResult) -> str:
    return "；".join(f"{error.field}：{error.message}" for error in validation.errors)[:1000]


def validation_metadata(validation: ValidationResult) -> dict[str, object]:
    return {
        "errors": [
            {"code": item.code, "message": item.message, "field": item.field}
            for item in validation.errors
        ],
        "warnings": [
            {"code": item.code, "message": item.message, "field": item.field}
            for item in validation.warnings
        ],
    }


def valid_asset_manifest(value: object) -> TypeGuard[list[dict[str, str]]]:
    return isinstance(value, list) and all(
        isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("sha256"), str)
        for item in value
    )


def is_idempotency_conflict(exc: IntegrityError) -> bool:
    original = exc.orig
    cause = getattr(original, "__cause__", None)
    constraint = getattr(cause, "constraint_name", None) or getattr(original, "constraint_name", None)
    sqlstate = getattr(cause, "sqlstate", None) or getattr(original, "sqlstate", None)
    return constraint == "uq_job_article_version_channels" and sqlstate == "23505"


def source_failure(error_type: str) -> ValidationResult:
    issue = ValidationError(
        "source_sync_failed",
        f"无法获取最新 Notion 内容（{error_type}），请检查连接后重试",
        "notion",
    )
    return ValidationResult((issue,))
