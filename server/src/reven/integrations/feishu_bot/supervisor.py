"""飞书机器人 WebSocket 长连接生命周期管理。

FeishuBotSupervisor 按 integrations 表中 feishu_bot 的配置驱动 lark-oapi ws.Client：
- start()：由 FastAPI lifespan 调用，按当前配置确保连接在运行（幂等）；
- reload()：配置变更时由路由调用，同步返回，内部另起线程读最新配置并原子替换连接；
- stop()：进程关闭时调用，尽力停止当前连接（幂等）。

review_callback（审核按钮回调分发器）随 start() 绑定主事件循环，并接入每代连接的事件分发器。
配置读取/解密失败只记 provider + 异常类型的日志，绝不阻断主进程。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reven.integrations.feishu_bot.config import PROVIDER, load_feishu_bot_config
from reven.integrations.feishu_bot.review_callback import ReviewActionDispatch, ReviewCallback
from reven.security.secrets import SecretBox

logger = logging.getLogger(__name__)

_CONFIG_READ_TIMEOUT_SECONDS = 10  # reload 线程等待主事件循环返回配置读取结果
_THREAD_JOIN_TIMEOUT_SECONDS = 2  # 停止时等待连接线程退出（尽力而为，不阻塞调用方）
_LOOP_SHUTDOWN_TIMEOUT_SECONDS = 2  # 等待代际事件循环就绪/执行断开调度


class BotConnection(Protocol):
    """一代长连接：run 阻塞运行（连接线程内），shutdown 尽力停止（任意线程调用）。"""

    def run(self) -> None: ...

    def shutdown(self) -> None: ...


@dataclass(frozen=True)
class FeishuBotCredentials:
    app_id: str = field(repr=False)
    app_secret: str = field(repr=False)


ConnectionFactory = Callable[[FeishuBotCredentials], BotConnection]


class FeishuBotSupervisor:
    """线程安全的 ws.Client 生命周期管理器；所有公开方法幂等。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_box: SecretBox,
        *,
        connection_factory: ConnectionFactory | None = None,
        review_callback: ReviewCallback | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._secret_box = secret_box
        self._review_callback = review_callback
        self._connection_factory = connection_factory or self._build_default_connection
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._connection: BotConnection | None = None
        self._thread: threading.Thread | None = None

    def _build_default_connection(self, credentials: FeishuBotCredentials) -> BotConnection:
        """默认连接工厂：建 LarkWsConnection 并把审核回调接进事件分发器。"""
        return LarkWsConnection(credentials, review_callback=self._review_callback)

    async def start(self) -> None:
        """按当前配置确保连接在运行；已在运行时直接返回。"""
        self._main_loop = asyncio.get_running_loop()
        if self._review_callback is not None:
            self._review_callback.bind_loop(self._main_loop)
        with self._lock:
            if self._connection is not None:
                return
        credentials = await self._load_credentials()
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
        try:
            future = asyncio.run_coroutine_threadsafe(self._load_credentials(), loop)
            credentials = future.result(timeout=_CONFIG_READ_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("飞书机器人配置热更新读取失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
            return
        self._replace_connection(credentials)

    def _replace_connection(self, credentials: FeishuBotCredentials | None) -> None:
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

    def _run_connection(self, connection: BotConnection) -> None:
        try:
            connection.run()
        except Exception as exc:
            logger.warning("飞书机器人长连接线程异常退出（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)

    def _stop_locked(self) -> None:
        connection = self._connection
        thread = self._thread
        self._connection = None
        self._thread = None
        if connection is None:
            return
        try:
            connection.shutdown()
        except Exception as exc:
            logger.warning("飞书机器人连接停止失败（provider=%s, error_type=%s）", PROVIDER, type(exc).__name__)
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=_THREAD_JOIN_TIMEOUT_SECONDS)

    async def _load_credentials(self) -> FeishuBotCredentials | None:
        """读取 feishu_bot 配置；未配置/未启用/凭证不完整/读取失败均返回 None。"""
        config = await load_feishu_bot_config(self._session_factory, self._secret_box)
        if config is None:
            return None
        return FeishuBotCredentials(app_id=config.app_id, app_secret=config.app_secret)


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
        credentials: FeishuBotCredentials,
        *,
        review_callback: ReviewActionDispatch | None = None,
    ) -> None:
        import lark_oapi  # type: ignore[import-untyped]  # 延迟导入：避免进程导入期触发 SDK 模块级事件循环副作用

        from reven.integrations.feishu_bot.handlers import build_event_handler

        self._client: Any = lark_oapi.ws.Client(
            credentials.app_id,
            credentials.app_secret,
            event_handler=build_event_handler(
                credentials.app_id,
                credentials.app_secret,
                review_dispatch=review_callback,
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
