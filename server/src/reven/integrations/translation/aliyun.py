"""阿里云机器翻译客户端与连接测试，RPC 风格公共参数 + HMAC-SHA1 签名。"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

import httpx

from reven.integrations.service import ConnectionTestResult
from reven.integrations.translation import TranslationError

ALIYUN_MT_BASE_URL = "https://mt.cn-hangzhou.aliyuncs.com"
_MT_VERSION = "2018-10-12"


class AliyunTranslateClient:
    def __init__(self, access_key_id: str, access_key_secret: str, *, http: httpx.AsyncClient) -> None:
        self._access_key_id = access_key_id
        self._access_key_secret = access_key_secret
        self._http = http

    async def translate(self, text: str, *, source: str = "en", target: str = "zh") -> str:
        params = {
            "Action": "TranslateGeneral",
            "FormatType": "text",
            "SourceLanguage": source,
            "TargetLanguage": target,
            "SourceText": text,
            "Version": _MT_VERSION,
            "Format": "JSON",
            "AccessKeyId": self._access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureVersion": "1.0",
            "SignatureNonce": uuid.uuid4().hex,
            "Timestamp": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "RegionId": "cn-hangzhou",
        }
        params["Signature"] = _signature(self._access_key_secret, params)
        try:
            response = await self._http.get("/", params=params)
        except httpx.HTTPError as exc:
            raise TranslationError(f"阿里翻译请求失败（{type(exc).__name__}）") from exc
        if response.status_code != 200:
            raise TranslationError(f"阿里翻译请求失败（HTTP {response.status_code}）")
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise TranslationError("阿里翻译响应不是有效 JSON") from exc
        if not isinstance(body, dict):
            raise TranslationError("阿里翻译响应格式无效")
        code = body.get("Code")
        if code != "200":
            raise TranslationError(f"阿里翻译返回错误（{code}）")
        data = body.get("Data")
        translated = data.get("Translated") if isinstance(data, dict) else None
        if not isinstance(translated, str) or not translated:
            raise TranslationError("阿里翻译响应缺少译文")
        return translated


def _percent_encode(value: str) -> str:
    return quote(str(value), safe="~").replace("+", "%20").replace("*", "%2A").replace("%7E", "~")


def _signature(access_key_secret: str, params: dict[str, str]) -> str:
    canonicalized = "&".join(
        f"{_percent_encode(key)}={_percent_encode(value)}" for key, value in sorted(params.items())
    )
    string_to_sign = f"GET&%2F&{_percent_encode(canonicalized)}"
    digest = hmac.new(f"{access_key_secret}&".encode(), string_to_sign.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


async def test_aliyun_translation(
    public_config: dict[str, object],
    secrets: dict[str, str] | None,
) -> ConnectionTestResult:
    del public_config
    access_key_id = secrets.get("access_key_id") if secrets else None
    access_key_secret = secrets.get("access_key_secret") if secrets else None
    if not access_key_id or not access_key_secret:
        return ConnectionTestResult(False, "阿里翻译 Secret 尚未配置")
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(base_url=ALIYUN_MT_BASE_URL, timeout=10, trust_env=False) as http:
            await AliyunTranslateClient(access_key_id, access_key_secret, http=http).translate("hello")
    except TranslationError as exc:
        return ConnectionTestResult(False, str(exc))
    except Exception as exc:
        return ConnectionTestResult(False, f"阿里翻译连接失败（{type(exc).__name__}）")
    return ConnectionTestResult(True, latency_ms=int((time.monotonic() - started) * 1000))
