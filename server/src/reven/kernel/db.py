"""Database engine and session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from reven.kernel.models.base import Base

__all__ = [
    "Base",
    "engine",
    "async_session_factory",
    "get_session",
]

engine = create_async_engine(
    "postgresql+asyncpg://reven:reven@localhost:5432/reven",
    echo=False,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency — yield an async session."""
    async with async_session_factory() as session:
        yield session
