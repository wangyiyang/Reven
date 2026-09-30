import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial
from typing import cast

from fastapi import FastAPI
from fastmcp.server.http import StarletteWithLifespan
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from reven.agent import AgentRuntime, resolve_agent_config, resolve_agent_model_config
from reven.agent.mcp_server import (
    AGENT_MCP_ENDPOINT_PATH,
    AGENT_MCP_MOUNT_PREFIX,
    AgentMcpContext,
    create_agent_mcp_app,
    resolve_agent_mcp_context,
)
from reven.agent.runtime import ModelConfigResolver
from reven.agent.service import AgentService
from reven.api.routes.agent import router as agent_router
from reven.api.routes.auth import router as auth_router
from reven.api.routes.brand import router as brand_router
from reven.api.routes.crm import router as crm_router
from reven.api.routes.finance import router as finance_router
from reven.api.routes.integrations import router as integrations_router
from reven.api.routes.projects import router as projects_router
from reven.api.routes.rss import router as rss_router
from reven.api.routes.sops import router as sops_router
from reven.api.routes.system import router as system_router
from reven.api.routes.talents import router as talents_router
from reven.background import build_background_runner
from reven.config import Settings, get_settings
from reven.db import create_session_factory
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.chat_dispatcher import FeishuChatDispatcher
from reven.integrations.feishu_bot.supervisor import FeishuBotSupervisor
from reven.provider_clients import ProviderClients
from reven.rss.factory import KeywordEmbeddingRefresher
from reven.security.auth import AuthMiddleware
from reven.security.csrf import CsrfOriginMiddleware
from reven.security.headers import SecurityHeadersMiddleware

logger = logging.getLogger(__name__)


class RunnerProtocol:
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


def _resolve_settings(
    override: Settings | None,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None,
    start_background_tasks: bool,
    runner: RunnerProtocol | None,
) -> Settings | None:
    """组合根唯一 Settings 解析：显式注入优先，否则经 get_settings() 解析一次。

    降级形态（注入 factory 或 runner）允许解析失败——集成/Agent 停用不阻断进程；
    生产形态（自建 factory 且跑后台任务）保持启动期 ValidationError 报错不变。
    """
    if override is not None:
        return override
    try:
        return get_settings()
    except ValidationError:
        if session_factory is None and start_background_tasks and runner is None:
            raise
        return None


def _resolve_factory(
    session_factory: async_sessionmaker[AsyncSession] | None,
    settings: Settings | None,
) -> async_sessionmaker[AsyncSession] | None:
    if session_factory is not None:
        return session_factory
    if settings is None:
        return None
    return create_session_factory(settings)


def _mount_agent_mcp(
    current_app: FastAPI,
    factory: async_sessionmaker[AsyncSession] | None,
    settings: Settings | None,
    embedding_refresher: KeywordEmbeddingRefresher | None,
) -> tuple[AgentMcpContext | None, StarletteWithLifespan | None]:
    """有数据库时装配进程内 MCP 端点（dsh 工具回调入口）；无库时不挂载，dsh 也不带工具 patch。"""
    if factory is None:
        return None, None
    context = resolve_agent_mcp_context(settings)
    mcp_app = create_agent_mcp_app(factory, context.token, embedding_refresher=embedding_refresher)
    current_app.mount(AGENT_MCP_MOUNT_PREFIX, mcp_app)
    return context, mcp_app


async def _build_agent_runtime(
    credentials: IntegrationCredentials | None,
    settings: Settings | None,
    mcp: AgentMcpContext | None,
) -> AgentRuntime:
    if settings is None:
        return AgentRuntime(None)
    config = await resolve_agent_config(credentials, settings)
    # 有凭证 seam 时接入模型注册表解析器，支持 /model 指令的会话级模型切换（#163）；
    # 无库/降级形态为 None：override 请求会被 AgentModelUnavailableError 明确拒绝
    resolver: ModelConfigResolver | None = None
    if credentials is not None:
        resolver = partial(resolve_agent_model_config, credentials, settings)
    return AgentRuntime(config, mcp=mcp, model_resolver=resolver)


def _build_provider_clients(
    factory: async_sessionmaker[AsyncSession] | None,
    settings: Settings | None,
) -> ProviderClients | None:
    """构建集成凭证/客户端单例；无库、无配置或密钥不可用时降级为 None（集成能力停用，不阻断进程）。"""
    if factory is None or settings is None:
        return None
    try:
        credentials = IntegrationCredentials(factory, settings)
    except Exception as exc:
        logger.warning("集成凭证不可用，集成相关能力降级（error_type=%s）", type(exc).__name__)
        return None
    return ProviderClients(credentials, settings)


def _build_feishu_bot_supervisor(
    current_app: FastAPI,
    factory: async_sessionmaker[AsyncSession] | None,
    credentials: IntegrationCredentials | None,
    agent_runtime: AgentRuntime,
) -> FeishuBotSupervisor | None:
    """创建飞书机器人长连接 supervisor；无库或凭证降级时停用，不阻断进程。"""
    if factory is None or credentials is None:
        return None
    chat_dispatcher = FeishuChatDispatcher(credentials, AgentService(agent_runtime))
    supervisor = FeishuBotSupervisor(credentials, chat_dispatcher=chat_dispatcher)
    current_app.state.feishu_bot_supervisor = supervisor
    return supervisor


