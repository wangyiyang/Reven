import asyncio
import base64
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reven.api.routes.integrations import router as integrations_router
from reven.config import get_settings
from reven.db import create_session_factory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()


async def _reset_integrations(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE integrations RESTART IDENTITY CASCADE"))
    finally:
        await engine.dispose()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    if "TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TEST_DATABASE_URL is not set, skipping API tests")
    database_url = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REVEN_MASTER_KEY", TEST_MASTER_KEY)
    get_settings.cache_clear()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        session_factory = create_session_factory(get_settings())
        app.state.session_factory = session_factory
        yield
        engine = session_factory.kw.get("bind")
        if isinstance(engine, AsyncEngine):
            await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(integrations_router)

    asyncio.run(_reset_integrations(database_url))

    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client

    get_settings.cache_clear()
