"""独立 psycopg 检查点池和显式部署初始化命令。"""

import asyncio
import logging
import os
import sys
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg import AsyncConnection, sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url

from reven.agent.errors import AgentRuntimeError

logger = logging.getLogger(__name__)
CHECKPOINT_SCHEMA = "reven_agent_checkpoints"
_CONNECTION_QUERY_KEYS = frozenset(
    {"sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout", "application_name", "client_encoding"}
)
_CONNECTION_OPTIONS: dict[str, Any] = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,
    "options": f"-c search_path={CHECKPOINT_SCHEMA}",
}


def postgres_conninfo(database_url: str) -> str:
    """解析 SQLAlchemy URL，显式映射 asyncpg 的 SSL 参数。"""
    try:
        url = make_url(database_url)
        if url.drivername not in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}:
            raise ValueError("不支持的数据库驱动")
        query: dict[str, str] = {}
        for key, value in url.query.items():
            if not isinstance(value, str):
                raise ValueError("重复的数据库连接参数")
            query[key] = value
        ssl = query.pop("ssl", None)
        if ssl is not None:
            if "sslmode" in query or not isinstance(ssl, str):
                raise ValueError("SSL 参数冲突")
            query["sslmode"] = {"true": "require", "false": "disable"}.get(ssl.lower(), ssl)
        if set(query) - _CONNECTION_QUERY_KEYS:
            raise ValueError("不支持的数据库连接参数")
        values: dict[str, str | int | None] = {
            "host": url.host,
            "port": url.port,
            "dbname": url.database,
            "user": url.username,
            "password": url.password,
        }
        return make_conninfo("", **{key: value for key, value in {**values, **query}.items() if value is not None})
    except Exception:
        raise ValueError("Agent 检查点数据库 URL 或参数无效") from None


def _serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=None)


async def initialize_checkpoint_schema(database_url: str) -> None:
    async with await AsyncConnection.connect(postgres_conninfo(database_url), **_CONNECTION_OPTIONS) as connection:
        await connection.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(CHECKPOINT_SCHEMA)))
        await AsyncPostgresSaver(connection, serde=_serializer()).setup()


class AgentCheckpoints:
    def __init__(self, database_url: str) -> None:
        self._conninfo = postgres_conninfo(database_url)
        self._pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]] | None = None
        self._saver: AsyncPostgresSaver | None = None

    @property
    def saver(self) -> AsyncPostgresSaver:
        if self._saver is None:
            raise AgentRuntimeError("AGENT_RUNTIME_UNAVAILABLE", "Agent 检查点尚未就绪")
        return self._saver

    async def open(self) -> None:
        if self._pool is not None:
            return
        self._pool = AsyncConnectionPool(self._conninfo, min_size=1, max_size=5, open=False, kwargs=_CONNECTION_OPTIONS)
        try:
            await self._pool.open()
            await self._pool.wait(timeout=10)
            if not await self.ready():
                raise AgentRuntimeError("AGENT_RUNTIME_UNAVAILABLE", "Agent 检查点未初始化或版本不兼容")
            self._saver = AsyncPostgresSaver(self._pool, serde=_serializer())
        except Exception:
            await self.close()
            raise AgentRuntimeError("AGENT_RUNTIME_UNAVAILABLE", "Agent 检查点连接或初始化失败") from None

    async def ready(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.connection(timeout=5) as connection:
                result = await connection.execute("SELECT max(v) AS version FROM checkpoint_migrations")
                row = await result.fetchone()
                return row is not None and row["version"] == len(AsyncPostgresSaver.MIGRATIONS) - 1
        except Exception as error:
            logger.warning("Agent 检查点检查失败（error_type=%s）", type(error).__name__)
            return False

    async def close(self) -> None:
        self._saver = None
        pool, self._pool = self._pool, None
        if pool is not None:
            await pool.close()


def main() -> None:
    try:
        asyncio.run(initialize_checkpoint_schema(os.environ["DATABASE_URL"]))
    except Exception as error:
        print(f"Agent 检查点初始化失败（error_type={type(error).__name__}）", file=sys.stderr)
        raise SystemExit(1) from None
    print("Agent 检查点已初始化")


if __name__ == "__main__":
    main()
