"""Shared, API-independent loading of persisted Notion configuration."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.config import get_settings
from reven.integrations.repository import IntegrationRepository
from reven.integrations.service import public_config_without_hint
from reven.security.secrets import SecretBox, SecretBoxError


class IntegrationConfigurationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def load_notion_config(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[str, str]:
    async with session_factory() as session:
        integration = await IntegrationRepository(session).get_by_provider("notion")
    if integration is None or integration.encrypted_secret is None:
        raise IntegrationConfigurationError("NOTION_SECRET_NOT_CONFIGURED")
    data_source_id = public_config_without_hint(integration).get("data_source_id")
    if not isinstance(data_source_id, str) or not data_source_id:
        raise IntegrationConfigurationError("NOTION_DATA_SOURCE_MISSING")
    try:
        secrets = SecretBox.from_base64(get_settings().reven_master_key.get_secret_value()).decrypt(
            integration.encrypted_secret
        )
    except SecretBoxError as exc:
        raise IntegrationConfigurationError("INTEGRATION_SECRET_INVALID") from exc
    token = secrets.get("token")
    if not token:
        raise IntegrationConfigurationError("NOTION_SECRET_NOT_CONFIGURED")
    return token, data_source_id
