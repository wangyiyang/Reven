"""默认模型热生效、持久 override 和每轮实际模型身份。"""

import asyncio
from dataclasses import replace

import pytest
from agent_service_support import DEFAULT_ENTRY, DEFAULT_REF, EXTRA_ENTRY, EXTRA_REF, ServiceRig
from reven.agent.errors import AgentModelUnavailableError


@pytest.mark.anyio
async def test_new_default_takes_effect_on_next_run_without_restart(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    before = await service.chat("旧默认", "sid")
    rig.credentials.entries = (replace(EXTRA_ENTRY, is_default=True),)
    state = await service.model_state("sid")
    after = await service.chat("新默认", "sid")
    assert before.model_ref == DEFAULT_REF and after.model_ref == EXTRA_REF
    assert state.default_ref == state.current_ref == EXTRA_REF
    assert not state.is_override and state.pending_default_ref is None
    assert [ref for ref, _ in rig.calls] == [DEFAULT_REF, EXTRA_REF]


@pytest.mark.anyio
async def test_model_choice_and_conversation_survive_service_and_pool_rebuild(rig: ServiceRig) -> None:
    first, runtime = await rig.build()
    await first.use_model("sid", EXTRA_REF)
    one = await first.chat("第一轮", "sid")
    await first.close()
    await runtime.close()
    second, _ = await rig.build()
    state = await second.model_state("sid")
    two = await second.chat("第二轮", "sid")
    assert state.current_ref == EXTRA_REF and state.is_override
    assert one.session_id == two.session_id == "sid"
    assert one.model_ref == two.model_ref == EXTRA_REF
    assert [message.content for message in rig.calls[-1][1]][1:] == ["第一轮", f"回复@{EXTRA_REF}", "第二轮"]
    assert len(await second.history("sid")) == 2


@pytest.mark.anyio
async def test_idle_deleted_override_is_preserved_and_needs_explicit_reset(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    await service.use_model("sid", EXTRA_REF)
    assert await service.model_refs_in_use() == frozenset()
    rig.credentials.entries = (DEFAULT_ENTRY,)
    state = await service.model_state("sid")
    assert state.current_ref == EXTRA_REF and state.is_override
    assert EXTRA_REF not in state.available_refs
    with pytest.raises(AgentModelUnavailableError):
        await service.chat("不可偷偷回默认", "sid")
    with pytest.raises(AgentModelUnavailableError):
        await service.use_model("sid", "unknown/model")
    assert not rig.calls
    await service.use_model("sid", DEFAULT_REF)
    turn = await service.chat("显式恢复默认", "sid")
    assert turn.model_ref == DEFAULT_REF and not turn.is_override


@pytest.mark.anyio
async def test_model_switch_during_execution_preserves_started_turn_identity(rig: ServiceRig) -> None:
    service, _ = await rig.build()
    await service.use_model("sid", EXTRA_REF)
    rig.block_ref = EXTRA_REF
    request = asyncio.create_task(service.chat("进行中", "sid"))
    await asyncio.wait_for(rig.started.wait(), 2)
    assert await service.model_refs_in_use() == frozenset({EXTRA_REF})
    await service.use_model("sid", DEFAULT_REF)
    assert await service.model_refs_in_use() == frozenset({EXTRA_REF})
    rig.release.set()
    started = await request
    assert started.model_ref == EXTRA_REF and started.is_override
    next_turn = await service.chat("下一轮", "sid")
    assert next_turn.model_ref == DEFAULT_REF and not next_turn.is_override
    assert await service.model_refs_in_use() == frozenset()


@pytest.mark.anyio
async def test_override_model_error_has_no_fallback_or_secret_in_state(
    rig: ServiceRig, caplog: pytest.LogCaptureFixture
) -> None:
    service, runtime = await rig.build()
    await service.use_model("sid", EXTRA_REF)
    rig.errors[EXTRA_REF] = RuntimeError("provider echoed api_key=test-leaked-secret")
    turn = await service.chat("上游失败", "sid")
    assert turn.run_id is not None
    state = await service.get_run(turn.run_id)
    assert state.status == "interrupted" and state.error_code == "AGENT_MODEL_UNAVAILABLE"
    assert [ref for ref, _ in rig.calls] == [EXTRA_REF]
    assert "test-leaked-secret" not in repr(state) + caplog.text + turn.response
    run = await service.store.raw_run(turn.run_id, service_actor())
    graph, _ = await service.execution.prepare(run)
    checkpoint = await runtime.state(graph, run)
    assert "test-leaked-secret" not in repr(checkpoint)
    assert (await service.model_state("sid")).current_ref == EXTRA_REF


def service_actor():
    from reven.agent.context import ADMIN_ACTOR

    return ADMIN_ACTOR
