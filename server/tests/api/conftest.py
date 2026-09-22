import asyncio
import base64
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reven.api.routes.integrations import router as integrations_router
from reven.app import create_app
from reven.config import Settings
from reven.db import create_session_factory
from reven.integrations.credentials import IntegrationCredentials
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
TEST_ADMIN_PASSWORD = "test-admin-password"
WRITE_HEADERS = {"Origin": "http://dev.wangyiyang.cc:3001", "X-Reven-CSRF": "1"}


def _settings(database_url: str) -> Settings:
    """显式构造测试 Settings：不读进程 env（含 .env），外部 shell 残留不影响用例。"""
    return Settings(
        database_url=database_url,
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password=TEST_ADMIN_PASSWORD,
        siliconflow_api_key=None,
        agent_api_key=None,
        _env_file=None,
    )


async def _reset_integrations(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE integrations RESTART IDENTITY CASCADE"))
    finally:
        await engine.dispose()


@pytest.fixture
def client() -> Iterator[TestClient]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping API tests")
    settings = _settings(database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        session_factory = create_session_factory(settings)
        app.state.session_factory = session_factory
        app.state.integration_credentials = IntegrationCredentials(session_factory, settings)
        yield
        engine = session_factory.kw.get("bind")
        if isinstance(engine, AsyncEngine):
            await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(integrations_router)
    asyncio.run(_reset_integrations(database_url))
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client


@pytest.fixture
def workbench() -> Iterator[tuple[TestClient, async_sessionmaker]]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def reset() -> None:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE rss_items, rss_discovery_runs, rss_keywords, rss_sources, "
                    "crm_follow_ups, crm_contacts, crm_customers, talent_interactions, talents, "
                    "finance_entries, projects, "
                    "sops, brand_versions, channel_template_versions, brand_assets, "
                    "integrations, auth_sessions, "
                    "system_state RESTART IDENTITY CASCADE"
                )
            )

    asyncio.run(reset())
    app = create_app(
        start_background_tasks=False,
        session_factory=factory,
        public_base_url="http://dev.wangyiyang.cc:3001",
        settings=_settings(database_url),
    )
    with TestClient(app, base_url="http://testserver", headers=WRITE_HEADERS) as test_client:
        login = test_client.post("/api/auth/login", json={"password": TEST_ADMIN_PASSWORD})
        assert login.status_code == 200
        yield test_client, factory
    asyncio.run(engine.dispose())
