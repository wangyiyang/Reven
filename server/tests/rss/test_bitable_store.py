"""BitableCandidateStore：绑定解析、search 列表/计数、先读后写审核、领域错误映射。

飞书出站流量经 ProviderClients 的 feishu_transport seam（httpx.MockTransport），不碰真实网络。
"""

import base64
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from urllib.parse import parse_qsl

import httpx
import pytest
from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.models import FeishuResourceBinding, Integration
from reven.provider_clients import ProviderClients
from reven.rss.bitable_store import (
    BitableCandidateStore,
    BitableCandidateStoreError,
)
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
APP_TOKEN = "bascn_store"
TABLE_ID = "tbl_store"

PUBLISHED_MS = int(datetime(2026, 8, 11, 1, tzinfo=UTC).timestamp() * 1000)
ARCHIVED_MS = int(datetime(2026, 8, 11, 2, tzinfo=UTC).timestamp() * 1000)


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1/unused",
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
        siliconflow_api_key=None,
        agent_api_key=None,
        _env_file=None,
    )


def _fields(status: str = "candidate", **overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "标题": [{"text": "智能体系统", "type": "text"}],  # 真实读路径的富文本段数组形态
        "摘要": "一份关于智能体系统的实践指南。",
        "来源": "Example",
        "发布时间": PUBLISHED_MS,
        "原文链接": {"link": "https://example.com/agent-systems", "text": "智能体系统"},
        "状态": status,
        "命中关键词": "AI 智能体、Agent",
        "入库日期": ARCHIVED_MS,
        "去重键": "url:key-1",
    }
    fields.update(overrides)
    return fields


