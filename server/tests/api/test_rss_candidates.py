"""RSS 候选工作台路由集成测试：列表/采纳/忽略切换到 BitableCandidateStore 后的响应与错误映射。

多数用例经 dependency_overrides 注入内存 fake store（验证路由↔store 契约）；
「未配置绑定」用例走真实 store（workbench 无绑定行 → 503），验证默认装配链路。
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from reven.api.dependencies import get_candidate_store
from reven.rss.bitable_store import BitableCandidate, BitableCandidatePage, BitableCandidateStoreError


class RecordingEmbeddingRefresher:
    def __init__(self) -> None:
        self.force_values: list[bool] = []

    async def refresh(self, *, force: bool = False) -> int:
        self.force_values.append(force)
        return 3


def make_candidate(record_id: str = "rec_1", status: str = "candidate") -> BitableCandidate:
    return BitableCandidate(
        record_id=record_id,
        title="智能体系统",
        summary="一份关于智能体系统的实践指南。",
        source_name="Example",
        published_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
        url="https://example.com/agent-systems",
        status=status,
        matched_keywords=("AI 智能体",),
        archived_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
        dedupe_key="url:key-1",
    )


class FakeCandidateStore:
    """路由测试替身：记录调用参数，按注入的响应/错误返回。"""

    def __init__(self) -> None:
        self.list_calls: list[dict[str, object]] = []
        self.set_calls: list[tuple[str, str]] = []
        self.page = BitableCandidatePage(items=(), total=0, next_cursor=None)
        self.list_error: BitableCandidateStoreError | None = None
        self.set_result: BitableCandidate | None = None
        self.set_error: BitableCandidateStoreError | None = None

    async def list_candidates(self, *, status: str, page_size: int, cursor: str | None) -> BitableCandidatePage:
        self.list_calls.append({"status": status, "page_size": page_size, "cursor": cursor})
        if self.list_error is not None:
            raise self.list_error
        return self.page

    async def set_status(self, record_id: str, target: str) -> BitableCandidate:
        self.set_calls.append((record_id, target))
        if self.set_error is not None:
            raise self.set_error
        assert self.set_result is not None
        return self.set_result

    async def count_candidates(self, status: str) -> int:
        return 0


def install_fake_store(client: TestClient) -> FakeCandidateStore:
    store = FakeCandidateStore()
    client.app.dependency_overrides[get_candidate_store] = lambda: store
    return store


def test_list_candidates_returns_bitable_page(workbench: tuple[TestClient, object]) -> None:
    client, _factory = workbench
    store = install_fake_store(client)
    store.page = BitableCandidatePage(items=(make_candidate(),), total=5, next_cursor="cursor-2")

    response = client.get("/api/rss/candidates")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "record_id": "rec_1",
                "title": "智能体系统",
                "summary": "一份关于智能体系统的实践指南。",
                "source_name": "Example",
                "published_at": "2026-08-11T01:00:00Z",
                "url": "https://example.com/agent-systems",
                "status": "candidate",
                "matched_keywords": ["AI 智能体"],
                "archived_at": "2026-08-11T02:00:00Z",
                "dedupe_key": "url:key-1",
            }
        ],
        "total": 5,
        "next_cursor": "cursor-2",
    }
    assert store.list_calls == [{"status": "candidate", "page_size": 30, "cursor": None}]


def test_list_candidates_forwards_status_cursor_and_page_size(workbench: tuple[TestClient, object]) -> None:
    client, _factory = workbench
    store = install_fake_store(client)

    response = client.get("/api/rss/candidates?status=saved&cursor=tok-9&page_size=10")

    assert response.status_code == 200
    assert store.list_calls == [{"status": "saved", "page_size": 10, "cursor": "tok-9"}]


def test_list_candidates_rejects_unknown_status(workbench: tuple[TestClient, object]) -> None:
    client, _factory = workbench
    install_fake_store(client)

    assert client.get("/api/rss/candidates?status=pending").status_code == 422


def test_confirm_candidate_returns_saved_record(workbench: tuple[TestClient, object]) -> None:
    client, _factory = workbench
    store = install_fake_store(client)
    store.set_result = make_candidate(status="saved")

    response = client.post("/api/rss/candidates/rec_1/confirm")

    assert response.status_code == 200
    assert response.json()["status"] == "saved"
    assert response.json()["record_id"] == "rec_1"
    assert store.set_calls == [("rec_1", "saved")]


def test_ignore_candidate_returns_ignored_record(workbench: tuple[TestClient, object]) -> None:
    client, _factory = workbench
    store = install_fake_store(client)
    store.set_result = make_candidate(status="ignored")

    response = client.post("/api/rss/candidates/rec_1/ignore")

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert store.set_calls == [("rec_1", "ignored")]


def test_review_missing_record_maps_404(workbench: tuple[TestClient, object]) -> None:
    client, _factory = workbench
    store = install_fake_store(client)
    store.set_error = BitableCandidateStoreError("RSS_CANDIDATE_NOT_FOUND", "RSS 候选不存在或已被删除", status_code=404)

    response = client.post("/api/rss/candidates/rec_gone/confirm")

    assert response.status_code == 404
    assert response.json()["code"] == "RSS_CANDIDATE_NOT_FOUND"


def test_review_status_conflict_maps_409(workbench: tuple[TestClient, object]) -> None:
    client, _factory = workbench
    store = install_fake_store(client)
    store.set_error = BitableCandidateStoreError(
        "RSS_CANDIDATE_NOT_SAVABLE", "RSS 候选状态已变更，当前状态不允许保存（请刷新列表）", status_code=409
    )

    response = client.post("/api/rss/candidates/rec_1/confirm")

    assert response.status_code == 409
    assert response.json()["code"] == "RSS_CANDIDATE_NOT_SAVABLE"


def test_store_unavailable_maps_503(workbench: tuple[TestClient, object]) -> None:
    client, _factory = workbench
    store = install_fake_store(client)
    store.list_error = BitableCandidateStoreError("RSS_CANDIDATES_UNAVAILABLE", "飞书应用机器人未启用", status_code=503)

    response = client.get("/api/rss/candidates")

    assert response.status_code == 503
    assert response.json()["code"] == "RSS_CANDIDATES_UNAVAILABLE"


def test_candidates_endpoints_fail_503_without_enabled_binding(workbench: tuple[TestClient, object]) -> None:
    """真实装配链路（无 dependency override）：未配置启用绑定时列表与审核端点都报 503，不静默返回空列表。"""
    client, _factory = workbench

    listed = client.get("/api/rss/candidates")
    confirmed = client.post("/api/rss/candidates/rec_1/confirm")
    ignored = client.post("/api/rss/candidates/rec_1/ignore")

    for response in (listed, confirmed, ignored):
        assert response.status_code == 503
        assert response.json()["code"] == "RSS_CANDIDATES_BINDING_MISSING"


def test_user_can_explicitly_rebuild_keyword_embeddings(workbench: tuple[TestClient, object]) -> None:
    client, _factory = workbench
    refresher = RecordingEmbeddingRefresher()
    client.app.state.rss_embedding_refresher = refresher

    response = client.post("/api/rss/embeddings/rebuild")

    assert response.status_code == 200
    assert response.json() == {"refreshed": 3, "model": "BAAI/bge-m3", "dimension": 1024}
    assert refresher.force_values == [True]
