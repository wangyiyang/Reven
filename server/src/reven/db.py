"""Async database engine and session helpers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from reven.config import Settings


class Base(DeclarativeBase):
    pass


def create_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        # 远端库单语句 RTT ~430ms（Supabase 新加坡节点）：pre_ping 每个请求白付一整次
        # 往返，改用 pool_recycle 在取用前回收超龄连接，避免使用已被对端关闭的连接。
        pool_recycle=180,
        pool_size=5,
    )
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a session; the caller is responsible for commit/rollback."""
    async with session_factory() as session:
        yield session