class _BitableStub:
    """内存表 stub：search（状态 filter + 游标翻页）、batch_get、batch_update。"""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, object]] = {}
        self.omit_total = False
        self.search_error: tuple[int, str] | None = None
        self.search_bodies: list[dict[str, object]] = []
        self.search_queries: list[dict[str, str]] = []
        self.get_bodies: list[dict[str, object]] = []
        self.update_bodies: list[dict[str, object]] = []
        self.calls: list[str] = []

    def seed(self, record_id: str, fields: dict[str, object]) -> None:
        self.records[record_id] = fields

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/auth/" in path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-store-token"})
        self.calls.append(path)
        if path.endswith("/records/search"):
            return self._search(request)
        if path.endswith("/records/batch_get"):
            body = json.loads(request.content)
            self.get_bodies.append(body)
            present = [
                {"record_id": rid, "fields": self.records[rid]} for rid in body["record_ids"] if rid in self.records
            ]
            absent = [rid for rid in body["record_ids"] if rid not in self.records]
            return httpx.Response(200, json={"code": 0, "data": {"records": present, "absent_record_ids": absent}})
        if path.endswith("/records/batch_update"):
            body = json.loads(request.content)
            self.update_bodies.append(body)
            updated = []
            for item in body["records"]:
                self.records[item["record_id"]].update(item["fields"])
                updated.append({"record_id": item["record_id"], "fields": self.records[item["record_id"]]})
            return httpx.Response(200, json={"code": 0, "data": {"records": updated}})
        return httpx.Response(500, json={"code": 500, "msg": "unexpected"})

    def _search(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.search_bodies.append(body)
        self.search_queries.append(dict(parse_qsl(request.url.query.decode())))
        if self.search_error is not None:
            code, message = self.search_error
            return httpx.Response(200, json={"code": code, "msg": message})
        statuses = set(body["filter"]["conditions"][0]["value"])
        matched = [
            {"record_id": rid, "fields": fields}
            for rid, fields in self.records.items()
            if fields.get("状态") in statuses
        ]
        page_size = int(dict(parse_qsl(request.url.query.decode())).get("page_size", "500"))
        offset = int(dict(parse_qsl(request.url.query.decode())).get("page_token", "0"))
        page = matched[offset : offset + page_size]
        has_more = offset + page_size < len(matched)
        data: dict[str, object] = {"items": page, "has_more": has_more}
        if has_more:
            data["page_token"] = str(offset + page_size)
        if not self.omit_total:
            data["total"] = len(matched)
        return httpx.Response(200, json={"code": 0, "data": data})


@pytest.fixture
async def rig(db_session: AsyncSession) -> AsyncIterator[tuple[_BitableStub, Callable[[], BitableCandidateStore]]]:
    stub = _BitableStub()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    created: list[ProviderClients] = []

    def make_store() -> BitableCandidateStore:
        settings = _settings()
        clients = ProviderClients(
            IntegrationCredentials(factory, settings),
            settings,
            feishu_transport=httpx.MockTransport(stub),
        )
        created.append(clients)
        return BitableCandidateStore(factory, clients)

    yield stub, make_store
    for clients in created:
        await clients.aclose()


async def _seed_binding(
    db_session: AsyncSession,
    *,
    enabled: bool = True,
    feishu_enabled: bool = True,
) -> FeishuResourceBinding:
    integration = Integration(
        provider="feishu_bot",
        public_config={"enabled": feishu_enabled, "whitelist_open_ids": ["ou_store"]},
        encrypted_secret=SecretBox.from_base64(TEST_MASTER_KEY).encrypt(
            {"app_id": "cli_store", "app_secret": "s3cret"}
        ),
    )
    db_session.add(integration)
    await db_session.flush()
    binding = FeishuResourceBinding(
        integration_id=integration.id,
        resource_type="bitable",
        purpose="rss_candidates",
        config={"app_token": APP_TOKEN, "table_id": TABLE_ID},
        enabled=enabled,
    )
    db_session.add(binding)
    await db_session.commit()
    return binding


@pytest.mark.anyio
async def test_list_candidates_filters_by_status_and_maps_nine_fields(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    await _seed_binding(db_session)
    stub, make_store = rig
    stub.seed("rec_1", _fields("candidate"))
    stub.seed("rec_2", _fields("saved"))

    page = await make_store().list_candidates(status="candidate", page_size=30, cursor=None)

    assert page.total == 1
    assert page.next_cursor is None
    assert len(page.items) == 1
    candidate = page.items[0]
    assert candidate.record_id == "rec_1"
    assert candidate.title == "智能体系统"
    assert candidate.summary == "一份关于智能体系统的实践指南。"
    assert candidate.source_name == "Example"
    assert candidate.published_at == datetime(2026, 8, 11, 1, tzinfo=UTC)
    assert candidate.url == "https://example.com/agent-systems"
    assert candidate.status == "candidate"
    assert candidate.matched_keywords == ("AI 智能体", "Agent")
    assert candidate.archived_at == datetime(2026, 8, 11, 2, tzinfo=UTC)
    assert candidate.dedupe_key == "url:key-1"
    # filter 形状：状态单选 is 条件 + 倒序排序
    body = stub.search_bodies[0]
    assert body["filter"] == {
        "conjunction": "and",
        "conditions": [{"field_name": "状态", "operator": "is", "value": ["candidate"]}],
    }
    assert body["sort"] == [
        {"field_name": "发布时间", "desc": True},
        {"field_name": "入库日期", "desc": True},
    ]
    assert stub.search_queries[0]["page_size"] == "30"


@pytest.mark.anyio
async def test_list_candidates_follows_page_token_cursor(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    await _seed_binding(db_session)
    stub, make_store = rig
    for index in range(3):
        stub.seed(f"rec_{index}", _fields("candidate", 标题=f"标题{index}"))

    store = make_store()
    first = await store.list_candidates(status="candidate", page_size=2, cursor=None)
    assert [item.record_id for item in first.items] == ["rec_0", "rec_1"]
    assert first.total == 3
    assert first.next_cursor == "2"

    second = await store.list_candidates(status="candidate", page_size=2, cursor=first.next_cursor)
    assert [item.record_id for item in second.items] == ["rec_2"]
    assert second.next_cursor is None
    assert stub.search_queries[1]["page_token"] == "2"


@pytest.mark.anyio
async def test_count_candidates_prefers_search_total(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    await _seed_binding(db_session)
    stub, make_store = rig
    stub.seed("rec_1", _fields("candidate"))
    stub.seed("rec_2", _fields("candidate"))
    stub.seed("rec_3", _fields("ignored"))

    assert await make_store().count_candidates("candidate") == 2
    assert stub.search_queries[0]["page_size"] == "1"  # 计数只取 total，不拉记录
    assert len(stub.search_bodies) == 1


@pytest.mark.anyio
async def test_count_candidates_paginates_when_total_missing(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    await _seed_binding(db_session)
    stub, make_store = rig
    stub.omit_total = True
    for index in range(3):
        stub.seed(f"rec_{index}", _fields("saved"))

    assert await make_store().count_candidates("saved") == 3
    assert len(stub.search_bodies) == 1 + 1  # 首页 page_size=1 + 聚合翻页（500/页，一次拿完剩余）


@pytest.mark.anyio
async def test_confirm_candidate_reads_then_updates_status(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    await _seed_binding(db_session)
    stub, make_store = rig
    stub.seed("rec_1", _fields("candidate"))

    saved = await make_store().set_status("rec_1", "saved")

    assert saved.record_id == "rec_1"
    assert saved.status == "saved"
    assert stub.get_bodies == [{"record_ids": ["rec_1"]}]  # 先读
    assert stub.update_bodies == [{"records": [{"record_id": "rec_1", "fields": {"状态": "saved"}}]}]  # 后写
    assert stub.records["rec_1"]["状态"] == "saved"


@pytest.mark.anyio
async def test_repeated_confirm_is_idempotent_without_rewrite(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    await _seed_binding(db_session)
    stub, make_store = rig
    stub.seed("rec_1", _fields("saved"))

    result = await make_store().set_status("rec_1", "saved")

    assert result.status == "saved"
    assert stub.update_bodies == []  # 已是目标态：不重复写


@pytest.mark.anyio
async def test_repeated_ignore_is_idempotent_without_rewrite(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    await _seed_binding(db_session)
    stub, make_store = rig
    stub.seed("rec_1", _fields("ignored"))

    result = await make_store().set_status("rec_1", "ignored")

    assert result.status == "ignored"
    assert stub.update_bodies == []


@pytest.mark.anyio
async def test_confirm_conflicts_when_status_changed_on_feishu_side(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    """读到记录已不是 candidate（飞书侧并发变更为 ignored）：409，不强制覆盖。"""
    await _seed_binding(db_session)
    stub, make_store = rig
    stub.seed("rec_1", _fields("ignored"))

    with pytest.raises(BitableCandidateStoreError) as caught:
        await make_store().set_status("rec_1", "saved")

    assert caught.value.code == "RSS_CANDIDATE_NOT_SAVABLE"
    assert caught.value.status_code == 409
    assert stub.update_bodies == []
    assert stub.records["rec_1"]["状态"] == "ignored"


@pytest.mark.anyio
async def test_ignore_conflicts_when_candidate_already_saved(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    await _seed_binding(db_session)
    stub, make_store = rig
    stub.seed("rec_1", _fields("saved"))

    with pytest.raises(BitableCandidateStoreError) as caught:
        await make_store().set_status("rec_1", "ignored")

    assert caught.value.code == "RSS_CANDIDATE_NOT_IGNORABLE"
    assert caught.value.status_code == 409


@pytest.mark.anyio
async def test_set_status_raises_not_found_for_missing_record(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    await _seed_binding(db_session)
    _stub, make_store = rig

    with pytest.raises(BitableCandidateStoreError) as caught:
        await make_store().set_status("rec_gone", "saved")

    assert caught.value.code == "RSS_CANDIDATE_NOT_FOUND"
    assert caught.value.status_code == 404


@pytest.mark.anyio
async def test_store_fails_without_enabled_binding(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    stub, make_store = rig

    with pytest.raises(BitableCandidateStoreError) as caught:
        await make_store().list_candidates(status="candidate", page_size=30, cursor=None)

    assert caught.value.code == "RSS_CANDIDATES_BINDING_MISSING"
    assert caught.value.status_code == 503
    assert stub.calls == []  # 配置错误在出站前失败

    await _seed_binding(db_session, enabled=False)
    with pytest.raises(BitableCandidateStoreError) as caught:
        await make_store().count_candidates("candidate")
    assert caught.value.code == "RSS_CANDIDATES_BINDING_MISSING"


@pytest.mark.anyio
async def test_store_fails_when_feishu_credentials_unavailable(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    stub, make_store = rig
    await _seed_binding(db_session, feishu_enabled=False)

    with pytest.raises(BitableCandidateStoreError) as caught:
        await make_store().list_candidates(status="candidate", page_size=30, cursor=None)

    assert caught.value.code == "RSS_CANDIDATES_UNAVAILABLE"
    assert caught.value.status_code == 503
    assert stub.calls == []


@pytest.mark.anyio
async def test_store_wraps_api_error_with_sanitized_message(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateStore]],
) -> None:
    await _seed_binding(db_session)
    stub, make_store = rig
    stub.search_error = (1254291, "rate limited: token t-store-token s3cret")

    with pytest.raises(BitableCandidateStoreError) as caught:
        await make_store().list_candidates(status="candidate", page_size=30, cursor=None)

    assert caught.value.code == "RSS_CANDIDATES_UNAVAILABLE"
    message = caught.value.message
    assert "1254291" in message
    assert "t-store-token" not in message
    assert "s3cret" not in message
