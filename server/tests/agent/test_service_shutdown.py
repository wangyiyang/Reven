"""关闭开始后拒绝新运行，跨 claim 的请求仍保留可查询编号。"""

import asyncio
from typing import Any

import pytest
from agent_service_support import ServiceRig
from reven.agent.errors import AgentRuntimeError
from reven.agent.service_store import AgentStore


@pytest.mark.anyio
async def test_close_waits_for_inflight_claim_then_records_interrupted_without_launch(
    rig: ServiceRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _ = await rig.build()
    claimed, release = asyncio.Event(), asyncio.Event()
    original = AgentStore.claim

    async def delayed_claim(store: AgentStore, *args: Any, **kwargs: Any):
        result = await original(store, *args, **kwargs)
        claimed.set()
        await release.wait()
        return result

    monkeypatch.setattr(AgentStore, "claim", delayed_claim)
    request = asyncio.create_task(service.chat("claim 期间关闭", "sid"))
    await asyncio.wait_for(claimed.wait(), 2)
    closing = asyncio.create_task(service.close())
    await asyncio.sleep(0)
    assert not closing.done()
    with pytest.raises(AgentRuntimeError) as error:
        await service.chat("迟到的飞书请求", "other")
    assert error.value.code == "AGENT_SERVICE_CLOSING"
    release.set()
    turn = await request
    await closing
    assert turn.run_id is not None
    saved = await service.get_run(turn.run_id)
    assert saved.status == "interrupted" and saved.error_code == "AGENT_SERVICE_CLOSING"
    assert not service.execution.tasks and not rig.calls and not saved.operations
    assert await service.history("other") == ()
    with pytest.raises(AgentRuntimeError):
        service.execution.launch(await service.store.raw_run(turn.run_id, trusted_actor()), new_run=True)


@pytest.mark.anyio
async def test_late_bridge_after_service_close_has_zero_business_effect(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    rig.tool_calls["新客户"] = [{"name": "crm_customer_create", "id": "late", "args": {"name": "不应创建"}}]
    await service.close()
    with pytest.raises(AgentRuntimeError) as error:
        await service.chat("新客户", "sid", actor=trusted_actor())
    assert error.value.code == "AGENT_SERVICE_CLOSING"
    assert not rig.calls and not service.execution.tasks
    assert await service.history("sid") == ()


def trusted_actor():
    from reven.agent.context import ADMIN_ACTOR

    return ADMIN_ACTOR
