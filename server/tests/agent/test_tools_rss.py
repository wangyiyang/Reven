"""RSS 关键词 MCP 工具测试：CRUD 行为、错误映射与 MCP 协议面。"""

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from reven.agent.mcp_server import create_agent_mcp_server
from reven.agent.tools_rss import RssKeywordTools
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping integration tests")
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE rss_keywords RESTART IDENTITY CASCADE"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.anyio
async def test_create_and_list_keywords_roundtrip(session_factory: async_sessionmaker[AsyncSession]) -> None:
    tools = RssKeywordTools(session_factory)

    created = await tools.create_keyword(term="AI Agent", kind="positive")
    negative = await tools.create_keyword(term="广告", kind="negative", enabled=False)

    assert created["term"] == "AI Agent"
    assert created["kind"] == "positive"
    assert created["enabled"] is True
    assert negative["term"] == "广告"
    listed = await tools.list_keywords()
    assert {(item["term"], item["kind"], item["enabled"]) for item in listed} == {
        ("AI Agent", "positive", True),
        ("广告", "negative", False),
    }
    assert {item["id"] for item in listed} == {created["id"], negative["id"]}


@pytest.mark.anyio
async def test_create_duplicate_keyword_raises_model_readable_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tools = RssKeywordTools(session_factory)
    await tools.create_keyword(term="AI Agent", kind="positive")

    with pytest.raises(ToolError) as exc_info:
        await tools.create_keyword(term="ai  agent ", kind="negative")

    assert "RSS_KEYWORD_CONFLICT" in str(exc_info.value)


@pytest.mark.anyio
async def test_update_keyword_reclassifies_and_disables(session_factory: async_sessionmaker[AsyncSession]) -> None:
    tools = RssKeywordTools(session_factory)
    created = await tools.create_keyword(term="LLM", kind="positive")
    keyword_id = UUID(str(created["id"]))

    updated = await tools.update_keyword(keyword_id, term="LLM 应用", kind="negative", enabled=False)

    assert updated == {"id": str(keyword_id), "term": "LLM 应用", "kind": "negative", "enabled": False}


@pytest.mark.anyio
async def test_update_missing_keyword_raises_not_found(session_factory: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(ToolError) as exc_info:
        await RssKeywordTools(session_factory).update_keyword(uuid4(), term="x", kind="positive", enabled=True)

    assert "关键词不存在" in str(exc_info.value)


@pytest.mark.anyio
async def test_delete_keyword(session_factory: async_sessionmaker[AsyncSession]) -> None:
    tools = RssKeywordTools(session_factory)
    created = await tools.create_keyword(term="待删除", kind="positive")

    deleted = await tools.delete_keyword(UUID(str(created["id"])))

    assert deleted == {"id": created["id"], "deleted": True}
    assert await tools.list_keywords() == []


@pytest.mark.anyio
async def test_delete_missing_keyword_raises_not_found(session_factory: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(ToolError) as exc_info:
        await RssKeywordTools(session_factory).delete_keyword(uuid4())

    assert "关键词不存在" in str(exc_info.value)


@pytest.mark.anyio
async def test_tools_are_callable_over_mcp_protocol(session_factory: async_sessionmaker[AsyncSession]) -> None:
    mcp = create_agent_mcp_server(session_factory, token="test-token")

    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {
            "rss_keyword_create",
            "rss_keyword_list",
            "rss_keyword_update",
            "rss_keyword_delete",
        }
        # 带空白的输入在 MCP 边界经 pydantic 约束自动 strip（与 API schema 行为一致）
        created = await client.call_tool("rss_keyword_create", {"term": " MCP 协议 ", "kind": "positive"})
        assert created.data["term"] == "MCP 协议"
        listed = await client.call_tool("rss_keyword_list", {})
        assert [item["term"] for item in listed.data] == ["MCP 协议"]
