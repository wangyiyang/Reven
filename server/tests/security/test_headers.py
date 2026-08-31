"""安全响应头中间件测试（#75）。"""

import base64
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from reven.app import create_app
from reven.config import get_settings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ORIGIN = "http://dev.wangyiyang.cc"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REVEN_MASTER_KEY", base64.urlsafe_b64encode(b"t" * 32).decode())
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", "test-admin-password")
    get_settings.cache_clear()
    engine = create_async_engine(database_url, poolclass=NullPool)
    app = create_app(
        start_background_tasks=False,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        public_base_url=ORIGIN,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_anonymous_api_response_carries_security_headers(client: TestClient) -> None:
    response = client.get("/api/system/status")

    assert response.status_code == 401  # 未登录被拒，但安全头仍应齐全
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "strict-transport-security" not in response.headers
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'self'" in csp


def test_auth_endpoint_response_carries_security_headers(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        headers={"Origin": ORIGIN, "X-Reven-CSRF": "1"},
        json={"password": "wrong"},
    )

    assert response.status_code in (401, 429)
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]
