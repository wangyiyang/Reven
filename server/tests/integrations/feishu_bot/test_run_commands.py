"""持久运行指令：只接受明确 UUID，传递原用户/会话，所有分支先验白名单。"""

import asyncio
from dataclasses import replace

import pytest
from agent_api_support import APPROVAL_ID, RUN, RUN_ID
from feishu_dispatch_support import FeishuAgentStub, ReplyRecorder, StubCredentials, submit, wait_replies
from reven.agent.context import AgentActor
from reven.agent.errors import AgentRuntimeError
from reven.agent.persistence_types import AgentApprovalNotFoundError
from reven.integrations.feishu_bot.chat_dispatcher import FeishuChatDispatcher
from reven.integrations.feishu_bot.run_commands import (
    RUN_USAGE_TEXT,
    parse_run_command,
    render_run_error,
    render_run_state,
)


@pytest.mark.parametrize(
    ("verb", "action"), [("确认", "approve"), ("取消", "reject"), ("状态", "status"), ("恢复", "resume")]
)
def test_parse_explicit_uuid_commands(verb: str, action: str) -> None:
    command = parse_run_command(f"  {verb}   {RUN_ID}  ")
    assert command is not None and command.action == action and command.identifier == RUN_ID


@pytest.mark.parametrize("text", ["确认", "取消 不正确", f"状态 {RUN_ID} extra", "恢复 123"])
def test_invalid_run_commands_return_help(text: str) -> None:
    command = parse_run_command(text)
    assert command is not None and command.action == "help" and command.identifier is None


@pytest.mark.parametrize("text", ["请确认删除客户", "已确认", "告诉我运行状态", "确认删除", ""])
def test_natural_language_is_not_authorization(text: str) -> None:
    assert parse_run_command(text) is None


def test_state_renders_pending_approval_and_interrupted_resume() -> None:
    pending = render_run_state(RUN)
    assert f"确认 {APPROVAL_ID}" in pending and f"取消 {APPROVAL_ID}" in pending
    assert "客户甲" in pending and "target_hash" not in pending
    interrupted = render_run_state(replace(RUN, status="interrupted", approvals=()))
    assert f"恢复 {RUN_ID}" in interrupted


def test_unknown_error_text_never_contains_upstream_exception() -> None:
    error = AgentRuntimeError("UNEXPECTED", "password=private-value")
    assert "private-value" not in render_run_error(error)
    assert "重复提交" in render_run_error(error)


def _dispatcher(agent: FeishuAgentStub, credentials: StubCredentials, recorder: ReplyRecorder) -> FeishuChatDispatcher:
    dispatcher = FeishuChatDispatcher(credentials, agent, reply=recorder)  # type: ignore[arg-type]
    dispatcher.bind_loop(asyncio.get_running_loop())
    return dispatcher


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("verb", "action"), [("确认", "approve"), ("取消", "reject"), ("状态", "status"), ("恢复", "resume")]
)
async def test_run_commands_use_original_session_and_actor_without_llm(verb: str, action: str) -> None:
    agent, credentials, recorder = FeishuAgentStub(), StubCredentials(), ReplyRecorder()
    dispatcher = _dispatcher(agent, credentials, recorder)
    identifier = APPROVAL_ID if action in {"approve", "reject"} else RUN_ID
    await submit(dispatcher, f"{verb} {identifier}")
    await wait_replies(recorder, 1)
    actor, session_id = AgentActor("feishu:ou_boss", "feishu"), "feishu:oc_1:ou_boss"
    expected = (
        ("resolve_approval", identifier, action, session_id, actor)
        if action in {"approve", "reject"}
        else ("get_run" if action == "status" else "resume_run", identifier, actor, session_id)
    )
    assert agent.command_calls == [expected] and agent.chat_calls == []
    assert len(recorder.calls) == 1 and recorder.calls[0][0] == "om_1"
    assert "思考中" not in recorder.calls[0][1]
    if action in {"approve", "reject", "resume"}:
        assert agent.command_wait_timeouts == [120.0]


@pytest.mark.anyio
async def test_other_group_is_not_allowed_to_resolve_original_confirmation() -> None:
    agent, credentials, recorder = FeishuAgentStub(), StubCredentials(), ReplyRecorder()
    agent.command_error = AgentApprovalNotFoundError()
    dispatcher = _dispatcher(agent, credentials, recorder)
    await submit(dispatcher, f"确认 {APPROVAL_ID}", chat_id="oc_other")
    await wait_replies(recorder, 1)
    assert agent.command_calls == [
        ("resolve_approval", APPROVAL_ID, "approve", "feishu:oc_other:ou_boss", AgentActor("feishu:ou_boss", "feishu"))
    ]
    assert "不属于当前会话" in recorder.calls[0][1]
    assert agent.chat_calls == []


@pytest.mark.anyio
async def test_invalid_confirmation_does_not_call_service_or_llm() -> None:
    agent, credentials, recorder = FeishuAgentStub(), StubCredentials(), ReplyRecorder()
    dispatcher = _dispatcher(agent, credentials, recorder)
    await submit(dispatcher, "确认 错误编号")
    await wait_replies(recorder, 1)
    assert recorder.calls == [("om_1", RUN_USAGE_TEXT)]
    assert agent.command_calls == agent.chat_calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "command", [f"确认 {APPROVAL_ID}", f"取消 {APPROVAL_ID}", f"状态 {RUN_ID}", f"恢复 {RUN_ID}", "/model current"]
)
async def test_commands_from_non_whitelisted_users_are_fully_silent(command: str) -> None:
    agent, credentials, recorder = FeishuAgentStub(), StubCredentials(), ReplyRecorder()
    dispatcher = _dispatcher(agent, credentials, recorder)
    await submit(dispatcher, command, open_id="ou_stranger")
    await asyncio.sleep(0.1)
    assert recorder.calls == agent.command_calls == agent.chat_calls == []


@pytest.mark.anyio
async def test_whitelist_revocation_after_precheck_prevents_confirmation_and_reply() -> None:
    class RevokedCredentials(StubCredentials):
        calls = 0

        async def feishu_bot(self):
            self.calls += 1
            return self.config if self.calls == 1 else None

    agent, credentials, recorder = FeishuAgentStub(), RevokedCredentials(), ReplyRecorder()
    dispatcher = _dispatcher(agent, credentials, recorder)
    await submit(dispatcher, f"确认 {APPROVAL_ID}")
    await asyncio.sleep(0.1)
    assert credentials.calls >= 2
    assert recorder.calls == agent.command_calls == agent.chat_calls == []
