import json

import httpx
import pytest
import respx
from reven.integrations.feishu_bot.client import BOT_INFO_URL, MESSAGES_URL, TENANT_TOKEN_URL
from reven.integrations.feishu_bot.service import test_feishu_bot_connection as feishu_bot_connection

SECRETS = {"app_id": "cli_test", "app_secret": "s3cret-value"}
CONFIG = {"whitelist_open_ids": ["ou_first", "ou_second"], "enabled": False}


def _mock_auth(router: respx.MockRouter) -> None:
    router.post(TENANT_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"code": 0, "tenant_access_token": "t-token", "expire": 7200})
    )
    router.get(BOT_INFO_URL).mock(return_value=httpx.Response(200, json={"code": 0}))


@pytest.mark.anyio
@pytest.mark.parametrize("secret", [None, {"app_id": "cli_test"}])
async def test_reports_not_configured_without_complete_secrets(secret: dict[str, str] | None) -> None:
    result = await feishu_bot_connection(CONFIG, secret)

    assert result.success is False
    assert result.message == "飞书应用凭证尚未配置"


@pytest.mark.anyio
@pytest.mark.parametrize("recipients", [None, [], ["", "   "]])
async def test_requires_recipients_before_contacting_feishu(recipients: object) -> None:
    with respx.mock(assert_all_called=True):
        result = await feishu_bot_connection({"whitelist_open_ids": recipients}, SECRETS)

    assert result.success is False
    assert result.message == "请先配置通知接收人 Open ID"


@pytest.mark.anyio
async def test_rejects_invalid_credentials() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(TENANT_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"code": 99991663, "msg": "s3cret-value"})
        )
        result = await feishu_bot_connection(CONFIG, SECRETS)

    assert result.success is False
    assert result.message == "飞书应用凭证无效（code=99991663）"


@pytest.mark.anyio
async def test_sends_to_all_recipients_even_when_config_disabled() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_auth(router)
        message = router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"code": 0}))
        result = await feishu_bot_connection(CONFIG, SECRETS)

    assert result.success is True
    assert [json.loads(call.request.content)["receive_id"] for call in message.calls] == ["ou_first", "ou_second"]
    for call in message.calls:
        payload = json.loads(call.request.content)
        assert payload["msg_type"] == "text"
        assert "Reven 测试通知" in json.loads(payload["content"])["text"]
        assert call.request.url.params["receive_id_type"] == "open_id"
        assert call.request.headers["Authorization"] == "Bearer t-token"


@pytest.mark.anyio
async def test_reports_missing_bot_capability_without_sending() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(TENANT_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"code": 0, "tenant_access_token": "t-token"})
        )
        router.get(BOT_INFO_URL).mock(return_value=httpx.Response(200, json={"code": 11205, "msg": "s3cret-value"}))
        result = await feishu_bot_connection(CONFIG, SECRETS)

    assert result.success is False
    assert result.message == "飞书机器人信息获取失败（请确认已开通并发布机器人能力）（code=11205）"


@pytest.mark.anyio
async def test_partial_permission_failure_reports_failure_and_still_attempts_remaining_recipients() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_auth(router)
        message = router.post(MESSAGES_URL).mock(
            side_effect=[
                httpx.Response(400, json={"code": 99991672, "msg": "s3cret-value t-token"}),
                httpx.Response(200, json={"code": 0}),
            ]
        )
        result = await feishu_bot_connection(CONFIG, SECRETS)

    assert message.call_count == 2
    assert result.success is False
    assert "im:message:send_as_bot" in (result.message or "")
    assert "已发送 1/2" in (result.message or "")
    assert "s3cret-value" not in (result.message or "")
    assert "t-token" not in (result.message or "")


@pytest.mark.anyio
async def test_network_failure_hides_exception_details() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(TENANT_TOKEN_URL).mock(side_effect=httpx.ConnectError("s3cret-value 泄露"))
        result = await feishu_bot_connection(CONFIG, SECRETS)

    assert result.success is False
    assert result.message == "飞书应用连接失败（ConnectError）"
