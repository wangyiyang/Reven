"""Agent 调试对话路由（#123）；飞书等正式入口由 #119 接入同一服务层。"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from reven.agent.errors import AgentError, AgentNotConfiguredError
from reven.api.dependencies import AgentServiceDep
from reven.api.schemas.agent import AgentChatRequest, AgentChatResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatResponse)
async def chat(body: AgentChatRequest, service: AgentServiceDep) -> AgentChatResponse | JSONResponse:
    try:
        turn = await service.chat(body.message, body.session_id)
    except AgentNotConfiguredError as exc:
        return _error_response(503, exc)
    except AgentError as exc:
        return _error_response(502, exc)
    return AgentChatResponse(session_id=turn.session_id, response=turn.response)


def _error_response(status_code: int, exc: AgentError) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": exc.code, "message": exc.message})
