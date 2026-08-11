"""Public workbench API schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiError(BaseModel):
    code: str
    message: str


class CurrentSnapshotSummary(BaseModel):
    id: UUID
    synced_at: datetime
    source_last_edited_at: datetime
    content_hash: str
    character_count: int
    media_count: int


class ContentSyncRunSummary(BaseModel):
    id: UUID
    status: str
    stage: str
    progress_current: int
    progress_total: int
    current_media: str | None
    error_stage: str | None
    error_code: str | None
    error_message: str | None
    error_media: str | None
    retryable: bool
    attempt_count: int
    created_at: datetime
    updated_at: datetime


class ContentSyncSummary(BaseModel):
    status: str
    outputs_enabled: bool
    error: str | None
    current_snapshot: CurrentSnapshotSummary | None
    latest_run: ContentSyncRunSummary | None


class ArticleSummary(BaseModel):
    id: UUID
    title: str
    notion_url: str
    notion_status: str
    automation_status: str
    target_channels: list[str]
    planned_at: datetime | None
    notion_last_edited_at: datetime
    last_synced_at: datetime
    cover_valid: bool
    content_sync: ContentSyncSummary
    blog_status: str | None = None
    wechat_status: str | None = None


class ArticleList(BaseModel):
    items: list[ArticleSummary]
    total: int
    page: int
    page_size: int


class JobSummary(BaseModel):
    id: UUID
    overall_status: str
    target_channels: list[str]
    scheduled_at: datetime
    content_hash: str | None
    blog_status: str
    wechat_status: str


class ChannelResult(BaseModel):
    status: str
    error: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class ArticleDetail(ArticleSummary):
    notion_url: str
    notion_metadata: dict[str, Any]
    cover_metadata: dict[str, Any]
    last_error: str | None
    content_hash: str | None
    validation_errors: list[dict[str, Any]]
    validation_warnings: list[dict[str, Any]]
    blog: ChannelResult | None
    wechat: ChannelResult | None
    jobs: list[JobSummary]
    jobs_total: int
    jobs_has_more: bool


class JobDetail(JobSummary):
    model_config = ConfigDict(extra="forbid")

    article_id: UUID
    snapshot_metadata: dict[str, Any]
    blog: ChannelResult
    wechat: ChannelResult
    wechat_html: str | None
    attempt_count: int
    created_at: datetime
    updated_at: datetime


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channels: list[str] = Field(min_length=1, max_length=2)


class ActionResult(BaseModel):
    ok: bool = True
    job_id: UUID


class PreviewResponse(BaseModel):
    html: str


class PortableMarkdownResponse(BaseModel):
    markdown: str
