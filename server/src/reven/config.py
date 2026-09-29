from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from reven.security.origin import normalize_origin

DEFAULT_AGENT_MCP_URL = "http://127.0.0.1:8000/agent/mcp"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    reven_master_key: SecretStr
    reven_admin_password: SecretStr
    public_base_url: str = Field(
        default="http://localhost:8080",
        validation_alias=AliasChoices("REVEN_PUBLIC_BASE_URL", "PUBLIC_BASE_URL"),
    )
    cos_bucket: str | None = None
    cos_region: str | None = None
    cos_secret_id: SecretStr | None = None
    cos_secret_key: SecretStr | None = None
    cos_public_base_url: str | None = None
    cos_asset_prefix: str = "assets/sha256"
    siliconflow_api_key: SecretStr | None = None
    siliconflow_chat_model: str = "Qwen/Qwen3-8B"
    rss_model_review_enabled: bool = True
    rss_scheduler_interval_seconds: int = Field(default=60, ge=5)
    dsh_home: Path = Path(".dsh-runtime")
    agent_provider: str = "deepseek-official"
    agent_model: str = "deepseek-v4-flash"
    agent_base_url: str | None = None
    agent_api_key: SecretStr | None = None
    agent_mcp_token: SecretStr | None = None
    agent_mcp_url: str = DEFAULT_AGENT_MCP_URL

    @field_validator("public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: str) -> str:
        try:
            return normalize_origin(value)
        except ValueError as error:
            raise ValueError("PUBLIC_BASE_URL 必须是 HTTP 或 HTTPS origin，域名请使用 ASCII 或 Punycode") from error


def get_settings() -> Settings:
    """全仓唯一 Settings 解析入口：仅组合根（app.py lifespan）调用，每进程一次。

    不设缓存：组合根之外的重复调用是装配缺陷，应显式注入 Settings 而非依赖全局态。
    """
    return Settings()  # type: ignore[call-arg]
