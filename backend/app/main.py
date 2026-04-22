import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.health import router as health_router
from app.core.config import settings
from app.core.database import check_db_health
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware, RequestLoggingMiddleware
from app.core.rate_limiter import limiter, rate_limit_exceeded_handler
from app.core.redis import check_redis_health
from app.core.security_headers import (
    PayloadSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.sentry import init_sentry
from app.core.startup_validator import validate_startup_config

configure_logging()
validate_startup_config()
init_sentry()
logger = structlog.get_logger()

app = FastAPI(
    title="WoW Achievement Route Optimizer",
    description="Generates personalized, optimized achievement routes for WoW players.",
    version=settings.VERSION,
)

# Allowed origins:
#   production: only the configured FRONTEND_URL
#   development: FRONTEND_URL + localhost:3000/3001 for local frontend dev
cors_origins = [settings.FRONTEND_URL]
if settings.ENVIRONMENT == "development":
    cors_origins.extend(["http://localhost:3000", "http://localhost:3001"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(PayloadSizeLimitMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)

# slowapi wiring
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.exception("unhandled_exception", request_id=request_id, path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_server_error", "request_id": request_id},
    )


@app.on_event("startup")
async def on_startup():
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()
    logger.info("startup_health", db=db_ok, redis=redis_ok, environment=settings.ENVIRONMENT)


app.include_router(health_router, prefix="/api")

from app.api.auth import router as auth_router  # noqa: E402
from app.api.auth_battlenet import router as auth_bnet_router  # noqa: E402
from app.api.pipeline import router as pipeline_router  # noqa: E402
from app.api.dashboard import router as dashboard_router  # noqa: E402
from app.api.achievements import router as achievements_router  # noqa: E402
from app.api.characters import router as characters_router  # noqa: E402
from app.api.routes import router as routes_router  # noqa: E402
from app.api.users import router as users_router  # noqa: E402

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(auth_bnet_router, prefix="/api/auth", tags=["auth"])
app.include_router(pipeline_router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(achievements_router, prefix="/api/achievements", tags=["achievements"])
app.include_router(characters_router, prefix="/api/characters", tags=["characters"])
app.include_router(routes_router, prefix="/api/routes", tags=["routes"])
app.include_router(users_router, prefix="/api/users", tags=["users"])
