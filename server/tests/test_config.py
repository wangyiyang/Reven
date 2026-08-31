import pytest
from pydantic import ValidationError
from reven.config import Settings


def test_settings_read_only_infrastructure_secrets(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@db/test")
    monkeypatch.setenv("REVEN_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://")
    assert settings.public_base_url == "http://dev.wangyiyang.cc:3001"
    assert "notion" not in Settings.model_fields
    assert "wechat_app_secret" not in Settings.model_fields
    assert settings.cos_secret_id is None
    assert settings.cos_secret_key is None
    assert settings.siliconflow_api_key is None
    assert settings.siliconflow_chat_model == "Qwen/Qwen3-8B"
    assert settings.rss_scheduler_interval_seconds == 60


def test_public_base_url_accepts_http_origin(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@db/test")
    monkeypatch.setenv("REVEN_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("REVEN_PUBLIC_BASE_URL", "http://example.com:8080")

    assert Settings(_env_file=None).public_base_url == "http://example.com:8080"


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com",
        "http://example.com/path",
        "http://user@example.com",
        "javascript:alert(1)",
    ],
)
def test_public_base_url_rejects_unsafe_origins(monkeypatch, value: str) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@db/test")
    monkeypatch.setenv("REVEN_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("REVEN_PUBLIC_BASE_URL", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
