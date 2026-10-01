"""ProviderClients seam 测试：per-provider 客户端装配、None 降级约定、长驻 client 生命周期。

凭证解析语义（DB 优先/env 兜底/hint 剥离/解密降级）由 tests/integrations/test_credentials.py 覆盖；
本文件只打 clients 的装配接口：配置 → typed client、超时策略、复用与关闭。
"""

import base64
import json
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
import respx
from pydantic import SecretStr
from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.errors import IntegrationConfigurationError
from reven.integrations.feishu_bot.client import FeishuBotApiError
from reven.integrations.models import Integration
from reven.provider_clients import FeishuReplier, ProviderClients
from reven.rss.ai import SiliconFlowChatClient
from reven.rss.embedding import BGE_M3_MODEL, SiliconFlowEmbeddingClient
from reven.security.secrets import SecretBox
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"t" * 32).decode()
EMBEDDING_RESPONSE = {
    "object": "list",
    "model": BGE_M3_MODEL,
    "data": [{"object": "embedding", "index": 0, "embedding": [0.5] * 1024}],
}


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://unused:unused@127.0.0.1/unused",
        "reven_master_key": TEST_MASTER_KEY,
        "reven_admin_password": "test-admin-password",
        "siliconflow_api_key": None,
        "agent_api_key": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _box() -> SecretBox:
    return SecretBox.from_base64(TEST_MASTER_KEY)


@pytest.fixture
async def make_clients(
    db_session: AsyncSession,
) -> AsyncIterator[Callable[..., ProviderClients]]:
    created: list[ProviderClients] = []

    def _make(
        settings: Settings | None = None, *, feishu_transport: httpx.MockTransport | None = None
    ) -> ProviderClients:
        resolved = settings if settings is not None else _settings()
        factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
        clients = ProviderClients(
            IntegrationCredentials(factory, resolved),
            resolved,
            feishu_transport=feishu_transport,
        )
        created.append(clients)
        return clients

    yield _make
    for clients in created:
        await clients.aclose()


async def _save_feishu_bot(session: AsyncSession, *, app_id: str = "cli_test", enabled: bool = True) -> None:
    session.add(
        Integration(
            provider="feishu_bot",
            public_config={"enabled": enabled, "whitelist_open_ids": ["ou_first"]},
            encrypted_secret=_box().encrypt({"app_id": app_id, "app_secret": "s3cret-bot-value"}),
        )
    )
    await session.commit()


# --- feishu_bot ---


@pytest.mark.anyio
async def test_feishu_bot_unconfigured_yields_none(make_clients: Callable[..., ProviderClients]) -> None:
    clients = make_clients()

    async with clients.feishu_bot() as bot:
        assert bot is None


@pytest.mark.anyio
async def test_feishu_bot_disabled_yields_none(
    db_session: AsyncSession, make_clients: Callable[..., ProviderClients]
) -> None:
    await _save_feishu_bot(db_session, enabled=False)
    clients = make_clients()

    async with clients.feishu_bot() as bot:
        assert bot is None


@pytest.mark.anyio
async def test_feishu_bot_sends_via_shared_http_and_carries_whitelist(
    db_session: AsyncSession, make_clients: Callable[..., ProviderClients]
) -> None:
    await _save_feishu_bot(db_session)
    sent: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/auth/" in request.url.path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token"})
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0})

    clients = make_clients(feishu_transport=httpx.MockTransport(handler))

    async with clients.feishu_bot() as first:
        assert first is not None
        assert first.config.whitelist_open_ids == ("ou_first",)
        await first.api.send_text_to_recipients(first.config.whitelist_open_ids, "第一条")
    async with clients.feishu_bot() as second:
        assert second is not None
        # 长驻 http client 跨调用复用；api 句柄每次新建（凭证每次现读，天然无陈旧缓存）
        assert second.api._http is first.api._http
        await second.api.send_text_to_recipients(second.config.whitelist_open_ids, "第二条")

    assert [json.loads(str(payload["content"]))["text"] for payload in sent] == ["第一条", "第二条"]


@pytest.mark.anyio
async def test_feishu_bot_rereads_config_after_update(
    db_session: AsyncSession, make_clients: Callable[..., ProviderClients]
) -> None:
    await _save_feishu_bot(db_session, app_id="cli_old")
    clients = make_clients()

    async with clients.feishu_bot() as bot:
        assert bot is not None
        assert bot.config.app_id == "cli_old"
    integration = await db_session.scalar(select(Integration).where(Integration.provider == "feishu_bot"))
    assert integration is not None
    integration.encrypted_secret = _box().encrypt({"app_id": "cli_new", "app_secret": "s3cret-bot-value"})
    await db_session.commit()

    async with clients.feishu_bot() as bot:
        assert bot is not None
        assert bot.config.app_id == "cli_new"


