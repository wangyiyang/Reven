"""Versioned AES-256-GCM envelope encryption for integration secrets."""

import base64
import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_ASSOCIATED_DATA = b"reven:v1"


class SecretBoxError(ValueError):
    """Secret 密文解析或解密失败（格式非法、版本不支持、被篡改或密钥错误）。"""


@dataclass(frozen=True)
class SecretBox:
    key: bytes

    @classmethod
    def from_base64(cls, encoded: str) -> "SecretBox":
        key = base64.urlsafe_b64decode(encoded)
        if len(key) != 32:
            raise ValueError("REVEN_MASTER_KEY 必须解码为 32 字节")
        return cls(key)

    def encrypt(self, value: dict[str, str]) -> str:
        nonce = os.urandom(12)
        plaintext = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
        ciphertext = AESGCM(self.key).encrypt(nonce, plaintext, _ASSOCIATED_DATA)
        envelope = base64.urlsafe_b64encode(nonce + ciphertext).decode()
        return f"v1:{envelope}"

    def decrypt(self, envelope: str) -> dict[str, str]:
        version, separator, encoded = envelope.partition(":")
        if not separator or not encoded:
            raise SecretBoxError("Secret 密文格式无效")
        if version != "v1":
            raise SecretBoxError("不支持的 Secret 密文版本")
        try:
            payload = base64.urlsafe_b64decode(encoded)
        except ValueError as exc:
            raise SecretBoxError("Secret 密文格式无效") from exc
        if len(payload) <= 12:
            raise SecretBoxError("Secret 密文格式无效")
        try:
            plaintext = AESGCM(self.key).decrypt(payload[:12], payload[12:], _ASSOCIATED_DATA)
            decoded = json.loads(plaintext)
        except Exception as exc:
            raise SecretBoxError("Secret 密文解密失败") from exc
        if not isinstance(decoded, dict):
            raise SecretBoxError("Secret 密文格式无效")
        return {str(key): str(value) for key, value in decoded.items()}
