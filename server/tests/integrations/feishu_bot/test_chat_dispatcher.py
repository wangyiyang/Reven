"""FeishuChatDispatcher：白名单现读、两座线程桥、超时/异常兜底、非白名单全静默。

桥接测试范式复刻自 3c44e27^ 的 test_review_callback.py：
`bind_loop(asyncio.get_running_loop())` 后经 `asyncio.to_thread` 以 SDK 线程视角
投递，工作线程的回复经轮询等待；dead loop 模拟 run_coroutine_threadsafe 调度失败。
除「白名单 db 现读」用例外均用 _StubCredentials，无需真实数据库。
"""

import asyncio
import base64
import logging
import time
from uuid import UUID

import pytest
from reven.agent.context import AgentActor
from reven.agent.errors import AgentError, AgentNotConfiguredError, AgentRuntimeError
from reven.agent.service_types import AgentTurn
from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.chat_dispatcher import (
    FALLBACK_TEXT,
    GUIDE_TEXT,
    THINKING_TEXT,
    UNSUPPORTED_TEXT,
    FeishuChatDispatcher,
)
from reven.integrations.feishu_bot.config import FeishuBotConfig
from reven.integrations.feishu_bot.run_commands import render_run_error
from reven.integrations.models import Integration
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"m" * 32).decode()
WHITELISTED_CONFIG = FeishuBotConfig(app_id="cli_test", app_secret="s3cret", whitelist_open_ids=("ou_boss",))
RUN_ID = UUID("5f69874c-b6c4-4a67-acf1-d2ea7c28e232")


def _factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(session.bind, expire_on_commit=False)


def _secret_box() -> SecretBox:
    return SecretBox.from_base64(TEST_MASTER_KEY)


def _credentials(session: AsyncSession) -> IntegrationCredentials:
    settings = Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1/unused",
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
    )
    return IntegrationCredentials(_factory(session), settings)


async def _write_bot_config(
    session: AsyncSession,
    *,
    enabled: bool = True,
    whitelist: tuple[str, ...] = ("ou_boss",),
) -> Integration:
    integration = Integration(
        provider="feishu_bot",
        public_config={"whitelist_open_ids": list(whitelist), "enabled": enabled},
        encrypted_secret=_secret_box().encrypt({"app_id": "cli_test", "app_secret": "s3cret"}),
    )
    session.add(integration)
    await session.commit()
    return integration


class _StubCredentials:
    """不走 db 的 credentials seam 替身：feishu_bot() 返回固定配置。"""

    def __init__(self, config: FeishuBotConfig | None, *, delay: float = 0.0) -> None:
        self._config = config
        self._delay = delay

    async def feishu_bot(self) -> FeishuBotConfig | None:
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._config


class _StubAgentService:
    """记录对话调用；可配置返回文本 / 抛错 / 延迟。"""

    def __init__(self, *, answer: str = "答案", error: Exception | None = None, delay: float = 0.0) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.contexts: list[tuple[AgentActor, str | None, float | None]] = []
        self._answer = answer
        self._error = error
        self._delay = delay

    async def chat(
        self,
        message: str,
        session_id: str | None = None,
        *,
        actor: AgentActor,
        request_key: str | None = None,
        wait_timeout_seconds: float | None = None,
    ) -> AgentTurn:
        self.calls.append((message, session_id))
        self.contexts.append((actor, request_key, wait_timeout_seconds))
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return AgentTurn("sid", self._answer, None, False, RUN_ID)


class ReplyRecorder:
    def __init__(self, *, fail_on: frozenset[int] = frozenset()) -> None:
        self.calls: list[tuple[str, str]] = []
        self.loops: list[asyncio.AbstractEventLoop] = []
        self._fail_on = fail_on

    async def __call__(self, message_id: str, text: str) -> None:
        self.calls.append((message_id, text))
        self.loops.append(asyncio.get_running_loop())
        if len(self.calls) in self._fail_on:
            raise RuntimeError("飞书 API 不可用")


def _dispatcher(
    credentials: object, agent: _StubAgentService, *, reply: ReplyRecorder, **kwargs: float
) -> FeishuChatDispatcher:
    return FeishuChatDispatcher(credentials, agent, reply=reply, **kwargs)  # type: ignore[arg-type]


