from datetime import UTC, datetime

from reven.api.routes.system import reset_egress_cache
from reven.system.models import SystemState


class FakeEgress:
    def __init__(self, value: str = "203.0.113.7") -> None:
        self.value = value
        self.calls = 0

    async def fetch(self) -> str:
        self.calls += 1
        return self.value


class BrokenEgress:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch(self) -> str:
        self.calls += 1
        raise TimeoutError


def test_status_returns_database_and_rss_heartbeat(workbench) -> None:  # type: ignore[no-untyped-def]
    client, factory = workbench
    now = datetime.now(tz=UTC).isoformat()
    _run_merge(factory, SystemState(key="rss_discovery", value={"last_heartbeat_at": now}))

    response = client.get("/api/system/status")

    assert response.status_code == 200
    assert response.json()["database"]["available"] is True
    assert set(response.json()) == {"database", "rss_discovery"}
    assert response.json()["rss_discovery"]["last_heartbeat_at"] == now


def test_egress_ip_validates_and_caches_provider_result(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    reset_egress_cache()
    provider = FakeEgress()
    client.app.state.egress_provider = provider

    first = client.get("/api/system/egress-ip")
    second = client.get("/api/system/egress-ip")

    assert first.json() == {"available": True, "ip": "203.0.113.7"}
    assert second.json() == first.json()
    assert provider.calls == 1


def test_egress_failure_never_fabricates_address(workbench) -> None:  # type: ignore[no-untyped-def]
    client, _factory = workbench
    reset_egress_cache()
    provider = BrokenEgress()
    client.app.state.egress_provider = provider

    response = client.get("/api/system/egress-ip")
    cached = client.get("/api/system/egress-ip")

    assert response.status_code == 200
    assert response.json() == {"available": False, "ip": None}
    assert cached.json() == response.json()
    assert provider.calls == 1


def _run_merge(factory, value) -> None:  # type: ignore[no-untyped-def]
    import asyncio

    async def merge() -> None:
        async with factory.begin() as session:
            await session.merge(value)

    asyncio.run(merge())
