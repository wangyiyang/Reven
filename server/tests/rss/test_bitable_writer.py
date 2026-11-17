"""BitableCandidateWriter：绑定解析、三层防重、字段/选项预检、advisory lock 串行化。

飞书出站流量经 ProviderClients 的 feishu_transport seam（httpx.MockTransport），不碰真实网络。
"""

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.bitable import RSS_CANDIDATES_REQUIRED_FIELDS
from reven.integrations.models import FeishuResourceBinding, Integration
from reven.provider_clients import ProviderClients
from reven.rss.bitable_writer import (
    BitableCandidateWriteError,
    BitableCandidateWriter,
    _record,
    write_lock_key,
)
from reven.rss.screening_service import ScreenedCandidate
from reven.security.secrets import SecretBox
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
APP_TOKEN = "bascn_writer"
TABLE_ID = "tbl_writer"
RUN_ID = UUID("00000000-0000-0000-0000-0000000000aa")

_FIELD_TYPES = dict(RSS_CANDIDATES_REQUIRED_FIELDS)


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1/unused",
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
        siliconflow_api_key=None,
        agent_api_key=None,
        _env_file=None,
    )


class _BitableStub:
    """可分派到每个用例自定义行为的飞书 Bitable API stub。"""

    def __init__(self) -> None:
        self.status_options: tuple[str, ...] = ("candidate", "saved", "ignored")
        self.missing_fields: set[str] = set()
        self.existing_keys: set[str] = set()
        self.create_error: tuple[int, str] | None = None
        self.created_bodies: list[dict[str, object]] = []
        self.search_bodies: list[dict[str, object]] = []
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/auth/" in path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-writer-token"})
        self.calls.append(path)
        if path.endswith("/fields"):
            return httpx.Response(200, json={"code": 0, "data": {"items": self._field_items(), "has_more": False}})
        if path.endswith("/records/search"):
            body = json.loads(request.content)
            self.search_bodies.append(body)
            keys = set(body["filter"]["conditions"][0]["value"]) & self.existing_keys
            items = [
                # 真实 API 文本字段返回富文本段数组形态，刻意用该形态覆盖解析
                {"record_id": f"rec_dup_{index}", "fields": {"去重键": [{"text": key, "type": "text"}]}}
                for index, key in enumerate(sorted(keys))
            ]
            return httpx.Response(200, json={"code": 0, "data": {"items": items, "has_more": False}})
        if path.endswith("/records/batch_create"):
            body = json.loads(request.content)
            self.created_bodies.append(body)
            if self.create_error is not None:
                code, message = self.create_error
                return httpx.Response(200, json={"code": code, "msg": message})
            records = [
                {"record_id": f"rec_new_{index}", "fields": record["fields"]}
                for index, record in enumerate(body["records"])
            ]
            return httpx.Response(200, json={"code": 0, "data": {"records": records}})
        return httpx.Response(500, json={"code": 500, "msg": "unexpected"})

    def _field_items(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for index, (name, field_type) in enumerate(RSS_CANDIDATES_REQUIRED_FIELDS):
            if name in self.missing_fields:
                continue
            item: dict[str, object] = {"field_id": f"fld_{index}", "field_name": name, "type": field_type}
            if name == "状态":
                item["property"] = {"options": [{"name": option} for option in self.status_options]}
            items.append(item)
        return items


@pytest.fixture
async def rig(db_session: AsyncSession) -> AsyncIterator[tuple[_BitableStub, Callable[[], BitableCandidateWriter]]]:
    stub = _BitableStub()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    created: list[ProviderClients] = []

    def make_writer() -> BitableCandidateWriter:
        settings = _settings()
        clients = ProviderClients(
            IntegrationCredentials(factory, settings),
            settings,
            feishu_transport=httpx.MockTransport(stub),
        )
        created.append(clients)
        return BitableCandidateWriter(factory, clients)

    yield stub, make_writer
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
        public_config={"enabled": feishu_enabled, "whitelist_open_ids": ["ou_writer"]},
        encrypted_secret=SecretBox.from_base64(TEST_MASTER_KEY).encrypt({"app_id": "cli_test", "app_secret": "s3cret"}),
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


def _candidate(dedupe_key: str, **overrides: object) -> ScreenedCandidate:
    base: dict[str, object] = {
        "source_name": "Example",
        "title": "智能体系统",
        "summary": "实用模式",
        "url": "https://example.com/post-1",
        "published_at": datetime(2026, 8, 11, 1, tzinfo=UTC),
        "matched_keywords": ("AI 智能体",),
        "dedupe_key": dedupe_key,
    }
    base.update(overrides)
    return ScreenedCandidate(**base)  # type: ignore[arg-type]


def test_record_field_names_match_required_benchmark() -> None:
    """写记录字段与 RSS_CANDIDATES_REQUIRED_FIELDS 九字段基准一一对应。"""
    record = _record(RUN_ID, _candidate("url:key"))
    assert set(record.fields) == {name for name, _field_type in RSS_CANDIDATES_REQUIRED_FIELDS}


@pytest.mark.anyio
async def test_write_candidates_maps_nine_fields_and_returns_created_count(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateWriter]],
) -> None:
    await _seed_binding(db_session)
    stub, make_writer = rig

    written = await make_writer().write_candidates(run_id=RUN_ID, candidates=(_candidate("url:key-1"),))

    assert written == 1
    assert len(stub.created_bodies) == 1
    record = stub.created_bodies[0]["records"][0]
    fields = record["fields"]
    assert fields["标题"] == "智能体系统"
    assert fields["摘要"] == "实用模式"
    assert fields["来源"] == "Example"
    assert fields["状态"] == "candidate"
    assert fields["命中关键词"] == "AI 智能体"
    assert fields["去重键"] == "url:key-1"
    assert fields["发布时间"] == int(datetime(2026, 8, 11, 1, tzinfo=UTC).timestamp() * 1000)
    assert isinstance(fields["入库日期"], int)
    assert fields["原文链接"] == {"link": "https://example.com/post-1", "text": "智能体系统"}
    assert record["client_token"].startswith(f"{RUN_ID}:")
    assert len(record["client_token"]) <= 64


