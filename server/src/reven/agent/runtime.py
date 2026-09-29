"""dsh 嵌入式运行时封装：单例生命周期 + 同步 SDK 的异步包装。"""

import logging
from pathlib import Path
from uuid import uuid4

from anyio import to_thread
from deepseek_harness import DeepSeekHarness
from deepseek_harness.errors import HarnessError, JsonRpcError

from reven.agent.config import AgentConfig
from reven.agent.errors import AgentNotConfiguredError, AgentRuntimeError
from reven.agent.mcp_server import AgentMcpContext

logger = logging.getLogger(__name__)

DSH_PATCH_FILE = Path(__file__).with_name("dsh.patch.yml")


def _launch(config: AgentConfig, mcp: AgentMcpContext | None) -> DeepSeekHarness:
    config.dsh_home.mkdir(parents=True, exist_ok=True)
    env: dict[str, str] = {}
    patches = config.patches
    if mcp is not None:
        # dsh.patch.yml 的 !!js 表达式依赖这两个变量；token 仅经 env 传递，不写日志
        env = {"REVEN_AGENT_MCP_URL": mcp.url, "REVEN_AGENT_MCP_TOKEN": mcp.token}
        patches = (*patches, str(DSH_PATCH_FILE))
    harness = DeepSeekHarness(
        dsh_home=str(config.dsh_home),
        cwd=str(config.cwd),
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        patches=patches,
        env=env,
    )
    try:
        harness.start()
    except Exception:
        harness.close()
        raise
    return harness


def _is_session_exists_conflict(exc: HarnessError) -> bool:
    """识别"磁盘上存在但进程内存中不存在"的会话冲突（dsh 无 resume API，进程重启后出现）。"""
    if not isinstance(exc, JsonRpcError):
        return False
    return "already exists" in str(exc)


class AgentRuntime:
    """持有 DeepSeekHarness 单例，由 FastAPI lifespan 管理启动与关闭。

    SDK 为同步客户端，所有调用经 anyio.to_thread 包装，不阻塞事件循环；
    M0.4 已实测单实例多线程并发 run()（独立 session_id）真并发，不加全局锁。
    启动失败不抛出：置为不可用状态并记日志，应用照常启动（已拍板降级策略）。
    """

    def __init__(self, config: AgentConfig | None, mcp: AgentMcpContext | None = None) -> None:
        self._config = config
        self._mcp = mcp
        self._harness: DeepSeekHarness | None = None
        self._start_failed = False
        self._session_aliases: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return self._config is not None

    async def start(self) -> None:
        """拉起 dsh 子进程并完成 initialize 握手；未配置或已失败时为空操作。

        启动失败（含 HarnessError / OSError / TimeoutError 等任意异常）仅记录
        结构化日志并标记不可用，绝不阻止应用启动；chat 在该状态返回 502。
        """
        if self._config is None or self._harness is not None or self._start_failed:
            return
        try:
            self._harness = await to_thread.run_sync(_launch, self._config, self._mcp)
        except Exception as exc:
            self._start_failed = True
            logger.error("dsh 运行时启动失败，Agent 降级为不可用（error_type=%s）", type(exc).__name__)

    async def close(self) -> None:
        """关闭 dsh 子进程并复位失败标记；幂等，未启动时为空操作。"""
        harness = self._harness
        self._harness = None
        self._start_failed = False
        if harness is not None:
            await to_thread.run_sync(harness.close)

    async def chat(self, message: str, session_id: str | None = None) -> tuple[str, str]:
        """执行一轮对话，返回 (实际使用的 session_id, 最终响应文本)；session_id 缺省时生成。

        进程重启后 dsh 内存会话表清空而磁盘会话仍在，旧 session_id 会触发 "already exists"
        冲突：为该外部 id 重铸活跃 id（`<外部 id>~r<随机>`）重试一次并记录进程内别名，
        后续同外部 id 的消息经别名沿用同一活跃会话；别名不持久化，重启后首次冲突会再次重铸。
        """
        if self._config is None:
            raise AgentNotConfiguredError()
        if self._start_failed:
            raise AgentRuntimeError("AGENT_RUNTIME_UNAVAILABLE", "dsh 运行时启动失败，Agent 暂不可用")
        harness = self._harness
        if harness is None:
            raise AgentRuntimeError("AGENT_RUNTIME_NOT_STARTED", "dsh 运行时未启动")
        resolved_session_id = self._session_aliases.get(session_id, session_id) if session_id else uuid4().hex
        try:
            result = await to_thread.run_sync(lambda: harness.run(message, session_id=resolved_session_id))
        except HarnessError as exc:
            if not session_id or not _is_session_exists_conflict(exc):
                raise AgentRuntimeError("AGENT_CHAT_FAILED", f"dsh 会话执行失败：{exc}") from exc
            resolved_session_id = f"{session_id}~r{uuid4().hex[:8]}"
            logger.info("dsh 会话冲突，重铸活跃 id 重试（session_id=%s, resolved=%s）", session_id, resolved_session_id)
            try:
                result = await to_thread.run_sync(lambda: harness.run(message, session_id=resolved_session_id))
            except HarnessError as retry_exc:
                raise AgentRuntimeError("AGENT_CHAT_FAILED", f"dsh 会话执行失败：{retry_exc}") from retry_exc
            self._session_aliases[session_id] = resolved_session_id
        return result.session_id, result.final_response
