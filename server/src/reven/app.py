from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from reven.api.routes.sync import router as sync_router
from reven.config import get_settings
from reven.db import create_session_factory


def create_app(
    *,
    start_background_tasks: bool = True,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(current_app: FastAPI) -> AsyncIterator[None]:
        owns_factory = session_factory is None
        factory = session_factory
        if factory is None:
            try:
                factory = create_session_factory(get_settings())
            except ValidationError:
                if start_background_tasks:
                    raise
        if factory is not None:
            current_app.state.session_factory = factory
        try:
            yield
        finally:
            if owns_factory and factory is not None:
                engine = factory.kw.get("bind")
                if isinstance(engine, AsyncEngine):
                    await engine.dispose()

    app = FastAPI(title="Reven", lifespan=lifespan)
    app.include_router(sync_router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"service": "reven", "status": "ok"}

    return app


app = create_app()
