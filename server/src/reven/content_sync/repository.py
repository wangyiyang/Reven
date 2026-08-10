"""Fenced database leases for the serial content-sync worker."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from reven.content_sync.domain import SyncRunStatus, SyncStage
from reven.content_sync.models import ContentSyncRun
from reven.scheduling import database_now

_CLAIM_LOCK_ID = 0x524556454E19


@dataclass(frozen=True)
class ContentSyncClaim:
    run_id: UUID
    article_id: UUID
    lease_token: UUID
    attempt_count: int


class ContentSyncRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim_next(self, *, lease_seconds: int) -> ContentSyncClaim | None:
        locked = await self.session.scalar(select(func.pg_try_advisory_xact_lock(_CLAIM_LOCK_ID)))
        if locked is not True:
            return None
        now = await database_now(self.session)
        if await self._has_active_worker(now):
            return None
        run = await self.session.scalar(self._claimable(now))
        if run is None:
            return None
        token = uuid4()
        run.status = SyncRunStatus.PROCESSING
        run.stage = SyncStage.READING_NOTION
        run.attempt_count += 1
        run.lease_token = token
        run.lease_expires_at = now + timedelta(seconds=lease_seconds)
        run.started_at = run.started_at or now
        run.progress_current = 0
        run.progress_total = 0
        run.current_media = None
        run.error_stage = None
        run.error_code = None
        run.error_message = None
        run.error_media = None
        run.retryable = False
        await self.session.flush()
        return ContentSyncClaim(run.id, run.article_id, token, run.attempt_count)

    async def renew(self, claim: ContentSyncClaim, *, lease_seconds: int) -> bool:
        now = await database_now(self.session)
        result = await self.session.execute(
            update(ContentSyncRun)
            .where(*self._owned_lease(claim, now))
            .values(lease_expires_at=now + timedelta(seconds=lease_seconds))
        )
        return bool(cast(Any, result).rowcount)

    async def progress(
        self,
        claim: ContentSyncClaim,
        *,
        stage: str,
        current: int = 0,
        total: int = 0,
        media: str | None = None,
    ) -> bool:
        now = await database_now(self.session)
        result = await self.session.execute(
            update(ContentSyncRun)
            .where(*self._owned_lease(claim, now))
            .values(
                stage=stage,
                progress_current=current,
                progress_total=total,
                current_media=media,
            )
        )
        return bool(cast(Any, result).rowcount)

    async def owned_run(self, claim: ContentSyncClaim, *, for_update: bool = False) -> ContentSyncRun | None:
        now = await database_now(self.session)
        statement = select(ContentSyncRun).where(*self._owned_lease(claim, now))
        if for_update:
            statement = statement.with_for_update()
        run: ContentSyncRun | None = await self.session.scalar(statement)
        return run

    async def _has_active_worker(self, now: datetime) -> bool:
        active = await self.session.scalar(
            select(ContentSyncRun.id)
            .where(
                ContentSyncRun.status == SyncRunStatus.PROCESSING,
                ContentSyncRun.lease_expires_at >= now,
            )
            .limit(1)
        )
        return active is not None

    @staticmethod
    def _claimable(now: datetime) -> Select[tuple[ContentSyncRun]]:
        return (
            select(ContentSyncRun)
            .where(
                or_(
                    and_(
                        ContentSyncRun.status == SyncRunStatus.WAITING,
                        ContentSyncRun.next_attempt_at <= now,
                    ),
                    and_(
                        ContentSyncRun.status == SyncRunStatus.PROCESSING,
                        ContentSyncRun.lease_expires_at < now,
                    ),
                )
            )
            .order_by(ContentSyncRun.next_attempt_at, ContentSyncRun.created_at, ContentSyncRun.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )

    @staticmethod
    def _owned_lease(claim: ContentSyncClaim, now: datetime) -> tuple[ColumnElement[bool], ...]:
        return (
            ContentSyncRun.id == claim.run_id,
            ContentSyncRun.status == SyncRunStatus.PROCESSING,
            ContentSyncRun.lease_token == claim.lease_token,
            ContentSyncRun.lease_expires_at >= now,
        )
