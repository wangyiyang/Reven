"""入站事件处理器测试：IM 固定引导回复与分发器注册回归。"""

import pytest
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1  # type: ignore[import-untyped]
from reven.integrations.feishu_bot.handlers import (
    GUIDE_TEXT,
    build_event_handler,
    build_guide_reply_handler,
)


def _message_event(
    *, sender_type: str = "user", chat_type: str = "p2p", message_id: str = "om_1"
) -> P2ImMessageReceiveV1:
    return P2ImMessageReceiveV1(
        {
            "event": {
                "sender": {"sender_id": {"open_id": "ou_boss"}, "sender_type": sender_type, "tenant_key": "t"},
                "message": {
                    "message_id": message_id,
                    "chat_id": "oc_1",
                    "chat_type": chat_type,
                    "message_type": "text",
                    "content": '{"text":"hi"}',
                    "create_time": 1,
                },
            }
        }
    )


class ReplyRecorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail = fail

    def __call__(self, message_id: str, text: str) -> None:
        self.calls.append((message_id, text))
        if self._fail:
            raise RuntimeError("飞书 API 不可用")


def test_replies_guide_text_to_private_user_message() -> None:
    recorder = ReplyRecorder()
    handler = build_guide_reply_handler(recorder)

    handler(_message_event())

    assert recorder.calls == [("om_1", GUIDE_TEXT)]


def test_ignores_bot_self_message_to_avoid_loop() -> None:
    recorder = ReplyRecorder()
    handler = build_guide_reply_handler(recorder)

    handler(_message_event(sender_type="app"))

    assert recorder.calls == []


def test_ignores_group_chat_message() -> None:
    recorder = ReplyRecorder()
    handler = build_guide_reply_handler(recorder)

    handler(_message_event(chat_type="group"))

    assert recorder.calls == []


def test_ignores_message_without_id() -> None:
    recorder = ReplyRecorder()
    handler = build_guide_reply_handler(recorder)

    handler(_message_event(message_id=None))  # type: ignore[arg-type]

    assert recorder.calls == []


def test_reply_failure_is_swallowed_and_logged() -> None:
    recorder = ReplyRecorder(fail=True)
    handler = build_guide_reply_handler(recorder)

    handler(_message_event())  # 回复失败仅记日志，不向 SDK 抛出

    assert recorder.calls == [("om_1", GUIDE_TEXT)]


def test_malformed_event_does_not_crash() -> None:
    recorder = ReplyRecorder()
    handler = build_guide_reply_handler(recorder)

    handler(P2ImMessageReceiveV1({"event": {}}))

    assert recorder.calls == []


@pytest.mark.parametrize("sender_type", ["anonymous", "unknown"])
def test_ignores_non_user_sender_types(sender_type: str) -> None:
    recorder = ReplyRecorder()
    handler = build_guide_reply_handler(recorder)

    handler(_message_event(sender_type=sender_type))

    assert recorder.calls == []


# --- 分发器注册回归 ---


def test_event_handler_registers_only_im_processor() -> None:
    handler = build_event_handler("cli_test", "secret")

    assert "p2.im.message.receive_v1" in handler._processorMap
    assert "p2.card.action.trigger" not in handler._callback_processor_map
