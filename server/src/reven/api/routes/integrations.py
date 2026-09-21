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
    IntegrationPut,
    IntegrationResponse,
    to_response,
)
from reven.config import get_settings
from reven.integrations.agent_llm.service import register_agent_llm_adapter
from reven.integrations.embedding.service import register_embedding_adapter
from reven.integrations.feishu_bot.service import register_feishu_bot_adapter
from reven.integrations.service import IntegrationError, IntegrationService
from reven.integrations.translation.aliyun import register_aliyun_adapter
from reven.integrations.translation.baidu import register_baidu_adapter
from reven.security.secrets import SecretBox

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

# 显式注册连接测试适配器，使 POST /api/integrations/{provider}/test 可用
register_feishu_bot_adapter()
register_baidu_adapter()
register_aliyun_adapter()
register_embedding_adapter()
register_agent_llm_adapter()


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(factory, async_sessionmaker):
        raise RuntimeError("app.state.session_factory 未初始化")
    return factory


async def get_session(
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _secret_box() -> SecretBox:
    return SecretBox.from_base64(get_settings().reven_master_key.get_secret_value())


def _ensure_known_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise IntegrationError(
            status_code=404,
            code="INTEGRATION_PROVIDER_UNKNOWN",
            message=f"不支持的集成：{provider}",
        )


def _error_response(exc: IntegrationError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})


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


@router.get("", response_model=list[IntegrationResponse])
async def list_integrations(session: SessionDep) -> list[IntegrationResponse]:
    service = IntegrationService(session, _secret_box())
    integrations = await service.list_integrations()
    return [to_response(integration) for integration in integrations if integration.provider in PROVIDERS]


@router.get("/{provider}", response_model=IntegrationResponse)
async def get_integration(provider: str, session: SessionDep) -> IntegrationResponse | JSONResponse:
    try:
        _ensure_known_provider(provider)
        integration = await IntegrationService(session, _secret_box()).get_integration(provider)
    except IntegrationError as exc:
        return _error_response(exc)
    return to_response(integration)


@router.put("/{provider}", response_model=IntegrationResponse)
async def put_integration(provider: str, request: Request, session: SessionDep) -> IntegrationResponse | JSONResponse:
    try:
        _ensure_known_provider(provider)
        body = await _parse_put_body(provider, request)
    except IntegrationError as exc:
        return _error_response(exc)
    service = IntegrationService(session, _secret_box())
    integration = await service.upsert_integration(
        provider=provider,
        public_config=body.public_config.model_dump(mode="json", exclude_none=True),
        secret=body.secret.model_dump(exclude_none=True) if body.secret is not None else None,
    )
    await session.commit()
    _reload_feishu_bot_supervisor(request, provider)
    return to_response(integration)


@router.delete("/{provider}/secret", response_model=IntegrationResponse)
async def delete_secret(provider: str, request: Request, session: SessionDep) -> IntegrationResponse | JSONResponse:
    try:
        _ensure_known_provider(provider)
        integration = await IntegrationService(session, _secret_box()).delete_secret(provider)
    except IntegrationError as exc:
        return _error_response(exc)
    await session.commit()
    _reload_feishu_bot_supervisor(request, provider)
    return to_response(integration)


@router.post("/{provider}/test", response_model=IntegrationResponse)
async def test_connection(provider: str, session: SessionDep) -> IntegrationResponse | JSONResponse:
    try:
        _ensure_known_provider(provider)
        integration = await IntegrationService(session, _secret_box()).run_connection_test(provider)
    except IntegrationError as exc:
        return _error_response(exc)
    await session.commit()
    return to_response(integration)
