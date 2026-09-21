"""Business logic for integration settings: secret lifecycle and connection tests.

Secrets are write/replace/delete only — this module never exposes plaintext
through its return values; decryption happens solely to hand credentials to
registered connection-test adapters inside the backend process.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from reven.integrations.models import Integration
from reven.integrations.repository import IntegrationRepository
from reven.scheduling import utc_now
from reven.security.redaction import redact
from reven.security.secrets import SecretBox, SecretBoxError

STATUS_UNTESTED = "未测试"
STATUS_OK = "连接正常"
STATUS_FAILED = "连接失败"

HINT_KEY = "_secret_hint"
MAX_ERROR_LENGTH = 500

SECRET_HINT_FIELDS = {
    "feishu": "webhook_url",
    "feishu_bot": "app_secret",
    "translate_baidu": "app_key",
    "translate_aliyun": "access_key_secret",
    "embedding": "api_key",
    "agent-llm": "api_key",
}


class IntegrationError(Exception):
    """Domain error carrying a stable code for API responses."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ConnectionTestResult:
    success: bool
    message: str | None = None
    latency_ms: int | None = None


ConnectionTestAdapter = Callable[
    [dict[str, object], dict[str, str] | None],
    Awaitable[ConnectionTestResult],
]

_CONNECTION_TEST_ADAPTERS: dict[str, ConnectionTestAdapter] = {}


def register_connection_test_adapter(provider: str, adapter: ConnectionTestAdapter) -> None:
    _CONNECTION_TEST_ADAPTERS[provider] = adapter


def unregister_connection_test_adapter(provider: str) -> None:
    _CONNECTION_TEST_ADAPTERS.pop(provider, None)


def compute_secret_hint(provider: str, secret: dict[str, str]) -> str:
    value = secret[SECRET_HINT_FIELDS[provider]]
    # 短 Secret 不附加末 4 位，避免 hint 暴露完整明文
    suffix = value[-4:] if len(value) > 4 else ""
    return f"已配置 · ****{suffix}"


def public_config_without_hint(integration: Integration) -> dict[str, object]:
    return {key: value for key, value in integration.public_config.items() if key != HINT_KEY}


def secret_hint_of(integration: Integration) -> str | None:
    if integration.encrypted_secret is None:
        return None
    hint = integration.public_config.get(HINT_KEY)
    return str(hint) if hint is not None else None


class IntegrationService:
    def __init__(self, session: AsyncSession, secret_box: SecretBox) -> None:
        self.repository = IntegrationRepository(session)
        self.secret_box = secret_box

    async def list_integrations(self) -> list[Integration]:
        return await self.repository.list_all()

    async def get_integration(self, provider: str) -> Integration:
        integration = await self.repository.get_by_provider(provider)
        if integration is None:
            raise IntegrationError(
                status_code=404,
                code="INTEGRATION_NOT_FOUND",
                message=f"集成 {provider} 尚未配置",
            )
        return integration

    async def upsert_integration(
        self,
        *,
        provider: str,
        public_config: dict[str, object],
        secret: dict[str, str] | None,
    ) -> Integration:
        """Create or replace an integration; ``secret=None`` keeps the current ciphertext."""
        integration = await self.repository.get_by_provider(provider)
        stored_config = dict(public_config)
        encrypted_secret: str | None
        if secret is not None:
            encrypted_secret = self.secret_box.encrypt(secret)
            stored_config[HINT_KEY] = compute_secret_hint(provider, secret)
        elif integration is not None:
            encrypted_secret = integration.encrypted_secret
            hint = secret_hint_of(integration)
            if hint is not None:
                stored_config[HINT_KEY] = hint
        else:
            encrypted_secret = None

        if integration is None:
            integration = Integration(provider=provider)
        integration.public_config = stored_config
        integration.encrypted_secret = encrypted_secret
        integration.connection_status = STATUS_UNTESTED
        integration.last_tested_at = None
        integration.last_error = None
        integration.last_latency_ms = None
        return await self.repository.save(integration)

    async def delete_secret(self, provider: str) -> Integration:
        integration = await self.get_integration(provider)
        if integration.encrypted_secret is None:
            raise IntegrationError(
                status_code=404,
                code="INTEGRATION_SECRET_NOT_CONFIGURED",
                message=f"集成 {provider} 尚未配置 Secret",
            )
        integration.encrypted_secret = None
        integration.public_config = public_config_without_hint(integration)
        integration.connection_status = STATUS_UNTESTED
        integration.last_tested_at = None
        integration.last_error = None
        integration.last_latency_ms = None
        return await self.repository.save(integration)

    async def run_connection_test(self, provider: str) -> Integration:
        integration = await self.get_integration(provider)
        adapter = _CONNECTION_TEST_ADAPTERS.get(provider)
        if adapter is None:
            raise IntegrationError(
                status_code=503,
                code="CONNECTION_TEST_UNAVAILABLE",
                message=f"集成 {provider} 的连接测试尚未接入",
            )
        try:
            secrets = (
                self.secret_box.decrypt(integration.encrypted_secret)
                if integration.encrypted_secret is not None
                else None
            )
        except SecretBoxError as exc:
            raise IntegrationError(
                status_code=500,
                code="INTEGRATION_SECRET_INVALID",
                message=f"集成 {provider} 的 Secret 密文无法解密，请重新配置",
            ) from exc
        try:
            result = await adapter(public_config_without_hint(integration), secrets)
        except Exception as exc:  # adapter failures must surface as a redacted result
            result = ConnectionTestResult(success=False, message=str(exc))

        integration.last_tested_at = utc_now()
        integration.last_latency_ms = result.latency_ms
        if result.success:
            integration.connection_status = STATUS_OK
            integration.last_error = None
        else:
            integration.connection_status = STATUS_FAILED
            known_secrets = list(secrets.values()) if secrets else []
            message = redact(result.message or "连接测试失败", known_secrets)
            integration.last_error = message[:MAX_ERROR_LENGTH]
        return await self.repository.save(integration)
