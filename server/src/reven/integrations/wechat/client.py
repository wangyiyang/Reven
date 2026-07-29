import asyncio
import json
import math
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from reven.integrations.wechat.models import (
    WeChatBlockedError,
    WeChatPermanentError,
    WeChatTransientError,
)

TOKEN_REFRESH_MARGIN = 300
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
REQUEST_TIMEOUT = httpx.Timeout(30)
TOKEN_INVALID_CODES = {40014, 42001}
BLOCKED_CODES = {
    40001,
    40013,
    40125,
    40164,
    48001,
    48002,
    50001,
}
TRANSIENT_CODES = {-1, 45009}


class WeChatClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        http: httpx.AsyncClient,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if http.base_url.scheme != "https":
            raise ValueError("WeChatClient 仅允许 HTTPS base URL")
        self._app_id = app_id
        self._app_secret = app_secret
        self._http = http
        self._monotonic = monotonic
        self._token: str | None = None
        self._token_refresh_at = 0.0
        self._token_lock = asyncio.Lock()

    async def get_token(self, *, force_refresh: bool = False) -> str:
        if not force_refresh and self._token_valid():
            return self._token or ""
        async with self._token_lock:
            if not force_refresh and self._token_valid():
                return self._token or ""
            payload = await self._raw_request(
                "GET",
                "/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": self._app_id,
                    "secret": self._app_secret,
                },
            )
            token = payload.get("access_token")
            expires_in = payload.get("expires_in")
            if not isinstance(token, str) or not token or not _valid_expiry(expires_in):
                raise WeChatTransientError("invalid_token_response", "微信 Token 响应无效")
            assert isinstance(expires_in, (int, float))
            self._token = token
            self._token_refresh_at = self._monotonic() + max(float(expires_in) - TOKEN_REFRESH_MARGIN, 0)
            return token

    async def upload_body_image(self, path: Path) -> str:
        payload = await self._multipart("/cgi-bin/media/uploadimg", path)
        url = payload.get("url")
        if not isinstance(url, str) or not _valid_wechat_image_url(url):
            raise WeChatPermanentError("invalid_upload_response", "微信正文图片响应无效")
        return url

    async def upload_cover_material(self, path: Path) -> str:
        payload = await self._multipart("/cgi-bin/material/add_material", path, params={"type": "image"})
        media_id = payload.get("media_id")
        if not isinstance(media_id, str) or not media_id:
            raise WeChatPermanentError("invalid_material_response", "微信封面素材响应无效")
        return media_id

    async def create_draft(self, payload: dict[str, object]) -> str:
        response = await self._authenticated_request("POST", "/cgi-bin/draft/add", json=payload)
        media_id = response.get("media_id")
        if not isinstance(media_id, str) or not media_id:
            raise WeChatPermanentError("invalid_draft_response", "微信草稿响应无效")
        return media_id

    async def _multipart(
        self,
        path: str,
        image: Path,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        _validate_image_file(image)

        async def operation(token: str) -> dict[str, Any]:
            with image.open("rb") as stream:
                query = {"access_token": token, **(params or {})}
                return await self._raw_request(
                    "POST",
                    path,
                    params=query,
                    files={"media": (image.name, stream, _mime_for(image))},
                )

        return await self._with_token_replay(operation)

    async def _authenticated_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async def operation(token: str) -> dict[str, Any]:
            params = {"access_token": token, **kwargs.pop("params", {})}
            return await self._raw_request(method, path, params=params, **kwargs)

        return await self._with_token_replay(operation)

    async def _with_token_replay(
        self,
        operation: Callable[[str], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        token = await self.get_token()
        try:
            return await operation(token)
        except _InvalidTokenError:
            if self._token == token:
                self._token = None
            token = await self.get_token()
            try:
                return await operation(token)
            except _InvalidTokenError as exc:
                raise WeChatBlockedError(exc.code, "微信 Token 刷新后仍无效") from exc

    async def _raw_request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._http.request(method, path, timeout=REQUEST_TIMEOUT, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise WeChatTransientError("network_error", "微信网络请求失败") from exc
        if response.status_code >= 500:
            raise WeChatTransientError(f"http_{response.status_code}", "微信服务暂时不可用")
        if not response.is_success:
            error = WeChatBlockedError if response.status_code in (401, 403) else WeChatPermanentError
            raise error(f"http_{response.status_code}", "微信请求被拒绝")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise WeChatTransientError("response_too_large", "微信响应超过大小限制")
        try:
            payload: Any = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WeChatTransientError("invalid_json", "微信响应格式无效") from exc
        if not isinstance(payload, dict):
            raise WeChatTransientError("invalid_json", "微信响应格式无效")
        _raise_business_error(payload)
        return payload

    def _token_valid(self) -> bool:
        return self._token is not None and self._monotonic() < self._token_refresh_at


class _InvalidTokenError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _raise_business_error(payload: dict[str, Any]) -> None:
    code = payload.get("errcode")
    if code in (None, 0):
        return
    normalized = str(code) if isinstance(code, int) else "invalid_errcode"
    if code in TOKEN_INVALID_CODES:
        raise _InvalidTokenError(normalized)
    if code in BLOCKED_CODES:
        raise WeChatBlockedError(normalized, "微信配置、IP 白名单或接口权限无效")
    if code in TRANSIENT_CODES:
        raise WeChatTransientError(normalized, "微信接口限流或暂时不可用")
    raise WeChatPermanentError(normalized, "微信请求参数或业务状态无效")


def _valid_expiry(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _validate_image_file(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise WeChatPermanentError("image_unreadable", "微信图片文件不可读取") from exc
    if not path.is_file() or path.is_symlink() or size <= 0 or size > MAX_IMAGE_BYTES:
        raise WeChatPermanentError("image_invalid", "微信图片文件无效或超过限制")
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        raise WeChatPermanentError("image_format_invalid", "微信图片格式不受支持")


def _mime_for(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }[path.suffix.lower()]


def _valid_wechat_image_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and parsed.username is None and parsed.password is None
