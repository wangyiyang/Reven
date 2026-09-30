from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from deepseek_harness.errors import HarnessError, JsonRpcError
from reven.agent import AgentConfig, AgentNotConfiguredError, AgentRuntime, AgentRuntimeError
from reven.agent.mcp_server import AgentMcpContext


def _make_config(dsh_home: Path) -> AgentConfig:
    return AgentConfig(
        provider="deepseek-official",
        model="deepseek-v4-flash",
        base_url=None,
        api_key=None,
        dsh_home=dsh_home,
        cwd=dsh_home,
    )


@pytest.mark.anyio
@pytest.mark.dsh_runtime
async def test_runtime_start_handshake_and_close(tmp_path: Path) -> None:
    """AC1：无 API key 拉起 dsh sdk profile + initialize 握手 + 优雅关闭（真实子进程）。"""
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-runtime"))

    await runtime.start()
    assert runtime.configured

    await runtime.close()
    await runtime.close()


@pytest.mark.anyio
async def test_chat_raises_when_not_configured() -> None:
    runtime = AgentRuntime(None)

    await runtime.start()
    with pytest.raises(AgentNotConfiguredError):
        await runtime.chat("你好")


@pytest.mark.anyio
async def test_chat_raises_when_not_started(tmp_path: Path) -> None:
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-runtime"))

    with pytest.raises(AgentRuntimeError):
        await runtime.chat("你好")


@pytest.mark.anyio
async def test_close_is_idempotent_without_start(tmp_path: Path) -> None:
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-runtime"))

    await runtime.close()
    await runtime.close()


@pytest.mark.anyio
async def test_start_failure_degrades_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """启动失败不阻止应用启动：记结构化日志，chat 映射为 AGENT_RUNTIME_UNAVAILABLE（502）。"""

    def _fail_launch(config: AgentConfig, mcp: AgentMcpContext | None) -> None:
        raise OSError("dsh binary missing")

    monkeypatch.setattr("reven.agent.runtime._launch", _fail_launch)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-runtime"))

    with caplog.at_level("ERROR", logger="reven.agent.runtime"):
        await runtime.start()

    assert any("启动失败" in record.message for record in caplog.records)
    with pytest.raises(AgentRuntimeError) as exc_info:
        await runtime.chat("你好")
    assert exc_info.value.code == "AGENT_RUNTIME_UNAVAILABLE"
    await runtime.close()


@pytest.mark.anyio
async def test_close_resets_failure_and_next_start_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def _fail_launch(config: AgentConfig, mcp: AgentMcpContext | None) -> None:
        nonlocal attempts
        attempts += 1
        raise OSError("boom")

    monkeypatch.setattr("reven.agent.runtime._launch", _fail_launch)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-runtime"))

    await runtime.start()
    await runtime.close()
    await runtime.start()

    assert attempts == 2


