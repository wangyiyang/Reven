"""Request/response schemas for the integration settings API.

Each provider has its own strict (``extra="forbid"``) public-config and secret
models so validation rules stay per-integration. Responses never carry secret
material: only ``secret_configured`` and an irreversible ``secret_hint``.
"""

from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from reven.integrations.models import Integration
from reven.integrations.providers import SUPPORTED_INTEGRATION_PROVIDERS
from reven.integrations.service import public_config_without_hint, secret_hint_of

PROVIDERS = SUPPORTED_INTEGRATION_PROVIDERS

_FEISHU_WEBHOOK_PATTERN = r"^https://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9-]+$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_https_origin(value: str, *, field: str) -> str:
    parsed = urlsplit(value)
    localhost = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    valid_scheme = parsed.scheme == "https" or (parsed.scheme == "http" and localhost)
    if (
        not valid_scheme
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{field} 必须是 HTTPS origin；仅 localhost 测试可使用 HTTP")
    return value.rstrip("/")


class FeishuPublicConfig(_Strict):
    name: str = Field(min_length=1, max_length=64)


class FeishuBotPublicConfig(_Strict):
    """飞书应用（机器人）公开配置：白名单限定可执行审核按钮的成员，enabled 控制入站长连接。"""

    whitelist_open_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(default_factory=list)
    enabled: bool = False


class FeishuSecret(_Strict):
    webhook_url: str = Field(pattern=_FEISHU_WEBHOOK_PATTERN, max_length=512)
    signing_secret: str | None = Field(default=None, min_length=1, max_length=256)


class FeishuBotSecret(_Strict):
    app_id: str = Field(min_length=1, max_length=256)
    app_secret: str = Field(min_length=1, max_length=256)


class TranslationPublicConfig(_Strict):
    """机翻集成的公开配置：priority 决定故障切换顺序，enabled 控制是否参与翻译。"""

    priority: int = Field(ge=1, le=99)
    enabled: bool = True


class EmbeddingPublicConfig(_Strict):
    base_url: str
    model: str = "BAAI/bge-m3"

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return _validate_https_origin(value, field="Embedding base_url")


class AgentLlmPublicConfig(_Strict):
    """Agent LLM 集成的公开配置：provider/model 决定推理端点，base_url 可覆盖官方地址。"""

    provider: str = Field(default="deepseek-official", min_length=1, max_length=64)
    model: str = Field(default="deepseek-v4-flash", min_length=1, max_length=128)
    base_url: str | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_https_origin(value, field="Agent LLM base_url")


class BaiduTranslateSecret(_Strict):
    app_id: str = Field(min_length=1, max_length=256)
    app_key: str = Field(min_length=1, max_length=256)


class AliyunTranslateSecret(_Strict):
    access_key_id: str = Field(min_length=1, max_length=256)
    access_key_secret: str = Field(min_length=1, max_length=256)


class EmbeddingSecret(_Strict):
    api_key: str = Field(min_length=1, max_length=256)


class AgentLlmSecret(_Strict):
    api_key: str = Field(min_length=1, max_length=256)


class FeishuIntegrationPut(_Strict):
    public_config: FeishuPublicConfig
    secret: FeishuSecret | None = None


class FeishuBotIntegrationPut(_Strict):
    public_config: FeishuBotPublicConfig
    secret: FeishuBotSecret | None = None


class BaiduTranslateIntegrationPut(_Strict):
    public_config: TranslationPublicConfig
    secret: BaiduTranslateSecret | None = None


class AliyunTranslateIntegrationPut(_Strict):
    public_config: TranslationPublicConfig
    secret: AliyunTranslateSecret | None = None


class EmbeddingIntegrationPut(_Strict):
    public_config: EmbeddingPublicConfig
    secret: EmbeddingSecret | None = None


class AgentLlmIntegrationPut(_Strict):
    public_config: AgentLlmPublicConfig
    secret: AgentLlmSecret | None = None


IntegrationPut = (
    FeishuIntegrationPut
    | FeishuBotIntegrationPut
    | BaiduTranslateIntegrationPut
    | AliyunTranslateIntegrationPut
    | EmbeddingIntegrationPut
    | AgentLlmIntegrationPut
)

PUT_MODELS: dict[str, type[IntegrationPut]] = {
    "feishu": FeishuIntegrationPut,
    "feishu_bot": FeishuBotIntegrationPut,
    "translate_baidu": BaiduTranslateIntegrationPut,
    "translate_aliyun": AliyunTranslateIntegrationPut,
    "embedding": EmbeddingIntegrationPut,
    "agent-llm": AgentLlmIntegrationPut,
}


class IntegrationResponse(BaseModel):
    provider: str
    public_config: dict[str, object]
    secret_configured: bool
    secret_hint: str | None
    connection_status: str
    last_tested_at: datetime | None
    last_error: str | None
    last_latency_ms: int | None


def to_response(integration: Integration) -> IntegrationResponse:
    return IntegrationResponse(
        provider=integration.provider,
        public_config=public_config_without_hint(integration),
        secret_configured=integration.encrypted_secret is not None,
        secret_hint=secret_hint_of(integration),
        connection_status=integration.connection_status,
        last_tested_at=integration.last_tested_at,
        last_error=integration.last_error,
        last_latency_ms=integration.last_latency_ms,
    )
