"""飞书入站对话分发：SDK 连接线程同步 submit，daemon 工作线程编排协程桥。

lark-oapi 的消息处理器与 SDK ping 循环（间隔 120s）跑在同一连接事件循环上，
处理器内阻塞等待 Agent（单轮上限 120s）会心跳超时掉线——因此 submit() 必须
立即返回；白名单预检、回复与 Agent 调用都经 run_coroutine_threadsafe 桥到 FastAPI
主事件循环执行，等待发生在每条消息一个的 daemon 工作线程内。

错误纪律：一切异常收敛为兜底文案 + 脱敏日志（provider + 异常类型），绝不向
SDK 抛；run_coroutine_threadsafe 调度失败必须 close 未 await 的协程。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Literal, Protocol, TypeVar
from uuid import UUID

from reven.agent.context import AgentActor
from reven.agent.errors import AgentError, AgentModelUnavailableError
from reven.agent.service_types import AgentTurn, RunState, SessionModelState
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.commands import (
    USAGE_TEXT,
    ModelCommand,
    is_valid_model_ref,
    parse_model_command,
    render_answer_with_model,
    render_current,
    render_model_list,
    render_model_unavailable,
    render_use_rejected,
    render_use_reset_to_default,
    render_use_switched,
)
from reven.integrations.feishu_bot.config import PROVIDER
from reven.integrations.feishu_bot.run_commands import (
    RESULT_UNAVAILABLE_TEXT,
    RUN_USAGE_TEXT,
    RunCommand,
    parse_run_command,
    render_run_error,
    render_run_state,
)

logger = logging.getLogger(__name__)

_CHAT_TIMEOUT_SECONDS = 120.0  # 接口等待期限，底层运行由应用生命周期持有
_PRECHECK_TIMEOUT_SECONDS = 10.0  # 白名单预检桥等待主事件循环返回的上限
_BRIDGE_GRACE_SECONDS = 5.0  # 让服务先返回包含运行编号的等待状态

GUIDE_TEXT = "@我 并输入你想问的问题。"
THINKING_TEXT = "思考中…"
FALLBACK_TEXT = RESULT_UNAVAILABLE_TEXT
UNSUPPORTED_TEXT = "暂只支持文字提问。"

# 回复必须在共享 HTTP 客户端所属的主循环执行，失败由桥接收敛。
AsyncMessageReplier = Callable[[str, str], Awaitable[None]]

RouteKind = Literal["chat", "guide", "unsupported"]


class AgentChatService(Protocol):
    """Agent 对话口（reven.agent.service.AgentService 满足该协议）；本地定义避免跨层依赖 api 层。"""

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        *,
        actor: AgentActor,
        request_key: str | None = None,
        wait_timeout_seconds: float | None = None,
    ) -> AgentTurn: ...

    async def model_state(self, session_id: str, *, actor: AgentActor) -> SessionModelState: ...

    async def use_model(self, session_id: str, model_ref: str, *, actor: AgentActor) -> SessionModelState: ...

    async def get_run(self, run_id: UUID, *, actor: AgentActor, session_id: str | None = None) -> RunState: ...

    async def resolve_approval(
        self,
        approval_id: UUID,
        decision: Literal["approve", "reject"],
        session_id: str,
        *,
        actor: AgentActor,
        wait_timeout_seconds: float | None = None,
    ) -> RunState: ...

    async def resume_run(
        self,
        run_id: UUID,
        *,
        actor: AgentActor,
        session_id: str | None = None,
        wait_timeout_seconds: float | None = None,
    ) -> AgentTurn: ...


class ChatDispatch(Protocol):
    """入站对话分发口：handlers 经 submit 投递（必须立即返回）；supervisor 在 start 时 bind_loop。"""

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None: ...

    def submit(
        self,
        *,
        kind: RouteKind,
        message_id: str,
        chat_id: str,
        open_id: str,
        text: str,
    ) -> None: ...


_T = TypeVar("_T")


class FeishuChatDispatcher:
    """消息对话分发器：白名单现读 + Agent 调用桥到主事件循环，工作线程内等待并回消息。

    指令消息（/model …）直接回复，不发「思考中…」占位、不进入 LLM。
    会话模型选择与本轮身份由共享 Agent 业务对象解释。
    """

    def __init__(
        self,
        credentials: IntegrationCredentials,
        agent_service: AgentChatService,
        *,
        reply: AsyncMessageReplier,
        timeout_seconds: float = _CHAT_TIMEOUT_SECONDS,
        precheck_timeout_seconds: float = _PRECHECK_TIMEOUT_SECONDS,
    ) -> None:
        self._credentials = credentials
        self._agent = agent_service
        self._reply = reply
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
            args=(loop, kind, message_id, chat_id, open_id, text),
            daemon=True,
            name="feishu-chat-worker",
        ).start()

    def _run(
        self,
        loop: asyncio.AbstractEventLoop,
        kind: RouteKind,
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
            self._reply_via(loop, message_id, GUIDE_TEXT, open_id)
            return
        if kind == "unsupported":
            self._reply_via(loop, message_id, UNSUPPORTED_TEXT, open_id)
            return
        command = parse_model_command(text) or parse_run_command(text)
        if command is not None:
            # 指令消息：直接回复，不发占位、不进入 Agent、不计入会话历史
            answer = self._bridge(
                loop,
                self._handle_command(chat_id, open_id, command),
                timeout=self._timeout_seconds + _BRIDGE_GRACE_SECONDS,
            )
            self._reply_via(loop, message_id, answer if answer is not None else FALLBACK_TEXT, open_id)
            return
        if not self._reply_via(loop, message_id, THINKING_TEXT, open_id):
            return  # 占位未送达时放弃本轮，避免后续结果破坏回复顺序
        answer = self._bridge(
            loop,
            self._chat(chat_id, open_id, text, message_id),
            timeout=self._timeout_seconds + _BRIDGE_GRACE_SECONDS,
        )
        if answer is None:
            self._reply_via(loop, message_id, FALLBACK_TEXT, open_id)
            return
        self._reply_via(loop, message_id, answer, open_id)

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

    def _reply_via(self, loop: asyncio.AbstractEventLoop, message_id: str, text: str, open_id: str) -> bool:
        return self._bridge(loop, self._send_reply(message_id, text, open_id), timeout=self._timeout_seconds) is True

    async def _send_reply(self, message_id: str, text: str, open_id: str) -> bool:
        if not await self._is_allowed(open_id):
            return False
        await self._reply(message_id, text)
        return True  # reply 的 None 是成功返回值，bridge 的 None 则表示失败

    async def _is_allowed(self, open_id: str) -> bool:
        """主循环内每次现读白名单（配置页改动即时生效）；配置缺失/禁用/读取失败视为空白名单。"""
        config = await self._credentials.feishu_bot()
        return config is not None and open_id in config.whitelist_open_ids

    @staticmethod
    def _session_id(chat_id: str, open_id: str) -> str:
        return f"feishu:{chat_id}:{open_id}"

    @staticmethod
    def _actor(open_id: str) -> AgentActor:
        return AgentActor(owner_id=f"feishu:{open_id}", channel="feishu")

    async def _handle_command(self, chat_id: str, open_id: str, command: ModelCommand | RunCommand) -> str:
        if not await self._is_allowed(open_id):
            return ""
        try:
            if isinstance(command, ModelCommand):
                return await self._handle_model_command(chat_id, open_id, command)
            return await self._handle_run_command(chat_id, open_id, command)
        except AgentModelUnavailableError as exc:
            self._log_agent_error(exc)
            return render_model_unavailable(exc.model_ref)
        except AgentError as exc:
            self._log_agent_error(exc)
            return render_run_error(exc)

    async def _handle_run_command(self, chat_id: str, open_id: str, command: RunCommand) -> str:
        if command.identifier is None:
            return RUN_USAGE_TEXT
        session_id, actor = self._session_id(chat_id, open_id), self._actor(open_id)
        if command.action == "approve" or command.action == "reject":
            run = await self._agent.resolve_approval(
                command.identifier,
                command.action,
                session_id,
                actor=actor,
                wait_timeout_seconds=self._timeout_seconds,
            )
            return render_run_state(run)
        if command.action == "status":
            return render_run_state(await self._agent.get_run(command.identifier, actor=actor, session_id=session_id))
        if command.action == "resume":
            turn = await self._agent.resume_run(
                command.identifier,
                actor=actor,
                session_id=session_id,
                wait_timeout_seconds=self._timeout_seconds,
            )
            return self._render_turn(turn)
        return RUN_USAGE_TEXT

    async def _handle_model_command(self, chat_id: str, open_id: str, command: ModelCommand) -> str:
        session_id = self._session_id(chat_id, open_id)
        actor = self._actor(open_id)
        if command.action == "list":
            return render_model_list(await self._agent.model_state(session_id, actor=actor))
        if command.action == "current":
            return render_current(await self._agent.model_state(session_id, actor=actor))
        if command.action == "use":
            ref = command.model_ref
            if ref is None or not is_valid_model_ref(ref):
                return USAGE_TEXT
            try:
                state = await self._agent.use_model(session_id, ref, actor=actor)
            except AgentModelUnavailableError:
                return render_use_rejected(ref, await self._agent.model_state(session_id, actor=actor))
            return render_use_switched(ref) if state.is_override else render_use_reset_to_default(ref)
        return USAGE_TEXT

    async def _chat(self, chat_id: str, open_id: str, text: str, message_id: str) -> str:
        if not await self._is_allowed(open_id):
            return ""
        try:
            turn = await self._agent.chat(
                text,
                self._session_id(chat_id, open_id),
                actor=self._actor(open_id),
                request_key=message_id,
                wait_timeout_seconds=self._timeout_seconds,
            )
        except AgentModelUnavailableError as exc:
            # 严格语义：override 模型不可达时明确报错，绝不静默回落默认模型
            logger.warning("飞书机器人会话模型不可用（model=%s, error_code=%s）", exc.model_ref, exc.code)
            return render_model_unavailable(exc.model_ref)
        except AgentError as exc:
            self._log_agent_error(exc)
            return render_run_error(exc)
        return self._render_turn(turn)

    @staticmethod
    def _render_turn(turn: AgentTurn) -> str:
        if turn.is_override and turn.model_ref is not None:
            return render_answer_with_model(turn.response, turn.model_ref)
        return turn.response

    @staticmethod
    def _log_agent_error(error: AgentError) -> None:
        logger.warning(
            "飞书机器人 Agent 请求失败（provider=%s, error_type=%s, error_code=%s）",
            PROVIDER,
            type(error).__name__,
            error.code,
        )
