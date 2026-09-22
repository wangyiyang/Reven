"""resolve_agent_config 测试：凭证 seam 映射，env fallback，失败显式降级。

凭证解析语义（DB 优先/解密降级/构造失败抛错）由 tests/integrations/test_credentials.py 覆盖；
本文件只打 resolve_agent_config 的 AgentConfig 映射与 credentials=None 降级路径。
"""

import base64
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from reven.agent.config import AgentConfig, resolve_agent_config
from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.models import Integration
from reven.integrations.repository import IntegrationRepository
from reven.integrations.service import HINT_KEY
from reven.security.secrets import SecretBox
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
OTHER_MASTER_KEY = base64.urlsafe_b64encode(b"o" * 32).decode()


def _make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://unused:unused@127.0.0.1/unused",
        "reven_master_key": TEST_MASTER_KEY,
        "reven_admin_password": "test-admin-password",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping integration tests")
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE integrations RESTART IDENTITY CASCADE"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _save_integration(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    public_config: dict[str, object],
    api_key: str | None,
    master_key: str = TEST_MASTER_KEY,
) -> None:
    encrypted = SecretBox.from_base64(master_key).encrypt({"api_key": api_key}) if api_key else None
    if encrypted:
        public_config = {**public_config, HINT_KEY: "已配置 · ****test"}
    async with session_factory() as session:
        await IntegrationRepository(session).save(
            Integration(provider="agent-llm", public_config=public_config, encrypted_secret=encrypted)
        )
        await session.commit()


@pytest.mark.anyio
async def test_resolves_config_from_integration_table(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await _save_integration(
        session_factory,
        public_config={
            "provider": "deepseek-official",
            "model": "deepseek-v4-pro",
            "base_url": "https://api.deepseek.com",
        },
        api_key="sk-db-key",
    )
    settings = _make_settings(dsh_home=tmp_path / "dsh")

    config = await resolve_agent_config(IntegrationCredentials(session_factory, settings), settings)

    assert config == AgentConfig(
        provider="deepseek-official",
        model="deepseek-v4-pro",
        base_url="https://api.deepseek.com",
        api_key="sk-db-key",
        dsh_home=tmp_path / "dsh",
        cwd=tmp_path / "dsh",
    )


@pytest.mark.anyio
async def test_db_config_wins_over_env(session_factory: async_sessionmaker[AsyncSession], tmp_path: Path) -> None:
    await _save_integration(
        session_factory, public_config={"provider": "deepseek-official", "model": "m"}, api_key="sk-db"
    )
    settings = _make_settings(dsh_home=tmp_path / "dsh", agent_api_key="sk-env")

    config = await resolve_agent_config(IntegrationCredentials(session_factory, settings), settings)

    assert config is not None
    assert config.api_key == "sk-db"


@pytest.mark.anyio
async def test_falls_back_to_env_when_db_empty(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    settings = _make_settings(dsh_home=tmp_path / "dsh", agent_api_key="sk-env", agent_model="env-model")

    config = await resolve_agent_config(IntegrationCredentials(session_factory, settings), settings)

    assert config is not None
    assert config.api_key == "sk-env"
    assert config.model == "env-model"


@pytest.mark.anyio
async def test_returns_none_when_unconfigured(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    settings = _make_settings(dsh_home=tmp_path / "dsh")
    assert await resolve_agent_config(IntegrationCredentials(session_factory, settings), settings) is None


@pytest.mark.anyio
async def test_falls_back_when_integration_has_no_secret(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    await _save_integration(session_factory, public_config={"provider": "p", "model": "m"}, api_key=None)
    settings = _make_settings(dsh_home=tmp_path / "dsh")

    assert await resolve_agent_config(IntegrationCredentials(session_factory, settings), settings) is None


@pytest.mark.anyio
async def test_undecryptable_secret_degrades_to_none(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    await _save_integration(
        session_factory,
        public_config={"provider": "p", "model": "m"},
        api_key="sk-db",
        master_key=OTHER_MASTER_KEY,
    )
    settings = _make_settings(dsh_home=tmp_path / "dsh")

    with caplog.at_level("ERROR", logger="reven.integrations.credentials"):
        config = await resolve_agent_config(IntegrationCredentials(session_factory, settings), settings)

    assert config is None
    assert any("解密失败" in record.message for record in caplog.records)


@pytest.mark.anyio
async def test_credentials_unavailable_uses_env_only(tmp_path: Path) -> None:
    """credentials 为 None（无库或 seam 构造失败降级）时只走 env fallback，绝不抛出。"""
    settings = _make_settings(dsh_home=tmp_path / "dsh", agent_api_key="sk-env")

    config = await resolve_agent_config(None, settings)

    assert config is not None
    assert config.api_key == "sk-env"