async def _cleanup_resources(
    *,
    agent_runtime: AgentRuntime,
    feishu_bot_supervisor: FeishuBotSupervisor | None,
    active_runner: RunnerProtocol | None,
    stop_runner: bool,
    owned_factory: async_sessionmaker[AsyncSession] | None,
    clients: ProviderClients | None,
) -> BaseException | None:
    cleanup_error: BaseException | None = None
    if feishu_bot_supervisor is not None:
        try:
            feishu_bot_supervisor.stop()
        except BaseException as exc:
            cleanup_error = exc
            logger.error("飞书机器人 supervisor 清理失败（error_type=%s）", type(exc).__name__)
    try:
        await agent_runtime.close()
    except BaseException as exc:
        cleanup_error = exc
        logger.error("Agent 运行时清理失败（error_type=%s）", type(exc).__name__)
    try:
        if stop_runner and active_runner is not None:
            await active_runner.stop()
    except BaseException as exc:
        cleanup_error = cleanup_error or exc
        logger.error("后台 runner 清理失败（error_type=%s）", type(exc).__name__)
    if clients is not None:
        try:
            await clients.aclose()
        except BaseException as exc:
            cleanup_error = cleanup_error or exc
            logger.error("Provider 客户端清理失败（error_type=%s）", type(exc).__name__)
    engine = owned_factory.kw.get("bind") if owned_factory is not None else None
    if isinstance(engine, AsyncEngine):
        try:
            await engine.dispose()
        except BaseException as exc:
            logger.error("数据库 Engine 清理失败（error_type=%s）", type(exc).__name__)
            cleanup_error = cleanup_error or exc
    return cleanup_error


@asynccontextmanager
async def _lifespan(
    current_app: FastAPI,
    *,
    start_background_tasks: bool,
    session_factory: async_sessionmaker[AsyncSession] | None,
    runner: RunnerProtocol | None,
    settings_override: Settings | None,
) -> AsyncIterator[None]:
    settings = _resolve_settings(
        settings_override,
        session_factory=session_factory,
        start_background_tasks=start_background_tasks,
        runner=runner,
    )
    owns_factory = session_factory is None
    factory = _resolve_factory(session_factory, settings)
    current_app.state.settings = settings
    clients = _build_provider_clients(factory, settings)
    current_app.state.integration_credentials = clients.credentials if clients is not None else None
    current_app.state.provider_clients = clients
    refresher: KeywordEmbeddingRefresher | None = None
    if factory is not None:
        current_app.state.session_factory = factory
        refresher = KeywordEmbeddingRefresher(factory, clients)
        current_app.state.rss_embedding_refresher = refresher
    mcp_context, mcp_app = _mount_agent_mcp(current_app, factory, settings, refresher)
    agent_runtime = await _build_agent_runtime(
        clients.credentials if clients is not None else None, settings, mcp_context
    )
    current_app.state.agent_runtime = agent_runtime
    feishu_bot_supervisor = _build_feishu_bot_supervisor(
        current_app, factory, clients.credentials if clients is not None else None, agent_runtime
    )
    active_runner = runner
    primary_error: BaseException | None = None
    mcp_stack = AsyncExitStack()
    try:
        if mcp_app is not None:
            await mcp_stack.enter_async_context(mcp_app.lifespan(mcp_app))
        if start_background_tasks and active_runner is None and factory is not None:
            active_runner = cast(RunnerProtocol, build_background_runner(factory, clients, settings))
        if start_background_tasks and active_runner is not None:
            await active_runner.start()
        await agent_runtime.start()
        if feishu_bot_supervisor is not None:
            await feishu_bot_supervisor.start()
        yield
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error = await _cleanup_resources(
            agent_runtime=agent_runtime,
            feishu_bot_supervisor=feishu_bot_supervisor,
            active_runner=active_runner,
            stop_runner=start_background_tasks,
            owned_factory=factory if owns_factory else None,
            clients=clients,
        )
        if mcp_app is not None:
            try:
                await mcp_stack.aclose()
            except BaseException as exc:
                logger.error("Agent MCP 端点清理失败（error_type=%s）", type(exc).__name__)
                cleanup_error = cleanup_error or exc
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


def create_app(
    *,
    start_background_tasks: bool = True,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    runner: RunnerProtocol | None = None,
    public_base_url: str | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """组合根：settings 为 None 时在 lifespan 内经 get_settings() 解析一次（全仓唯一调用点）。"""
    lifespan = partial(
        _lifespan,
        start_background_tasks=start_background_tasks,
        session_factory=session_factory,
        runner=runner,
        settings_override=settings,
    )
    app = FastAPI(title="Reven", lifespan=lifespan)
    app.add_middleware(
        CsrfOriginMiddleware,
        public_base_url=public_base_url,
        # agent MCP 端点走 Bearer token（机器对机器），不经浏览器 cookie 会话，豁免 Origin 校验
        exempt_prefixes=(AGENT_MCP_ENDPOINT_PATH,),
    )
    # 后加的中间件在最外层：先过认证，再做 CSRF 校验
    app.add_middleware(AuthMiddleware)
    # 最外层统一加安全响应头（#75）：登录页与 API 全覆盖
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(agent_router)
    app.include_router(auth_router)
    app.include_router(brand_router)
    app.include_router(crm_router)
    app.include_router(finance_router)
    app.include_router(integrations_router)
    app.include_router(projects_router)
    app.include_router(sops_router)
    app.include_router(rss_router)
    app.include_router(system_router)
    app.include_router(talents_router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"service": "reven", "status": "ok"}

    return app


app = create_app()
