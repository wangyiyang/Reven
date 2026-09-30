"""Agent 配置解析：凭证由 IntegrationCredentials seam 提供，本模块只做 AgentConfig 映射。"""

from dataclasses import dataclass
from pathlib import Path

from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials


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
    credentials: IntegrationCredentials | None,
    settings: Settings,
) -> AgentConfig | None:
    """解析 Agent 配置：integrations 表优先，env/Settings fallback；未配置返回 None。

    credentials 为 None（无库或 seam 构造失败降级）时只走 env fallback；
    读取/解密失败由 IntegrationCredentials 记日志并降级，绝不抛出——
    Agent 不可用不应阻止应用启动（已拍板降级策略）。
    """
    if credentials is None:
        return AgentConfig.from_settings(settings)
    resolved = await credentials.agent_llm()
    if resolved is None:
        return None
    return AgentConfig(
        provider=resolved.provider,
        model=resolved.model,
        base_url=resolved.base_url,
        api_key=resolved.api_key,
        dsh_home=settings.dsh_home,
        cwd=settings.dsh_home,
    )


async def resolve_agent_model_config(
    credentials: IntegrationCredentials,
    settings: Settings,
    model_ref: str,
) -> AgentConfig | None:
    """按模型引用（provider/model）解析运行时配置；未注册/未启用返回 None。

    每次调用现读注册表（配置页改动即时生效）；读取/解密失败由 seam 内部降级。
    返回 None 时调用方必须明确报错，禁止静默回落默认模型（OpenClaw 严格语义）。
    """
    entries = await credentials.agent_llm_models()
    for entry in entries or ():
        if entry.ref == model_ref:
            return AgentConfig(
                provider=entry.provider,
                model=entry.model,
                base_url=entry.base_url,
                api_key=entry.api_key,
                dsh_home=settings.dsh_home,
                cwd=settings.dsh_home,
            )
    return None
