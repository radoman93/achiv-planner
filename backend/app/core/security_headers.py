"""Security headers + payload size middleware."""

from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


MAX_BODY_BYTES = 1024 * 1024  # 1 MB

# CSP allowances:
#   img-src: own origin + wowhead image CDN + data URIs for base64 icons
#   script-src: 'unsafe-inline' required for Next.js inline scripts (known tradeoff)
DEFAULT_CSP = (
    "default-src 'self'; "
    "img-src 'self' https://wow.zamimg.com data:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)

SECURITY_HEADERS: dict[str, str] = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": DEFAULT_CSP,
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach a fixed set of security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


class PayloadSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds MAX_BODY_BYTES."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "data": None,
                            "error": {
                                "code": "payload_too_large",
                                "message": "Request body exceeds 1MB limit",
                            },
                        },
                    )
            except ValueError:
                pass
        return await call_next(request)
