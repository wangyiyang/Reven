"""RSS 候选审核领域服务：保存素材、忽略。"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.rss.models import RssItem
from reven.scheduling import utc_now


class CandidateReviewError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class CandidateReviewService:
    """候选审核核心操作：飞书机器人、REST 路由、未来 MCP Server 共用。"""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._factory = factory

    async def approve(self, item_id: UUID) -> RssItem:
        """保存候选为素材；重复采纳保留首次保存时间。"""
        async with self._factory.begin() as session:
            item = await session.get(RssItem, item_id, with_for_update=True)
            if item is None:
                raise CandidateReviewError("RSS_CANDIDATE_NOT_FOUND", "RSS 候选不存在", status_code=404)
            if item.status == "saved":
                return item
            if item.status != "candidate":
                raise CandidateReviewError("RSS_CANDIDATE_NOT_SAVABLE", "RSS 候选当前状态不允许保存")
            item.status = "saved"
            item.saved_at = utc_now()
            return item

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
