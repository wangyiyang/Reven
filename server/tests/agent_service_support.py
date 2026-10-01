"""真实 AgentService/runtime 组合测试的凭证与同步 harness 替身。"""

import threading
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from deepseek_harness.errors import HarnessError, JsonRpcError
from reven.agent.config import AgentConfig, resolve_agent_model_config
from reven.agent.runtime import AgentRuntime
from reven.agent.service import AgentService
from reven.config import Settings
from reven.integrations.credentials import AgentModelEntry, IntegrationCredentials
from reven.integrations.feishu_bot.config import FeishuBotConfig

DEFAULT_ENTRY = AgentModelEntry("sk-default", "deepseek-official", "deepseek-v4-flash", None, True)
EXTRA_ENTRY = AgentModelEntry("sk-extra", "openai", "gpt-5", None, False)
DEFAULT_REF = DEFAULT_ENTRY.ref
EXTRA_REF = EXTRA_ENTRY.ref


class MutableCredentials:
    def __init__(self) -> None:
        self.entries: tuple[AgentModelEntry, ...] | None = (DEFAULT_ENTRY, EXTRA_ENTRY)

    async def agent_llm_models(self) -> tuple[AgentModelEntry, ...] | None:
        return self.entries

    async def feishu_bot(self) -> FeishuBotConfig:
        return FeishuBotConfig("cli_test", "test-secret", ("ou_boss", "ou_other"))


class FakeHarness:
    def __init__(self, rig: "ServiceRig", **kwargs: object) -> None:
        self.ref = f"{kwargs['provider']}/{kwargs['model']}"
        self.calls: list[tuple[str, str]] = []
        self.closed = False
        self.rig = rig
        rig.instances.append(self)

    def start(self) -> None:
        error = self.rig.start_errors.get(self.ref)
        if error is not None:
            raise error

    def close(self) -> None:
        self.closed = True

    def run(self, message: str, *, session_id: str) -> object:
        self.calls.append((message, session_id))
        if session_id in self.rig.conflict_ids:
            raise JsonRpcError(-32602, f'session "{session_id}" already exists')
        if self.ref == self.rig.block_ref:
            self.rig.started.set()
            if not self.rig.release.wait(timeout=5):
                raise AssertionError("等待测试释放 harness 超时")
        error = self.rig.run_errors.get(self.ref)
        if error is not None:
            raise error
        return SimpleNamespace(session_id=session_id, final_response=f"回复@{self.ref}")


class ServiceRig:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.credentials = MutableCredentials()
        self.instances: list[FakeHarness] = []
        self.conflict_ids: set[str] = set()
        self.start_errors: dict[str, Exception] = {}
        self.run_errors: dict[str, HarnessError] = {}
        self.block_ref: str | None = None
        self.started, self.release = threading.Event(), threading.Event()
        self.settings = Settings(
            database_url="postgresql+asyncpg://test@127.0.0.1/test",
            reven_master_key="dGVzdA==",
            reven_admin_password="test-admin-password",
            dsh_home=tmp_path / "dsh",
            agent_api_key=None,
            _env_file=None,
        )
        monkeypatch.setattr("reven.agent.runtime.DeepSeekHarness", partial(FakeHarness, self))

    async def build(self, default: AgentModelEntry | None = DEFAULT_ENTRY) -> tuple[AgentService, AgentRuntime]:
        config = None
        if default is not None:
            config = AgentConfig(
                default.provider,
                default.model,
                default.base_url,
                default.api_key,
                self.settings.dsh_home,
                self.settings.dsh_home,
            )
        credentials = cast(IntegrationCredentials, self.credentials)
        resolver = partial(resolve_agent_model_config, credentials, self.settings)
        runtime = AgentRuntime(config, model_resolver=resolver)
        await runtime.start()
        return AgentService(runtime, credentials), runtime
