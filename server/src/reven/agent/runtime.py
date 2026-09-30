"""dsh 嵌入式运行时封装：单例生命周期 + 同步 SDK 的异步包装 + 按模型的 harness 缓存池。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

from anyio import to_thread
from deepseek_harness import DeepSeekHarness
from deepseek_harness.errors import HarnessError, JsonRpcError

from reven.agent.config import AgentConfig
from reven.agent.errors import AgentModelUnavailableError, AgentNotConfiguredError, AgentRuntimeError
from reven.agent.mcp_server import AgentMcpContext
from reven.integrations.credentials import model_ref_of

logger = logging.getLogger(__name__)

DSH_PATCH_FILE = Path(__file__).with_name("dsh.patch.yml")

# 模型引用（provider/model）→ 运行时配置；未注册/未启用返回 None。
# 由组合根装配（agent.config.resolve_agent_model_config），运行时不直接依赖凭证 seam。
ModelConfigResolver = Callable[[str], Awaitable[AgentConfig | None]]


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
    """持有 DeepSeekHarness 主实例与按模型缓存池，由 FastAPI lifespan 管理启动与关闭。

    SDK 为同步客户端，所有调用经 anyio.to_thread 包装，不阻塞事件循环；
    M0.4 已实测单实例多线程并发 run()（独立 session_id）真并发，不加全局锁。
    启动失败不抛出：置为不可用状态并记日志，应用照常启动（已拍板降级策略）。

    多模型（#163）：dsh SDK 的 run() 无 per-call model 参数，模型在 initialize 握手时
    固定——因此切换模型 = 换用按该模型配置拉起的另一个 harness 实例（缓存池懒加载，
    进程内每模型至多一个实例）。override 模型未注册/拉起失败时抛
    AgentModelUnavailableError，绝不静默回落默认模型（OpenClaw 严格语义）。
    """

    def __init__(
        self,
        config: AgentConfig | None,
        mcp: AgentMcpContext | None = None,
        *,
        model_resolver: ModelConfigResolver | None = None,
    ) -> None:
        self._config = config
        self._mcp = mcp
        self._model_resolver = model_resolver
        self._harness: DeepSeekHarness | None = None
        self._harness_pool: dict[str, DeepSeekHarness] = {}
        self._pool_locks: dict[str, asyncio.Lock] = {}
        self._start_failed = False
        self._session_aliases: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return self._config is not None

    @property
    def default_model_ref(self) -> str | None:
        """默认模型引用（主 harness 所用模型）；未配置时为 None。"""
        if self._config is None:
            return None
        return model_ref_of(self._config.provider, self._config.model)

    async def start(self) -> None:
        """拉起 dsh 子进程并完成 initialize 握手；未配置或已失败时为空操作。

        启动失败（含 HarnessError / OSError / TimeoutError 等任意异常）仅记录
        结构化日志并标记不可用，绝不阻止应用启动；chat 在该状态返回 502。
        仅拉起默认模型主实例；override 模型的池实例在首次使用时懒加载。
        """
        if self._config is None or self._harness is not None or self._start_failed:
            return
        try:
            self._harness = await to_thread.run_sync(_launch, self._config, self._mcp)
        except Exception as exc:
            self._start_failed = True
            logger.error("dsh 运行时启动失败，Agent 降级为不可用（error_type=%s）", type(exc).__name__)

    async def close(self) -> None:
        """关闭主实例与缓存池全部实例并复位失败标记；幂等，未启动时为空操作。"""
        harness = self._harness
        self._harness = None
        self._start_failed = False
        pool = tuple(self._harness_pool.values())
        self._harness_pool.clear()
        for instance in (harness, *pool):
            if instance is not None:
                await to_thread.run_sync(instance.close)

    async def chat(self, message: str, session_id: str | None = None, *, model: str | None = None) -> tuple[str, str]:
        """执行一轮对话，返回 (实际使用的 session_id, 最终响应文本)；session_id 缺省时生成。

        model 为可选模型引用（provider/model，来自 /model 指令的会话级 override）：
        缺省或命中默认模型时走主实例；否则经 model_resolver 校验后使用缓存池实例——
        未注册/未启用/拉起失败均抛 AgentModelUnavailableError，不静默降级。

        进程重启后 dsh 内存会话表清空而磁盘会话仍在，旧 session_id 会触发 "already exists"
        冲突：为该外部 id 重铸活跃 id（`<外部 id>~r<随机>`）重试一次并记录进程内别名，
        后续同外部 id 的消息经别名沿用同一活跃会话；别名不持久化，重启后首次冲突会再次重铸。
        """
        if self._config is None:
            raise AgentNotConfiguredError()
        if self._start_failed:
            raise AgentRuntimeError("AGENT_RUNTIME_UNAVAILABLE", "dsh 运行时启动失败，Agent 暂不可用")
        harness = await self._resolve_harness(model)
        return await self._run_turn(harness, message, session_id)

    async def _resolve_harness(self, model: str | None) -> DeepSeekHarness:
        """按模型引用选择 harness：默认走主实例，override 走缓存池（严格校验，不回落）。"""
        if model is None or model == self.default_model_ref:
            harness = self._harness
            if harness is None:
                raise AgentRuntimeError("AGENT_RUNTIME_NOT_STARTED", "dsh 运行时未启动")
            return harness
        if self._model_resolver is None:
            raise AgentModelUnavailableError(model, "运行时未接入模型注册表")
        config = await self._model_resolver(model)
        if config is None:
            raise AgentModelUnavailableError(model)
        return await self._harness_for(model, config)

    async def _harness_for(self, model_ref: str, config: AgentConfig) -> DeepSeekHarness:
        """缓存池取实例；未命中则按该模型配置懒拉起一个（同模型并发首用经 per-ref 锁去重）。"""
        cached = self._harness_pool.get(model_ref)
        if cached is not None:
            return cached
        lock = self._pool_locks.setdefault(model_ref, asyncio.Lock())
        async with lock:
            cached = self._harness_pool.get(model_ref)
            if cached is not None:
                return cached
            try:
                instance = await to_thread.run_sync(_launch, config, self._mcp)
            except Exception as exc:
                # 拉起失败只记异常类型：异常 message 可能含上游凭证回显，禁止进日志与错误消息
                logger.error("dsh 模型实例拉起失败（model=%s, error_type=%s）", model_ref, type(exc).__name__)
                raise AgentModelUnavailableError(model_ref, "运行时拉起失败") from exc
            self._harness_pool[model_ref] = instance
            return instance

    async def _run_turn(self, harness: DeepSeekHarness, message: str, session_id: str | None) -> tuple[str, str]:
        """在指定 harness 上执行一轮对话（含 already exists 冲突的重铸重试）。"""
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
