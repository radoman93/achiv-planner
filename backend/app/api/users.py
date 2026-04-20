"""User API — profile, preferences, stats, account deletion."""

from __future__ import annotations

import logging
from collections import Counter
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_active_user, verify_password
from app.core.database import get_db
from app.models.achievement import Achievement
from app.models.progress import UserAchievementState
from app.models.route import Route, RouteStep, RouteStop
from app.models.user import Character, User

router = APIRouter()
logger = logging.getLogger(__name__)

VALID_MODES = {"completionist", "points_per_hour", "goal_driven", "seasonal_first"}


def _ok(data):
    return {"data": data, "error": None}


# ---------------------------------------------------------------------------
# GET /api/users/me — current user profile
# ---------------------------------------------------------------------------

@router.get("/me")
async def get_profile(user: User = Depends(get_current_active_user)):
    return _ok({
        "id": str(user.id),
        "email": user.email,
        "tier": user.tier,
        "battlenet_connected": bool(user.battlenet_token),
        "battlenet_region": user.battlenet_region,
        "priority_mode": user.priority_mode,
        "session_duration_minutes": user.session_duration_minutes,
        "solo_only": user.solo_only,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    })


# ---------------------------------------------------------------------------
# PUT /api/users/me — update user preferences
# ---------------------------------------------------------------------------

class UpdateUserBody(BaseModel):
    priority_mode: Optional[str] = None
    session_duration_minutes: Optional[int] = Field(None, ge=30, le=480)
    solo_only: Optional[bool] = None


@router.put("/me")
async def update_profile(
    body: UpdateUserBody,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
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
        "id": str(user.id),
        "email": user.email,
        "tier": user.tier,
        "battlenet_connected": bool(user.battlenet_token),
        "battlenet_region": user.battlenet_region,
        "priority_mode": user.priority_mode,
        "session_duration_minutes": user.session_duration_minutes,
        "solo_only": user.solo_only,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    })


# ---------------------------------------------------------------------------
# GET /api/users/me/stats — aggregate achievement statistics
# ---------------------------------------------------------------------------

