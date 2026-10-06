"""真实 PostgreSQL 验证会话归属、请求认领、配置版本和持久确认。"""

import asyncio
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from reven.agent.models import AgentApproval, AgentConfigRevision, AgentOperation, AgentRun, AgentSession
from reven.agent.persistence_types import (
    AgentApprovalConflictError,
    AgentApprovalNotFoundError,
    AgentPersistenceError,
    AgentRequestConflictError,
    AgentRunNotFoundError,
    AgentSessionBusyError,
    AgentSessionOwnershipError,
    AgentStateConflictError,
    ApprovalStatus,
    RunClaim,
    RunStatus,
    arguments_hash,
    canonical_arguments,
)
from reven.agent.repository import AgentRepository
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TOOLS = ("crm_customer_get", "crm_customer_delete")
MODEL_REF = "deepseek-official/demo-model"


@pytest.fixture
def agent_factory(db_session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_session.bind, expire_on_commit=False)


async def _session_revision(
    factory: async_sessionmaker[AsyncSession], external_id: str = "session", *, owner_id: str = "admin"
) -> tuple[AgentSession, AgentConfigRevision]:
    async with factory() as db:
        repository = AgentRepository(db)
        session = await repository.ensure_session(external_id, owner_id=owner_id, channel="rest")
        revision = await repository.current_revision(default_prompt="管理虚构测试客户", default_tool_names=TOOLS)
        await db.commit()
        return session, revision


async def _new_run(
    factory: async_sessionmaker[AsyncSession],
    session: AgentSession,
    revision: AgentConfigRevision,
    *,
    request_key: str | None = None,
    message: str = "记录一条跟进",
    model_ref: str = MODEL_REF,
) -> RunClaim:
    async with factory() as db:
        claim = await AgentRepository(db).create_run(
            session=session,
            revision=revision,
            message=message,
            model_ref=model_ref,
            snapshot={"protocol": "deepseek", "runtime_version": 1},
            is_override=False,
            request_key=request_key,
        )
        await db.commit()
        return claim


def test_argument_fingerprint_is_typed_and_order_independent() -> None:
    customer_id = uuid4()
    typed: dict[str, object] = {"customer_id": customer_id, "on": date(2026, 10, 6), "amount": Decimal("123.00")}
    serialized: dict[str, object] = {"amount": "123.00", "on": "2026-10-06", "customer_id": str(customer_id)}
    assert canonical_arguments(typed) == serialized
    assert arguments_hash(typed) == arguments_hash(serialized)
    assert arguments_hash({"name": "客户甲"}) != arguments_hash({"name": "客户乙"})
    with pytest.raises(TypeError):
        canonical_arguments({"session": object()})
    with pytest.raises(ValueError):
        arguments_hash({"amount": float("nan")})


@pytest.mark.anyio
async def test_session_owner_and_override_survive_repository_rebuild(
    agent_factory: async_sessionmaker[AsyncSession],
) -> None:
    session, _ = await _session_revision(agent_factory)
    async with agent_factory() as db:
        await AgentRepository(db).set_override(session.id, "openai/retired-model", owner_id="admin")
        await db.commit()
    async with agent_factory() as db:
        repository = AgentRepository(db)
        assert await repository.find_session("unknown", owner_id="admin", channel="rest") is None
        with pytest.raises(AgentSessionOwnershipError):
            await repository.find_session("session", owner_id="other", channel="rest")
        loaded = await repository.ensure_session("session", owner_id="admin", channel="rest")
        assert loaded.id == session.id and loaded.override_model_ref == "openai/retired-model"
        for owner, channel in (("feishu:other", "rest"), ("admin", "feishu")):
            with pytest.raises(AgentSessionOwnershipError):
                await repository.ensure_session("session", owner_id=owner, channel=channel)
        with pytest.raises(AgentSessionOwnershipError):
            await repository.get_session(session.id, owner_id="other")
        with pytest.raises(AgentSessionOwnershipError):
            await repository.ensure_session("", owner_id="admin", channel="rest")
        cleared = await repository.set_override(session.id, None, owner_id="admin")
        assert cleared.override_model_ref is None


