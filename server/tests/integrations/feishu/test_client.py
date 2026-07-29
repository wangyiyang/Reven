import json

import httpx
import pytest
from reven.integrations.feishu.client import FeishuWebhookClient, NotificationCard


@pytest.mark.anyio
async def test_sends_interactive_card_with_safe_links_only() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read()))
        return httpx.Response(200, json={"code": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as http:
        client = FeishuWebhookClient(
            "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            http=http,
        )
        await client.send(
            NotificationCard(
                title="稿件",
                stage="已完成",
                summary="博客已上线",
                links={
                    "Notion": "https://www.notion.so/page",
                    "危险": "javascript:alert(1)",
                },
            )
        )

    assert captured["msg_type"] == "interactive"
    payload = str(captured)
    assert "稿件" in payload
    assert "https://www.notion.so/page" in payload
    assert "javascript:" not in payload


@pytest.mark.anyio
async def test_rejects_failed_webhook_response_without_exposing_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"code": 19001, "msg": "secret response"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False) as http:
        client = FeishuWebhookClient(
            "https://open.feishu.cn/open-apis/bot/v2/hook/test",
            http=http,
        )
        with pytest.raises(RuntimeError, match="飞书 Webhook"):
            await client.send(NotificationCard("稿件", "失败", "需要处理", {}))