@router.get("/me/stats")
async def get_stats(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    # Get all character IDs for this user
    chars_result = await db.execute(
        select(Character.id).where(Character.user_id == user.id)
    )
    character_ids = [r[0] for r in chars_result.all()]

    if not character_ids:
        return _ok({
            "total_achievement_points": 0,
            "total_achievements_completed": 0,
            "total_achievements_eligible": 0,
            "overall_completion_pct": 0,
            "completion_by_expansion": {},
            "estimated_hours_remaining": 0,
            "achievements_completed_this_month": 0,
            "favorite_category": None,
        })

    # Completed achievement IDs across all characters (deduplicated for account-wide)
    completed_sub = (
        select(UserAchievementState.achievement_id)
        .where(
            UserAchievementState.character_id.in_(character_ids),
            UserAchievementState.completed == True,  # noqa: E712
        )
        .distinct()
    )

    # Total completed count
    total_completed = (
        await db.execute(select(func.count()).select_from(completed_sub.subquery()))
    ).scalar() or 0

    # Total eligible (non-legacy)
    total_eligible = (
        await db.execute(
            select(func.count(Achievement.id)).where(
                Achievement.is_legacy == False  # noqa: E712
            )
        )
    ).scalar() or 0

    # Total points earned
    total_points = (
        await db.execute(
            select(func.coalesce(func.sum(Achievement.points), 0)).where(
                Achievement.id.in_(completed_sub)
            )
        )
    ).scalar() or 0

    # Overall completion %
    overall_pct = round(total_completed / total_eligible * 100, 1) if total_eligible > 0 else 0

    # Completion by expansion
    expansion_stats = await db.execute(
        select(
            Achievement.expansion,
            func.count(Achievement.id).label("total"),
        )
        .where(
            Achievement.is_legacy == False,  # noqa: E712
            Achievement.expansion.isnot(None),
        )
        .group_by(Achievement.expansion)
    )
    expansion_totals = {row[0]: row[1] for row in expansion_stats.all()}

    expansion_completed_result = await db.execute(
        select(
            Achievement.expansion,
            func.count(Achievement.id).label("completed"),
        )
        .where(
            Achievement.id.in_(completed_sub),
            Achievement.expansion.isnot(None),
        )
        .group_by(Achievement.expansion)
    )
    expansion_completed = {row[0]: row[1] for row in expansion_completed_result.all()}

    completion_by_expansion = {}
    for exp, total in expansion_totals.items():
        comp = expansion_completed.get(exp, 0)
        completion_by_expansion[exp] = {
            "completed": comp,
            "total": total,
            "pct": round(comp / total * 100, 1) if total > 0 else 0,
        }

    # Estimated hours remaining
    remaining_minutes = (
        await db.execute(
            select(func.coalesce(func.sum(Achievement.estimated_minutes), 0)).where(
                Achievement.is_legacy == False,  # noqa: E712
                Achievement.id.notin_(completed_sub),
            )
        )
    ).scalar() or 0
    estimated_hours = round(remaining_minutes / 60, 1)

    # Achievements completed this month
    from datetime import date, datetime, timezone
    first_of_month = date.today().replace(day=1)
    this_month_count = (
        await db.execute(
            select(func.count(UserAchievementState.id)).where(
                UserAchievementState.character_id.in_(character_ids),
                UserAchievementState.completed == True,  # noqa: E712
                UserAchievementState.completed_at >= datetime(
                    first_of_month.year, first_of_month.month, first_of_month.day,
                    tzinfo=timezone.utc,
                ),
            )
        )
    ).scalar() or 0

    # Favorite category
    fav_result = await db.execute(
        select(Achievement.category, func.count(Achievement.id).label("cnt"))
        .where(
            Achievement.id.in_(completed_sub),
            Achievement.category.isnot(None),
        )
        .group_by(Achievement.category)
        .order_by(func.count(Achievement.id).desc())
        .limit(1)
    )
    fav_row = fav_result.first()
    favorite_category = fav_row[0] if fav_row else None

    return _ok({
        "total_achievement_points": total_points,
        "total_achievements_completed": total_completed,
        "total_achievements_eligible": total_eligible,
        "overall_completion_pct": overall_pct,
        "completion_by_expansion": completion_by_expansion,
        "estimated_hours_remaining": estimated_hours,
        "achievements_completed_this_month": this_month_count,
        "favorite_category": favorite_category,
    })


# ---------------------------------------------------------------------------
# DELETE /api/users/me — account deletion (GDPR)
# ---------------------------------------------------------------------------

class DeleteAccountBody(BaseModel):
    password: Optional[str] = None
    confirm: Optional[bool] = None


@router.delete("/me")
async def delete_account(
    body: DeleteAccountBody,
    response: Response,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify authorization
    if user.hashed_password:
        # Password-based account
        if not body.password:
            raise HTTPException(401, "password required to delete account")
        if not verify_password(body.password, user.hashed_password):
            raise HTTPException(401, "incorrect password")
    else:
        # Battle.net-only account
        if not body.confirm:
            raise HTTPException(400, "confirm=true required to delete Battle.net-only account")

    user_id = user.id

    # Cascade delete in FK-safe order
    # 1. Get all route IDs for this user
    route_ids_result = await db.execute(
        select(Route.id).where(Route.user_id == user_id)
    )
    route_ids = [r[0] for r in route_ids_result.all()]

    if route_ids:
        # 1a. Get all route_stop IDs
        stop_ids_result = await db.execute(
            select(RouteStop.id).where(RouteStop.route_id.in_(route_ids))
        )
        stop_ids = [r[0] for r in stop_ids_result.all()]

        # 1b. Delete RouteSteps
        if stop_ids:
            await db.execute(
                delete(RouteStep).where(RouteStep.route_stop_id.in_(stop_ids))
            )

        # 1c. Delete RouteStops
        await db.execute(
            delete(RouteStop).where(RouteStop.route_id.in_(route_ids))
        )

        # 1d. Delete Routes
        await db.execute(
            delete(Route).where(Route.id.in_(route_ids))
        )

    # 2. Get character IDs
    char_ids_result = await db.execute(
        select(Character.id).where(Character.user_id == user_id)
    )
    char_ids = [r[0] for r in char_ids_result.all()]

    # 3. Delete UserAchievementState
    if char_ids:
        await db.execute(
            delete(UserAchievementState).where(
                UserAchievementState.character_id.in_(char_ids)
            )
        )

    # 4. Delete Characters
    await db.execute(
        delete(Character).where(Character.user_id == user_id)
    )

    # 5. Delete User
    await db.execute(
        delete(User).where(User.id == user_id)
    )

    await db.commit()

    # Clear auth cookies
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")

    logger.info("account_deleted", extra={"user_id_hash": hash(str(user_id)) % 10**8})

    return _ok({"message": "account deleted"})
