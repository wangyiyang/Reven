"""Runtime loading of enabled, complete Baidu/Aliyun translation settings."""

import base64
from collections.abc import Iterator

import pytest
from reven.config import get_settings
from reven.integrations.models import Integration
from reven.integrations.translation.configuration import (
    AliyunTranslationConfig,
    BaiduTranslationConfig,
    load_translation_configs,
)
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"m" * 32).decode()


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://reven:reven@localhost/reven")
    monkeypatch.setenv("REVEN_MASTER_KEY", TEST_MASTER_KEY)
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(session.bind, expire_on_commit=False)


def _secret_box() -> SecretBox:
    return SecretBox.from_base64(TEST_MASTER_KEY)


@pytest.mark.anyio
async def test_loads_enabled_complete_configs_in_priority_and_provider_order(
    db_session: AsyncSession,
    settings_env: None,
) -> None:
    db_session.add_all(
        [
            Integration(
                provider="translate_aliyun",
                public_config={"priority": 1, "enabled": True},
                encrypted_secret=_secret_box().encrypt(
                    {"access_key_id": "aliyun-id-secret", "access_key_secret": "aliyun-key-secret"}
                ),
            ),
            Integration(
                provider="translate_baidu",
                public_config={"priority": 1, "enabled": True},
                encrypted_secret=_secret_box().encrypt({"app_id": "baidu-id-secret", "app_key": "baidu-key-secret"}),
            ),
        ]
    )
    await db_session.commit()

    configs = await load_translation_configs(_factory(db_session))

    assert [config.provider for config in configs] == ["translate_baidu", "translate_aliyun"]
    assert isinstance(configs[0], BaiduTranslationConfig)
    assert isinstance(configs[1], AliyunTranslationConfig)
    rendered = repr(configs)
    assert "baidu-id-secret" not in rendered
    assert "baidu-key-secret" not in rendered
    assert "aliyun-id-secret" not in rendered
    assert "aliyun-key-secret" not in rendered


@pytest.mark.anyio
async def test_lower_numeric_priority_wins_before_provider_tiebreak(
    db_session: AsyncSession,
    settings_env: None,
) -> None:
    db_session.add_all(
        [
            Integration(
                provider="translate_baidu",
                public_config={"priority": 2, "enabled": True},
                encrypted_secret=_secret_box().encrypt({"app_id": "baidu-id", "app_key": "baidu-key"}),
            ),
            Integration(
                provider="translate_aliyun",
                public_config={"priority": 1, "enabled": True},
                encrypted_secret=_secret_box().encrypt(
                    {"access_key_id": "aliyun-id", "access_key_secret": "aliyun-key"}
                ),
            ),
        ]
    )
    await db_session.commit()

    configs = await load_translation_configs(_factory(db_session))

    assert [(config.provider, config.priority) for config in configs] == [
        ("translate_aliyun", 1),
        ("translate_baidu", 2),
    ]


@pytest.mark.anyio
async def test_skips_disabled_incomplete_and_unsupported_configs(
    db_session: AsyncSession,
    settings_env: None,
) -> None:
    db_session.add_all(
        [
            Integration(
                provider="translate_baidu",
                public_config={"priority": 1, "enabled": False},
                encrypted_secret=_secret_box().encrypt({"app_id": "disabled-id", "app_key": "disabled-key"}),
            ),
            Integration(
                provider="translate_aliyun",
                public_config={"priority": 2, "enabled": True},
                encrypted_secret=_secret_box().encrypt({"access_key_id": "missing-key"}),
            ),
            Integration(
                provider="translate_tencent",
                public_config={"priority": 0, "enabled": True},
                encrypted_secret="legacy-ciphertext",
            ),
        ]
    )
    await db_session.commit()

    assert await load_translation_configs(_factory(db_session)) == ()


@pytest.mark.anyio
async def test_corrupted_secret_is_skipped_without_logging_secret(
    db_session: AsyncSession,
    settings_env: None,
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

    assert await load_translation_configs(_factory(db_session)) == ()
    assert "provider=translate_baidu" in caplog.text
    assert "corrupted-secret-material" not in caplog.text
