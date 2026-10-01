"""主动推送投递层：chat_id 定向优先、白名单兜底、配置缺失显式报错。"""

import base64
import json

import httpx
import pytest
from reven.config import Settings
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.models import Integration
from reven.notify.notifier import FeishuProactiveNotifier, PushTargetMissingError
from reven.provider_clients import ProviderClients
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_MASTER_KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
SECRET_BOX = SecretBox(b"k" * 32)


async def configure_bot(session: AsyncSession, *, enabled: bool = True, whitelist: list[str] | None = None) -> None:
    session.add(
        Integration(
            provider="feishu_bot",
            public_config={
                "enabled": enabled,
                "whitelist_open_ids": ["ou_a", "ou_b"] if whitelist is None else whitelist,
            },
            encrypted_secret=SECRET_BOX.encrypt({"app_id": "cli_test", "app_secret": "test-secret"}),
        )
    )
    await session.commit()


def build_notifier(session: AsyncSession, handler: object) -> FeishuProactiveNotifier:
    settings = Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1/unused",
        reven_master_key=TEST_MASTER_KEY,
        reven_admin_password="test-admin-password",
    )
    credentials = IntegrationCredentials(async_sessionmaker(session.bind, expire_on_commit=False), settings)
    clients = ProviderClients(
        credentials,
        settings,
        feishu_transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )
    return FeishuProactiveNotifier(clients)


def token_then_messages(captured: list[dict[str, object]], *, fail_chat: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        if "/auth/" in request.url.path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token"})
        payload = json.loads(request.content)
        payload["receive_id_type"] = request.url.params["receive_id_type"]
        captured.append(payload)
        if fail_chat and payload["receive_id_type"] == "chat_id":
            return httpx.Response(200, json={"code": 230002, "msg": "bot is not in the chat"})
        return httpx.Response(200, json={"code": 0})

    return handler


@pytest.mark.anyio
async def test_chat_id_is_the_primary_channel(db_session: AsyncSession) -> None:
    captured: list[dict[str, object]] = []
    await configure_bot(db_session)

    channel = await build_notifier(db_session, token_then_messages(captured)).send_markdown(
        chat_id="oc_group", title="CRM 待跟进提醒", markdown="正文", fallback_text="正文"
    )

    assert channel == "chat"
    assert len(captured) == 1
    assert captured[0]["receive_id_type"] == "chat_id"
    assert captured[0]["receive_id"] == "oc_group"
    assert captured[0]["msg_type"] == "interactive"


@pytest.mark.anyio
async def test_chat_failure_falls_back_to_whitelist(db_session: AsyncSession) -> None:
    captured: list[dict[str, object]] = []
    await configure_bot(db_session)

    channel = await build_notifier(db_session, token_then_messages(captured, fail_chat=True)).send_markdown(
        chat_id="oc_group", title="CRM 待跟进提醒", markdown="正文", fallback_text="正文"
    )

    assert channel == "whitelist"
    # 卡片 + 纯文本降级各试一次 chat，随后广播两位白名单接收人
    assert [payload["receive_id_type"] for payload in captured] == ["chat_id", "chat_id", "open_id", "open_id"]
    assert [payload["receive_id"] for payload in captured[2:]] == ["ou_a", "ou_b"]


@pytest.mark.anyio
async def test_chat_failure_log_contains_only_error_type_and_code(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """#176 P2：降级日志只记异常类型与稳定平台码，异常原文不进日志（文件头脱敏纪律）。"""
    captured: list[dict[str, object]] = []
    await configure_bot(db_session)

    with caplog.at_level("WARNING", logger="reven.notify.notifier"):
        channel = await build_notifier(db_session, token_then_messages(captured, fail_chat=True)).send_markdown(
            chat_id="oc_group", title="标题", markdown="正文", fallback_text="正文"
        )

    assert channel == "whitelist"
    warning = next(record for record in caplog.records if "降级白名单" in record.getMessage())
    message = warning.getMessage()
    assert "FeishuBotApiError" in message
    assert "230002" in message
    assert "飞书消息发送失败" not in message  # 异常原文（含固定提示）不进日志


@pytest.mark.anyio
async def test_whitelist_is_used_when_chat_id_missing(db_session: AsyncSession) -> None:
    captured: list[dict[str, object]] = []
    await configure_bot(db_session)

    channel = await build_notifier(db_session, token_then_messages(captured)).send_markdown(
        chat_id=None, title="标题", markdown="正文", fallback_text="正文"
    )

    assert channel == "whitelist"
    assert [payload["receive_id"] for payload in captured] == ["ou_a", "ou_b"]


@pytest.mark.anyio
async def test_missing_any_target_raises(db_session: AsyncSession) -> None:
    await configure_bot(db_session, whitelist=[])

    with pytest.raises(PushTargetMissingError):
        await build_notifier(db_session, token_then_messages([])).send_markdown(
            chat_id=None, title="标题", markdown="正文", fallback_text="正文"
        )


@pytest.mark.anyio
async def test_unconfigured_bot_raises_target_missing(db_session: AsyncSession) -> None:
    with pytest.raises(PushTargetMissingError):
        await build_notifier(db_session, token_then_messages([])).send_markdown(
            chat_id="oc_group", title="标题", markdown="正文", fallback_text="正文"
        )
