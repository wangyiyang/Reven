import asyncio
import base64
import os
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from reven.api.routes.integrations import get_session_factory
from reven.api.routes.sync import get_notion_sync_service, router
from reven.app import create_app
from reven.config import get_settings
from reven.integrations.notion.sync import SyncResult
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

DUMMY_DATABASE_URL = "postgresql+asyncpg://user:password@127.0.0.1:1/reven"


class FakeSyncService:
    def __init__(self) -> None:
        self.article_id = None

    async def sync_once(self) -> SyncResult:
        return SyncResult(created=1, updated=55, failed=0, duration_ms=842)

    async def sync_page(self, article_id):  # type: ignore[no-untyped-def]
        self.article_id = article_id
        return SyncResult(created=0, updated=1, failed=0, duration_ms=12)


def test_notion_sync_api_returns_statistics() -> None:
    service = FakeSyncService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_notion_sync_service] = lambda: service

    response = TestClient(app).post("/api/sync/notion")

    assert response.status_code == 200
    assert response.json() == {"created": 1, "updated": 55, "failed": 0, "duration_ms": 842}


def test_article_sync_api_passes_article_id() -> None:
    article_id = uuid4()
    service = FakeSyncService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_notion_sync_service] = lambda: service

    response = TestClient(app).post(f"/api/articles/{article_id}/sync")

    assert response.status_code == 200
    assert response.json()["updated"] == 1
    assert service.article_id == article_id


@pytest.mark.anyio
async def test_production_app_mounts_sync_routes_with_database_dependency(
    monkeypatch: pytest.MonkeyPatch,
    db_session,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv(
        "REVEN_MASTER_KEY",
        base64.urlsafe_b64encode(b"t" * 32).decode(),
    )
    get_settings.cache_clear()

    headers = {"Origin": "https://dev.wangyiyang.cc", "X-Reven-CSRF": "1"}
    with TestClient(create_app(start_background_tasks=False), headers=headers) as client:
        response = client.post("/api/sync/notion")
        paths = client.get("/openapi.json").json()["paths"]

    assert response.status_code == 409
    assert "/api/sync/notion" in paths
    assert "/api/articles/{article_id}/sync" in paths
    get_settings.cache_clear()


def test_app_lifespan_does_not_dispose_injected_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(DUMMY_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    disposed = False
    original_dispose = AsyncEngine.dispose

    async def track_dispose(target: AsyncEngine) -> None:
        nonlocal disposed
        if target is engine:
            disposed = True
        await original_dispose(target)

    monkeypatch.setattr(AsyncEngine, "dispose", track_dispose)
    app = create_app(start_background_tasks=False, session_factory=factory)

    @app.get("/test/session-factory")
    def factory_identity(
        request: Request,
        dependency: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    ) -> dict[str, bool]:
        return {"same": dependency is factory and request.app.state.session_factory is factory}

    with TestClient(app) as client:
        first = client.get("/test/session-factory")
        second = client.get("/test/session-factory")

    assert first.json() == {"same": True}
    assert second.json() == {"same": True}
    assert disposed is False
    asyncio.run(engine.dispose())


def test_app_lifespan_disposes_internally_created_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DUMMY_DATABASE_URL)
    monkeypatch.setenv(
        "REVEN_MASTER_KEY",
        base64.urlsafe_b64encode(b"t" * 32).decode(),
    )
    get_settings.cache_clear()
    disposed = 0
    original_dispose = AsyncEngine.dispose

    async def track_dispose(target: AsyncEngine) -> None:
        nonlocal disposed
        disposed += 1
        await original_dispose(target)

    monkeypatch.setattr(AsyncEngine, "dispose", track_dispose)
    with TestClient(create_app(start_background_tasks=False)):
        pass

    assert disposed == 1
    get_settings.cache_clear()


def test_database_settings_accept_ci_test_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ci_url = "postgresql+asyncpg://reven_test:reven_test@127.0.0.1:5432/reven_test"
    monkeypatch.setenv("TEST_DATABASE_URL", ci_url)
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv(
        "REVEN_MASTER_KEY",
        base64.urlsafe_b64encode(b"t" * 32).decode(),
    )
    get_settings.cache_clear()

    assert get_settings().database_url.get_secret_value() == ci_url
    get_settings.cache_clear()
