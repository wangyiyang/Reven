"""Admin session authentication: cookie middleware, token helpers, login throttle."""

import hashlib
import secrets
from datetime import timedelta
from time import monotonic

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from reven.scheduling import utc_now
from reven.security.models import AuthSession

SESSION_COOKIE = "reven_session"
SESSION_TTL = timedelta(days=7)
# 滑动续期节流（#177）：仅距过期不足一半 TTL 才顺延写库；
# last_seen_at 距上次回写超过该阈值才更新——绝大多数请求只读不写，
# 远端库 RTT（~430ms/写）不再每请求白付，同 cookie 并发也不再因 UPDATE 互锁。
SESSION_REFRESH_REMAINING = SESSION_TTL / 2
LAST_SEEN_UPDATE_INTERVAL = timedelta(hours=1)
PUBLIC_PATHS = {"/api/health", "/api/auth/login"}


def issue_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"code": "unauthorized", "message": "未登录或会话已过期"},
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """Fail-closed session guard: everything except PUBLIC_PATHS requires a valid session."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Caddy 只把 /api/* 反代到本服务，其余路径走静态文件；fail-closed 只守 API 面
        path = request.url.path
        if not path.startswith("/api/") or path in PUBLIC_PATHS:
            return await call_next(request)
        factory = getattr(request.app.state, "session_factory", None)
        token = request.cookies.get(SESSION_COOKIE)
        if not isinstance(factory, async_sessionmaker) or token is None:
            return _unauthorized()
        async with factory() as session:
            row = await session.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
            now = utc_now()
            if row is None:
                return _unauthorized()
            if row.expires_at <= now:
                await session.delete(row)
                await session.commit()
                return _unauthorized()
            # 滑动续期节流（#177）：距过期不足一半 TTL 才顺延；last_seen 超阈值才回写
            refresh_expiry = row.expires_at - now < SESSION_REFRESH_REMAINING
            refresh_seen = now - row.last_seen_at >= LAST_SEEN_UPDATE_INTERVAL
            if refresh_expiry or refresh_seen:
                if refresh_expiry:
                    row.expires_at = now + SESSION_TTL
                row.last_seen_at = now
                await session.commit()
        request.state.authenticated_owner_id = "admin"
        return await call_next(request)


class LoginThrottle:
    """In-memory per-IP login failure counter: 5 failures lock the IP for 15 minutes.

    字典容量有界（max_keys）：新 key 入库前若已满，先清理已过期锁定项，仍满则按插入
    顺序逐出最旧项——防止伪造/轮换来源 key 使 _failures/_locked_until 无界增长（内存 DoS）。
    """

    def __init__(self, *, max_attempts: int = 5, lock_seconds: float = 900, max_keys: int = 10_000) -> None:
        self.max_attempts = max_attempts
        self.lock_seconds = lock_seconds
        self.max_keys = max_keys
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def locked(self, key: str) -> bool:
        until = self._locked_until.get(key)
        if until is None:
            return False
        if monotonic() < until:
            return True
        del self._locked_until[key]
        self._failures.pop(key, None)
        return False

    def record_failure(self, key: str) -> None:
        if key not in self._failures and key not in self._locked_until:
            self._evict_overflow()
        failures = self._failures.get(key, 0) + 1
        self._failures[key] = failures
        if failures >= self.max_attempts:
            self._locked_until[key] = monotonic() + self.lock_seconds
            self._failures.pop(key, None)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)

    def _evict_overflow(self) -> None:
        if len(self._failures) + len(self._locked_until) < self.max_keys:
            return
        now = monotonic()
        for locked_key in [key for key, until in self._locked_until.items() if until <= now]:
            del self._locked_until[locked_key]
        while len(self._failures) + len(self._locked_until) >= self.max_keys:
            if self._failures:
                self._failures.pop(next(iter(self._failures)))
            else:
                self._locked_until.pop(next(iter(self._locked_until)))


login_throttle = LoginThrottle()


def reset_login_throttle() -> None:
    """Test hook; production never needs to reset this process-local state."""
    login_throttle._failures.clear()
    login_throttle._locked_until.clear()
