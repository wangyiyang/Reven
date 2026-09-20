"""候选稿审核领域服务：待审核查询、采纳推送、忽略，与协议适配层零耦合。"""

from collections.abc import Collection
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.rss.inbox import InboxPushResult
from reven.rss.models import RssItem
from reven.scheduling import utc_now


class CandidateReviewError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ReviewInboxPusher(Protocol):
    async def push(self, item_id: UUID) -> InboxPushResult: ...


class CandidateReviewService:
    """候选审核核心操作：飞书机器人、REST 路由、未来 MCP Server 共用。"""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        inbox: ReviewInboxPusher,
    ) -> None:
        self._factory = factory
        self._inbox = inbox

    async def list_pending_review(self) -> list[RssItem]:
        """待审核候选：status=candidate 且未推送过审核卡片，发布时间倒序（NULL 排最后）。"""
        async with self._factory() as session:
            result = await session.scalars(
                select(RssItem)
                .where(RssItem.status == "candidate", RssItem.review_pushed_at.is_(None))
                .order_by(RssItem.published_at.desc().nullslast())
            )
            return list(result)

    async def approve(self, item_id: UUID) -> InboxPushResult:
        """采纳 = 现有 confirm 流程：candidate → pushing → pushed（推 Notion Inbox）。"""
        return await self._inbox.push(item_id)

    async def ignore(self, item_id: UUID) -> RssItem:
        """忽略候选；已忽略幂等返回，其余非候选状态抛领域错误。"""
        async with self._factory.begin() as session:
            item = await session.get(RssItem, item_id, with_for_update=True)
            if item is None:
                raise CandidateReviewError("RSS_CANDIDATE_NOT_FOUND", "RSS 候选不存在", status_code=404)
            if item.status == "ignored":
                return item
            if item.status != "candidate":
                raise CandidateReviewError("RSS_CANDIDATE_NOT_IGNORABLE", "RSS 候选当前状态不允许忽略")
            item.status = "ignored"
            return item

    async def mark_review_pushed(self, item_ids: Collection[UUID]) -> None:
        """批量标记审核卡片已推送（同一事务）；空集合为空操作。"""
        if not item_ids:
            return
        async with self._factory.begin() as session:
            await session.execute(update(RssItem).where(RssItem.id.in_(item_ids)).values(review_pushed_at=utc_now()))
