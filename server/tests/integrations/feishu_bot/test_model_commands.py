"""飞书 /model 指令（#163）：解析、白名单校验、会话 override、不静默降级。

桥接测试范式同 test_chat_dispatcher.py：bind_loop 后以 SDK 线程视角投递，
工作线程回复经轮询等待。指令消息直接回复：无「思考中…」占位、不进入 Agent。
"""

import asyncio
import time
from collections.abc import Sequence

import pytest
from reven.agent.errors import AgentModelUnavailableError, AgentRuntimeError
from reven.integrations.credentials import AgentModelEntry
from reven.integrations.feishu_bot.chat_dispatcher import FALLBACK_TEXT, FeishuChatDispatcher
from reven.integrations.feishu_bot.commands import (
    USAGE_TEXT,
    is_valid_model_ref,
    parse_model_command,
)
from reven.integrations.feishu_bot.config import FeishuBotConfig

WHITELISTED_CONFIG = FeishuBotConfig(app_id="cli_test", app_secret="s3cret", whitelist_open_ids=("ou_boss",))
DEFAULT_ENTRY = AgentModelEntry(
    api_key="sk-default", provider="deepseek-official", model="deepseek-v4-flash", base_url=None, is_default=True
)
EXTRA_ENTRY = AgentModelEntry(
    api_key="sk-openai", provider="openai", model="gpt-5", base_url="https://api.openai.com/v1", is_default=False
)
DEFAULT_REF = DEFAULT_ENTRY.ref
EXTRA_REF = EXTRA_ENTRY.ref


# --- 指令解析（纯函数） ---


@pytest.mark.parametrize(
    ("text", "action", "ref"),
    [
        ("/model", "list", None),
        ("/model list", "list", None),
        ("/model  list ", "list", None),
        ("/model current", "current", None),
        ("/model use openai/gpt-5", "use", "openai/gpt-5"),
        ("/model use siliconflow/Qwen/Qwen3-8B", "use", "siliconflow/Qwen/Qwen3-8B"),  # model 段允许含 /
        ("/model foo", "help", None),  # 未识别子指令
        ("/model use", "help", None),  # 缺 ref
        ("/model use gpt-5", "help", None),  # ref 缺 provider 段
        ("/model use openai/", "help", None),  # ref 缺 model 段
        ("/model use openai/gpt-5 extra", "help", None),  # 多余参数
    ],
)
def test_parse_model_command_variants(text: str, action: str, ref: str | None) -> None:
    command = parse_model_command(text)
    assert command is not None
    assert command.action == action
    assert command.model_ref == ref


@pytest.mark.parametrize("text", ["你好", "/modelx", "/modelx use openai/gpt-5", "/models", "/ model list"])
def test_non_command_text_returns_none(text: str) -> None:
    assert parse_model_command(text) is None


@pytest.mark.parametrize(
    ("ref", "valid"),
    [("openai/gpt-5", True), ("a/b/c", True), ("gpt-5", False), ("/gpt-5", False), ("openai/", False), ("", False)],
)
def test_is_valid_model_ref(ref: str, valid: bool) -> None:
    assert is_valid_model_ref(ref) is valid


# --- 指令端到端（dispatcher 接线） ---


class _StubCredentials:
    """credentials seam 替身：固定白名单配置 + 固定模型注册表。"""

    def __init__(self, entries: Sequence[AgentModelEntry] | None = (DEFAULT_ENTRY, EXTRA_ENTRY)) -> None:
        self._entries = tuple(entries) if entries is not None else None

    async def feishu_bot(self) -> FeishuBotConfig | None:
        return WHITELISTED_CONFIG

    async def agent_llm_models(self) -> tuple[AgentModelEntry, ...] | None:
        return self._entries


class _StubAgentService:
    """记录 (message, session_id, model) 调用；可按模型脚本化抛错。"""

    def __init__(self, *, answer: str = "答案", error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str | None, str | None]] = []
        self._answer = answer
        self._error = error

    async def chat(self, message: str, session_id: str | None = None, *, model: str | None = None) -> tuple[str, str]:
        self.calls.append((message, session_id, model))
        if self._error is not None:
            raise self._error
        return ("sid", f"{self._answer}@{model or 'default'}")


class ReplyRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, message_id: str, text: str) -> None:
        self.calls.append((message_id, text))


