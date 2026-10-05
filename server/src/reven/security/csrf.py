from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from reven.config import Settings
from reven.security.origin import normalize_origin

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class CsrfOriginMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        public_base_url: str | None = None,
        allowed_origins: tuple[str, ...] = (),
        exempt_prefixes: tuple[str, ...] = (),
    ) -> None:
        super().__init__(app)
        self.public_base_url = public_base_url
        self.allowed_origins = allowed_origins
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
        configured = self.public_base_url or _configured_base_url(request)
        allowed_origins = self.allowed_origins or _configured_allowed_origins(request)
        # fail-closed：组合根未提供 settings（无配置降级启动）时写请求来源无法校验，一律拒绝
        if csrf_header != "1" or origin is None or not _origin_allowed(origin, configured, allowed_origins):
            return JSONResponse(
                status_code=403,
                content={"code": "csrf_validation_failed", "message": "写请求来源校验失败"},
            )
        return await call_next(request)


def _configured_base_url(request: Request) -> str | None:
    """装配时未显式传 public_base_url 的生产形态：从组合根写入的 app.state.settings 取。"""
    settings = getattr(request.app.state, "settings", None)
    return settings.public_base_url if isinstance(settings, Settings) else None


def _configured_allowed_origins(request: Request) -> tuple[str, ...]:
    """与 public_base_url 同理：装配时未显式传 allowed_origins 时从 app.state.settings 取。"""
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return tuple(settings.csrf_allowed_origins)
    return ()


def _origin_allowed(origin: str, configured: str | None, allowed_origins: tuple[str, ...]) -> bool:
    if configured is not None and _same_origin(origin, configured):
        return True
    return any(_same_origin(origin, allowed) for allowed in allowed_origins)


def _same_origin(candidate: str, configured: str) -> bool:
    try:
        return normalize_origin(candidate) == normalize_origin(configured)
    except ValueError:
        return False
