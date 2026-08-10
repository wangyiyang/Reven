"""Shared API dependencies and typed service injection points."""

from collections.abc import AsyncIterator
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(factory, async_sessionmaker):
        raise RuntimeError("数据库会话工厂未初始化")
    return factory


async def get_session(
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session


SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


class WechatPreviewService(Protocol):
    async def render_current(self, article_id: UUID) -> str: ...


def get_preview_service(request: Request) -> WechatPreviewService:
    service = getattr(request.app.state, "wechat_preview_service", None)
    if service is None:
        from reven.config import get_settings
        from reven.publishing.wechat.preview import ConfiguredWechatPreview

        service = ConfiguredWechatPreview(get_session_factory(request), get_settings().renderer_command)
    return service


PreviewServiceDep = Annotated[WechatPreviewService, Depends(get_preview_service)]
