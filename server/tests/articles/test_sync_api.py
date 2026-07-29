from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from reven.api.routes.sync import get_notion_sync_service, router
from reven.integrations.notion.sync import SyncResult


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
