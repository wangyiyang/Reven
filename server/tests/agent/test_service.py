"""同一业务 interface 验证会话选择、真实执行身份与运行中默认。"""

import asyncio
from dataclasses import FrozenInstanceError, replace

import pytest
from agent_service_support import DEFAULT_ENTRY, DEFAULT_REF, EXTRA_ENTRY, EXTRA_REF, ServiceRig
from deepseek_harness.errors import HarnessError
from reven.agent.errors import AgentModelUnavailableError, AgentNotConfiguredError, AgentRuntimeError


@pytest.mark.anyio
async def test_model_refs_in_use_retains_shared_choice_until_all_sessions_restore(tmp_path, monkeypatch) -> None:
    rig = ServiceRig(tmp_path, monkeypatch)
    service, runtime = await rig.build()
    try:
        assert service.model_refs_in_use() == frozenset()
        await service.use_model("rest-session", EXTRA_REF)
        await service.use_model("feishu:chat:user", EXTRA_REF)
        snapshot = service.model_refs_in_use()
        assert snapshot == frozenset({EXTRA_REF})
        await service.use_model("rest-session", DEFAULT_REF)
        assert service.model_refs_in_use() == snapshot
        await service.use_model("feishu:chat:user", DEFAULT_REF)
        assert service.model_refs_in_use() == frozenset()
        assert snapshot == frozenset({EXTRA_REF})
    finally:
        await runtime.close()


@pytest.mark.anyio
async def test_saved_default_drift_keeps_active_default_and_allows_recovery(tmp_path, monkeypatch) -> None:
    rig = ServiceRig(tmp_path, monkeypatch)
    service, runtime = await rig.build()
    rig.credentials.entries = (replace(EXTRA_ENTRY, is_default=True),)
    state = await service.model_state("sid")
    assert state.default_ref == state.current_ref == DEFAULT_REF
    assert state.pending_default_ref == EXTRA_REF
    assert state.available_refs == (DEFAULT_REF, EXTRA_REF)
    assert not state.is_override

    switched = await service.use_model("sid", EXTRA_REF)
    assert switched.is_override
    turn = await service.chat("新默认仍是显式选择", "sid")
    assert turn.model_ref == EXTRA_REF and turn.is_override
    assert turn.response == f"回复@{EXTRA_REF}"
    restored = await service.use_model("sid", DEFAULT_REF)
    assert not restored.is_override
    turn = await service.chat("恢复启动默认", "sid")
    assert turn.model_ref == DEFAULT_REF and not turn.is_override
    assert rig.instances[0].calls == [("恢复启动默认", "sid")]
    await runtime.close()


@pytest.mark.anyio
async def test_switch_executes_selected_model_and_keeps_external_choice_after_remint(tmp_path, monkeypatch) -> None:
    rig = ServiceRig(tmp_path, monkeypatch)
    service, runtime = await rig.build()
    sid = "feishu:chat:user"
    state = await service.use_model(sid, EXTRA_REF)
    assert state.current_ref == EXTRA_REF and state.is_override
    assert len(rig.instances) == 1 and rig.instances[0].calls == []
    rig.conflict_ids.add(sid)
    first = await service.chat("第一问", sid)
    second = await service.chat("继续", sid)
    assert first.session_id.startswith(f"{sid}~r")
    assert second.session_id == first.session_id
    assert first.response == second.response == f"回复@{EXTRA_REF}"
    assert first.model_ref == EXTRA_REF and first.is_override
    assert rig.instances[0].calls == []
    assert rig.instances[1].calls == [("第一问", sid), ("第一问", first.session_id), ("继续", first.session_id)]
    assert (await service.model_state(sid)).current_ref == EXTRA_REF
    await service.use_model(sid, DEFAULT_REF)
    restored = await service.chat("恢复默认", sid)
    assert restored.model_ref == DEFAULT_REF and not restored.is_override
    assert restored.session_id == first.session_id
    await service.use_model(sid, EXTRA_REF)
    await service.chat("复用池", sid)
    isolated = await service.chat("其他用户", "feishu:chat:other")
    assert isolated.model_ref == DEFAULT_REF and not isolated.is_override
    assert len(rig.instances) == 2
    await runtime.close()
    assert all(instance.closed for instance in rig.instances)


@pytest.mark.anyio
async def test_disabled_choice_fails_without_default_calls_and_requires_explicit_restore(tmp_path, monkeypatch) -> None:
    rig = ServiceRig(tmp_path, monkeypatch)
    service, runtime = await rig.build()
    await service.use_model("sid", EXTRA_REF)
    await service.chat("创建池", "sid")
    rig.credentials.entries = (DEFAULT_ENTRY,)
    with pytest.raises(AgentModelUnavailableError) as exc_info:
        await service.chat("已禁用", "sid")
    assert exc_info.value.model_ref == EXTRA_REF
    state = await service.model_state("sid")
    assert state.current_ref == EXTRA_REF and state.is_override
    assert EXTRA_REF not in state.available_refs
    assert rig.instances[0].calls == []
    with pytest.raises(AgentModelUnavailableError):
        await service.use_model("sid", "unknown/model")
    assert (await service.model_state("sid")).current_ref == EXTRA_REF
    await service.use_model("sid", DEFAULT_REF)
    assert (await service.chat("显式恢复", "sid")).model_ref == DEFAULT_REF
    await runtime.close()


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["launch", "run"])
async def test_override_failure_retains_choice_and_sanitizes_error(tmp_path, monkeypatch, caplog, failure) -> None:
    rig = ServiceRig(tmp_path, monkeypatch)
    service, runtime = await rig.build()
    if failure == "launch":
        rig.start_errors[EXTRA_REF] = OSError("api_key=sk-leaked")
    else:
        rig.run_errors[EXTRA_REF] = HarnessError("api_key=sk-leaked")
    await service.use_model("sid", EXTRA_REF)
    with pytest.raises(AgentModelUnavailableError) as exc_info:
        await service.chat("失败", "sid")
    assert "sk-leaked" not in str(exc_info.value)
    assert "sk-leaked" not in caplog.text
    assert (await service.model_state("sid")).current_ref == EXTRA_REF
    assert rig.instances[0].calls == []
    await runtime.close()


