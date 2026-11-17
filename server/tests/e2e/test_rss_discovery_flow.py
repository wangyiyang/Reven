"""端到端：RSS 抓取 → 内存筛选 → 候选直写 Bitable（飞书侧用 MockTransport stub，零网络）。"""

import base64
import json
from datetime import UTC, date, datetime

import httpx
import pytest
from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.bitable import RSS_CANDIDATES_REQUIRED_FIELDS
from reven.integrations.models import FeishuResourceBinding, Integration
from reven.provider_clients import ProviderClients
from reven.rss.bitable_writer import BitableCandidateWriter
from reven.rss.discovery import FeedEntry, LocalizedEntry, RssDiscoveryService
from reven.rss.embedding import BGE_M3_DIMENSION, BGE_M3_MODEL, EmbedOutcome, KeywordEmbeddingService
from reven.rss.factory import RssCandidatePipeline
from reven.rss.models import RssItem, RssSource
from reven.rss.repository import RssSettingsRepository
from reven.rss.screening import RssScreeningEngine
from reven.rss.screening_service import RssScreeningService
from reven.security.secrets import SecretBox
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()


class Feed:
    async def fetch(self, source: RssSource) -> tuple[FeedEntry, ...]:
        return (
            FeedEntry(
                "agent-1",
                "https://example.com/agent-1",
                "AI agent architecture",
                "Practical engineering patterns",
                datetime(2026, 8, 11, 1, tzinfo=UTC),
            ),
        )


class Localizer:
    async def localize(self, entries: tuple[FeedEntry, ...]) -> tuple[LocalizedEntry, ...]:
        return tuple(LocalizedEntry(entry, "AI 智能体架构", "实用工程模式") for entry in entries)


class Embedder:
    model = BGE_M3_MODEL
    dimension = BGE_M3_DIMENSION

    async def embed(self, texts: tuple[str, ...]) -> EmbedOutcome:
        vector = tuple([1.0] + [0.0] * (self.dimension - 1))
        return EmbedOutcome(tuple(vector for _text in texts), tuple(None for _text in texts))


class Notifier:
    def __init__(self) -> None:
        self.messages: list[object] = []

    async def send(self, message: object) -> None:
        self.messages.append(message)


class BitableStub:
    """字段预检通过（含状态选项）+ 查重为空 + 记录创建的飞书 Bitable stub。"""

    def __init__(self) -> None:
        self.created_bodies: list[dict[str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/auth/" in path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-e2e-token"})
        if path.endswith("/fields"):
            items = []
            for index, (name, field_type) in enumerate(RSS_CANDIDATES_REQUIRED_FIELDS):
                item: dict[str, object] = {"field_id": f"fld_{index}", "field_name": name, "type": field_type}
                if name == "状态":
                    item["property"] = {"options": [{"name": o} for o in ("candidate", "saved", "ignored")]}
                items.append(item)
            return httpx.Response(200, json={"code": 0, "data": {"items": items, "has_more": False}})
        if path.endswith("/records/search"):
            return httpx.Response(200, json={"code": 0, "data": {"items": [], "has_more": False}})
        if path.endswith("/records/batch_create"):
            body = json.loads(request.content)
            self.created_bodies.append(body)
            records = [
                {"record_id": f"rec_{index}", "fields": record["fields"]}
                for index, record in enumerate(body["records"])
            ]
            return httpx.Response(200, json={"code": 0, "data": {"records": records}})
        return httpx.Response(500, json={"code": 500, "msg": "unexpected"})


@pytest.mark.anyio
async def test_rss_discovery_writes_candidates_to_bitable_idempotently(
    db_session: AsyncSession,
) -> None:
    source = RssSource(name="Example", feed_url="https://example.com/e2e.xml", enabled=True)
    db_session.add(source)
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    integration = Integration(
        provider="feishu_bot",
        public_config={"enabled": True, "whitelist_open_ids": ["ou_e2e"]},
        encrypted_secret=SecretBox.from_base64(TEST_MASTER_KEY).encrypt({"app_id": "cli_e2e", "app_secret": "s3cret"}),
    )
    db_session.add(integration)
    await db_session.flush()
    db_session.add(
        FeishuResourceBinding(
            integration_id=integration.id,
            resource_type="bitable",
            purpose="rss_candidates",
            config={"app_token": "bascn_e2e", "table_id": "tbl_e2e"},
            enabled=True,
        )
    )
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    stub = BitableStub()
    settings = Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1/unused",
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
        siliconflow_api_key=None,
        agent_api_key=None,
        _env_file=None,
    )
    clients = ProviderClients(
        IntegrationCredentials(factory, settings),
        settings,
        feishu_transport=httpx.MockTransport(stub),
    )
    notifier = Notifier()
    pipeline = RssCandidatePipeline(
        RssScreeningService(factory, KeywordEmbeddingService(factory, Embedder()), RssScreeningEngine()),
        BitableCandidateWriter(factory, clients),
    )
    discovery = RssDiscoveryService(
        factory,
        Feed(),
        Localizer(),
        notifier,
        screener=pipeline,
        candidate_url="http://reven.example/rss/candidates",
    )

    first = await discovery.run(date(2026, 8, 11))
    second = await discovery.run(date(2026, 8, 11))
    await clients.aclose()

    # 同日重跑幂等：同一 run，候选只写一次
    assert first.run_id == second.run_id
    assert first.status == "completed"
    assert first.candidate_count == 1
    assert len(notifier.messages) == 1
    assert len(stub.created_bodies) == 1

    # 九字段完整写入，状态初始 candidate，client_token 稳定
    record = stub.created_bodies[0]["records"][0]
    fields = record["fields"]
    assert set(fields) == {name for name, _type in RSS_CANDIDATES_REQUIRED_FIELDS}
    assert fields["标题"] == "AI 智能体架构"
    assert fields["摘要"] == "实用工程模式"
    assert fields["来源"] == "Example"
    assert fields["状态"] == "candidate"
    assert fields["命中关键词"] == "AI 智能体"
    assert fields["原文链接"] == {"link": "https://example.com/agent-1", "text": "AI 智能体架构"}
    assert fields["去重键"].startswith("url:")
    assert record["client_token"].startswith(f"{first.run_id}:")

    # 条目不落 PG
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(RssItem)) == 0
