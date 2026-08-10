"""Public schemas for observable content synchronization."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ContentSyncRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    article_id: UUID
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
    created: bool | None = None
