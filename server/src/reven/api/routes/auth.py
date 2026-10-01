"""Admin authentication endpoints: login, logout, session probe."""

import hmac
import uuid

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete
from starlette.responses import JSONResponse

from reven.api.dependencies import SessionDep, SettingsDep
from reven.scheduling import utc_now
from reven.security.auth import (
    SESSION_COOKIE,
    SESSION_TTL,
    hash_token,
    issue_token,
    login_throttle,
)
from reven.security.models import AuthSession

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    password: str


def _client_key(request: Request) -> str:
    # 限流 key 只认直连对端地址（部署形态固定 Caddy 前置）：X-Forwarded-For 可由客户端
    # 伪造，取首段作 key 会让爆破者无限换 key 绕过锁定（#176 P0）。
    return request.client.host if request.client is not None else "unknown"


@router.post("/login")
async def login(request: Request, body: LoginBody, session: SessionDep, settings: SettingsDep) -> Response:
    key = _client_key(request)
    if login_throttle.locked(key):
        return JSONResponse(
            status_code=429,
            content={"code": "login_locked", "message": "尝试次数过多，请稍后再试"},
        )
    expected = settings.reven_admin_password.get_secret_value().encode("utf-8")
    if not hmac.compare_digest(body.password.encode("utf-8"), expected):
        login_throttle.record_failure(key)
        return JSONResponse(
            status_code=401,
            content={"code": "invalid_credentials", "message": "密码错误"},
        )
    login_throttle.reset(key)
    token = issue_token()
    now = utc_now()
    session.add(
        AuthSession(
            id=uuid.uuid4(),
            token_hash=hash_token(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + SESSION_TTL,
        )
    )
    await session.commit()
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout", status_code=204)
async def logout(request: Request, session: SessionDep, settings: SettingsDep) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token is not None:
        await session.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        await session.commit()
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=settings.public_base_url.startswith("https://"),
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/me")
async def me() -> dict[str, bool]:
    return {"authenticated": True}
