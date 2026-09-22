"""IntegrationCredentials seam 测试：唯一 SecretBox 构造点、typed credentials、hint 剥离、env 兜底、解密降级。"""

import base64
import logging
from collections.abc import AsyncIterator

import pytest
from reven.config import Settings
from reven.integrations.credentials import (
    DEFAULT_AGENT_LLM_MODEL,
    DEFAULT_AGENT_LLM_PROVIDER,
    IntegrationCredentials,
)
from reven.integrations.errors import IntegrationConfigurationError
from reven.integrations.feishu_bot.config import FeishuBotConfig
from reven.integrations.models import Integration
from reven.integrations.service import HINT_KEY
from reven.integrations.translation.configuration import AliyunTranslationConfig, BaiduTranslationConfig
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
OTHER_MASTER_KEY = base64.urlsafe_b64encode(b"o" * 32).decode()
BOT_SECRET = {"app_id": "cli_test", "app_secret": "s3cret-bot-value"}


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


def _box(master_key: str = TEST_MASTER_KEY) -> SecretBox:
    return SecretBox.from_base64(master_key)


@pytest.fixture
async def credentials(db_session: AsyncSession) -> AsyncIterator[IntegrationCredentials]:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    yield IntegrationCredentials(factory, _settings())


async def _save(
    session: AsyncSession,
    provider: str,
    *,
    public_config: dict[str, object],
    secret: dict[str, str] | None,
    master_key: str = TEST_MASTER_KEY,
) -> None:
    encrypted = _box(master_key).encrypt(secret) if secret is not None else None
    if encrypted is not None:
        public_config = {**public_config, HINT_KEY: "已配置 · ****test"}
    session.add(Integration(provider=provider, public_config=public_config, encrypted_secret=encrypted))
    await session.commit()


# --- feishu_bot ---


@pytest.mark.anyio
async def test_feishu_bot_missing_row_returns_none(credentials: IntegrationCredentials) -> None:
    assert await credentials.resolve("feishu_bot") is None


@pytest.mark.anyio
async def test_feishu_bot_disabled_returns_none(db_session: AsyncSession, credentials: IntegrationCredentials) -> None:
    await _save(db_session, "feishu_bot", public_config={"enabled": False}, secret=BOT_SECRET)

    assert await credentials.resolve("feishu_bot") is None


