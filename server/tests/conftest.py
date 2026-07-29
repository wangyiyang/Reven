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
            text("TRUNCATE publication_jobs, articles, integrations, system_state RESTART IDENTITY CASCADE")
        )
    async with session_factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()
