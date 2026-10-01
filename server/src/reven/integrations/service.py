"""Business logic for integration settings: secret lifecycle and connection tests.

Secrets are write/replace/delete only — this module never exposes plaintext
through its return values; decryption happens solely to hand credentials to
connection-test adapters inside the backend process.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import NotRequired, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from reven.integrations.models import Integration
from reven.integrations.providers import (
    AGENT_LLM_PROVIDER,
    DEFAULT_AGENT_LLM_MODEL,
    DEFAULT_AGENT_LLM_PROVIDER,
    model_ref_of,
)
from reven.integrations.repository import IntegrationRepository
from reven.scheduling import utc_now
from reven.security.redaction import redact
from reven.security.secrets import SecretBox, SecretBoxError

STATUS_UNTESTED = "未测试"
STATUS_OK = "连接正常"
STATUS_FAILED = "连接失败"

HINT_KEY = "_secret_hint"
MAX_ERROR_LENGTH = 500

# 附加模型独立密钥在 encrypted_secret 中的扁平键前缀（#166 约定：SecretBox 契约是扁平 dict）
MODEL_KEY_PREFIX = "model_key:"

SECRET_HINT_FIELDS = {
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


@dataclass(frozen=True)
class AgentModelTestResult:
    """单个模型的连接测试结果（ref 指定的模型条目；默认模型测试同时落行状态）。"""

    ref: str
    success: bool
    message: str | None
    latency_ms: int | None
    tested_at: datetime


ConnectionTestAdapter = Callable[
    [dict[str, object], dict[str, str] | None],
    Awaitable[ConnectionTestResult],
]


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
    def __init__(
        self,
        session: AsyncSession,
        secret_box: SecretBox,
        adapters: dict[str, ConnectionTestAdapter],
    ) -> None:
        self.repository = IntegrationRepository(session)
        self.secret_box = secret_box
        self.adapters = adapters

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

    async def upsert_agent_llm(
        self,
        *,
        public_config: dict[str, object],
        api_key: str | None,
        model_keys: dict[str, str] | None,
        refs_in_use: frozenset[str] = frozenset(),
    ) -> Integration:
        """agent-llm 专用 upsert：models[] 写回 + 密钥 merge 语义（#173）。

        与通用 upsert 的差异：
        - api_key 缺省时保留现有默认密钥；model_keys 增量合并（空串=清除该模型独立密钥）；
        - 每次写回 prune 掉不再被 models[] 引用的 ``model_key:<ref>`` 扁平键；
        - 从 models[] 移除被飞书会话 override 引用中的模型时拒绝（409 AGENT_MODEL_IN_USE）。
        """
        integration = await self.repository.get_by_provider(AGENT_LLM_PROVIDER)
        new_refs = _model_entry_refs(public_config)
        if integration is not None and refs_in_use:
            removed = _model_entry_refs(integration.public_config) - new_refs
            blocked = sorted(removed & refs_in_use)
            if blocked:
                raise IntegrationError(
                    status_code=409,
                    code="AGENT_MODEL_IN_USE",
                    message=f"模型 {', '.join(blocked)} 正被飞书会话使用，请先 /model use 切换其他模型",
                )

        existing: dict[str, str] = {}
        keep_ciphertext = False
        if integration is not None and integration.encrypted_secret is not None:
            try:
                existing = self.secret_box.decrypt(integration.encrypted_secret)
            except SecretBoxError as exc:
                if model_keys:
                    # 增量合并必须读旧密文；损坏时显式失败（对齐 delete/test 路径纪律）
                    raise IntegrationError(
                        status_code=500,
                        code="INTEGRATION_SECRET_INVALID",
                        message="集成 agent-llm 的 Secret 密文无法解密，请重新配置",
                    ) from exc
                if api_key is None:
                    # 纯配置保存：密文损坏不影响 public_config 写回，保持原样
                    keep_ciphertext = True
                # api_key 全量替换：旧密文（含 model_key:*）作废，从空字典重建

        secrets = dict(existing)
        if api_key is not None:
            secrets["api_key"] = api_key
        for ref, key in (model_keys or {}).items():
            if key:
                secrets[f"{MODEL_KEY_PREFIX}{ref}"] = key
            else:
                secrets.pop(f"{MODEL_KEY_PREFIX}{ref}", None)
        secrets = _prune_model_keys(secrets, new_refs)

        stored_config = dict(public_config)
        if api_key is not None:
            stored_config[HINT_KEY] = compute_secret_hint(AGENT_LLM_PROVIDER, {"api_key": api_key})
        elif integration is not None and (hint := secret_hint_of(integration)) is not None:
            stored_config[HINT_KEY] = hint

        if integration is None:
            integration = Integration(provider=AGENT_LLM_PROVIDER)
        integration.public_config = stored_config
        if not keep_ciphertext:
            integration.encrypted_secret = self.secret_box.encrypt(secrets) if secrets else None
        integration.connection_status = STATUS_UNTESTED
        integration.last_tested_at = None
        integration.last_error = None
        integration.last_latency_ms = None
        return await self.repository.save(integration)

    async def set_default_agent_model(self, ref: str) -> Integration:
        """把 models[] 中的附加模型提升为默认模型（#173）：顶层三元组与 api_key 一并交换。

        旧默认模型回落为启用的附加条目（占据被提升条目的原位置，列表顺序稳定）；
        其原默认 key 若与新默认 key 不同，则沉淀为该条目的独立 key（model_key:<ref>），
        保证交换后两个模型的凭证都继续可用。明文密钥不出后端进程。
        """
        integration = await self.get_integration(AGENT_LLM_PROVIDER)
        public = public_config_without_hint(integration)
        default_ref = _default_model_ref(public)
        if ref == default_ref:
            return integration  # 幂等：已是默认模型
        entries = _model_entries(public)
        index = next(
            (i for i, entry in enumerate(entries) if model_ref_of(entry["provider"], entry["model"]) == ref),
            None,
        )
        if index is None:
            raise IntegrationError(
                status_code=404,
                code="AGENT_MODEL_NOT_FOUND",
                message=f"模型 {ref} 未注册，无法设为默认",
            )
        promoted = entries[index]
        if promoted.get("enabled") is False:
            raise IntegrationError(
                status_code=409,
                code="AGENT_MODEL_DISABLED",
                message=f"模型 {ref} 已停用，请先启用再设为默认",
            )

        secrets = self._decrypt_secrets(integration)
        old_api_key = secrets.get("api_key")
        new_api_key = secrets.pop(f"{MODEL_KEY_PREFIX}{ref}", None) or old_api_key

        demoted_provider, demoted_model = _default_provider_model(public)
        demoted: _ModelEntry = {"provider": demoted_provider, "model": demoted_model, "enabled": True}
        if isinstance(public.get("base_url"), str) and public["base_url"]:
            demoted["base_url"] = str(public["base_url"])
        new_entries = list(entries)
        new_entries[index] = demoted

        new_config: dict[str, object] = {
            "provider": promoted["provider"],
            "model": promoted["model"],
            "models": new_entries,
        }
        if isinstance(promoted.get("base_url"), str) and promoted["base_url"]:
            new_config["base_url"] = promoted["base_url"]

        if new_api_key:
            secrets["api_key"] = new_api_key
        else:
            secrets.pop("api_key", None)
        if old_api_key is not None and old_api_key != new_api_key:
            secrets[f"{MODEL_KEY_PREFIX}{default_ref}"] = old_api_key
        else:
            secrets.pop(f"{MODEL_KEY_PREFIX}{default_ref}", None)
        secrets = _prune_model_keys(secrets, {model_ref_of(e["provider"], e["model"]) for e in new_entries})

        if new_api_key:
            new_config[HINT_KEY] = compute_secret_hint(AGENT_LLM_PROVIDER, {"api_key": new_api_key})
        integration.public_config = new_config
        integration.encrypted_secret = self.secret_box.encrypt(secrets) if secrets else None
        integration.connection_status = STATUS_UNTESTED
        integration.last_tested_at = None
        integration.last_error = None
        integration.last_latency_ms = None
        return await self.repository.save(integration)

    async def test_agent_model(self, ref: str) -> AgentModelTestResult:
        """按模型 ref 做连接测试（#173）：默认模型落行状态，附加模型纯返回本次结果。

        附加模型允许在停用状态下测试（先测后启用的工作流）；凭证取独立 key，
        缺省回落默认条目 api_key（与 #166 注册表同一约定）。
        """
        integration = await self.get_integration(AGENT_LLM_PROVIDER)
        adapter = self.adapters.get(AGENT_LLM_PROVIDER)
        if adapter is None:
            raise IntegrationError(
                status_code=503,
                code="CONNECTION_TEST_UNAVAILABLE",
                message=f"集成 {AGENT_LLM_PROVIDER} 的连接测试尚未接入",
            )
        secrets = self._decrypt_secrets(integration) if integration.encrypted_secret is not None else None
        public = public_config_without_hint(integration)
        default_ref = _default_model_ref(public)
        is_default = ref == default_ref
        if is_default:
            scoped_base_url = public.get("base_url")
            scoped_key = secrets.get("api_key") if secrets else None
        else:
            entry = next(
                (item for item in _model_entries(public) if model_ref_of(item["provider"], item["model"]) == ref),
                None,
            )
            if entry is None:
                raise IntegrationError(
                    status_code=404,
                    code="AGENT_MODEL_NOT_FOUND",
                    message=f"模型 {ref} 未注册，无法测试连接",
                )
            scoped_base_url = entry.get("base_url")
            scoped_key = (secrets.get(f"{MODEL_KEY_PREFIX}{ref}") or secrets.get("api_key")) if secrets else None

        scoped_public: dict[str, object] = {}
        if isinstance(scoped_base_url, str) and scoped_base_url:
            scoped_public["base_url"] = scoped_base_url
        scoped_secrets = {"api_key": scoped_key} if scoped_key else None
        try:
            result = await adapter(scoped_public, scoped_secrets)
        except Exception as exc:  # adapter failures must surface as a redacted result
            result = ConnectionTestResult(success=False, message=str(exc))

        tested_at = utc_now()
        known_secrets = list(secrets.values()) if secrets else []
        message = None
        if not result.success:
            message = redact(result.message or "连接测试失败", known_secrets)[:MAX_ERROR_LENGTH]
        if is_default:
            # 默认模型测试落行状态（与 run_connection_test 同语义）
            integration.last_tested_at = tested_at
            integration.last_latency_ms = result.latency_ms
            integration.connection_status = STATUS_OK if result.success else STATUS_FAILED
            integration.last_error = message
            await self.repository.save(integration)
        return AgentModelTestResult(
            ref=ref,
            success=result.success,
            message=message,
            latency_ms=result.latency_ms,
            tested_at=tested_at,
        )

    def agent_model_key_refs(self, integration: Integration) -> list[str] | None:
        """配有独立密钥的附加模型 ref 列表（排序、展示用）；密文缺失/损坏返回 None。"""
        if integration.encrypted_secret is None:
            return None
        try:
            secrets = self.secret_box.decrypt(integration.encrypted_secret)
        except SecretBoxError:
            return None
        return sorted(key[len(MODEL_KEY_PREFIX) :] for key in secrets if key.startswith(MODEL_KEY_PREFIX))

    def _decrypt_secrets(self, integration: Integration) -> dict[str, str]:
        """解密行密文；损坏抛 INTEGRATION_SECRET_INVALID（对齐 delete/test 路径纪律）。"""
        if integration.encrypted_secret is None:
            return {}
        try:
            return self.secret_box.decrypt(integration.encrypted_secret)
        except SecretBoxError as exc:
            raise IntegrationError(
                status_code=500,
                code="INTEGRATION_SECRET_INVALID",
                message=f"集成 {integration.provider} 的 Secret 密文无法解密，请重新配置",
            ) from exc

    async def run_connection_test(self, provider: str) -> Integration:
        integration = await self.get_integration(provider)
        adapter = self.adapters.get(provider)
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


class _ModelEntry(TypedDict):
    """public_config.models 条目（provider/model 必填，base_url/enabled 可选）。"""

    provider: str
    model: str
    base_url: NotRequired[str]
    enabled: NotRequired[bool]


def _model_entries(public_config: dict[str, object]) -> list[_ModelEntry]:
    """public_config.models 中形态合法的条目（provider/model 为非空字符串），规范化为已知键。

    API 写路径经 Pydantic 校验后此处恒为全量通过；防御性过滤兜底历史脏数据。
    """
    raw = public_config.get("models")
    if not isinstance(raw, list):
        return []
    entries: list[_ModelEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        provider = item.get("provider")
        model = item.get("model")
        if not (isinstance(provider, str) and provider and isinstance(model, str) and model):
            continue
        entry: _ModelEntry = {"provider": provider, "model": model}
        base_url = item.get("base_url")
        if isinstance(base_url, str) and base_url:
            entry["base_url"] = base_url
        if item.get("enabled") is False:
            entry["enabled"] = False
        entries.append(entry)
    return entries


def _model_entry_refs(public_config: dict[str, object]) -> set[str]:
    return {model_ref_of(entry["provider"], entry["model"]) for entry in _model_entries(public_config)}


def _default_provider_model(public_config: dict[str, object]) -> tuple[str, str]:
    provider = public_config.get("provider")
    model = public_config.get("model")
    return (
        provider if isinstance(provider, str) and provider else DEFAULT_AGENT_LLM_PROVIDER,
        model if isinstance(model, str) and model else DEFAULT_AGENT_LLM_MODEL,
    )


def _default_model_ref(public_config: dict[str, object]) -> str:
    return model_ref_of(*_default_provider_model(public_config))


def _prune_model_keys(secrets: dict[str, str], valid_refs: set[str]) -> dict[str, str]:
    """丢弃不再被 models[] 引用的 model_key:<ref> 扁平键（默认条目的 key 是 api_key，无需保留）。"""
    return {
        key: value
        for key, value in secrets.items()
        if not key.startswith(MODEL_KEY_PREFIX) or key[len(MODEL_KEY_PREFIX) :] in valid_refs
    }
