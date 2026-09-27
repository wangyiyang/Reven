"""飞书应用 API：通知消息发送共用鉴权与脱敏错误处理。"""

import json
import time
from typing import Any

import httpx

TENANT_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
BOT_INFO_URL = "https://open.feishu.cn/open-apis/bot/v3/info"
MESSAGES_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
_MAX_RESPONSE_BYTES = 64 * 1024


class FeishuBotApiError(Exception):
    """只包含固定提示和数字错误码，不暴露响应正文、凭证或令牌。"""


class FeishuBotApiClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        *,
        http: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._http = http
        self._transport = transport
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def _tenant_token(self) -> str:
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return self._token
        payload = await self._request(
            "POST",
            TENANT_TOKEN_URL,
            body={"app_id": self._app_id, "app_secret": self._app_secret},
            error="飞书应用凭证无效",
        )
        token = payload.get("tenant_access_token")
        if not isinstance(token, str) or not token:
            raise FeishuBotApiError("飞书应用凭证无效")
        self._token = token
        expire = payload.get("expire", 7200)
        self._token_expires_at = time.monotonic() + max(expire - 60, 0) if isinstance(expire, int) else 0
        return token

    async def verify_bot(self) -> None:
        await self._request(
            "GET",
            BOT_INFO_URL,
            token=await self._tenant_token(),
            error="飞书机器人信息获取失败（请确认已开通并发布机器人能力）",
        )

    async def get_bot_open_id(self) -> str:
        """获取机器人自身 open_id（群聊 @ 判定用）；复用 verify_bot 同一端点与 token 缓存。"""
        payload = await self._request(
            "GET",
            BOT_INFO_URL,
            token=await self._tenant_token(),
            error="飞书机器人信息获取失败（请确认已开通并发布机器人能力）",
        )
        bot = payload.get("bot")
        open_id = bot.get("open_id") if isinstance(bot, dict) else None
        if not isinstance(open_id, str) or not open_id:
            raise FeishuBotApiError("飞书机器人信息响应格式无效")
        return open_id

    async def send_text(self, open_id: str, text: str) -> None:
        await self._send_message(open_id, "text", {"text": text})

    async def send_text_to_recipients(self, recipients: tuple[str, ...], text: str) -> None:
        if not recipients:
            raise FeishuBotApiError("请先配置通知接收人 Open ID")
        failures: list[FeishuBotApiError] = []
        for open_id in recipients:
            try:
                await self.send_text(open_id, text)
            except FeishuBotApiError as exc:
                failures.append(exc)
        if failures:
            delivered = len(recipients) - len(failures)
            raise FeishuBotApiError(f"{failures[0]}；已发送 {delivered}/{len(recipients)} 位接收人")

    async def _send_message(self, open_id: str, msg_type: str, content: dict[str, Any]) -> None:
        await self._request(
            "POST",
            f"{MESSAGES_URL}?receive_id_type=open_id",
            token=await self._tenant_token(),
            body={"receive_id": open_id, "msg_type": msg_type, "content": json.dumps(content, ensure_ascii=False)},
            error="飞书消息发送失败",
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        token: str | None = None,
        error: str,
    ) -> dict[str, Any]:
        # 注入的共享 client（ProviderClients 长驻实例）直接使用且不在这里关闭；
        # 否则按请求自建造 client，保持 timeout=10s / trust_env=False 策略不变。
        if self._http is not None:
            return await self._request_via(self._http, method, url, body=body, token=token, error=error)
        async with httpx.AsyncClient(timeout=10, trust_env=False, transport=self._transport) as http:
            return await self._request_via(http, method, url, body=body, token=token, error=error)

    async def _request_via(
        self,
        http: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None,
        token: str | None,
        error: str,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            async with http.stream(method, url, json=body, headers=headers) as response:
                payload = await _read_payload(response)
                code = payload.get("code")
                if type(code) is not int:
                    raise FeishuBotApiError("飞书应用响应格式无效")
                if code != 0:
                    if code in {99991672, 99991679} and url.startswith(MESSAGES_URL):
                        error = "飞书发消息权限不足，请开通 im:message:send_as_bot 并发布应用"
                    raise FeishuBotApiError(f"{error}（code={code}）")
                if not response.is_success:
                    raise FeishuBotApiError(f"{error}（HTTP {response.status_code}）")
                return payload
        except httpx.HTTPError as exc:
            raise FeishuBotApiError(f"飞书应用连接失败（{type(exc).__name__}）") from None


async def _read_payload(response: httpx.Response) -> dict[str, Any]:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise FeishuBotApiError("飞书应用响应超过大小限制")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise FeishuBotApiError("飞书应用响应格式无效") from None
    if not isinstance(payload, dict):
        raise FeishuBotApiError("飞书应用响应格式无效")
    return payload
