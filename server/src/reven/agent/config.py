"""Agent 配置解析：凭证由 IntegrationCredentials seam 提供，本模块只做 AgentConfig 映射。"""

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials

logger = logging.getLogger(__name__)


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

    读取/解密失败由 IntegrationCredentials 记日志并降级，绝不抛出——
    Agent 不可用不应阻止应用启动（已拍板降级策略）。
    """
    if session_factory is None:
        return AgentConfig.from_settings(settings)
    try:
        credentials = await IntegrationCredentials(session_factory, settings).agent_llm()
    except Exception as exc:
        # seam 构造即失败（如 master key 非法）：记日志后回退 env，绝不抛出
        logger.error("agent-llm 凭证解析失败（error_type=%s），回退 env 配置", type(exc).__name__)
        return AgentConfig.from_settings(settings)
    if credentials is None:
        return None
    return AgentConfig(
        provider=credentials.provider,
        model=credentials.model,
        base_url=credentials.base_url,
        api_key=credentials.api_key,
        dsh_home=settings.dsh_home,
        cwd=settings.dsh_home,
    )
