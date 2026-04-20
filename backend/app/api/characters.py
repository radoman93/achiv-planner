"""Character API — CRUD, Battle.net sync, preferences."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_active_user
from app.core.celery_app import celery_app
from app.core.database import get_db
from app.core.redis import get_redis_client
from app.models.achievement import Achievement
from app.models.progress import UserAchievementState
from app.models.route import Route
from app.models.user import Character, User

router = APIRouter()

VALID_FACTIONS = {"horde", "alliance"}
VALID_CLASSES = {
    "warrior", "paladin", "hunter", "rogue", "priest", "shaman",
    "mage", "warlock", "monk", "druid", "demon hunter", "death knight",
    "evoker",
}
VALID_MODES = {"completionist", "points_per_hour", "goal_driven", "seasonal_first"}


def _ok(data):
    return {"data": data, "error": None}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_owned_character(
    character_id: UUID, user: User, db: AsyncSession
) -> Character:
    result = await db.execute(
        select(Character).where(
            Character.id == character_id,
            Character.user_id == user.id,
        )
    )
    char = result.scalar_one_or_none()
    if not char:
        raise HTTPException(404, "character not found")
    return char


async def _completion_pct(character_id: UUID, db: AsyncSession) -> float:
    completed = (
        await db.execute(
            select(func.count(UserAchievementState.id)).where(
                UserAchievementState.character_id == character_id,
                UserAchievementState.completed == True,  # noqa: E712
            )
        )
    ).scalar() or 0

    total = (await db.execute(select(func.count(Achievement.id)))).scalar() or 1
    return round(completed / total * 100, 1)


def _char_summary(c: Character, pct: float) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "realm": c.realm,
        "faction": c.faction,
        "class": c.class_,
        "level": c.level,
        "region": c.region,
        "last_synced_at": c.last_synced_at.isoformat() if c.last_synced_at else None,
        "achievement_completion_pct": pct,
    }


# ---------------------------------------------------------------------------
# GET /api/characters — list user's characters
# ---------------------------------------------------------------------------

@router.get("")
async def list_characters(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Character).where(Character.user_id == user.id)
    )
    chars = result.scalars().all()

    items = []
    for c in chars:
        pct = await _completion_pct(c.id, db)
        items.append(_char_summary(c, pct))

    return _ok(items)


# ---------------------------------------------------------------------------
# POST /api/characters — create character manually
# ---------------------------------------------------------------------------

class CreateCharacterBody(BaseModel):
    name: str = Field(min_length=2, max_length=12)
    realm: str = Field(min_length=1)
    faction: str
    class_: str = Field(alias="class")
    race: Optional[str] = None
    level: int = Field(ge=1, le=80)
    region: str = Field(default="eu")
    flying_unlocked: Optional[dict[str, bool]] = None

    model_config = {"populate_by_name": True}


@router.post("", status_code=201)
async def create_character(
    body: CreateCharacterBody,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    if body.faction.lower() not in VALID_FACTIONS:
        raise HTTPException(422, f"faction must be one of: {', '.join(VALID_FACTIONS)}")
    if body.class_.lower() not in VALID_CLASSES:
        raise HTTPException(422, f"class must be one of: {', '.join(sorted(VALID_CLASSES))}")

    char = Character(
        user_id=user.id,
        name=body.name,
        realm=body.realm,
        faction=body.faction.lower(),
        class_=body.class_.lower(),
        race=body.race,
        level=body.level,
        region=body.region.lower(),
        flying_unlocked=body.flying_unlocked,
    )
    db.add(char)
    await db.commit()
    await db.refresh(char)

    return _ok(_char_summary(char, 0.0))


# ---------------------------------------------------------------------------
# GET /api/characters/{id} — character detail
# ---------------------------------------------------------------------------

@router.get("/{character_id}")
async def get_character(
    character_id: UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    char = await _get_owned_character(character_id, user, db)

    # Achievement stats
    completed_count = (
        await db.execute(
            select(func.count(UserAchievementState.id)).where(
                UserAchievementState.character_id == character_id,
                UserAchievementState.completed == True,  # noqa: E712
            )
        )
    ).scalar() or 0

    total_eligible = (await db.execute(select(func.count(Achievement.id)))).scalar() or 0

    points_earned = (
        await db.execute(
            select(func.coalesce(func.sum(Achievement.points), 0)).where(
                Achievement.id.in_(
                    select(UserAchievementState.achievement_id).where(
                        UserAchievementState.character_id == character_id,
                        UserAchievementState.completed == True,  # noqa: E712
                    )
                )
            )
        )
    ).scalar() or 0

    # Completion by expansion
    expansion_stats_result = await db.execute(
        select(
            Achievement.expansion,
            func.count(Achievement.id).label("total"),
            func.count(UserAchievementState.id).filter(
                UserAchievementState.completed == True  # noqa: E712
            ).label("completed"),
        )
        .outerjoin(
            UserAchievementState,
            (UserAchievementState.achievement_id == Achievement.id)
            & (UserAchievementState.character_id == character_id),
        )
        .where(Achievement.expansion.isnot(None))
        .group_by(Achievement.expansion)
    )
    completion_by_expansion = {}
    for row in expansion_stats_result.all():
        exp, total, comp = row
        if exp:
            completion_by_expansion[exp] = {
                "completed": comp,
                "total": total,
                "pct": round(comp / total * 100, 1) if total > 0 else 0,
            }

    # Active route summary
    active_route_result = await db.execute(
        select(Route).where(
            Route.character_id == character_id,
            Route.status == "active",
        ).limit(1)
    )
    active_route = active_route_result.scalar_one_or_none()
    route_summary = None
    if active_route:
        from app.models.route import RouteStop
        remaining_count = (
            await db.execute(
                select(func.count(RouteStop.id)).where(
                    RouteStop.route_id == active_route.id,
                    RouteStop.completed == False,  # noqa: E712
                    RouteStop.skipped == False,  # noqa: E712
                )
            )
        ).scalar() or 0

        route_summary = {
            "route_id": str(active_route.id),
            "mode": active_route.mode,
            "stops_remaining": remaining_count,
        }

    return _ok({
        "id": str(char.id),
        "name": char.name,
        "realm": char.realm,
        "faction": char.faction,
        "class": char.class_,
        "race": char.race,
        "level": char.level,
        "region": char.region,
        "flying_unlocked": char.flying_unlocked,
        "current_expansion": char.current_expansion,
        "last_synced_at": char.last_synced_at.isoformat() if char.last_synced_at else None,
        "stats": {
            "total_completed": completed_count,
            "total_eligible": total_eligible,
            "points_earned": points_earned,
            "completion_by_expansion": completion_by_expansion,
        },
        "active_route": route_summary,
    })


# ---------------------------------------------------------------------------
# PUT /api/characters/{id} — update character fields
# ---------------------------------------------------------------------------

class UpdateCharacterBody(BaseModel):
    level: Optional[int] = Field(None, ge=1, le=80)
    flying_unlocked: Optional[dict[str, bool]] = None
    current_expansion: Optional[str] = None


@router.put("/{character_id}")
async def update_character(
    character_id: UUID,
    body: UpdateCharacterBody,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    char = await _get_owned_character(character_id, user, db)

    if body.level is not None:
        char.level = body.level
    if body.flying_unlocked is not None:
        char.flying_unlocked = body.flying_unlocked
    if body.current_expansion is not None:
        char.current_expansion = body.current_expansion

    await db.commit()
    await db.refresh(char)

    pct = await _completion_pct(char.id, db)
    return _ok(_char_summary(char, pct))


# ---------------------------------------------------------------------------
# POST /api/characters/{id}/sync — trigger Battle.net sync
# ---------------------------------------------------------------------------

@router.post("/{character_id}/sync")
async def trigger_sync(
    character_id: UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    char = await _get_owned_character(character_id, user, db)

    if not user.battlenet_token:
        raise HTTPException(400, "Battle.net OAuth not connected")

    # Check if sync already in progress
    redis = get_redis_client()
    try:
        lock_key = f"sync:lock:{character_id}"
        locked = await redis.get(lock_key)
        if locked:
            raise HTTPException(429, "sync already in progress for this character")

        # Set lock (5 minute TTL)
        await redis.set(lock_key, "1", ex=300)
    finally:
        await redis.aclose()

    # Queue Celery task
    task = celery_app.send_task(
        "pipeline.sync.achievement_sync",
        args=[str(character_id), str(user.id)],
        queue="sync",
    )

    # Store progress key
    redis2 = get_redis_client()
    try:
        await redis2.set(
            f"sync:progress:{task.id}",
            '{"status":"queued","processed":0,"total":0,"percent":0}',
            ex=600,
        )
    finally:
        await redis2.aclose()

    return _ok({"job_id": task.id, "status": "queued"})


# ---------------------------------------------------------------------------
# GET /api/characters/{id}/sync/status/{job_id} — poll sync progress
# ---------------------------------------------------------------------------

@router.get("/{character_id}/sync/status/{job_id}")
async def sync_status(
    character_id: UUID,
    job_id: str,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify ownership
    await _get_owned_character(character_id, user, db)

    redis = get_redis_client()
    try:
        import json
        progress_raw = await redis.get(f"sync:progress:{job_id}")
    finally:
        await redis.aclose()

    if not progress_raw:
        # Check Celery result
        result = celery_app.AsyncResult(job_id)
        state = result.state.lower() if result.state else "unknown"
        return _ok({
            "status": state,
            "progress": {"processed": 0, "total": 0, "percent": 0},
            "completed_at": None,
            "error": str(result.result) if result.failed() else None,
        })

    progress = json.loads(progress_raw)
    return _ok({
        "status": progress.get("status", "unknown"),
        "progress": {
            "processed": progress.get("processed", 0),
            "total": progress.get("total", 0),
            "percent": progress.get("percent", 0),
        },
        "completed_at": progress.get("completed_at"),
        "error": progress.get("error"),
    })


# ---------------------------------------------------------------------------
# PUT /api/characters/{id}/preferences — update play preferences
# ---------------------------------------------------------------------------

class PreferencesBody(BaseModel):
    priority_mode: Optional[str] = None
    session_duration_minutes: Optional[int] = Field(None, ge=30, le=480)
    solo_only: Optional[bool] = None


@router.put("/{character_id}/preferences")
async def update_preferences(
    character_id: UUID,
    body: PreferencesBody,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    # Preferences are stored on User, not Character
    await _get_owned_character(character_id, user, db)

    if body.priority_mode is not None:
        if body.priority_mode not in VALID_MODES:
            raise HTTPException(422, f"mode must be one of: {', '.join(sorted(VALID_MODES))}")
        user.priority_mode = body.priority_mode
    if body.session_duration_minutes is not None:
        user.session_duration_minutes = body.session_duration_minutes
    if body.solo_only is not None:
        user.solo_only = body.solo_only

    await db.commit()
    await db.refresh(user)

    return _ok({
        "priority_mode": user.priority_mode,
        "session_duration_minutes": user.session_duration_minutes,
        "solo_only": user.solo_only,
    })
