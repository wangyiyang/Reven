from fastapi.testclient import TestClient
from reven.app import create_app


class FakeRunner:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1


def test_health_returns_service_status() -> None:
    with TestClient(create_app(start_background_tasks=False)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"service": "reven", "status": "ok"}


def test_lifespan_starts_and_stops_injected_runner() -> None:
    runner = FakeRunner()

    with TestClient(create_app(runner=runner)):
        assert runner.started == 1

    assert runner.stopped == 1
