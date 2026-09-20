import httpx
import pytest
import respx
from reven.integrations.feishu_bot.service import test_feishu_bot_connection as feishu_bot_connection

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
BOT_INFO_URL = "https://open.feishu.cn/open-apis/bot/v1/info"
SECRETS = {"app_id": "cli_a1b2c3d4e5", "app_secret": "s3cret-value"}


@pytest.mark.anyio
async def test_reports_not_configured_without_secrets() -> None:
    result = await feishu_bot_connection({}, None)

    assert result.success is False
    assert result.message == "飞书应用凭证尚未配置"


@pytest.mark.anyio
async def test_reports_not_configured_with_incomplete_secrets() -> None:
    result = await feishu_bot_connection({}, {"app_id": "cli_a1b2c3d4e5"})

    assert result.success is False
    assert result.message == "飞书应用凭证尚未配置"


@pytest.mark.anyio
async def test_rejects_invalid_credentials() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"code": 99991663, "msg": "bad credentials"}))
        result = await feishu_bot_connection({}, SECRETS)

    assert result.success is False
    assert result.message == "飞书应用凭证无效"


@pytest.mark.anyio
async def test_succeeds_when_tenant_token_issued() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"code": 0, "tenant_access_token": "t-token"})
        )
        bot_request = router.get(BOT_INFO_URL).mock(
            return_value=httpx.Response(200, json={"code": 0, "bot": {"app_name": "Reven"}})
        )
        result = await feishu_bot_connection({}, SECRETS)

    assert result.success is True
    assert bot_request.calls[0].request.headers["Authorization"] == "Bearer t-token"


@pytest.mark.anyio
async def test_reports_bot_capability_missing_when_bot_info_fails() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"code": 0, "tenant_access_token": "t-token"})
        )
        router.get(BOT_INFO_URL).mock(return_value=httpx.Response(200, json={"code": 99991672, "msg": "no bot"}))
        result = await feishu_bot_connection({}, SECRETS)

    assert result.success is False
    assert result.message == "飞书机器人信息获取失败（请确认已开通机器人能力）"
    assert "s3cret-value" not in (result.message or "")


@pytest.mark.anyio
async def test_network_failure_hides_exception_details() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("s3cret-value 泄露"))
        result = await feishu_bot_connection({}, SECRETS)

    assert result.success is False
    assert result.message == "飞书应用连接失败（ConnectError）"
    assert "s3cret-value" not in (result.message or "")
