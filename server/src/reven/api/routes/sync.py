"""Immediate Notion synchronization commands."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from reven.api.routes.integrations import get_session_factory
from reven.api.schemas.sync import ContentSyncRunResponse
from reven.content_sync.configured import ConfiguredContentSource
from reven.content_sync.requests import (
    ContentSyncRequestError,
    ContentSyncRequestService,
    SyncRunView,
)
from reven.integrations.notion.client import NotionClient
from reven.integrations.notion.configuration import (
    IntegrationConfigurationError,
    load_notion_config,
)
from reven.integrations.notion.service import NOTION_BASE_URL, REQUEST_TIMEOUT
from reven.integrations.notion.sync import NotionSyncService, SyncResult

router = APIRouter(tags=["sync"])


async def get_notion_sync_service(request: Request) -> AsyncIterator[NotionSyncService]:
    session_factory = get_session_factory(request)
    try:
        token, data_source_id = await load_notion_config(session_factory)
    except IntegrationConfigurationError as exc:
        status = 500 if exc.code == "INTEGRATION_SECRET_INVALID" else 409
        raise HTTPException(status_code=status, detail=exc.code) from exc
    async with httpx.AsyncClient(base_url=NOTION_BASE_URL, timeout=REQUEST_TIMEOUT) as http:
        yield NotionSyncService(session_factory, NotionClient(token=token, http=http), data_source_id)


SyncServiceDep = Annotated[NotionSyncService, Depends(get_notion_sync_service)]


def get_content_sync_request_service(request: Request) -> ContentSyncRequestService:
    factory = get_session_factory(request)
    return ContentSyncRequestService(factory, ConfiguredContentSource(factory))


ContentSyncRequestDep = Annotated[ContentSyncRequestService, Depends(get_content_sync_request_service)]


@router.post("/api/sync/notion", response_model=SyncResult)
async def sync_notion(service: SyncServiceDep) -> SyncResult:
    return await service.sync_once()


@router.post("/api/articles/{article_id}/sync", response_model=ContentSyncRunResponse, status_code=202)
async def sync_article(
    article_id: UUID,
    service: ContentSyncRequestDep,
) -> ContentSyncRunResponse | JSONResponse:
    try:
        result = await service.request(article_id)
    except ContentSyncRequestError as exc:
        status = 404 if exc.code == "ARTICLE_NOT_FOUND" else 409
        return JSONResponse(status_code=status, content={"code": exc.code, "message": exc.message})
    return _sync_run_response(result.run, created=result.created)


@router.get(
    "/api/articles/{article_id}/sync-runs/{run_id}",
    response_model=ContentSyncRunResponse,
)
async def get_content_sync_run(
    article_id: UUID,
    run_id: UUID,
    service: ContentSyncRequestDep,
) -> ContentSyncRunResponse | JSONResponse:
    run = await service.get_run(article_id, run_id)
    if run is None:
        return JSONResponse(status_code=404, content={"code": "SYNC_RUN_NOT_FOUND", "message": "同步任务不存在"})
    return _sync_run_response(run)


def _sync_run_response(run: SyncRunView, *, created: bool | None = None) -> ContentSyncRunResponse:
    return ContentSyncRunResponse(**run.__dict__, created=created)
