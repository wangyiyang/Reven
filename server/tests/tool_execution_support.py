"""Trusted run fixtures and typed receipt assertions for transactional tools."""

from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

import pytest
from reven.agent.context import AgentContext
from reven.agent.models import AgentApproval, AgentConfigRevision, AgentOperation, AgentRun, AgentSession
from reven.agent.persistence_types import ApprovalStatus, RunStatus, arguments_hash, message_hash
from reven.agent.tool_registry import ToolRegistry
from reven.agent.tools_rss import KeywordEmbeddingHooks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class ToolRig:
    factory: async_sessionmaker[AsyncSession]
    registry: ToolRegistry
    context: AgentContext

    async def execute(self, name: str, args: dict[str, object], call_id: str) -> object:
        return await self.registry.execute(name, args, self.context, call_id)

    async def operation(self, call_id: str) -> AgentOperation | None:
        async with self.factory() as session:
            return await session.scalar(
                select(AgentOperation).where(
                    AgentOperation.run_id == self.context.run_id, AgentOperation.tool_call_id == call_id
                )
            )

    async def entity_id(self, call_id: str) -> UUID:
        operation = await self.operation(call_id)
        assert operation is not None
        entities = cast(dict[str, object], operation.result["entities"])
        records = cast(list[dict[str, str]], entities["records"])
        return UUID(records[0]["id"])

    async def approval(
        self, name: str, args: dict[str, object], call_id: str, *, status: ApprovalStatus = ApprovalStatus.APPROVED
    ) -> UUID:
        normalized = self.registry.canonical_tool_arguments(name, args)
        target = await self.registry.confirmation_target(name, normalized)
        async with self.factory() as session, session.begin():
            approval = AgentApproval(
                run_id=self.context.run_id,
                tool_call_id=call_id,
                tool_name=name,
                args=normalized,
                args_hash=arguments_hash(normalized),
                target_summary=target.summary,
                target_hash=target.fingerprint,
                status=status,
            )
            session.add(approval)
            await session.flush()
            return approval.id


async def build_tool_rig(
    db_session: AsyncSession, *, embedding_refresher: KeywordEmbeddingHooks | None = None
) -> ToolRig:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    registry = ToolRegistry(factory, embedding_refresher=embedding_refresher)
    revision = AgentConfigRevision(prompt="测试经营助手", tool_names=list(registry.tool_names))
    session = AgentSession(external_id=uuid4().hex, owner_id="test-admin", channel="rest")
    db_session.add_all([revision, session])
    await db_session.flush()
    run = AgentRun(
        session_id=session.id,
        owner_id=session.owner_id,
        channel=session.channel,
        input_hash=message_hash("test"),
        message="test",
        revision_id=revision.id,
        snapshot={"tool_names": list(registry.tool_names)},
        model_ref="deepseek-official/deepseek-v4-flash",
        status=RunStatus.RUNNING,
    )
    db_session.add(run)
    await db_session.commit()
    return ToolRig(factory, registry, AgentContext(session.owner_id, session.id, run.id))


@pytest.fixture
async def tool_rig(db_session: AsyncSession) -> ToolRig:
    return await build_tool_rig(db_session)
