"""Embedding 服务配置加载：优先读集成设置入库的凭证，回退环境变量。"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import get_settings
from reven.integrations.notion.configuration import IntegrationConfigurationError
from reven.integrations.repository import IntegrationRepository
from reven.integrations.service import public_config_without_hint
from reven.rss.embedding import BGE_M3_MODEL
from reven.security.secrets import SecretBox, SecretBoxError

DEFAULT_EMBEDDING_BASE_URL = "https://api.siliconflow.cn"


@dataclass(frozen=True)
class EmbeddingConfig:
    base_url: str
    model: str
    api_key: str


async def load_embedding_config(
    session_factory: async_sessionmaker[AsyncSession],
) -> EmbeddingConfig | None:
    """DB 中 provider="embedding" 的集成优先；缺省时回退 SILICONFLOW_API_KEY 环境变量。"""
    async with session_factory() as session:
        integration = await IntegrationRepository(session).get_by_provider("embedding")
    if integration is not None and integration.encrypted_secret is not None:
        public_config = public_config_without_hint(integration)
        base_url = public_config.get("base_url")
        model = public_config.get("model")
        try:
            secrets = SecretBox.from_base64(get_settings().reven_master_key.get_secret_value()).decrypt(
                integration.encrypted_secret
            )
        except SecretBoxError as exc:
            raise IntegrationConfigurationError("INTEGRATION_SECRET_INVALID") from exc
        api_key = secrets.get("api_key")
        if not api_key:
            raise IntegrationConfigurationError("INTEGRATION_SECRET_INVALID")
        return EmbeddingConfig(
            base_url=base_url if isinstance(base_url, str) and base_url else DEFAULT_EMBEDDING_BASE_URL,
            model=model if isinstance(model, str) and model else BGE_M3_MODEL,
            api_key=api_key,
        )
    settings = get_settings()
    if settings.siliconflow_api_key is None:
        return None
    return EmbeddingConfig(
        base_url=DEFAULT_EMBEDDING_BASE_URL,
        model=BGE_M3_MODEL,
        api_key=settings.siliconflow_api_key.get_secret_value(),
    )
