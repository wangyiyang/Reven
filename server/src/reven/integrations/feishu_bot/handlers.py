"""飞书机器人入站事件处理：IM 固定引导回复 + 候选审核按钮回调。

按钮回调链路：解析卡片按钮 value（结构畸形直接 toast"操作无效"）→
同步分发器 ReviewActionDispatch（白名单校验与核心层调用在分发器内桥接主事件循环完成）→
toast 反馈。处理器绝不向 SDK 抛异常。lark-oapi 延迟导入到构建处，
避免包导入期触发 SDK 模块级事件循环副作用。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from reven.integrations.feishu_bot.review_callback import (
    TOAST_FAILED,
    TOAST_INVALID,
    ReviewActionDispatch,
    ReviewActionOutcome,
)

if TYPE_CHECKING:
    from lark_oapi.event.callback.model.p2_card_action_trigger import (  # type: ignore[import-untyped]
        P2CardActionTrigger,
        P2CardActionTriggerResponse,
    )
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

GUIDE_TEXT = "请打开 Reven 候选工作台完成审核操作。"

# (message_id, text) -> None；回复失败时抛出异常，由处理器捕获记日志
MessageReplier = Callable[[str, str], None]

_REVIEW_ACTIONS = ("approve", "ignore")


def build_guide_reply_handler(reply: MessageReplier) -> Callable[[Any], None]:
    """构建 im.message.receive_v1 处理器：仅对私聊中的用户消息回固定引导文案。"""

    def handle(data: Any) -> None:
        event = getattr(data, "event", None)
        message = getattr(event, "message", None)
        sender = getattr(event, "sender", None)
        if message is None or sender is None:
            return
        if sender.sender_type != "user":
            return  # 机器人自身或应用消息：忽略，防自循环
        if message.chat_type != "p2p":
            return
        message_id = message.message_id
        if not message_id:
            return
        try:
            reply(message_id, GUIDE_TEXT)
        except Exception as exc:
            logger.warning("飞书机器人引导回复失败（provider=feishu_bot, error_type=%s）", type(exc).__name__)

    return handle


def parse_review_action(value: object) -> tuple[str, UUID] | None:
    """解析审核按钮 value：{"action": "approve"|"ignore", "item_id": "<uuid>"}；结构不符返回 None。"""
    if not isinstance(value, dict):
        return None
    action = value.get("action")
    if not isinstance(action, str) or action not in _REVIEW_ACTIONS:
        return None
    raw_item_id = value.get("item_id")
    if not isinstance(raw_item_id, str):
        return None
    try:
        item_id = UUID(raw_item_id)
    except ValueError:
        return None
    return action, item_id


def build_review_action_handler(
    dispatch: ReviewActionDispatch,
) -> Callable[[P2CardActionTrigger], P2CardActionTriggerResponse]:
    """构建 card.action.trigger 处理器：解析按钮值 → 分发审核 → toast 反馈；绝不向 SDK 抛异常。"""
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTriggerResponse,  # 延迟导入：避免包导入期触发 SDK 模块级事件循环副作用
    )

    def handle(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        event = getattr(data, "event", None)
        operator = getattr(event, "operator", None)
        open_id = getattr(operator, "open_id", None)
        action_obj = getattr(event, "action", None)
        parsed = parse_review_action(getattr(action_obj, "value", None))
        if parsed is None:
            return _toast_response(P2CardActionTriggerResponse, TOAST_INVALID)
        action, item_id = parsed
        try:
            outcome = dispatch(action, item_id, open_id if isinstance(open_id, str) else None)
        except Exception as exc:
            logger.warning("飞书机器人审核回调分发失败（provider=feishu_bot, error_type=%s）", type(exc).__name__)
            outcome = TOAST_FAILED
        return _toast_response(P2CardActionTriggerResponse, outcome)

    return handle


def _toast_response(
    response_type: type[P2CardActionTriggerResponse],
    outcome: ReviewActionOutcome,
) -> P2CardActionTriggerResponse:
    return response_type({"toast": {"type": outcome.toast_type, "content": outcome.text}})


def build_event_handler(
    app_id: str,
    app_secret: str,
    *,
    review_dispatch: ReviewActionDispatch | None = None,
) -> EventDispatcherHandler:
    """构建长连接事件分发器；长连接模式下 encrypt_key/verification_token 传空串。"""
    import lark_oapi  # type: ignore[import-untyped]
    from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody  # type: ignore[import-untyped]
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

    im_client = lark_oapi.Client.builder().app_id(app_id).app_secret(app_secret).build()

    def reply(message_id: str, text: str) -> None:
        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .build()
            )
            .build()
        )
        response = im_client.im.v1.message.reply(request)
        if not response.success():
            raise RuntimeError(f"飞书消息回复失败（code={response.code}）")

    builder = EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(build_guide_reply_handler(reply))
    if review_dispatch is not None:
        builder = builder.register_p2_card_action_trigger(build_review_action_handler(review_dispatch))
    handler: EventDispatcherHandler = builder.build()
    return handler
