"""Internal value objects for publication preparation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from reven.domain import AutomationStatus, TargetChannel
from reven.integrations.notion.models import MappedNotionPage
from reven.publishing.assets import MaterializedAssets
from reven.publishing.validation import ValidationResult

if TYPE_CHECKING:
    from reven.jobs.brand_preparation import BrandPreparation


@dataclass(frozen=True)
class PrepareResult:
    job_id: UUID
    reused: bool = False
    blocked: bool = False
    validation: ValidationResult | None = None


@dataclass(frozen=True)
class PersistedPreparation:
    result: PrepareResult
    page_id: str | None = None
    status: AutomationStatus | None = None
    reason: str | None = None
    staging_identity: str | None = None
    asset_manifest: list[dict[str, str]] | None = None


@dataclass(frozen=True)
class Preflight:
    job_id: UUID
    article_id: UUID
    notion_page_id: str
    article_updated_at: datetime


@dataclass(frozen=True)
class PreparedWork:
    preflight: Preflight
    mapped: MappedNotionPage | None
    markdown: str
    channels: tuple[TargetChannel, ...]
    unsupported: tuple[str, ...]
    assets: MaterializedAssets | None
    validation: ValidationResult
    brand: BrandPreparation | None = None
