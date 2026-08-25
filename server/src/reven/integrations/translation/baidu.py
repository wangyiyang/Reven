"""百度翻译客户端与连接测试，MD5(appid+q+salt+密钥) 签名。"""

import hashlib
import json
import secrets as secrets_module
import time

import httpx

from reven.integrations.service import ConnectionTestResult, register_connection_test_adapter
from reven.integrations.translation import TranslationError

BAIDU_TRANSLATE_BASE_URL = "https://fanyi-api.baidu.com"


class BaiduTranslateClient:
    def __init__(self, app_id: str, app_key: str, *, http: httpx.AsyncClient) -> None:
        self._app_id = app_id
        self._app_key = app_key
        self._http = http

    async def translate(self, text: str, *, source: str = "en", target: str = "zh") -> str:
        salt = secrets_module.token_hex(8)
        sign = hashlib.md5(f"{self._app_id}{text}{salt}{self._app_key}".encode()).hexdigest()
        params = {"q": text, "from": source, "to": target, "appid": self._app_id, "salt": salt, "sign": sign}
        try:
            response = await self._http.get("/api/trans/vip/translate", params=params)
        except httpx.HTTPError as exc:
            raise TranslationError(f"百度翻译请求失败（{type(exc).__name__}）") from exc
        if response.status_code != 200:
            raise TranslationError(f"百度翻译请求失败（HTTP {response.status_code}）")
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise TranslationError("百度翻译响应不是有效 JSON") from exc
        if not isinstance(body, dict):
            raise TranslationError("百度翻译响应格式无效")
        error_code = body.get("error_code")
        if error_code is not None:
            raise TranslationError(f"百度翻译返回错误（{error_code}）")
        trans_result = body.get("trans_result")
        if not isinstance(trans_result, list) or not trans_result:
            raise TranslationError("百度翻译响应缺少译文")
        first = trans_result[0]
        translated = first.get("dst") if isinstance(first, dict) else None
        if not isinstance(translated, str) or not translated:
            raise TranslationError("百度翻译响应缺少译文")
        return translated


async def test_baidu_translation(
    public_config: dict[str, object],
    secrets: dict[str, str] | None,
) -> ConnectionTestResult:
    del public_config
    app_id = secrets.get("app_id") if secrets else None
    app_key = secrets.get("app_key") if secrets else None
    if not app_id or not app_key:
        return ConnectionTestResult(False, "百度翻译 Secret 尚未配置")
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(base_url=BAIDU_TRANSLATE_BASE_URL, timeout=10, trust_env=False) as http:
            await BaiduTranslateClient(app_id, app_key, http=http).translate("hello")
    except TranslationError as exc:
        return ConnectionTestResult(False, str(exc))
    except Exception as exc:
        return ConnectionTestResult(False, f"百度翻译连接失败（{type(exc).__name__}）")
    return ConnectionTestResult(True, latency_ms=int((time.monotonic() - started) * 1000))


def register_baidu_adapter() -> None:
    register_connection_test_adapter("translate_baidu", test_baidu_translation)
