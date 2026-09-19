"""审核按钮回调执行：白名单校验、核心层调用、SDK 事件线程→主事件循环桥接。

事件处理器（handlers.build_review_action_handler）解析按钮值后同步调用
ReviewCallbackDispatcher；后者把 async 审核动作桥接到主事件循环执行，
并把结果收敛为 toast 反馈。任何失败只记 provider + 异常类型的日志，
绝不向上抛，也不泄露配置内容或凭证。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.integrations.feishu_bot.config import PROVIDER, load_feishu_bot_config
from reven.rss.inbox import InboxPushError
from reven.rss.review_service import CandidateReviewError
from reven.security.secrets import SecretBox

if TYPE_CHECKING:
    from reven.rss.inbox import InboxPushResult
    from reven.rss.models import RssItem

logger = logging.getLogger(__name__)

_CALLBACK_TIMEOUT_SECONDS = 10.0  # 桥接等待主事件循环返回审核结果的上限


@dataclass(frozen=True)
class ReviewActionOutcome:
    """一次审核动作的 toast 反馈（toast_type 取值按飞书卡片回调协议）。"""

    toast_type: Literal["success", "info", "error"]
    text: str


TOAST_APPROVED = ReviewActionOutcome("success", "已采纳，推入 Notion Inbox")
TOAST_IGNORED = ReviewActionOutcome("success", "已忽略")
TOAST_ALREADY_HANDLED = ReviewActionOutcome("info", "该候选已处理")
TOAST_FORBIDDEN = ReviewActionOutcome("error", "无审核权限")
TOAST_INVALID = ReviewActionOutcome("error", "操作无效")
TOAST_FAILED = ReviewActionOutcome("error", "操作失败，请稍后重试")


class ReviewActionExecutor(Protocol):
    """审核动作核心口：approve/ignore（CandidateReviewService 满足该协议）。"""

    async def approve(self, item_id: UUID) -> InboxPushResult: ...

    async def ignore(self, item_id: UUID) -> RssItem: ...


class ReviewActionDispatch(Protocol):
    """事件处理器视角的审核分发口：SDK 事件线程内同步调用，返回 toast 反馈。"""

    def __call__(self, action: str, item_id: UUID, operator_open_id: str | None) -> ReviewActionOutcome: ...


class ReviewCallback(ReviewActionDispatch, Protocol):
    """supervisor 视角的回调口：start 时绑定主事件循环作为桥接目标。"""

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None: ...


async def run_review_action(
    executor: ReviewActionExecutor,
    whitelist_open_ids: tuple[str, ...],
    *,
    action: str,
    item_id: UUID,
    operator_open_id: str | None,
) -> ReviewActionOutcome:
    """白名单校验 + 调核心层 + 错误映射；任何失败都收敛为 toast 反馈，不向上抛。"""
    if operator_open_id is None or operator_open_id not in whitelist_open_ids:
        return TOAST_FORBIDDEN
    try:
        if action == "approve":
            await executor.approve(item_id)
            return TOAST_APPROVED
        if action == "ignore":
            await executor.ignore(item_id)
            return TOAST_IGNORED
        return TOAST_INVALID  # 防御：事件处理器已保证 action 合法
    except (CandidateReviewError, InboxPushError) as exc:
        if exc.status_code in (404, 409):
            return TOAST_ALREADY_HANDLED  # 重复点击/飞书重放的幂等语意
        logger.warning("飞书机器人审核回调领域错误（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
        return TOAST_FAILED
    except Exception as exc:
        logger.warning("飞书机器人审核回调执行失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
        return TOAST_FAILED


class ReviewCallbackDispatcher:
    """card.action.trigger 同步分发器：把 async 审核动作桥接到主事件循环执行。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_box: SecretBox,
        executor: ReviewActionExecutor,
        *,
        timeout_seconds: float = _CALLBACK_TIMEOUT_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._secret_box = secret_box
        self._executor = executor
        self._timeout_seconds = timeout_seconds
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """绑定主事件循环（supervisor.start 时调用）；进程生命周期内不变。"""
        self._main_loop = loop

    def __call__(self, action: str, item_id: UUID, operator_open_id: str | None) -> ReviewActionOutcome:
        loop = self._main_loop
        if loop is None:
            logger.warning("飞书机器人审核回调忽略：主事件循环未绑定（provider=%s）", PROVIDER)
            return TOAST_FAILED
        coro = self._execute(action, item_id, operator_open_id)
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception as exc:
            # 调度失败时协程从未被 await，必须显式 close 避免泄漏（RuntimeWarning）
            coro.close()
            logger.warning("飞书机器人审核回调桥接失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
            return TOAST_FAILED
        try:
            return future.result(timeout=self._timeout_seconds)
        except Exception as exc:
            logger.warning("飞书机器人审核回调桥接失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
            return TOAST_FAILED

    async def _execute(self, action: str, item_id: UUID, operator_open_id: str | None) -> ReviewActionOutcome:
        """按最新配置取白名单后执行审核；配置缺失/禁用视为空白名单。"""
        config = await load_feishu_bot_config(self._session_factory, self._secret_box)
        whitelist = config.whitelist_open_ids if config is not None else ()
        return await run_review_action(
            self._executor,
            whitelist,
            action=action,
            item_id=item_id,
            operator_open_id=operator_open_id,
        )
