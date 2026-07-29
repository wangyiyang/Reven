from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    reven_master_key: SecretStr
    public_base_url: str = "https://dev.wangyiyang.cc"
    sync_interval_seconds: int = 60
    scheduler_interval_seconds: int = 5
    job_lease_seconds: int = Field(default=120, ge=3)
    job_data_dir: str = "/data/jobs"
    renderer_command: str = "node /app/renderer/dist/cli.mjs"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
