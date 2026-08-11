"""Editorial workbench read and action endpoints."""

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from reven.api.dependencies import PreviewServiceDep, SessionDep, SessionFactoryDep
from reven.api.schemas.articles import (
    ActionResult,
    ArticleDetail,
    ArticleList,
    ArticleSummary,
    ChannelResult,
    ContentSyncRunSummary,
    ContentSyncSummary,
    CurrentSnapshotSummary,
    JobDetail,
    JobSummary,
    PortableMarkdownResponse,
    PreviewResponse,
    RetryRequest,
)
from reven.articles.actions import ActionConflictError, ArticleActionService
from reven.articles.models import Article
from reven.articles.query import ArticleQuery
from reven.content_sync.configured import ConfiguredContentSource
from reven.content_sync.domain import ContentSyncStatus
from reven.content_sync.gate import CurrentSnapshotGate, SnapshotUnavailableError
from reven.content_sync.models import ContentSnapshot, ContentSyncRun
from reven.domain import TargetChannel
from reven.integrations.notion.configuration import IntegrationConfigurationError
from reven.integrations.notion.models import NotionResponseTooLargeError
from reven.jobs.models import PublicationJob
from reven.publishing.wechat.preview import PreviewConflictError, PreviewValidationError

router = APIRouter(prefix="/api/articles", tags=["articles"])
_SAFE_RESULT_KEYS = frozenset(
    {"article_url", "pull_request_url", "pull_request_number", "commit_sha", "merge_sha", "media_id"}
)


