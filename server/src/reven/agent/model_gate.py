"""单 worker 的模型更新短窗口；不持锁等待模型或业务工具。"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from weakref import WeakKeyDictionary

_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = WeakKeyDictionary()


@asynccontextmanager
async def model_update_guard() -> AsyncIterator[None]:
    loop = asyncio.get_running_loop()
    lock = _locks.setdefault(loop, asyncio.Lock())
    async with lock:
        yield
