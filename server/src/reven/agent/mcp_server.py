"""FastAPI 进程内 MCP streamable-http 端点：dsh loopback 工具回调入口（#123 方案 B2）。

挂点语义：
- 挂载在 AGENT_MCP_MOUNT_PREFIX 下，对外完整路径 AGENT_MCP_ENDPOINT_PATH（非 /api/*），
  因此不经过 AuthMiddleware 的会话拦截；由 StaticTokenVerifier 的 Bearer token 独立鉴权。
- CsrfOriginMiddleware 对该路径豁免（Bearer 鉴权的机器端点无 CSRF 威胁模型），
  豁免由 app.py 装配时显式传入。
- token 缺省为进程内随机生成值，仅经 env 注入 dsh 子进程：不进 git、不写日志、公网匿名不可用。
"""

import secrets
from dataclasses import dataclass

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from fastmcp.server.http import StarletteWithLifespan
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.tools_crm import register_crm_tools
from reven.agent.tools_rss import KeywordEmbeddingHooks, register_rss_tools
from reven.agent.tools_talents import register_talents_tools
from reven.config import DEFAULT_AGENT_MCP_URL, Settings

AGENT_MCP_MOUNT_PREFIX = "/agent"
AGENT_MCP_ENDPOINT_PATH = f"{AGENT_MCP_MOUNT_PREFIX}/mcp"

_MCP_CLIENT_ID = "dsh-loopback"


@dataclass(frozen=True, slots=True)
class AgentMcpContext:
    """dsh 子进程回调本进程 MCP 端点所需的地址与凭证。"""

    url: str
    token: str


def resolve_agent_mcp_context(settings: Settings | None) -> AgentMcpContext:
    """解析 loopback 上下文；token 缺省时生成进程内随机值（每次重启轮换）。"""
    configured = settings.agent_mcp_token if settings is not None else None
    token = configured.get_secret_value() if configured is not None else secrets.token_hex(32)
    url = settings.agent_mcp_url if settings is not None else DEFAULT_AGENT_MCP_URL
    return AgentMcpContext(url=url, token=token)


def create_agent_mcp_server(
    session_factory: async_sessionmaker[AsyncSession],
    token: str,
    *,
    embedding_refresher: KeywordEmbeddingHooks | None = None,
) -> FastMCP:
    """构建注册了 Reven 工具集、仅接受内部 Bearer token 的 FastMCP 实例。"""
    verifier = StaticTokenVerifier(tokens={token: {"client_id": _MCP_CLIENT_ID, "scopes": []}})
    mcp = FastMCP("reven", auth=verifier)
    register_rss_tools(mcp, session_factory, embedding_refresher=embedding_refresher)
    register_crm_tools(mcp, session_factory)
    register_talents_tools(mcp, session_factory)
    return mcp


def create_agent_mcp_app(
    session_factory: async_sessionmaker[AsyncSession],
    token: str,
    *,
    embedding_refresher: KeywordEmbeddingHooks | None = None,
) -> StarletteWithLifespan:
    """构建可挂载进 FastAPI 的 MCP ASGI 子应用；调用方必须进入其 lifespan（驱动会话管理器）。"""
    return create_agent_mcp_server(
        session_factory,
        token,
        embedding_refresher=embedding_refresher,
    ).http_app(path="/mcp")
