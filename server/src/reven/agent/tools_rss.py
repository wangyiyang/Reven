"""RSS 关键词 dsh 工具集：直连 RssSettingsRepository，冲突映射为模型可读错误。"""

from typing import Annotated, Literal
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.rss.models import RssKeyword
from reven.rss.normalization import normalize_keyword
from reven.rss.repository import RssSettingsConflictError, RssSettingsRepository

KeywordKind = Literal["positive", "negative"]

TermParam = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
KindParam = Annotated[KeywordKind, Field(description="positive=正向关键词，negative=反向关键词")]
EnabledParam = Annotated[bool, Field(description="是否启用")]
KeywordIdParam = Annotated[UUID, Field(description="关键词 ID（由 rss_keyword_create / rss_keyword_list 返回）")]

KeywordPayload = dict[str, object]


def register_rss_tools(mcp: FastMCP, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """把 RSS 关键词 CRUD 注册为 MCP 工具（模型侧呈现为 mcp__reven__rss_keyword_*）。"""
    tools = RssKeywordTools(session_factory)
    mcp.tool(tools.create_keyword, name="rss_keyword_create")
    mcp.tool(tools.list_keywords, name="rss_keyword_list")
    mcp.tool(tools.update_keyword, name="rss_keyword_update")
    mcp.tool(tools.delete_keyword, name="rss_keyword_delete")


class RssKeywordTools:
    """RSS 关键词工具实现；每次调用独立开库会话并提交，与 API 路由的写语义一致。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_keyword(self, term: TermParam, kind: KindParam, enabled: EnabledParam = True) -> KeywordPayload:
        """新建一个 RSS 关键词。同一关键词（归一化后）不能同时存在于正向和反向列表。"""
        _validate_normalized_length(term)
        async with self._session_factory() as session:
            try:
                keyword = await RssSettingsRepository(session).create_keyword(term=term, kind=kind, enabled=enabled)
            except RssSettingsConflictError as exc:
                raise _conflict_tool_error(exc) from exc
            await session.commit()
        return _serialize(keyword)

    async def list_keywords(self) -> list[KeywordPayload]:
        """列出全部 RSS 关键词（含 id、kind、enabled），供后续 update/delete 取用。"""
        async with self._session_factory() as session:
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
        async with self._session_factory() as session:
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
            await session.commit()
        return _serialize(keyword)

    async def delete_keyword(self, keyword_id: KeywordIdParam) -> KeywordPayload:
        """删除一个关键词。"""
        async with self._session_factory() as session:
            deleted = await RssSettingsRepository(session).delete_keyword(keyword_id)
            if not deleted:
                raise _not_found_tool_error(keyword_id)
            await session.commit()
        return {"id": str(keyword_id), "deleted": True}


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
