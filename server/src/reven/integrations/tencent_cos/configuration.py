import re
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit

from reven.config import Settings

_BUCKET_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,48}[a-z0-9]-[0-9]{5,20}")
_REGION_PATTERN = re.compile(r"(?:ap|na|eu|af|me|sa)-[a-z0-9-]{2,60}")
_PREFIX_PATTERN = re.compile(r"[a-z0-9][a-z0-9/_-]{0,127}")


class TencentCosConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class TencentCosConfiguration:
    bucket: str
    region: str
    secret_id: str
    secret_key: str
    public_base_url: str
    asset_prefix: str


def load_tencent_cos_configuration(settings: Settings) -> TencentCosConfiguration:
    values = (
        settings.cos_bucket,
        settings.cos_region,
        settings.cos_secret_id,
        settings.cos_secret_key,
    )
    names = ("COS_BUCKET", "COS_REGION", "COS_SECRET_ID", "COS_SECRET_KEY")
    missing = [name for name, value in zip(names, values, strict=True) if value is None]
    if missing:
        raise TencentCosConfigurationError(f"缺少 COS 配置：{', '.join(missing)}")

    assert settings.cos_bucket is not None
    assert settings.cos_region is not None
    assert settings.cos_secret_id is not None
    assert settings.cos_secret_key is not None
    if _BUCKET_PATTERN.fullmatch(settings.cos_bucket) is None:
        raise TencentCosConfigurationError("COS_BUCKET 必须是 BucketName-APPID 格式")
    if _REGION_PATTERN.fullmatch(settings.cos_region) is None:
        raise TencentCosConfigurationError("COS_REGION 格式无效")
    secret_id = settings.cos_secret_id.get_secret_value()
    secret_key = settings.cos_secret_key.get_secret_value()
    _validate_secret(secret_id, "COS_SECRET_ID")
    _validate_secret(secret_key, "COS_SECRET_KEY")

    default_public_url = f"https://{settings.cos_bucket}.cos.{settings.cos_region}.myqcloud.com"
    public_base_url = _validate_public_url(settings.cos_public_base_url or default_public_url)
    asset_prefix = settings.cos_asset_prefix.strip("/")
    if _PREFIX_PATTERN.fullmatch(asset_prefix) is None or "//" in asset_prefix:
        raise TencentCosConfigurationError("COS_ASSET_PREFIX 格式无效")
    return TencentCosConfiguration(
        settings.cos_bucket,
        settings.cos_region,
        secret_id,
        secret_key,
        public_base_url,
        asset_prefix,
    )


def _validate_secret(value: str, field: str) -> None:
    if not value or any(character.isspace() for character in value):
        raise TencentCosConfigurationError(f"{field} 不能为空或包含空白字符")


def _validate_public_url(value: str) -> str:
    parsed = urlsplit(value)
    if not _is_https_origin(parsed):
        raise TencentCosConfigurationError("COS_PUBLIC_BASE_URL 必须是 HTTPS origin")
    return value.rstrip("/")


def _is_https_origin(parsed: SplitResult) -> bool:
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and port is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )
