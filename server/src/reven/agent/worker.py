"""独立 DSH Agent Worker 容器入口与内部 HTTP 服务。"""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from reven.agent.config import resolve_agent_config, resolve_agent_model_config
from reven.agent.errors import AgentError, AgentModelUnavailableError, AgentNotConfiguredError
from reven.agent.mcp_server import resolve_agent_mcp_context
from reven.agent.runtime import AgentRuntime, ModelConfigResolver
from reven.config import get_settings
from reven.db import create_session_factory
from reven.integrations.credentials import IntegrationCredentials

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    model: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    response: str


async def ensure_runtime_configured(app: FastAPI) -> None:
    """动态检查凭证并自愈 Worker 运行时配置。

    未就绪或未配置时每次调用均尝试重解析，一旦 DB 迁移完成或凭据就绪即可自动恢复；
    正常就绪后按 5 秒节流，兼顾近即时生效与轻量低开销。
    """
    runtime: AgentRuntime | None = getattr(app.state, "runtime", None)
    if runtime is None:
        return
    now = time.monotonic()
    last_check = getattr(app.state, "last_config_check", 0.0)
    if runtime.available and runtime.configured and (now - last_check < 5.0):
        return
    app.state.last_config_check = now
    settings = getattr(app.state, "settings", None)
    credentials = getattr(app.state, "credentials", None)
    if settings is None:
        return
    try:
        new_config = await resolve_agent_config(credentials, settings)
        await runtime.reload_config(new_config)
    except Exception as exc:
        logger.warning("Agent Worker 动态刷新配置失败（error_type=%s）", type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    factory = create_session_factory(settings)
    credentials: IntegrationCredentials | None = None
    try:
        credentials = IntegrationCredentials(factory, settings)
    except Exception as exc:
        logger.warning("Agent Worker 集成凭证加载失败（error_type=%s）", type(exc).__name__)

    mcp_context = resolve_agent_mcp_context(settings)
    config = await resolve_agent_config(credentials, settings)

    resolver: ModelConfigResolver | None = None
    if credentials is not None:
        resolver = partial(resolve_agent_model_config, credentials, settings)

    runtime = AgentRuntime(
        config,
        mcp=mcp_context,
        model_resolver=resolver,
        run_timeout_seconds=settings.agent_run_timeout_seconds,
    )
    app.state.settings = settings
    app.state.credentials = credentials
    app.state.runtime = runtime
    app.state.last_config_check = 0.0
    await runtime.start()

    try:
        yield
    finally:
        await runtime.close()
        engine = factory.kw.get("bind")
        if engine is not None and hasattr(engine, "dispose"):
            await engine.dispose()


app = FastAPI(title="Reven Agent Worker", lifespan=lifespan)


@app.get("/internal/agent/health")
async def health() -> dict[str, Any]:
    await ensure_runtime_configured(app)
    runtime: AgentRuntime | None = getattr(app.state, "runtime", None)
    if runtime is None:
        return {"status": "starting", "available": False, "configured": False, "default_model_ref": None}
    return {
        "status": "ok" if runtime.available else "degraded",
        "available": runtime.available,
        "configured": runtime.configured,
        "default_model_ref": runtime.default_model_ref,
    }


@app.post("/internal/agent/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    await ensure_runtime_configured(app)
    runtime: AgentRuntime | None = getattr(app.state, "runtime", None)
    if runtime is None:
        raise HTTPException(status_code=502, detail={"code": "AGENT_RUNTIME_UNAVAILABLE", "message": "Worker 未就绪"})
    try:
        session_id, response = await runtime.chat(request.message, request.session_id, model=request.model)
        return ChatResponse(session_id=session_id, response=response)
    except AgentNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc
    except AgentModelUnavailableError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": exc.message}) from exc
    except AgentError as exc:
        raise HTTPException(status_code=502, detail={"code": exc.code, "message": exc.message}) from exc


def main() -> None:
    import uvicorn

    uvicorn.run("reven.agent.worker:app", host="0.0.0.0", port=8001, log_level="info")


if __name__ == "__main__":
    main()
