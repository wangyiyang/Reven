"""运行时多模型路由（#163）：harness 缓存池、override 严格校验（不静默降级）、池生命周期。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from reven.agent import AgentConfig, AgentModelUnavailableError, AgentRuntime
from reven.agent.runtime import ModelConfigResolver

DEFAULT_REF = "deepseek-official/deepseek-v4-flash"
EXTRA_REF = "openai/gpt-5"


def _make_config(
    dsh_home: Path, *, provider: str = "deepseek-official", model: str = "deepseek-v4-flash"
) -> AgentConfig:
    return AgentConfig(provider=provider, model=model, base_url=None, api_key=None, dsh_home=dsh_home, cwd=dsh_home)


class _StubHarness:
    """按构造 kwargs 记录模型身份；run 返回带模型标记的响应，close 置标记。"""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.run_calls: list[tuple[str, str]] = []
        self.closed = False

    def start(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def run(self, message: str, *, session_id: str) -> object:
        self.run_calls.append((message, session_id))
        return SimpleNamespace(session_id=session_id, final_response=f"回复@{self.kwargs['model']}")


def _stub_harness_class(monkeypatch: pytest.MonkeyPatch) -> list[_StubHarness]:
    created: list[_StubHarness] = []

    class _Factory(_StubHarness):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)
            created.append(self)

    monkeypatch.setattr("reven.agent.runtime.DeepSeekHarness", _Factory)
    return created


def _resolver(tmp_path: Path) -> ModelConfigResolver:
    async def resolve(ref: str) -> AgentConfig | None:
        if ref == EXTRA_REF:
            return _make_config(tmp_path / "dsh-extra", provider="openai", model="gpt-5")
        return None

    return resolve


@pytest.mark.anyio
async def test_override_model_uses_pooled_harness_and_caches_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """override 模型走缓存池实例；同 ref 再次对话命中缓存，不重复拉起。"""
    created = _stub_harness_class(monkeypatch)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-main"), model_resolver=_resolver(tmp_path))
    await runtime.start()
    assert len(created) == 1  # 仅主实例

    _, first = await runtime.chat("你好", "s-1", model=EXTRA_REF)
    _, second = await runtime.chat("再问", "s-1", model=EXTRA_REF)

    assert first == "回复@gpt-5"
    assert second == "回复@gpt-5"
    assert len(created) == 2  # 主实例 + 池实例各一
    pool_instance = created[1]
    assert pool_instance.kwargs["provider"] == "openai"
    assert pool_instance.kwargs["model"] == "gpt-5"
    assert pool_instance.run_calls == [("你好", "s-1"), ("再问", "s-1")]
    assert created[0].run_calls == []  # 主实例未被 override 对话触碰
    await runtime.close()


@pytest.mark.anyio
async def test_unregistered_model_raises_and_never_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """未注册/未启用的 override：明确抛错，不静默降级到默认模型（主实例零调用）。"""
    created = _stub_harness_class(monkeypatch)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-main"), model_resolver=_resolver(tmp_path))
    await runtime.start()

    with pytest.raises(AgentModelUnavailableError) as exc_info:
        await runtime.chat("你好", "s-1", model="anthropic/claude-sonnet-4")

    assert exc_info.value.code == "AGENT_MODEL_UNAVAILABLE"
    assert "anthropic/claude-sonnet-4" in exc_info.value.message
    assert len(created) == 1  # 未拉起任何池实例
    assert created[0].run_calls == []  # 默认模型未被静默使用
    await runtime.close()


@pytest.mark.anyio
async def test_override_without_resolver_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """运行时未接入注册表（无库降级形态）：override 明确拒绝而非忽略。"""
    _stub_harness_class(monkeypatch)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-main"))
    await runtime.start()

    with pytest.raises(AgentModelUnavailableError):
        await runtime.chat("你好", "s-1", model=EXTRA_REF)
    await runtime.close()


@pytest.mark.anyio
async def test_override_equal_to_default_uses_main_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """override 命中默认模型 ref：直接走主实例，不起池实例、不调 resolver。"""
    created = _stub_harness_class(monkeypatch)

    async def _fail_resolver(ref: str) -> AgentConfig | None:
        raise AssertionError("默认模型不应触发 resolver")

    runtime = AgentRuntime(_make_config(tmp_path / "dsh-main"), model_resolver=_fail_resolver)
    await runtime.start()

    _, answer = await runtime.chat("你好", "s-1", model=DEFAULT_REF)

    assert answer == "回复@deepseek-v4-flash"
    assert len(created) == 1
    await runtime.close()


@pytest.mark.anyio
async def test_pool_launch_failure_raises_model_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """池实例拉起失败：抛 AGENT_MODEL_UNAVAILABLE 且不缓存失败实例（下次可重试）。"""

    class _FailingHarness:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def start(self) -> None:
            if self.kwargs["model"] == "gpt-5":
                raise OSError("dsh binary missing")

        def close(self) -> None:
            pass

        def run(self, message: str, *, session_id: str) -> object:
            return SimpleNamespace(session_id=session_id, final_response="回复")

    monkeypatch.setattr("reven.agent.runtime.DeepSeekHarness", _FailingHarness)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-main"), model_resolver=_resolver(tmp_path))
    await runtime.start()

    with pytest.raises(AgentModelUnavailableError) as exc_info:
        await runtime.chat("你好", "s-1", model=EXTRA_REF)

    assert exc_info.value.code == "AGENT_MODEL_UNAVAILABLE"
    assert runtime._harness_pool == {}  # 失败实例不入池
    await runtime.close()


@pytest.mark.anyio
async def test_close_shuts_down_pool_instances(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """close 关闭主实例与全部池实例。"""
    created = _stub_harness_class(monkeypatch)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-main"), model_resolver=_resolver(tmp_path))
    await runtime.start()
    await runtime.chat("你好", "s-1", model=EXTRA_REF)
    assert len(created) == 2

    await runtime.close()

    assert all(instance.closed for instance in created)
    assert runtime._harness_pool == {}


@pytest.mark.anyio
async def test_default_chat_path_is_unaffected_by_pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无 override 的常规对话走主实例（回归：默认路径行为不变）。"""
    created = _stub_harness_class(monkeypatch)
    runtime = AgentRuntime(_make_config(tmp_path / "dsh-main"), model_resolver=_resolver(tmp_path))
    await runtime.start()

    _, answer = await runtime.chat("你好", "s-1")

    assert answer == "回复@deepseek-v4-flash"
    assert len(created) == 1
    await runtime.close()
