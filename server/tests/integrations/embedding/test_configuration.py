"""load_embedding_config 的 DB 优先 / env 回退 / 缺省 / 密文损坏分支测试。"""

import base64
from collections.abc import AsyncIterator, Iterator

import pytest
from reven.config import get_settings
from reven.integrations.embedding.configuration import (
    DEFAULT_EMBEDDING_BASE_URL,
    EmbeddingConfig,
    load_embedding_config,
)
from reven.integrations.errors import IntegrationConfigurationError
from reven.integrations.models import Integration
from reven.rss.embedding import BGE_M3_MODEL
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


@pytest.fixture
async def factory(db_session: AsyncSession) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield async_sessionmaker(db_session.bind, expire_on_commit=False)


def _secret_box() -> SecretBox:
    return SecretBox.from_base64(TEST_MASTER_KEY)


@pytest.mark.anyio
async def test_db_config_takes_precedence_over_env(
    db_session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-env-should-lose")
    get_settings.cache_clear()
    db_session.add(
        Integration(
            provider="embedding",
            public_config={"base_url": "https://embedding.example.com", "model": "custom/model"},
            encrypted_secret=_secret_box().encrypt({"api_key": "sk-db-wins"}),
        )
    )
    await db_session.commit()

    config = await load_embedding_config(factory)

    assert config == EmbeddingConfig(
        base_url="https://embedding.example.com", model="custom/model", api_key="sk-db-wins"
    )


@pytest.mark.anyio
async def test_db_config_falls_back_to_default_base_url_and_model(
    db_session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    settings_env: None,
) -> None:
    db_session.add(
        Integration(
            provider="embedding",
            public_config={},
            encrypted_secret=_secret_box().encrypt({"api_key": "sk-db"}),
        )
    )
    await db_session.commit()

    config = await load_embedding_config(factory)

    assert config == EmbeddingConfig(base_url=DEFAULT_EMBEDDING_BASE_URL, model=BGE_M3_MODEL, api_key="sk-db")


@pytest.mark.anyio
async def test_env_fallback_when_db_missing(
    factory: async_sessionmaker[AsyncSession],
    settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-env")
    get_settings.cache_clear()

    config = await load_embedding_config(factory)

    assert config == EmbeddingConfig(base_url=DEFAULT_EMBEDDING_BASE_URL, model=BGE_M3_MODEL, api_key="sk-env")


@pytest.mark.anyio
async def test_db_row_without_secret_falls_back_to_env(
    db_session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    settings_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-env")
    get_settings.cache_clear()
    db_session.add(Integration(provider="embedding", public_config={"base_url": "https://embedding.example.com"}))
    await db_session.commit()

    config = await load_embedding_config(factory)

    assert config is not None
    assert config.api_key == "sk-env"


@pytest.mark.anyio
async def test_returns_none_when_neither_db_nor_env(
    factory: async_sessionmaker[AsyncSession],
    settings_env: None,
) -> None:
    assert await load_embedding_config(factory) is None


@pytest.mark.anyio
async def test_corrupted_secret_raises_domain_error(
    db_session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    settings_env: None,
) -> None:
    db_session.add(Integration(provider="embedding", public_config={}, encrypted_secret="v1:corrupted"))
    await db_session.commit()

    with pytest.raises(IntegrationConfigurationError) as caught:
        await load_embedding_config(factory)

    assert caught.value.code == "INTEGRATION_SECRET_INVALID"
