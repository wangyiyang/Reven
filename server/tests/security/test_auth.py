import asyncio
import base64
import os
from collections.abc import Iterator
from datetime import timedelta
from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from reven.api.routes.auth import _client_key
from reven.app import create_app
from reven.config import Settings
from reven.scheduling import utc_now
from reven.security.auth import SESSION_COOKIE, LoginThrottle, hash_token, reset_login_throttle
from reven.security.models import AuthSession
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

ORIGIN = "http://dev.wangyiyang.cc:3001"
TEST_ADMIN_PASSWORD = "test-admin-password"


@pytest.fixture(autouse=True)
def _reset_throttle() -> Iterator[None]:
    reset_login_throttle()
    yield
    reset_login_throttle()


@pytest.fixture(params=[ORIGIN, "HTTPS://REVEN.EXAMPLE:443/"], ids=["http", "https"])
def auth_client(request: pytest.FixtureRequest) -> Iterator[tuple[TestClient, async_sessionmaker]]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    settings = Settings(
        database_url=database_url,
        reven_master_key=base64.urlsafe_b64encode(b"t" * 32).decode(),
        reven_admin_password=TEST_ADMIN_PASSWORD,
        public_base_url=request.param,
        agent_api_key=None,
        _env_file=None,
    )
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def reset() -> None:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE auth_sessions RESTART IDENTITY CASCADE"))

    asyncio.run(reset())
    origin = settings.public_base_url
    app = create_app(
        start_background_tasks=False,
        session_factory=factory,
        public_base_url=origin,
        settings=settings,
    )
    with TestClient(app, base_url=origin, headers={"Origin": origin, "X-Reven-CSRF": "1"}) as client:
        yield client, factory
    asyncio.run(engine.dispose())


def _login(client: TestClient, password: str = TEST_ADMIN_PASSWORD):
    return client.post("/api/auth/login", json={"password": password})


def test_health_is_public(auth_client: tuple[TestClient, async_sessionmaker]) -> None:
    client, _ = auth_client
    assert client.get("/api/health").status_code == 200


def test_business_api_requires_session(auth_client: tuple[TestClient, async_sessionmaker]) -> None:
    client, _ = auth_client
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_login_sets_session_cookie_and_unlocks_api(
    auth_client: tuple[TestClient, async_sessionmaker],
) -> None:
    client, _ = auth_client
    response = _login(client)

    assert response.status_code == 200
    morsel = SimpleCookie(response.headers["set-cookie"])[SESSION_COOKIE]
    assert bool(morsel["secure"]) is (client.base_url.scheme == "https")
    assert morsel["httponly"]
    assert morsel["samesite"] == "lax"
    assert morsel["path"] == "/"
    assert not morsel["domain"]
    cookie = client.cookies.get(SESSION_COOKIE)
    assert cookie
    assert client.get("/api/auth/me").status_code == 200


def test_login_rejects_wrong_password(auth_client: tuple[TestClient, async_sessionmaker]) -> None:
    client, _ = auth_client
    response = _login(client, "wrong-password")

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"
    assert client.cookies.get(SESSION_COOKIE) is None


def test_logout_invalidates_session(auth_client: tuple[TestClient, async_sessionmaker]) -> None:
    client, _ = auth_client
    assert _login(client).status_code == 200

    token = client.cookies.get(SESSION_COOKIE)
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    morsel = SimpleCookie(response.headers["set-cookie"])[SESSION_COOKIE]
    assert morsel["max-age"] == "0"
    assert bool(morsel["secure"]) is (client.base_url.scheme == "https")
    assert morsel["httponly"]
    assert morsel["samesite"] == "lax"
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Cookie": f"{SESSION_COOKIE}={token}"}).status_code == 401


