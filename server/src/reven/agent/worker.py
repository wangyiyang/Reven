"""独立 DSH Agent Worker 容器入口与内部 HTTP 服务。"""

import logging
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
    app.state.runtime = runtime
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
