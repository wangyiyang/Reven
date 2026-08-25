"""腾讯云机器翻译（TMT）客户端与连接测试，TC3-HMAC-SHA256 签名。"""

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

import httpx

from reven.integrations.service import ConnectionTestResult, register_connection_test_adapter
from reven.integrations.translation import TranslationError

TENCENT_TMT_BASE_URL = "https://tmt.tencentcloudapi.com"
TENCENT_TMT_HOST = "tmt.tencentcloudapi.com"
_TMT_SERVICE = "tmt"
_TMT_VERSION = "2018-03-21"
_TMT_REGION = "ap-guangzhou"
_CONTENT_TYPE = "application/json; charset=utf-8"
_SIGNED_HEADERS = "content-type;host;x-tc-action"


class TencentTranslateClient:
    def __init__(self, secret_id: str, secret_key: str, *, http: httpx.AsyncClient) -> None:
        self._secret_id = secret_id
        self._secret_key = secret_key
        self._http = http

    async def translate(self, text: str, *, source: str = "en", target: str = "zh") -> str:
        payload = json.dumps(
            {"SourceText": text, "Source": source, "Target": target, "ProjectId": 0},
            ensure_ascii=False,
        )
        timestamp = int(time.time())
        headers = {
            "Authorization": _authorization(self._secret_id, self._secret_key, payload, timestamp),
            "Content-Type": _CONTENT_TYPE,
            "Host": TENCENT_TMT_HOST,
            "X-TC-Action": "TextTranslate",
            "X-TC-Version": _TMT_VERSION,
            "X-TC-Region": _TMT_REGION,
            "X-TC-Timestamp": str(timestamp),
        }
        try:
            response = await self._http.post("/", content=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise TranslationError(f"腾讯翻译请求失败（{type(exc).__name__}）") from exc
        if response.status_code != 200:
            raise TranslationError(f"腾讯翻译请求失败（HTTP {response.status_code}）")
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise TranslationError("腾讯翻译响应不是有效 JSON") from exc
        result = body.get("Response") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            raise TranslationError("腾讯翻译响应格式无效")
        error = result.get("Error")
        if isinstance(error, dict):
            raise TranslationError(f"腾讯翻译返回错误（{error.get('Code', 'Unknown')}）")
        translated = result.get("TargetText")
        if not isinstance(translated, str) or not translated:
            raise TranslationError("腾讯翻译响应缺少译文")
        return translated


def _authorization(secret_id: str, secret_key: str, payload: str, timestamp: int) -> str:
    algorithm = "TC3-HMAC-SHA256"
    canonical_headers = f"content-type:{_CONTENT_TYPE}\nhost:{TENCENT_TMT_HOST}\nx-tc-action:texttranslate\n"
    canonical_request = (
        f"POST\n/\n\n{canonical_headers}\n{_SIGNED_HEADERS}\n{hashlib.sha256(payload.encode()).hexdigest()}"
    )
    date = datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d")
    credential_scope = f"{date}/{_TMT_SERVICE}/tc3_request"
    string_to_sign = (
        f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )
    secret_date = hmac.new(f"TC3{secret_key}".encode(), date.encode(), hashlib.sha256).digest()
    secret_service = hmac.new(secret_date, _TMT_SERVICE.encode(), hashlib.sha256).digest()
    secret_signing = hmac.new(secret_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
    credential = f"Credential={secret_id}/{credential_scope}"
    return f"{algorithm} {credential}, SignedHeaders={_SIGNED_HEADERS}, Signature={signature}"


async def test_tencent_translation(
    public_config: dict[str, object],
    secrets: dict[str, str] | None,
) -> ConnectionTestResult:
    del public_config
    secret_id = secrets.get("secret_id") if secrets else None
    secret_key = secrets.get("secret_key") if secrets else None
    if not secret_id or not secret_key:
        return ConnectionTestResult(False, "腾讯翻译 Secret 尚未配置")
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(base_url=TENCENT_TMT_BASE_URL, timeout=10, trust_env=False) as http:
            await TencentTranslateClient(secret_id, secret_key, http=http).translate("hello")
    except TranslationError as exc:
        return ConnectionTestResult(False, str(exc))
    except Exception as exc:
        return ConnectionTestResult(False, f"腾讯翻译连接失败（{type(exc).__name__}）")
    return ConnectionTestResult(True, latency_ms=int((time.monotonic() - started) * 1000))


def register_tencent_adapter() -> None:
    register_connection_test_adapter("translate_tencent", test_tencent_translation)
