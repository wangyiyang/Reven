from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from reven.config import get_settings

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class CsrfOriginMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        public_base_url: str | None = None,
        exempt_prefixes: tuple[str, ...] = (),
    ) -> None:
        super().__init__(app)
        self.public_base_url = public_base_url
        self.exempt_prefixes = exempt_prefixes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in UNSAFE_METHODS:
            return await call_next(request)
        # 豁免 Bearer token 鉴权的机器端点（agent MCP loopback）：浏览器跨站请求无法
        # 携带 Authorization 头，CSRF 威胁模型不适用；该路径仍有独立 token 校验兜底
        if any(request.url.path.startswith(prefix) for prefix in self.exempt_prefixes):
            return await call_next(request)
        origin = request.headers.get("origin")
        csrf_header = request.headers.get("x-reven-csrf")
        configured = self.public_base_url or get_settings().public_base_url
        if csrf_header != "1" or origin is None or not _same_origin(origin, configured):
            return JSONResponse(
                status_code=403,
                content={"code": "csrf_validation_failed", "message": "写请求来源校验失败"},
            )
        return await call_next(request)


def _same_origin(candidate: str, configured: str) -> bool:
    try:
        return _origin(candidate) == _origin(configured)
    except ValueError:
        return False


def _origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("invalid origin")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("invalid origin")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("invalid origin")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, parsed.hostname.lower(), port
