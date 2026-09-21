import pytest
from pydantic import ValidationError
from reven.config import Settings


@pytest.fixture(autouse=True)
def _clean_origin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REVEN_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)


def test_settings_read_only_infrastructure_secrets(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@db/test")
    monkeypatch.setenv("REVEN_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://")
    assert settings.public_base_url == "http://dev.wangyiyang.cc:3001"
    assert "notion" not in Settings.model_fields
    assert "wechat_app_secret" not in Settings.model_fields
    assert {
        "sync_interval_seconds",
        "scheduler_interval_seconds",
        "job_lease_seconds",
        "job_data_dir",
        "renderer_command",
    }.isdisjoint(Settings.model_fields)
    assert settings.cos_secret_id is None
    assert settings.cos_secret_key is None
    assert settings.siliconflow_api_key is None
    assert settings.siliconflow_chat_model == "Qwen/Qwen3-8B"
    assert settings.rss_scheduler_interval_seconds == 60


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://example.com:8080", "http://example.com:8080"),
        ("HTTPS://EXAMPLE.COM/", "https://example.com"),
        ("https://example.com:443/", "https://example.com"),
        ("HTTP://LOCALHOST:80", "http://localhost"),
        ("https://example.com:8443", "https://example.com:8443"),
        ("https://xn--fa-hia.de", "https://xn--fa-hia.de"),
        ("http://127.0.0.1:8080/", "http://127.0.0.1:8080"),
        ("https://[::1]:443/", "https://[::1]"),
    ],
)
def test_public_base_url_normalizes_http_and_https_origins(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@db/test")
    monkeypatch.setenv("REVEN_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("REVEN_PUBLIC_BASE_URL", value)

    assert Settings(_env_file=None).public_base_url == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com/path",
        "http://user@example.com",
        "javascript:alert(1)",
        "http://example.com:0",
        "https://example.com:65536",
        "https://example.com:invalid",
        "https://example.com:",
        "https://example.com?",
        "https://example.com#fragment",
        " https://example.com",
        "https://example.com ",
        "https://exam\tple.com",
        "https://example.com\n",
        "https://exam ple.com",
        "https://example.com\\evil",
        "https://example..com",
        "https://-example.com",
        "https://example.com,evil.example",
        "https://[::1",
        "https://[::1]evil",
        "https://[::1]evil:443",
        "https://faß.de",
        "https://例子.example",
        "https://K.example",
    ],
)
def test_public_base_url_rejects_unsafe_origins(monkeypatch, value: str) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@db/test")
    monkeypatch.setenv("REVEN_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("REVEN_PUBLIC_BASE_URL", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_public_base_url_preserves_alias_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@db/test")
    monkeypatch.setenv("REVEN_MASTER_KEY", "test-master-key")
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")
    monkeypatch.setenv("PUBLIC_BASE_URL", "HTTPS://EXAMPLE.COM:443/")
    assert Settings(_env_file=None).public_base_url == "https://example.com"

    monkeypatch.setenv("REVEN_PUBLIC_BASE_URL", "http://localhost:8080")
    assert Settings(_env_file=None).public_base_url == "http://localhost:8080"