def _dispatcher(credentials: _StubCredentials, agent: _StubAgentService) -> FeishuChatDispatcher:
    return FeishuChatDispatcher(credentials, agent)  # type: ignore[arg-type]


async def _submit(dispatcher: FeishuChatDispatcher, reply: ReplyRecorder, text: str, **kwargs: str) -> None:
    params = {"message_id": "om_1", "chat_id": "oc_1", "open_id": "ou_boss", **kwargs}
    await asyncio.to_thread(dispatcher.submit, kind="chat", reply=reply, text=text, **params)  # type: ignore[arg-type]


async def _wait_replies(recorder: ReplyRecorder, count: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while len(recorder.calls) < count and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    if len(recorder.calls) < count:
        raise AssertionError(f"等待回复超时：期望 {count} 条，实际 {recorder.calls!r}")


@pytest.mark.anyio
async def test_model_list_replies_registry_without_agent_call() -> None:
    agent = _StubAgentService()
    dispatcher = _dispatcher(_StubCredentials(), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, "/model list")
    await _wait_replies(recorder, 1)

    [(message_id, text)] = recorder.calls
    assert message_id == "om_1"
    assert f"1. {DEFAULT_REF}（默认）" in text
    assert f"2. {EXTRA_REF}" in text
    assert "/model use provider/model" in text
    assert agent.calls == []  # 指令不进入 Agent


@pytest.mark.anyio
async def test_model_use_switches_session_and_marks_following_answers() -> None:
    """切换成功后：后续对话带 override 模型，回复末尾附当前模型行。"""
    agent = _StubAgentService()
    dispatcher = _dispatcher(_StubCredentials(), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 1)
    assert recorder.calls[0] == ("om_1", f"已切换：本会话后续回答使用 {EXTRA_REF}。")

    await _submit(dispatcher, recorder, "你好")
    await _wait_replies(recorder, 3)  # 占位 + 回答

    assert recorder.calls[1] == ("om_1", "思考中…")
    assert recorder.calls[2][1].startswith(f"答案@{EXTRA_REF}")
    assert recorder.calls[2][1].endswith(f"—— 当前模型：{EXTRA_REF}")
    assert agent.calls == [("你好", "feishu:oc_1:ou_boss", EXTRA_REF)]


@pytest.mark.anyio
async def test_model_use_rejects_unregistered_model_with_options() -> None:
    """白名单拒绝：未配置/未启用的模型明确拒绝并列出可选项。"""
    agent = _StubAgentService()
    dispatcher = _dispatcher(_StubCredentials(), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, "/model use anthropic/claude-sonnet-4")
    await _wait_replies(recorder, 1)

    [(message_id, text)] = recorder.calls
    assert "无法切换到 anthropic/claude-sonnet-4：未配置或未启用" in text
    assert DEFAULT_REF in text and EXTRA_REF in text  # 列出可选项
    assert agent.calls == []


@pytest.mark.anyio
async def test_model_use_default_clears_override() -> None:
    """切回默认模型 = 清除会话 override；后续对话不再带 model 参数与落款。"""
    agent = _StubAgentService()
    dispatcher = _dispatcher(_StubCredentials(), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 1)
    await _submit(dispatcher, recorder, f"/model use {DEFAULT_REF}")
    await _wait_replies(recorder, 2)
    assert recorder.calls[1] == ("om_1", f"已恢复默认模型：{DEFAULT_REF}。")

    await _submit(dispatcher, recorder, "你好")
    await _wait_replies(recorder, 4)

    assert recorder.calls[3] == ("om_1", "答案@default")  # 无模型落款
    assert agent.calls[-1] == ("你好", "feishu:oc_1:ou_boss", None)


@pytest.mark.anyio
async def test_model_current_reports_default_then_override() -> None:
    agent = _StubAgentService()
    dispatcher = _dispatcher(_StubCredentials(), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, "/model current")
    await _wait_replies(recorder, 1)
    assert recorder.calls[0] == ("om_1", f"当前会话模型：{DEFAULT_REF}（默认）")

    await _submit(dispatcher, recorder, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 2)
    await _submit(dispatcher, recorder, "/model current")
    await _wait_replies(recorder, 3)
    assert recorder.calls[2] == ("om_1", f"当前会话模型：{EXTRA_REF}（会话指定）")


@pytest.mark.anyio
async def test_model_list_marks_current_override() -> None:
    agent = _StubAgentService()
    dispatcher = _dispatcher(_StubCredentials(), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 1)
    await _submit(dispatcher, recorder, "/model")
    await _wait_replies(recorder, 2)

    text = recorder.calls[1][1]
    assert f"1. {DEFAULT_REF}（默认）" in text
    assert f"2. {EXTRA_REF}（当前会话）" in text


@pytest.mark.anyio
async def test_unknown_subcommand_replies_usage() -> None:
    agent = _StubAgentService()
    dispatcher = _dispatcher(_StubCredentials(), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, "/model foo")
    await _wait_replies(recorder, 1)

    assert recorder.calls == [("om_1", USAGE_TEXT)]
    assert agent.calls == []


@pytest.mark.anyio
async def test_commands_do_not_pollute_session_history() -> None:
    """指令消息不进 Agent（不计入会话历史），会话内仅保留真实问答。"""
    agent = _StubAgentService()
    dispatcher = _dispatcher(_StubCredentials(), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, "/model list")
    await _submit(dispatcher, recorder, "/model current")
    await _submit(dispatcher, recorder, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 3)
    await _submit(dispatcher, recorder, "真实问题")
    await _wait_replies(recorder, 5)

    assert [call[0] for call in agent.calls] == ["真实问题"]


@pytest.mark.anyio
async def test_override_scope_is_per_conversation() -> None:
    """切换仅影响当前会话：其他 chat_id/open_id 的对话仍走默认模型。"""
    agent = _StubAgentService()
    dispatcher = _dispatcher(_StubCredentials(), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 1)
    await _submit(dispatcher, recorder, "别人的消息", chat_id="oc_2", open_id="ou_boss")
    await _wait_replies(recorder, 3)

    assert agent.calls[-1] == ("别人的消息", "feishu:oc_2:ou_boss", None)


@pytest.mark.anyio
async def test_unavailable_override_model_replies_explicit_error_without_fallback() -> None:
    """override 模型不可达：明确报错（非通用兜底文案），不静默降级到默认模型。"""
    agent = _StubAgentService(error=AgentModelUnavailableError(EXTRA_REF))
    dispatcher = _dispatcher(_StubCredentials(), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 1)
    await _submit(dispatcher, recorder, "你好")
    await _wait_replies(recorder, 3)

    text = recorder.calls[2][1]
    assert f"模型 {EXTRA_REF} 当前不可用" in text
    assert text != FALLBACK_TEXT
    assert "sk-openai" not in text and "sk-default" not in text  # 凭证红线：不回显 key


@pytest.mark.anyio
async def test_override_model_runtime_failure_also_explicit() -> None:
    """override 模型调用失败（如上游 5xx）：同样明确报错并保留 override。"""
    agent = _StubAgentService(
        error=AgentRuntimeError("AGENT_CHAT_FAILED", "dsh 会话执行失败：upstream api_key=sk-leaked")
    )
    dispatcher = _dispatcher(_StubCredentials(), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 1)
    await _submit(dispatcher, recorder, "你好")
    await _wait_replies(recorder, 3)

    text = recorder.calls[2][1]
    assert f"模型 {EXTRA_REF} 当前不可用" in text
    assert "sk-leaked" not in text  # 上游异常 message 含凭证回显，禁止进回复


@pytest.mark.anyio
async def test_default_model_failure_keeps_existing_fallback() -> None:
    """无 override 时调用失败维持既有兜底文案（回归：默认路径行为不变）。"""
    agent = _StubAgentService(error=AgentRuntimeError("AGENT_CHAT_FAILED", "boom"))
    dispatcher = _dispatcher(_StubCredentials(), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, "你好")
    await _wait_replies(recorder, 2)

    assert recorder.calls[1] == ("om_1", FALLBACK_TEXT)


@pytest.mark.anyio
async def test_commands_with_empty_registry() -> None:
    """未配置任何模型：list/current 提示未配置，use 拒绝。"""
    agent = _StubAgentService()
    dispatcher = _dispatcher(_StubCredentials(None), agent)
    dispatcher.bind_loop(asyncio.get_running_loop())
    recorder = ReplyRecorder()

    await _submit(dispatcher, recorder, "/model list")
    await _wait_replies(recorder, 1)
    assert recorder.calls[0] == ("om_1", "尚未配置可用模型。")

    await _submit(dispatcher, recorder, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 2)
    assert "无法切换" in recorder.calls[1][1]
