"""模型注册表读取（#163）：默认条目 + 附加条目、禁用过滤、key 回落、env 兜底、解密降级。

注册表存于 agent-llm 集成行（provider 列 UNIQUE，单行承载）：顶层为默认模型，
public_config["models"] 为附加条目，独立 key 存 secret 扁平键 "model_key:<ref>"。
"""

import base64
import logging
from collections.abc import AsyncIterator

import pytest
from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.models import Integration
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"r" * 32).decode()
OTHER_MASTER_KEY = base64.urlsafe_b64encode(b"o" * 32).decode()


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://unused:unused@127.0.0.1/unused",
        "reven_master_key": TEST_MASTER_KEY,
        "reven_admin_password": "test-admin-password",
        "siliconflow_api_key": None,
        "agent_api_key": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
async def credentials(db_session: AsyncSession) -> AsyncIterator[IntegrationCredentials]:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    yield IntegrationCredentials(factory, _settings())


async def _save(
    session: AsyncSession,
    *,
    public_config: dict[str, object],
    secret: dict[str, str] | None,
    master_key: str = TEST_MASTER_KEY,
) -> None:
    encrypted = SecretBox.from_base64(master_key).encrypt(secret) if secret is not None else None
    session.add(Integration(provider="agent-llm", public_config=public_config, encrypted_secret=encrypted))
    await session.commit()


@pytest.mark.anyio
async def test_registry_returns_default_entry_only_when_no_extra_models(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    """无 models 数组时注册表仅含默认条目（向后兼容现有配置页写法）。"""
    await _save(
        db_session,
        public_config={
            "provider": "deepseek-official",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
        },
        secret={"api_key": "sk-default"},
    )

    entries = await credentials.agent_llm_models()

    assert entries is not None
    assert len(entries) == 1
    (default,) = entries
    assert default.ref == "deepseek-official/deepseek-v4-flash"
    assert default.is_default
    assert default.api_key == "sk-default"
    assert default.base_url == "https://api.deepseek.com"


@pytest.mark.anyio
async def test_registry_lists_enabled_extra_models_with_key_fallback(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    """附加条目启用者入册：独立 key 走 model_key:<ref>，缺省回落默认条目 key。"""
    await _save(
        db_session,
        public_config={
            "provider": "deepseek-official",
            "model": "deepseek-v4-flash",
            "models": [
                {"provider": "openai", "model": "gpt-5", "base_url": "https://api.openai.com/v1", "enabled": True},
                {"provider": "deepseek-official", "model": "deepseek-v4-pro"},  # 无独立 key → 回落
                {"provider": "anthropic", "model": "claude-sonnet-4", "enabled": False},  # 禁用 → 过滤
            ],
        },
        secret={"api_key": "sk-default", "model_key:openai/gpt-5": "sk-openai"},
    )

    entries = await credentials.agent_llm_models()

    assert entries is not None
    assert [entry.ref for entry in entries] == [
        "deepseek-official/deepseek-v4-flash",
        "openai/gpt-5",
        "deepseek-official/deepseek-v4-pro",
    ]
    by_ref = {entry.ref: entry for entry in entries}
    assert by_ref["openai/gpt-5"].api_key == "sk-openai"
    assert by_ref["openai/gpt-5"].base_url == "https://api.openai.com/v1"
    assert not by_ref["openai/gpt-5"].is_default
    assert by_ref["deepseek-official/deepseek-v4-pro"].api_key == "sk-default"  # key 回落
    assert by_ref["deepseek-official/deepseek-v4-pro"].base_url is None


@pytest.mark.anyio
async def test_registry_skips_malformed_and_duplicate_entries(
    db_session: AsyncSession, credentials: IntegrationCredentials, caplog: pytest.LogCaptureFixture
) -> None:
    """畸形/缺字段/与默认条目 ref 重复的附加条目跳过并记脱敏日志。"""
    await _save(
        db_session,
        public_config={
            "provider": "deepseek-official",
            "model": "deepseek-v4-flash",
            "models": [
                "not-a-dict",
                {"provider": "openai"},  # 缺 model
                {"provider": "deepseek-official", "model": "deepseek-v4-flash"},  # 与默认重复
                {"provider": "openai", "model": "gpt-5"},
            ],
        },
        secret={"api_key": "sk-default"},
    )

    with caplog.at_level(logging.WARNING, logger="reven.integrations.credentials"):
        entries = await credentials.agent_llm_models()

    assert entries is not None
    assert [entry.ref for entry in entries] == ["deepseek-official/deepseek-v4-flash", "openai/gpt-5"]
    assert "sk-default" not in caplog.text  # 日志脱敏：任何跳过都不带配置/凭证内容


@pytest.mark.anyio
async def test_registry_env_fallback_when_db_missing(db_session: AsyncSession) -> None:
    """无 DB 行时 env 兜底为单条目注册表（env 模型即默认）。"""
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    credentials = IntegrationCredentials(factory, _settings(agent_api_key="sk-env", agent_model="env-model"))

    entries = await credentials.agent_llm_models()

    assert entries is not None
    (entry,) = entries
    assert entry.is_default
    assert entry.api_key == "sk-env"
    assert entry.model == "env-model"


@pytest.mark.anyio
async def test_registry_returns_none_when_unconfigured(credentials: IntegrationCredentials) -> None:
    assert await credentials.agent_llm_models() is None


@pytest.mark.anyio
async def test_registry_undecryptable_falls_back_to_env(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """密文损坏：记错误日志并回退 env 注册表（与 agent_llm() 同纪律）。"""
    await _save(
        db_session,
        public_config={"models": [{"provider": "p", "model": "m"}]},
        secret={"api_key": "sk-db"},
        master_key=OTHER_MASTER_KEY,
    )
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    credentials = IntegrationCredentials(factory, _settings(agent_api_key="sk-env"))

    with caplog.at_level(logging.ERROR, logger="reven.integrations.credentials"):
        entries = await credentials.agent_llm_models()

    assert entries is not None
    (entry,) = entries
    assert entry.api_key == "sk-env"
    assert "解密失败" in caplog.text
    assert "sk-db" not in caplog.text