async def _submit(dispatcher: FeishuChatDispatcher, *, kind: str = "chat", **kwargs: str) -> None:
    """以 SDK 连接线程视角投递一条消息（submit 必须立即返回）。"""
    params = {"message_id": "om_1", "chat_id": "oc_1", "open_id": "ou_boss", "text": "你好", **kwargs}
    await asyncio.to_thread(dispatcher.submit, kind=kind, **params)  # type: ignore[arg-type]


async def _wait_replies(recorder: ReplyRecorder, count: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while len(recorder.calls) < count and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    if len(recorder.calls) < count:
        raise AssertionError(f"等待回复超时：期望 {count} 条，实际 {recorder.calls!r}")


# --- 正常流转：两座桥 + 两类直复 ---


@pytest.mark.anyio
async def test_chat_submit_replies_thinking_then_answer() -> None:
    agent = _StubAgentService()
    recorder = ReplyRecorder()
    dispatcher = _dispatcher(_StubCredentials(WHITELISTED_CONFIG), agent, reply=recorder)
    dispatcher.bind_loop(asyncio.get_running_loop())

    await _submit(dispatcher)
    await _wait_replies(recorder, 2)

    assert recorder.calls == [("om_1", THINKING_TEXT), ("om_1", "答案")]
    assert recorder.loops == [asyncio.get_running_loop()] * 2
    assert agent.calls == [("你好", "feishu:oc_1:ou_boss")]


@pytest.mark.anyio
async def test_guide_kind_replies_guide_text_without_agent() -> None:
    agent = _StubAgentService()
    recorder = ReplyRecorder()
    dispatcher = _dispatcher(_StubCredentials(WHITELISTED_CONFIG), agent, reply=recorder)
    dispatcher.bind_loop(asyncio.get_running_loop())

    await _submit(dispatcher, kind="guide", text="")
    await _wait_replies(recorder, 1)

    assert recorder.calls == [("om_1", GUIDE_TEXT)]
    assert agent.calls == []


@pytest.mark.anyio
async def test_unsupported_kind_replies_unsupported_text_without_agent() -> None:
    agent = _StubAgentService()
    recorder = ReplyRecorder()
    dispatcher = _dispatcher(_StubCredentials(WHITELISTED_CONFIG), agent, reply=recorder)
    dispatcher.bind_loop(asyncio.get_running_loop())

    await _submit(dispatcher, kind="unsupported", text="")
    await _wait_replies(recorder, 1)

    assert recorder.calls == [("om_1", UNSUPPORTED_TEXT)]
    assert agent.calls == []


# --- 静默分支：非白名单 / 配置缺失 / 未绑 loop / 桥接调度失败 ---


@pytest.mark.anyio
async def test_submit_returns_while_async_reply_is_waiting() -> None:
    started, release = asyncio.Event(), asyncio.Event()
    agent = _StubAgentService()
    recorder = ReplyRecorder()

    async def reply(message_id: str, text: str) -> None:
        started.set()
        await release.wait()
        await recorder(message_id, text)

    dispatcher = FeishuChatDispatcher(_StubCredentials(WHITELISTED_CONFIG), agent, reply=reply)  # type: ignore[arg-type]
    dispatcher.bind_loop(asyncio.get_running_loop())
    await asyncio.wait_for(_submit(dispatcher), timeout=1)
    await asyncio.wait_for(started.wait(), timeout=1)
    assert recorder.calls == [] and agent.calls == []
    release.set()
    await _wait_replies(recorder, 2)


@pytest.mark.anyio
async def test_reply_schedule_failure_closes_coroutine_and_aborts_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    schedule = asyncio.run_coroutine_threadsafe

    def fail_reply(coro, loop):
        if coro.cr_code.co_name == "_send_reply":
            raise RuntimeError("closed loop")
        return schedule(coro, loop)

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", fail_reply)
    agent, recorder = _StubAgentService(), ReplyRecorder()
    dispatcher = _dispatcher(_StubCredentials(WHITELISTED_CONFIG), agent, reply=recorder)
    dispatcher.bind_loop(asyncio.get_running_loop())
    await _submit(dispatcher)
    await asyncio.sleep(0.2)
    assert recorder.calls == [] and agent.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["chat", "guide", "unsupported"])
