"""Supervisor 非预期退出复位与正常停止告警边界。"""

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from reven.integrations.feishu_bot.config import FeishuBotConfig
from reven.integrations.feishu_bot.supervisor import FeishuBotSupervisor
from sqlalchemy.ext.asyncio import AsyncSession
from supervisor_test_support import (
    ConnectionFactoryStub,
    FakeChatDispatcher,
    _credentials,
    _secret_box,
    _wait_until,
    _write_bot_config,
)
from supervisor_test_support import _stub_bot_api_client as _stub_bot_api_client


class DyingConnection:
    """run 立即抛异常的假连接：模拟连接线程非预期死亡（#177）。"""

    def __init__(self) -> None:
        self.shutdown_calls = 0

    def run(self) -> None:
        raise RuntimeError("ws boom")

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def _supervisor_with_alerter(
    session: AsyncSession,
    connection_factory: Callable[[FeishuBotConfig], Any],
    alerts: list[str],
) -> FeishuBotSupervisor:
    return FeishuBotSupervisor(
        _credentials(session),
        chat_dispatcher=FakeChatDispatcher(),
        connection_factory=connection_factory,
        on_unexpected_exit=alerts.append,
    )


@pytest.mark.anyio
async def test_connection_thread_death_resets_state_and_alerts(db_session: AsyncSession) -> None:
    """连接线程非预期死亡（#177 验收：kill 飞书线程后状态复位）：

    状态复位为 dead、连接/线程引用清空、触发告警钩子；复位后 stop() 是幂等空操作。
    """
    await _write_bot_config(db_session, enabled=True)
    dying = DyingConnection()
    alerts: list[str] = []
    supervisor = _supervisor_with_alerter(db_session, lambda config: dying, alerts)

    await supervisor.start()

    assert await _wait_until(lambda: supervisor.status()["state"] == "dead")
    status = supervisor.status()
    assert status["last_started_at"] is not None  # 保留历史时间点，状态本身已不再撒谎
    assert len(alerts) == 1
    assert "dead" in alerts[0]

    supervisor.stop()
    assert dying.shutdown_calls == 0  # 死亡连接不再被 shutdown
    assert supervisor.status()["state"] == "stopped"


@pytest.mark.anyio
async def test_manual_stop_marks_stopped_without_alert(db_session: AsyncSession) -> None:
    """正常起停：running → stopped，绝不触发死亡告警，也不得被退出线程误判为 dead。"""
    await _write_bot_config(db_session, enabled=True)
    factory = ConnectionFactoryStub()
    alerts: list[str] = []
    supervisor = _supervisor_with_alerter(db_session, factory, alerts)

    assert supervisor.status() == {"state": "stopped", "last_started_at": None}

    await supervisor.start()
    assert await _wait_until(lambda: len(factory.connections) == 1)
    status = supervisor.status()
    assert status["state"] == "running"
    assert status["last_started_at"] is not None

    supervisor.stop()
    await asyncio.sleep(0.2)  # 宽限退出线程收尾：正常路径下它不得复位状态

    assert supervisor.status()["state"] == "stopped"
    assert alerts == []


@pytest.mark.anyio
async def test_reload_replacement_keeps_running_state_without_alert(db_session: AsyncSession) -> None:
    """reload 原子替换：旧线程退出是正常路径，状态保持 running 且不告警。"""
    integration = await _write_bot_config(db_session, enabled=True, secret={"app_id": "cli_old", "app_secret": "old"})
    factory = ConnectionFactoryStub()
    alerts: list[str] = []
    supervisor = _supervisor_with_alerter(db_session, factory, alerts)
    await supervisor.start()
    assert await _wait_until(lambda: len(factory.connections) == 1)

    integration.encrypted_secret = _secret_box().encrypt({"app_id": "cli_new", "app_secret": "new"})
    await db_session.commit()
    supervisor.reload()

    assert await _wait_until(lambda: factory.connections[0].shutdown_calls == 1)
    await asyncio.sleep(0.2)  # 宽限旧线程收尾
    assert supervisor.status()["state"] == "running"
    assert alerts == []
    supervisor.stop()


@pytest.mark.anyio
async def test_alert_hook_failure_does_not_propagate(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """告警钩子自身失败只记日志，状态复位不受影响。"""

    def bad_alerter(message: str) -> None:
        raise RuntimeError("notify down")

    await _write_bot_config(db_session, enabled=True)
    dying = DyingConnection()
    supervisor = FeishuBotSupervisor(
        _credentials(db_session),
        chat_dispatcher=FakeChatDispatcher(),
        connection_factory=lambda config: dying,
        on_unexpected_exit=bad_alerter,
    )

    with caplog.at_level("WARNING"):
        await supervisor.start()
        assert await _wait_until(lambda: supervisor.status()["state"] == "dead")

    assert "死亡告警回调失败" in caplog.text