@pytest.mark.anyio
async def test_default_failure_preserves_runtime_error(tmp_path, monkeypatch) -> None:
    rig = ServiceRig(tmp_path, monkeypatch)
    service, runtime = await rig.build()
    rig.run_errors[DEFAULT_REF] = HarnessError("default failed")
    with pytest.raises(AgentRuntimeError) as exc_info:
        await service.chat("失败", "sid")
    assert exc_info.value.code == "AGENT_CHAT_FAILED"
    assert not (await service.model_state("sid")).is_override
    await runtime.close()


@pytest.mark.anyio
async def test_model_switch_during_execution_keeps_started_turn_identity(tmp_path, monkeypatch) -> None:
    rig = ServiceRig(tmp_path, monkeypatch)
    service, runtime = await rig.build()
    await service.use_model("sid", EXTRA_REF)
    rig.block_ref = EXTRA_REF
    running = asyncio.create_task(service.chat("尚在执行", "sid"))
    try:
        assert await asyncio.to_thread(rig.started.wait, 2)
        await service.use_model("sid", DEFAULT_REF)
    finally:
        rig.release.set()
    turn = await running
    assert turn.model_ref == EXTRA_REF and turn.is_override
    assert turn.response == f"回复@{EXTRA_REF}"
    following = await service.chat("下一轮", "sid")
    assert following.model_ref == DEFAULT_REF and not following.is_override
    await runtime.close()


@pytest.mark.anyio
async def test_restart_uses_new_default_without_old_choice_and_remints_conflict(tmp_path, monkeypatch) -> None:
    rig = ServiceRig(tmp_path, monkeypatch)
    first, old_runtime = await rig.build()
    await first.use_model("sid", EXTRA_REF)
    await first.chat("旧进程", "sid")
    await old_runtime.close()
    rig.credentials.entries = (replace(EXTRA_ENTRY, is_default=True),)
    second, new_runtime = await rig.build(rig.credentials.entries[0])
    state = await second.model_state("sid")
    assert state.current_ref == state.default_ref == EXTRA_REF
    assert not state.is_override and state.pending_default_ref is None
    rig.conflict_ids.add("sid")
    turn = await second.chat("新进程", "sid")
    assert turn.session_id.startswith("sid~r")
    assert turn.model_ref == EXTRA_REF and not turn.is_override
    await new_runtime.close()
    assert all(instance.closed for instance in rig.instances)


@pytest.mark.anyio
async def test_unconfigured_runtime_does_not_launch_extra_model(tmp_path, monkeypatch) -> None:
    rig = ServiceRig(tmp_path, monkeypatch)
    service, runtime = await rig.build(None)
    state = await service.model_state("sid")
    assert state.default_ref is None and state.pending_default_ref == DEFAULT_REF
    with pytest.raises(AgentNotConfiguredError):
        await service.chat("默认未配置", "sid")
    await service.use_model("sid", EXTRA_REF)
    with pytest.raises(AgentModelUnavailableError):
        await service.chat("不能绕过先决条件", "sid")
    assert rig.instances == []
    await runtime.close()


@pytest.mark.anyio
async def test_failed_main_start_does_not_launch_extra_model(tmp_path, monkeypatch) -> None:
    rig = ServiceRig(tmp_path, monkeypatch)
    rig.start_errors[DEFAULT_REF] = OSError("main start failed")
    service, runtime = await rig.build()
    with pytest.raises(AgentRuntimeError) as exc_info:
        await service.chat("默认启动失败", "sid")
    assert exc_info.value.code == "AGENT_RUNTIME_UNAVAILABLE"
    await service.use_model("sid", EXTRA_REF)
    with pytest.raises(AgentModelUnavailableError):
        await service.chat("不能绕过失败主实例", "sid")
    assert len(rig.instances) == 1 and rig.instances[0].closed
    assert (await service.model_state("sid")).current_ref == EXTRA_REF
    await runtime.close()


@pytest.mark.anyio
async def test_new_sessions_are_generated_by_runtime_and_results_are_immutable(tmp_path, monkeypatch) -> None:
    rig = ServiceRig(tmp_path, monkeypatch)
    service, runtime = await rig.build()
    turn = await service.chat("新会话")
    assert len(turn.session_id) == 32
    assert turn.model_ref == DEFAULT_REF and not turn.is_override
    state = await service.model_state(turn.session_id)
    with pytest.raises(FrozenInstanceError):
        state.current_ref = EXTRA_REF
    with pytest.raises(FrozenInstanceError):
        turn.model_ref = EXTRA_REF
    assert "sk-default" not in repr(state) + repr(turn)
    await runtime.close()
