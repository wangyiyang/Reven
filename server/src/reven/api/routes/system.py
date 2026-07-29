"""Operational status endpoints for the single-server deployment."""

import asyncio
import ipaddress
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

import httpx
from fastapi import APIRouter, Request
from sqlalchemy import text

from reven.api.dependencies import SessionDep
from reven.system.models import SystemState

router = APIRouter(prefix="/api/system", tags=["system"])


class EgressProvider(Protocol):
    async def fetch(self) -> str: ...


class HttpsEgressProvider:
    def __init__(self, url: str = "https://api.ipify.org") -> None:
        if not url.startswith("https://"):
            raise ValueError("出口 IP provider 必须使用 HTTPS")
        self.url = url

    async def fetch(self) -> str:
        timeout = httpx.Timeout(3.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            async with client.stream("GET", self.url) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes(chunk_size=64):
                    size += len(chunk)
                    if size > 64:
                        raise ValueError("出口 IP provider 响应过大")
                    chunks.append(chunk)
        value = b"".join(chunks).decode("ascii").strip()
        return str(ipaddress.ip_address(value))


@dataclass
class _Cache:
    value: str | None = None
    expires_at: float = 0
    lock: asyncio.Lock | None = None


_egress_cache = _Cache()


@router.get("/status")
async def system_status(session: SessionDep) -> dict[str, object]:
    database = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        database = False
    sync = await session.get(SystemState, "notion_sync") if database else None
    scheduler = await session.get(SystemState, "scheduler") if database else None
    return {
        "database": {"available": database},
        "notion_sync": _heartbeat(sync),
        "scheduler": _heartbeat(scheduler),
    }


@router.get("/egress-ip")
async def egress_ip(request: Request) -> dict[str, object]:
    now = monotonic()
    if _egress_cache.expires_at > now:
        return _egress_response(_egress_cache.value)
    lock = _egress_cache.lock
    if lock is None:
        lock = asyncio.Lock()
        _egress_cache.lock = lock
    async with lock:
        if _egress_cache.expires_at > monotonic():
            return _egress_response(_egress_cache.value)
        provider = getattr(request.app.state, "egress_provider", None) or HttpsEgressProvider()
        try:
            value = str(ipaddress.ip_address(await asyncio.wait_for(provider.fetch(), timeout=3)))
        except Exception:
            _egress_cache.value = None
            _egress_cache.expires_at = monotonic() + 15
            return _egress_response(None)
        _egress_cache.value = value
        _egress_cache.expires_at = monotonic() + 60
        return _egress_response(value)


def _heartbeat(state: SystemState | None) -> dict[str, object]:
    if state is None:
        return {"available": False, "last_heartbeat_at": None}
    raw = state.value.get("last_success_at") or state.value.get("last_heartbeat_at")
    return {"available": isinstance(raw, str), "last_heartbeat_at": raw if isinstance(raw, str) else None}


def _egress_response(value: str | None) -> dict[str, object]:
    return {"available": value is not None, "ip": value}


def reset_egress_cache() -> None:
    """Test hook; production never needs to reset this process-local cache."""
    _egress_cache.value = None
    _egress_cache.expires_at = 0
    _egress_cache.lock = None
