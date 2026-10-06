"""真实图与数据库经过飞书确定性指令的重发、取消和批准流程。"""

import asyncio
from typing import cast

import pytest
from agent_service_support import DEFAULT_REF, ServiceRig
from feishu_dispatch_support import ReplyRecorder, submit, wait_replies
from reven.agent.context import AgentActor
from reven.agent.service import AgentService
from reven.crm.inputs import CustomerCreate
from reven.crm.repository import CrmRepository
from reven.crm.service import CrmService
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.chat_dispatcher import FALLBACK_TEXT, FeishuChatDispatcher
from sqlalchemy.ext.asyncio import async_sessionmaker

ACTOR = AgentActor("feishu:ou_boss", "feishu")
SESSION_ID = "feishu:oc_1:ou_boss"


@pytest.fixture
async def native_bot(db_session):
    rig = ServiceRig(async_sessionmaker(db_session.bind, expire_on_commit=False))
    service, _ = await rig.build()
    customer = await CrmService(db_session).create_customer(CustomerCreate(name="飞书待确认客户"))
    rig.tool_calls["删除飞书待确认客户"] = [
        {
            "name": "crm_customer_delete",
            "args": {"customer_id": str(customer.id), "confirm_customer_name": customer.name},
            "id": "feishu-delete",
            "type": "tool_call",
        }
    ]
    recorder = ReplyRecorder()
    dispatcher = FeishuChatDispatcher(rig.credentials, service, reply=recorder)  # type: ignore[arg-type]
    dispatcher.bind_loop(asyncio.get_running_loop())
    try:
        yield rig, service, recorder, dispatcher, customer
    finally:
        await rig.close()


async def _ask(native_bot):
    _, service, recorder, dispatcher, _ = native_bot
    await submit(dispatcher, "删除飞书待确认客户", message_id="om-original")
    await wait_replies(recorder, 2)
    run = (await service.history(SESSION_ID, actor=ACTOR))[0]
    assert run.status == "waiting_approval" and len(run.approvals) == 1
    assert f"确认 {run.approvals[0].id}" in recorder.calls[-1][1]
    return run


@pytest.mark.anyio
async def test_feishu_message_id_retry_attaches_pending_run_without_second_model_call(native_bot) -> None:
    rig, service, recorder, dispatcher, _ = native_bot
    first = await _ask(native_bot)
    await submit(dispatcher, "删除飞书待确认客户", message_id="om-original")
    await wait_replies(recorder, 4)
    history = await service.history(SESSION_ID, actor=ACTOR)
    assert len(history) == 1 and history[0].id == first.id
    assert len(rig.calls) == 1 and len(history[0].approvals) == 1
    assert recorder.calls[1][1] == recorder.calls[3][1]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("verb", "approval_status", "operation_count"), [("确认", "consumed", 1), ("取消", "rejected", 0)]
)
async def test_feishu_confirmation_scopes_original_group_and_preserves_repeat_decision(
    native_bot, db_session, verb, approval_status, operation_count
) -> None:
    rig, service, recorder, dispatcher, customer = native_bot
    run = await _ask(native_bot)
    approval_id = run.approvals[0].id
    await submit(dispatcher, f"{verb} {approval_id}", chat_id="oc_other", message_id="om-wrong-group")
    await wait_replies(recorder, 3)
    assert "不属于当前会话" in recorder.calls[-1][1]
    assert (await service.get_run(run.id, actor=ACTOR)).status == "waiting_approval"
    assert await CrmRepository(db_session).get_customer(customer.id) is not None
    await submit(dispatcher, f"{verb} {approval_id}", message_id="om-decision")
    await wait_replies(recorder, 4)
    assert "已完成" in recorder.calls[-1][1]
    await submit(dispatcher, f"{verb} {approval_id}", message_id="om-decision-repeat")
    await wait_replies(recorder, 5)
    final = await service.get_run(run.id, actor=ACTOR, session_id=SESSION_ID)
    assert final.status == "completed" and final.approvals[0].status == approval_status
    assert len(final.operations) == operation_count and len(rig.calls) == 2
    async with rig.factory() as verification:
        customer_after = await CrmRepository(verification).get_customer(customer.id)
    assert (customer_after is None) == (verb == "确认")


@pytest.mark.anyio
@pytest.mark.parametrize("verb", ["确认", "恢复"])
async def test_feishu_command_wait_budget_overrides_long_rest_wait_and_returns_original_run(native_bot, verb) -> None:
    rig, _, _, _, _ = native_bot
    run = await _ask(native_bot)
    _, runtime = rig.services[0]
    service = AgentService(
        runtime, cast(IntegrationCredentials, rig.credentials), session_factory=rig.factory, wait_timeout_seconds=1000
    )
    recorder = ReplyRecorder()
    dispatcher = FeishuChatDispatcher(rig.credentials, service, reply=recorder, timeout_seconds=0.01)  # type: ignore[arg-type]
    dispatcher.bind_loop(asyncio.get_running_loop())
    rig.block_ref = DEFAULT_REF
    try:
        pending = await service.resolve_approval(
            run.approvals[0].id, "approve", SESSION_ID, actor=ACTOR, wait_timeout_seconds=0.001
        )
        assert pending.status == "running"
        await asyncio.wait_for(rig.started.wait(), 2)
        identifier = run.approvals[0].id if verb == "确认" else run.id
        await submit(dispatcher, f"{verb} {identifier}", message_id="om-budget")
        await wait_replies(recorder, 1)
        assert str(run.id) in recorder.calls[0][1]
        assert recorder.calls[0][1] != FALLBACK_TEXT
    finally:
        rig.release.set()
        await service.execution.wait(run.id, 2)
        await service.close()
