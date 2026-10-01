"""Integration settings routes.

Secrets can only be written, replaced or deleted — never read back. The host
app must set ``app.state.session_factory`` (an ``async_sessionmaker``) during
startup; Task 13 wires this router into ``create_app``.
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.api.schemas.integrations import (
    PROVIDERS,
    PUT_MODELS,
    AgentLlmIntegrationPut,
    AgentModelTestResponse,
    IntegrationPut,
    IntegrationResponse,
    SetDefaultModelRequest,
    TestConnectionRequest,
    to_response,
)
from reven.integrations.agent_llm.service import test_agent_llm_connection
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.embedding.service import test_embedding_connection
from reven.integrations.feishu_bot.service import test_feishu_bot_connection
from reven.integrations.models import Integration
from reven.integrations.providers import AGENT_LLM_PROVIDER
from reven.integrations.service import ConnectionTestAdapter, IntegrationError, IntegrationService
from reven.integrations.translation.aliyun import test_aliyun_translation
from reven.integrations.translation.baidu import test_baidu_translation

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

# 连接测试适配器映射：新增 provider 时在此加一行
CONNECTION_TEST_ADAPTERS: dict[str, ConnectionTestAdapter] = {
    "feishu_bot": test_feishu_bot_connection,
    "translate_baidu": test_baidu_translation,
    "translate_aliyun": test_aliyun_translation,
    "embedding": test_embedding_connection,
    "agent-llm": test_agent_llm_connection,
}


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(factory, async_sessionmaker):
        raise RuntimeError("app.state.session_factory 未初始化")
    return factory


def get_integration_credentials(request: Request) -> IntegrationCredentials:
    """lifespan 构建的集成凭证单例；未初始化（无库/密钥降级）时显式失败。"""
    credentials = getattr(request.app.state, "integration_credentials", None)
    if not isinstance(credentials, IntegrationCredentials):
        raise RuntimeError("app.state.integration_credentials 未初始化")
    return credentials


CredentialsDep = Annotated[IntegrationCredentials, Depends(get_integration_credentials)]


async def get_session(
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _service(credentials: IntegrationCredentials, session: AsyncSession) -> IntegrationService:
    return IntegrationService(session, credentials.secret_box, CONNECTION_TEST_ADAPTERS)


def _ensure_known_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise IntegrationError(
            status_code=404,
            code="INTEGRATION_PROVIDER_UNKNOWN",
            message=f"不支持的集成：{provider}",
        )


def _error_response(exc: IntegrationError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})


def _to_response(service: IntegrationService, integration: Integration) -> IntegrationResponse:
    """组装响应；agent-llm 额外填充 model_key_refs（有独立密钥的附加模型 ref，永不包含明文）。"""
    response = to_response(integration)
    if integration.provider == AGENT_LLM_PROVIDER:
        response.model_key_refs = service.agent_model_key_refs(integration)
    return response


def _model_refs_in_use(request: Request) -> frozenset[str]:
    """飞书会话 override 正在引用的模型 ref 快照；supervisor 缺失/不支持时降级为空集。"""
    supervisor = getattr(request.app.state, "feishu_bot_supervisor", None)
    getter = getattr(supervisor, "model_refs_in_use", None)
    if not callable(getter):
        return frozenset()
    refs = getter()
    return frozenset(refs) if refs else frozenset()


def _reload_feishu_bot_supervisor(request: Request, provider: str) -> None:
    """feishu_bot 配置变更后触发热更新：supervisor 不在（未启用入站能力）时静默跳过。"""
    if provider != "feishu_bot":
        return
    supervisor = getattr(request.app.state, "feishu_bot_supervisor", None)
    if supervisor is None:
        return
    supervisor.reload()


async def _parse_put_body(provider: str, request: Request) -> IntegrationPut:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise RequestValidationError(
            errors=[{"type": "json_invalid", "loc": ["body"], "msg": "请求体必须是合法的 JSON"}]
        ) from exc
    try:
        return PUT_MODELS[provider].model_validate(payload)
    except ValidationError as exc:
        raise RequestValidationError(errors=exc.errors()) from exc


async def _parse_test_body(request: Request) -> TestConnectionRequest:
    """连接测试可选请求体：空体视为缺省（测默认）；必须在 provider 校验之后调用。"""
    raw = await request.body()
    if not raw:
        return TestConnectionRequest()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RequestValidationError(
            errors=[{"type": "json_invalid", "loc": ["body"], "msg": "请求体必须是合法的 JSON"}]
        ) from exc
    try:
        return TestConnectionRequest.model_validate(payload)
    except ValidationError as exc:
        raise RequestValidationError(errors=exc.errors()) from exc


@router.get("", response_model=list[IntegrationResponse])
async def list_integrations(credentials: CredentialsDep, session: SessionDep) -> list[IntegrationResponse]:
    service = _service(credentials, session)
    integrations = await service.list_integrations()
    return [_to_response(service, integration) for integration in integrations if integration.provider in PROVIDERS]


@router.get("/{provider}", response_model=IntegrationResponse)
async def get_integration(
    provider: str, credentials: CredentialsDep, session: SessionDep
) -> IntegrationResponse | JSONResponse:
    try:
        _ensure_known_provider(provider)
        service = _service(credentials, session)
        integration = await service.get_integration(provider)
    except IntegrationError as exc:
        return _error_response(exc)
    return _to_response(service, integration)


@router.put("/{provider}", response_model=IntegrationResponse)
async def put_integration(
    provider: str, request: Request, credentials: CredentialsDep, session: SessionDep
) -> IntegrationResponse | JSONResponse:
    try:
        _ensure_known_provider(provider)
        body = await _parse_put_body(provider, request)
    except IntegrationError as exc:
        return _error_response(exc)
    service = _service(credentials, session)
    try:
        if provider == AGENT_LLM_PROVIDER:
            # agent-llm 走 merge 语义：models[] 写回 + api_key/model_keys 增量合并（#173）
            assert isinstance(body, AgentLlmIntegrationPut)
            integration = await service.upsert_agent_llm(
                public_config=body.public_config.model_dump(mode="json", exclude_none=True),
                api_key=body.secret.api_key if body.secret is not None else None,
                model_keys=body.secret.model_keys if body.secret is not None else None,
                refs_in_use=_model_refs_in_use(request),
            )
        else:
            integration = await service.upsert_integration(
                provider=provider,
                public_config=body.public_config.model_dump(mode="json", exclude_none=True),
                secret=body.secret.model_dump(exclude_none=True) if body.secret is not None else None,
            )
    except IntegrationError as exc:
        return _error_response(exc)
    await session.commit()
    _reload_feishu_bot_supervisor(request, provider)
    return _to_response(service, integration)


@router.delete("/{provider}/secret", response_model=IntegrationResponse)
async def delete_secret(
    provider: str, request: Request, credentials: CredentialsDep, session: SessionDep
) -> IntegrationResponse | JSONResponse:
    try:
        _ensure_known_provider(provider)
        service = _service(credentials, session)
        integration = await service.delete_secret(provider)
    except IntegrationError as exc:
        return _error_response(exc)
    await session.commit()
    _reload_feishu_bot_supervisor(request, provider)
    return _to_response(service, integration)


@router.post("/agent-llm/default-model", response_model=IntegrationResponse)
async def set_default_model(
    request: Request,
    credentials: CredentialsDep,
    session: SessionDep,
    body: SetDefaultModelRequest,
) -> IntegrationResponse | JSONResponse:
    """把 models[] 中的附加模型设为默认（服务端完成 key 材料交换，明文不出后端）。"""
    service = _service(credentials, session)
    try:
        integration = await service.set_default_agent_model(body.ref)
    except IntegrationError as exc:
        return _error_response(exc)
    await session.commit()
    return _to_response(service, integration)


@router.post("/{provider}/test", response_model=IntegrationResponse | AgentModelTestResponse)
async def test_connection(
    provider: str,
    request: Request,
    credentials: CredentialsDep,
    session: SessionDep,
) -> IntegrationResponse | AgentModelTestResponse | JSONResponse:
    """连接测试：缺省测集成默认配置（落行状态）；agent-llm 可按 model_ref 测单个模型。"""
    service = _service(credentials, session)
    try:
        _ensure_known_provider(provider)
        body = await _parse_test_body(request)
        if body.model_ref is not None:
            if provider != AGENT_LLM_PROVIDER:
                raise IntegrationError(
                    status_code=422,
                    code="MODEL_REF_UNSUPPORTED",
                    message=f"集成 {provider} 不支持按模型测试连接",
                )
            result = await service.test_agent_model(body.model_ref)
            await session.commit()
            return AgentModelTestResponse(
                ref=result.ref,
                success=result.success,
                message=result.message,
                latency_ms=result.latency_ms,
                tested_at=result.tested_at,
            )
        integration = await service.run_connection_test(provider)
    except IntegrationError as exc:
        return _error_response(exc)
    await session.commit()
    return _to_response(service, integration)
