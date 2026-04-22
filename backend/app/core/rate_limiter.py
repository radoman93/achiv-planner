"""Rate limiting with slowapi.

Provides:
- `limiter` — the shared `slowapi.Limiter` instance
- `tier_key(request)` — tier-aware key function for per-user/per-tier limits
- `ip_key(request)` — simple per-IP key
- `rate_limit_exceeded_handler` — returns the standard `{data, error}` envelope
  with `error.code=rate_limited` and a 429 status code

Storage backend is Redis (matches the rest of the stack). All limits are
expressed as `slowapi`-compatible strings (e.g., `"100/minute"`).
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings


def ip_key(request: Request) -> str:
    """Per-IP key, used for unauthenticated endpoints."""
    return get_remote_address(request)


def tier_key(request: Request) -> str:
    """Per-user tier-aware key.

    Falls back to the IP when no user is attached (pre-auth). When a user
    is present, the tier is embedded so a single limits rule can differ
    by tier via the custom `cost` function on the decorator.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        return f"anon:{get_remote_address(request)}"
    tier = getattr(user, "tier", "free")
    return f"{tier}:{user.id}"


def character_key(request: Request) -> str:
    """Per-character key (for endpoints scoped by character_id in the path)."""
    character_id = request.path_params.get("character_id")
    if character_id:
        return f"character:{character_id}"
    return tier_key(request)


limiter = Limiter(
    key_func=ip_key,
    storage_uri=settings.REDIS_URL,
    headers_enabled=True,
    strategy="fixed-window",
    default_limits=["300/minute"],
)


def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Return the project's envelope shape for 429s."""
    # slowapi stashes `Retry-After` on the exception's detail; the integer
    # seconds value is most useful to the client.
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is None:
        # Fallback: try to parse from the rate limit description
        try:
            retry_after = int(exc.limit.limit.get_expiry())  # type: ignore[attr-defined]
        except Exception:
            retry_after = 60
    payload: dict[str, Any] = {
        "data": None,
        "error": {
            "code": "rate_limited",
            "message": f"Too many requests. Try again in {retry_after} seconds.",
            "retry_after_seconds": int(retry_after),
        },
    }
    response = JSONResponse(status_code=429, content=payload)
    response.headers["Retry-After"] = str(int(retry_after))
    return response
