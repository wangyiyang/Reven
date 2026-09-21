import asyncio
import base64
import os
from collections.abc import Iterator
from datetime import timedelta
from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from reven.app import create_app
from reven.config import Settings, get_settings
from reven.scheduling import utc_now
from reven.security.auth import SESSION_COOKIE, hash_token, reset_login_throttle
from reven.security.models import AuthSession
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ORIGIN = "http://dev.wangyiyang.cc:3001"
TEST_ADMIN_PASSWORD = "test-admin-password"


@pytest.fixture(autouse=True)
def _reset_throttle() -> Iterator[None]:
    reset_login_throttle()
    yield
    reset_login_throttle()


@pytest.fixture(params=[ORIGIN, "HTTPS://REVEN.EXAMPLE:443/"], ids=["http", "https"])
def auth_client(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[tuple[TestClient, async_sessionmaker]]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REVEN_MASTER_KEY", base64.urlsafe_b64encode(b"t" * 32).decode())
    monkeypatch.setenv("REVEN_ADMIN_PASSWORD", TEST_ADMIN_PASSWORD)
    monkeypatch.setenv("REVEN_PUBLIC_BASE_URL", request.param)
    get_settings.cache_clear()
    engine = create_async_engine(database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def reset() -> None:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE auth_sessions RESTART IDENTITY CASCADE"))

    asyncio.run(reset())
    origin = get_settings().public_base_url
    app = create_app(
        start_background_tasks=False,
        session_factory=factory,
        public_base_url=origin,
    )
    with TestClient(app, base_url=origin, headers={"Origin": origin, "X-Reven-CSRF": "1"}) as client:
        yield client, factory
    asyncio.run(engine.dispose())
    get_settings.cache_clear()


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
