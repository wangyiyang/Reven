"""rss/factory.py 的回填兜底、发现任务装配与关键词刷新器测试。

embedding/chat 客户端装配与默认值语义由 tests/test_provider_clients.py 在 seam 接口上覆盖。
"""

import base64
from datetime import UTC, date, datetime
from urllib.parse import parse_qsl
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.models import Integration
from reven.provider_clients import ProviderClients
from reven.rss.discovery import FeedEntry
from reven.rss.embedding import BGE_M3_MODEL, EmbeddingError
from reven.rss.factory import (
    KeywordEmbeddingRefresher,
    RssDiscoveryJob,
    _UnavailableSiliconFlow,
    record_backfill_error,
)
from reven.rss.models import RssDiscoveryRun, RssItem, RssKeyword, RssSource
from reven.rss.repository import RssSettingsRepository
from reven.security.secrets import SecretBox
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()


@pytest.fixture
def settings() -> Settings:
    """显式构造测试 Settings：不读进程 env（含 .env），SiliconFlow/Agent env 显式为空。"""
    return Settings(
        database_url="postgresql+asyncpg://reven:reven@localhost/reven",
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
        siliconflow_api_key=None,
        agent_api_key=None,
        _env_file=None,
    )


def _clients(db_session: AsyncSession, settings: Settings) -> ProviderClients:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    return ProviderClients(IntegrationCredentials(factory, settings), settings)


@pytest.mark.anyio
async def test_unavailable_embedder_raises_concrete_code() -> None:
    unavailable = _UnavailableSiliconFlow()
    with pytest.raises(EmbeddingError) as caught:
        await unavailable.embed(("text",))
    assert caught.value.code == "EMBEDDING_NOT_CONFIGURED"


@pytest.mark.anyio
async def test_record_backfill_error_marks_run_partial(db_session: AsyncSession) -> None:
    run = RssDiscoveryRun(run_date=date(2026, 8, 25), status="completed")
    db_session.add(run)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    await record_backfill_error(factory, run.id, "EMBEDDING_TIMEOUT")

    async with factory() as session:
        stored = await session.get(RssDiscoveryRun, run.id)
        assert stored is not None
        assert stored.status == "partial"
        assert stored.failure_count == 1
        assert stored.errors == [{"stage": "backfill", "error_type": "EMBEDDING_TIMEOUT"}]


@pytest.mark.anyio
async def test_record_backfill_error_ignores_missing_run(db_session: AsyncSession) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    await record_backfill_error(factory, uuid4(), "EMBEDDING_TIMEOUT")


@pytest.mark.anyio
async def test_refresher_raises_when_nothing_configured(db_session: AsyncSession, settings: Settings) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    with pytest.raises(RuntimeError, match="SILICONFLOW_API_KEY_NOT_CONFIGURED"):
        await KeywordEmbeddingRefresher(factory, _clients(db_session, settings)).refresh()


@pytest.mark.anyio
async def test_refresher_raises_when_clients_degraded(db_session: AsyncSession) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    with pytest.raises(RuntimeError, match="SILICONFLOW_API_KEY_NOT_CONFIGURED"):
        await KeywordEmbeddingRefresher(factory, None).refresh()


@pytest.mark.anyio
@respx.mock
async def test_refresher_embeds_keywords_via_seam(db_session: AsyncSession, settings: Settings) -> None:
    db_session.add(
        Integration(
            provider="embedding",
            public_config={"base_url": "https://embedding.example.com", "model": BGE_M3_MODEL},
            encrypted_secret=SecretBox.from_base64(TEST_MASTER_KEY).encrypt({"api_key": "sk-db"}),
        )
    )
    await RssSettingsRepository(db_session).create_keyword(term="AI 智能体", kind="positive", enabled=True)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    route = respx.post("https://embedding.example.com/v1/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "list",
                "model": BGE_M3_MODEL,
                "data": [{"object": "embedding", "index": 0, "embedding": [0.5] * 1024}],
            },
        )
    )

    assert await KeywordEmbeddingRefresher(factory, _clients(db_session, settings)).refresh() == 1
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-db"


def _embedding_integration() -> Integration:
    return Integration(
        provider="embedding",
        public_config={"base_url": "https://embedding.example.com", "model": BGE_M3_MODEL},
        encrypted_secret=SecretBox.from_base64(TEST_MASTER_KEY).encrypt({"api_key": "sk-db"}),
    )


def _embedding_route(vectors: list[list[float]]) -> respx.Route:
    return respx.post("https://embedding.example.com/v1/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "list",
                "model": BGE_M3_MODEL,
                "data": [
                    {"object": "embedding", "index": index, "embedding": vector} for index, vector in enumerate(vectors)
                ],
            },
        )
    )


