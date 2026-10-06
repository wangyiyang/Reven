"""模型配置只由既有凭据 seam 解析，不保存密钥到运行快照。"""

from dataclasses import dataclass, field

from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials


@dataclass(frozen=True, slots=True)
class AgentConfig:
    provider: str
    model: str
    base_url: str | None
    api_key: str | None = field(repr=False)

    @classmethod
    def from_settings(cls, settings: Settings) -> "AgentConfig | None":
        if settings.agent_api_key is None:
            return None
        return cls(
            settings.agent_provider,
            settings.agent_model,
            settings.agent_base_url,
            settings.agent_api_key.get_secret_value(),
        )


async def resolve_agent_config(credentials: IntegrationCredentials | None, settings: Settings) -> AgentConfig | None:
    if credentials is None:
        return AgentConfig.from_settings(settings)
    resolved = await credentials.agent_llm()
    if resolved is None:
        return None
    return AgentConfig(resolved.provider, resolved.model, resolved.base_url, resolved.api_key)


async def resolve_agent_model_config(
    credentials: IntegrationCredentials, settings: Settings, model_ref: str
) -> AgentConfig | None:
    del settings
    entries = await credentials.agent_llm_models()
    for entry in entries or ():
        if entry.ref == model_ref:
            return AgentConfig(entry.provider, entry.model, entry.base_url, entry.api_key)
    return None
