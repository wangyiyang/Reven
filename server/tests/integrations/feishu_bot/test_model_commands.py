"""飞书 /model 指令（#163）：解析、白名单校验、会话 override、不静默降级。

桥接测试范式同 test_chat_dispatcher.py：bind_loop 后以 SDK 线程视角投递，
工作线程回复经轮询等待。指令消息直接回复：无「思考中…」占位、不进入 Agent。
"""

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
from agent_service_support import DEFAULT_ENTRY, DEFAULT_REF, EXTRA_ENTRY, EXTRA_REF, ServiceRig
from deepseek_harness.errors import HarnessError
from reven.integrations.feishu_bot.chat_dispatcher import FALLBACK_TEXT, FeishuChatDispatcher
from reven.integrations.feishu_bot.commands import (
    USAGE_TEXT,
    is_valid_model_ref,
    parse_model_command,
)

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


# --- 指令适配：真实 AgentService + runtime，fake harness 零网络 ---


class ReplyRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, message_id: str, text: str) -> None:
        self.calls.append((message_id, text))


@pytest.fixture
async def model_chat(tmp_path, monkeypatch, request) -> AsyncIterator[tuple]:
    rig = ServiceRig(tmp_path, monkeypatch)
    if not getattr(request, "param", True):
        rig.credentials.entries = None
    service, runtime = await rig.build(DEFAULT_ENTRY if rig.credentials.entries else None)
    recorder = ReplyRecorder()
    dispatcher = FeishuChatDispatcher(rig.credentials, service, reply=recorder)  # type: ignore[arg-type]
    dispatcher.bind_loop(asyncio.get_running_loop())
    yield rig, service, recorder, dispatcher
    await runtime.close()


async def _submit(dispatcher: FeishuChatDispatcher, text: str, **kwargs: str) -> None:
    params = {"message_id": "om_1", "chat_id": "oc_1", "open_id": "ou_boss", **kwargs}
    await asyncio.to_thread(dispatcher.submit, kind="chat", text=text, **params)  # type: ignore[arg-type]


