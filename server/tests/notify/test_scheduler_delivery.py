"""真实 CRM 提醒经调度器与飞书 adapter 交付，卡片降级保留完整内容。"""

import base64
import json
from datetime import date, datetime, time

import httpx
import pytest
from reven.config import Settings
from reven.crm.follow_up_reminder import CrmFollowUpReminder
from reven.crm.models import Customer, FollowUp
from reven.integrations.credentials import IntegrationCredentials
from reven.integrations.models import Integration
from reven.notify.notifier import FeishuProactiveNotifier
from reven.notify.scheduler import DailyPushConfig, DailyPushScheduler
from reven.provider_clients import ProviderClients
from reven.scheduling import SHANGHAI
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def _configured_clients(session: AsyncSession, transport: httpx.MockTransport) -> ProviderClients:
    key = base64.urlsafe_b64encode(b"n" * 32).decode()
    session.add(
        Integration(
            provider="feishu_bot",
            public_config={"enabled": True, "whitelist_open_ids": ["ou_owner"]},
            encrypted_secret=SecretBox.from_base64(key).encrypt({"app_id": "cli_test", "app_secret": "test-secret"}),
        )
    )
    await session.commit()
    settings = Settings(
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1/unused",
        reven_master_key=key,
        reven_admin_password="test-admin-password",
        _env_file=None,
    )
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    return ProviderClients(IntegrationCredentials(factory, settings), settings, feishu_transport=transport)


@pytest.mark.anyio
async def test_crm_reminder_text_fallback_contains_title_customer_action_and_due(db_session: AsyncSession) -> None:
    today = date(2026, 10, 1)
    customer = Customer(name="待跟进客户")
    db_session.add(customer)
    await db_session.flush()
    db_session.add(
        FollowUp(
            customer_id=customer.id,
            kind="电话",
            occurred_on=today,
            summary="回访沟通",
            next_action="确认报价",
            next_due_on=today,
        )
    )
    await db_session.commit()
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/auth/" in request.url.path:
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "token"})
        payload = json.loads(request.content)
        captured.append(payload)
        assert request.url.params["receive_id_type"] == "chat_id"
        assert payload["receive_id"] == "oc_target"
        return httpx.Response(200, json={"code": 230027 if payload["msg_type"] == "interactive" else 0})

    clients = await _configured_clients(db_session, httpx.MockTransport(handler))
    scheduler = DailyPushScheduler(
        async_sessionmaker(db_session.bind, expire_on_commit=False),
        FeishuProactiveNotifier(clients),
        (CrmFollowUpReminder(),),
        DailyPushConfig(enabled=True, run_at=time(9), chat_id="oc_target", heartbeat=False),
        clock=lambda: datetime.combine(today, time(10), tzinfo=SHANGHAI),
    )
    try:
        await scheduler.tick()
    finally:
        await clients.aclose()

    assert [item["msg_type"] for item in captured] == ["interactive", "text"]
    text = json.loads(captured[1]["content"])["text"]
    assert text.startswith("CRM 待跟进提醒\n")
    for content in ("待跟进客户", "确认报价", "今日到期", "10月1日"):
        assert content in text
