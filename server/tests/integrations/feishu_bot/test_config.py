"""feishu_bot 共享配置加载器：缺行/禁用/密文损坏/字段缺失均返回 None，日志不泄露凭证。"""

import base64
import logging

import pytest
from reven.integrations.feishu_bot.config import FeishuBotConfig, load_feishu_bot_config
from reven.integrations.models import Integration
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"m" * 32).decode()
BOT_SECRET = {"app_id": "cli_test", "app_secret": "s3cret-bot-value"}


def _factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(session.bind, expire_on_commit=False)


def _secret_box() -> SecretBox:
    return SecretBox.from_base64(TEST_MASTER_KEY)


async def _write_config(
    session: AsyncSession,
    *,
    enabled: bool = True,
    whitelist: object = ["ou_boss"],
    secret: dict[str, str] | None = BOT_SECRET,
) -> Integration:
    integration = Integration(
        provider="feishu_bot",
        public_config={"whitelist_open_ids": whitelist, "enabled": enabled},
        encrypted_secret=_secret_box().encrypt(secret) if secret is not None else None,
    )
    session.add(integration)
    await session.commit()
    return integration


@pytest.mark.anyio
async def test_missing_row_returns_none(db_session: AsyncSession) -> None:
    assert await load_feishu_bot_config(_factory(db_session), _secret_box()) is None


@pytest.mark.anyio
async def test_disabled_config_returns_none(db_session: AsyncSession) -> None:
    await _write_config(db_session, enabled=False)

    assert await load_feishu_bot_config(_factory(db_session), _secret_box()) is None


@pytest.mark.anyio
async def test_missing_secret_returns_none(db_session: AsyncSession) -> None:
    await _write_config(db_session, secret=None)

    assert await load_feishu_bot_config(_factory(db_session), _secret_box()) is None


@pytest.mark.anyio
async def test_incomplete_secret_returns_none(db_session: AsyncSession) -> None:
    await _write_config(db_session, secret={"app_id": "cli_test"})

    assert await load_feishu_bot_config(_factory(db_session), _secret_box()) is None


@pytest.mark.anyio
async def test_undecryptable_secret_returns_none_without_leaking(
    db_session: AsyncSession,
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
        assert await load_feishu_bot_config(_factory(db_session), _secret_box()) is None

    assert any("feishu_bot" in record.getMessage() for record in caplog.records)
    assert "s3cret-bot-value" not in caplog.text
    assert "not-a-valid-ciphertext" not in caplog.text


@pytest.mark.anyio
async def test_enabled_config_returns_credentials_and_whitelist(db_session: AsyncSession) -> None:
    await _write_config(db_session, whitelist=["ou_boss", "ou_backup"])

    config = await load_feishu_bot_config(_factory(db_session), _secret_box())

    assert config == FeishuBotConfig(
        app_id="cli_test",
        app_secret="s3cret-bot-value",
        whitelist_open_ids=("ou_boss", "ou_backup"),
    )


@pytest.mark.anyio
async def test_malformed_whitelist_is_filtered(db_session: AsyncSession) -> None:
    await _write_config(db_session, whitelist=["ou_boss", "", "   ", "ou_boss", 42, None])

    config = await load_feishu_bot_config(_factory(db_session), _secret_box())

    assert config is not None
    assert config.whitelist_open_ids == ("ou_boss",)


@pytest.mark.anyio
async def test_non_list_whitelist_yields_empty(db_session: AsyncSession) -> None:
    await _write_config(db_session, whitelist="ou_boss")

    config = await load_feishu_bot_config(_factory(db_session), _secret_box())

    assert config is not None
    assert config.whitelist_open_ids == ()


def test_config_repr_hides_credentials() -> None:
    config = FeishuBotConfig(app_id="cli_test", app_secret="s3cret-bot-value", whitelist_open_ids=("ou_boss",))

    text = repr(config)
    assert "s3cret-bot-value" not in text
    assert "cli_test" not in text
