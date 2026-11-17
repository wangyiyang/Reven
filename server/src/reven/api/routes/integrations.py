"""Integration settings routes.

Secrets can only be written, replaced or deleted — never read back. The host
app must set ``app.state.session_factory`` (an ``async_sessionmaker``) during
startup; Task 13 wires this router into ``create_app``.
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.api.schemas.integrations import (
    PROVIDERS,
    PUT_MODELS,
    AgentLlmIntegrationPut,
    AgentModelTestResponse,
    BindingTestResponse,
    BindingTestStageResult,
    FeishuBitableBindingConfig,
    FeishuResourceBindingCreate,
    FeishuResourceBindingResponse,
    FeishuResourceBindingUpdate,
    IntegrationPut,
    IntegrationResponse,
    SetDefaultModelRequest,
    TestConnectionRequest,
    to_response,
)
from reven.integrations.agent_llm.service import test_agent_llm_connection
from reven.integrations.bindings import FeishuResourceBindingService
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.embedding.service import test_embedding_connection
from reven.integrations.feishu_bot.bitable import probe_rss_candidates_binding
from reven.integrations.feishu_bot.service import test_feishu_bot_connection
from reven.integrations.models import FeishuResourceBinding, Integration
from reven.integrations.providers import AGENT_LLM_PROVIDER
from reven.integrations.service import ConnectionTestAdapter, IntegrationError, IntegrationService
from reven.integrations.translation.aliyun import test_aliyun_translation
from reven.integrations.translation.baidu import test_baidu_translation
from reven.provider_clients import ProviderClients

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
    """读取 REST 与飞书共享的会话选择；服务未初始化时返回空集。"""
    service = getattr(request.app.state, "agent_service", None)
    getter = getattr(service, "model_refs_in_use", None)
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


# --- 飞书资源绑定（/api/integrations/feishu_bot/bindings） ---


def get_provider_clients(request: Request) -> ProviderClients:
    """lifespan 构建的 provider 客户端单例；未初始化（无库/密钥降级）时显式失败。"""
    clients = getattr(request.app.state, "provider_clients", None)
    if not isinstance(clients, ProviderClients):
        raise RuntimeError("app.state.provider_clients 未初始化")
    return clients


ProviderClientsDep = Annotated[ProviderClients, Depends(get_provider_clients)]


def _binding_response(binding: FeishuResourceBinding) -> FeishuResourceBindingResponse:
    return FeishuResourceBindingResponse(
        id=binding.id,
        resource_type=binding.resource_type,
        purpose=binding.purpose,
        config=dict(binding.config),
        enabled=binding.enabled,
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


def _bitable_config_of(binding: FeishuResourceBinding) -> FeishuBitableBindingConfig:
    """读回绑定 config 并复验 schema（写路径已校验，此处防御历史脏数据）。"""
    try:
        return FeishuBitableBindingConfig.model_validate(binding.config)
    except ValidationError as exc:
        raise IntegrationError(
            status_code=500,
            code="BINDING_CONFIG_INVALID",
            message="绑定配置数据无效，请更新或重新创建绑定",
        ) from exc


@router.get("/feishu_bot/bindings", response_model=list[FeishuResourceBindingResponse])
async def list_feishu_bindings(session: SessionDep) -> list[FeishuResourceBindingResponse]:
    bindings = await FeishuResourceBindingService(session).list_bindings()
    return [_binding_response(binding) for binding in bindings]


@router.post("/feishu_bot/bindings", response_model=FeishuResourceBindingResponse)
async def create_feishu_binding(
    body: FeishuResourceBindingCreate, session: SessionDep
) -> FeishuResourceBindingResponse | JSONResponse:
    service = FeishuResourceBindingService(session)
    try:
        binding = await service.create_binding(
            resource_type=body.resource_type,
            purpose=body.purpose,
            config=body.config.model_dump(mode="json"),
            enabled=body.enabled,
        )
    except IntegrationError as exc:
        return _error_response(exc)
    await session.commit()
    return _binding_response(binding)


@router.put("/feishu_bot/bindings/{binding_id}", response_model=FeishuResourceBindingResponse)
async def update_feishu_binding(
    binding_id: UUID, body: FeishuResourceBindingUpdate, session: SessionDep
) -> FeishuResourceBindingResponse | JSONResponse:
    service = FeishuResourceBindingService(session)
    try:
        binding = await service.update_config(binding_id, config=body.config.model_dump(mode="json"))
    except IntegrationError as exc:
        return _error_response(exc)
    await session.commit()
    return _binding_response(binding)


@router.post("/feishu_bot/bindings/{binding_id}/enable", response_model=FeishuResourceBindingResponse)
async def enable_feishu_binding(binding_id: UUID, session: SessionDep) -> FeishuResourceBindingResponse | JSONResponse:
    service = FeishuResourceBindingService(session)
    try:
        binding = await service.set_enabled(binding_id, enabled=True)
    except IntegrationError as exc:
        return _error_response(exc)
    await session.commit()
    return _binding_response(binding)


@router.post("/feishu_bot/bindings/{binding_id}/disable", response_model=FeishuResourceBindingResponse)
async def disable_feishu_binding(binding_id: UUID, session: SessionDep) -> FeishuResourceBindingResponse | JSONResponse:
    service = FeishuResourceBindingService(session)
    try:
        binding = await service.set_enabled(binding_id, enabled=False)
    except IntegrationError as exc:
        return _error_response(exc)
    await session.commit()
    return _binding_response(binding)


@router.delete(
    "/feishu_bot/bindings/{binding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_feishu_binding(binding_id: UUID, session: SessionDep) -> Response:
    service = FeishuResourceBindingService(session)
    try:
        await service.delete_binding(binding_id)
    except IntegrationError as exc:
        return _error_response(exc)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/feishu_bot/bindings/{binding_id}/test", response_model=BindingTestResponse)
async def test_feishu_binding(
    binding_id: UUID, session: SessionDep, clients: ProviderClientsDep
) -> BindingTestResponse | JSONResponse:
    """真实探针：字段校验 → 只读查询 → 创建测试记录 → 删除之；任一步失败返回失败阶段。"""
    service = FeishuResourceBindingService(session)
    try:
        binding = await service.get_binding(binding_id)
        config = _bitable_config_of(binding)
    except IntegrationError as exc:
        return _error_response(exc)
    async with clients.feishu_bot() as bot:
        if bot is None:
            return BindingTestResponse(
                success=False,
                failed_stage=None,
                stages=[],
                message="飞书应用机器人未启用或凭证不可用",
            )
        result = await probe_rss_candidates_binding(bot.api, app_token=config.app_token, table_id=config.table_id)
    return BindingTestResponse(
        success=result.success,
        failed_stage=result.failed_stage,
        stages=[
            BindingTestStageResult(stage=stage.stage, success=stage.success, message=stage.message)
            for stage in result.stages
        ],
    )
