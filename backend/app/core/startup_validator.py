"""Startup validation for required environment configuration.

Called from FastAPI's lifespan startup. Fails fast with a clear message
when any required variable is missing or malformed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.config import settings
from app.core.logging import logger


class StartupValidationError(Exception):
    """Raised when a required setting is missing or malformed."""


@dataclass
class ValidationFailure:
    field: str
    message: str


REQUIRED_FIELDS = (
    "DATABASE_URL",
    "REDIS_URL",
    "SECRET_KEY",
    "BATTLENET_CLIENT_ID",
    "BATTLENET_CLIENT_SECRET",
    "ANTHROPIC_API_KEY",
    "FRONTEND_URL",
)

OPTIONAL_WITH_WARNINGS = {
    # field: warning message when missing
    "YOUTUBE_API_KEY": "YouTube fallback scraping disabled",
    "SENTRY_DSN": "Error tracking disabled",
}


def _is_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return bool(parsed.scheme) and bool(parsed.netloc)
    except Exception:
        return False


def _collect_failures() -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []

    for field in REQUIRED_FIELDS:
        value = getattr(settings, field, None)
        if not value:
            failures.append(
                ValidationFailure(field, f"{field} is required")
            )

    # SECRET_KEY length check
    if settings.SECRET_KEY and len(settings.SECRET_KEY) < 32:
        failures.append(
            ValidationFailure(
                "SECRET_KEY",
                "SECRET_KEY is required and must be at least 32 characters",
            )
        )

    # Anthropic key format
    if settings.ANTHROPIC_API_KEY and not settings.ANTHROPIC_API_KEY.startswith("sk-ant-"):
        failures.append(
            ValidationFailure(
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_API_KEY must start with 'sk-ant-'",
            )
        )

    # Frontend URL shape
    if settings.FRONTEND_URL and not _is_url(settings.FRONTEND_URL):
        failures.append(
            ValidationFailure(
                "FRONTEND_URL",
                f"FRONTEND_URL must be a valid URL (got: {settings.FRONTEND_URL!r})",
            )
        )

    # Environment enum
    if settings.ENVIRONMENT not in ("development", "production"):
        failures.append(
            ValidationFailure(
                "ENVIRONMENT",
                f"ENVIRONMENT must be 'development' or 'production' (got: {settings.ENVIRONMENT!r})",
            )
        )

    return failures


def validate_startup_config(*, strict: bool = True) -> None:
    """Run all startup checks.

    On failure (strict=True): log each error and raise SystemExit(1).
    On failure (strict=False): log each error and raise StartupValidationError
    so tests can assert on the failure mode.

    Emits a warning (but does not fail) for optional fields that are unset.
    """
    failures = _collect_failures()

    for field, warning in OPTIONAL_WITH_WARNINGS.items():
        value = getattr(settings, field, None)
        if not value:
            logger.warning("startup.optional_missing", field=field, message=warning)

    if not failures:
        logger.info(
            "startup.config_valid",
            environment=settings.ENVIRONMENT,
            checks=len(REQUIRED_FIELDS),
        )
        return

    for failure in failures:
        logger.error(
            "startup.config_invalid",
            field=failure.field,
            message=failure.message,
        )

    if strict:
        print("\n[startup] FATAL: configuration validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure.field}: {failure.message}", file=sys.stderr)
        print(
            "\nFix your backend/.env (see backend/.env.example) and restart.\n",
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise StartupValidationError(
        "; ".join(f"{f.field}: {f.message}" for f in failures)
    )
