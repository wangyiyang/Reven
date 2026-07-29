"""Immediate Notion synchronization commands."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from reven.api.routes.integrations import get_session_factory
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


@router.post("/api/sync/notion", response_model=SyncResult)
async def sync_notion(service: SyncServiceDep) -> SyncResult:
    return await service.sync_once()


@router.post("/api/articles/{article_id}/sync", response_model=SyncResult)
async def sync_article(article_id: UUID, service: SyncServiceDep) -> SyncResult:
    return await service.sync_page(article_id)