def test_active_request_slides_session_expiry(
    auth_client: tuple[TestClient, async_sessionmaker],
) -> None:
    client, factory = auth_client
    assert _login(client).status_code == 200
    token = client.cookies.get(SESSION_COOKIE)
    assert token

    async def read_expiry() -> tuple[object, object]:
        async with factory() as session:
            row = (
                await session.execute(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
            ).scalar_one()
            return row.last_seen_at, row.expires_at

    first_seen, first_expiry = asyncio.run(read_expiry())

    assert client.get("/api/auth/me").status_code == 200
    last_seen, expiry = asyncio.run(read_expiry())

    assert last_seen >= first_seen  # type: ignore[operator]
    assert expiry > first_expiry  # type: ignore[operator]
    assert expiry > utc_now() + timedelta(days=6)  # type: ignore[operator]


def test_login_locks_after_five_failures(auth_client: tuple[TestClient, async_sessionmaker]) -> None:
    client, _ = auth_client
    for _ in range(5):
        assert _login(client, "wrong-password").status_code == 401

    locked = _login(client, "wrong-password")
    assert locked.status_code == 429
    assert locked.json()["code"] == "login_locked"

    # 锁定期间正确密码同样被拒
    assert _login(client).status_code == 429


def test_forged_x_forwarded_for_does_not_bypass_lockout(auth_client: tuple[TestClient, async_sessionmaker]) -> None:
    """#176 P0：每次请求伪造不同 XFF 不再绕过限流——key 只取直连对端地址。"""
    client, _ = auth_client
    for index in range(5):
        response = client.post(
            "/api/auth/login",
            json={"password": "wrong-password"},
            headers={"X-Forwarded-For": f"203.0.113.{index}"},
        )
        assert response.status_code == 401

    locked = client.post(
        "/api/auth/login",
        json={"password": "wrong-password"},
        headers={"X-Forwarded-For": "203.0.113.99"},
    )
    assert locked.status_code == 429
    assert locked.json()["code"] == "login_locked"


def _probe_request(xff: str | None, client_host: str | None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/login",
            "headers": headers,
            "client": (client_host, 50000) if client_host is not None else None,
        }
    )


def test_client_key_ignores_x_forwarded_for() -> None:
    """#176 P0：限流 key 只认 request.client.host，XFF（含多段链路伪造）一律不参与。"""
    request = _probe_request("198.51.100.7, 10.0.0.1", "172.16.0.2")
    assert _client_key(request) == "172.16.0.2"
    assert _client_key(_probe_request(None, "172.16.0.2")) == "172.16.0.2"
    assert _client_key(_probe_request("198.51.100.7", None)) == "unknown"


def test_login_throttle_bounds_tracked_keys() -> None:
    """#176 P0：轮换来源 key 时计数字典容量有界，不会无界增长（内存 DoS 防呆）。"""
    throttle = LoginThrottle(max_attempts=5, lock_seconds=900, max_keys=3)
    for index in range(20):
        throttle.record_failure(f"10.0.0.{index}")

    assert len(throttle._failures) <= 3
    assert len(throttle._failures) + len(throttle._locked_until) <= 3


def test_login_throttle_reclaims_expired_locks_before_evicting() -> None:
    """#176 P0：容量满时优先回收已过期的锁定项，未过期锁定不受新 key 挤占。"""
    throttle = LoginThrottle(max_attempts=1, lock_seconds=60, max_keys=2)
    throttle.record_failure("10.0.0.1")  # 立即锁定
    assert throttle.locked("10.0.0.1")

    # 手工造一个已过期锁定，再让字典满员：过期项被回收，未过期的 10.0.0.1 锁定保留
    throttle._locked_until["10.0.0.2"] = 0.0
    throttle.record_failure("10.0.0.3")

    assert "10.0.0.2" not in throttle._locked_until
    assert throttle.locked("10.0.0.1")


def test_settings_require_admin_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@db/test")
    monkeypatch.setenv("REVEN_MASTER_KEY", "test-master-key")
    monkeypatch.delenv("REVEN_ADMIN_PASSWORD", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_cookie_security_uses_configured_origin_behind_proxy(
    auth_client: tuple[TestClient, async_sessionmaker],
) -> None:
    client, _ = auth_client
    expected_secure = client.base_url.scheme == "https"
    response = client.post(
        "http://reven:8000/api/auth/login",
        json={"password": TEST_ADMIN_PASSWORD},
        headers={"X-Forwarded-Proto": "https" if not expected_secure else "http"},
    )
    assert response.status_code == 200
    assert bool(SimpleCookie(response.headers["set-cookie"])[SESSION_COOKIE]["secure"]) is expected_secure
