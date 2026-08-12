import json

import httpx
import pytest
from reven.integrations.models import Integration
from reven.publishing.factory import ConfiguredFeishuNotifier
from reven.publishing.notifications import Notification
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.anyio
async def test_configured_notifier_loads_encrypted_signing_secret(
    db_session: AsyncSession,
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"code": 0})

    secret_box = SecretBox(b"k" * 32)
    db_session.add(
        Integration(
            provider="feishu",
            public_config={"name": "发布通知"},
            encrypted_secret=secret_box.encrypt(
                {
                    "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
                    "signing_secret": "demo",
                }
            ),
        )
    )
    await db_session.commit()
    notifier = ConfiguredFeishuNotifier(
        async_sessionmaker(db_session.bind, expire_on_commit=False),
        secret_box,
        transport=httpx.MockTransport(handler),
        clock=lambda: 1599360473.9,
    )

    await notifier.send(Notification("Reven 测试", "连接正常", "飞书已连接", {}))

    assert captured["timestamp"] == "1599360473"
    assert captured["sign"] == "l1N0gAcBjdwBvGm1xMjOF0XSyaLRpR7tuO5dHfhAYc8="