async def _seed_items(db_session: AsyncSession, titles: list[str]) -> None:
    run = RssDiscoveryRun(run_date=date(2026, 9, 28), status="completed")
    db_session.add(run)
    await db_session.flush()
    for index, title in enumerate(titles):
        db_session.add(
            RssItem(
                first_seen_run_id=run.id,
                source_name="Example",
                title_key=f"title-key-{index}",
                title=title,
                title_zh=title,
            )
        )


async def _seed_embedded_keyword(db_session: AsyncSession) -> UUID:
    keyword = RssKeyword(
        term="具身智能",
        normalized_term="具身智能",
        kind="positive",
        enabled=True,
        embedding=[0.5] * 1024,
        embedding_model=BGE_M3_MODEL,
        embedding_dimension=1024,
    )
    db_session.add(keyword)
    await db_session.commit()
    return keyword.id


@pytest.mark.anyio
@respx.mock
async def test_estimate_hits_counts_items_above_screening_threshold(
    db_session: AsyncSession, settings: Settings
) -> None:
    db_session.add(_embedding_integration())
    await _seed_items(db_session, ["具身智能取得突破", "今日天气预报"])
    keyword_id = await _seed_embedded_keyword(db_session)
    # 第一条与词向量同向（cosine=1.0，超筛选阈值 0.55），第二条反向（cosine=-1.0）
    _embedding_route([[0.5] * 1024, [-0.5] * 1024])
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    assert await KeywordEmbeddingRefresher(factory, _clients(db_session, settings)).estimate_hits(keyword_id) == 1


@pytest.mark.anyio
async def test_estimate_hits_returns_zero_when_item_store_empty(db_session: AsyncSession, settings: Settings) -> None:
    keyword_id = await _seed_embedded_keyword(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    assert await KeywordEmbeddingRefresher(factory, _clients(db_session, settings)).estimate_hits(keyword_id) == 0


@pytest.mark.anyio
async def test_estimate_hits_returns_none_when_embedder_not_configured(
    db_session: AsyncSession, settings: Settings
) -> None:
    await _seed_items(db_session, ["具身智能取得突破"])
    keyword_id = await _seed_embedded_keyword(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    assert await KeywordEmbeddingRefresher(factory, _clients(db_session, settings)).estimate_hits(keyword_id) is None
    assert await KeywordEmbeddingRefresher(factory, None).estimate_hits(keyword_id) is None


@pytest.mark.anyio
async def test_estimate_hits_returns_none_when_keyword_vector_missing(
    db_session: AsyncSession, settings: Settings
) -> None:
    await RssSettingsRepository(db_session).create_keyword(term="无向量", kind="positive", enabled=True)
    await db_session.commit()
    keyword_id = (await RssSettingsRepository(db_session).list_keywords())[0].id
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    assert await KeywordEmbeddingRefresher(factory, _clients(db_session, settings)).estimate_hits(keyword_id) is None


class _SingleEntryFeedReader:
    async def fetch(self, source: RssSource) -> tuple[FeedEntry, ...]:
        del source
        return (
            FeedEntry(
                guid="factory-translation",
                url="https://example.com/factory-translation",
                title="Agent systems",
                summary="",
                published_at=datetime(2026, 8, 25, tzinfo=UTC),
            ),
        )


class _RecordingNotifier:
    def __init__(self) -> None:
        self.notifications: list[object] = []

    async def send(self, notification: object) -> None:
        self.notifications.append(notification)


@pytest.mark.anyio
@respx.mock
async def test_discovery_tick_uses_db_translation_without_qwen(
    db_session: AsyncSession,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add_all(
        [
            RssSource(name="Example", feed_url="https://example.com/feed.xml", enabled=True),
            Integration(
                provider="translate_baidu",
                public_config={"priority": 1, "enabled": True},
                encrypted_secret=SecretBox.from_base64(TEST_MASTER_KEY).encrypt(
                    {"app_id": "baidu-app-id", "app_key": "baidu-app-key"}
                ),
            ),
        ]
    )
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr("reven.rss.factory.SecureFeedReader", _SingleEntryFeedReader)

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(parse_qsl(request.url.query.decode()))
        assert params["q"] == "Agent systems"
        assert params["from"] == "auto"
        return httpx.Response(200, json={"trans_result": [{"src": "Agent systems", "dst": "智能体系统"}]})

    route = respx.get("https://fanyi-api.baidu.com/api/trans/vip/translate").mock(side_effect=handler)
    notifier = _RecordingNotifier()

    await RssDiscoveryJob(factory, _clients(db_session, settings), settings, notifier).run(date(2026, 8, 25))

    async with factory() as session:
        item = await session.scalar(select(RssItem))
    assert item is not None
    assert item.title_zh == "智能体系统"
    assert item.summary_zh == ""
    assert route.call_count == 1
    assert len(notifier.notifications) == 1
