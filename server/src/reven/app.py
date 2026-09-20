import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from typing import cast

from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from reven.api.routes.articles import router as articles_router
from reven.api.routes.auth import router as auth_router
from reven.api.routes.brand import router as brand_router
from reven.api.routes.crm import router as crm_router
from reven.api.routes.finance import router as finance_router
from reven.api.routes.integrations import router as integrations_router
from reven.api.routes.projects import router as projects_router
from reven.api.routes.rss import router as rss_router
from reven.api.routes.sops import router as sops_router
from reven.api.routes.sync import router as sync_router
from reven.api.routes.system import router as system_router
from reven.api.routes.talents import router as talents_router
from reven.config import get_settings
from reven.db import create_session_factory
from reven.integrations.feishu_bot.review_callback import ReviewCallbackDispatcher
from reven.integrations.feishu_bot.supervisor import FeishuBotSupervisor
from reven.jobs.runner import build_background_runner
from reven.rss.factory import ConfiguredKeywordEmbeddingRefresher, ConfiguredRssInboxPusher
from reven.rss.review_service import CandidateReviewService
from reven.security.auth import AuthMiddleware
from reven.security.csrf import CsrfOriginMiddleware
from reven.security.headers import SecurityHeadersMiddleware
from reven.security.secrets import SecretBox

logger = logging.getLogger(__name__)


class RunnerProtocol:
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


def _resolve_factory(
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    start_background_tasks: bool,
    runner: RunnerProtocol | None,
) -> async_sessionmaker[AsyncSession] | None:
    if session_factory is not None:
        return session_factory
    try:
        return create_session_factory(get_settings())
    except ValidationError:
        if start_background_tasks and runner is None:
            raise
        return None


def _build_feishu_bot_supervisor(
    current_app: FastAPI,
    factory: async_sessionmaker[AsyncSession] | None,
) -> FeishuBotSupervisor | None:
    """创建飞书机器人长连接 supervisor；配置缺失/初始化失败时降级为停用，不阻断进程。"""
    if factory is None:
        return None
    try:
        secret_box = SecretBox.from_base64(get_settings().reven_master_key.get_secret_value())
        review_callback = ReviewCallbackDispatcher(
            factory,
            secret_box,
            CandidateReviewService(factory, ConfiguredRssInboxPusher(factory)),
        )
        supervisor = FeishuBotSupervisor(factory, secret_box, review_callback=review_callback)
    except Exception as exc:
        logger.warning("飞书机器人 supervisor 初始化失败，入站能力停用（error_type=%s）", type(exc).__name__)
        return None
    current_app.state.feishu_bot_supervisor = supervisor
    return supervisor


async def _cleanup_resources(
    *,
    feishu_bot_supervisor: FeishuBotSupervisor | None,
    active_runner: RunnerProtocol | None,
    stop_runner: bool,
    owned_factory: async_sessionmaker[AsyncSession] | None,
) -> BaseException | None:
    cleanup_error: BaseException | None = None
    if feishu_bot_supervisor is not None:
        try:
            feishu_bot_supervisor.stop()
        except BaseException as exc:
            cleanup_error = exc
            logger.error("飞书机器人 supervisor 清理失败（error_type=%s）", type(exc).__name__)
    try:
        if stop_runner and active_runner is not None:
            await active_runner.stop()
    except BaseException as exc:
        cleanup_error = cleanup_error or exc
        logger.error("后台 runner 清理失败（error_type=%s）", type(exc).__name__)
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
) -> AsyncIterator[None]:
    owns_factory = session_factory is None
    factory = _resolve_factory(
        session_factory,
        start_background_tasks=start_background_tasks,
        runner=runner,
    )
    if factory is not None:
        current_app.state.session_factory = factory
        current_app.state.rss_inbox_service = ConfiguredRssInboxPusher(factory)
        current_app.state.rss_embedding_refresher = ConfiguredKeywordEmbeddingRefresher(factory)
    feishu_bot_supervisor = _build_feishu_bot_supervisor(current_app, factory)
    active_runner = runner
    primary_error: BaseException | None = None
    try:
        if start_background_tasks and active_runner is None and factory is not None:
            active_runner = cast(RunnerProtocol, build_background_runner(factory))
        if start_background_tasks and active_runner is not None:
            await active_runner.start()
        if feishu_bot_supervisor is not None:
            await feishu_bot_supervisor.start()
        yield
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error = await _cleanup_resources(
            feishu_bot_supervisor=feishu_bot_supervisor,
            active_runner=active_runner,
            stop_runner=start_background_tasks,
            owned_factory=factory if owns_factory else None,
        )
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


def create_app(
    *,
    start_background_tasks: bool = True,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    runner: RunnerProtocol | None = None,
    public_base_url: str | None = None,
) -> FastAPI:
    lifespan = partial(
        _lifespan,
        start_background_tasks=start_background_tasks,
        session_factory=session_factory,
        runner=runner,
    )
    app = FastAPI(title="Reven", lifespan=lifespan)
    app.add_middleware(CsrfOriginMiddleware, public_base_url=public_base_url)
    # 后加的中间件在最外层：先过认证，再做 CSRF 校验
    app.add_middleware(AuthMiddleware)
    # 最外层统一加安全响应头（#75）：登录页与 API 全覆盖
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(auth_router)
    app.include_router(brand_router)
    app.include_router(articles_router)
    app.include_router(crm_router)
    app.include_router(finance_router)
    app.include_router(integrations_router)
    app.include_router(projects_router)
    app.include_router(sops_router)
    app.include_router(rss_router)
    app.include_router(sync_router)
    app.include_router(system_router)
    app.include_router(talents_router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"service": "reven", "status": "ok"}

    return app


app = create_app()
