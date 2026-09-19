from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_AGENT_MCP_URL = "http://127.0.0.1:8000/agent/mcp"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    reven_master_key: SecretStr
    reven_admin_password: SecretStr
    public_base_url: str = Field(
        default="http://dev.wangyiyang.cc:3001",
        validation_alias=AliasChoices("REVEN_PUBLIC_BASE_URL", "PUBLIC_BASE_URL"),
    )
    sync_interval_seconds: int = 60
    scheduler_interval_seconds: int = 5
    job_lease_seconds: int = Field(default=120, ge=3)
    job_data_dir: str = "/data/jobs"
    renderer_command: str = "node /app/renderer/dist/cli.mjs"
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
        parsed = urlsplit(value)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("PUBLIC_BASE_URL 必须是 HTTP origin")
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
