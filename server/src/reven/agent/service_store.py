"""Agent 服务的短事务数据访问，不跨模型等待持有数据库会话。"""

from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.agent.config import AgentConfig
from reven.agent.context import AgentActor
from reven.agent.models import AgentConfigRevision, AgentOperation, AgentRun, AgentSession
from reven.agent.persistence_types import (
    AgentPersistenceError,
    AgentRequestConflictError,
    AgentRunNotFoundError,
    RunClaim,
    RunStatus,
    arguments_hash,
    message_hash,
)
from reven.agent.prompt import DEFAULT_AGENT_PROMPT
from reven.agent.repository import AgentRepository
from reven.agent.service_types import ApprovalState, ConfigurationState, OperationState, RunState
from reven.integrations.providers import model_ref_of


class AgentStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession], tool_names: Sequence[str]) -> None:
        self.factory = factory
        self.tool_names = tuple(tool_names)

    async def session(self, external_id: str, actor: AgentActor, *, create: bool = False) -> AgentSession | None:
        async with self.factory() as db, db.begin():
            repository = AgentRepository(db)
            if create:
                return await repository.ensure_session(external_id, owner_id=actor.owner_id, channel=actor.channel)
            return await repository.find_session(external_id, owner_id=actor.owner_id, channel=actor.channel)

    async def override(self, external_id: str, actor: AgentActor, ref: str | None) -> None:
        async with self.factory() as db, db.begin():
            repository = AgentRepository(db)
            session = await repository.ensure_session(external_id, owner_id=actor.owner_id, channel=actor.channel)
            await repository.set_override(session.id, ref, owner_id=actor.owner_id)

    async def configuration(self, revision_id: UUID | None = None) -> AgentConfigRevision:
        async with self.factory() as db, db.begin():
            repository = AgentRepository(db)
            if revision_id is not None:
                return await repository.get_revision(revision_id)
            return await repository.current_revision(
                default_prompt=DEFAULT_AGENT_PROMPT, default_tool_names=self.tool_names
            )

    async def update_configuration(self, prompt: str, tool_names: Sequence[str]) -> ConfigurationState:
        if len(prompt) > 32000:
            raise AgentPersistenceError("AGENT_CONFIG_INVALID", "Agent 指令不能超过 32000 字符")
        if not set(tool_names) <= set(self.tool_names):
            raise AgentPersistenceError("AGENT_TOOL_UNKNOWN", "配置包含未注册的 Agent 工具")
        async with self.factory() as db, db.begin():
            row = await AgentRepository(db).create_revision(prompt=prompt, tool_names=tool_names)
            return ConfigurationState(row.id, row.version, row.prompt, tuple(row.tool_names))

    async def existing_request(
        self, message: str, external_id: str | None, actor: AgentActor, request_key: str | None
    ) -> AgentRun | None:
        if request_key is None:
            return None
        async with self.factory() as db:
            repository = AgentRepository(db)
            run = await repository.find_request_run(
                owner_id=actor.owner_id, channel=actor.channel, request_key=request_key
            )
            if run is None:
                return None
            session = await repository.get_session(run.session_id, owner_id=actor.owner_id)
            if run.input_hash != message_hash(message) or (
                external_id is not None and session.external_id != external_id
            ):
                raise AgentRequestConflictError()
            return run

    async def claim(
        self,
        message: str,
        external_id: str | None,
        actor: AgentActor,
        request_key: str | None,
        config: AgentConfig,
        is_override: bool,
    ) -> RunClaim:
        async with self.factory() as db, db.begin():
            repository = AgentRepository(db)
            if request_key is not None:
                digest = arguments_hash({"owner": actor.owner_id, "channel": actor.channel, "key": request_key})
                lock_id = int.from_bytes(bytes.fromhex(digest[:16]), "big", signed=True)
                await db.execute(select(func.pg_advisory_xact_lock(lock_id)))
            existing = (
                None
                if request_key is None
                else await repository.find_request_run(
                    owner_id=actor.owner_id, channel=actor.channel, request_key=request_key
                )
            )
            if existing is not None and external_id is None:
                session = await repository.get_session(existing.session_id, owner_id=actor.owner_id)
            else:
                session = await repository.ensure_session(
                    external_id or uuid4().hex, owner_id=actor.owner_id, channel=actor.channel
                )
            revision = await repository.current_revision(
                default_prompt=DEFAULT_AGENT_PROMPT, default_tool_names=self.tool_names
            )
            snapshot: dict[str, object] = {
                "runtime_contract": 1,
                "provider": config.provider,
                "model": config.model,
                "base_url": config.base_url,
                "tool_names": list(revision.tool_names),
            }
            return await repository.create_run(
                session=session,
                revision=revision,
                message=message,
                model_ref=model_ref_of(config.provider, config.model),
                snapshot=snapshot,
                is_override=is_override,
                request_key=request_key,
            )

    async def raw_run(self, run_id: UUID, actor: AgentActor, external_id: str | None = None) -> AgentRun:
        async with self.factory() as db:
            repository = AgentRepository(db)
            session = (
                None
                if external_id is None
                else await repository.find_session(external_id, owner_id=actor.owner_id, channel=actor.channel)
            )
            if external_id is not None and session is None:
                raise AgentRunNotFoundError()
            run = await repository.get_run(run_id, owner_id=actor.owner_id, session_id=session.id if session else None)
            if run.channel != actor.channel:
                raise AgentRunNotFoundError()
            return run

    async def mark(
        self, run: AgentRun, status: RunStatus, *, response: str | None = None, error_code: str | None = None
    ) -> None:
        async with self.factory() as db, db.begin():
            await AgentRepository(db).mark_status(
                run.id, status, owner_id=run.owner_id, result=response, error_code=error_code
            )

    async def complete_checkpoint(self, run: AgentRun, response: str) -> None:
        async with self.factory() as db, db.begin():
            repository = AgentRepository(db)
            await repository.mark_status(run.id, RunStatus.RUNNING, owner_id=run.owner_id)
            await repository.mark_status(run.id, RunStatus.COMPLETED, owner_id=run.owner_id, result=response)

    async def state(self, run_id: UUID, actor: AgentActor, external_id: str | None = None) -> RunState:
        run = await self.raw_run(run_id, actor, external_id)
        async with self.factory() as db:
            repository = AgentRepository(db)
            session = await repository.get_session(run.session_id, owner_id=actor.owner_id)
            approvals = await repository.approvals_for_run(run.id, owner_id=actor.owner_id)
            operations = list(
                await db.scalars(
                    select(AgentOperation).where(AgentOperation.run_id == run.id).order_by(AgentOperation.created_at)
                )
            )
            return RunState(
                run.id,
                session.external_id,
                run.status,
                run.result,
                run.model_ref,
                run.is_override,
                run.error_code,
                tuple(
                    ApprovalState(a.id, a.tool_call_id, a.tool_name, a.args, a.target_summary, a.status)
                    for a in approvals
                ),
                tuple(OperationState(o.id, o.tool_call_id, o.tool_name, o.args, o.result) for o in operations),
                run.created_at,
                run.updated_at,
                run.message,
            )

    async def history(self, external_id: str, actor: AgentActor) -> tuple[RunState, ...]:
        session = await self.session(external_id, actor)
        if session is None:
            return ()
        async with self.factory() as db:
            runs = await AgentRepository(db).list_runs(session.id, owner_id=actor.owner_id)
        return tuple([await self.state(run.id, actor) for run in runs])

    async def model_refs_in_use(self) -> frozenset[str]:
        async with self.factory() as db:
            return frozenset(await AgentRepository(db).model_refs_in_use())

    async def interrupt_stale_runs(self) -> None:
        async with self.factory() as db, db.begin():
            await AgentRepository(db).interrupt_stale_runs()
