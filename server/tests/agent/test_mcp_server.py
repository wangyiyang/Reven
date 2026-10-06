"""Agent MCP 端点测试：Bearer 鉴权、中间件旁路语义与真实 HTTP 回路。"""

import asyncio
import base64
import os
import socket
from collections.abc import AsyncIterator, Iterator

import anyio
import pytest
import uvicorn
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.exceptions import ToolError
from reven.agent.mcp_server import AGENT_MCP_ENDPOINT_PATH, create_agent_mcp_app
from reven.agent.tools_rss import RssKeywordTools
from reven.app import create_app
from reven.config import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_MCP_TOKEN = "test-mcp-token"
INIT_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def mcp_client() -> Iterator[TestClient]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    settings = Settings(
        database_url=database_url,
        reven_master_key=base64.urlsafe_b64encode(b"t" * 32).decode(),
        reven_admin_password="test-admin-password",
        agent_mcp_token=TEST_MCP_TOKEN,
        agent_api_key=None,
        _env_file=None,
    )
    engine = create_async_engine(database_url, poolclass=NullPool)

    async def _reset() -> None:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE rss_keywords RESTART IDENTITY CASCADE"))

    asyncio.run(_reset())
    app = create_app(
        start_background_tasks=False,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        public_base_url="https://reven.wangyiyang.cc",
        settings=settings,
    )
    with TestClient(app, base_url="http://testserver") as client:
        yield client
    asyncio.run(engine.dispose())


@pytest.fixture
async def mcp_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE rss_keywords RESTART IDENTITY CASCADE"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def test_mcp_endpoint_rejects_requests_without_token(mcp_client: TestClient) -> None:
    # 无会话 cookie、无 Origin/CSRF 头：既不能被 AuthMiddleware/CSRF 拦截，也不能匿名通过 Bearer
    response = mcp_client.post(AGENT_MCP_ENDPOINT_PATH, json=INIT_PAYLOAD, headers=MCP_HEADERS)

    assert response.status_code == 401


def test_mcp_endpoint_rejects_wrong_token(mcp_client: TestClient) -> None:
    response = mcp_client.post(
        AGENT_MCP_ENDPOINT_PATH,
        json=INIT_PAYLOAD,
        headers={**MCP_HEADERS, "Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401


def test_mcp_endpoint_accepts_internal_bearer_token(mcp_client: TestClient) -> None:
    response = mcp_client.post(
        AGENT_MCP_ENDPOINT_PATH,
        json=INIT_PAYLOAD,
        headers={**MCP_HEADERS, "Authorization": f"Bearer {TEST_MCP_TOKEN}"},
    )

    assert response.status_code == 200
    assert "serverInfo" in response.text


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.anyio
async def test_fastmcp_client_calls_tools_over_http_with_bearer_token(
    mcp_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bearer 允许真实 HTTP 读取，不能绕过可信运行入口直接写入。"""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    await RssKeywordTools(mcp_session_factory).create_keyword(term="AI Agent", kind="positive")
    mcp_app = create_agent_mcp_app(mcp_session_factory, TEST_MCP_TOKEN)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(mcp_app, host="127.0.0.1", port=port, log_level="error"))
    serve_task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await anyio.sleep(0.05)
    assert server.started
    try:
        async with Client(f"http://127.0.0.1:{port}/mcp", auth=TEST_MCP_TOKEN) as client:
            with pytest.raises(ToolError, match="MCP_WRITE_CONTEXT_REQUIRED"):
                await client.call_tool("rss_keyword_create", {"term": "无上下文写入", "kind": "positive"})
            listed = await client.call_tool("rss_keyword_list", {})
            assert [item["term"] for item in listed.data] == ["AI Agent"]
    finally:
        server.should_exit = True
        await serve_task