@pytest.mark.anyio
async def test_write_candidates_omits_absent_url_and_published_at(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateWriter]],
) -> None:
    await _seed_binding(db_session)
    stub, make_writer = rig

    written = await make_writer().write_candidates(
        run_id=RUN_ID,
        candidates=(_candidate("title:key", url=None, published_at=None, matched_keywords=()),),
    )

    assert written == 1
    fields = stub.created_bodies[0]["records"][0]["fields"]
    assert "原文链接" not in fields
    assert "发布时间" not in fields
    assert fields["命中关键词"] == ""


@pytest.mark.anyio
async def test_write_candidates_dedupes_within_run_seen_set(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateWriter]],
) -> None:
    await _seed_binding(db_session)
    stub, make_writer = rig
    candidates = (_candidate("url:same", title="第一条"), _candidate("url:same", title="重复键"))

    written = await make_writer().write_candidates(run_id=RUN_ID, candidates=candidates)

    assert written == 1
    assert len(stub.created_bodies) == 1
    assert stub.created_bodies[0]["records"][0]["fields"]["标题"] == "第一条"


@pytest.mark.anyio
async def test_write_candidates_skips_keys_already_in_table(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateWriter]],
) -> None:
    await _seed_binding(db_session)
    stub, make_writer = rig
    stub.existing_keys = {"url:existing"}

    written = await make_writer().write_candidates(
        run_id=RUN_ID,
        candidates=(_candidate("url:existing"), _candidate("url:fresh")),
    )

    assert written == 1
    assert len(stub.search_bodies) == 1
    condition = stub.search_bodies[0]["filter"]["conditions"][0]
    assert condition["field_name"] == "去重键"
    assert condition["operator"] == "is"
    assert set(condition["value"]) == {"url:existing", "url:fresh"}
    assert [r["fields"]["去重键"] for r in stub.created_bodies[0]["records"]] == ["url:fresh"]


@pytest.mark.anyio
async def test_client_token_stable_across_retries(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateWriter]],
) -> None:
    """同 run_id + 同去重键的重试产生相同 client_token（飞书侧幂等拒绝重复创建）。"""
    await _seed_binding(db_session)
    stub, make_writer = rig
    writer = make_writer()

    await writer.write_candidates(run_id=RUN_ID, candidates=(_candidate("url:key"),))
    await writer.write_candidates(run_id=RUN_ID, candidates=(_candidate("url:key"),))

    tokens = [body["records"][0]["client_token"] for body in stub.created_bodies]
    assert len(tokens) == 2 and tokens[0] == tokens[1]


