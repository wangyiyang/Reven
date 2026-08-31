import base64
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from reven.app import create_app
from reven.config import get_settings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ORIGIN = "http://dev.wangyiyang.cc:3001"
TEST_ADMIN_PASSWORD = "test-admin-password"


@pytest.fixture
def csrf_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REVEN_MASTER_KEY", base64.urlsafe_b64encode(b"t" * 32).decode())
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", TEST_ADMIN_PASSWORD)
    get_settings.cache_clear()
    engine = create_async_engine(database_url, poolclass=NullPool)
    app = create_app(
        start_background_tasks=False,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        public_base_url=ORIGIN,
    )

    @app.post("/api/csrf-probe")
    async def csrf_probe() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app, base_url="http://testserver") as client:
        login = client.post(
            "/api/auth/login",
            json={"password": TEST_ADMIN_PASSWORD},
            headers={"Origin": ORIGIN, "X-Reven-CSRF": "1"},
        )
        assert login.status_code == 200
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
        {"Origin": "http://dev.wangyiyang.cc.evil.example", "X-Reven-CSRF": "1"},
        {"Origin": "https://dev.wangyiyang.cc", "X-Reven-CSRF": "1"},
    ],
)
def test_unsafe_requests_fail_closed(csrf_client: TestClient, headers: dict[str, str]) -> None:
    response = csrf_client.post("/api/csrf-probe", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"code": "csrf_validation_failed", "message": "写请求来源校验失败"}


def test_get_does_not_require_csrf_headers(csrf_client: TestClient) -> None:
    assert csrf_client.get("/api/health").status_code == 200


def test_preflight_does_not_enable_cross_origin_access(csrf_client: TestClient) -> None:
    # 浏览器 preflight 不携带 Cookie，会被认证中间件拦截；关键是不返回任何 CORS 放行头
    csrf_client.cookies.clear()
    response = csrf_client.options(
        "/api/csrf-probe",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 401
    assert "access-control-allow-origin" not in response.headers
