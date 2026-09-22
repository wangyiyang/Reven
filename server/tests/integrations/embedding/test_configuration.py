"""load_embedding_config 薄封装：seam 原始凭证套上默认 base_url/model。

DB 优先 / env 回退 / 密文损坏等凭证语义由 tests/integrations/test_credentials.py 覆盖。
"""

import base64
from collections.abc import AsyncIterator, Iterator

import pytest
from reven.config import get_settings
from reven.integrations.embedding.configuration import (
    DEFAULT_EMBEDDING_BASE_URL,
    EmbeddingConfig,
    load_embedding_config,
)
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


@pytest.mark.anyio
async def test_empty_public_config_falls_back_to_default_base_url_and_model(
    db_session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    settings_env: None,
) -> None:
    db_session.add(
        Integration(
            provider="embedding",
            public_config={},
            encrypted_secret=SecretBox.from_base64(TEST_MASTER_KEY).encrypt({"api_key": "sk-db"}),
        )
    )
    await db_session.commit()

    config = await load_embedding_config(factory)

    assert config == EmbeddingConfig(base_url=DEFAULT_EMBEDDING_BASE_URL, model=BGE_M3_MODEL, api_key="sk-db")


@pytest.mark.anyio
async def test_explicit_public_config_passes_through(
    db_session: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    settings_env: None,
) -> None:
    db_session.add(
        Integration(
            provider="embedding",
            public_config={"base_url": "https://embedding.example.com", "model": "custom/model"},
            encrypted_secret=SecretBox.from_base64(TEST_MASTER_KEY).encrypt({"api_key": "sk-db"}),
        )
    )
    await db_session.commit()

    config = await load_embedding_config(factory)

    assert config == EmbeddingConfig(base_url="https://embedding.example.com", model="custom/model", api_key="sk-db")
