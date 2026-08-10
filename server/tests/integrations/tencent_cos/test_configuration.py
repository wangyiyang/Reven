import pytest
from reven.config import Settings
from reven.integrations.tencent_cos.configuration import (
    TencentCosConfigurationError,
    load_tencent_cos_configuration,
)


def _settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    values = {
        "DATABASE_URL": "postgresql+asyncpg://test:test@db/test",
        "REVEN_MASTER_KEY": "test-master-key",
        "COS_BUCKET": "reven-1251081768",
        "COS_REGION": "ap-beijing",
        "COS_SECRET_ID": "AKIDexample",
        "COS_SECRET_KEY": "secret-key",
        **overrides,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def test_configuration_builds_official_public_domain_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    configuration = load_tencent_cos_configuration(_settings(monkeypatch))

    assert configuration.bucket == "reven-1251081768"
    assert configuration.region == "ap-beijing"
    assert configuration.public_base_url == "https://reven-1251081768.cos.ap-beijing.myqcloud.com"
    assert configuration.asset_prefix == "assets/sha256"


def test_configuration_accepts_custom_public_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    configuration = load_tencent_cos_configuration(
        _settings(monkeypatch, COS_PUBLIC_BASE_URL="https://assets.example.com")
    )

    assert configuration.public_base_url == "https://assets.example.com"


@pytest.mark.parametrize(
    "name,value",
    [
        ("COS_BUCKET", "reven"),
        ("COS_REGION", "https://evil.example.com"),
        ("COS_PUBLIC_BASE_URL", "https://user@example.com"),
        ("COS_ASSET_PREFIX", "../assets"),
    ],
)
def test_configuration_rejects_unsafe_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    with pytest.raises(TencentCosConfigurationError):
        load_tencent_cos_configuration(_settings(monkeypatch, **{name: value}))


def test_configuration_reports_missing_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@db/test")
    monkeypatch.setenv("REVEN_MASTER_KEY", "test-master-key")

    with pytest.raises(TencentCosConfigurationError, match="COS_BUCKET"):
        load_tencent_cos_configuration(Settings(_env_file=None))
