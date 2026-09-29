"""飞书机器人入站事件处理：消息路由 + 对话分发。

仅注册 im.message.receive_v1：route_message 纯函数把消息分类为
chat / guide / unsupported，处理器只做「路由 → submit → 立即返回」——
lark-oapi 的处理器与 SDK ping 循环跑在同一连接事件循环上，阻塞等待会心跳
超时掉线，因此一切等待都在 dispatcher 的工作线程内。处理器绝不向 SDK 抛
异常。lark-oapi 延迟导入到构建处，避免包导入期触发 SDK 模块级事件循环副作用。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from reven.integrations.feishu_bot.cards import build_markdown_card
from reven.integrations.feishu_bot.config import PROVIDER

if TYPE_CHECKING:
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler  # type: ignore[import-untyped]

    from reven.integrations.feishu_bot.chat_dispatcher import ChatDispatch, MessageReplier, RouteKind

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteDecision:
    """一条入站消息的路由结论：kind 决定回复策略，text 为 chat 时剥离 mention 占位符后的正文。"""

    kind: RouteKind
    text: str = ""


def route_message(sender: Any, message: Any, bot_open_id: str | None) -> RouteDecision | None:
    """纯函数路由判定（不触网、不抛异常）：

    1. 非 user 消息（机器人自身/应用）→ None（防自循环）；
    2. 私聊：text → chat，其他类型 → unsupported；
    3. 群聊：bot_open_id 未知或未被 @（只比 mentions[*].id.open_id）→ None；
       被 @ 后非 text → unsupported；剥离全部 mention 占位符后为空 → guide，否则 → chat；
    4. content 畸形 JSON → 按非 text 处理为 unsupported。
    """
    if sender.sender_type != "user":
        return None
    if message.chat_type == "p2p":
        if message.message_type != "text":
            return RouteDecision("unsupported")
        text = _strip_text(message)
        return RouteDecision("chat", text) if text is not None else RouteDecision("unsupported")
    if message.chat_type == "group":
        if bot_open_id is None or not _mentions_bot(message, bot_open_id):
            return None
        if message.message_type != "text":
            return RouteDecision("unsupported")
        text = _strip_text(message)
        if text is None:
            return RouteDecision("unsupported")
        return RouteDecision("chat", text) if text else RouteDecision("guide")
    return None


def _strip_text(message: Any) -> str | None:
    """剥离 mention 占位符后的正文；content 非 JSON 对象或 text 字段异常时返回 None。"""
    content = message.content
    if not isinstance(content, str):
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    text = payload.get("text", "")
    if not isinstance(text, str):
        return None
    for mention in message.mentions or []:
        key = getattr(mention, "key", None)
        if key:
            text = text.replace(key, " ")
    return text.strip()


def _mentions_bot(message: Any, bot_open_id: str) -> bool:
    """机器人被 @ 只用 mentions[*].id.open_id 判定；name/mentioned_type 不可靠，禁用。"""
    for mention in message.mentions or []:
        if getattr(getattr(mention, "id", None), "open_id", None) == bot_open_id:
            return True
    return False


def build_message_handler(
    reply: MessageReplier, chat_dispatch: ChatDispatch, bot_open_id: str | None
) -> Callable[[Any], None]:
    """构建 im.message.receive_v1 处理器：路由 → submit → 立即返回；绝不向 SDK 抛异常。"""

    def handle(data: Any) -> None:
        event = getattr(data, "event", None)
        message = getattr(event, "message", None)
        sender = getattr(event, "sender", None)
        if message is None or sender is None:
            return
        try:
            decision = route_message(sender, message, bot_open_id)
        except Exception as exc:
            logger.warning("飞书机器人消息路由失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
            return
        if decision is None:
            return
        message_id = message.message_id
        chat_id = message.chat_id
        open_id = getattr(sender.sender_id, "open_id", None)
        if not message_id or not chat_id or not open_id:
            return
        try:
            chat_dispatch.submit(
                kind=decision.kind,
                reply=reply,
                message_id=message_id,
                chat_id=chat_id,
                open_id=open_id,
                text=decision.text,
            )
        except Exception as exc:
            logger.warning("飞书机器人消息分发失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)

    return handle


def build_event_handler(
    app_id: str,
    app_secret: str,
    *,
    bot_open_id: str | None,
    chat_dispatch: ChatDispatch,
) -> EventDispatcherHandler:
    """构建长连接事件分发器；长连接模式下 encrypt_key/verification_token 传空串。"""
    import lark_oapi  # type: ignore[import-untyped]
    from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody  # type: ignore[import-untyped]
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

    im_client = lark_oapi.Client.builder().app_id(app_id).app_secret(app_secret).build()

    def reply_once(message_id: str, msg_type: str, content: dict[str, Any]) -> Any:
        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type(msg_type)
                .content(json.dumps(content, ensure_ascii=False))
                .build()
            )
            .build()
        )
        return im_client.im.v1.message.reply(request)

    def reply(message_id: str, text: str) -> None:
        # 优先卡片渲染 markdown；卡片失败降级纯文本保证可达，纯文本也失败才抛错
        card_response = reply_once(message_id, "interactive", build_markdown_card(text))
        if card_response.success():
            return
        text_response = reply_once(message_id, "text", {"text": text})
        if not text_response.success():
            raise RuntimeError(f"飞书消息回复失败（code={text_response.code}）")

    builder = EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(
        build_message_handler(reply, chat_dispatch, bot_open_id)
    )
    handler: EventDispatcherHandler = builder.build()
    return handler
