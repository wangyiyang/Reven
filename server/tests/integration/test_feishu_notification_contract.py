import json

import httpx
import pytest
from reven.integrations.feishu_bot.client import FeishuBotApiError
from reven.integrations.models import Integration
from reven.notifications import ConfiguredFeishuNotifier, Notification
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SECRET_BOX = SecretBox(b"k" * 32)
NOTIFICATION = Notification(
    "Reven RSS 每日汇总",
    "RSS 内容发现",
    "发现了新候选",
    {"打开候选": "https://example.com/rss", "打开后台": "https://example.com/cms"},
)


async def _configure(session: AsyncSession, *, enabled: bool = True, recipients: list[str] | None = None) -> None:
    session.add(
        Integration(
            provider="feishu_bot",
            public_config={
                "enabled": enabled,
                "whitelist_open_ids": ["ou_first", "ou_second"] if recipients is None else recipients,
            },
            encrypted_secret=SECRET_BOX.encrypt({"app_id": "cli_test", "app_secret": "test-secret"}),
        )
    )
    await session.commit()


def _notifier(session: AsyncSession, handler: object) -> ConfiguredFeishuNotifier:
    return ConfiguredFeishuNotifier(
        async_sessionmaker(session.bind, expire_on_commit=False),
        SECRET_BOX,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


@pytest.mark.anyio
async def test_application_only_config_sends_all_notification_content_to_every_recipient(
    db_session: AsyncSession,
) -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/auth/" in request.url.path:
            assert json.loads(request.content) == {"app_id": "cli_test", "app_secret": "test-secret"}
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token"})
        assert request.url.path == "/open-apis/im/v1/messages"
        assert request.headers["Authorization"] == "Bearer token"
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0})

    await _configure(db_session)
    await _notifier(db_session, handler).send(NOTIFICATION)

    assert [payload["receive_id"] for payload in captured] == ["ou_first", "ou_second"]
    for payload in captured:
        assert payload["msg_type"] == "text"
        content = json.loads(str(payload["content"]))["text"]
        assert NOTIFICATION.title in content
        assert NOTIFICATION.stage in content
        assert NOTIFICATION.summary in content
        for label, url in NOTIFICATION.links.items():
            assert f"{label}：{url}" in content


@pytest.mark.anyio
async def test_partial_failure_raises_for_retry_and_attempts_every_recipient(db_session: AsyncSession) -> None:
    recipients: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/auth/" in request.url.path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token"})
        recipient = json.loads(request.content)["receive_id"]
        recipients.append(recipient)
        return httpx.Response(200, json={"code": 230013 if recipient == "ou_first" else 0, "msg": "test-secret token"})

    await _configure(db_session)
    notifier = _notifier(db_session, handler)
    with pytest.raises(FeishuBotApiError, match="已发送 1/2") as caught:
        await notifier.send(NOTIFICATION)

    assert recipients == ["ou_first", "ou_second"]
    assert "test-secret" not in str(caught.value)
    assert "token" not in str(caught.value)


@pytest.mark.anyio
@pytest.mark.parametrize("enabled,recipients", [(False, ["ou_first"]), (True, [])])
async def test_disabled_or_empty_recipients_cannot_report_success(
    db_session: AsyncSession, enabled: bool, recipients: list[str]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid config must not call Feishu")

    await _configure(db_session, enabled=enabled, recipients=recipients)
    with pytest.raises((RuntimeError, FeishuBotApiError)):
        await _notifier(db_session, handler).send(NOTIFICATION)


@pytest.mark.anyio
async def test_legacy_webhook_config_is_never_used(db_session: AsyncSession) -> None:
    db_session.add(
        Integration(
            provider="feishu",
            public_config={"name": "legacy"},
            encrypted_secret=SECRET_BOX.encrypt({"webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/legacy"}),
        )
    )
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("legacy config must never be used")

    with pytest.raises(RuntimeError, match="未启用或凭证不可用"):
        await _notifier(db_session, handler).send(NOTIFICATION)
