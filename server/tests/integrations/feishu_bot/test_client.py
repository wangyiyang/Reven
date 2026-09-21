import json

import httpx
import pytest
import respx
from reven.integrations.feishu_bot.client import MESSAGES_URL, TENANT_TOKEN_URL, FeishuBotApiClient, FeishuBotApiError


def _mock_token(router: respx.MockRouter) -> None:
    router.post(TENANT_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"code": 0, "tenant_access_token": "token"})
    )


@pytest.mark.anyio
async def test_review_card_and_text_use_same_message_api_and_token() -> None:
    card = {"header": {"title": {"tag": "plain_text", "content": "审核"}}, "elements": []}
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        message = router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"code": 0}))
        client = FeishuBotApiClient("cli_test", "secret")
        await client.send_review_card("ou_owner", card)
        await client.send_text("ou_owner", "通知")
        assert len(router.calls) == 3
    payloads = [json.loads(call.request.content) for call in message.calls]
    assert payloads[0]["msg_type"] == "interactive"
    assert json.loads(payloads[0]["content"]) == card
    assert payloads[1]["msg_type"] == "text"
    assert json.loads(payloads[1]["content"]) == {"text": "通知"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json secret token"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"code": "secret token"}),
        httpx.Response(200, json={"code": False}),
        httpx.Response(200, content=b"x" * (64 * 1024 + 1)),
        httpx.Response(503, json={"code": 0, "msg": "secret token"}),
    ],
)
async def test_malformed_or_failed_response_is_explicit_and_redacted(response: httpx.Response) -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        router.post(MESSAGES_URL).mock(return_value=response)
        with pytest.raises(FeishuBotApiError) as caught:
            await FeishuBotApiClient("cli_test", "secret").send_text("ou_owner", "通知")

    assert "secret" not in str(caught.value)
    assert "token" not in str(caught.value)


@pytest.mark.anyio
async def test_missing_token_is_rejected() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(TENANT_TOKEN_URL).mock(return_value=httpx.Response(200, json={"code": 0}))
        with pytest.raises(FeishuBotApiError, match="凭证无效"):
            await FeishuBotApiClient("cli_test", "secret").send_text("ou_owner", "通知")
