"""Agent 对话兼容入口、配置版本、运行查询与持久确认。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response
from fastapi.responses import JSONResponse

from reven.agent.errors import AgentError
from reven.api.dependencies import AgentActorDep, AgentServiceDep
from reven.api.schemas.agent import (
    AgentApprovalResolveRequest,
    AgentChatRequest,
    AgentChatResponse,
    AgentConfigurationPut,
    AgentConfigurationResponse,
    AgentResumeRequest,
    AgentRunResponse,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])
SessionQuery = Annotated[str | None, Query(min_length=1, max_length=128)]
RequestKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=256)]
_ERROR_STATUS = {
    "AGENT_NOT_CONFIGURED": 503,
    "AGENT_SESSION_FORBIDDEN": 403,
    "AGENT_RUN_NOT_FOUND": 404,
    "AGENT_APPROVAL_NOT_FOUND": 404,
    "AGENT_REVISION_NOT_FOUND": 404,
    "AGENT_REQUEST_CONFLICT": 409,
    "AGENT_SESSION_BUSY": 409,
    "AGENT_APPROVAL_CONFLICT": 409,
    "AGENT_STATE_CONFLICT": 409,
    "AGENT_RUN_UNRESUMABLE": 409,
    "AGENT_CONFIG_INVALID": 422,
    "AGENT_TOOL_UNKNOWN": 422,
    "AGENT_INPUT_INVALID": 422,
}


@router.post("/chat", response_model=AgentChatResponse)
async def chat(
    body: AgentChatRequest,
    service: AgentServiceDep,
    actor: AgentActorDep,
    response: Response,
    request_key: RequestKeyHeader = None,
) -> AgentChatResponse | JSONResponse:
    try:
        turn = await service.chat(body.message, body.session_id, actor=actor, request_key=request_key)
    except AgentError as exc:
        return _error_response(exc)
    if turn.run_id is not None:
        response.headers["X-Agent-Run-ID"] = str(turn.run_id)
    return AgentChatResponse(session_id=turn.session_id, response=turn.response)


@router.get("/config", response_model=AgentConfigurationResponse)
async def get_configuration(
    service: AgentServiceDep, _actor: AgentActorDep
) -> AgentConfigurationResponse | JSONResponse:
    try:
        return AgentConfigurationResponse.model_validate(await service.get_configuration())
    except AgentError as exc:
        return _error_response(exc)


@router.put("/config", response_model=AgentConfigurationResponse)
async def update_configuration(
    body: AgentConfigurationPut, service: AgentServiceDep, _actor: AgentActorDep
) -> AgentConfigurationResponse | JSONResponse:
    try:
        return AgentConfigurationResponse.model_validate(
            await service.update_configuration(body.prompt, body.tool_names)
        )
    except AgentError as exc:
        return _error_response(exc)


@router.get("/config/revisions/{revision_id}", response_model=AgentConfigurationResponse)
async def get_revision(
    revision_id: UUID, service: AgentServiceDep, _actor: AgentActorDep
) -> AgentConfigurationResponse | JSONResponse:
    try:
        return AgentConfigurationResponse.model_validate(await service.get_revision(revision_id))
    except AgentError as exc:
        return _error_response(exc)


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
async def get_run(
    run_id: UUID, service: AgentServiceDep, actor: AgentActorDep, session_id: SessionQuery = None
) -> AgentRunResponse | JSONResponse:
    try:
        return AgentRunResponse.model_validate(await service.get_run(run_id, actor=actor, session_id=session_id))
    except AgentError as exc:
        return _error_response(exc)


@router.get("/history", response_model=list[AgentRunResponse])
async def history(
    service: AgentServiceDep,
    actor: AgentActorDep,
    session_id: Annotated[str, Query(min_length=1, max_length=128)],
) -> list[AgentRunResponse] | JSONResponse:
    try:
        return [AgentRunResponse.model_validate(run) for run in await service.history(session_id, actor=actor)]
    except AgentError as exc:
        return _error_response(exc)


@router.post("/approvals/{approval_id}/resolve", response_model=AgentRunResponse)
async def resolve_approval(
    approval_id: UUID, body: AgentApprovalResolveRequest, service: AgentServiceDep, actor: AgentActorDep
) -> AgentRunResponse | JSONResponse:
    try:
        run = await service.resolve_approval(approval_id, body.decision, body.session_id, actor=actor)
        return AgentRunResponse.model_validate(run)
    except AgentError as exc:
        return _error_response(exc)


@router.post("/runs/{run_id}/resume", response_model=AgentChatResponse)
async def resume_run(
    run_id: UUID,
    service: AgentServiceDep,
    actor: AgentActorDep,
    response: Response,
    body: AgentResumeRequest | None = None,
) -> AgentChatResponse | JSONResponse:
    try:
        turn = await service.resume_run(run_id, actor=actor, session_id=body.session_id if body else None)
    except AgentError as exc:
        return _error_response(exc)
    if turn.run_id is not None:
        response.headers["X-Agent-Run-ID"] = str(turn.run_id)
    return AgentChatResponse(session_id=turn.session_id, response=turn.response)


def _error_response(exc: AgentError) -> JSONResponse:
    response = JSONResponse(
        status_code=_ERROR_STATUS.get(exc.code, 502), content={"code": exc.code, "message": exc.message}
    )
    run_id = getattr(exc, "run_id", None)
    if isinstance(run_id, UUID):
        response.headers["X-Agent-Run-ID"] = str(run_id)
    return response
