"""Immediate Notion synchronization commands."""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.api.routes.integrations import get_session_factory
from reven.config import get_settings
from reven.integrations.notion.client import NotionClient
from reven.integrations.notion.service import NOTION_BASE_URL, REQUEST_TIMEOUT
from reven.integrations.notion.sync import NotionSyncService, SyncResult
from reven.integrations.repository import IntegrationRepository
from reven.integrations.service import public_config_without_hint
from reven.security.secrets import SecretBox, SecretBoxError

router = APIRouter(tags=["sync"])


async def get_notion_sync_service(request: Request) -> AsyncIterator[NotionSyncService]:
    session_factory = get_session_factory(request)
    token, data_source_id = await _load_notion_config(session_factory)
    async with httpx.AsyncClient(base_url=NOTION_BASE_URL, timeout=REQUEST_TIMEOUT) as http:
        yield NotionSyncService(session_factory, NotionClient(token=token, http=http), data_source_id)


async def _load_notion_config(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[str, str]:
    async with session_factory() as session:
        integration = await IntegrationRepository(session).get_by_provider("notion")
    if integration is None or integration.encrypted_secret is None:
        raise HTTPException(status_code=409, detail="Notion 集成或 Token 未配置")
    config = public_config_without_hint(integration)
    data_source_id = config.get("data_source_id")
    if not isinstance(data_source_id, str) or not data_source_id:
        raise HTTPException(status_code=409, detail="Notion data_source_id 未配置")
    try:
        secrets = SecretBox.from_base64(get_settings().reven_master_key.get_secret_value()).decrypt(
            integration.encrypted_secret
        )
    except SecretBoxError as exc:
        raise HTTPException(status_code=500, detail="Notion Token 密文无法解密") from exc
    token = secrets.get("token")
    if not token:
        raise HTTPException(status_code=409, detail="Notion Token 未配置")
    return token, data_source_id


SyncServiceDep = Annotated[NotionSyncService, Depends(get_notion_sync_service)]


@router.post("/api/sync/notion", response_model=SyncResult)
async def sync_notion(service: SyncServiceDep) -> SyncResult:
    return await service.sync_once()


@router.post("/api/articles/{article_id}/sync", response_model=SyncResult)
async def sync_article(article_id: UUID, service: SyncServiceDep) -> SyncResult:
    return await service.sync_page(article_id)
