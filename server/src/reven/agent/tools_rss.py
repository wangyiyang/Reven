"""RSS 关键词工具集：直连 RssSettingsRepository，冲突映射为模型可读错误。

create/update 写库后触发增量 embedding refresh（与 REST /embeddings/rebuild 同一 seam）：
embedder 不可用或刷新失败时词仍入库，响应以 embedding_status="pending" 标注，不静默、不抛出。
"""

import logging
from typing import Annotated, Literal, Protocol
from uuid import UUID

from fastmcp.exceptions import ToolError
from pydantic import Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.tool_binding import ToolSessionBinding
from reven.rss.models import RssKeyword
from reven.rss.normalization import normalize_keyword
from reven.rss.repository import RssSettingsConflictError, RssSettingsRepository

logger = logging.getLogger(__name__)

KeywordKind = Literal["positive", "negative"]

TermParam = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
KindParam = Annotated[KeywordKind, Field(description="positive=正向关键词，negative=反向关键词")]
EnabledParam = Annotated[bool, Field(description="是否启用")]
KeywordIdParam = Annotated[UUID, Field(description="关键词 ID（由 rss_keyword_create / rss_keyword_list 返回）")]

KeywordPayload = dict[str, object]


class KeywordEmbeddingHooks(Protocol):
    """关键词 embedding 生效钩子：写后增量 refresh；命中数估计供加词话术引用。"""

    async def refresh(self, *, force: bool = False) -> int: ...

    async def estimate_hits(self, keyword_id: UUID) -> int | None: ...


class RssKeywordTools(ToolSessionBinding):
    """单独调用自行提交；Agent 绑定真实 session 时由操作执行器提交。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_refresher: KeywordEmbeddingHooks | None = None,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        super().__init__(session_factory, session=session)
        self._embedding_refresher = embedding_refresher

    async def create_keyword(self, term: TermParam, kind: KindParam, enabled: EnabledParam = True) -> KeywordPayload:
        """新建一个 RSS 关键词。同一关键词（归一化后）不能同时存在于正向和反向列表。

        响应含 embedding_status（ready/pending）与 hit_count（近期条目库的语义命中数估计，
        不可估计时为 null）。
        """
        _validate_normalized_length(term)
        async with self._session() as session:
            try:
                keyword = await RssSettingsRepository(session).create_keyword(term=term, kind=kind, enabled=enabled)
            except RssSettingsConflictError as exc:
                raise _conflict_tool_error(exc) from exc
            self._record_entity(keyword)
            await self._commit(session)
        return await self._write_payload(keyword, include_hits=True)

    async def list_keywords(self) -> list[KeywordPayload]:
        """列出全部 RSS 关键词（含 id、kind、enabled），供后续 update/delete 取用。"""
        async with self._session() as session:
            keywords = await RssSettingsRepository(session).list_keywords()
        return [_serialize(keyword) for keyword in keywords]

    async def update_keyword(
        self,
        keyword_id: KeywordIdParam,
        term: TermParam,
        kind: KindParam,
        enabled: EnabledParam,
    ) -> KeywordPayload:
        """全量更新一个关键词。先调用 rss_keyword_list 获取现状，再在此基础上修改。"""
        _validate_normalized_length(term)
        async with self._session() as session:
            try:
                keyword = await RssSettingsRepository(session).update_keyword(
                    keyword_id,
                    term=term,
                    kind=kind,
                    enabled=enabled,
                )
            except RssSettingsConflictError as exc:
                raise _conflict_tool_error(exc) from exc
            if keyword is None:
                raise _not_found_tool_error(keyword_id)
            self._record_entity(keyword)
            await self._commit(session)
        return await self._write_payload(keyword, include_hits=False)

    async def delete_keyword(self, keyword_id: KeywordIdParam) -> KeywordPayload:
        """删除一个关键词。"""
        async with self._session() as session:
            deleted = await RssSettingsRepository(session).delete_keyword(keyword_id)
            if not deleted:
                raise _not_found_tool_error(keyword_id)
            self._record_id(RssKeyword.__tablename__, keyword_id)
            await self._commit(session)
        return {"id": str(keyword_id), "deleted": True}

    async def _write_payload(self, keyword: RssKeyword, *, include_hits: bool) -> KeywordPayload:
        payload = {**_serialize(keyword), "embedding_status": "pending"}
        if include_hits:
            payload["hit_count"] = None
        return await self.refresh_result(payload) if self._commits else payload

    async def refresh_result(self, payload: KeywordPayload) -> KeywordPayload:
        """补做提交后 embedding 工作；重放只使用保存的关键词 ID，不再执行 CRUD。"""
        if payload.get("embedding_status") == "ready":
            return payload
        result = dict(payload)
        result["embedding_status"] = await self._refresh_embedding()
        if "hit_count" in result and result["embedding_status"] == "ready":
            result["hit_count"] = await self._estimate_hits(UUID(str(result["id"])))
        return result

    async def _refresh_embedding(self) -> str:
        """增量补算关键词 embedding；未装配或失败时降级 pending（词已入库，下轮每日调度兜底）。"""
        refresher = self._embedding_refresher
        if refresher is None:
            return "pending"
        try:
            await refresher.refresh()
        except Exception as exc:
            logger.warning("关键词 embedding 刷新失败，按 pending 降级（error_type=%s）", type(exc).__name__)
            return "pending"
        return "ready"

    async def _estimate_hits(self, keyword_id: UUID) -> int | None:
        """命中数估计；refresher 未装配或估计失败返回 None，由 Agent 话术省略。"""
        refresher = self._embedding_refresher
        if refresher is None:
            return None
        try:
            return await refresher.estimate_hits(keyword_id)
        except Exception as exc:
            logger.warning("关键词命中数估计失败（error_type=%s）", type(exc).__name__)
            return None


def _serialize(keyword: RssKeyword) -> KeywordPayload:
    return {
        "id": str(keyword.id),
        "term": keyword.term,
        "kind": keyword.kind,
        "enabled": keyword.enabled,
    }


def _validate_normalized_length(term: str) -> None:
    if len(normalize_keyword(term)) > 200:
        raise ToolError("关键词归一化后不能超过 200 个字符")


def _conflict_tool_error(exc: RssSettingsConflictError) -> ToolError:
    return ToolError(f"{exc.message}（{exc.code}）：可先调用 rss_keyword_list 查看已有关键词，删除冲突项后重试")


def _not_found_tool_error(keyword_id: UUID) -> ToolError:
    return ToolError(f"关键词不存在（id={keyword_id}），请先调用 rss_keyword_list 确认可用的关键词 ID")