@pytest.mark.anyio
async def test_feishu_bot_missing_secret_returns_none(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    await _save(db_session, "feishu_bot", public_config={"enabled": True}, secret=None)

    assert await credentials.resolve("feishu_bot") is None


@pytest.mark.anyio
async def test_feishu_bot_incomplete_secret_returns_none(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    await _save(db_session, "feishu_bot", public_config={"enabled": True}, secret={"app_id": "cli_test"})

    assert await credentials.resolve("feishu_bot") is None


@pytest.mark.anyio
async def test_feishu_bot_undecryptable_returns_none_without_leaking(
    db_session: AsyncSession,
    credentials: IntegrationCredentials,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db_session.add(
        Integration(
            provider="feishu_bot",
            public_config={"whitelist_open_ids": ["ou_boss"], "enabled": True},
            encrypted_secret="v1:not-a-valid-ciphertext",
        )
    )
    await db_session.commit()

    with caplog.at_level(logging.WARNING):
        assert await credentials.resolve("feishu_bot") is None

    assert any("feishu_bot" in record.getMessage() for record in caplog.records)
    assert "s3cret-bot-value" not in caplog.text
    assert "not-a-valid-ciphertext" not in caplog.text


@pytest.mark.anyio
async def test_feishu_bot_enabled_returns_credentials_and_whitelist(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    await _save(
        db_session,
        "feishu_bot",
        public_config={"enabled": True, "whitelist_open_ids": ["ou_boss", "ou_backup"]},
        secret=BOT_SECRET,
    )

    config = await credentials.resolve("feishu_bot")

    assert config == FeishuBotConfig(
        app_id="cli_test",
        app_secret="s3cret-bot-value",
        whitelist_open_ids=("ou_boss", "ou_backup"),
    )


@pytest.mark.anyio
async def test_feishu_bot_malformed_whitelist_is_filtered(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    await _save(
        db_session,
        "feishu_bot",
        public_config={"enabled": True, "whitelist_open_ids": ["ou_boss", "", "   ", "ou_boss", 42, None]},
        secret=BOT_SECRET,
    )

    config = await credentials.resolve("feishu_bot")

    assert config is not None
    assert config.whitelist_open_ids == ("ou_boss",)


@pytest.mark.anyio
async def test_feishu_bot_non_list_whitelist_yields_empty(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    await _save(
        db_session, "feishu_bot", public_config={"enabled": True, "whitelist_open_ids": "ou_boss"}, secret=BOT_SECRET
    )

    config = await credentials.resolve("feishu_bot")

    assert config is not None
    assert config.whitelist_open_ids == ()


def test_feishu_bot_config_repr_hides_credentials() -> None:
    config = FeishuBotConfig(app_id="cli_test", app_secret="s3cret-bot-value", whitelist_open_ids=("ou_boss",))

    rendered = repr(config)
    assert "s3cret-bot-value" not in rendered
    assert "cli_test" not in rendered


# --- embedding ---


@pytest.mark.anyio
async def test_embedding_db_config_wins_over_env(db_session: AsyncSession) -> None:
    await _save(
        db_session,
        "embedding",
        public_config={"base_url": "https://embedding.example.com", "model": "custom/model"},
        secret={"api_key": "sk-db-wins"},
    )
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    credentials = IntegrationCredentials(factory, _settings(siliconflow_api_key="sk-env-should-lose"))

    resolved = await credentials.resolve("embedding")

    assert resolved is not None
    assert resolved.api_key == "sk-db-wins"
    assert resolved.base_url == "https://embedding.example.com"
    assert resolved.model == "custom/model"


@pytest.mark.anyio
async def test_embedding_db_config_without_urls_returns_raw_none(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    await _save(db_session, "embedding", public_config={}, secret={"api_key": "sk-db"})

    resolved = await credentials.resolve("embedding")

    assert resolved is not None
    assert resolved.api_key == "sk-db"
    assert resolved.base_url is None
    assert resolved.model is None


@pytest.mark.anyio
async def test_embedding_env_fallback_when_db_missing(db_session: AsyncSession) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    credentials = IntegrationCredentials(factory, _settings(siliconflow_api_key="sk-env"))

    resolved = await credentials.resolve("embedding")

    assert resolved is not None
    assert resolved.api_key == "sk-env"
    assert resolved.base_url is None
    assert resolved.model is None


@pytest.mark.anyio
async def test_embedding_row_without_secret_falls_back_to_env(db_session: AsyncSession) -> None:
    db_session.add(Integration(provider="embedding", public_config={"base_url": "https://embedding.example.com"}))
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    credentials = IntegrationCredentials(factory, _settings(siliconflow_api_key="sk-env"))

    resolved = await credentials.resolve("embedding")

    assert resolved is not None
    assert resolved.api_key == "sk-env"


@pytest.mark.anyio
async def test_embedding_returns_none_when_neither_db_nor_env(credentials: IntegrationCredentials) -> None:
    assert await credentials.resolve("embedding") is None


@pytest.mark.anyio
async def test_embedding_corrupted_secret_raises_domain_error(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    db_session.add(Integration(provider="embedding", public_config={}, encrypted_secret="v1:corrupted"))
    await db_session.commit()

    with pytest.raises(IntegrationConfigurationError) as caught:
        await credentials.resolve("embedding")

    assert caught.value.code == "INTEGRATION_SECRET_INVALID"


@pytest.mark.anyio
async def test_embedding_repr_hides_api_key(db_session: AsyncSession, credentials: IntegrationCredentials) -> None:
    await _save(db_session, "embedding", public_config={}, secret={"api_key": "sk-db-secret"})

    resolved = await credentials.resolve("embedding")

    assert resolved is not None
    assert "sk-db-secret" not in repr(resolved)


# --- agent-llm ---


@pytest.mark.anyio
async def test_agent_llm_db_config_applies_defaults_and_strips_hint(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    await _save(
        db_session, "agent-llm", public_config={"base_url": "https://api.deepseek.com"}, secret={"api_key": "sk-db"}
    )

    resolved = await credentials.resolve("agent-llm")

    assert resolved is not None
    assert resolved.api_key == "sk-db"
    assert resolved.provider == DEFAULT_AGENT_LLM_PROVIDER
    assert resolved.model == DEFAULT_AGENT_LLM_MODEL
    assert resolved.base_url == "https://api.deepseek.com"


@pytest.mark.anyio
async def test_agent_llm_db_config_wins_over_env(db_session: AsyncSession) -> None:
    await _save(db_session, "agent-llm", public_config={"provider": "p", "model": "m"}, secret={"api_key": "sk-db"})
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    credentials = IntegrationCredentials(factory, _settings(agent_api_key="sk-env"))

    resolved = await credentials.resolve("agent-llm")

    assert resolved is not None
    assert resolved.api_key == "sk-db"


@pytest.mark.anyio
async def test_agent_llm_env_fallback_when_db_missing(db_session: AsyncSession) -> None:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    credentials = IntegrationCredentials(factory, _settings(agent_api_key="sk-env", agent_model="env-model"))

    resolved = await credentials.resolve("agent-llm")

    assert resolved is not None
    assert resolved.api_key == "sk-env"
    assert resolved.model == "env-model"


@pytest.mark.anyio
async def test_agent_llm_undecryptable_falls_back_to_env_with_error_log(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _save(db_session, "agent-llm", public_config={}, secret={"api_key": "sk-db"}, master_key=OTHER_MASTER_KEY)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    credentials = IntegrationCredentials(factory, _settings(agent_api_key="sk-env"))

    with caplog.at_level("ERROR", logger="reven.integrations.credentials"):
        resolved = await credentials.resolve("agent-llm")

    assert resolved is not None
    assert resolved.api_key == "sk-env"
    assert any("解密失败" in record.message for record in caplog.records)


@pytest.mark.anyio
async def test_agent_llm_returns_none_when_unconfigured(credentials: IntegrationCredentials) -> None:
    assert await credentials.resolve("agent-llm") is None


# --- translation ---


@pytest.mark.anyio
async def test_translations_ordered_by_priority_and_provider_tiebreak(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    await _save(
        db_session,
        "translate_aliyun",
        public_config={"priority": 1, "enabled": True},
        secret={"access_key_id": "aliyun-id-secret", "access_key_secret": "aliyun-key-secret"},
    )
    await _save(
        db_session,
        "translate_baidu",
        public_config={"priority": 1, "enabled": True},
        secret={"app_id": "baidu-id-secret", "app_key": "baidu-key-secret"},
    )

    configs = await credentials.translations()

    assert [config.provider for config in configs] == ["translate_baidu", "translate_aliyun"]
    assert isinstance(configs[0], BaiduTranslationConfig)
    assert isinstance(configs[1], AliyunTranslationConfig)
    rendered = repr(configs)
    assert "baidu-id-secret" not in rendered
    assert "baidu-key-secret" not in rendered
    assert "aliyun-id-secret" not in rendered
    assert "aliyun-key-secret" not in rendered


@pytest.mark.anyio
async def test_translations_lower_numeric_priority_wins(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    await _save(
        db_session,
        "translate_baidu",
        public_config={"priority": 2, "enabled": True},
        secret={"app_id": "baidu-id", "app_key": "baidu-key"},
    )
    await _save(
        db_session,
        "translate_aliyun",
        public_config={"priority": 1, "enabled": True},
        secret={"access_key_id": "aliyun-id", "access_key_secret": "aliyun-key"},
    )

    configs = await credentials.translations()

    assert [(config.provider, config.priority) for config in configs] == [
        ("translate_aliyun", 1),
        ("translate_baidu", 2),
    ]


@pytest.mark.anyio
async def test_translations_skips_disabled_incomplete_and_unsupported(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    await _save(
        db_session,
        "translate_baidu",
        public_config={"priority": 1, "enabled": False},
        secret={"app_id": "disabled-id", "app_key": "disabled-key"},
    )
    await _save(
        db_session,
        "translate_aliyun",
        public_config={"priority": 2, "enabled": True},
        secret={"access_key_id": "missing-key"},
    )
    db_session.add(
        Integration(
            provider="translate_tencent", public_config={"priority": 0, "enabled": True}, encrypted_secret="legacy"
        )
    )
    await db_session.commit()

    assert await credentials.translations() == ()


@pytest.mark.anyio
async def test_translations_corrupted_secret_skipped_without_leaking(
    db_session: AsyncSession,
    credentials: IntegrationCredentials,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db_session.add(
        Integration(
            provider="translate_baidu",
            public_config={"priority": 1, "enabled": True},
            encrypted_secret="v1:corrupted-secret-material",
        )
    )
    await db_session.commit()

    with caplog.at_level(logging.WARNING):
        assert await credentials.translations() == ()

    assert "provider=translate_baidu" in caplog.text
    assert "corrupted-secret-material" not in caplog.text


@pytest.mark.anyio
async def test_resolve_single_translation_provider(
    db_session: AsyncSession, credentials: IntegrationCredentials
) -> None:
    await _save(
        db_session,
        "translate_baidu",
        public_config={"priority": 3, "enabled": True},
        secret={"app_id": "baidu-id", "app_key": "baidu-key"},
    )

    resolved = await credentials.resolve("translate_baidu")

    assert resolved == BaiduTranslationConfig(3, "baidu-id", "baidu-key")


# --- seam 通用 ---


@pytest.mark.anyio
async def test_resolve_unknown_provider_raises(credentials: IntegrationCredentials) -> None:
    with pytest.raises(ValueError, match="未知集成 provider"):
        await credentials.resolve("unknown-provider")  # type: ignore[call-overload]


def test_constructor_rejects_invalid_master_key() -> None:
    invalid_key = base64.urlsafe_b64encode(b"short").decode()
    with pytest.raises(ValueError, match="32 字节"):
        IntegrationCredentials(async_sessionmaker(), _settings(reven_master_key=invalid_key))


def test_secret_box_property_exposes_single_instance() -> None:
    credentials = IntegrationCredentials(async_sessionmaker(), _settings())

    assert credentials.secret_box == _box()
