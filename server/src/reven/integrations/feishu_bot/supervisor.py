"""飞书机器人 WebSocket 长连接生命周期管理。

FeishuBotSupervisor 按 integrations 表中 feishu_bot 的配置驱动 lark-oapi ws.Client：
- start()：由 FastAPI lifespan 调用，按当前配置确保连接在运行（幂等）；
- reload()：配置变更时由路由调用，同步返回，内部另起线程读最新配置并原子替换连接；
- stop()：进程关闭时调用，尽力停止当前连接（幂等）。

状态机（#177）：running（连接线程在跑）/ stopped（正常停止）/ dead（线程非预期死亡）。
连接线程一旦非预期退出，_on_connection_exit 同步把状态复位为 dead 并触发告警钩子——
杜绝"线程已死但状态仍新鲜"的静默死亡（10-01 故障同类）；status() 供监控抓取。

配置读取/解密失败只记 provider + 异常类型的日志，绝不阻断主进程。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from typing import Any, Protocol

from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.chat_dispatcher import ChatDispatch
from reven.integrations.feishu_bot.client import FeishuBotApiClient
from reven.integrations.feishu_bot.config import PROVIDER, FeishuBotConfig
from reven.scheduling import utc_now

logger = logging.getLogger(__name__)

_CONFIG_READ_TIMEOUT_SECONDS = 10  # reload 线程等待主事件循环返回配置读取结果
_THREAD_JOIN_TIMEOUT_SECONDS = 2  # 停止时等待连接线程退出（尽力而为，不阻塞调用方）
_LOOP_SHUTDOWN_TIMEOUT_SECONDS = 2  # 等待代际事件循环就绪/执行断开调度


class BotConnection(Protocol):
    """一代长连接：run 阻塞运行（连接线程内），shutdown 尽力停止（任意线程调用）。"""

    def run(self) -> None: ...

    def shutdown(self) -> None: ...


ConnectionFactory = Callable[[FeishuBotConfig], BotConnection]


class FeishuBotSupervisor:
    """线程安全的 ws.Client 生命周期管理器；所有公开方法幂等。

    状态机（#177）：running → stop()/reload() 正常替换 → stopped；连接线程非预期死亡 → dead。
    dead 由 _on_connection_exit 在确认死亡线程仍是当前连接后复位（同时清空连接/线程引用），
    并经 on_unexpected_exit 钩子告警；监控读 status() 即可发现死亡，不再被新鲜 last_started_at 蒙蔽。
    """

    def __init__(
        self,
        credentials: IntegrationCredentials,
        *,
        chat_dispatcher: ChatDispatch,
        connection_factory: ConnectionFactory | None = None,
        on_unexpected_exit: Callable[[str], None] | None = None,
    ) -> None:
        self._credentials = credentials
        self._chat_dispatcher = chat_dispatcher
        self._connection_factory = connection_factory or self._build_default_connection
        # 非预期死亡告警钩子（接 notify 通道，由组合根装配）；同步回调，在连接线程内触发，必须快速返回
        self.on_unexpected_exit = on_unexpected_exit
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._bot_open_id: str | None = None
        self._lock = threading.Lock()
        self._connection: BotConnection | None = None
        self._thread: threading.Thread | None = None
        self._state = "stopped"
        self._last_started_at: datetime | None = None

    @property
    def main_loop(self) -> asyncio.AbstractEventLoop | None:
        """主事件循环（组合根的告警钩子用它把异步投递调度回主线程）。"""
        return self._main_loop

    def status(self) -> dict[str, str | None]:
        """监控用连接状态：state ∈ running/stopped/dead；last_started_at 为 ISO 时间或 None。"""
        with self._lock:
            started = self._last_started_at
            return {"state": self._state, "last_started_at": started.isoformat() if started is not None else None}

    def _build_default_connection(self, credentials: FeishuBotConfig) -> BotConnection:
        """默认连接工厂：建 LarkWsConnection（透传 bot open_id 与对话分发器）。"""
        return LarkWsConnection(credentials, bot_open_id=self._bot_open_id, chat_dispatch=self._chat_dispatcher)

    async def start(self) -> None:
        """按当前配置确保连接在运行；已在运行时直接返回。"""
        self._main_loop = asyncio.get_running_loop()
        self._chat_dispatcher.bind_loop(self._main_loop)
        with self._lock:
            if self._connection is not None:
                return
        credentials = await self._prepare_credentials()
        self._replace_connection(credentials)

    def stop(self) -> None:
        """停止当前连接；无连接时是空操作。"""
        self._replace_connection(None)

    def reload(self) -> None:
        """配置热更新：同步返回，内部另起线程读最新配置并原子替换连接。"""
        threading.Thread(target=self._reload_in_thread, daemon=True, name="feishu-bot-reload").start()

    def _reload_in_thread(self) -> None:
        loop = self._main_loop
        if loop is None:
            logger.warning("飞书机器人 reload 忽略：主事件循环尚未就绪（provider=%s）", PROVIDER)
            return
        coro = self._prepare_credentials()
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception as exc:
            coro.close()  # 调度失败时协程从未被 await，必须显式 close 避免泄漏（RuntimeWarning）
            logger.warning("飞书机器人配置热更新读取失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
            return
        try:
            credentials = future.result(timeout=_CONFIG_READ_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("飞书机器人配置热更新读取失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
            return
        self._replace_connection(credentials)

    def _replace_connection(self, credentials: FeishuBotConfig | None) -> None:
        """原子替换：先停旧连接，再按给定配置建新连接；配置为 None 时仅停旧。"""
        with self._lock:
            self._stop_locked()
            if credentials is None:
                return
            try:
                connection = self._connection_factory(credentials)
                thread = threading.Thread(
                    target=self._run_connection,
                    args=(connection,),
                    daemon=True,
                    name="feishu-bot-ws",
                )
                thread.start()
            except Exception as exc:
                logger.warning("飞书机器人长连接启动失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
                return
            self._connection = connection
            self._thread = thread
            self._state = "running"
            self._last_started_at = utc_now()

    def _run_connection(self, connection: BotConnection) -> None:
        try:
            connection.run()
        except Exception as exc:
            logger.warning("飞书机器人长连接线程异常退出（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
        finally:
            self._on_connection_exit(connection)

    def _on_connection_exit(self, connection: BotConnection) -> None:
        """连接线程退出复位（#177）：仍是当前连接即非预期死亡——复位状态为 dead 并告警，杜绝静默死亡。

        stop()/reload() 会先把 _connection 置 None 再 shutdown，因此正常替换路径下
        死亡线程进来时 _connection 已不是它，直接返回（状态由 _stop_locked 管理）。
        """
        with self._lock:
            if self._connection is not connection:
                return
            self._connection = None
            self._thread = None
            self._state = "dead"
        logger.warning("飞书机器人长连接意外终止，状态已复位为 dead（provider=%s）", PROVIDER)
        alerter = self.on_unexpected_exit
        if alerter is None:
            return
        try:
            alerter("飞书机器人长连接意外终止，状态已复位为 dead，请检查机器人配置与网络")
        except Exception as exc:
            logger.warning("飞书机器人死亡告警回调失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)

    def _stop_locked(self) -> None:
        connection = self._connection
        thread = self._thread
        self._connection = None
        self._thread = None
        self._state = "stopped"
        if connection is None:
            return
        try:
            connection.shutdown()
        except Exception as exc:
            logger.warning("飞书机器人连接停止失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=_THREAD_JOIN_TIMEOUT_SECONDS)

    async def _load_credentials(self) -> FeishuBotConfig | None:
        """读取 feishu_bot 配置；未配置/未启用/凭证不完整/读取失败均返回 None。"""
        return await self._credentials.feishu_bot()

    async def _prepare_credentials(self) -> FeishuBotConfig | None:
        """读取配置并按需补齐 bot open_id（群聊 @ 判定用；为 None 时重试，成功一次后不再拉取）。"""
        credentials = await self._load_credentials()
        if credentials is not None and self._bot_open_id is None:
            self._bot_open_id = await self._fetch_bot_open_id(credentials)
        return credentials

    async def _fetch_bot_open_id(self, credentials: FeishuBotConfig) -> str | None:
        """获取机器人 open_id；失败降级为 None：群聊消息忽略（记日志），私聊对话不受影响。"""
        try:
            return await FeishuBotApiClient(credentials.app_id, credentials.app_secret).get_bot_open_id()
        except Exception as exc:
            logger.warning(
                "飞书机器人 open_id 获取失败，群聊消息将忽略（provider=%s, error_type=%s）",
                PROVIDER,
                type(exc).__name__,
            )
            return None


class LarkWsConnection:
    """lark-oapi ws.Client 一代连接。

    SDK 仅提供阻塞式 start()、无公开 stop()，且内部硬编码引用
    ``lark_oapi.ws.client`` 模块级事件循环。本类在连接线程内按代际新建事件循环
    并替换该模块级引用，保证多代连接互不干扰；shutdown() 以"关闭自动重连 +
    断开当前连接 + 停止代际循环"尽力停止。以上私有 API 在 SDK 升级后若失效，
    静默降级为"daemon 线程随进程退出回收"。断线重连由 SDK 内建，不在本类实现。
    """

    def __init__(
        self,
        credentials: FeishuBotConfig,
        *,
        bot_open_id: str | None,
        chat_dispatch: ChatDispatch,
    ) -> None:
        import lark_oapi  # type: ignore[import-untyped]  # 延迟导入：避免进程导入期触发 SDK 模块级事件循环副作用

        from reven.integrations.feishu_bot.handlers import build_event_handler

        self._client: Any = lark_oapi.ws.Client(
            credentials.app_id,
            credentials.app_secret,
            event_handler=build_event_handler(
                bot_open_id=bot_open_id,
                chat_dispatch=chat_dispatch,
            ),
            log_level=lark_oapi.LogLevel.INFO,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._stop_requested = False

    def run(self) -> None:
        import lark_oapi.ws.client as ws_client_module  # type: ignore[import-untyped]

        try:
            loop = asyncio.new_event_loop()
            ws_client_module.loop = loop  # SDK 私有：按代际替换模块级循环
            self._loop = loop
        except Exception as exc:
            logger.warning("飞书机器人事件循环初始化失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
            self._ready.set()
            return
        self._ready.set()
        try:
            if self._stop_requested:
                return
            self._client.start()  # 阻塞直到连接断开且不再重连，或代际循环被 shutdown 停止
        except Exception as exc:
            logger.warning("飞书机器人长连接退出（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
        finally:
            with suppress(Exception):
                loop.close()

    def shutdown(self) -> None:
        self._stop_requested = True
        with suppress(Exception):
            self._client._auto_reconnect = False  # SDK 私有：阻断断线重连
        if not self._ready.wait(timeout=_LOOP_SHUTDOWN_TIMEOUT_SECONDS):
            return
        loop = self._loop
        if loop is None:
            return
        with suppress(Exception):
            if loop.is_running():
                future = asyncio.run_coroutine_threadsafe(self._client._disconnect(), loop)  # SDK 私有
                future.result(timeout=_LOOP_SHUTDOWN_TIMEOUT_SECONDS)
        with suppress(Exception):
            loop.call_soon_threadsafe(loop.stop)
