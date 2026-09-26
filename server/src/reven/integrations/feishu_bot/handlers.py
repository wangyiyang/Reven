"""飞书机器人入站事件处理：IM 固定引导回复。

仅注册 im.message.receive_v1：私聊中的用户消息回复固定引导文案，
提示到网页候选工作台完成审核。处理器绝不向 SDK 抛异常。lark-oapi
延迟导入到构建处，避免包导入期触发 SDK 模块级事件循环副作用。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

GUIDE_TEXT = "请打开 Reven 候选工作台完成审核操作。"

# (message_id, text) -> None；回复失败时抛出异常，由处理器捕获记日志
MessageReplier = Callable[[str, str], None]


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


def build_event_handler(app_id: str, app_secret: str) -> EventDispatcherHandler:
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
    handler: EventDispatcherHandler = builder.build()
    return handler
