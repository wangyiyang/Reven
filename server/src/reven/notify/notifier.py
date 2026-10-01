"""主动推送投递层：飞书机器人定向会话优先，白名单接收人兜底。

通道降级顺序：chat_id 定向群聊/私聊 → 机器人白名单 open_id 广播。
出向 webhook 已在 0022 迁移中退役，不再作为降级通道。
日志脱敏纪律：只记通道、异常类型与稳定平台码，不带 chat_id、open_id、消息内容或异常原文。
"""

import logging
from typing import Protocol

from reven.integrations.feishu_bot.client import FeishuBotApiError
from reven.provider_clients import ProviderClients

logger = logging.getLogger(__name__)


class PushTargetMissingError(RuntimeError):
    """推送目标/通道配置缺失（机器人未启用、无 chat_id 且白名单为空）；属配置问题而非投递失败。"""


class ProactiveNotifier(Protocol):
    """主动推送口：返回实际使用的投递通道标识。"""

    async def send_markdown(
        self,
        *,
        chat_id: str | None,
        title: str,
        markdown: str,
    ) -> str: ...


class FeishuProactiveNotifier:
    """飞书机器人主动推送：配置与客户端由 ProviderClients seam 提供，凭证每次现读。"""

    def __init__(self, clients: ProviderClients) -> None:
        self._clients = clients

    async def send_markdown(
        self,
        *,
        chat_id: str | None,
        title: str,
        markdown: str,
    ) -> str:
        async with self._clients.feishu_bot() as bot:
            if bot is None:
                raise PushTargetMissingError("飞书应用机器人未启用或凭证不可用")
            if chat_id:
                try:
                    await bot.api.send_markdown_to_chat(chat_id, markdown, title=title)
                    return "chat"
                except FeishuBotApiError as exc:
                    # 脱敏纪律（#176）：只记异常类型与稳定平台码；异常 message 不进日志
                    logger.warning(
                        "飞书定向会话推送失败，降级白名单接收人（error_type=%s, code=%s）",
                        type(exc).__name__,
                        exc.code,
                    )
            if not bot.config.whitelist_open_ids:
                if chat_id:
                    raise FeishuBotApiError("飞书定向会话推送失败且无白名单接收人可降级")
                raise PushTargetMissingError("未配置推送目标（chat_id 与机器人白名单均为空）")
            await bot.api.send_markdown_to_recipients(
                bot.config.whitelist_open_ids,
                markdown,
                title=title,
            )
            return "whitelist"