async def _wait_replies(recorder: ReplyRecorder, count: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while len(recorder.calls) < count and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    if len(recorder.calls) < count:
        raise AssertionError(f"等待回复超时：期望 {count} 条，实际 {recorder.calls!r}")


@pytest.mark.anyio
async def test_model_commands_render_choices_and_turn_identity_without_inference(model_chat) -> None:
    rig, service, recorder, dispatcher = model_chat
    await _submit(dispatcher, "/model list")
    await _wait_replies(recorder, 1)
    assert f"1. {DEFAULT_REF}（默认）" in recorder.calls[0][1]
    assert f"2. {EXTRA_REF}" in recorder.calls[0][1]
    assert "（当前会话）" not in recorder.calls[0][1]
    await _submit(dispatcher, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 2)
    assert recorder.calls[1] == ("om_1", f"已切换：本会话后续回答使用 {EXTRA_REF}。")
    await _submit(dispatcher, "/model current")
    await _wait_replies(recorder, 3)
    assert recorder.calls[2] == ("om_1", f"当前会话模型：{EXTRA_REF}（会话指定）")
    await _submit(dispatcher, "/model")
    await _wait_replies(recorder, 4)
    assert f"2. {EXTRA_REF}（当前会话）" in recorder.calls[3][1]
    assert all(instance.calls == [] for instance in rig.instances)
    await _submit(dispatcher, "真实问题")
    await _wait_replies(recorder, 6)
    assert recorder.calls[4] == ("om_1", "思考中…")
    assert recorder.calls[5] == ("om_1", f"回复@{EXTRA_REF}\n\n—— 当前模型：{EXTRA_REF}")
    await _submit(dispatcher, f"/model use {DEFAULT_REF}")
    await _wait_replies(recorder, 7)
    assert recorder.calls[6] == ("om_1", f"已恢复默认模型：{DEFAULT_REF}。")
    await _submit(dispatcher, "默认问题")
    await _wait_replies(recorder, 9)
    assert recorder.calls[8] == ("om_1", f"回复@{DEFAULT_REF}")
    assert rig.instances[1].calls == [("真实问题", "feishu:oc_1:ou_boss")]
    assert rig.instances[0].calls == [("默认问题", "feishu:oc_1:ou_boss")]


@pytest.mark.anyio
async def test_rejected_and_unknown_commands_keep_selection_without_chat(model_chat) -> None:
    rig, service, recorder, dispatcher = model_chat
    await _submit(dispatcher, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 1)
    await _submit(dispatcher, "/model use unknown/model")
    await _wait_replies(recorder, 2)
    text = recorder.calls[1][1]
    assert "无法切换到 unknown/model：未配置或未启用" in text
    assert DEFAULT_REF in text and EXTRA_REF in text
    assert "（当前会话）" not in text
    assert (await service.model_state("feishu:oc_1:ou_boss")).current_ref == EXTRA_REF
    await _submit(dispatcher, "/model foo")
    await _wait_replies(recorder, 3)
    assert recorder.calls[2] == ("om_1", USAGE_TEXT)
    assert all(instance.calls == [] for instance in rig.instances)


@pytest.mark.anyio
async def test_group_members_have_distinct_external_sessions(model_chat) -> None:
    rig, _, recorder, dispatcher = model_chat
    await _submit(dispatcher, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 1)
    await _submit(dispatcher, "另一用户", open_id="ou_other")
    await _wait_replies(recorder, 3)
    await _submit(dispatcher, "另一群", chat_id="oc_2")
    await _wait_replies(recorder, 5)
    assert rig.instances[0].calls == [("另一用户", "feishu:oc_1:ou_other"), ("另一群", "feishu:oc_2:ou_boss")]
    assert "—— 当前模型" not in recorder.calls[-1][1]


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["disabled", "run", "default"])
async def test_failures_render_strict_override_or_default_fallback(model_chat, failure, caplog) -> None:
    rig, service, recorder, dispatcher = model_chat
    replies = 0
    if failure != "default":
        await _submit(dispatcher, f"/model use {EXTRA_REF}")
        await _wait_replies(recorder, 1)
        replies = 1
    if failure == "disabled":
        rig.credentials.entries = (DEFAULT_ENTRY,)
    else:
        rig.run_errors[DEFAULT_REF if failure == "default" else EXTRA_REF] = HarnessError("api_key=sk-leaked")
    await _submit(dispatcher, "失败问题")
    await _wait_replies(recorder, replies + 2)
    text = recorder.calls[-1][1]
    if failure == "default":
        assert text == FALLBACK_TEXT
    else:
        assert f"模型 {EXTRA_REF} 当前不可用" in text
        assert text != FALLBACK_TEXT and rig.instances[0].calls == []
        assert (await service.model_state("feishu:oc_1:ou_boss")).current_ref == EXTRA_REF
    assert "sk-leaked" not in text + caplog.text


@pytest.mark.anyio
async def test_saved_default_drift_renders_restart_hint_and_keeps_actual_default(model_chat) -> None:
    rig, _, recorder, dispatcher = model_chat
    rig.credentials.entries = (replace(EXTRA_ENTRY, is_default=True),)
    await _submit(dispatcher, "/model current")
    await _wait_replies(recorder, 1)
    assert recorder.calls[0][1].startswith(f"当前会话模型：{DEFAULT_REF}（默认）")
    assert f"已保存默认模型：{EXTRA_REF}，重启后生效。" in recorder.calls[0][1]
    await _submit(dispatcher, "/model list")
    await _wait_replies(recorder, 2)
    assert f"1. {DEFAULT_REF}（默认）" in recorder.calls[1][1]
    assert f"2. {EXTRA_REF}（重启后默认）" in recorder.calls[1][1]
    await _submit(dispatcher, f"/model use {EXTRA_REF}")
    await _wait_replies(recorder, 3)
    assert "已切换" in recorder.calls[2][1]
    await _submit(dispatcher, f"/model use {DEFAULT_REF}")
    await _wait_replies(recorder, 4)
    assert recorder.calls[3] == ("om_1", f"已恢复默认模型：{DEFAULT_REF}。")


@pytest.mark.anyio
@pytest.mark.parametrize("model_chat", [False], indirect=True)
async def test_commands_without_configured_models(model_chat) -> None:
    rig, _, recorder, dispatcher = model_chat
    for index, command in enumerate(["/model list", "/model current", f"/model use {EXTRA_REF}"], start=1):
        await _submit(dispatcher, command)
        await _wait_replies(recorder, index)
    assert recorder.calls[0] == recorder.calls[1] == ("om_1", "尚未配置可用模型。")
    assert "无法切换" in recorder.calls[2][1]
    assert rig.instances == []
