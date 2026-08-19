import base64
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from reven.config import get_settings
from reven.domain import JobStatus, TargetChannel
from reven.integrations.models import Integration
from reven.jobs.errors import BlockedPublishError, TransientPublishError
from reven.publishing.factory import ConfiguredNotionDeliveryWriter
from reven.publishing.orchestrator import DeliveryRecord
from reven.security.secrets import SecretBox
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    yield
    get_settings.cache_clear()


def _record() -> DeliveryRecord:
    return DeliveryRecord(
        uuid4(),
        uuid4(),
        "page-contract",
        "https://notion.so/page",
        "https://reven/articles/1",
        "标题",
        (TargetChannel.BLOG,),
        False,
        {TargetChannel.BLOG: "已上线"},
        {TargetChannel.BLOG: {"article_url": "https://blog.example/post"}},
        None,
        "",
        False,
        False,
        Path("/tmp/jobs"),
        Path("/tmp/jobs/one"),
    )


async def _configured_writer(db_session: AsyncSession, monkeypatch, handler) -> ConfiguredNotionDeliveryWriter:
    key = base64.urlsafe_b64encode(b"k" * 32).decode()
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://unused")
    monkeypatch.setenv("REVEN_MASTER_KEY", key)
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")
    get_settings.cache_clear()
    db_session.add(
        Integration(
            provider="notion",
            public_config={"data_source_id": "source-contract"},
            encrypted_secret=SecretBox.from_base64(key).encrypt({"token": "notion-contract-token"}),
        )
    )
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    return ConfiguredNotionDeliveryWriter(factory, transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_real_notion_writer_loads_secret_and_sends_delivery_contract(db_session, monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": "page-contract"})

    writer = await _configured_writer(db_session, monkeypatch, handler)
    await writer.write(_record(), JobStatus.COMPLETED, "")

    assert requests[0].url == httpx.URL("https://api.notion.com/v1/pages/page-contract")
    assert requests[0].headers["authorization"] == "Bearer notion-contract-token"
    payload = __import__("json").loads(requests[0].content)
    properties = payload["properties"]
    assert properties["状态"]["status"]["name"] == "已交付"
    assert properties["自动化状态"]["select"]["name"] == "已完成"
    assert properties["失败原因"]["rich_text"] == []
    assert properties["链接"]["url"] == "https://blog.example/post"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(500, TransientPublishError), (401, BlockedPublishError)],
)
async def test_real_notion_writer_classifies_errors_and_recovers(
    db_session, monkeypatch, status_code: int, expected: type[Exception]
) -> None:
    responses = iter((status_code, 200))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(responses), json={"message": "contract"})

    writer = await _configured_writer(db_session, monkeypatch, handler)
    with pytest.raises(expected):
        await writer.write(_record(), JobStatus.BLOCKED, "缺少封面")
    await writer.write(_record(), JobStatus.COMPLETED, "")
