"""Embedding 服务配置加载：凭证由 IntegrationCredentials seam 提供，本模块套默认值。"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import get_settings
from reven.integrations.credentials import IntegrationCredentials
from reven.rss.embedding import BGE_M3_MODEL

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
    credentials = await IntegrationCredentials(session_factory, get_settings()).embedding()
    if credentials is None:
        return None
    return EmbeddingConfig(
        base_url=credentials.base_url or DEFAULT_EMBEDDING_BASE_URL,
        model=credentials.model or BGE_M3_MODEL,
        api_key=credentials.api_key,
    )
