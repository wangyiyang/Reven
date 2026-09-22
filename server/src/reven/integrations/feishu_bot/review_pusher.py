"""候选稿审核卡片推送管道：discovery run 结束后把待审核候选推送给白名单用户。

流程：加载配置 → 选候选 → 分批构建卡片 → 逐接收者发送 → 成功批次批量标记 review_pushed_at。
任一环节失败只记日志（provider + 数量 + 异常类型），绝不向上抛，不影响 run 结果；
发送失败的批次不标记，次日随下次 run 重推。本类不依赖 lark SDK 具体类型，可独立测试。
"""

import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol
from uuid import UUID

from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.client import FeishuBotApiClient
from reven.integrations.feishu_bot.config import PROVIDER
from reven.integrations.feishu_bot.review_card import build_review_card_batches
from reven.rss.models import RssItem

logger = logging.getLogger(__name__)


class ReviewBoard(Protocol):
    """审核看板数据口：候选查询与推送标记（核心层 CandidateReviewService 满足该协议）。"""

    async def list_pending_review(self) -> list[RssItem]: ...

    async def mark_review_pushed(self, item_ids: Sequence[UUID]) -> None: ...


class ReviewCardSender(Protocol):
    """卡片发送口：异步应用消息发送，失败抛异常。"""

    async def send_review_card(self, open_id: str, card: dict[str, Any]) -> None: ...


SenderFactory = Callable[[str, str], ReviewCardSender]


class ReviewCardPusher:
    """每日审核卡片推送：无配置/禁用/空白名单/无候选时安静跳过。"""

    def __init__(
        self,
        credentials: IntegrationCredentials,
        review_board: ReviewBoard,
        *,
        sender_factory: SenderFactory | None = None,
    ) -> None:
        self._credentials = credentials
        self._review_board = review_board
        self._sender_factory = sender_factory or FeishuBotApiClient

    async def push_pending_review(self) -> None:
        config = await self._credentials.feishu_bot()
        if config is None:
            return  # loader 已按 provider + 异常类型记日志
        recipients = config.whitelist_open_ids
        if not recipients:
            logger.info("飞书机器人审核卡片推送跳过：白名单为空（provider=%s）", PROVIDER)
            return
        try:
            items = await self._review_board.list_pending_review()
        except Exception as exc:
            logger.warning("飞书机器人审核候选查询失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
            return
        if not items:
            return
        sender = self._sender_factory(config.app_id, config.app_secret)
        delivered = await self._send_batches(sender, recipients, items)
        await self._mark_delivered(delivered)

    async def _send_batches(
        self,
        sender: ReviewCardSender,
        recipients: tuple[str, ...],
        items: list[RssItem],
    ) -> list[UUID]:
        """逐批发送给全部接收者；失败批次记日志后继续后续批次（尽力而为）。"""
        delivered: list[UUID] = []
        for batch in build_review_card_batches(items):
            try:
                for open_id in recipients:
                    await sender.send_review_card(open_id, batch.card)
            except Exception as exc:
                logger.warning(
                    "飞书机器人审核卡片批次发送失败（provider=%s, items=%d, error_type=%s）",
                    PROVIDER,
                    len(batch.item_ids),
                    type(exc).__name__,
                )
                continue
            delivered.extend(batch.item_ids)
        return delivered

    async def _mark_delivered(self, item_ids: list[UUID]) -> None:
        """全部批次对全部接收者发送成功的候选，同一事务批量标记；标记失败仅记日志。"""
        if not item_ids:
            return
        try:
            await self._review_board.mark_review_pushed(item_ids)
        except Exception as exc:
            logger.warning(
                "飞书机器人审核推送标记失败（provider=%s, items=%d, error_type=%s）",
                PROVIDER,
                len(item_ids),
                type(exc).__name__,
            )
