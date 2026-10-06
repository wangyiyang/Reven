"""飞书 /model 指令：确定性解析、可信身份、模型切换与本轮落款。"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from feishu_dispatch_support import (
    DEFAULT_REF,
    EXTRA_REF,
    FeishuAgentStub,
    ReplyRecorder,
    StubCredentials,
    submit,
    wait_replies,
)
from reven.agent.context import AgentActor
from reven.agent.errors import AgentModelUnavailableError, AgentRuntimeError
from reven.integrations.feishu_bot.chat_dispatcher import FALLBACK_TEXT, FeishuChatDispatcher
from reven.integrations.feishu_bot.commands import USAGE_TEXT, is_valid_model_ref, parse_model_command


@pytest.mark.parametrize(
    ("text", "action", "ref"),
    [
        ("/model", "list", None),
        ("/model list", "list", None),
        ("/model  list ", "list", None),
        ("/model current", "current", None),
        ("/model use openai/gpt-5", "use", "openai/gpt-5"),
        ("/model use siliconflow/Qwen/Qwen3-8B", "use", "siliconflow/Qwen/Qwen3-8B"),
        ("/model foo", "help", None),
        ("/model use", "help", None),
        ("/model use gpt-5", "help", None),
        ("/model use openai/", "help", None),
        ("/model use openai/gpt-5 extra", "help", None),
    ],
)
def test_parse_model_command_variants(text: str, action: str, ref: str | None) -> None:
    command = parse_model_command(text)
    assert command is not None and command.action == action and command.model_ref == ref


@pytest.mark.parametrize("text", ["你好", "/modelx", "/modelx use openai/gpt-5", "/models", "/ model list"])
def test_non_command_text_returns_none(text: str) -> None:
    assert parse_model_command(text) is None


@pytest.mark.parametrize(
    ("ref", "valid"),
    [("openai/gpt-5", True), ("a/b/c", True), ("gpt-5", False), ("/gpt-5", False), ("openai/", False), ("", False)],
)
def test_is_valid_model_ref(ref: str, valid: bool) -> None:
    assert is_valid_model_ref(ref) is valid


@pytest.fixture
async def model_chat() -> AsyncIterator[tuple]:
    agent, credentials, recorder = FeishuAgentStub(), StubCredentials(), ReplyRecorder()
    dispatcher = FeishuChatDispatcher(credentials, agent, reply=recorder)  # type: ignore[arg-type]
    dispatcher.bind_loop(asyncio.get_running_loop())
    yield agent, recorder, dispatcher


@pytest.mark.anyio
async def test_model_commands_render_choices_and_turn_identity_without_inference(model_chat) -> None:
    agent, recorder, dispatcher = model_chat
    await submit(dispatcher, "/model list")
    await wait_replies(recorder, 1)
    assert f"1. {DEFAULT_REF}（默认）" in recorder.calls[0][1]
    assert f"2. {EXTRA_REF}" in recorder.calls[0][1]
    await submit(dispatcher, f"/model use {EXTRA_REF}")
    await wait_replies(recorder, 2)
    assert recorder.calls[1] == ("om_1", f"已切换：本会话后续回答使用 {EXTRA_REF}。")
    await submit(dispatcher, "/model current")
    await wait_replies(recorder, 3)
    assert recorder.calls[2] == ("om_1", f"当前会话模型：{EXTRA_REF}（会话指定）")
    await submit(dispatcher, "/model")
    await wait_replies(recorder, 4)
    assert f"2. {EXTRA_REF}（当前会话）" in recorder.calls[3][1]
    assert agent.chat_calls == []
    await submit(dispatcher, "真实问题")
    await wait_replies(recorder, 6)
    assert recorder.calls[4] == ("om_1", "思考中…")
    assert recorder.calls[5] == ("om_1", f"回复@{EXTRA_REF}\n\n—— 当前模型：{EXTRA_REF}")
    assert agent.chat_calls == [
        ("真实问题", "feishu:oc_1:ou_boss", AgentActor("feishu:ou_boss", "feishu"), "om_1", 120.0)
    ]


@pytest.mark.anyio
async def test_use_default_clears_override_and_response_has_no_model_suffix(model_chat) -> None:
    agent, recorder, dispatcher = model_chat
    agent.overrides["feishu:oc_1:ou_boss"] = EXTRA_REF
    await submit(dispatcher, f"/model use {DEFAULT_REF}")
    await wait_replies(recorder, 1)
    assert recorder.calls[0] == ("om_1", f"已恢复默认模型：{DEFAULT_REF}。")
    await submit(dispatcher, "默认问题")
    await wait_replies(recorder, 3)
    assert recorder.calls[-1] == ("om_1", f"回复@{DEFAULT_REF}")


@pytest.mark.anyio
async def test_rejected_and_unknown_commands_keep_selection_without_chat(model_chat) -> None:
    agent, recorder, dispatcher = model_chat
    agent.overrides["feishu:oc_1:ou_boss"] = EXTRA_REF
    await submit(dispatcher, "/model use unknown/model")
    await wait_replies(recorder, 1)
    assert "无法切换到 unknown/model：未配置或未启用" in recorder.calls[0][1]
    assert DEFAULT_REF in recorder.calls[0][1] and EXTRA_REF in recorder.calls[0][1]
    assert "（当前会话）" not in recorder.calls[0][1]
    assert agent.overrides["feishu:oc_1:ou_boss"] == EXTRA_REF
    await submit(dispatcher, "/model foo")
    await wait_replies(recorder, 2)
    assert recorder.calls[1] == ("om_1", USAGE_TEXT)
    assert agent.chat_calls == []


@pytest.mark.anyio
async def test_group_members_have_distinct_external_sessions(model_chat) -> None:
    agent, recorder, dispatcher = model_chat
    agent.overrides["feishu:oc_1:ou_boss"] = EXTRA_REF
    await submit(dispatcher, "另一用户", open_id="ou_other")
    await wait_replies(recorder, 2)
    await submit(dispatcher, "另一群", chat_id="oc_2")
    await wait_replies(recorder, 4)
    assert [(call[1], call[2]) for call in agent.chat_calls] == [
        ("feishu:oc_1:ou_other", AgentActor("feishu:ou_other", "feishu")),
        ("feishu:oc_2:ou_boss", AgentActor("feishu:ou_boss", "feishu")),
    ]
    assert all("—— 当前模型" not in text for _, text in recorder.calls)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["disabled", "run", "default"])
async def test_failures_render_strict_override_or_safe_default_error(model_chat, failure, caplog) -> None:
    agent, recorder, dispatcher = model_chat
    if failure != "default":
        agent.overrides["feishu:oc_1:ou_boss"] = EXTRA_REF
    if failure == "disabled":
        agent.refs = (DEFAULT_REF,)
    elif failure == "run":
        agent.errors[EXTRA_REF] = AgentModelUnavailableError(EXTRA_REF)
    else:
        agent.errors[DEFAULT_REF] = AgentRuntimeError("AGENT_CHAT_FAILED", "api_key=sk-leaked")
    await submit(dispatcher, "失败问题")
    await wait_replies(recorder, 2)
    text = recorder.calls[-1][1]
    if failure == "default":
        assert text == FALLBACK_TEXT
    else:
        assert f"模型 {EXTRA_REF} 当前不可用" in text
        assert agent.overrides["feishu:oc_1:ou_boss"] == EXTRA_REF
    assert "sk-leaked" not in text + caplog.text


@pytest.mark.anyio
async def test_default_configuration_changes_next_turn_without_restart_hint(model_chat) -> None:
    agent, recorder, dispatcher = model_chat
    agent.default_ref = EXTRA_REF
    await submit(dispatcher, "/model current")
    await wait_replies(recorder, 1)
    assert recorder.calls[0] == ("om_1", f"当前会话模型：{EXTRA_REF}（默认）")
    await submit(dispatcher, "/model list")
    await wait_replies(recorder, 2)
    assert f"2. {EXTRA_REF}（默认）" in recorder.calls[1][1]
    assert "重启" not in recorder.calls[1][1]
    await submit(dispatcher, "下一轮")
    await wait_replies(recorder, 4)
    assert recorder.calls[-1] == ("om_1", f"回复@{EXTRA_REF}")


@pytest.mark.anyio
async def test_commands_without_configured_models(model_chat) -> None:
    agent, recorder, dispatcher = model_chat
    agent.refs, agent.default_ref = (), None
    for index, command in enumerate(["/model list", "/model current", f"/model use {EXTRA_REF}"], start=1):
        await submit(dispatcher, command)
        await wait_replies(recorder, index)
    assert recorder.calls[0] == recorder.calls[1] == ("om_1", "尚未配置可用模型。")
    assert "无法切换" in recorder.calls[2][1]
    assert agent.chat_calls == []
