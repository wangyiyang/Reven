"""集成凭证 seam：全仓唯一 SecretBox 构造点，统一行读取、hint 剥离、env 兜底与解密降级。

调用方拿到 per-provider typed credentials；未配置/禁用/凭证不完整返回 None。
读取/解密失败只记 provider + error_type 日志并降级，绝不让意外异常冲出调用路径。
唯一例外：embedding 密文损坏维持 INTEGRATION_SECRET_INVALID 领域错误（错误码红线，
见 integration-provider-contract）。

tencent_cos 不在本 seam 内：它是纯 env/Settings 同步校验（无 integrations 行、无密文、
无 hint），见 tencent_cos/configuration.py。
"""

import logging
from dataclasses import dataclass, field
from typing import Literal, TypeGuard, overload

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import Settings
from reven.db import session_scope
from reven.integrations.errors import IntegrationConfigurationError
from reven.integrations.feishu_bot.config import PROVIDER as FEISHU_BOT_PROVIDER
from reven.integrations.feishu_bot.config import FeishuBotConfig, parse_whitelist
from reven.integrations.models import Integration
from reven.integrations.providers import TRANSLATION_PROVIDERS, TranslationProvider
from reven.integrations.repository import IntegrationRepository
from reven.integrations.service import public_config_without_hint
from reven.integrations.translation.configuration import (
    AliyunTranslationConfig,
    BaiduTranslationConfig,
    TranslationConfig,
)
from reven.security.secrets import SecretBox, SecretBoxError

logger = logging.getLogger(__name__)

AGENT_LLM_PROVIDER = "agent-llm"
DEFAULT_AGENT_LLM_PROVIDER = "deepseek-official"
DEFAULT_AGENT_LLM_MODEL = "deepseek-v4-flash"

_TRANSLATION_PROVIDER_ORDER = {provider: index for index, provider in enumerate(TRANSLATION_PROVIDERS)}


@dataclass(frozen=True)
class EmbeddingCredentials:
    """embedding 原始凭证；base_url/model 为 None 时由调用方套各自默认值。"""

    api_key: str = field(repr=False)
    base_url: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class AgentLlmCredentials:
    """agent-llm 凭证；DB 路径已套默认值，env 路径按 Settings 原样携带。"""

    api_key: str = field(repr=False)
    provider: str
    model: str
    base_url: str | None


