import asyncio
import base64
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reven.api.routes.integrations import router as integrations_router
from reven.app import create_app
from reven.config import get_settings
from reven.db import create_session_factory
from reven.integrations.notion.service import register_notion_adapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
TEST_ADMIN_PASSWORD = "test-admin-password"
WRITE_HEADERS = {"Origin": "http://dev.wangyiyang.cc:3001", "X-Reven-CSRF": "1"}


class _FakePreview:
    async def render_current(self, article_id: UUID) -> str:
        return f"<p>{article_id}</p>"


@pytest.fixture(autouse=True)
def _restore_notion_adapter() -> Iterator[None]:
    # 其它用例会临时注册/注销 notion 适配器，这里保证每个 API 用例前后都是真实适配器
    register_notion_adapter()
    yield
    register_notion_adapter()


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
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", TEST_ADMIN_PASSWORD)
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


@pytest.fixture
def workbench(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, async_sessionmaker]]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REVEN_MASTER_KEY", TEST_MASTER_KEY)
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", TEST_ADMIN_PASSWORD)
    get_settings.cache_clear()
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def reset() -> None:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE rss_items, rss_discovery_runs, rss_keywords, rss_sources, publication_jobs, "
                    "articles, crm_follow_ups, crm_contacts, crm_customers, talent_interactions, talents, "
                    "finance_entries, projects, "
                    "sops, brand_versions, channel_template_versions, brand_assets, brand_import_runs, "
                    "integrations, auth_sessions, "
                    "system_state RESTART IDENTITY CASCADE"
                )
            )

    asyncio.run(reset())
    app = create_app(
        start_background_tasks=False,
        session_factory=factory,
        public_base_url="http://dev.wangyiyang.cc:3001",
    )
    app.state.wechat_preview_service = _FakePreview()
    with TestClient(app, base_url="http://testserver", headers=WRITE_HEADERS) as test_client:
        login = test_client.post("/api/auth/login", json={"password": TEST_ADMIN_PASSWORD})
        assert login.status_code == 200
        yield test_client, factory
    asyncio.run(engine.dispose())
    get_settings.cache_clear()
