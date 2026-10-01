"""关闭循环与连接退出告警竞争时，协程必须显式关闭。"""

from types import SimpleNamespace
from typing import cast

import pytest
from reven.app import _build_feishu_exit_alerter
from reven.integrations.feishu_bot.supervisor import FeishuBotSupervisor
from reven.provider_clients import ProviderClients


def test_exit_alert_closes_coroutine_when_loop_closes_during_dispatch(monkeypatch, caplog) -> None:
    loop = SimpleNamespace(is_closed=lambda: False)
    supervisor = cast(FeishuBotSupervisor, SimpleNamespace(main_loop=loop))
    captured = []

    def fail_schedule(coro, target_loop):
        assert target_loop is loop
        captured.append(coro)
        raise RuntimeError("loop closed, credential=secret-value")

    monkeypatch.setattr("reven.app.asyncio.run_coroutine_threadsafe", fail_schedule)
    with caplog.at_level("WARNING", logger="reven.app"):
        _build_feishu_exit_alerter(cast(ProviderClients, object()), supervisor)("连接退出")

    assert len(captured) == 1 and captured[0].cr_frame is None
    assert "error_type=RuntimeError" in caplog.text
    assert "secret-value" not in caplog.text


@pytest.mark.parametrize("loop", [None, SimpleNamespace(is_closed=lambda: True)])
def test_exit_alert_skips_unavailable_loop(loop, monkeypatch) -> None:
    supervisor = cast(FeishuBotSupervisor, SimpleNamespace(main_loop=loop))

    def unexpected_schedule(*args):
        pytest.fail("不可用循环不应调度告警")

    monkeypatch.setattr("reven.app.asyncio.run_coroutine_threadsafe", unexpected_schedule)
    _build_feishu_exit_alerter(cast(ProviderClients, object()), supervisor)("连接退出")
