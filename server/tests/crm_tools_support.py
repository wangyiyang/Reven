"""CRM MCP 测试共享数据库 fixture 与结果解析。"""

import os
from collections.abc import AsyncIterator
from datetime import date, datetime
from uuid import UUID

import pytest
from reven.agent.tools_crm_customers import CrmCustomerTools
from reven.scheduling import SHANGHAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _today() -> date:
    # 与工具实现同一时钟（上海时区），避免 CI UTC 16:00-24:00 窗口内两侧日期串天
    return datetime.now(SHANGHAI).date()


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set, skipping integration tests")
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE crm_follow_ups, crm_contacts, crm_customers RESTART IDENTITY CASCADE"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _create_customer(tools: CrmCustomerTools, name: str = "示例科技", **overrides: object) -> UUID:
    kwargs: dict[str, object] = {"name": name}
    kwargs.update(overrides)
    result = await tools.create_customer(**kwargs)  # type: ignore[arg-type]
    return _extract_id(result)


def _extract_id(text_result: str) -> UUID:
    marker = "id="
    start = text_result.index(marker) + len(marker)
    end = start
    while end < len(text_result) and text_result[end] in "0123456789abcdef-":
        end += 1
    return UUID(text_result[start:end])
