import base64
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from reven.app import create_app
from reven.config import get_settings
from sqlalchemy.ext.asyncio import async_sessionmaker

ORIGIN = "https://dev.wangyiyang.cc"


@pytest.fixture
def csrf_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost/unused")
    monkeypatch.setenv("REVEN_MASTER_KEY", base64.urlsafe_b64encode(b"t" * 32).decode())
    monkeypatch.setenv("REVEN_PUBLIC_BASE_URL", ORIGIN)
    get_settings.cache_clear()
    app = create_app(
        start_background_tasks=False,
        session_factory=async_sessionmaker(),
        public_base_url=ORIGIN,
    )

    @app.post("/api/csrf-probe")
    async def csrf_probe() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def test_same_origin_write_with_csrf_header_succeeds(csrf_client: TestClient) -> None:
    response = csrf_client.post("/api/csrf-probe", headers={"Origin": ORIGIN, "X-Reven-CSRF": "1"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": ORIGIN},
        {"X-Reven-CSRF": "1"},
        {"Origin": "https://evil.example", "X-Reven-CSRF": "1"},
        {"Origin": "null", "X-Reven-CSRF": "1"},
        {"Origin": "https://dev.wangyiyang.cc.evil.example", "X-Reven-CSRF": "1"},
        {"Origin": "http://dev.wangyiyang.cc", "X-Reven-CSRF": "1"},
    ],
)
def test_unsafe_requests_fail_closed(csrf_client: TestClient, headers: dict[str, str]) -> None:
    response = csrf_client.post("/api/csrf-probe", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"code": "csrf_validation_failed", "message": "写请求来源校验失败"}


def test_get_does_not_require_csrf_headers(csrf_client: TestClient) -> None:
    assert csrf_client.get("/api/health").status_code == 200


def test_preflight_does_not_enable_cross_origin_access(csrf_client: TestClient) -> None:
    response = csrf_client.options(
        "/api/csrf-probe",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 405
    assert "access-control-allow-origin" not in response.headers
