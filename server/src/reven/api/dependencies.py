"""Shared API dependencies and typed service injection points."""

from collections.abc import AsyncIterator
from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.rss.inbox import InboxPushResult


class AgentChatService(Protocol):
    async def chat(self, message: str, session_id: str | None = None) -> tuple[str, str]: ...


def get_agent_service(request: Request) -> AgentChatService:
    runtime = getattr(request.app.state, "agent_runtime", None)
    if runtime is None:
        raise RuntimeError("Agent 运行时未初始化")
    from reven.agent.service import AgentService

    return AgentService(runtime)


AgentServiceDep = Annotated[AgentChatService, Depends(get_agent_service)]


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
    return cast(WechatPreviewService, service)


PreviewServiceDep = Annotated[WechatPreviewService, Depends(get_preview_service)]


class RssInboxPusher(Protocol):
    async def push(self, item_id: UUID) -> InboxPushResult: ...


def get_rss_inbox_service(request: Request) -> RssInboxPusher:
    service = getattr(request.app.state, "rss_inbox_service", None)
    if service is None:
        raise RuntimeError("RSS Notion Inbox 服务未初始化")
    return cast(RssInboxPusher, service)


RssInboxServiceDep = Annotated[RssInboxPusher, Depends(get_rss_inbox_service)]


class RssEmbeddingRefresher(Protocol):
    async def refresh(self, *, force: bool = False) -> int: ...


def get_rss_embedding_refresher(request: Request) -> RssEmbeddingRefresher:
    service = getattr(request.app.state, "rss_embedding_refresher", None)
    if service is None:
        raise RuntimeError("RSS Embedding 服务未初始化")
    return cast(RssEmbeddingRefresher, service)


RssEmbeddingRefresherDep = Annotated[RssEmbeddingRefresher, Depends(get_rss_embedding_refresher)]
