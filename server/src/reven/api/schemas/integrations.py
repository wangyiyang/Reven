"""Request/response schemas for the integration settings API.

Each provider has its own strict (``extra="forbid"``) public-config and secret
models so validation rules stay per-integration. Responses never carry secret
material: only ``secret_configured`` and an irreversible ``secret_hint``.
"""

from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reven.integrations.models import Integration
from reven.integrations.providers import SUPPORTED_INTEGRATION_PROVIDERS, model_ref_of
from reven.integrations.service import public_config_without_hint, secret_hint_of

PROVIDERS = SUPPORTED_INTEGRATION_PROVIDERS


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


class FeishuBotPublicConfig(_Strict):
    """飞书应用（机器人）公开配置：白名单指定通知接收人与审核成员，enabled 控制通知和入站事件。"""

    whitelist_open_ids: list[Annotated[str, Field(min_length=1, max_length=64, pattern=r"^\S+$")]] = Field(
        default_factory=list
    )
    enabled: bool = False


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


class AgentLlmModelEntry(_Strict):
    """附加模型条目（public_config.models[] 元素）：一个可切换的 provider/model 组合。

    enabled=False 时对 /model 指令与运行时不可见（白名单语义），但配置与独立 key 保留。
    """

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    base_url: str | None = None
    enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_https_origin(value, field="附加模型 base_url")


MAX_AGENT_LLM_MODELS = 16


class AgentLlmPublicConfig(_Strict):
    """Agent LLM 集成的公开配置：provider/model 决定推理端点，base_url 可覆盖官方地址。

    models[] 为附加可切换模型（#163 注册表、#173 管理界面）；顶层三元组始终是默认条目。
    """

    provider: str = Field(default="deepseek-official", min_length=1, max_length=64)
    model: str = Field(default="deepseek-v4-flash", min_length=1, max_length=128)
    base_url: str | None = None
    models: list[AgentLlmModelEntry] = Field(default_factory=list, max_length=MAX_AGENT_LLM_MODELS)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_https_origin(value, field="Agent LLM base_url")

    @model_validator(mode="after")
    def validate_model_refs(self) -> "AgentLlmPublicConfig":
        default_ref = model_ref_of(self.provider, self.model)
        seen: set[str] = set()
        for entry in self.models:
            ref = model_ref_of(entry.provider, entry.model)
            if ref == default_ref:
                raise ValueError(f"附加模型 {ref} 与默认模型重复")
            if ref in seen:
                raise ValueError(f"附加模型 {ref} 重复")
            seen.add(ref)
        return self


class BaiduTranslateSecret(_Strict):
    app_id: str = Field(min_length=1, max_length=256)
    app_key: str = Field(min_length=1, max_length=256)


class AliyunTranslateSecret(_Strict):
    access_key_id: str = Field(min_length=1, max_length=256)
    access_key_secret: str = Field(min_length=1, max_length=256)


class EmbeddingSecret(_Strict):
    api_key: str = Field(min_length=1, max_length=256)


class AgentLlmSecret(_Strict):
    """agent-llm 密钥写入口：api_key 为默认模型密钥，model_keys 为附加模型独立密钥。

    两者均可选（至少提供一项），服务端按 merge 语义写回 encrypted_secret：
    未提及的 key 保留；model_keys 值为空串表示清除该模型的独立密钥（回落共用默认密钥）。
    """

    api_key: str | None = Field(default=None, min_length=1, max_length=256)
    model_keys: dict[Annotated[str, Field(min_length=3, max_length=193, pattern=r"^\S+/\S+$")], str] | None = None

    @model_validator(mode="after")
    def validate_any_secret(self) -> "AgentLlmSecret":
        if self.api_key is None and not self.model_keys:
            raise ValueError("secret 必须包含 api_key 或 model_keys")
        return self


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
    FeishuBotIntegrationPut
    | BaiduTranslateIntegrationPut
    | AliyunTranslateIntegrationPut
    | EmbeddingIntegrationPut
    | AgentLlmIntegrationPut
)

PUT_MODELS: dict[str, type[IntegrationPut]] = {
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
    """仅 agent-llm：配有独立密钥的附加模型 ref 列表（其他 provider 恒为 None）。"""
    model_key_refs: list[str] | None = None


class SetDefaultModelRequest(_Strict):
    """设默认模型请求体：ref 为 `provider/model` 形式的模型引用。"""

    ref: Annotated[str, Field(min_length=3, max_length=193, pattern=r"^\S+/\S+$")]


class TestConnectionRequest(_Strict):
    """连接测试请求体：model_ref 缺省时测默认模型（现状行为）；仅 agent-llm 支持指定。"""

    model_ref: Annotated[str, Field(min_length=3, max_length=193, pattern=r"^\S+/\S+$")] | None = None


class AgentModelTestResponse(BaseModel):
    """附加模型的连接测试结果：不动 integrations 行状态，纯本次结果回传。"""

    ref: str
    success: bool
    message: str | None
    latency_ms: int | None
    tested_at: datetime


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