async def test_non_whitelisted_user_is_fully_silent(kind: str) -> None:
    agent = _StubAgentService()
    recorder = ReplyRecorder()
    dispatcher = _dispatcher(_StubCredentials(WHITELISTED_CONFIG), agent, reply=recorder)
    dispatcher.bind_loop(asyncio.get_running_loop())

    await _submit(dispatcher, kind=kind, open_id="ou_stranger")
    await asyncio.sleep(0.3)  # 宽限工作线程收尾：任何消息都不应发出

    assert recorder.calls == []
    assert agent.calls == []


@pytest.mark.anyio
async def test_missing_config_is_fully_silent() -> None:
    agent = _StubAgentService()
    recorder = ReplyRecorder()
    dispatcher = _dispatcher(_StubCredentials(None), agent, reply=recorder)
    dispatcher.bind_loop(asyncio.get_running_loop())

    await _submit(dispatcher)
    await asyncio.sleep(0.3)

    assert recorder.calls == []
    assert agent.calls == []


@pytest.mark.anyio
async def test_submit_without_bound_loop_is_ignored() -> None:
    agent = _StubAgentService()
    recorder = ReplyRecorder()
    dispatcher = _dispatcher(_StubCredentials(WHITELISTED_CONFIG), agent, reply=recorder)

    await _submit(dispatcher)
    await asyncio.sleep(0.2)

    assert recorder.calls == []
    assert agent.calls == []


@pytest.mark.anyio
async def test_dead_loop_schedule_failure_closes_coroutine_and_stays_silent() -> None:
    agent = _StubAgentService()
    recorder = ReplyRecorder()
    dispatcher = _dispatcher(_StubCredentials(WHITELISTED_CONFIG), agent, reply=recorder)
    dead_loop = asyncio.new_event_loop()
    dead_loop.close()
    dispatcher.bind_loop(dead_loop)

    await _submit(dispatcher)
    await asyncio.sleep(0.3)

    assert recorder.calls == []  # 预检桥调度失败：协程已 close，本轮全静默
    assert agent.calls == []


@pytest.mark.anyio
async def test_precheck_timeout_is_fully_silent() -> None:
    agent = _StubAgentService()
    recorder = ReplyRecorder()
    dispatcher = _dispatcher(
        _StubCredentials(WHITELISTED_CONFIG, delay=0.3), agent, reply=recorder, precheck_timeout_seconds=0.05
    )
    dispatcher.bind_loop(asyncio.get_running_loop())

    await _submit(dispatcher)
    await asyncio.sleep(0.6)  # 宽限慢预检协程跑完：超时后仍不得补发任何消息

    assert recorder.calls == []
    assert agent.calls == []


# --- chat 桥兜底：超时 / AgentError / 未知异常 / 回复失败 ---


@pytest.mark.anyio
async def test_service_wait_budget_returns_run_state_before_bridge_timeout() -> None:
    answer = f"运行仍在进行，请查询：状态 {RUN_ID}。"
    agent = _StubAgentService(answer=answer, delay=0.06)
    recorder = ReplyRecorder()
    dispatcher = _dispatcher(_StubCredentials(WHITELISTED_CONFIG), agent, reply=recorder, timeout_seconds=0.05)
    dispatcher.bind_loop(asyncio.get_running_loop())

    await _submit(dispatcher)
    await _wait_replies(recorder, 2)

    assert recorder.calls == [("om_1", THINKING_TEXT), ("om_1", answer)]
    assert agent.contexts == [(AgentActor("feishu:ou_boss", "feishu"), "om_1", 0.05)]
    assert "重试" not in recorder.calls[-1][1]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error",
    [
        AgentNotConfiguredError(),
        AgentRuntimeError("AGENT_CHAT_FAILED", "upstream api_key=sk-secret"),
        RuntimeError("db-credential-value"),
    ],
)
async def test_agent_error_falls_back_and_log_is_sanitized(error: Exception, caplog: pytest.LogCaptureFixture) -> None:
    agent = _StubAgentService(error=error)
    recorder = ReplyRecorder()
    dispatcher = _dispatcher(_StubCredentials(WHITELISTED_CONFIG), agent, reply=recorder)
    dispatcher.bind_loop(asyncio.get_running_loop())

    with caplog.at_level(logging.WARNING):
        await _submit(dispatcher)
        await _wait_replies(recorder, 2)

    expected = render_run_error(error) if isinstance(error, AgentError) else FALLBACK_TEXT
    assert recorder.calls == [("om_1", THINKING_TEXT), ("om_1", expected)]
    assert type(error).__name__ in caplog.text
    if isinstance(error, AgentError):
        assert error.code in caplog.text  # 稳定错误码进日志（PRD：完整错误进服务端日志）
    assert "db-credential-value" not in caplog.text  # 日志脱敏：异常 message 不进日志，只记类型与稳定码
    assert "sk-secret" not in caplog.text


