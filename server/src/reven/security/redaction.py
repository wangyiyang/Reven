"""Redaction helpers to keep secrets out of responses, logs and stored errors."""

from collections.abc import Iterable

SENSITIVE_KEYS = frozenset({"token", "secret", "password", "authorization", "webhook_url", "signing_secret"})

REDACTED = "***"


def redact_mapping(value: object) -> object:
    if isinstance(value, dict):
        return {key: REDACTED if key.lower() in SENSITIVE_KEYS else redact_mapping(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    return value


def redact(text: str, known_secrets: Iterable[str]) -> str:
    """Replace every occurrence of each known secret value in ``text``.

    注意：替换是精确且大小写敏感的子串匹配，无法识别 Secret 的 URL 编码
    或 base64 编码形态；适配器作者在记录日志前应先对响应体自行脱敏。
    """
    redacted = text
    for secret in sorted(set(known_secrets), key=len, reverse=True):
        if secret:
            redacted = redacted.replace(secret, REDACTED)
    return redacted
