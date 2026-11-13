"""Agent 客户端抽象与远程 Worker 客户端实现。"""

import logging
from typing import Protocol

import httpx

from reven.agent.errors import AgentModelUnavailableError, AgentNotConfiguredError, AgentRuntimeError

logger = logging.getLogger(__name__)


class AgentRuntimeProtocol(Protocol):
    """Agent 运行时通用接口契约，本地进程 AgentRuntime 与远程 RemoteAgentWorkerClient 均满足。"""

    @property
    def configured(self) -> bool: ...

    @property
    def available(self) -> bool: ...

    @property
    def default_model_ref(self) -> str | None: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def refresh(self) -> None: ...

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        *,
        model: str | None = None,
    ) -> tuple[str, str]: ...


class RemoteAgentWorkerClient:
    """通过 HTTP 连接独立 Agent 容器 Worker 的运行时客户端。"""

    def __init__(self, base_url: str, *, run_timeout_seconds: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._run_timeout_seconds = run_timeout_seconds
        self._http: httpx.AsyncClient | None = None
        self._default_model_ref: str | None = None
        self._available: bool = False
        self._configured: bool = True

    @property
    def configured(self) -> bool:
        return self._configured

    @property
    def available(self) -> bool:
        return self._available

    @property
    def default_model_ref(self) -> str | None:
        return self._default_model_ref

    async def start(self) -> None:
        self._http = httpx.AsyncClient(timeout=self._run_timeout_seconds)
        await self.refresh()

    async def refresh(self) -> None:
        """刷新远端 Worker 运行状态。"""
        if self._http is None:
            return
        try:
            resp = await self._http.get(f"{self.base_url}/internal/agent/health", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                self._default_model_ref = data.get("default_model_ref")
                self._available = bool(data.get("available", False))
                self._configured = bool(data.get("configured", True))
            else:
                self._available = False
        except Exception as exc:
            logger.warning("Agent Worker 连接不可用（url=%s, error_type=%s）", self.base_url, type(exc).__name__)
            self._available = False

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        *,
        model: str | None = None,
    ) -> tuple[str, str]:
        if self._http is None:
            raise AgentRuntimeError("AGENT_RUNTIME_UNAVAILABLE", "Agent Worker 客户端未初始化")
        if not self._available or not self._configured:
            await self.refresh()
        try:
            resp = await self._http.post(
                f"{self.base_url}/internal/agent/chat",
                json={"message": message, "session_id": session_id, "model": model},
                timeout=self._run_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise AgentRuntimeError("AGENT_CHAT_TIMEOUT", f"Agent Worker 执行超时（session_id={session_id}）") from exc
        except httpx.HTTPError as exc:
            raise AgentRuntimeError("AGENT_CHAT_FAILED", f"Agent Worker 通信失败（session_id={session_id}）") from exc

        if resp.status_code == 503:
            raise AgentNotConfiguredError()
        if resp.status_code == 404:
            raise AgentModelUnavailableError(model or "")
        if resp.status_code != 200:
            error_data = resp.json() if resp.headers.get("content-type") == "application/json" else {}
            code = error_data.get("code", "AGENT_RUNTIME_UNAVAILABLE")
            msg = error_data.get("message", f"Agent Worker 错误: {resp.status_code}")
            raise AgentRuntimeError(code, msg)

        data = resp.json()
        return data["session_id"], data["response"]
