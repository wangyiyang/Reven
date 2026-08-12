import base64

import pytest
from reven.security.redaction import redact, redact_mapping
from reven.security.secrets import SecretBox, SecretBoxError


def _master_key() -> str:
    return base64.urlsafe_b64encode(b"k" * 32).decode()


def test_secret_box_round_trip_and_random_nonce() -> None:
    box = SecretBox.from_base64(_master_key())
    first = box.encrypt({"token": "notion-secret"})
    second = box.encrypt({"token": "notion-secret"})

    assert first != second
    assert box.decrypt(first) == {"token": "notion-secret"}


def test_secret_box_tampered_ciphertext_is_rejected() -> None:
    box = SecretBox.from_base64(_master_key())
    envelope = box.encrypt({"token": "notion-secret"})
    version, encoded = envelope.split(":", maxsplit=1)
    payload = bytearray(base64.urlsafe_b64decode(encoded))
    payload[-1] ^= 1
    tampered = f"{version}:{base64.urlsafe_b64encode(bytes(payload)).decode()}"

    with pytest.raises(SecretBoxError):
        box.decrypt(tampered)


def test_secret_box_wrong_key_is_rejected() -> None:
    box = SecretBox.from_base64(_master_key())
    other = SecretBox.from_base64(base64.urlsafe_b64encode(b"x" * 32).decode())
    envelope = box.encrypt({"token": "notion-secret"})

    with pytest.raises(SecretBoxError):
        other.decrypt(envelope)


def test_secret_box_rejects_unknown_version() -> None:
    box = SecretBox.from_base64(_master_key())
    envelope = box.encrypt({"token": "notion-secret"})

    with pytest.raises(SecretBoxError, match="版本"):
        box.decrypt(f"v2:{envelope.split(':', maxsplit=1)[1]}")


def test_secret_box_rejects_malformed_envelopes() -> None:
    box = SecretBox.from_base64(_master_key())

    with pytest.raises(SecretBoxError):
        box.decrypt("没有分隔符")
    with pytest.raises(SecretBoxError):
        box.decrypt("v1:")
    with pytest.raises(SecretBoxError):
        box.decrypt(f"v1:{base64.urlsafe_b64encode(b'short').decode()}")
    with pytest.raises(SecretBoxError):
        box.decrypt("v1:!!!不是base64!!!")


def test_secret_box_rejects_wrong_key_length() -> None:
    with pytest.raises(ValueError, match="32"):
        SecretBox.from_base64(base64.urlsafe_b64encode(b"short").decode())


def test_redact_mapping_replaces_sensitive_keys_case_insensitively() -> None:
    value = {
        "Token": "abc",
        "authorization": "Bearer xyz",
        "WEBHOOK_URL": "https://open.feishu.cn/hook/1",
        "signing_secret": "feishu-signing-secret",
        "name": "保留",
    }

    assert redact_mapping(value) == {
        "Token": "***",
        "authorization": "***",
        "WEBHOOK_URL": "***",
        "signing_secret": "***",
        "name": "保留",
    }


def test_redact_mapping_recurses_into_nested_structures() -> None:
    value = {"outer": {"secret": "s", "items": [{"password": "p"}, {"ok": 1}]}}

    assert redact_mapping(value) == {"outer": {"secret": "***", "items": [{"password": "***"}, {"ok": 1}]}}


def test_redact_replaces_known_secret_values_in_text() -> None:
    text = "请求失败：token=ntn_12345 返回 401，ntn_12345 已失效"

    assert redact(text, ["ntn_12345"]) == "请求失败：token=*** 返回 401，*** 已失效"


def test_redact_leaves_text_without_known_secrets_untouched() -> None:
    assert redact("普通错误", ["ntn_12345"]) == "普通错误"
    assert redact("普通错误", []) == "普通错误"
