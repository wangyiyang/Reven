import json

import httpx
import pytest
import respx
from reven.integrations.feishu_bot.client import (
    BOT_INFO_URL,
    MESSAGES_URL,
    TENANT_TOKEN_URL,
    FeishuBotApiClient,
    FeishuBotApiError,
)


def _mock_token(router: respx.MockRouter) -> None:
    router.post(TENANT_TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"code": 0, "tenant_access_token": "token"})
    )


@pytest.mark.anyio
async def test_text_message_uses_message_api_and_token() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        message = router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"code": 0}))
        client = FeishuBotApiClient("cli_test", "secret")
        await client.send_text("ou_owner", "通知")
        assert len(router.calls) == 2
    payload = json.loads(message.calls[0].request.content)
    assert message.calls[0].request.headers["authorization"] == "Bearer token"
    assert payload["msg_type"] == "text"
    assert json.loads(payload["content"]) == {"text": "通知"}


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


@pytest.mark.anyio
async def test_markdown_message_sends_interactive_card() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        message = router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"code": 0}))
        client = FeishuBotApiClient("cli_test", "secret")
        await client.send_markdown("ou_owner", "**加粗**", title="标题")
        assert len(router.calls) == 2
    payload = json.loads(message.calls[0].request.content)
    assert payload["msg_type"] == "interactive"
    card = json.loads(payload["content"])
    assert card["schema"] == "2.0"
    assert card["header"] == {"title": {"tag": "plain_text", "content": "标题"}}
    assert card["body"]["elements"] == [{"tag": "markdown", "content": "**加粗**"}]


@pytest.mark.anyio
async def test_markdown_message_falls_back_to_text_when_card_fails() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        message = router.post(MESSAGES_URL).mock(
            side_effect=[
                httpx.Response(200, json={"code": 230027}),
                httpx.Response(200, json={"code": 0}),
            ]
        )
        client = FeishuBotApiClient("cli_test", "secret")
        await client.send_markdown("ou_owner", "**加粗**", fallback_text="加粗")

    card_payload = json.loads(message.calls[0].request.content)
    text_payload = json.loads(message.calls[1].request.content)
    assert card_payload["msg_type"] == "interactive"
    assert text_payload["msg_type"] == "text"
    assert json.loads(text_payload["content"]) == {"text": "加粗"}


@pytest.mark.anyio
async def test_markdown_message_raises_when_card_and_text_both_fail() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"code": 230027}))
        client = FeishuBotApiClient("cli_test", "secret")
        with pytest.raises(FeishuBotApiError, match="code=230027"):
            await client.send_markdown("ou_owner", "**加粗**")


@pytest.mark.anyio
async def test_get_bot_open_id_parses_bot_payload() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        router.get(BOT_INFO_URL).mock(return_value=httpx.Response(200, json={"code": 0, "bot": {"open_id": "ou_bot"}}))
        client = FeishuBotApiClient("cli_test", "secret")

        assert await client.get_bot_open_id() == "ou_bot"
        assert len(router.calls) == 2


@pytest.mark.anyio
async def test_chat_markdown_uses_chat_id_receive_type() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        message = router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"code": 0}))
        client = FeishuBotApiClient("cli_test", "secret")
        await client.send_markdown_to_chat("oc_group", "正文", title="标题")

    request = message.calls[0].request
    assert request.url.params["receive_id_type"] == "chat_id"
    payload = json.loads(request.content)
    assert payload["receive_id"] == "oc_group"
    assert payload["msg_type"] == "interactive"


@pytest.mark.anyio
async def test_chat_markdown_falls_back_to_text_when_card_fails() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        message = router.post(MESSAGES_URL).mock(
            side_effect=[
                httpx.Response(200, json={"code": 230027}),
                httpx.Response(200, json={"code": 0}),
            ]
        )
        client = FeishuBotApiClient("cli_test", "secret")
        await client.send_markdown_to_chat("oc_group", "**加粗**", fallback_text="加粗")

    text_payload = json.loads(message.calls[1].request.content)
    assert text_payload["msg_type"] == "text"
    assert json.loads(text_payload["content"]) == {"text": "加粗"}


@pytest.mark.anyio
async def test_chat_markdown_raises_when_chat_unreachable() -> None:
    """会话不可达（如机器人不在群内）：卡片与纯文本都失败，错误照常抛给调用方降级。"""
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json={"code": 230002}))
        client = FeishuBotApiClient("cli_test", "secret")
        with pytest.raises(FeishuBotApiError, match="code=230002"):
            await client.send_markdown_to_chat("oc_group", "正文")


@pytest.mark.anyio
async def test_get_bot_open_id_error_is_explicit_and_redacted() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        router.get(BOT_INFO_URL).mock(return_value=httpx.Response(200, json={"code": 403, "msg": "secret token"}))
        with pytest.raises(FeishuBotApiError) as caught:
            await FeishuBotApiClient("cli_test", "secret").get_bot_open_id()

    assert "secret" not in str(caught.value)
    assert "token" not in str(caught.value)


@pytest.mark.anyio
@pytest.mark.parametrize("payload", [{"code": 0, "bot": {}}, {"code": 0}, {"code": 0, "bot": {"open_id": 1}}])
async def test_get_bot_open_id_malformed_payload_is_rejected(payload: dict) -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        router.get(BOT_INFO_URL).mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(FeishuBotApiError, match="格式无效"):
            await FeishuBotApiClient("cli_test", "secret").get_bot_open_id()
