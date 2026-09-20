"""飞书应用（机器人）集成的显式连接测试：验证凭证可换取 tenant_access_token 并拉取 bot 信息。"""

import httpx

from reven.integrations.service import ConnectionTestResult, register_connection_test_adapter

TENANT_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
BOT_INFO_URL = "https://open.feishu.cn/open-apis/bot/v1/info"


async def test_feishu_bot_connection(
    public_config: dict[str, object],
    secrets: dict[str, str] | None,
) -> ConnectionTestResult:
    del public_config
    app_id = secrets.get("app_id") if secrets else None
    app_secret = secrets.get("app_secret") if secrets else None
    if not app_id or not app_secret:
        return ConnectionTestResult(False, "飞书应用凭证尚未配置")
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as http:
            response = await http.post(TENANT_TOKEN_URL, json={"app_id": app_id, "app_secret": app_secret})
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("code") != 0:
                return ConnectionTestResult(False, "飞书应用凭证无效")
            token = payload.get("tenant_access_token")
            if not isinstance(token, str) or not token:
                return ConnectionTestResult(False, "飞书应用凭证无效")
            bot_response = await http.get(BOT_INFO_URL, headers={"Authorization": f"Bearer {token}"})
            bot_response.raise_for_status()
            bot_payload = bot_response.json()
    except Exception as exc:
        return ConnectionTestResult(False, f"飞书应用连接失败（{type(exc).__name__}）")
    if not isinstance(bot_payload, dict) or bot_payload.get("code") != 0:
        return ConnectionTestResult(False, "飞书机器人信息获取失败（请确认已开通机器人能力）")
    return ConnectionTestResult(True)


def register_feishu_bot_adapter() -> None:
    register_connection_test_adapter("feishu_bot", test_feishu_bot_connection)
