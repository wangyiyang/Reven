import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from reven.api.routes.sync import router as sync_router
from reven.config import get_settings
from reven.db import create_session_factory
from reven.jobs.runner import build_background_runner

logger = logging.getLogger(__name__)


class RunnerProtocol:
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


def create_app(
    *,
    start_background_tasks: bool = True,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    runner: RunnerProtocol | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(current_app: FastAPI) -> AsyncIterator[None]:
        owns_factory = session_factory is None
        factory = session_factory
        if factory is None:
            try:
                factory = create_session_factory(get_settings())
            except ValidationError:
                if start_background_tasks and runner is None:
                    raise
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
            cleanup_error: BaseException | None = None
            try:
                if start_background_tasks and active_runner is not None:
                    await active_runner.stop()
            except BaseException as exc:
                cleanup_error = exc
                logger.error("后台 runner 清理失败（error_type=%s）", type(exc).__name__)
            if owns_factory and factory is not None:
                engine = factory.kw.get("bind")
                if isinstance(engine, AsyncEngine):
                    try:
                        await engine.dispose()
                    except BaseException as exc:
                        logger.error("数据库 Engine 清理失败（error_type=%s）", type(exc).__name__)
                        if cleanup_error is None:
                            cleanup_error = exc
            if primary_error is None and cleanup_error is not None:
                raise cleanup_error

    app = FastAPI(title="Reven", lifespan=lifespan)
    app.include_router(sync_router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"service": "reven", "status": "ok"}

    return app


app = create_app()
