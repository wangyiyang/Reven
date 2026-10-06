"""Commit business changes, operation receipts and approval consumption together."""

from typing import cast
from uuid import UUID

from fastmcp.exceptions import ToolError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.context import AgentContext
from reven.agent.models import AgentApproval, AgentOperation, AgentRun
from reven.agent.persistence_types import (
    ApprovalStatus,
    OperationStatus,
    RunStatus,
    arguments_hash,
    canonical_arguments,
)
from reven.agent.tool_confirmations import confirmation_target
from reven.agent.tool_definition import ToolDefinition
from reven.agent.tool_errors import AgentOperationConflictError, AgentToolApprovalError, AgentToolContextError
from reven.agent.tools_rss import KeywordEmbeddingHooks, RssKeywordTools
from reven.scheduling import utc_now


class ToolExecutor:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        embedding_refresher: KeywordEmbeddingHooks | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._rss_tools = RssKeywordTools(session_factory, embedding_refresher)

    async def execute(
        self, definition: ToolDefinition, arguments: dict[str, object], context: AgentContext, tool_call_id: str
    ) -> object:
        if not isinstance(context, AgentContext) or not tool_call_id or len(tool_call_id) > 256:
            raise AgentToolContextError()
        normalized = definition.canonical_arguments(arguments)
        if not definition.spec.is_write:
            result, _ = await definition.invoke(normalized)
            return result
        result = await self._write(definition, normalized, context, tool_call_id)
        if definition.spec.refresh_embedding:
            result = await self._refresh_embedding(result, context.run_id, tool_call_id)
        return result["output"]

    async def _write(
        self, definition: ToolDefinition, arguments: dict[str, object], context: AgentContext, tool_call_id: str
    ) -> dict[str, object]:
        fingerprint = arguments_hash(arguments)
        async with self._session_factory() as session, session.begin():
            run = await self._lock_run(session, context)
            operation = await session.scalar(
                select(AgentOperation)
                .where(AgentOperation.run_id == run.id, AgentOperation.tool_call_id == tool_call_id)
                .with_for_update()
            )
            if operation is not None:
                return self._saved_result(operation, definition.name, fingerprint)
            enabled_names = run.snapshot.get("tool_names")
            if (
                run.status != RunStatus.RUNNING
                or not isinstance(enabled_names, list)
                or definition.name not in enabled_names
            ):
                raise AgentToolContextError()
            approval = None
            if definition.spec.requires_confirmation:
                approval = await self._approval(session, run, tool_call_id, definition, arguments, fingerprint)
            output, entities = await definition.invoke(arguments, session=session)
            result = canonical_arguments({"output": output, "entities": entities})
            session.add(
                AgentOperation(
                    run_id=run.id,
                    tool_call_id=tool_call_id,
                    tool_name=definition.name,
                    args_hash=fingerprint,
                    args=arguments,
                    result=result,
                    status=OperationStatus.COMMITTED,
                )
            )
            if approval is not None:
                approval.status = ApprovalStatus.CONSUMED
                approval.consumed_at = utc_now()
            await session.flush()
        return result

    async def _lock_run(self, session: AsyncSession, context: AgentContext) -> AgentRun:
        run = await session.scalar(select(AgentRun).where(AgentRun.id == context.run_id).with_for_update())
        if run is None or run.owner_id != context.owner_id or run.session_id != context.session_id:
            raise AgentToolContextError()
        return run

    async def is_rejected_call(
        self, definition: ToolDefinition, arguments: dict[str, object], context: AgentContext, tool_call_id: str
    ) -> bool:
        if not definition.spec.requires_confirmation:
            return False
        fingerprint = arguments_hash(definition.canonical_arguments(arguments))
        async with self._session_factory() as session:
            approval = await session.scalar(
                select(AgentApproval)
                .join(AgentRun)
                .where(
                    AgentRun.id == context.run_id,
                    AgentRun.owner_id == context.owner_id,
                    AgentRun.session_id == context.session_id,
                    AgentApproval.tool_call_id == tool_call_id,
                    AgentApproval.tool_name == definition.name,
                    AgentApproval.args_hash == fingerprint,
                    AgentApproval.status == ApprovalStatus.REJECTED,
                )
            )
            return approval is not None

    @staticmethod
    def _saved_result(operation: AgentOperation, name: str, fingerprint: str) -> dict[str, object]:
        if (
            operation.tool_name != name
            or operation.args_hash != fingerprint
            or arguments_hash(operation.args) != fingerprint
            or operation.status != OperationStatus.COMMITTED
            or "output" not in operation.result
        ):
            raise AgentOperationConflictError()
        return dict(operation.result)

    async def _approval(
        self,
        session: AsyncSession,
        run: AgentRun,
        tool_call_id: str,
        definition: ToolDefinition,
        arguments: dict[str, object],
        fingerprint: str,
    ) -> AgentApproval:
        approval = await session.scalar(
            select(AgentApproval)
            .where(AgentApproval.run_id == run.id, AgentApproval.tool_call_id == tool_call_id)
            .with_for_update()
        )
        if (
            approval is None
            or approval.status != ApprovalStatus.APPROVED
            or approval.tool_name != definition.name
            or approval.args_hash != fingerprint
            or arguments_hash(approval.args) != fingerprint
        ):
            raise AgentToolApprovalError()
        try:
            target = await confirmation_target(session, definition.name, arguments, lock=True)
        except ToolError as exc:
            raise AgentToolApprovalError() from exc
        if target.fingerprint != approval.target_hash:
            raise AgentToolApprovalError()
        return approval

    async def _refresh_embedding(self, result: dict[str, object], run_id: UUID, tool_call_id: str) -> dict[str, object]:
        payload = result["output"]
        if not isinstance(payload, dict) or payload.get("embedding_status") != "pending":
            return result
        refreshed = await self._rss_tools.refresh_result(cast(dict[str, object], payload))
        if refreshed == payload:
            return result
        async with self._session_factory() as session, session.begin():
            operation = await session.scalar(
                select(AgentOperation)
                .where(AgentOperation.run_id == run_id, AgentOperation.tool_call_id == tool_call_id)
                .with_for_update()
            )
            if operation is None:
                raise AgentOperationConflictError()
            operation.result = {**operation.result, "output": refreshed}
            result = dict(operation.result)
        return result
