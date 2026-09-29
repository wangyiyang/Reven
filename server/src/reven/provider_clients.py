"""外部 provider HTTP 客户端装配 seam：lifespan 构建并持有，统一超时与连接策略。

- 凭证解析全部经 IntegrationCredentials 单例；配置不可用一律 yield None，
  由调用方按领域语义降级或报错（通知/刷新抛固定错误，discovery tick 降级跳过）。
- feishu_bot() 的 httpx client 长驻复用（热点路径），aclose() 时统一关闭；
  凭证每次调用现读，配置热更新后下一次调用即生效。
- embedding() / siliconflow_chat() 的 httpx client 随配置可能变化，每次短驻、用毕即关。
- 落在顶层而非 integrations/ 内：SiliconFlow 客户端属于 rss 层，integrations 反向依赖会造成层级倒置。
- FeishuNotifier 是本 seam 上唯一的生产 DeliveryNotifier 适配器；放在此处而非 notifications.py，
  是为了让通知契约保持零依赖（rss.discovery 只需契约），避免与 rss 客户端导入成环。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.feishu_bot.client import FeishuBotApiClient
from reven.integrations.feishu_bot.config import FeishuBotConfig
from reven.notifications import Notification
from reven.rss.ai import SiliconFlowChatClient
from reven.rss.embedding import BGE_M3_MODEL, Embedder, SiliconFlowEmbeddingClient

SILICONFLOW_BASE_URL = "https://api.siliconflow.cn"
SILICONFLOW_TIMEOUT = httpx.Timeout(45.0)
FEISHU_TIMEOUT = httpx.Timeout(10.0)


@dataclass(frozen=True)
class FeishuBotClient:
    """feishu_bot 就绪句柄：一份当前配置 + 绑定共享 http 的 API 客户端。"""

    config: FeishuBotConfig
    api: FeishuBotApiClient


class ProviderClients:
    """provider 客户端 seam：IntegrationCredentials + Settings 进，typed client 出。"""

    def __init__(
        self,
        credentials: IntegrationCredentials,
        settings: Settings,
        *,
        feishu_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._credentials = credentials
        self._settings = settings
        self._feishu_transport = feishu_transport
        self._feishu_http: httpx.AsyncClient | None = None

    @property
    def credentials(self) -> IntegrationCredentials:
        return self._credentials

    @asynccontextmanager
    async def feishu_bot(self) -> AsyncIterator[FeishuBotClient | None]:
        """feishu_bot 客户端：未配置/禁用/凭证不可用 yield None；http 长驻复用，退出上下文不关闭。"""
        config = await self._credentials.feishu_bot()
        if config is None:
            yield None
            return
        yield FeishuBotClient(config, FeishuBotApiClient(config.app_id, config.app_secret, http=self._http()))

    @asynccontextmanager
    async def embedding(self) -> AsyncIterator[Embedder | None]:
        """embedding 客户端：DB 优先、env 兜底并套默认 base_url/model；未配置 yield None。

        密文损坏维持 INTEGRATION_SECRET_INVALID 领域错误（IntegrationCredentials 约定）。
        """
        credentials = await self._credentials.embedding()
        if credentials is None:
            yield None
            return
        base_url = credentials.base_url or SILICONFLOW_BASE_URL
        model = credentials.model or BGE_M3_MODEL
        async with httpx.AsyncClient(base_url=base_url, timeout=SILICONFLOW_TIMEOUT, trust_env=False) as http:
            yield SiliconFlowEmbeddingClient(credentials.api_key, http=http, model=model)

    @asynccontextmanager
    async def siliconflow_chat(self) -> AsyncIterator[SiliconFlowChatClient | None]:
        """SiliconFlow chat 客户端（RSS 翻译兜底/边界评审）：env 未配 API Key 时 yield None。"""
        api_key = self._settings.siliconflow_api_key
        if api_key is None:
            yield None
            return
        async with httpx.AsyncClient(
            base_url=SILICONFLOW_BASE_URL,
            timeout=SILICONFLOW_TIMEOUT,
            trust_env=False,
        ) as http:
            yield SiliconFlowChatClient(
                api_key.get_secret_value(),
                model=self._settings.siliconflow_chat_model,
                http=http,
            )

    async def aclose(self) -> None:
        """关闭长驻 feishu http client（lifespan 清理调用）；幂等。"""
        http, self._feishu_http = self._feishu_http, None
        if http is not None:
            await http.aclose()

    def _http(self) -> httpx.AsyncClient:
        """长驻 feishu http client（懒构造）：统一 timeout=10s、trust_env=False。"""
        if self._feishu_http is None:
            self._feishu_http = httpx.AsyncClient(
                timeout=FEISHU_TIMEOUT,
                trust_env=False,
                transport=self._feishu_transport,
            )
        return self._feishu_http


class FeishuNotifier:
    """飞书应用机器人通知投递：配置与客户端由 ProviderClients seam 提供。

    未配置/禁用时抛 RuntimeError，部分接收人失败抛 FeishuBotApiError——
    由调用方（RSS discovery）捕获并记录 notification_error。
    """

    def __init__(self, clients: ProviderClients) -> None:
        self._clients = clients

    async def send(self, notification: Notification) -> None:
        async with self._clients.feishu_bot() as bot:
            if bot is None:
                raise RuntimeError("飞书应用机器人未启用或凭证不可用")
            lines = [notification.title, f"当前阶段：{notification.stage}", notification.summary]
            lines.extend(f"{label}：{url}" for label, url in notification.links.items())
            markdown = f"**当前阶段**：{notification.stage}\n\n{notification.summary}"
            if notification.links:
                markdown += "\n\n" + "　".join(f"[{label}]({url})" for label, url in notification.links.items())
            await bot.api.send_markdown_to_recipients(
                bot.config.whitelist_open_ids,
                markdown,
                title=notification.title,
                fallback_text="\n".join(lines),
            )
