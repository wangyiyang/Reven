"""入站事件处理器测试：route_message 路由矩阵 + 分发投递 + 分发器注册回归。

事件全部用 dict 构造（SDK init() 反序列化）；bot_open_id 作为 build 参数注入，
DispatchRecorder 替身保证零网络。
"""

from typing import Any

import pytest
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1  # type: ignore[import-untyped]
from reven.integrations.feishu_bot.handlers import build_event_handler, build_message_handler

BOT_OPEN_ID = "ou_bot"
BOT_MENTION = {"key": "@_user_1", "id": {"open_id": BOT_OPEN_ID}, "name": "Reven"}
OTHER_MENTION = {"key": "@_user_1", "id": {"open_id": "ou_other"}, "name": "同事"}


def _message_event(
    *,
    sender_type: str = "user",
    sender_open_id: str | None = "ou_boss",
    chat_type: str = "p2p",
    message_id: str | None = "om_1",
    message_type: str = "text",
    content: str = '{"text":"hi"}',
    mentions: list[dict[str, Any]] | None = None,
) -> P2ImMessageReceiveV1:
    message: dict[str, Any] = {
        "message_id": message_id,
        "chat_id": "oc_1",
        "chat_type": chat_type,
        "message_type": message_type,
        "content": content,
        "create_time": 1,
    }
    if mentions is not None:
        message["mentions"] = mentions
    return P2ImMessageReceiveV1(
        {
            "event": {
                "sender": {"sender_id": {"open_id": sender_open_id}, "sender_type": sender_type, "tenant_key": "t"},
                "message": message,
            }
        }
    )


class DispatchRecorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    def submit(
        self,
        *,
        kind: str,
        message_id: str,
        chat_id: str,
        open_id: str,
        text: str,
    ) -> None:
        self.calls.append(
            {
                "kind": kind,
                "message_id": message_id,
                "chat_id": chat_id,
                "open_id": open_id,
                "text": text,
            }
        )
        if self._fail:
            raise RuntimeError("dispatch boom")


def _handler(dispatch: DispatchRecorder, bot_open_id: str | None = BOT_OPEN_ID) -> Any:
    return build_message_handler(dispatch, bot_open_id)  # type: ignore[arg-type]


# --- 私聊路由 ---


def test_private_text_message_dispatches_chat() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event())

    assert len(dispatch.calls) == 1
    call = dispatch.calls[0]
    assert call["kind"] == "chat"
    assert call["text"] == "hi"
    assert call["message_id"] == "om_1"
    assert call["chat_id"] == "oc_1"
    assert call["open_id"] == "ou_boss"
    assert set(call) == {"kind", "message_id", "chat_id", "open_id", "text"}


def test_private_non_text_message_dispatches_unsupported() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event(message_type="image", content='{"image_key":"img_1"}'))

    assert [call["kind"] for call in dispatch.calls] == ["unsupported"]


def test_private_malformed_content_dispatches_unsupported_without_crash() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event(content="not-json{"))

    assert [call["kind"] for call in dispatch.calls] == ["unsupported"]


# --- 群聊路由 ---


def test_group_message_without_mention_is_ignored() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event(chat_type="group"))

    assert dispatch.calls == []


def test_group_message_mentioning_other_is_ignored() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event(chat_type="group", content='{"text":"@_user_1 看这个"}', mentions=[OTHER_MENTION]))

    assert dispatch.calls == []


def test_group_message_is_ignored_when_bot_open_id_unknown() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch, bot_open_id=None)

    handler(_message_event(chat_type="group", content='{"text":"@_user_1 你好"}', mentions=[BOT_MENTION]))

    assert dispatch.calls == []  # open_id 获取失败降级：群聊一律忽略（私聊不受影响）


def test_group_mention_bot_strips_placeholder_and_dispatches_chat() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event(chat_type="group", content='{"text":"@_user_1 你好"}', mentions=[BOT_MENTION]))

    assert len(dispatch.calls) == 1
    call = dispatch.calls[0]
    assert call["kind"] == "chat"
    assert call["text"] == "你好"


def test_group_mention_bot_with_empty_text_dispatches_guide() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event(chat_type="group", content='{"text":"@_user_1"}', mentions=[BOT_MENTION]))

    assert [(call["kind"], call["text"]) for call in dispatch.calls] == [("guide", "")]


def test_group_mention_bot_with_non_text_dispatches_unsupported() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    event = _message_event(
        chat_type="group", message_type="sticker", content='{"file_key":"stk_1"}', mentions=[BOT_MENTION]
    )
    handler(event)

    assert [call["kind"] for call in dispatch.calls] == ["unsupported"]


def test_group_mention_bot_with_malformed_content_dispatches_unsupported() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event(chat_type="group", content="not-json{", mentions=[BOT_MENTION]))

    assert [call["kind"] for call in dispatch.calls] == ["unsupported"]


def test_unknown_chat_type_is_ignored() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event(chat_type="thread"))

    assert dispatch.calls == []


@pytest.mark.parametrize("content", [None, '"just-a-string"', "[1,2]", '{"text": 42}'])
def test_abnormal_content_payloads_dispatch_unsupported(content: str | None) -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event(content=content))  # type: ignore[arg-type]

    assert [call["kind"] for call in dispatch.calls] == ["unsupported"]


# --- 通用忽略与兜底 ---


@pytest.mark.parametrize("sender_type", ["app", "anonymous", "unknown"])
def test_ignores_non_user_sender_types(sender_type: str) -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event(sender_type=sender_type))

    assert dispatch.calls == []


def test_ignores_message_without_id() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event(message_id=None))

    assert dispatch.calls == []


def test_ignores_message_without_sender_open_id() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event(sender_open_id=None))

    assert dispatch.calls == []


def test_malformed_event_does_not_crash() -> None:
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(P2ImMessageReceiveV1({"event": {}}))

    assert dispatch.calls == []


def test_dispatch_failure_is_swallowed_and_logged() -> None:
    dispatch = DispatchRecorder(fail=True)
    handler = _handler(dispatch)

    handler(_message_event())  # 分发失败仅记日志，不向 SDK 抛出

    assert len(dispatch.calls) == 1


def test_route_failure_is_swallowed_and_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_route(sender: Any, message: Any, bot_open_id: str | None) -> Any:
        raise RuntimeError("route boom")

    monkeypatch.setattr("reven.integrations.feishu_bot.handlers.route_message", broken_route)
    dispatch = DispatchRecorder()
    handler = _handler(dispatch)

    handler(_message_event())  # 路由异常仅记日志，不向 SDK 抛出

    assert dispatch.calls == []


# --- 分发器注册回归 ---


def test_event_handler_registers_only_im_processor() -> None:
    handler = build_event_handler(bot_open_id=BOT_OPEN_ID, chat_dispatch=DispatchRecorder())  # type: ignore[arg-type]

    assert "p2.im.message.receive_v1" in handler._processorMap
    assert "p2.card.action.trigger" not in handler._callback_processor_map
