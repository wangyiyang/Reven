"""Public workbench API schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiError(BaseModel):
    code: str
    message: str


class ArticleSummary(BaseModel):
    id: UUID
    title: str
    notion_status: str
    automation_status: str
    target_channels: list[str]
    planned_at: datetime | None
    notion_last_edited_at: datetime


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
