"""最小化的飞书自定义机器人 Webhook 客户端。"""

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

_WEBHOOK_HOSTS = frozenset({"open.feishu.cn", "open.larksuite.com"})
_MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True)
class NotificationCard:
    title: str
    stage: str
    summary: str
    links: dict[str, str]


class FeishuWebhookClient:
    def __init__(
        self,
        webhook_url: str,
        *,
        http: httpx.AsyncClient,
        signing_secret: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        _validate_webhook(webhook_url)
        self.webhook_url = webhook_url
        self.http = http
        self.signing_secret = signing_secret
        self.clock = clock

    async def send(self, card: NotificationCard) -> None:
        payload = _payload(card)
        if self.signing_secret:
            timestamp = str(int(self.clock()))
            signing_key = f"{timestamp}\n{self.signing_secret}".encode()
            digest = hmac.new(signing_key, digestmod=hashlib.sha256).digest()
            payload.update(timestamp=timestamp, sign=base64.b64encode(digest).decode())
        async with self.http.stream("POST", self.webhook_url, json=payload) as response:
            body = await _bounded_body(response)
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("飞书 Webhook 响应格式无效") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("飞书 Webhook 响应格式无效")
        if not response.is_success or decoded.get("code") != 0:
            raise RuntimeError(f"飞书 Webhook 发送失败（HTTP {response.status_code}）")


async def _bounded_body(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > _MAX_RESPONSE_BYTES:
            raise RuntimeError("飞书 Webhook 响应超过大小限制")
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_webhook(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _WEBHOOK_HOSTS
        or not parsed.path.startswith("/open-apis/bot/v2/hook/")
    ):
        raise ValueError("飞书 Webhook URL 无效")


def _safe_links(links: dict[str, str]) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    for label, url in links.items():
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            continue
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": label[:40]},
                "url": url,
                "type": "default",
            }
        )
    return actions


def _payload(card: NotificationCard) -> dict[str, object]:
    elements: list[dict[str, object]] = [
        {
            "tag": "markdown",
            "content": f"**当前阶段：** {card.stage[:80]}\n{card.summary[:500]}",
        }
    ]
    actions = _safe_links(card.links)
    if actions:
        elements.append({"tag": "action", "actions": actions})
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": card.title[:120]},
            },
            "elements": elements,
        },
    }
