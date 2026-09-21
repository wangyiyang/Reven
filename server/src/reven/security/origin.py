"""Canonical HTTP origins shared by configuration and CSRF validation."""

import re
from ipaddress import IPv6Address
from urllib.parse import urlsplit

_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.?\Z")


def normalize_origin(value: str) -> str:
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("invalid origin")
    if any(char in value for char in ("\\", "?", "#", "%")):
        raise ValueError("invalid origin")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or not parsed.netloc.isascii()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.netloc.endswith(":")
    ):
        raise ValueError("invalid origin")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{IPv6Address(host).compressed}]"
    elif len(host) > 253 or not _HOST.fullmatch(host):
        raise ValueError("invalid origin")
    port = parsed.port
    if port == 0:
        raise ValueError("invalid origin")
    default_port = 443 if parsed.scheme == "https" else 80
    authority = host if port in {None, default_port} else f"{host}:{port}"
    return f"{parsed.scheme}://{authority}"
