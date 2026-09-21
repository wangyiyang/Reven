"""Shared API dependencies and typed service injection points."""

from collections.abc import AsyncIterator
from typing import Annotated, Protocol, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.rss.review_service import CandidateReviewService


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


def get_candidate_review_service(request: Request) -> CandidateReviewService:
    return CandidateReviewService(get_session_factory(request))


CandidateReviewServiceDep = Annotated[CandidateReviewService, Depends(get_candidate_review_service)]


class RssEmbeddingRefresher(Protocol):
    async def refresh(self, *, force: bool = False) -> int: ...


def get_rss_embedding_refresher(request: Request) -> RssEmbeddingRefresher:
    service = getattr(request.app.state, "rss_embedding_refresher", None)
    if service is None:
        raise RuntimeError("RSS Embedding 服务未初始化")
    return cast(RssEmbeddingRefresher, service)


RssEmbeddingRefresherDep = Annotated[RssEmbeddingRefresher, Depends(get_rss_embedding_refresher)]
