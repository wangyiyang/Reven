from fastapi.testclient import TestClient
from reven.app import create_app


def test_health_returns_service_status() -> None:
    with TestClient(create_app(start_background_tasks=False)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"service": "reven", "status": "ok"}