class IntegrationCredentials:
    """凭证解析 seam：session_factory + Settings 进，typed credentials 出。

    构造即完成全仓唯一的 SecretBox.from_base64；master key 非法时构造抛 ValueError，
    与现状一致：装配点（supervisor）捕获降级，路由/任务路径显式失败。
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._secret_box = SecretBox.from_base64(settings.reven_master_key.get_secret_value())

    @property
    def secret_box(self) -> SecretBox:
        """IntegrationService 写路径（加密/连接测试解密）复用同一实例。"""
        return self._secret_box

    @overload
    async def resolve(self, provider: Literal["feishu_bot"]) -> FeishuBotConfig | None: ...

    @overload
    async def resolve(self, provider: Literal["embedding"]) -> EmbeddingCredentials | None: ...

    @overload
    async def resolve(self, provider: Literal["agent-llm"]) -> AgentLlmCredentials | None: ...

    @overload
    async def resolve(self, provider: TranslationProvider) -> TranslationConfig | None: ...

    async def resolve(
        self, provider: str
    ) -> FeishuBotConfig | EmbeddingCredentials | AgentLlmCredentials | TranslationConfig | None:
        """按 provider 返回 typed credentials；不可用返回 None（embedding 密文损坏除外）。"""
        if provider == FEISHU_BOT_PROVIDER:
            return await self.feishu_bot()
        if provider == "embedding":
            return await self.embedding()
        if provider == AGENT_LLM_PROVIDER:
            return await self.agent_llm()
        if provider in TRANSLATION_PROVIDERS:
            return await self._translation(provider)
        raise ValueError(f"未知集成 provider：{provider}")

    async def feishu_bot(self) -> FeishuBotConfig | None:
        """feishu_bot 有效配置；未配置/禁用/凭证不完整/读取或解密失败均返回 None。"""
        try:
            async with session_scope(self._session_factory) as session:
                integration = await IntegrationRepository(session).get_by_provider(FEISHU_BOT_PROVIDER)
            if integration is None or integration.public_config.get("enabled") is not True:
                return None
            if integration.encrypted_secret is None:
                return None
            secret = self._secret_box.decrypt(integration.encrypted_secret)
        except Exception as exc:
            # 脱敏：只记 provider + 异常类型，不带配置/密文内容
            logger.warning(
                "飞书机器人配置读取失败（provider=%s, error_type=%s）", FEISHU_BOT_PROVIDER, type(exc).__name__
            )
            return None
        app_id = secret.get("app_id")
        app_secret = secret.get("app_secret")
        if not app_id or not app_secret:
            return None
        return FeishuBotConfig(
            app_id=app_id,
            app_secret=app_secret,
            whitelist_open_ids=parse_whitelist(integration.public_config.get("whitelist_open_ids")),
        )

    async def embedding(self) -> EmbeddingCredentials | None:
        """embedding 凭证：DB 优先、env（SILICONFLOW_API_KEY）兜底；密文损坏抛领域错误。"""
        async with session_scope(self._session_factory) as session:
            integration = await IntegrationRepository(session).get_by_provider("embedding")
        if integration is not None and integration.encrypted_secret is not None:
            try:
                secrets = self._secret_box.decrypt(integration.encrypted_secret)
            except SecretBoxError as exc:
                raise IntegrationConfigurationError("INTEGRATION_SECRET_INVALID") from exc
            api_key = secrets.get("api_key")
            if not api_key:
                raise IntegrationConfigurationError("INTEGRATION_SECRET_INVALID")
            public_config = public_config_without_hint(integration)
            return EmbeddingCredentials(
                api_key=api_key,
                base_url=_nonempty_str(public_config.get("base_url")),
                model=_nonempty_str(public_config.get("model")),
            )
        return self._embedding_from_env()

    async def agent_llm(self) -> AgentLlmCredentials | None:
        """agent-llm 凭证：integrations 表优先、env 兜底；读取/解密失败记日志后走 env。"""
        try:
            async with session_scope(self._session_factory) as session:
                integration = await IntegrationRepository(session).get_by_provider(AGENT_LLM_PROVIDER)
            if integration is None or integration.encrypted_secret is None:
                return self._agent_llm_from_env()
            secrets = self._secret_box.decrypt(integration.encrypted_secret)
        except SecretBoxError:
            logger.error("agent-llm 集成 Secret 解密失败，请重新配置；Agent 按未配置降级")
            return self._agent_llm_from_env()
        except Exception as exc:
            logger.error("agent-llm 集成配置读取失败（error_type=%s），回退 env 配置", type(exc).__name__)
            return self._agent_llm_from_env()
        api_key = secrets.get("api_key")
        if not api_key:
            return self._agent_llm_from_env()
        public_config = public_config_without_hint(integration)
        base_url = public_config.get("base_url")
        return AgentLlmCredentials(
            api_key=api_key,
            provider=_nonempty_str(public_config.get("provider")) or DEFAULT_AGENT_LLM_PROVIDER,
            model=_nonempty_str(public_config.get("model")) or DEFAULT_AGENT_LLM_MODEL,
            base_url=base_url if isinstance(base_url, str) else None,
        )

    async def translations(self) -> tuple[TranslationConfig, ...]:
        """全部可用机翻凭证：priority 数值升序，同优先级按 TRANSLATION_PROVIDERS 声明次序。"""
        async with session_scope(self._session_factory) as session:
            integrations = await IntegrationRepository(session).list_all()
        configs = [
            config
            for integration in integrations
            if integration.provider in TRANSLATION_PROVIDERS
            if (config := self._translation_from_integration(integration)) is not None
        ]
        return tuple(sorted(configs, key=lambda item: (item.priority, _TRANSLATION_PROVIDER_ORDER[item.provider])))

    async def _translation(self, provider: str) -> TranslationConfig | None:
        async with session_scope(self._session_factory) as session:
            integration = await IntegrationRepository(session).get_by_provider(provider)
        if integration is None:
            return None
        return self._translation_from_integration(integration)

    def _translation_from_integration(self, integration: Integration) -> TranslationConfig | None:
        public_config = public_config_without_hint(integration)
        priority = public_config.get("priority")
        enabled = public_config.get("enabled")
        if enabled is not True or not isinstance(priority, int) or isinstance(priority, bool):
            return None
        if not 1 <= priority <= 99:
            return None
        if integration.encrypted_secret is None:
            return None
        try:
            secret = self._secret_box.decrypt(integration.encrypted_secret)
        except SecretBoxError:
            logger.warning("跳过机翻配置（provider=%s, error_type=SecretBoxError）", integration.provider)
            return None
        config = _translation_config_from_secret(integration.provider, priority, secret)
        if config is None:
            logger.warning("跳过机翻配置（provider=%s, error_type=IncompleteSecret）", integration.provider)
        return config

    def _embedding_from_env(self) -> EmbeddingCredentials | None:
        api_key = self._settings.siliconflow_api_key
        if api_key is None:
            return None
        return EmbeddingCredentials(api_key=api_key.get_secret_value())

    def _agent_llm_from_env(self) -> AgentLlmCredentials | None:
        api_key = self._settings.agent_api_key
        if api_key is None:
            return None
        return AgentLlmCredentials(
            api_key=api_key.get_secret_value(),
            provider=self._settings.agent_provider,
            model=self._settings.agent_model,
            base_url=self._settings.agent_base_url,
        )


def _translation_config_from_secret(provider: str, priority: int, secret: dict[str, str]) -> TranslationConfig | None:
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


def _nonempty_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
