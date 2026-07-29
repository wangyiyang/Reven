"""Request/response schemas for the integration settings API.

Each provider has its own strict (``extra="forbid"``) public-config and secret
models so validation rules stay per-integration. Responses never carry secret
material: only ``secret_configured`` and an irreversible ``secret_hint``.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from reven.integrations.models import Integration
from reven.integrations.service import public_config_without_hint, secret_hint_of

PROVIDERS = ("notion", "github", "wechat", "feishu")

_OWNER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$"
_REPO_PATTERN = r"^[A-Za-z0-9._-]{1,100}$"
_BRANCH_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$"
_APP_ID_PATTERN = r"^[A-Za-z0-9]{1,64}$"
_FEISHU_WEBHOOK_PATTERN = r"^https://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9-]+$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NotionPublicConfig(_Strict):
    data_source_id: UUID
    database_id: UUID


class GitHubPublicConfig(_Strict):
    owner: str = Field(pattern=_OWNER_PATTERN)
    repo: str = Field(pattern=_REPO_PATTERN)
    default_branch: str = Field(default="main", pattern=_BRANCH_PATTERN)


class WeChatPublicConfig(_Strict):
    app_id: str = Field(pattern=_APP_ID_PATTERN)
    author: str | None = Field(default=None, max_length=64)


class FeishuPublicConfig(_Strict):
    name: str = Field(min_length=1, max_length=64)


class NotionSecret(_Strict):
    token: str = Field(min_length=1, max_length=256)


class GitHubSecret(_Strict):
    token: str = Field(min_length=1, max_length=256)


class WeChatSecret(_Strict):
    app_secret: str = Field(min_length=1, max_length=256)


class FeishuSecret(_Strict):
    webhook_url: str = Field(pattern=_FEISHU_WEBHOOK_PATTERN, max_length=512)


class NotionIntegrationPut(_Strict):
    public_config: NotionPublicConfig
    secret: NotionSecret | None = None


class GitHubIntegrationPut(_Strict):
    public_config: GitHubPublicConfig
    secret: GitHubSecret | None = None


class WeChatIntegrationPut(_Strict):
    public_config: WeChatPublicConfig
    secret: WeChatSecret | None = None


class FeishuIntegrationPut(_Strict):
    public_config: FeishuPublicConfig
    secret: FeishuSecret | None = None


IntegrationPut = NotionIntegrationPut | GitHubIntegrationPut | WeChatIntegrationPut | FeishuIntegrationPut

PUT_MODELS: dict[str, type[IntegrationPut]] = {
    "notion": NotionIntegrationPut,
    "github": GitHubIntegrationPut,
    "wechat": WeChatIntegrationPut,
    "feishu": FeishuIntegrationPut,
}


class IntegrationResponse(BaseModel):
    provider: str
    public_config: dict[str, object]
    secret_configured: bool
    secret_hint: str | None
    connection_status: str
    last_tested_at: datetime | None
    last_error: str | None


class BootstrapSchemaResponse(BaseModel):
    """Notion 字段初始化结果：本次是否发送了 PATCH 以及补齐了哪些字段。"""

    patched: bool
    properties: list[str]


def to_response(integration: Integration) -> IntegrationResponse:
    return IntegrationResponse(
        provider=integration.provider,
        public_config=public_config_without_hint(integration),
        secret_configured=integration.encrypted_secret is not None,
        secret_hint=secret_hint_of(integration),
        connection_status=integration.connection_status,
        last_tested_at=integration.last_tested_at,
        last_error=integration.last_error,
    )
