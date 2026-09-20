import asyncio
import hashlib
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from reven.rss.models import RssDiscoveryRun, RssItem, RssSource
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class RecordingEmbeddingRefresher:
    def __init__(self) -> None:
        self.force_values: list[bool] = []

    async def refresh(self, *, force: bool = False) -> int:
        self.force_values.append(force)
        return 3


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def seed_candidate(factory: async_sessionmaker[AsyncSession]) -> UUID:
    async with factory.begin() as session:
        source = RssSource(name="Example", feed_url="https://example.com/feed", enabled=True)
        run = RssDiscoveryRun(run_date=date(2026, 8, 11), status="completed")
        session.add_all([source, run])
        await session.flush()
        item = RssItem(
            source_id=source.id,
            first_seen_run_id=run.id,
            source_name=source.name,
            guid="one",
            url="https://example.com/one",
            url_key=digest("url-one"),
            guid_key=digest("guid-one"),
            title_key=digest("title-one"),
            title="Agent systems",
            summary="Original summary",
            title_zh="智能体系统",
            summary_zh="中文摘要",
            published_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
            status="candidate",
            positive_literal_matches=["agent"],
            negative_literal_matches=[],
            bm25_score=0.6,
            positive_embedding_score=0.9,
            negative_embedding_score=0.1,
            embedding_model="BAAI/bge-m3",
            embedding_status="completed",
            model_status="skipped",
            reason="正向信号达到阈值",
            rules_version="rss-v1",
        )
        session.add(item)
        await session.flush()
        return item.id


def test_user_can_list_and_ignore_candidates(workbench: tuple[TestClient, async_sessionmaker]) -> None:
    client, factory = workbench
    item_id = asyncio.run(seed_candidate(factory))

    response = client.get("/api/rss/candidates")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": str(item_id),
                "source_name": "Example",
                "url": "https://example.com/one",
                "title": "Agent systems",
                "summary": "Original summary",
                "title_zh": "智能体系统",
                "summary_zh": "中文摘要",
                "published_at": "2026-08-11T01:00:00Z",
                "status": "candidate",
                "positive_literal_matches": ["agent"],
                "negative_literal_matches": [],
                "bm25_score": 0.6,
                "positive_embedding_score": 0.9,
                "negative_embedding_score": 0.1,
                "embedding_model": "BAAI/bge-m3",
                "embedding_status": "completed",
                "model_status": "skipped",
                "model_score": None,
                "reason": "正向信号达到阈值",
                "rules_version": "rss-v1",
                "screening_error": None,
                "saved_at": None,
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 30,
    }
    ignored = client.post(f"/api/rss/candidates/{item_id}/ignore")
    assert ignored.status_code == 200
    assert ignored.json()["status"] == "ignored"
    assert client.get("/api/rss/candidates").json()["items"] == []


def test_candidates_paginate_with_page_and_page_size(workbench: tuple[TestClient, async_sessionmaker]) -> None:
    client, factory = workbench

    async def seed_three() -> None:
        async with factory.begin() as session:
            source = RssSource(name="Example", feed_url="https://example.com/feed", enabled=True)
            run = RssDiscoveryRun(run_date=date(2026, 8, 11), status="completed")
            session.add_all([source, run])
            await session.flush()
            for index in range(3):
                session.add(
                    RssItem(
                        source_id=source.id,
                        first_seen_run_id=run.id,
                        source_name=source.name,
                        guid=f"g{index}",
                        url=f"https://example.com/{index}",
                        url_key=digest(f"url-{index}"),
                        guid_key=digest(f"guid-{index}"),
                        title_key=digest(f"title-{index}"),
                        title=f"T{index}",
                        summary="s",
                        title_zh=f"标题{index}",
                        summary_zh="摘要",
                        published_at=datetime(2026, 8, 11, index, tzinfo=UTC),
                        status="candidate",
                        positive_literal_matches=[],
                        negative_literal_matches=[],
                        bm25_score=0.0,
                        positive_embedding_score=0.0,
                        negative_embedding_score=0.0,
                        embedding_model=None,
                        embedding_status="skipped",
                        model_status="skipped",
                    )
                )

    asyncio.run(seed_three())

    first = client.get("/api/rss/candidates?page=1&page_size=2")
    assert first.status_code == 200
    payload = first.json()
    assert payload["total"] == 3
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert len(payload["items"]) == 2

    second = client.get("/api/rss/candidates?page=2&page_size=2").json()
    assert len(second["items"]) == 1
    first_ids = {item["id"] for item in payload["items"]}
    assert all(item["id"] not in first_ids for item in second["items"])

    assert client.get("/api/rss/candidates?page=0").status_code == 422


def test_user_can_save_and_list_material_without_integrations(workbench: tuple[TestClient, async_sessionmaker]) -> None:
    client, factory = workbench
    item_id = asyncio.run(seed_candidate(factory))
    candidate = client.get("/api/rss/candidates").json()["items"][0]

    response = client.post(f"/api/rss/candidates/{item_id}/confirm")

    assert response.status_code == 200
    saved = response.json()
    assert saved["saved_at"] is not None
    assert saved == {**candidate, "status": "saved", "saved_at": saved["saved_at"]}
    repeated = client.post(f"/api/rss/candidates/{item_id}/confirm")
    assert repeated.status_code == 200
    assert repeated.json() == saved
    assert client.get("/api/rss/candidates").json()["items"] == []
    materials = client.get("/api/rss/candidates?status=saved").json()
    assert materials["total"] == 1
    assert materials["items"] == [saved]
    assert client.post(f"/api/rss/candidates/{item_id}/ignore").status_code == 409


def test_user_cannot_save_ignored_or_missing_candidate(workbench: tuple[TestClient, async_sessionmaker]) -> None:
    client, factory = workbench
    item_id = asyncio.run(seed_candidate(factory))
    assert client.post(f"/api/rss/candidates/{item_id}/ignore").status_code == 200

    ignored = client.post(f"/api/rss/candidates/{item_id}/confirm")
    missing = client.post(f"/api/rss/candidates/{uuid4()}/confirm")

    assert ignored.status_code == 409
    assert ignored.json()["code"] == "RSS_CANDIDATE_NOT_SAVABLE"
    assert missing.status_code == 404
    assert missing.json()["code"] == "RSS_CANDIDATE_NOT_FOUND"
    assert client.get("/api/rss/candidates?status=saved").json()["items"] == []


def test_user_can_explicitly_rebuild_keyword_embeddings(
    workbench: tuple[TestClient, async_sessionmaker],
) -> None:
    client, _factory = workbench
    refresher = RecordingEmbeddingRefresher()
    client.app.state.rss_embedding_refresher = refresher

    response = client.post("/api/rss/embeddings/rebuild")

    assert response.status_code == 200
    assert response.json() == {"refreshed": 3, "model": "BAAI/bge-m3", "dimension": 1024}
    assert refresher.force_values == [True]
