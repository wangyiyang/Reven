"""飞书集成的显式连接测试。"""

import httpx

from reven.integrations.feishu.client import FeishuWebhookClient, NotificationCard
from reven.integrations.service import ConnectionTestResult, register_connection_test_adapter


async def test_feishu_connection(
    public_config: dict[str, object],
    secrets: dict[str, str] | None,
) -> ConnectionTestResult:
    del public_config
    webhook_url = secrets.get("webhook_url") if secrets else None
    if not webhook_url:
        return ConnectionTestResult(False, "飞书 Webhook 尚未配置")
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as http:
            await FeishuWebhookClient(webhook_url, http=http).send(
                NotificationCard("Reven 连接测试", "连接正常", "飞书机器人已连接。", {})
            )
    except Exception as exc:
        return ConnectionTestResult(False, f"飞书连接失败（{type(exc).__name__}）")
    return ConnectionTestResult(True)


def register_feishu_adapter() -> None:
    register_connection_test_adapter("feishu", test_feishu_connection)