@pytest.mark.anyio
async def test_concurrent_default_and_new_revisions_are_immutable(
    agent_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def load_default() -> AgentConfigRevision:
        async with agent_factory() as db:
            revision = await AgentRepository(db).current_revision(default_prompt="初始指令", default_tool_names=TOOLS)
            await db.commit()
            return revision

    defaults = await asyncio.gather(load_default(), load_default())
    assert defaults[0].id == defaults[1].id and defaults[0].version == 1
    async with agent_factory() as db:
        repository = AgentRepository(db)
        latest = await repository.create_revision(prompt="下一轮指令", tool_names=TOOLS[:1])
        await db.commit()
    async with agent_factory() as db:
        repository = AgentRepository(db)
        current = await repository.current_revision(default_prompt="不会覆盖", default_tool_names=())
        original = await repository.get_revision(defaults[0].id)
        assert current.id == latest.id and current.version == 2
        assert original.prompt == "初始指令" and original.tool_names == list(TOOLS)
        with pytest.raises(AgentPersistenceError, match="配置版本不存在"):
            await repository.get_revision(uuid4())


@pytest.mark.anyio
@pytest.mark.parametrize("prompt,tools", [(" ", TOOLS), ("指令", ("a", "a")), ("指令", ("",))])
async def test_invalid_revision_is_rejected(
    agent_factory: async_sessionmaker[AsyncSession], prompt: str, tools: tuple[str, ...]
) -> None:
    async with agent_factory() as db:
        with pytest.raises(AgentPersistenceError, match="不能为空"):
            await AgentRepository(db).create_revision(prompt=prompt, tool_names=tools)


@pytest.mark.anyio
async def test_concurrent_request_claim_and_conflicts(agent_factory: async_sessionmaker[AsyncSession]) -> None:
    session, revision = await _session_revision(agent_factory)
    claims = await asyncio.gather(
        _new_run(agent_factory, session, revision, request_key="message-1"),
        _new_run(agent_factory, session, revision, request_key="message-1"),
    )
    assert claims[0].run.id == claims[1].run.id
    assert sum(claim.created for claim in claims) == 1
    async with agent_factory() as db:
        repository = AgentRepository(db)
        await repository.mark_status(claims[0].run.id, RunStatus.RUNNING, owner_id="admin")
        await db.commit()
    replay = await _new_run(agent_factory, session, revision, request_key="message-1")
    assert not replay.created and replay.run.status == RunStatus.RUNNING
    with pytest.raises(AgentRequestConflictError):
        await _new_run(agent_factory, session, revision, request_key="message-1", message="不同输入")
    another, _ = await _session_revision(agent_factory, "another")
    with pytest.raises(AgentRequestConflictError):
        await _new_run(agent_factory, another, revision, request_key="message-1")
    with pytest.raises(AgentSessionBusyError) as busy:
        await _new_run(agent_factory, session, revision, request_key="message-2")
    assert busy.value.run_id == claims[0].run.id
    other_owner, _ = await _session_revision(agent_factory, "other-owner", owner_id="feishu:other")
    isolated = await _new_run(agent_factory, other_owner, revision, request_key="message-1")
    assert isolated.created


@pytest.mark.anyio
async def test_same_intent_without_request_key_is_a_new_run_after_completion(
    agent_factory: async_sessionmaker[AsyncSession],
) -> None:
    session, revision = await _session_revision(agent_factory)
    first = await _new_run(agent_factory, session, revision)
    async with agent_factory() as db:
        repository = AgentRepository(db)
        await repository.mark_status(first.run.id, RunStatus.RUNNING, owner_id="admin")
        await repository.mark_status(first.run.id, RunStatus.COMPLETED, owner_id="admin", result="已记录")
        await db.commit()
    second = await _new_run(agent_factory, session, revision)
    assert second.created and second.run.id != first.run.id
    async with agent_factory() as db:
        repository = AgentRepository(db)
        history = await repository.list_runs(session.id, owner_id="admin")
        assert [row.id for row in history] == [second.run.id, first.run.id]
        assert history[1].result == "已记录" and history[1].completed_at is not None
        with pytest.raises(AgentRunNotFoundError):
            await repository.get_run(first.run.id, owner_id="other")
        with pytest.raises(AgentRunNotFoundError):
            await repository.get_run(first.run.id, owner_id="admin", session_id=uuid4())
        with pytest.raises(AgentStateConflictError):
            await repository.mark_status(first.run.id, RunStatus.RUNNING, owner_id="admin")


@pytest.mark.anyio
@pytest.mark.parametrize("snapshot", [{"api_key": "fake-test-secret"}, {"nested": {"authorization": "fake"}}])
async def test_snapshot_cannot_persist_credentials(
    agent_factory: async_sessionmaker[AsyncSession], snapshot: dict[str, object]
) -> None:
    session, revision = await _session_revision(agent_factory)
    async with agent_factory() as db:
        with pytest.raises(AgentPersistenceError, match="不得保存凭据"):
            await AgentRepository(db).create_run(
                session=session,
                revision=revision,
                message="输入",
                model_ref=MODEL_REF,
                snapshot=snapshot,
                is_override=False,
            )
        assert await db.scalar(select(func.count()).select_from(AgentRun)) == 0


@pytest.mark.anyio
async def test_startup_interruption_preserves_approvals_and_model_guard(
    agent_factory: async_sessionmaker[AsyncSession],
) -> None:
    running_session, revision = await _session_revision(agent_factory, "running")
    queued_session, _ = await _session_revision(agent_factory, "queued")
    waiting_session, _ = await _session_revision(agent_factory, "waiting")
    done_session, _ = await _session_revision(agent_factory, "done")
    running = (await _new_run(agent_factory, running_session, revision)).run
    queued = (await _new_run(agent_factory, queued_session, revision)).run
    waiting = (await _new_run(agent_factory, waiting_session, revision)).run
    done = (await _new_run(agent_factory, done_session, revision, model_ref="openai/historical")).run
    async with agent_factory() as db:
        repository = AgentRepository(db)
        for run in (running, waiting, done):
            await repository.mark_status(run.id, RunStatus.RUNNING, owner_id="admin")
        await repository.mark_status(waiting.id, RunStatus.WAITING_APPROVAL, owner_id="admin")
        await repository.mark_status(done.id, RunStatus.COMPLETED, owner_id="admin", result="完成")
        await repository.set_override(done_session.id, "openai/idle-override", owner_id="admin")
        await db.commit()
    async with agent_factory() as db:
        repository = AgentRepository(db)
        assert await repository.interrupt_stale_runs() == 2
        await db.commit()
    async with agent_factory() as db:
        repository = AgentRepository(db)
        for run in (running, queued):
            assert (await repository.get_run(run.id, owner_id="admin")).status == RunStatus.INTERRUPTED
        assert (await repository.get_run(waiting.id, owner_id="admin")).status == RunStatus.WAITING_APPROVAL
        assert await repository.model_refs_in_use() == (MODEL_REF,)
        with pytest.raises(AgentSessionBusyError):
            await repository.create_run(
                session=running_session,
                revision=revision,
                message="抢跑",
                model_ref=MODEL_REF,
                snapshot={},
                is_override=False,
            )


async def _approval(
    factory: async_sessionmaker[AsyncSession], run: AgentRun, *, tool_call_id: str = "delete-1", position: int = 0
) -> AgentApproval:
    async with factory() as db:
        repository = AgentRepository(db)
        row = await repository.create_approval(
            run.id,
            owner_id=run.owner_id,
            tool_call_id=tool_call_id,
            tool_name="crm_customer_delete",
            args={"customer_id": "fictional-customer", "confirm_customer_name": "虚构客户"},
            target_summary="虚构客户；级联联系人和跟进",
            target_hash=arguments_hash({"customer": "虚构客户", "children": []}),
            position=position,
        )
        await db.commit()
        return row


@pytest.mark.anyio
async def test_approval_is_bound_to_original_owner_session_and_arguments(
    agent_factory: async_sessionmaker[AsyncSession],
) -> None:
    session, revision = await _session_revision(agent_factory)
    run = (await _new_run(agent_factory, session, revision)).run
    approval = await _approval(agent_factory, run)
    repeated = await _approval(agent_factory, run)
    assert repeated.id == approval.id and repeated.status == ApprovalStatus.PENDING
    async with agent_factory() as db:
        repository = AgentRepository(db)
        with pytest.raises(AgentApprovalConflictError):
            await repository.create_approval(
                run.id,
                owner_id="admin",
                tool_call_id="delete-1",
                tool_name="crm_customer_delete",
                args={"customer_id": "another"},
                target_summary=approval.target_summary,
                target_hash=approval.target_hash,
            )
        with pytest.raises(AgentApprovalNotFoundError):
            await repository.get_approval(approval.id, owner_id="other")
        with pytest.raises(AgentApprovalNotFoundError):
            await repository.resolve_approval(approval.id, "approve", owner_id="admin", session_id=uuid4())
        with pytest.raises(AgentStateConflictError):
            await repository.resolve_approval(approval.id, "approve", owner_id="admin", session_id=session.id)
        await repository.mark_status(run.id, RunStatus.RUNNING, owner_id="admin")
        await repository.mark_status(run.id, RunStatus.WAITING_APPROVAL, owner_id="admin")
        await db.commit()
    async with agent_factory() as db:
        repository = AgentRepository(db)
        approved = await repository.resolve_approval(approval.id, "approve", owner_id="admin", session_id=session.id)
        assert approved.status == ApprovalStatus.APPROVED and approved.decided_at is not None
        same = await repository.resolve_approval(approval.id, "approve", owner_id="admin", session_id=session.id)
        assert same.id == approved.id
        with pytest.raises(AgentApprovalConflictError):
            await repository.resolve_approval(approval.id, "reject", owner_id="admin", session_id=session.id)
        approved.status = ApprovalStatus.CONSUMED
        await db.commit()
    async with agent_factory() as db:
        consumed = await AgentRepository(db).resolve_approval(
            approval.id, "approve", owner_id="admin", session_id=session.id
        )
        assert consumed.status == ApprovalStatus.CONSUMED


@pytest.mark.anyio
async def test_approval_decision_races_have_one_winner(agent_factory: async_sessionmaker[AsyncSession]) -> None:
    session, revision = await _session_revision(agent_factory)
    run = (await _new_run(agent_factory, session, revision)).run
    first = await _approval(agent_factory, run, tool_call_id="first", position=1)
    second = await _approval(agent_factory, run, tool_call_id="second", position=0)
    async with agent_factory() as db:
        repository = AgentRepository(db)
        await repository.mark_status(run.id, RunStatus.RUNNING, owner_id="admin")
        await repository.mark_status(run.id, RunStatus.WAITING_APPROVAL, owner_id="admin")
        await db.commit()

    async def decide(decision: str) -> str:
        async with agent_factory() as db:
            row = await AgentRepository(db).resolve_approval(
                first.id,
                decision,
                owner_id="admin",
                session_id=session.id,  # type: ignore[arg-type]
            )
            await db.commit()
            return row.status

    results = await asyncio.gather(decide("approve"), decide("reject"), return_exceptions=True)
    assert sum(isinstance(result, AgentApprovalConflictError) for result in results) == 1
    async with agent_factory() as db:
        repository = AgentRepository(db)
        rows = await repository.approvals_for_run(run.id, owner_id="admin")
        assert [row.id for row in rows] == [second.id, first.id]
        assert len(await repository.approvals_for_run(run.id, owner_id="admin", pending_only=True)) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("drift", ["target_hash", "target_summary", "tool_name", "position"])
async def test_existing_approval_rejects_target_and_action_drift(
    agent_factory: async_sessionmaker[AsyncSession], drift: str
) -> None:
    session, revision = await _session_revision(agent_factory)
    run = (await _new_run(agent_factory, session, revision)).run
    approval = await _approval(agent_factory, run)
    async with agent_factory() as db:
        with pytest.raises(AgentApprovalConflictError):
            await AgentRepository(db).create_approval(
                run.id,
                owner_id="admin",
                tool_call_id=approval.tool_call_id,
                tool_name="talent_delete" if drift == "tool_name" else approval.tool_name,
                args=approval.args,
                target_summary="目标名称相同但影响不同" if drift == "target_summary" else approval.target_summary,
                target_hash=arguments_hash({"children": ["replacement"]})
                if drift == "target_hash"
                else approval.target_hash,
                position=1 if drift == "position" else approval.position,
            )
    async with agent_factory() as db:
        loaded = await AgentRepository(db).get_approval(approval.id, owner_id="admin", session_id=session.id)
        assert loaded.target_hash == approval.target_hash and loaded.status == ApprovalStatus.PENDING


@pytest.mark.anyio
async def test_database_rejects_duplicate_operation_and_forged_run_owner(
    agent_factory: async_sessionmaker[AsyncSession],
) -> None:
    session, revision = await _session_revision(agent_factory)
    run = (await _new_run(agent_factory, session, revision)).run
    receipt = {
        "run_id": run.id,
        "tool_call_id": "tool-1",
        "tool_name": "crm_customer_create",
        "args_hash": arguments_hash({"name": "虚构客户"}),
        "args": {"name": "虚构客户"},
        "result": {"output": "创建成功", "entities": {"customer_id": str(uuid4())}},
    }
    async with agent_factory() as db:
        db.add(AgentOperation(**receipt))
        await db.commit()
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(AgentOperation(**receipt))
                await db.flush()
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(
                    AgentRun(
                        session_id=session.id,
                        owner_id="other",
                        channel="rest",
                        input_hash="a" * 64,
                        message="伪造",
                        revision_id=revision.id,
                        snapshot={},
                        model_ref=MODEL_REF,
                        status=RunStatus.COMPLETED,
                    )
                )
                await db.flush()
    async with agent_factory() as db:
        assert await db.scalar(select(func.count()).select_from(AgentOperation)) == 1
