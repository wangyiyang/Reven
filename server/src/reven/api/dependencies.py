"""Shared API dependencies and typed service injection points."""

from collections.abc import AsyncIterator
from typing import Annotated, Literal, Protocol, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.context import ADMIN_ACTOR, AgentActor
from reven.agent.service_types import AgentTurn, ConfigurationState, RunState
from reven.config import Settings
from reven.rss.review_service import CandidateReviewService


class AgentChatService(Protocol):
    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        *,
        actor: AgentActor = ADMIN_ACTOR,
        request_key: str | None = None,
        wait_timeout_seconds: float | None = None,
    ) -> AgentTurn: ...

    async def get_configuration(self) -> ConfigurationState: ...

    async def update_configuration(self, prompt: str, tool_names: list[str]) -> ConfigurationState: ...

    async def get_revision(self, revision_id: UUID) -> ConfigurationState: ...

    async def history(self, session_id: str, *, actor: AgentActor = ADMIN_ACTOR) -> tuple[RunState, ...]: ...

    async def get_run(
        self, run_id: UUID, *, actor: AgentActor = ADMIN_ACTOR, session_id: str | None = None
    ) -> RunState: ...

    async def resolve_approval(
        self,
        approval_id: UUID,
        decision: Literal["approve", "reject"],
        session_id: str,
        *,
        actor: AgentActor = ADMIN_ACTOR,
    ) -> RunState: ...

    async def resume_run(
        self, run_id: UUID, *, actor: AgentActor = ADMIN_ACTOR, session_id: str | None = None
    ) -> AgentTurn: ...


def get_agent_service(request: Request) -> AgentChatService:
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise RuntimeError("Agent 服务未初始化")
    return cast(AgentChatService, service)


AgentServiceDep = Annotated[AgentChatService, Depends(get_agent_service)]


def get_agent_actor(request: Request) -> AgentActor:
    if getattr(request.state, "authenticated_owner_id", None) != ADMIN_ACTOR.owner_id:
        raise HTTPException(status_code=401, detail="未认证的 Agent 请求")
    return ADMIN_ACTOR


AgentActorDep = Annotated[AgentActor, Depends(get_agent_actor)]


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


def get_app_settings(request: Request) -> Settings:
    """组合根装配的 Settings 单例（app.state.settings）；未初始化（无配置降级启动）时显式失败。"""
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise RuntimeError("app.state.settings 未初始化")
    return settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


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
