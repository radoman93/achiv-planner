import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.core.config import settings
from app.core.database import check_db_health
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware, RequestLoggingMiddleware
from app.core.redis import check_redis_health

configure_logging()
logger = structlog.get_logger()

app = FastAPI(
    title="WoW Achievement Route Optimizer",
    description="Generates personalized, optimized achievement routes for WoW players.",
    version=settings.VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)


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

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(auth_bnet_router, prefix="/api/auth", tags=["auth"])