@router.get("", response_model=ArticleList)
async def list_articles(
    session: SessionDep,
    page: int = Query(default=1, ge=1, le=100_000),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, min_length=1, max_length=32),
    channel: TargetChannel | None = None,
    query: str | None = Query(default=None, min_length=1, max_length=200),
) -> ArticleList:
    items, total = await ArticleQuery(session).list_articles(
        page=page,
        page_size=page_size,
        status=status,
        channel=channel.value if channel else None,
        query=query,
    )
    query_service = ArticleQuery(session)
    article_ids = [item.id for item in items]
    latest_jobs = await query_service.latest_channel_jobs(article_ids)
    latest_runs = await query_service.latest_sync_runs(article_ids)
    snapshots = await query_service.current_snapshots(
        [item.current_snapshot_id for item in items if item.current_snapshot_id is not None]
    )
    return ArticleList(
        items=[
            _article_summary(
                item,
                latest_jobs.get((item.id, "个人博客")),
                latest_jobs.get((item.id, "微信公众号")),
                latest_runs.get(item.id),
                snapshots.get(item.current_snapshot_id) if item.current_snapshot_id else None,
            )
            for item in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{article_id}", response_model=ArticleDetail)
async def get_article(article_id: UUID, session: SessionDep) -> ArticleDetail | JSONResponse:
    query = ArticleQuery(session)
    article = await query.get(article_id)
    if article is None:
        return _error(404, "ARTICLE_NOT_FOUND", "稿件不存在")
    jobs, jobs_total = await query.jobs(article_id)
    latest = jobs[0] if jobs else None
    latest_runs = await query.latest_sync_runs([article.id])
    snapshots = await query.current_snapshots([article.current_snapshot_id] if article.current_snapshot_id else [])
    return _article_detail(
        article,
        jobs,
        jobs_total,
        latest,
        latest_runs.get(article.id),
        snapshots.get(article.current_snapshot_id) if article.current_snapshot_id else None,
    )


@router.get("/{article_id}/jobs/{job_id}", response_model=JobDetail)
async def get_job(article_id: UUID, job_id: UUID, session: SessionDep) -> JobDetail | JSONResponse:
    job = await ArticleQuery(session).job(article_id, job_id)
    if job is None:
        return _error(404, "JOB_NOT_FOUND", "发布任务不存在")
    return _job_detail(job)


@router.post("/{article_id}/preview/wechat", response_model=PreviewResponse)
async def preview_wechat(
    article_id: UUID,
    session: SessionDep,
    service: PreviewServiceDep,
) -> PreviewResponse | JSONResponse:
    article = await ArticleQuery(session).get(article_id)
    if article is None:
        return _error(404, "ARTICLE_NOT_FOUND", "稿件不存在")
    try:
        html = await service.render_current(article.id)
    except SnapshotUnavailableError as exc:
        return _error(409, exc.code, exc.message)
    except IntegrationConfigurationError:
        return _error(409, "NOTION_NOT_CONFIGURED", "Notion 集成尚未正确配置")
    except PreviewConflictError:
        return _error(409, "PREVIEW_SOURCE_CHANGED", "Notion 内容在生成预览期间发生变化，请重试")
    except PreviewValidationError as exc:
        return _error(422, "PREVIEW_CONTENT_INVALID", str(exc))
    except NotionResponseTooLargeError:
        return _error(422, "PREVIEW_CONTENT_TOO_LARGE", "Notion 页面超过预览大小限制")
    except Exception:
        return _error(502, "PREVIEW_FAILED", "微信预览生成失败，请检查集成和渲染器")
    return PreviewResponse(html=html)


@router.post("/{article_id}/portable-markdown", response_model=PortableMarkdownResponse)
async def get_portable_markdown(
    article_id: UUID,
    session: SessionDep,
    factory: SessionFactoryDep,
) -> PortableMarkdownResponse | JSONResponse:
    article = await ArticleQuery(session).get(article_id)
    if article is None:
        return _error(404, "ARTICLE_NOT_FOUND", "稿件不存在")
    try:
        snapshot = await CurrentSnapshotGate(factory, ConfiguredContentSource(factory)).require(article.id)
    except SnapshotUnavailableError as exc:
        return _error(409, exc.code, exc.message)
    return PortableMarkdownResponse(markdown=snapshot.portable_markdown)


@router.post("/{article_id}/jobs/{job_id}/retry", response_model=ActionResult)
async def retry_job(
    article_id: UUID,
    job_id: UUID,
    body: RetryRequest,
    factory: SessionFactoryDep,
) -> ActionResult | JSONResponse:
    try:
        channels = _parse_channels(body.channels)
        await ArticleActionService(factory).retry(article_id, job_id, channels)
    except ActionConflictError as exc:
        return _error(409 if exc.code != "JOB_NOT_FOUND" else 404, exc.code, exc.message)
    return ActionResult(job_id=job_id)


@router.post("/{article_id}/jobs/{job_id}/cancel", response_model=ActionResult)
async def cancel_job(
    article_id: UUID,
    job_id: UUID,
    factory: SessionFactoryDep,
) -> ActionResult | JSONResponse:
    try:
        await ArticleActionService(factory).cancel(article_id, job_id)
    except ActionConflictError as exc:
        return _error(409 if exc.code != "JOB_NOT_FOUND" else 404, exc.code, exc.message)
    return ActionResult(job_id=job_id)


def _parse_channels(raw: list[str]) -> list[TargetChannel]:
    if len(set(raw)) != len(raw):
        raise ActionConflictError("CHANNEL_DUPLICATED", "重试渠道不能重复")
    try:
        return [TargetChannel(value) for value in raw]
    except ValueError as exc:
        raise ActionConflictError("CHANNEL_UNSUPPORTED", "包含不支持的目标渠道") from exc


def _article_summary(
    article: Article,
    latest_blog: PublicationJob | None = None,
    latest_wechat: PublicationJob | None = None,
    latest_sync_run: ContentSyncRun | None = None,
    current_snapshot: ContentSnapshot | None = None,
) -> ArticleSummary:
    return ArticleSummary.model_validate(
        {
            "id": article.id,
            "title": article.title,
            "notion_url": article.notion_url,
            "notion_status": article.notion_status,
            "automation_status": article.automation_status,
            "target_channels": article.target_channels,
            "planned_at": article.planned_at,
            "notion_last_edited_at": article.notion_last_edited_at,
            "last_synced_at": article.last_synced_at,
            "cover_valid": bool(article.cover_metadata.get("name")),
            "content_sync": _content_sync_summary(article, latest_sync_run, current_snapshot),
            "blog_status": latest_blog.blog_status if latest_blog else None,
            "wechat_status": latest_wechat.wechat_status if latest_wechat else None,
        }
    )


def _article_detail(
    article: Article,
    jobs: list[PublicationJob],
    jobs_total: int,
    latest: PublicationJob | None,
    latest_sync_run: ContentSyncRun | None,
    current_snapshot: ContentSnapshot | None,
) -> ArticleDetail:
    summary = _article_summary(article, latest, latest, latest_sync_run, current_snapshot).model_dump()
    errors = _validation_items(latest, "errors")
    if article.last_error and not errors:
        errors = [{"code": "publication_blocked", "message": _safe_error(article.last_error), "field": "job"}]
    return ArticleDetail(
        **summary,
        notion_metadata=article.notion_metadata,
        cover_metadata=_safe_cover(article.cover_metadata),
        last_error=_safe_error(article.last_error),
        content_hash=latest.content_hash if latest else None,
        validation_errors=errors,
        validation_warnings=_validation_items(latest, "warnings"),
        blog=_channel_result(latest, "blog") if latest else None,
        wechat=_channel_result(latest, "wechat") if latest else None,
        jobs=[_job_summary(job) for job in jobs],
        jobs_total=jobs_total,
        jobs_has_more=jobs_total > len(jobs),
    )


def _content_sync_summary(
    article: Article,
    latest_run: ContentSyncRun | None,
    current_snapshot: ContentSnapshot | None,
) -> ContentSyncSummary:
    current_is_valid = (
        article.content_sync_status == ContentSyncStatus.SYNCED
        and current_snapshot is not None
        and current_snapshot.source_last_edited_at == article.notion_last_edited_at
    )
    snapshot_summary = None
    if current_snapshot is not None:
        metadata = current_snapshot.snapshot_metadata
        snapshot_summary = CurrentSnapshotSummary(
            id=current_snapshot.id,
            synced_at=current_snapshot.synced_at,
            source_last_edited_at=current_snapshot.source_last_edited_at,
            content_hash=current_snapshot.content_hash,
            character_count=_metadata_count(metadata, "character_count"),
            media_count=_metadata_count(metadata, "media_count"),
        )
    run_summary = None
    if latest_run is not None:
        run_summary = ContentSyncRunSummary.model_validate(latest_run, from_attributes=True)
    return ContentSyncSummary(
        status=article.content_sync_status,
        outputs_enabled=current_is_valid,
        error=_safe_error(article.content_sync_error),
        current_snapshot=snapshot_summary,
        latest_run=run_summary,
    )


def _metadata_count(metadata: dict[str, object], key: str) -> int:
    value = metadata.get(key)
    return value if isinstance(value, int) and value >= 0 else 0


def _job_summary(job: PublicationJob) -> JobSummary:
    return JobSummary(
        id=job.id,
        overall_status=job.overall_status,
        target_channels=job.target_channels,
        scheduled_at=job.scheduled_at,
        content_hash=job.content_hash,
        blog_status=job.blog_status,
        wechat_status=job.wechat_status,
    )


def _job_detail(job: PublicationJob) -> JobDetail:
    return JobDetail(
        **_job_summary(job).model_dump(),
        article_id=job.article_id,
        snapshot_metadata={
            "title": job.snapshot_metadata.get("title"),
            "categories": job.snapshot_metadata.get("categories"),
        },
        blog=_channel_result(job, "blog"),
        wechat=_channel_result(job, "wechat"),
        wechat_html=job.wechat_html,
        attempt_count=job.attempt_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _channel_result(job: PublicationJob, name: str) -> ChannelResult:
    status = job.blog_status if name == "blog" else job.wechat_status
    error = job.blog_error if name == "blog" else job.wechat_error
    result = job.blog_result if name == "blog" else job.wechat_result
    return ChannelResult(
        status=status,
        error=_safe_error(error),
        result={key: value for key, value in result.items() if key in _SAFE_RESULT_KEYS},
    )


def _validation_items(job: PublicationJob | None, key: str) -> list[dict[str, Any]]:
    if job is None:
        return []
    validation = job.snapshot_metadata.get("validation")
    items = validation.get(key) if isinstance(validation, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _safe_cover(value: dict[str, object]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key in {"name", "expiry_time"}}


def _safe_error(value: str | None) -> str | None:
    if value is None:
        return None
    without_urls = re.sub(r"https?://\S+", "[已脱敏地址]", value)
    return re.sub(r"(?i)(bearer|token|secret|password)\s*[:=]?\s*\S+", r"\1=***", without_urls)[:1000]


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message})
