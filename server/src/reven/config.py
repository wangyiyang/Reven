import re
from datetime import time
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
    # RSS 批韧性（#178）：翻译失败告警阈值与死源连续失败禁用阈值
    # ratio 设为 >1.0 可关闭占比通道（仅看绝对数阈值）
    rss_translation_alert_count: int = Field(default=10, ge=1)
    rss_translation_alert_ratio: float = Field(default=0.3, ge=0.0)
    rss_source_max_consecutive_failures: int = Field(default=3, ge=1)
    # 定时主动推送（#171）：每日 run_at（Asia/Shanghai）触发挂载场景；chat_id 为空时降级机器人白名单接收人
    notify_push_enabled: bool = True
    notify_push_time: str = "09:00"
    notify_push_chat_id: str | None = None
    notify_push_heartbeat: bool = False
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

    @field_validator("notify_push_time")
    @classmethod
    def validate_notify_push_time(cls, value: str) -> str:
        """严格 HH:MM（24 小时制）；time.fromisoformat 单独用会放过带时区偏移等异形输入。"""
        if not re.fullmatch(r"\d{2}:\d{2}", value):
            raise ValueError("NOTIFY_PUSH_TIME 必须是 HH:MM 格式（Asia/Shanghai 本地时刻）")
        try:
            time.fromisoformat(value)
        except ValueError as error:
            raise ValueError("NOTIFY_PUSH_TIME 必须是 HH:MM 格式（Asia/Shanghai 本地时刻）") from error
        return value

    @field_validator("notify_push_chat_id", mode="before")
    @classmethod
    def blank_chat_id_as_none(cls, value: object) -> object:
        """.env 里 NOTIFY_PUSH_CHAT_ID= 留空视为未配置。"""
        if isinstance(value, str) and not value.strip():
            return None
        return value


def get_settings() -> Settings:
    """全仓唯一 Settings 解析入口：仅组合根（app.py lifespan）调用，每进程一次。

    不设缓存：组合根之外的重复调用是装配缺陷，应显式注入 Settings 而非依赖全局态。
    """
    return Settings()  # type: ignore[call-arg]
