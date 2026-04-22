"""Route API — generate, retrieve, complete/skip stops, reoptimize, archive."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_active_user
from app.core.database import get_db
from app.core.redis import get_redis_client
from app.models.achievement import Achievement, AchievementDependency
from app.models.content import Guide
from app.models.progress import UserAchievementState
from app.models.route import Route, RouteStep, RouteStop
from app.models.user import Character, User
from app.models.zone import Zone

router = APIRouter()
logger = logging.getLogger(__name__)

VALID_MODES = {"completionist", "points_per_hour", "goal_driven", "seasonal_first"}
FREE_TIER_DAILY_LIMIT = 5
PRO_TIER_DAILY_LIMIT = 50


def _ok(data):
    return {"data": data, "error": None}


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _serialize_stop(stop: RouteStop) -> dict:
    ach = stop.achievement
    return {
        "id": str(stop.id),
        "achievement": {
            "id": str(ach.id),
            "blizzard_id": ach.blizzard_id,
            "name": ach.name,
            "points": ach.points,
            "category": ach.category,
        } if ach else None,
        "zone": {"name": stop.zone.name, "expansion": stop.zone.expansion} if stop.zone else None,
        "estimated_minutes": stop.estimated_minutes,
        "confidence_tier": stop.confidence_tier,
        "is_seasonal": stop.is_seasonal,
        "days_remaining": stop.days_remaining,
        "steps": [
            {
                "order": s.sequence_order,
                "description": s.description,
                "step_type": s.step_type,
                "location": s.location,
            }
            for s in (stop.steps or [])
        ],
        "community_tips": stop.community_tips or [],
        "wowhead_url": f"https://www.wowhead.com/achievement={ach.blizzard_id}" if ach else None,
        "completed": stop.completed,
        "skipped": stop.skipped,
    }


def _serialize_route(route: Route) -> dict:
    # Group stops by session
    seasonal_stops = []
    session_map: dict[int, list] = {}

    for stop in (route.stops or []):
        if stop.session_number == 0:
            seasonal_stops.append(_serialize_stop(stop))
        else:
            session_map.setdefault(stop.session_number, []).append(_serialize_stop(stop))

    sessions = []
    for snum in sorted(session_map.keys()):
        stops = session_map[snum]
        total_min = sum(s["estimated_minutes"] or 0 for s in stops)
        # Primary zone = most common zone
        zone_counts: dict[str, int] = {}
        for s in stops:
            zn = s["zone"]["name"] if s.get("zone") else "Unknown"
            zone_counts[zn] = zone_counts.get(zn, 0) + 1
        primary_zone = max(zone_counts, key=zone_counts.get) if zone_counts else "Unknown"

        sessions.append({
            "session_number": snum,
            "estimated_minutes": total_min,
            "primary_zone": primary_zone,
            "stops": stops,
        })

    return {
        "id": str(route.id),
        "mode": route.mode,
        "status": route.status,
        "created_at": route.created_at.isoformat() if route.created_at else None,
        "overall_confidence": route.overall_confidence,
        "total_estimated_minutes": route.total_estimated_minutes,
        "seasonal_block": {"stops": seasonal_stops},
        "sessions": sessions,
        "blocked_pool": route.blocked_pool or [],
    }


def _serialize_route_summary(route: Route) -> dict:
    return {
        "id": str(route.id),
        "mode": route.mode,
        "status": route.status,
        "created_at": route.created_at.isoformat() if route.created_at else None,
        "overall_confidence": route.overall_confidence,
        "total_estimated_minutes": route.total_estimated_minutes,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_owned_route(
    route_id: UUID, user: User, db: AsyncSession, eager: bool = True,
) -> Route:
    stmt = select(Route).where(Route.id == route_id, Route.user_id == user.id)
    if eager:
        stmt = stmt.options(
            selectinload(Route.stops).selectinload(RouteStop.achievement),
            selectinload(Route.stops).selectinload(RouteStop.zone),
            selectinload(Route.stops).selectinload(RouteStop.steps),
        )
    result = await db.execute(stmt)
    route = result.scalar_one_or_none()
    if not route:
        raise HTTPException(404, "route not found")
    return route


def _daily_limit_for(user: User) -> int:
    return PRO_TIER_DAILY_LIMIT if user.tier == "pro" else FREE_TIER_DAILY_LIMIT


async def _check_rate_limit(user: User) -> None:
    limit = _daily_limit_for(user)
    redis = get_redis_client()
    try:
        key = f"rate:routes:{user.id}:{date.today().isoformat()}"
        count = await redis.get(key)
        if count and int(count) >= limit:
            raise HTTPException(429, f"{user.tier} tier limit: {limit} route generations per day")
    finally:
        await redis.aclose()


async def _increment_rate_limit(user: User) -> None:
    redis = get_redis_client()
    try:
        key = f"rate:routes:{user.id}:{date.today().isoformat()}"
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 86400)
        await pipe.execute()
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# POST /api/routes/generate — generate a new route
# ---------------------------------------------------------------------------

class GenerateRouteBody(BaseModel):
    character_id: UUID
    mode: str = "completionist"
    constraints: Optional[dict] = None


@router.post("/generate")
async def generate_route(
    body: GenerateRouteBody,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    import time as _time
    _t_start = _time.perf_counter()

    def _step(label: str, t0: float) -> float:
        elapsed_ms = (_time.perf_counter() - t0) * 1000
        logger.info("route.generate.%s took %.0fms", label, elapsed_ms)
        return _time.perf_counter()

    if body.mode not in VALID_MODES:
        raise HTTPException(422, f"mode must be one of: {', '.join(sorted(VALID_MODES))}")

    # Validate character ownership
    char_result = await db.execute(
        select(Character).where(
            Character.id == body.character_id,
            Character.user_id == user.id,
        )
    )
    character = char_result.scalar_one_or_none()
    if not character:
        raise HTTPException(404, "character not found")

    _t = _step("load_character", _t_start)

    # Guardrail: a Battle.net-connected user whose character has never been
    # synced would silently get a route that includes already-earned
    # achievements. last_synced_at is set on every sync attempt — including
    # empty ones for characters with no public Blizzard profile — so it's a
    # reliable signal for "we tried to pull completions for this character".
    if user.battlenet_token and character.last_synced_at is None:
        raise HTTPException(
            409,
            detail={
                "error": "character_not_synced",
                "character_id": str(body.character_id),
                "message": (
                    "This character has not been synced with Battle.net yet. "
                    "Trigger a sync before generating a route."
                ),
            },
        )

    # Rate limit check
    await _check_rate_limit(user)

    # Parse constraints
    constraints = body.constraints or {}
    solo_only = constraints.get("solo_only", user.solo_only)
    expansion_filter = constraints.get("expansion_filter")
    zone_filter = constraints.get("zone_filter")
    exclude_ids = set(constraints.get("exclude_achievement_ids", []))

    # Load uncompleted achievements for character
    completed_sub = (
        select(UserAchievementState.achievement_id)
        .where(
            UserAchievementState.character_id == body.character_id,
            UserAchievementState.completed == True,  # noqa: E712
        )
    )

    ach_stmt = (
        select(Achievement)
        .where(Achievement.id.notin_(completed_sub))
        .options(
            selectinload(Achievement.zone),
            selectinload(Achievement.guides),
        )
    )
    if expansion_filter:
        ach_stmt = ach_stmt.where(Achievement.expansion.in_(expansion_filter))
    if zone_filter:
        ach_stmt = ach_stmt.where(Achievement.zone_id.in_(zone_filter))

    result = await db.execute(ach_stmt)
    achievements = list(result.scalars().unique().all())

    if exclude_ids:
        achievements = [a for a in achievements if str(a.id) not in exclude_ids]

    if not achievements:
        raise HTTPException(400, "no eligible achievements found for this character")

    _t = _step(f"load_achievements[{len(achievements)}]", _t)

    # Load dependencies
    deps_result = await db.execute(select(AchievementDependency))
    all_deps = list(deps_result.scalars().all())

    # Load zones
    zones_result = await db.execute(select(Zone))
    all_zones = list(zones_result.scalars().all())

    _t = _step(f"load_deps_and_zones[deps={len(all_deps)},zones={len(all_zones)}]", _t)

    # Run routing pipeline
    from app.router_engine.constraint_filter import ConstraintFilter
    from app.router_engine.dependency_resolver import DependencyResolver
    from app.router_engine.geographic_clusterer import GeographicClusterer
    from app.router_engine.route_assembler import RouteAssembler
    from app.router_engine.seasonal_override import SeasonalOverride
    from app.router_engine.session_structurer import SessionStructurer
    from app.router_engine.zone_graph import ZoneGraph

    # 1. Constraint filter
    filter_result = ConstraintFilter().filter(achievements, character, solo_only=solo_only)
    _t = _step("constraint_filter", _t)

    # 2. Dependency resolver
    resolved_order = DependencyResolver().resolve(filter_result.eligible, all_deps)
    _t = _step("dependency_resolver", _t)

    # 3. Zone graph
    redis = get_redis_client()
    try:
        zone_graph = ZoneGraph(redis)
        await zone_graph.build_graph(all_zones, character)
        _t = _step("zone_graph", _t)

        # 4. Geographic clusterer
        clusters = await GeographicClusterer().cluster(
            resolved_order, character, zone_graph
        )
        _t = _step(f"clusterer[{len(clusters)}]", _t)
    finally:
        await redis.aclose()

    # 5. Session structurer
    partial_result = await db.execute(
        select(UserAchievementState).where(
            UserAchievementState.character_id == body.character_id,
            UserAchievementState.completed == False,  # noqa: E712
        )
    )
    partial_states = partial_result.scalars().all()
    partially_completed: dict[str, float] = {}
    for state in partial_states:
        if state.criteria_progress:
            total = sum(
                v for v in state.criteria_progress.values()
                if isinstance(v, (int, float))
            )
            partially_completed[str(state.achievement_id)] = min(total, 99.0)

    sessions = SessionStructurer().structure(
        clusters,
        user.session_duration_minutes,
        partially_completed,
    )
    _t = _step(f"session_structurer[{len(sessions)}]", _t)

    # 6. Seasonal override
    completed_ids_result = await db.execute(
        select(UserAchievementState.achievement_id).where(
            UserAchievementState.character_id == body.character_id,
            UserAchievementState.completed == True,  # noqa: E712
        )
    )
    completed_ids = {str(r[0]) for r in completed_ids_result.all()}

    seasonal_result = SeasonalOverride().process(
        all_achievements=filter_result.eligible,
        character=character,
        current_date=date.today(),
        completed_ids=completed_ids,
    )
    _t = _step("seasonal_override", _t)

    # 7. Assemble
    route = await RouteAssembler().assemble(
        character=character,
        mode=body.mode,
        filter_result=filter_result,
        resolved_order=resolved_order,
        sessions=sessions,
        seasonal_result=seasonal_result,
        db=db,
    )
    _t = _step(f"route_assembler[stops={sum(len(s.stops) for s in sessions)}]", _t)

    # Increment rate limit
    await _increment_rate_limit(user)

    # Re-fetch with eager loads for serialization
    route = await _get_owned_route(route.id, user, db)
    _t = _step("reload_for_serialize", _t)

    payload = _ok(_serialize_route(route))
    logger.info(
        "route.generate.total took %.0fms",
        (_time.perf_counter() - _t_start) * 1000,
    )
    return payload


# ---------------------------------------------------------------------------
# GET /api/routes — list user's routes
# ---------------------------------------------------------------------------

@router.get("")
async def list_routes(
    character_id: Optional[UUID] = None,
    status: str = Query("active", pattern="^(active|archived|all)$"),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Route).where(Route.user_id == user.id)
    if status != "all":
        stmt = stmt.where(Route.status == status)
    if character_id:
        stmt = stmt.where(Route.character_id == character_id)
    stmt = stmt.order_by(Route.created_at.desc())

    result = await db.execute(stmt)
    routes = result.scalars().all()

    return _ok([_serialize_route_summary(r) for r in routes])


# ---------------------------------------------------------------------------
# GET /api/routes/{id} — fetch existing route
# ---------------------------------------------------------------------------

@router.get("/{route_id}")
async def get_route(
    route_id: UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    route = await _get_owned_route(route_id, user, db)
    return _ok(_serialize_route(route))


# ---------------------------------------------------------------------------
# POST /api/routes/{id}/complete/{achievement_id}
# ---------------------------------------------------------------------------

@router.post("/{route_id}/complete/{achievement_id}")
async def complete_achievement(
    route_id: UUID,
    achievement_id: UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify ownership
    route = await _get_owned_route(route_id, user, db, eager=False)

    # Find the stop
    stop_result = await db.execute(
        select(RouteStop).where(
            RouteStop.route_id == route_id,
            RouteStop.achievement_id == achievement_id,
        )
    )
    stop = stop_result.scalar_one_or_none()
    if not stop:
        raise HTTPException(404, "stop not found in this route")
    if stop.completed:
        raise HTTPException(409, "already marked complete")

    from app.router_engine.reoptimizer import Reoptimizer
    redis = get_redis_client()
    try:
        reoptimizer = Reoptimizer(redis)
        result = await reoptimizer.mark_complete(str(route_id), str(achievement_id), db)
    finally:
        await redis.aclose()

    return _ok({
        "success": result.success,
        "newly_unblocked": result.newly_unblocked,
        "sessions_adjusted": result.sessions_adjusted,
        "session_time_freed": result.session_time_freed,
    })


# ---------------------------------------------------------------------------
# POST /api/routes/{id}/skip/{achievement_id}
# ---------------------------------------------------------------------------

@router.post("/{route_id}/skip/{achievement_id}")
async def skip_achievement(
    route_id: UUID,
    achievement_id: UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    route = await _get_owned_route(route_id, user, db, eager=False)

    stop_result = await db.execute(
        select(RouteStop).where(
            RouteStop.route_id == route_id,
            RouteStop.achievement_id == achievement_id,
        )
    )
    stop = stop_result.scalar_one_or_none()
    if not stop:
        raise HTTPException(404, "stop not found in this route")
    if stop.skipped:
        raise HTTPException(409, "already skipped")

    from app.router_engine.reoptimizer import Reoptimizer
    redis = get_redis_client()
    try:
        reoptimizer = Reoptimizer(redis)
        result = await reoptimizer.mark_skipped(str(route_id), str(achievement_id), db)
    finally:
        await redis.aclose()

    return _ok({
        "success": result.success,
        "achievement_id": str(achievement_id),
        "session_time_freed": result.session_time_freed,
    })


# ---------------------------------------------------------------------------
# POST /api/routes/{id}/reoptimize — full reoptimization
# ---------------------------------------------------------------------------

@router.post("/{route_id}/reoptimize")
async def reoptimize_route(
    route_id: UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    route = await _get_owned_route(route_id, user, db, eager=False)

    from app.router_engine.reoptimizer import RateLimitError, Reoptimizer
    redis = get_redis_client()
    try:
        reoptimizer = Reoptimizer(redis)
        new_route = await reoptimizer.full_reoptimize(
            str(route.character_id), route.mode or "completionist", db
        )
    except RateLimitError as e:
        raise HTTPException(
            429,
            detail={
                "message": str(e),
                "retry_after_seconds": e.minutes_remaining * 60,
            },
        )
    finally:
        await redis.aclose()

    # Re-fetch with eager loads
    new_route = await _get_owned_route(new_route.id, user, db)
    return _ok(_serialize_route(new_route))


# ---------------------------------------------------------------------------
# DELETE /api/routes/{id} — archive route
# ---------------------------------------------------------------------------

@router.delete("/{route_id}")
async def archive_route(
    route_id: UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    route = await _get_owned_route(route_id, user, db, eager=False)
    route.status = "archived"
    route.archived_at = datetime.now(timezone.utc)
    await db.commit()

    return _ok({"success": True})
