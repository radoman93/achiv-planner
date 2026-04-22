"""Sentry initialisation and PII scrubbing."""

from __future__ import annotations

import re
from typing import Any

from app.core.config import settings
from app.core.logging import logger


EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
TOKEN_KEYS = {
    "access_token",
    "refresh_token",
    "battlenet_token",
    "hashed_password",
    "password",
    "secret_key",
    "jwt_secret",
    "anthropic_api_key",
    "authorization",
    "cookie",
    "set-cookie",
}


def _mask_emails(value: str) -> str:
    return EMAIL_PATTERN.sub("[redacted-email]", value)


def _scrub(obj: Any) -> Any:
    """Recursively scrub known-sensitive values from arbitrary objects."""
    if isinstance(obj, str):
        return _mask_emails(obj)
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            key_lower = k.lower() if isinstance(k, str) else k
            if isinstance(key_lower, str) and key_lower in TOKEN_KEYS:
                out[k] = "[redacted]"
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_scrub(v) for v in obj)
    return obj


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Sentry before_send hook.

    - Drop 401/404 errors (expected user-level errors, not bugs).
    - Scrub email addresses and known token/password keys from the event.
    """
    # Drop expected 4xx errors
    response = (event.get("contexts") or {}).get("response") or {}
    status_code = response.get("status_code")
    if status_code in (401, 404):
        return None

    exc_info = hint.get("exc_info") if hint else None
    if exc_info:
        exc = exc_info[1]
        # Starlette/FastAPI HTTPException carries status_code
        code = getattr(exc, "status_code", None)
        if code in (401, 404):
            return None

    # Scrub request data
    if "request" in event:
        event["request"] = _scrub(event["request"])
    if "extra" in event:
        event["extra"] = _scrub(event["extra"])
    if "exception" in event:
        event["exception"] = _scrub(event["exception"])
    if "breadcrumbs" in event:
        event["breadcrumbs"] = _scrub(event["breadcrumbs"])
    # message is a string on the top level
    if isinstance(event.get("message"), str):
        event["message"] = _mask_emails(event["message"])

    return event


def init_sentry() -> bool:
    """Initialise Sentry if SENTRY_DSN is set. Returns True if initialised."""
    dsn = settings.SENTRY_DSN
    if not dsn:
        logger.info("sentry.disabled", reason="no_dsn")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    except ImportError:
        logger.warning("sentry.sdk_not_installed")
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.ENVIRONMENT,
        release=settings.VERSION,
        sample_rate=1.0,  # 100% of errors
        traces_sample_rate=0.1,  # 10% of transactions
        send_default_pii=False,
        before_send=_before_send,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            CeleryIntegration(),
            SqlalchemyIntegration(),
        ],
    )
    logger.info("sentry.initialised", environment=settings.ENVIRONMENT)
    return True


def set_user_context(user_id: str | None, tier: str | None = None) -> None:
    """Attach user_id + tier to the current Sentry scope."""
    try:
        import sentry_sdk
    except ImportError:
        return
    if user_id is None:
        sentry_sdk.set_user(None)
        return
    sentry_sdk.set_user({"id": user_id, "tier": tier})


def scrub_secrets(text: str) -> str:
    """Public utility: redact emails and Anthropic API key patterns in text."""
    if not text:
        return text
    redacted = EMAIL_PATTERN.sub("[redacted-email]", text)
    redacted = re.sub(r"sk-ant-[A-Za-z0-9_\-]{10,}", "sk-ant-[redacted]", redacted)
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]{10,}", "Bearer [redacted]", redacted)
    return redacted