@pytest.mark.anyio
async def test_thinking_placeholder_failure_aborts_turn() -> None:
    agent = _StubAgentService()
    recorder = ReplyRecorder(fail_on=frozenset({1}))
    dispatcher = _dispatcher(_StubCredentials(WHITELISTED_CONFIG), agent, reply=recorder)
    dispatcher.bind_loop(asyncio.get_running_loop())

    await _submit(dispatcher)
    await asyncio.sleep(0.3)

    assert recorder.calls == [("om_1", THINKING_TEXT)]  # 占位发不出即放弃本轮，不再尝试发结果
    assert agent.calls == []


@pytest.mark.anyio
async def test_answer_reply_failure_is_swallowed() -> None:
    agent = _StubAgentService()
    recorder = ReplyRecorder(fail_on=frozenset({2}))  # 结果回复失败：工作线程收敛异常，不向调用方抛
    dispatcher = _dispatcher(_StubCredentials(WHITELISTED_CONFIG), agent, reply=recorder)
    dispatcher.bind_loop(asyncio.get_running_loop())

    await _submit(dispatcher)
    await asyncio.sleep(0.3)  # 工作线程收敛异常，不向调用方抛

    assert recorder.calls == [("om_1", THINKING_TEXT), ("om_1", "答案")]
    assert agent.calls == [("你好", "feishu:oc_1:ou_boss")]


@pytest.mark.anyio
async def test_whitelist_revocation_before_result_prevents_visible_reply() -> None:
    agent, recorder = _StubAgentService(delay=0.1), ReplyRecorder()
    credentials = _StubCredentials(WHITELISTED_CONFIG)
    dispatcher = _dispatcher(credentials, agent, reply=recorder)
    dispatcher.bind_loop(asyncio.get_running_loop())
    await _submit(dispatcher)
    for _ in range(100):
        if agent.calls:
            break
        await asyncio.sleep(0.005)
    assert agent.calls
    credentials._config = None
    await asyncio.sleep(0.2)
    assert recorder.calls == [("om_1", THINKING_TEXT)]


# --- 真实 credentials seam：db 配置接线与白名单现读 ---


@pytest.mark.anyio
async def test_chat_roundtrip_with_db_credentials(db_session: AsyncSession) -> None:
    await _write_bot_config(db_session)
    agent = _StubAgentService()
    recorder = ReplyRecorder()
    dispatcher = _dispatcher(_credentials(db_session), agent, reply=recorder)
    dispatcher.bind_loop(asyncio.get_running_loop())

    await _submit(dispatcher)
    await _wait_replies(recorder, 2)

    assert recorder.calls == [("om_1", THINKING_TEXT), ("om_1", "答案")]
    assert agent.calls == [("你好", "feishu:oc_1:ou_boss")]


@pytest.mark.anyio
async def test_whitelist_is_reread_on_every_turn(db_session: AsyncSession) -> None:
    integration = await _write_bot_config(db_session)
    agent = _StubAgentService()
    recorder = ReplyRecorder()
    dispatcher = _dispatcher(_credentials(db_session), agent, reply=recorder)
    dispatcher.bind_loop(asyncio.get_running_loop())

    await _submit(dispatcher)
    await _wait_replies(recorder, 2)
    assert [text for _, text in recorder.calls] == [THINKING_TEXT, "答案"]

    integration.public_config = {"whitelist_open_ids": ["ou_other"], "enabled": True}
    await db_session.commit()

    recorder.calls.clear()
    await _submit(dispatcher)
    await asyncio.sleep(0.3)  # 白名单收紧即时生效：全静默，不进 Agent

    assert recorder.calls == []
    assert len(agent.calls) == 1
