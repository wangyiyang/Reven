import json
from urllib.parse import quote

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


TARGETS = [
    ("send_markdown", "ou_owner", "open_id"),
    ("send_markdown_to_chat", "oc_group", "chat_id"),
    ("reply_markdown", "om/引用?#", None),
]


def _message_route(router: respx.MockRouter) -> respx.Route:
    return router.post(url__startswith=MESSAGES_URL)


def _assert_target(request: httpx.Request, target: str, receive_type: str | None) -> dict:
    payload = json.loads(request.content)
    assert request.headers["authorization"] == "Bearer token"
    if receive_type is None:
        assert request.url.raw_path.decode() == f"/open-apis/im/v1/messages/{quote(target, safe='')}/reply"
        assert set(payload) == {"msg_type", "content"}
    else:
        assert request.url.params["receive_id_type"] == receive_type
        assert payload["receive_id"] == target
    return payload


@pytest.mark.anyio
@pytest.mark.parametrize(("method", "target", "receive_type"), TARGETS)
async def test_markdown_delivery_sends_one_card(method: str, target: str, receive_type: str | None) -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        message = _message_route(router).mock(return_value=httpx.Response(200, json={"code": 0}))
        await getattr(FeishuBotApiClient("cli_test", "secret"), method)(target, "**加粗**", title="标题")

    assert len(message.calls) == 1
    payload = _assert_target(message.calls[0].request, target, receive_type)
    assert payload["msg_type"] == "interactive"
    card = json.loads(payload["content"])
    assert card["schema"] == "2.0"
    assert card["header"] == {"title": {"tag": "plain_text", "content": "标题"}}
    assert card["body"]["elements"] == [{"tag": "markdown", "content": "**加粗**"}]


@pytest.mark.anyio
@pytest.mark.parametrize(("method", "target", "receive_type"), TARGETS)
@pytest.mark.parametrize(
    "card_failure",
    [
        httpx.Response(200, json={"code": 230027, "msg": "secret token"}),
        httpx.Response(503, json={"code": 0, "msg": "secret token"}),
        httpx.Response(200, content=b"invalid secret token"),
        httpx.ConnectError("secret token"),
        httpx.ReadTimeout("secret token"),
    ],
)
async def test_delivery_falls_back_on_same_target_preserving_content(
    method: str, target: str, receive_type: str | None, card_failure: httpx.Response | Exception
) -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        message = _message_route(router).mock(side_effect=[card_failure, httpx.Response(200, json={"code": 0})])
        await getattr(FeishuBotApiClient("cli_test", "secret"), method)(target, "**加粗**", title="标题")

    assert len(message.calls) == 2
    card = _assert_target(message.calls[0].request, target, receive_type)
    text = _assert_target(message.calls[1].request, target, receive_type)
    assert card["msg_type"] == "interactive"
    assert text["msg_type"] == "text"
    assert json.loads(text["content"]) == {"text": "标题\n**加粗**"}


@pytest.mark.anyio
@pytest.mark.parametrize(("method", "target", "receive_type"), TARGETS)
@pytest.mark.parametrize("failure", [httpx.Response(200, json={"code": 230027}), httpx.ReadTimeout("secret token")])
async def test_delivery_reports_two_failures_without_leaking_secrets(
    method: str, target: str, receive_type: str | None, failure: httpx.Response | Exception
) -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        message = _message_route(router).mock(side_effect=[failure, failure])
        with pytest.raises(FeishuBotApiError) as caught:
            await getattr(FeishuBotApiClient("cli_test", "secret"), method)(target, "正文")
    assert len(message.calls) == 2
    assert "secret" not in str(caught.value) and "token" not in str(caught.value)
    for call in message.calls:
        _assert_target(call.request, target, receive_type)


@pytest.mark.anyio
async def test_get_bot_open_id_parses_bot_payload() -> None:
    with respx.mock(assert_all_called=True) as router:
        _mock_token(router)
        router.get(BOT_INFO_URL).mock(return_value=httpx.Response(200, json={"code": 0, "bot": {"open_id": "ou_bot"}}))
        client = FeishuBotApiClient("cli_test", "secret")

        assert await client.get_bot_open_id() == "ou_bot"
        assert len(router.calls) == 2


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
