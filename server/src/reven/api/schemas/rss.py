"""Public schemas for RSS configuration."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl, StringConstraints, field_validator

from reven.rss.normalization import normalize_keyword

SourceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
KeywordTerm = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class RssSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: SourceName
    feed_url: HttpUrl
    enabled: bool = True


class RssSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    feed_url: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class RssKeywordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: KeywordTerm
    kind: Literal["positive", "negative"]
    enabled: bool = True

    @field_validator("term")
    @classmethod
    def validate_normalized_length(cls, term: str) -> str:
        if len(normalize_keyword(term)) > 200:
            raise ValueError("关键词归一化后不能超过 200 个字符")
        return term


class RssKeywordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    term: str
    kind: Literal["positive", "negative"]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class RssCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_name: str
    url: str | None
    title: str
    summary: str
    title_zh: str
    summary_zh: str
    published_at: datetime | None
    status: str
    positive_literal_matches: list[str]
    negative_literal_matches: list[str]
    bm25_score: float
    positive_embedding_score: float
    negative_embedding_score: float
    embedding_model: str | None
    embedding_status: str
    model_status: str
    model_score: float | None
    reason: str | None
    rules_version: str | None
    screening_error: str | None
    push_error: str | None
    notion_url: str | None


class InboxPushResponse(BaseModel):
    item_id: UUID
    notion_page_id: UUID
    notion_url: str


class RssEmbeddingRebuildResponse(BaseModel):
    refreshed: int
    model: str
    dimension: int
