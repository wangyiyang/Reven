"""GET /api/rss/runs/latest 的健康状态端点测试。"""

import asyncio
from datetime import date

from fastapi.testclient import TestClient
from reven.rss.models import RssDiscoveryRun
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def seed_runs(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory.begin() as session:
        session.add_all(
            [
                RssDiscoveryRun(run_date=date(2026, 8, 24), status="completed", candidate_count=3),
                RssDiscoveryRun(
                    run_date=date(2026, 8, 25),
                    status="partial",
                    candidate_count=5,
                    failure_count=1,
                    errors=[{"stage": "backfill", "error_type": "EMBEDDING_TIMEOUT"}],
                    notification_error="FeishuNotificationError",
                ),
            ]
        )


def test_latest_run_returns_most_recent_record(workbench: tuple[TestClient, async_sessionmaker]) -> None:
    client, factory = workbench
    asyncio.run(seed_runs(factory))

    response = client.get("/api/rss/runs/latest")

    assert response.status_code == 200
    body = response.json()
    assert body["run_date"] == "2026-08-25"
    assert body["status"] == "partial"
    assert body["candidate_count"] == 5
    assert body["failure_count"] == 1
    assert body["errors"] == [{"stage": "backfill", "error_type": "EMBEDDING_TIMEOUT"}]
    assert body["notification_error"] == "FeishuNotificationError"
    assert body["started_at"] is not None


def test_latest_run_without_records_returns_404(workbench: tuple[TestClient, async_sessionmaker]) -> None:
    client, _factory = workbench

    response = client.get("/api/rss/runs/latest")

    assert response.status_code == 404
    assert response.json()["code"] == "RSS_RUN_NOT_FOUND"