def _stub_harness(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    captured: list[dict[str, object]] = []

    class _Harness:
        def __init__(self, **kwargs: object) -> None:
            captured.append(kwargs)

        def start(self) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr("reven.agent.runtime.DeepSeekHarness", _Harness)
    return captured


@pytest.mark.anyio
async def test_launch_with_mcp_context_injects_patch_and_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _stub_harness(monkeypatch)
    mcp = AgentMcpContext(url="http://127.0.0.1:8000/agent/mcp", token="tok-secret")
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-runtime"), mcp=mcp)

    await runtime.start()
    await runtime.close()

    (kwargs,) = captured
    patches = kwargs["patches"]
    assert isinstance(patches, tuple)
    assert patches[-1].endswith("dsh.patch.yml")
    assert kwargs["env"] == {"REVEN_AGENT_MCP_URL": mcp.url, "REVEN_AGENT_MCP_TOKEN": "tok-secret"}


@pytest.mark.anyio
async def test_launch_without_mcp_context_keeps_plain_sdk_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无 MCP 上下文时不挂 patch（保持 AC1 无 key 纯握手行为），也不注入 REVEN_AGENT_MCP_*。"""
    captured = _stub_harness(monkeypatch)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-runtime"))

    await runtime.start()
    await runtime.close()

    (kwargs,) = captured
    assert kwargs["patches"] == ()
    assert kwargs["env"] == {}


EXTERNAL_SESSION_ID = "feishu:chat-1:user-1"


def _stub_chat_harness(monkeypatch: pytest.MonkeyPatch, run: Callable[[str, str], object]) -> list[str]:
    """替换 DeepSeekHarness 为脚本化 run 的假实现，返回 run 依次收到的 session_id。"""
    seen_session_ids: list[str] = []

    class _Harness:
        def __init__(self, **kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

        def close(self) -> None:
            pass

        def run(self, message: str, *, session_id: str) -> object:
            seen_session_ids.append(session_id)
            return run(message, session_id)

    monkeypatch.setattr("reven.agent.runtime.DeepSeekHarness", _Harness)
    return seen_session_ids


def _fail_on_external_id(message: str, session_id: str) -> object:
    if session_id == EXTERNAL_SESSION_ID:
        raise JsonRpcError(-32602, f'session "{session_id}" already exists')
    return SimpleNamespace(session_id=session_id, final_response="回复")


@pytest.mark.anyio
async def test_chat_remints_session_id_on_already_exists_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """进程重启后旧 session_id 报 already exists：重铸活跃 id 重试成功并返回新 id。"""
    seen = _stub_chat_harness(monkeypatch, _fail_on_external_id)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-runtime"))
    await runtime.start()

    session_id, response = await runtime.chat("你好", EXTERNAL_SESSION_ID)

    assert response == "回复"
    assert session_id.startswith(f"{EXTERNAL_SESSION_ID}~r")
    assert seen == [EXTERNAL_SESSION_ID, session_id]
    await runtime.close()


@pytest.mark.anyio
async def test_chat_reuses_reminted_alias_for_same_external_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """同一外部 session_id 的后续消息直接命中别名，沿用同一活跃 id，不再重铸重试。"""
    seen = _stub_chat_harness(monkeypatch, _fail_on_external_id)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-runtime"))
    await runtime.start()

    first_id, _ = await runtime.chat("第一条", EXTERNAL_SESSION_ID)
    second_id, _ = await runtime.chat("第二条", EXTERNAL_SESSION_ID)

    assert second_id == first_id
    assert seen == [EXTERNAL_SESSION_ID, first_id, first_id]
    await runtime.close()


@pytest.mark.anyio
async def test_chat_raises_when_remint_retry_also_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """重铸重试仍失败时按原路径抛 AGENT_CHAT_FAILED，且不记录别名（下次仍从外部 id 重试）。"""

    def _always_conflict(message: str, session_id: str) -> object:
        raise JsonRpcError(-32602, f'session "{session_id}" already exists')

    seen = _stub_chat_harness(monkeypatch, _always_conflict)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-runtime"))
    await runtime.start()

    with pytest.raises(AgentRuntimeError) as exc_info:
        await runtime.chat("你好", EXTERNAL_SESSION_ID)

    assert exc_info.value.code == "AGENT_CHAT_FAILED"
    assert len(seen) == 2
    assert seen[1].startswith(f"{EXTERNAL_SESSION_ID}~r")

    with pytest.raises(AgentRuntimeError):
        await runtime.chat("再来", EXTERNAL_SESSION_ID)
    assert seen[2] == EXTERNAL_SESSION_ID
    await runtime.close()


@pytest.mark.anyio
async def test_chat_without_session_id_does_not_remint_on_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """session_id 缺省时即使报 already exists 也不重铸重试（无外部 id 可记别名），直接抛 AGENT_CHAT_FAILED。"""

    def _always_conflict(message: str, session_id: str) -> object:
        raise JsonRpcError(-32602, f'session "{session_id}" already exists')

    seen = _stub_chat_harness(monkeypatch, _always_conflict)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-runtime"))
    await runtime.start()

    with pytest.raises(AgentRuntimeError) as exc_info:
        await runtime.chat("你好")

    assert exc_info.value.code == "AGENT_CHAT_FAILED"
    assert len(seen) == 1
    await runtime.close()


@pytest.mark.anyio
@pytest.mark.parametrize("error", [HarnessError("transport closed"), JsonRpcError(-32000, "rate limited")])
async def test_chat_does_not_retry_on_non_conflict_errors(
    error: HarnessError, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非 already exists 冲突的 HarnessError 不触发重铸重试，直接抛 AGENT_CHAT_FAILED。"""

    def _fail(message: str, session_id: str) -> object:
        raise error

    seen = _stub_chat_harness(monkeypatch, _fail)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-runtime"))
    await runtime.start()

    with pytest.raises(AgentRuntimeError) as exc_info:
        await runtime.chat("你好", EXTERNAL_SESSION_ID)

    assert exc_info.value.code == "AGENT_CHAT_FAILED"
    assert seen == [EXTERNAL_SESSION_ID]
    await runtime.close()