@pytest.mark.anyio
async def test_write_candidates_fails_without_enabled_binding(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateWriter]],
) -> None:
    stub, make_writer = rig

    with pytest.raises(BitableCandidateWriteError, match="未配置启用的飞书多维表格绑定"):
        await make_writer().write_candidates(run_id=RUN_ID, candidates=(_candidate("url:key"),))

    assert stub.calls == []  # 配置错误在出站前失败

    await _seed_binding(db_session, enabled=False)
    with pytest.raises(BitableCandidateWriteError, match="未配置启用的飞书多维表格绑定"):
        await make_writer().write_candidates(run_id=RUN_ID, candidates=(_candidate("url:key"),))


@pytest.mark.anyio
async def test_write_candidates_fails_when_feishu_credentials_unavailable(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateWriter]],
) -> None:
    _stub, make_writer = rig
    await _seed_binding(db_session, feishu_enabled=False)

    with pytest.raises(BitableCandidateWriteError, match="未启用或凭证不可用"):
        await make_writer().write_candidates(run_id=RUN_ID, candidates=(_candidate("url:key"),))


@pytest.mark.anyio
async def test_write_candidates_empty_list_is_noop_but_still_requires_binding(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateWriter]],
) -> None:
    stub, make_writer = rig
    with pytest.raises(BitableCandidateWriteError, match="未配置启用"):
        await make_writer().write_candidates(run_id=RUN_ID, candidates=())

    await _seed_binding(db_session)
    assert await make_writer().write_candidates(run_id=RUN_ID, candidates=()) == 0
    assert stub.calls == []  # 无候选不发起任何飞书调用


@pytest.mark.anyio
async def test_write_candidates_fails_when_status_option_missing(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateWriter]],
) -> None:
    """「状态」单选缺少 candidate 选项：Bitable 写入不存在的选项值会失败，故写前预检给出修复指引。"""
    await _seed_binding(db_session)
    stub, make_writer = rig
    stub.status_options = ("saved", "ignored")

    with pytest.raises(BitableCandidateWriteError, match="缺少单选选项「candidate」"):
        await make_writer().write_candidates(run_id=RUN_ID, candidates=(_candidate("url:key"),))

    assert stub.created_bodies == []  # 未写入半截数据


@pytest.mark.anyio
async def test_write_candidates_fails_when_required_field_missing(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateWriter]],
) -> None:
    await _seed_binding(db_session)
    stub, make_writer = rig
    stub.missing_fields = {"去重键"}

    with pytest.raises(BitableCandidateWriteError, match="缺少字段「去重键」"):
        await make_writer().write_candidates(run_id=RUN_ID, candidates=(_candidate("url:key"),))


@pytest.mark.anyio
async def test_write_candidates_wraps_api_error_with_sanitized_message(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateWriter]],
) -> None:
    await _seed_binding(db_session)
    stub, make_writer = rig
    stub.create_error = (1254607, "field value invalid: token t-writer-token s3cret")

    with pytest.raises(BitableCandidateWriteError) as caught:
        await make_writer().write_candidates(run_id=RUN_ID, candidates=(_candidate("url:key"),))

    message = str(caught.value)
    assert "1254607" in message
    assert "t-writer-token" not in message
    assert "s3cret" not in message


@pytest.mark.anyio
async def test_write_serializes_on_binding_advisory_lock(
    db_session: AsyncSession,
    rig: tuple[_BitableStub, Callable[[], BitableCandidateWriter]],
) -> None:
    """另一事务持有同绑定 advisory lock 时，writer 的查重+创建整体阻塞（串行化同表写入）。"""
    binding = await _seed_binding(db_session)
    stub, make_writer = rig
    await db_session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": write_lock_key(binding.id)},
    )
    try:
        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(1):
                await make_writer().write_candidates(run_id=RUN_ID, candidates=(_candidate("url:key"),))
        assert stub.created_bodies == []  # 锁内才允许查重与写入
    finally:
        await db_session.rollback()  # 释放 xact lock

    # 锁释放后可正常写入
    assert await make_writer().write_candidates(run_id=RUN_ID, candidates=(_candidate("url:key"),)) == 1
