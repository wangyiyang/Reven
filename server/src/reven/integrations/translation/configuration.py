"""Load enabled Baidu/Aliyun translation credentials from integration settings."""

import logging
from dataclasses import dataclass, field
from typing import ClassVar, Literal, TypeGuard

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import get_settings
from reven.integrations.providers import TRANSLATION_PROVIDERS
from reven.integrations.repository import IntegrationRepository
from reven.integrations.service import public_config_without_hint
from reven.security.secrets import SecretBox, SecretBoxError

logger = logging.getLogger(__name__)

_PROVIDER_ORDER = {provider: index for index, provider in enumerate(TRANSLATION_PROVIDERS)}


@dataclass(frozen=True)
class BaiduTranslationConfig:
    priority: int
    app_id: str = field(repr=False)
    app_key: str = field(repr=False)
    provider: ClassVar[Literal["translate_baidu"]] = "translate_baidu"


@dataclass(frozen=True)
class AliyunTranslationConfig:
    priority: int
    access_key_id: str = field(repr=False)
    access_key_secret: str = field(repr=False)
    provider: ClassVar[Literal["translate_aliyun"]] = "translate_aliyun"


type TranslationConfig = BaiduTranslationConfig | AliyunTranslationConfig


async def load_translation_configs(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[TranslationConfig, ...]:
    """Return usable providers ordered by priority and a stable provider tie-break."""
    async with session_factory() as session:
        integrations = await IntegrationRepository(session).list_all()

    secret_box = SecretBox.from_base64(get_settings().reven_master_key.get_secret_value())
    configs: list[TranslationConfig] = []
    for integration in integrations:
        if integration.provider not in TRANSLATION_PROVIDERS:
            continue
        public_config = public_config_without_hint(integration)
        priority = public_config.get("priority")
        enabled = public_config.get("enabled")
        if enabled is not True or not isinstance(priority, int) or isinstance(priority, bool):
            continue
        if not 1 <= priority <= 99:
            continue
        if integration.encrypted_secret is None:
            continue
        try:
            secret = secret_box.decrypt(integration.encrypted_secret)
        except SecretBoxError:
            logger.warning("跳过机翻配置（provider=%s, error_type=SecretBoxError）", integration.provider)
            continue
        config = _config_from_secret(integration.provider, priority, secret)
        if config is None:
            logger.warning("跳过机翻配置（provider=%s, error_type=IncompleteSecret）", integration.provider)
            continue
        configs.append(config)
    return tuple(sorted(configs, key=lambda item: (item.priority, _PROVIDER_ORDER[item.provider])))


def _config_from_secret(provider: str, priority: int, secret: dict[str, str]) -> TranslationConfig | None:
    if provider == "translate_baidu":
        app_id = secret.get("app_id")
        app_key = secret.get("app_key")
        if _present(app_id) and _present(app_key):
            return BaiduTranslationConfig(priority, app_id, app_key)
        return None
    if provider == "translate_aliyun":
        access_key_id = secret.get("access_key_id")
        access_key_secret = secret.get("access_key_secret")
        if _present(access_key_id) and _present(access_key_secret):
            return AliyunTranslationConfig(priority, access_key_id, access_key_secret)
    return None


def _present(value: str | None) -> TypeGuard[str]:
    return value is not None and bool(value.strip())
