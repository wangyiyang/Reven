import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from typing import cast

from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from reven.api.routes.articles import router as articles_router
from reven.api.routes.integrations import router as integrations_router
from reven.api.routes.rss import router as rss_router
from reven.api.routes.sync import router as sync_router
from reven.api.routes.system import router as system_router
from reven.config import get_settings
from reven.db import create_session_factory
from reven.jobs.runner import build_background_runner
from reven.security.csrf import CsrfOriginMiddleware

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


async def _cleanup_resources(
    *,
    active_runner: RunnerProtocol | None,
    stop_runner: bool,
    owned_factory: async_sessionmaker[AsyncSession] | None,
) -> BaseException | None:
    cleanup_error: BaseException | None = None
    try:
        if stop_runner and active_runner is not None:
            await active_runner.stop()
    except BaseException as exc:
        cleanup_error = exc
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
    active_runner = runner
    primary_error: BaseException | None = None
    try:
        if start_background_tasks and active_runner is None and factory is not None:
            active_runner = cast(RunnerProtocol, build_background_runner(factory))
        if start_background_tasks and active_runner is not None:
            await active_runner.start()
        yield
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        cleanup_error = await _cleanup_resources(
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
    app.include_router(articles_router)
    app.include_router(integrations_router)
    app.include_router(rss_router)
    app.include_router(sync_router)
    app.include_router(system_router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"service": "reven", "status": "ok"}

    return app


app = create_app()
