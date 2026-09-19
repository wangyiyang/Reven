import json
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from ci_gate import is_test_database_missing_in_ci
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def require_database_url_in_ci() -> None:
    if is_test_database_missing_in_ci(os.environ):
        raise pytest.UsageError("CI 必须配置 TEST_DATABASE_URL，禁止静默跳过数据库测试")


def pytest_sessionstart(session: pytest.Session) -> None:
    del session
    require_database_url_in_ci()


@pytest.fixture(autouse=True)
def _scrub_agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离开发者 shell 残留的 AGENT_*/DSH_HOME env。

    app lifespan 会直接读进程 env 构造 AgentConfig；残留 AGENT_API_KEY 会让
    无关 API 测试拉起真实 dsh 子进程，启动失败时级联导致整批用例 ERROR。
    """
    for var in (
        "AGENT_API_KEY",
        "AGENT_PROVIDER",
        "AGENT_MODEL",
        "AGENT_BASE_URL",
        "AGENT_MCP_TOKEN",
        "AGENT_MCP_URL",
        "DSH_HOME",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def load_fixture() -> Callable[[str], Any]:
    """读取 server/tests/fixtures 下的 JSON 固定样例并返回解析结果。"""

    def _load(relative_path: str) -> Any:
        return json.loads((FIXTURES_DIR / relative_path).read_text(encoding="utf-8"))

    return _load


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
                "TRUNCATE rss_items, rss_discovery_runs, rss_keywords, rss_sources, publication_jobs, articles, "
                "crm_follow_ups, crm_contacts, crm_customers, talent_interactions, talents, "
                "finance_entries, projects, sops, "
                "brand_versions, channel_template_versions, brand_assets, brand_import_runs, "
                "integrations, auth_sessions, "
                "system_state RESTART IDENTITY CASCADE"
            )
        )
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()
