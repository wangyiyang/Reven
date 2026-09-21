"""每个迁移用例使用独立空库，避免跨越不可逆迁移或污染业务测试。"""

import asyncio
import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


async def _database(database_url: str, name: str, *, create: bool) -> None:
    engine = create_async_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            statement = f'CREATE DATABASE "{name}"' if create else f'DROP DATABASE "{name}" WITH (FORCE)'
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def isolated_migration_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        yield
        return
    name = f"reven_migration_{uuid4().hex}"
    asyncio.run(_database(database_url, name, create=True))
    isolated_url = make_url(database_url).set(database=name).render_as_string(hide_password=False)
    monkeypatch.setenv("TEST_DATABASE_URL", isolated_url)
    monkeypatch.setenv("DATABASE_URL", isolated_url)
    try:
        yield
    finally:
        asyncio.run(_database(database_url, name, create=False))
