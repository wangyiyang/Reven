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
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from reven.agent.errors import AgentModelUnavailableError
from reven.agent.service import AgentTurn, SessionModelState
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

logger = logging.getLogger(__name__)

_CHAT_TIMEOUT_SECONDS = 120.0  # 单轮对话总超时（PRD 硬编码，不做配置项）
_PRECHECK_TIMEOUT_SECONDS = 10.0  # 白名单预检桥等待主事件循环返回的上限

GUIDE_TEXT = "@我 并输入你想问的问题。"
THINKING_TEXT = "思考中…"
FALLBACK_TEXT = "出了点问题，请稍后重试。"
UNSUPPORTED_TEXT = "暂只支持文字提问。"

# 回复必须在共享 HTTP 客户端所属的主循环执行，失败由桥接收敛。
AsyncMessageReplier = Callable[[str, str], Awaitable[None]]


class AsyncResourceDownloader(Protocol):
    """飞书消息附件资源异步下载器协议。"""

    def __call__(self, message_id: str, file_key: str, *, resource_type: str = "file") -> Awaitable[bytes]: ...


RouteKind = Literal["chat", "guide", "unsupported", "file"]


class AgentChatService(Protocol):
    """Agent 对话口（reven.agent.service.AgentService 满足该协议）；本地定义避免跨层依赖 api 层。"""

    async def chat(self, message: str, session_id: str | None = None) -> AgentTurn: ...

    async def model_state(self, session_id: str) -> SessionModelState: ...

    async def use_model(self, session_id: str, model_ref: str) -> SessionModelState: ...


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
        file_key: str | None = None,
        file_name: str | None = None,
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
        downloader: AsyncResourceDownloader | None = None,
        workspace_root: Path = Path("workspace"),
        timeout_seconds: float = _CHAT_TIMEOUT_SECONDS,
        precheck_timeout_seconds: float = _PRECHECK_TIMEOUT_SECONDS,
    ) -> None:
        self._credentials = credentials
        self._agent = agent_service
        self._reply = reply
        self._downloader = downloader
        self._workspace_root = workspace_root
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
        file_key: str | None = None,
        file_name: str | None = None,
    ) -> None:
        """handlers 同步调用；立即返回，不阻塞 SDK 连接循环。"""
        loop = self._main_loop
        if loop is None:
            logger.warning("飞书机器人对话忽略：主事件循环未绑定（provider=%s）", PROVIDER)
            return
        threading.Thread(
            target=self._run,
            args=(loop, kind, message_id, chat_id, open_id, text, file_key, file_name),
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
        file_key: str | None = None,
        file_name: str | None = None,
    ) -> None:
        """工作线程编排：白名单预检（先于任何外显回复）→ 按 kind 回复 → chat 桥 → 结果或兜底。"""
        allowed = self._bridge(loop, self._is_allowed(open_id), timeout=self._precheck_timeout_seconds)
        if allowed is not True:
            return  # 非白名单/配置缺失/预检失败：全静默（连「思考中…」都不发）
        if kind == "guide":
            self._reply_via(loop, message_id, GUIDE_TEXT)
            return
        if kind == "unsupported":
            self._reply_via(loop, message_id, UNSUPPORTED_TEXT)
            return

        chat_prompt = text
        if kind == "file":
            if not self._reply_via(loop, message_id, "正在接收并下载文件…"):
                return
            download_result = self._bridge(
                loop,
                self._download_and_stage_file(message_id, file_key, file_name),
                timeout=self._timeout_seconds,
            )
            if download_result is None:
                self._reply_via(loop, message_id, "文件下载失败，请稍后重试。")
                return
            saved_path, safe_name = download_result
            chat_prompt = (
                f"[收到用户发送的文件，已保存至工作区: {saved_path}]\n"
                f"文件名: {safe_name}\n"
                f"请结合工作区知识或对应 Skill 进行分析与处理。"
            )

        command = parse_model_command(chat_prompt)
        if command is not None:
            # 指令消息：直接回复，不发占位、不进入 Agent、不计入会话历史
            answer = self._bridge(
                loop, self._handle_model_command(chat_id, open_id, command), timeout=self._timeout_seconds
            )
            self._reply_via(loop, message_id, answer if answer is not None else FALLBACK_TEXT)
            return
        if not self._reply_via(loop, message_id, THINKING_TEXT):
            return  # 占位未送达时放弃本轮，避免后续结果破坏回复顺序
        answer = self._bridge(loop, self._chat(chat_id, open_id, chat_prompt), timeout=self._timeout_seconds)
        if answer is None:
            self._reply_via(loop, message_id, FALLBACK_TEXT)
            return
        self._reply_via(loop, message_id, answer)

    async def _download_and_stage_file(
        self,
        message_id: str,
        file_key: str | None,
        file_name: str | None,
    ) -> tuple[str, str] | None:
        """从飞书下载文件并保存到工作区 downloads 目录。"""
        if not file_key or self._downloader is None:
            return None
        safe_name = Path(file_name).name if file_name else f"{file_key}.bin"
        downloads_dir = self._workspace_root / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        target_path = downloads_dir / safe_name
        try:
            content = await self._downloader(message_id, file_key, resource_type="file")
            target_path.write_bytes(content)
            return str(target_path), safe_name
        except Exception as exc:
            logger.warning("飞书附件下载失败（file_key=%s, error_type=%s）", file_key, type(exc).__name__)
            return None

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

    def _reply_via(self, loop: asyncio.AbstractEventLoop, message_id: str, text: str) -> bool:
        return self._bridge(loop, self._send_reply(message_id, text), timeout=self._timeout_seconds) is True

    async def _send_reply(self, message_id: str, text: str) -> bool:
        await self._reply(message_id, text)
        return True  # reply 的 None 是成功返回值，bridge 的 None 则表示失败

    async def _is_allowed(self, open_id: str) -> bool:
        """主循环内每次现读白名单（配置页改动即时生效）；配置缺失/禁用/读取失败视为空白名单。"""
        config = await self._credentials.feishu_bot()
        return config is not None and open_id in config.whitelist_open_ids

    @staticmethod
    def _session_id(chat_id: str, open_id: str) -> str:
        return f"feishu:{chat_id}:{open_id}"

    async def _handle_model_command(self, chat_id: str, open_id: str, command: ModelCommand) -> str:
        session_id = self._session_id(chat_id, open_id)
        if command.action == "list":
            return render_model_list(await self._agent.model_state(session_id))
        if command.action == "current":
            return render_current(await self._agent.model_state(session_id))
        if command.action == "use":
            ref = command.model_ref
            if ref is None or not is_valid_model_ref(ref):
                return USAGE_TEXT
            try:
                state = await self._agent.use_model(session_id, ref)
            except AgentModelUnavailableError:
                return render_use_rejected(ref, await self._agent.model_state(session_id))
            return render_use_switched(ref) if state.is_override else render_use_reset_to_default(ref)
        return USAGE_TEXT

    async def _chat(self, chat_id: str, open_id: str, text: str) -> str:
        try:
            turn = await self._agent.chat(text, self._session_id(chat_id, open_id))
        except AgentModelUnavailableError as exc:
            # 严格语义：override 模型不可达时明确报错，绝不静默回落默认模型
            logger.warning("飞书机器人会话模型不可用（model=%s, error_code=%s）", exc.model_ref, exc.code)
            return render_model_unavailable(exc.model_ref)
        if turn.is_override and turn.model_ref is not None:
            return render_answer_with_model(turn.response, turn.model_ref)
        return turn.response
