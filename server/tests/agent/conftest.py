from collections.abc import AsyncIterator

import pytest
from agent_service_support import ServiceRig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def rig(db_session: AsyncSession) -> AsyncIterator[ServiceRig]:
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    candidate = ServiceRig(factory)
    try:
        yield candidate
    finally:
        await candidate.close()