@pytest.mark.anyio
async def test_aclose_closes_shared_http_and_is_idempotent(
    db_session: AsyncSession, make_clients: Callable[..., ProviderClients]
) -> None:
    await _save_feishu_bot(db_session)
    clients = make_clients()

    async with clients.feishu_bot() as bot:
        assert bot is not None
    http = clients._feishu_http
    assert http is not None
    assert not http.is_closed

    await clients.aclose()

    assert http.is_closed
    assert clients._feishu_http is None
    await clients.aclose()  # 幂等


@pytest.mark.anyio
async def test_replier_rereads_credentials_reuses_http_and_rejects_disabled_bot(
    db_session: AsyncSession, make_clients: Callable[..., ProviderClients]
) -> None:
    await _save_feishu_bot(db_session, app_id="cli_old")
    app_ids, targets = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/auth/" in request.url.path:
            app_ids.append(json.loads(request.content)["app_id"])
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token"})
        targets.append(request.url.path)
        assert set(json.loads(request.content)) == {"msg_type", "content"}
        return httpx.Response(200, json={"code": 0})

    clients = make_clients(feishu_transport=httpx.MockTransport(handler))
    reply = FeishuReplier(clients)
    await reply("om_first", "第一条")
    shared_http = clients._feishu_http
    integration = await db_session.scalar(select(Integration).where(Integration.provider == "feishu_bot"))
    assert integration is not None
    integration.encrypted_secret = _box().encrypt({"app_id": "cli_new", "app_secret": "updated-secret"})
    await db_session.commit()
    await reply("om_second", "第二条")
    assert clients._feishu_http is shared_http
    assert app_ids == ["cli_old", "cli_new"]
    assert targets == ["/open-apis/im/v1/messages/om_first/reply", "/open-apis/im/v1/messages/om_second/reply"]

    integration.public_config = {"enabled": False, "whitelist_open_ids": ["ou_first"]}
    await db_session.commit()
    with pytest.raises(FeishuBotApiError, match="未启用或凭证不可用"):
        await reply("om_third", "第三条")
    assert len(app_ids) == 2 and len(targets) == 2


# --- embedding ---


@pytest.mark.anyio
async def test_embedding_unconfigured_yields_none(make_clients: Callable[..., ProviderClients]) -> None:
    clients = make_clients()

    async with clients.embedding() as embedder:
        assert embedder is None


@pytest.mark.anyio
@respx.mock
async def test_embedding_env_fallback_uses_default_base_url_and_model(
    make_clients: Callable[..., ProviderClients],
) -> None:
    route = respx.post("https://api.siliconflow.cn/v1/embeddings").mock(
        return_value=httpx.Response(200, json=EMBEDDING_RESPONSE)
    )
    clients = make_clients(_settings(siliconflow_api_key=SecretStr("sk-env")))

    async with clients.embedding() as embedder:
        assert isinstance(embedder, SiliconFlowEmbeddingClient)
        assert embedder.model == BGE_M3_MODEL
        outcome = await embedder.embed(("测试文本",))

    assert outcome.vectors[0] is not None
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-env"


@pytest.mark.anyio
@respx.mock
async def test_embedding_db_config_uses_custom_base_url_and_model(
    db_session: AsyncSession, make_clients: Callable[..., ProviderClients]
) -> None:
    db_session.add(
        Integration(
            provider="embedding",
            public_config={"base_url": "https://embedding.example.com", "model": "custom/model"},
            encrypted_secret=_box().encrypt({"api_key": "sk-db"}),
        )
    )
    await db_session.commit()
    route = respx.post("https://embedding.example.com/v1/embeddings").mock(
        return_value=httpx.Response(200, json=EMBEDDING_RESPONSE)
    )
    clients = make_clients()

    async with clients.embedding() as embedder:
        assert isinstance(embedder, SiliconFlowEmbeddingClient)
        assert embedder.model == "custom/model"
        await embedder.embed(("测试文本",))

    assert route.calls[0].request.headers["authorization"] == "Bearer sk-db"


@pytest.mark.anyio
async def test_embedding_corrupt_secret_raises_domain_error(
    db_session: AsyncSession, make_clients: Callable[..., ProviderClients]
) -> None:
    db_session.add(
        Integration(
            provider="embedding",
            public_config={},
            encrypted_secret="v1:not-a-valid-ciphertext",
        )
    )
    await db_session.commit()
    clients = make_clients()

    with pytest.raises(IntegrationConfigurationError, match="INTEGRATION_SECRET_INVALID"):
        async with clients.embedding():
            pass


# --- siliconflow_chat ---


@pytest.mark.anyio
async def test_siliconflow_chat_without_env_key_yields_none(make_clients: Callable[..., ProviderClients]) -> None:
    clients = make_clients()

    async with clients.siliconflow_chat() as chat:
        assert chat is None


@pytest.mark.anyio
async def test_siliconflow_chat_yields_client_with_settings_model(
    make_clients: Callable[..., ProviderClients],
) -> None:
    clients = make_clients(_settings(siliconflow_api_key=SecretStr("sk-chat"), siliconflow_chat_model="custom/chat"))

    async with clients.siliconflow_chat() as chat:
        assert isinstance(chat, SiliconFlowChatClient)
        assert chat._model == "custom/chat"
