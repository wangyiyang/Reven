"""飞书入站对话分发：SDK 连接线程同步 submit，daemon 工作线程编排两座协程桥。

lark-oapi 的消息处理器与 SDK ping 循环（间隔 120s）跑在同一连接事件循环上，
处理器内阻塞等待 Agent（单轮上限 120s）会心跳超时掉线——因此 submit() 必须
立即返回；白名单预检与 Agent 调用都经 run_coroutine_threadsafe 桥到 FastAPI
主事件循环执行，等待发生在每条消息一个的 daemon 工作线程内。

错误纪律：一切异常收敛为兜底文案 + 脱敏日志（provider + 异常类型），绝不向
SDK 抛；run_coroutine_threadsafe 调度失败必须 close 未 await 的协程。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Coroutine
from typing import Any, Literal, Protocol, TypeVar

from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.config import PROVIDER

logger = logging.getLogger(__name__)

_CHAT_TIMEOUT_SECONDS = 120.0  # 单轮对话总超时（PRD 硬编码，不做配置项）
_PRECHECK_TIMEOUT_SECONDS = 10.0  # 白名单预检桥等待主事件循环返回的上限

GUIDE_TEXT = "@我 并输入你想问的问题。"
THINKING_TEXT = "思考中…"
FALLBACK_TEXT = "出了点问题，请稍后重试。"
UNSUPPORTED_TEXT = "暂只支持文字提问。"

# (message_id, text) -> None；回复失败时抛出异常，由调用处捕获记日志
MessageReplier = Callable[[str, str], None]

RouteKind = Literal["chat", "guide", "unsupported"]


class AgentChatService(Protocol):
    """Agent 对话口（reven.agent.service.AgentService 满足该协议）；本地定义避免跨层依赖 api 层。"""

    async def chat(self, message: str, session_id: str | None = None) -> tuple[str, str]: ...


class ChatDispatch(Protocol):
    """入站对话分发口：handlers 经 submit 投递（必须立即返回）；supervisor 在 start 时 bind_loop。"""

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None: ...

    def submit(
        self,
        *,
        kind: RouteKind,
        reply: MessageReplier,
        message_id: str,
        chat_id: str,
        open_id: str,
        text: str,
    ) -> None: ...


_T = TypeVar("_T")


class FeishuChatDispatcher:
    """消息对话分发器：白名单现读 + Agent 调用桥到主事件循环，工作线程内等待并回消息。"""

    def __init__(
        self,
        credentials: IntegrationCredentials,
        agent_service: AgentChatService,
        *,
        timeout_seconds: float = _CHAT_TIMEOUT_SECONDS,
        precheck_timeout_seconds: float = _PRECHECK_TIMEOUT_SECONDS,
    ) -> None:
        self._credentials = credentials
        self._agent = agent_service
        self._timeout_seconds = timeout_seconds
        self._precheck_timeout_seconds = precheck_timeout_seconds
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """绑定主事件循环（supervisor.start 时调用）；进程生命周期内不变。"""
        self._main_loop = loop

    def submit(
        self,
        *,
        kind: RouteKind,
        reply: MessageReplier,
        message_id: str,
        chat_id: str,
        open_id: str,
        text: str,
    ) -> None:
        """handlers 同步调用；立即返回，不阻塞 SDK 连接循环。"""
        loop = self._main_loop
        if loop is None:
            logger.warning("飞书机器人对话忽略：主事件循环未绑定（provider=%s）", PROVIDER)
            return
        threading.Thread(
            target=self._run,
            args=(loop, kind, reply, message_id, chat_id, open_id, text),
            daemon=True,
            name="feishu-chat-worker",
        ).start()

    def _run(
        self,
        loop: asyncio.AbstractEventLoop,
        kind: RouteKind,
        reply: MessageReplier,
        message_id: str,
        chat_id: str,
        open_id: str,
        text: str,
    ) -> None:
        """工作线程编排：白名单预检（先于任何外显回复）→ 按 kind 回复 → chat 桥 → 结果或兜底。"""
        allowed = self._bridge(loop, self._is_allowed(open_id), timeout=self._precheck_timeout_seconds)
        if allowed is not True:
            return  # 非白名单/配置缺失/预检失败：全静默（连「思考中…」都不发）
        if kind == "guide":
            self._safe_reply(reply, message_id, GUIDE_TEXT)
            return
        if kind == "unsupported":
            self._safe_reply(reply, message_id, UNSUPPORTED_TEXT)
            return
        try:
            reply(message_id, THINKING_TEXT)
        except Exception as exc:
            # 占位都发不出就直接放弃本轮（不再尝试发结果，避免时序错乱）
            logger.warning(
                "飞书机器人占位回复失败，放弃本轮对话（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__
            )
            return
        answer = self._bridge(loop, self._chat(chat_id, open_id, text), timeout=self._timeout_seconds)
        if answer is None:
            self._safe_reply(reply, message_id, FALLBACK_TEXT)
            return
        self._safe_reply(reply, message_id, answer)

    def _bridge(self, loop: asyncio.AbstractEventLoop, coro: Coroutine[Any, Any, _T], *, timeout: float) -> _T | None:
        """run_coroutine_threadsafe 桥：调度失败 close 协程；超时/异常收敛为 None + 脱敏日志。"""
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception as exc:
            coro.close()  # 调度失败时协程从未被 await，必须显式 close 避免泄漏（RuntimeWarning）
            logger.warning("飞书机器人对话桥接调度失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
            return None
        try:
            return future.result(timeout=timeout)
        except Exception as exc:
            # error_code 取 AgentError 一族的稳定错误码（不含 secret/token）；异常 message 可能含上游
            # 凭证回显，禁止进日志——code 即 design 要求的「脱敏 message」
            logger.warning(
                "飞书机器人对话桥接失败（provider=%s, error_type=%s, error_code=%s）",
                PROVIDER,
                type(exc).__name__,
                getattr(exc, "code", "-"),
            )
            return None

    @staticmethod
    def _safe_reply(reply: MessageReplier, message_id: str, text: str) -> None:
        try:
            reply(message_id, text)
        except Exception as exc:
            logger.warning("飞书机器人对话回复失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)

    async def _is_allowed(self, open_id: str) -> bool:
        """主循环内每次现读白名单（配置页改动即时生效）；配置缺失/禁用/读取失败视为空白名单。"""
        config = await self._credentials.feishu_bot()
        return config is not None and open_id in config.whitelist_open_ids

    async def _chat(self, chat_id: str, open_id: str, text: str) -> str:
        session_id = f"feishu:{chat_id}:{open_id}"
        _, answer = await self._agent.chat(text, session_id)
        return answer
