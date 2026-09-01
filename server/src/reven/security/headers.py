"""安全响应头中间件：登录页与 API 统一加固（#75）。

刻意保持基线可运行：
- CSP 允许 style 'unsafe-inline'（Tailwind/shadcn 内联样式），脚本仅 'self'
- X-Frame-Options 用 SAMEORIGIN 而非 DENY（详情页微信预览是同源 srcdoc iframe）
"""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

_HEADERS: dict[str, str] = {
    "content-security-policy": _CONTENT_SECURITY_POLICY,
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-content-type-options": "nosniff",
    "x-frame-options": "SAMEORIGIN",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for name, value in _HEADERS.items():
            response.headers.setdefault(name, value)
        return response
