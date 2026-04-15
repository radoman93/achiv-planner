from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import check_db_health
from app.core.redis import check_redis_health

router = APIRouter()


@router.get("/health")
async def health():
    db_ok = await check_db_health()
    redis_ok = await check_redis_health()
    payload = {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "db": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "version": settings.VERSION,
    }
    status = 200 if (db_ok and redis_ok) else 503
    return JSONResponse(payload, status_code=status)
