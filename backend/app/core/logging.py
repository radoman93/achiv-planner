import logging
import sys

import structlog

from app.core.config import settings


SERVICE_NAME = "wow-optimizer-backend"


def _add_service(logger, method_name, event_dict):
    event_dict.setdefault("service", SERVICE_NAME)
    event_dict.setdefault("environment", settings.ENVIRONMENT)
    return event_dict


def configure_logging() -> None:
    """Configure structlog.

    Production: JSON output for ingestion by log aggregators.
    Development: colored console output for human readability.
    """
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _add_service,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.ENVIRONMENT == "development":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger()
