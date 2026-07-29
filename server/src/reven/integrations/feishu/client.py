"""最小化的飞书自定义机器人 Webhook 客户端。"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

_WEBHOOK_HOSTS = frozenset({"open.feishu.cn", "open.larksuite.com"})


@dataclass(frozen=True)
class NotificationCard:
    title: str
    stage: str
    summary: str
    links: dict[str, str]


class FeishuWebhookClient:
    def __init__(self, webhook_url: str, *, http: httpx.AsyncClient) -> None:
        _validate_webhook(webhook_url)
        self.webhook_url = webhook_url
        self.http = http

    async def send(self, card: NotificationCard) -> None:
        response = await self.http.post(self.webhook_url, json=_payload(card))
        try:
            decoded: Any = response.json()
        except ValueError as exc:
            raise RuntimeError("飞书 Webhook 响应格式无效") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("飞书 Webhook 响应格式无效")
        if not response.is_success or decoded.get("code") != 0:
            raise RuntimeError(f"飞书 Webhook 发送失败（HTTP {response.status_code}）")


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
