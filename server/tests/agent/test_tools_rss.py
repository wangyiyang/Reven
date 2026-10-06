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


class _FakeEmbeddingRefresher:
    """KeywordEmbeddingHooks 测试替身：记录调用，可注入 refresh 失败与命中数。"""

    def __init__(self, *, hits: int | None = 0, fail_refresh: bool = False) -> None:
        self._hits = hits
        self._fail_refresh = fail_refresh
        self.refresh_calls = 0
        self.estimate_calls: list[UUID] = []

    async def refresh(self, *, force: bool = False) -> int:
        self.refresh_calls += 1
        if self._fail_refresh:
            raise RuntimeError("SILICONFLOW_API_KEY_NOT_CONFIGURED")
        return 1

    async def estimate_hits(self, keyword_id: UUID) -> int | None:
        self.estimate_calls.append(keyword_id)
        return self._hits


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

    assert updated == {
        "id": str(keyword_id),
        "term": "LLM 应用",
        "kind": "negative",
        "enabled": False,
        "embedding_status": "pending",
    }


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
        # RSS 关键词 4 个 + CRM 人才库 15 个（#169）+ talents 人才库 18 个（#201 P3），注册完整性以名集合断言
        assert {tool.name for tool in tools} == {
            "rss_keyword_create",
            "rss_keyword_list",
            "rss_keyword_update",
            "rss_keyword_delete",
            "crm_customer_list",
            "crm_customer_get",
            "crm_customer_create",
            "crm_customer_update",
            "crm_customer_delete",
            "crm_contact_list",
            "crm_contact_create",
            "crm_contact_update",
            "crm_contact_delete",
            "crm_follow_up_list",
            "crm_follow_up_create",
            "crm_follow_up_update",
            "crm_follow_up_delete",
            "crm_lead_funnel",
            "crm_due_follow_ups",
            "talent_list",
            "talent_get",
            "talent_create",
            "talent_update",
            "talent_delete",
            "talent_interaction_list",
            "talent_interaction_create",
            "talent_interaction_update",
            "talent_interaction_delete",
            "talent_experience_list",
            "talent_experience_create",
            "talent_experience_update",
            "talent_experience_delete",
            "talent_education_list",
            "talent_education_create",
            "talent_education_update",
            "talent_education_delete",
            "talent_import_profile",
        }
        with pytest.raises(ToolError, match="MCP_WRITE_CONTEXT_REQUIRED"):
            await client.call_tool("rss_keyword_create", {"term": " MCP 协议 ", "kind": "positive"})
        assert await RssKeywordTools(session_factory).list_keywords() == []
        await RssKeywordTools(session_factory).create_keyword(term="MCP 协议", kind="positive")
        listed = await client.call_tool("rss_keyword_list", {})
        assert [item["term"] for item in listed.data] == ["MCP 协议"]


@pytest.mark.anyio
async def test_create_triggers_refresh_and_reports_hit_count(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    refresher = _FakeEmbeddingRefresher(hits=7)
    tools = RssKeywordTools(session_factory, refresher)

    created = await tools.create_keyword(term="具身智能", kind="positive")

    assert refresher.refresh_calls == 1
    assert refresher.estimate_calls == [UUID(str(created["id"]))]
    assert created["embedding_status"] == "ready"
    assert created["hit_count"] == 7


@pytest.mark.anyio
async def test_create_degrades_to_pending_when_refresh_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    refresher = _FakeEmbeddingRefresher(fail_refresh=True)
    tools = RssKeywordTools(session_factory, refresher)

    created = await tools.create_keyword(term="具身智能", kind="positive")

    # 词已入库且工具返回成功，仅标注 pending（不静默、不抛出）
    assert created["embedding_status"] == "pending"
    assert created["hit_count"] is None
    assert refresher.estimate_calls == []
    listed = await tools.list_keywords()
    assert [item["term"] for item in listed] == ["具身智能"]


@pytest.mark.anyio
async def test_create_marks_pending_when_refresher_not_wired(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    created = await RssKeywordTools(session_factory).create_keyword(term="具身智能", kind="positive")

    assert created["embedding_status"] == "pending"
    assert created["hit_count"] is None


@pytest.mark.anyio
async def test_update_triggers_refresh_and_marks_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    refresher = _FakeEmbeddingRefresher()
    tools = RssKeywordTools(session_factory, refresher)
    created = await tools.create_keyword(term="LLM", kind="positive")

    updated = await tools.update_keyword(UUID(str(created["id"])), term="LLM 应用", kind="positive", enabled=True)

    assert refresher.refresh_calls == 2
    assert updated["embedding_status"] == "ready"
    assert "hit_count" not in updated


@pytest.mark.anyio
async def test_create_conflict_still_raises_before_refresh(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    refresher = _FakeEmbeddingRefresher()
    tools = RssKeywordTools(session_factory, refresher)
    await tools.create_keyword(term="AI Agent", kind="positive")

    with pytest.raises(ToolError) as exc_info:
        await tools.create_keyword(term="ai  agent ", kind="negative")

    assert "RSS_KEYWORD_CONFLICT" in str(exc_info.value)
    assert refresher.refresh_calls == 1
