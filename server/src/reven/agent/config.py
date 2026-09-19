"""Agent 配置解析：优先读 integrations 表的 agent-llm，env/Settings 作为 fallback。"""

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import Settings
from reven.integrations.repository import IntegrationRepository
from reven.integrations.service import public_config_without_hint
from reven.security.secrets import SecretBox, SecretBoxError

logger = logging.getLogger(__name__)

AGENT_LLM_PROVIDER = "agent-llm"
DEFAULT_PROVIDER = "deepseek-official"
DEFAULT_MODEL = "deepseek-v4-flash"


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """dsh 嵌入式运行时的启动参数。

    api_key 为 None 表示未携带凭证（仅用于无 key 拉起握手等场景）。
    """

    provider: str
    model: str
    base_url: str | None
    api_key: str | None
    dsh_home: Path
    cwd: Path
    patches: tuple[str, ...] = ()

    @classmethod
    def from_settings(cls, settings: Settings) -> "AgentConfig | None":
        """从应用 Settings 构建配置；未配置 API Key 时返回 None（优雅降级）。"""
        if settings.agent_api_key is None:
            return None
        return cls(
            provider=settings.agent_provider,
            model=settings.agent_model,
            base_url=settings.agent_base_url,
            api_key=settings.agent_api_key.get_secret_value(),
            dsh_home=settings.dsh_home,
            cwd=settings.dsh_home,
        )


async def resolve_agent_config(
    session_factory: async_sessionmaker[AsyncSession] | None,
    settings: Settings,
) -> AgentConfig | None:
    """解析 Agent 配置：integrations 表优先，env/Settings fallback；未配置返回 None。

    任何读取/解密失败都只记日志并继续 fallback，绝不在 lifespan 阶段抛出——
    Agent 不可用不应阻止应用启动（已拍板降级策略）。
    """
    if session_factory is not None:
        config = await _config_from_integration(session_factory, settings)
        if config is not None:
            return config
    return AgentConfig.from_settings(settings)


async def _config_from_integration(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> AgentConfig | None:
    try:
        async with session_factory() as session:
            integration = await IntegrationRepository(session).get_by_provider(AGENT_LLM_PROVIDER)
        if integration is None or integration.encrypted_secret is None:
            return None
        secrets = SecretBox.from_base64(settings.reven_master_key.get_secret_value()).decrypt(
            integration.encrypted_secret
        )
    except SecretBoxError:
        logger.error("agent-llm 集成 Secret 解密失败，请重新配置；Agent 按未配置降级")
        return None
    except Exception as exc:
        logger.error("agent-llm 集成配置读取失败（error_type=%s），回退 env 配置", type(exc).__name__)
        return None
    api_key = secrets.get("api_key")
    if not api_key:
        return None
    public = public_config_without_hint(integration)
    base_url = public.get("base_url")
    return AgentConfig(
        provider=_str_or(public.get("provider"), DEFAULT_PROVIDER),
        model=_str_or(public.get("model"), DEFAULT_MODEL),
        base_url=base_url if isinstance(base_url, str) else None,
        api_key=api_key,
        dsh_home=settings.dsh_home,
        cwd=settings.dsh_home,
    )


def _str_or(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default
