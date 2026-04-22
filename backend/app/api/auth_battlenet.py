import asyncio
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import _set_auth_cookies
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import logger
from app.core.redis import get_redis, get_redis_client
from app.models.user import User
from app.services import battlenet as bnet
from app.services.sync_service import enqueue_character_sync

router = APIRouter()

CHARACTER_LIST_TIMEOUT_SECONDS = 15

STATE_TTL_SECONDS = 600
VALID_REGIONS = {"us", "eu", "kr", "tw"}


@router.get("/battlenet")
async def battlenet_login(
    region: str = Query(default="eu"),
    redis: Redis = Depends(get_redis),
):
    if region not in VALID_REGIONS:
        raise HTTPException(status_code=400, detail="invalid region")
    state = secrets.token_urlsafe(32)
    await redis.set(f"bnet:state:{state}", region, ex=STATE_TTL_SECONDS)
    return RedirectResponse(bnet.authorize_url(region, state))


@router.get("/battlenet/callback")
async def battlenet_callback(
    code: str,
    state: str,
    region: str = Query(default="eu"),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    stored = await redis.get(f"bnet:state:{state}")
    if not stored or stored != region:
        raise HTTPException(status_code=400, detail="invalid state")
    await redis.delete(f"bnet:state:{state}")

    token_data = await bnet.exchange_code(code, region)
    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in", 3600)

    userinfo = await bnet.fetch_userinfo(access_token)
    battlenet_id = str(userinfo.get("id"))
    battletag = userinfo.get("battletag", "")
    synthetic_email = f"{battlenet_id}@battlenet.local"

    existing = await db.execute(select(User).where(User.battlenet_id == battlenet_id))
    user = existing.scalar_one_or_none()
    is_new = user is None
    if is_new:
        user = User(
            email=synthetic_email,
            battlenet_id=battlenet_id,
        )
        db.add(user)

    user.battlenet_token = access_token
    user.battlenet_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    user.battlenet_region = region
    await db.commit()
    await db.refresh(user)

    characters: list = []
    try:
        characters = await asyncio.wait_for(
            bnet.fetch_character_list(user, region, db),
            timeout=CHARACTER_LIST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "battlenet.callback.character_list_timeout",
            user_id=str(user.id),
            timeout=CHARACTER_LIST_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "battlenet.callback.character_list_failed",
            user_id=str(user.id),
            error=str(exc),
        )

    if characters:
        sync_redis = get_redis_client()
        try:
            for char in characters:
                try:
                    acquired, job_id = await enqueue_character_sync(
                        char.id, user.id, sync_redis
                    )
                    if acquired:
                        logger.info(
                            "battlenet.callback.sync_enqueued",
                            user_id=str(user.id),
                            character_id=str(char.id),
                            job_id=job_id,
                        )
                except Exception as exc:
                    logger.warning(
                        "battlenet.callback.sync_enqueue_failed",
                        user_id=str(user.id),
                        character_id=str(char.id),
                        error=str(exc),
                    )
        finally:
            await sync_redis.aclose()

    redirect_path = "/onboarding" if is_new else "/dashboard"
    response = RedirectResponse(url=f"{settings.FRONTEND_URL}{redirect_path}")
    _set_auth_cookies(response, user.id)
    return response
