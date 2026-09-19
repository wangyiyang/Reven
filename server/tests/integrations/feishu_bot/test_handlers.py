"""入站事件处理器测试：IM 固定引导回复、审核按钮回调（解析/白名单/幂等 toast）、分发器注册回归。"""

from uuid import UUID

import pytest
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1  # type: ignore[import-untyped]
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTrigger  # type: ignore[import-untyped]
from reven.integrations.feishu_bot.handlers import (
    GUIDE_TEXT,
    build_event_handler,
    build_guide_reply_handler,
    build_review_action_handler,
)
from reven.integrations.feishu_bot.review_callback import (
    TOAST_ALREADY_HANDLED,
    TOAST_APPROVED,
    TOAST_FORBIDDEN,
    TOAST_IGNORED,
    ReviewActionOutcome,
)

ITEM_ID = UUID("12345678-1234-5678-1234-567812345678")


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


# --- 审核按钮回调（card.action.trigger）---


def _card_event(*, open_id: str | None = "ou_boss", value: object = None) -> P2CardActionTrigger:
    if value is None:
        value = {"action": "approve", "item_id": str(ITEM_ID)}
    operator = {} if open_id is None else {"open_id": open_id}
    return P2CardActionTrigger({"event": {"operator": operator, "action": {"value": value}}})


class DispatchStub:
    """假审核分发器：记录 (action, item_id, operator_open_id)，返回固定 outcome 或抛错。"""

    def __init__(self, outcome: ReviewActionOutcome = TOAST_APPROVED, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, UUID, str | None]] = []
        self._outcome = outcome
        self._error = error

    def __call__(self, action: str, item_id: UUID, operator_open_id: str | None) -> ReviewActionOutcome:
        self.calls.append((action, item_id, operator_open_id))
        if self._error is not None:
            raise self._error
        return self._outcome


def _toast_of(response: object) -> tuple[str, str]:
    toast = response.toast  # type: ignore[attr-defined]
    return toast.type, toast.content


def test_approve_action_dispatches_and_returns_success_toast() -> None:
    dispatch = DispatchStub(TOAST_APPROVED)
    handler = build_review_action_handler(dispatch)

    response = handler(_card_event())

    assert dispatch.calls == [("approve", ITEM_ID, "ou_boss")]
    assert _toast_of(response) == ("success", "已采纳，推入 Notion Inbox")


def test_ignore_action_dispatches_and_returns_success_toast() -> None:
    dispatch = DispatchStub(TOAST_IGNORED)
    handler = build_review_action_handler(dispatch)

    response = handler(_card_event(value={"action": "ignore", "item_id": str(ITEM_ID)}))

    assert dispatch.calls == [("ignore", ITEM_ID, "ou_boss")]
    assert _toast_of(response) == ("success", "已忽略")


def test_already_handled_outcome_maps_to_info_toast() -> None:
    dispatch = DispatchStub(TOAST_ALREADY_HANDLED)
    handler = build_review_action_handler(dispatch)

    response = handler(_card_event())

    assert _toast_of(response) == ("info", "该候选已处理")


def test_missing_operator_passes_none_open_id_to_dispatch() -> None:
    dispatch = DispatchStub(TOAST_FORBIDDEN)
    handler = build_review_action_handler(dispatch)

    response = handler(_card_event(open_id=None))

    assert dispatch.calls == [("approve", ITEM_ID, None)]
    assert _toast_of(response) == ("error", "无审核权限")


@pytest.mark.parametrize(
    "value",
    [
        {"item_id": str(ITEM_ID)},  # 缺 action
        {"action": "approve"},  # 缺 item_id
        {"action": "delete", "item_id": str(ITEM_ID)},  # 未知 action
        {"action": "approve", "item_id": "not-a-uuid"},  # 非法 UUID
        {"action": "approve", "item_id": 123},  # item_id 非字符串
    ],
)
def test_malformed_value_returns_invalid_toast_without_dispatch(value: object) -> None:
    dispatch = DispatchStub()
    handler = build_review_action_handler(dispatch)

    response = handler(_card_event(value=value))

    assert dispatch.calls == []
    assert _toast_of(response) == ("error", "操作无效")


def test_non_dict_value_returns_invalid_toast_without_dispatch() -> None:
    dispatch = DispatchStub()
    handler = build_review_action_handler(dispatch)
    event = _card_event()
    event.event.action.value = ["approve", str(ITEM_ID)]  # SDK 模型层会拦截，此处直接赋值测防御分支

    response = handler(event)

    assert dispatch.calls == []
    assert _toast_of(response) == ("error", "操作无效")


def test_malformed_card_event_returns_invalid_toast_without_dispatch() -> None:
    dispatch = DispatchStub()
    handler = build_review_action_handler(dispatch)

    response = handler(P2CardActionTrigger({}))

    assert dispatch.calls == []
    assert _toast_of(response) == ("error", "操作无效")


def test_dispatch_exception_returns_failed_toast_without_raising() -> None:
    dispatch = DispatchStub(error=RuntimeError("database down"))
    handler = build_review_action_handler(dispatch)

    response = handler(_card_event())  # 不向 SDK 抛异常

    assert _toast_of(response) == ("error", "操作失败，请稍后重试")


# --- 分发器注册回归 ---


def test_event_handler_registers_im_and_card_action_processors() -> None:
    handler = build_event_handler("cli_test", "secret", review_dispatch=DispatchStub())

    assert "p2.im.message.receive_v1" in handler._processorMap
    assert "p2.card.action.trigger" in handler._callback_processor_map


def test_event_handler_without_review_dispatch_registers_only_im_processor() -> None:
    handler = build_event_handler("cli_test", "secret")

    assert "p2.im.message.receive_v1" in handler._processorMap
    assert "p2.card.action.trigger" not in handler._callback_processor_map
