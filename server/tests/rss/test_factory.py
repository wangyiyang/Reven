"""rss/factory.py 的 embedder 装配、回填兜底与关键词刷新器测试。"""

import base64
from collections.abc import Iterator
from datetime import date
from uuid import uuid4

import httpx
import pytest
import respx
from reven.config import get_settings
from reven.integrations.embedding.configuration import EmbeddingConfig
from reven.integrations.models import Integration
from reven.rss.embedding import BGE_M3_MODEL, EmbeddingError, SiliconFlowEmbeddingClient
from reven.rss.factory import (
    ConfiguredKeywordEmbeddingRefresher,
    _UnavailableSiliconFlow,
    configured_embedder,
    record_backfill_error,
)
from reven.rss.models import RssDiscoveryRun
from reven.rss.repository import RssSettingsRepository
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://reven:reven@localhost/reven")
    monkeypatch.setenv("REVEN_MASTER_KEY", TEST_MASTER_KEY)
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_unavailable_embedder_raises_concrete_code() -> None:
    unavailable = _UnavailableSiliconFlow()
    with pytest.raises(EmbeddingError) as caught:
        await unavailable.embed(("text",))
    assert caught.value.code == "EMBEDDING_NOT_CONFIGURED"


@pytest.mark.anyio
async def test_configured_embedder_uses_db_base_url_and_model() -> None:
    config = EmbeddingConfig(base_url="https://embedding.example.com", model="custom/model", api_key="sk-test")
    async with configured_embedder(config) as embedder:
        assert isinstance(embedder, SiliconFlowEmbeddingClient)
        assert embedder.model == "custom/model"
    async with configured_embedder(None) as fallback:
        assert isinstance(fallback, _UnavailableSiliconFlow)


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
async def test_refresher_raises_when_nothing_configured(db_session: AsyncSession, settings_env: None) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    with pytest.raises(RuntimeError, match="SILICONFLOW_API_KEY_NOT_CONFIGURED"):
        await ConfiguredKeywordEmbeddingRefresher(factory).refresh()


@pytest.mark.anyio
@respx.mock
async def test_refresher_uses_db_config(db_session: AsyncSession, settings_env: None) -> None:
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

    assert await ConfiguredKeywordEmbeddingRefresher(factory).refresh() == 1
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-db"
