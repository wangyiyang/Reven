import os
from collections.abc import AsyncIterator

import pytest
from ci_gate import is_test_database_missing_in_ci
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def require_database_url_in_ci() -> None:
    if is_test_database_missing_in_ci(os.environ):
        raise pytest.UsageError("CI 必须配置 TEST_DATABASE_URL，禁止静默跳过数据库测试")


def pytest_sessionstart(session: pytest.Session) -> None:
    del session
    require_database_url_in_ci()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if "TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TEST_DATABASE_URL is not set, skipping integration tests")
    database_url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE rss_items, rss_discovery_runs, rss_keywords, rss_sources, "
                "crm_follow_ups, crm_contacts, crm_customers, "
                "talent_experiences, talent_educations, talent_interactions, talents, "
                "finance_entries, projects, sops, notification_logs, "
                "brand_versions, channel_template_versions, brand_assets, "
                "agent_operations, agent_approvals, agent_runs, agent_sessions, agent_config_revisions, "
                "integrations, auth_sessions, "
                "system_state RESTART IDENTITY CASCADE"
            )
        )
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()
