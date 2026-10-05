import base64
import os
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from reven.app import create_app
from reven.config import Settings
from reven.security.csrf import CsrfOriginMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ORIGIN = "http://dev.wangyiyang.cc:3001"
TEST_ADMIN_PASSWORD = "test-admin-password"


@pytest.fixture
def csrf_client() -> Iterator[TestClient]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    settings = Settings(
        database_url=database_url,
        reven_master_key=base64.urlsafe_b64encode(b"t" * 32).decode(),
        reven_admin_password=TEST_ADMIN_PASSWORD,
        agent_api_key=None,
        _env_file=None,
    )
    engine = create_async_engine(database_url, poolclass=NullPool)
    app = create_app(
        start_background_tasks=False,
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        public_base_url=ORIGIN,
        settings=settings,
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


def test_same_origin_write_with_csrf_header_succeeds(csrf_client: TestClient) -> None:
    response = csrf_client.post("/api/csrf-probe", headers={"Origin": ORIGIN, "X-Reven-CSRF": "1"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_agent_mcp_endpoint_exempt_from_csrf_but_requires_bearer(csrf_client: TestClient) -> None:
    """/agent/mcp 无 Origin/CSRF 头不应被 403 拦截；它由 MCP Bearer token 独立鉴权（401）。"""
    response = csrf_client.post(
        "/agent/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )

    assert response.status_code == 401


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


@pytest.fixture
def https_csrf_client() -> Iterator[TestClient]:
    app = FastAPI()
    app.add_middleware(CsrfOriginMiddleware, public_base_url="https://reven.example")

    @app.post("/write")
    async def write() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("origin", ["https://reven.example", "https://reven.example:443", "HTTPS://REVEN.EXAMPLE"])
def test_https_origin_and_default_port_are_equivalent(https_csrf_client: TestClient, origin: str) -> None:
    response = https_csrf_client.post("/write", headers={"Origin": origin, "X-Reven-CSRF": "1"})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "http://reven.example",
        "https://reven.example:8443",
        "https://reven.example:0",
        "https://reven.example:invalid",
        "https://reven.example:",
        "https://reven.example.evil.example",
        "https://reven.example/path",
        "https://reven.example?",
        "https://reven.example#",
        " https://reven.example",
        "https://rev\ten.example",
        "https://reven.example\n",
        "https://user@reven.example",
        "null",
    ],
)
def test_https_write_rejects_invalid_or_different_origin(https_csrf_client: TestClient, origin: str) -> None:
    response = https_csrf_client.post(
        "/write",
        headers={
            "Origin": origin,
            "X-Reven-CSRF": "1",
            "X-Forwarded-Host": "reven.example",
            "X-Forwarded-Proto": "https",
        },
    )
    assert response.status_code == 403


@pytest.mark.parametrize("headers", [{"Origin": "https://reven.example"}, {"X-Reven-CSRF": "1"}])
def test_https_write_requires_both_csrf_headers(https_csrf_client: TestClient, headers: dict[str, str]) -> None:
    assert https_csrf_client.post("/write", headers=headers).status_code == 403


ALLOWED_ORIGINS = ("https://reven-web-nine.vercel.app", "http://localhost:5173")


@pytest.fixture
def allowlist_csrf_client() -> Iterator[TestClient]:
    app = FastAPI()
    app.add_middleware(
        CsrfOriginMiddleware,
        public_base_url="https://reven.example",
        allowed_origins=ALLOWED_ORIGINS,
    )

    @app.post("/write")
    async def write() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("origin", ["https://reven.example", *ALLOWED_ORIGINS, "HTTPS://REVEN-WEB-NINE.VERCEL.APP"])
def test_allowlisted_origin_write_succeeds(allowlist_csrf_client: TestClient, origin: str) -> None:
    response = allowlist_csrf_client.post("/write", headers={"Origin": origin, "X-Reven-CSRF": "1"})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "https://reven-web-nine.vercel.app.evil.example",
        "https://reven-web-fake.vercel.app",
        "http://localhost:5174",
    ],
)
def test_origin_outside_allowlist_still_rejected(allowlist_csrf_client: TestClient, origin: str) -> None:
    response = allowlist_csrf_client.post("/write", headers={"Origin": origin, "X-Reven-CSRF": "1"})

    assert response.status_code == 403
    assert response.json() == {"code": "csrf_validation_failed", "message": "写请求来源校验失败"}


def test_allowed_origins_fall_back_to_app_state_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产形态：装配时无显式配置，请求时从组合根写入的 app.state.settings 取白名单。"""
    monkeypatch.setenv("REVEN_CSRF_ALLOWED_ORIGINS", "https://reven-web-nine.vercel.app")
    settings = Settings(
        database_url="postgresql+asyncpg://test:test@db/test",
        reven_master_key=base64.urlsafe_b64encode(b"t" * 32).decode(),
        reven_admin_password=TEST_ADMIN_PASSWORD,
        _env_file=None,
    )
    app = FastAPI()
    app.state.settings = settings
    app.add_middleware(CsrfOriginMiddleware)

    @app.post("/write")
    async def write() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        allowed = client.post("/write", headers={"Origin": "https://reven-web-nine.vercel.app", "X-Reven-CSRF": "1"})
        assert allowed.status_code == 200
        rejected = client.post("/write", headers={"Origin": "https://evil.example", "X-Reven-CSRF": "1"})
        assert rejected.status_code == 403
