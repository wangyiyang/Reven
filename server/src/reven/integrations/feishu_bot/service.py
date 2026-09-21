"""显式测试飞书应用：验证凭证及机器人能力，并真实发送测试通知。"""

from reven.integrations.feishu_bot.client import FeishuBotApiClient, FeishuBotApiError
from reven.integrations.feishu_bot.config import parse_whitelist
from reven.integrations.service import ConnectionTestResult, register_connection_test_adapter


async def test_feishu_bot_connection(
    public_config: dict[str, object],
    secrets: dict[str, str] | None,
) -> ConnectionTestResult:
    app_id = secrets.get("app_id") if secrets else None
    app_secret = secrets.get("app_secret") if secrets else None
    if not app_id or not app_secret:
        return ConnectionTestResult(False, "飞书应用凭证尚未配置")
    recipients = parse_whitelist(public_config.get("whitelist_open_ids"))
    if not recipients:
        return ConnectionTestResult(False, "请先配置通知接收人 Open ID")
    try:
        client = FeishuBotApiClient(app_id, app_secret)
        await client.verify_bot()
        await client.send_text_to_recipients(recipients, "Reven 测试通知\n应用机器人消息发送正常。")
    except FeishuBotApiError as exc:
        return ConnectionTestResult(False, str(exc))
    except Exception as exc:
        return ConnectionTestResult(False, f"飞书应用测试失败（{type(exc).__name__}）")
    return ConnectionTestResult(True)


def register_feishu_bot_adapter() -> None:
    register_connection_test_adapter("feishu_bot", test_feishu_bot_connection)
