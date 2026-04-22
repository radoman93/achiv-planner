"""Achievement API — browse, search, seasonal, and guide endpoints."""

from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import Integer as SAInteger, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user, verify_token
from app.core.database import get_db
from app.core.rate_limiter import limiter
from app.models.achievement import Achievement, AchievementCriteria, AchievementDependency
from app.models.content import Comment, Guide
from app.models.progress import UserAchievementState
from app.models.user import User
from app.models.zone import Zone

router = APIRouter()


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _ok(data):
    return {"data": data, "error": None}


def _confidence_tier(score: float) -> str:
    if score >= 0.85:
        return "verified"
    if score >= 0.65:
        return "high"
    if score >= 0.40:
        return "medium"
    if score >= 0.20:
        return "low"
    return "research_required"


def _ach_summary(a: Achievement) -> dict:
    return {
        "id": str(a.id),
        "blizzard_id": a.blizzard_id,
        "name": a.name,
        "category": a.category,
        "subcategory": a.subcategory,
        "expansion": a.expansion,
        "points": a.points,
        "zone_name": a.zone.name if a.zone else None,
        "is_seasonal": a.is_seasonal,
        "requires_group": a.requires_group,
        "confidence_tier": _confidence_tier(a.confidence_score),
        "is_meta": a.is_meta,
    }


# ---------------------------------------------------------------------------
# GET /api/achievements — paginated achievement browser (public)
# ---------------------------------------------------------------------------

@router.get("")
@limiter.limit("100/minute")
async def list_achievements(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    expansion: Optional[str] = None,
    category: Optional[str] = None,
    zone_id: Optional[UUID] = None,
    is_seasonal: Optional[bool] = None,
    requires_group: Optional[bool] = None,
    min_points: Optional[int] = None,
    max_points: Optional[int] = None,
    completed: Optional[bool] = None,
    character_id: Optional[UUID] = None,
    access_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    # Auth check if completed filter is used
    if completed is not None:
        if not access_token:
            raise HTTPException(401, "authentication required for completed filter")
        payload = verify_token(access_token)
        if not character_id:
            raise HTTPException(400, "character_id required when filtering by completed")

    # Build query
    q = select(Achievement).outerjoin(Zone, Achievement.zone_id == Zone.id)
    count_q = select(func.count(Achievement.id))

    filters = []
    if expansion:
        filters.append(Achievement.expansion == expansion)
    if category:
        filters.append(Achievement.category == category)
    if zone_id:
        filters.append(Achievement.zone_id == zone_id)
    if is_seasonal is not None:
        filters.append(Achievement.is_seasonal == is_seasonal)
    if requires_group is not None:
        filters.append(Achievement.requires_group == requires_group)
    if min_points is not None:
        filters.append(Achievement.points >= min_points)
    if max_points is not None:
        filters.append(Achievement.points <= max_points)

    if completed is not None and character_id:
        completed_sub = (
            select(UserAchievementState.achievement_id)
            .where(
                UserAchievementState.character_id == character_id,
                UserAchievementState.completed == True,  # noqa: E712
            )
        )
        if completed:
            filters.append(Achievement.id.in_(completed_sub))
        else:
            filters.append(Achievement.id.notin_(completed_sub))

    for f in filters:
        q = q.where(f)
        count_q = count_q.where(f)

    # Total count
    total = (await db.execute(count_q)).scalar() or 0
    total_pages = max(1, (total + per_page - 1) // per_page)

    # Paginate
    q = (
        q.options(selectinload(Achievement.zone))
        .order_by(Achievement.category, Achievement.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(q)
    achs = result.scalars().unique().all()

    return _ok({
        "achievements": [_ach_summary(a) for a in achs],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    })


# ---------------------------------------------------------------------------
# GET /api/achievements/search — full-text search (public)
# ---------------------------------------------------------------------------

@router.get("/search")
@limiter.limit("60/minute")
async def search_achievements(
    request: Request,
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    # PostgreSQL full-text search on name + description
    ts_query = func.plainto_tsquery("english", q)
    ts_vector = func.to_tsvector(
        "english",
        func.coalesce(Achievement.name, "") + " " + func.coalesce(Achievement.description, ""),
    )
    rank = func.ts_rank(ts_vector, ts_query).label("relevance_score")

    stmt = (
        select(Achievement, rank)
        .where(ts_vector.op("@@")(ts_query))
        .options(selectinload(Achievement.zone))
        .order_by(rank.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.unique().all()

    items = []
    for ach, score in rows:
        item = _ach_summary(ach)
        item["relevance_score"] = round(float(score), 4)
        items.append(item)

    return _ok({"achievements": items, "total": len(items)})


# ---------------------------------------------------------------------------
# GET /api/achievements/seasonal — seasonal achievements (public)
# ---------------------------------------------------------------------------

@router.get("/seasonal")
async def seasonal_achievements(
    status: str = Query("all", pattern="^(active|upcoming|all)$"),
    days_ahead: int = Query(60, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    today = date.today()

    stmt = (
        select(Achievement)
        .where(Achievement.is_seasonal == True)  # noqa: E712
        .options(selectinload(Achievement.zone))
    )
    result = await db.execute(stmt)
    seasonal = result.scalars().unique().all()

    active: list[dict] = []
    upcoming: list[dict] = []

    # Group by event
    events: dict[str, list[Achievement]] = {}
    for a in seasonal:
        key = a.seasonal_event or "Unknown"
        events.setdefault(key, []).append(a)

    for event_name, achs in events.items():
        sample = achs[0]
        if not sample.seasonal_start or not sample.seasonal_end:
            continue

        start = sample.seasonal_start.replace(year=today.year)
        end = sample.seasonal_end.replace(year=today.year)

        # Year-wrap handling
        if sample.seasonal_start.month > sample.seasonal_end.month:
            if today.month <= sample.seasonal_end.month + 1:
                start = sample.seasonal_start.replace(year=today.year - 1)
            else:
                end = sample.seasonal_end.replace(year=today.year + 1)

        if end < today:
            start = sample.seasonal_start.replace(year=today.year + 1)
            end = sample.seasonal_end.replace(year=today.year + 1)
            if sample.seasonal_start.month > sample.seasonal_end.month:
                end = sample.seasonal_end.replace(year=today.year + 2)

        is_active = start <= today <= end

        if is_active:
            days_remaining = (end - today).days
            active.append({
                "event_name": event_name,
                "opens_at": start.isoformat(),
                "closes_at": end.isoformat(),
                "days_remaining": days_remaining,
                "achievement_count": len(achs),
                "achievements": [_ach_summary(a) for a in achs],
            })
        elif start > today and (start - today).days <= days_ahead:
            upcoming.append({
                "event_name": event_name,
                "opens_at": start.isoformat(),
                "closes_at": end.isoformat(),
                "days_until_open": (start - today).days,
                "achievement_count": len(achs),
            })

    data: dict = {}
    if status in ("active", "all"):
        data["active"] = active
    if status in ("upcoming", "all"):
        data["upcoming"] = sorted(upcoming, key=lambda x: x["opens_at"])

    return _ok(data)


# ---------------------------------------------------------------------------
# GET /api/achievements/{id} — full achievement detail (public)
# ---------------------------------------------------------------------------

@router.get("/{achievement_id}")
async def get_achievement(
    achievement_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Achievement)
        .where(Achievement.id == achievement_id)
        .options(
            selectinload(Achievement.zone),
            selectinload(Achievement.criteria),
            selectinload(Achievement.guides),
            selectinload(Achievement.comments),
        )
    )
    ach = result.scalar_one_or_none()
    if not ach:
        raise HTTPException(404, "achievement not found")

    # Best guide
    best_guide = None
    if ach.guides:
        sorted_guides = sorted(ach.guides, key=lambda g: g.confidence_score or 0, reverse=True)
        g = sorted_guides[0]
        best_guide = {
            "id": str(g.id),
            "source_type": g.source_type,
            "source_url": g.source_url,
            "steps": g.steps,
            "confidence_score": g.confidence_score,
            "scraped_at": g.scraped_at.isoformat() if g.scraped_at else None,
        }

    # Top 5 comments
    top_comments = sorted(
        ach.comments, key=lambda c: c.combined_score or 0, reverse=True
    )[:5]

    # Dependencies
    deps_required_result = await db.execute(
        select(AchievementDependency)
        .where(AchievementDependency.dependent_achievement_id == achievement_id)
        .options(selectinload(AchievementDependency.required_achievement))
    )
    requires = [
        {"id": str(d.required_achievement_id), "name": d.required_achievement.name}
        for d in deps_required_result.scalars().all()
    ]

    deps_by_result = await db.execute(
        select(AchievementDependency)
        .where(AchievementDependency.required_achievement_id == achievement_id)
        .options(selectinload(AchievementDependency.dependent_achievement))
    )
    required_by = [
        {"id": str(d.dependent_achievement_id), "name": d.dependent_achievement.name}
        for d in deps_by_result.scalars().all()
    ]

    return _ok({
        "id": str(ach.id),
        "blizzard_id": ach.blizzard_id,
        "name": ach.name,
        "description": ach.description,
        "how_to_complete": ach.how_to_complete,
        "category": ach.category,
        "subcategory": ach.subcategory,
        "expansion": ach.expansion,
        "points": ach.points,
        "zone": {"id": str(ach.zone.id), "name": ach.zone.name} if ach.zone else None,
        "is_meta": ach.is_meta,
        "is_legacy": ach.is_legacy,
        "is_seasonal": ach.is_seasonal,
        "seasonal_event": ach.seasonal_event,
        "seasonal_start": ach.seasonal_start.isoformat() if ach.seasonal_start else None,
        "seasonal_end": ach.seasonal_end.isoformat() if ach.seasonal_end else None,
        "requires_flying": ach.requires_flying,
        "requires_group": ach.requires_group,
        "min_group_size": ach.min_group_size,
        "estimated_minutes": ach.estimated_minutes,
        "confidence_score": ach.confidence_score,
        "confidence_tier": _confidence_tier(ach.confidence_score),
        "last_scraped_at": ach.last_scraped_at.isoformat() if ach.last_scraped_at else None,
        "guide": best_guide,
        "comments": [
            {
                "id": str(c.id),
                "author": c.author,
                "text": c.raw_text[:500] if c.raw_text else "",
                "combined_score": c.combined_score,
                "comment_type": c.comment_type,
                "upvotes": c.upvotes,
            }
            for c in top_comments
        ],
        "criteria": [
            {
                "id": str(cr.id),
                "description": cr.description,
                "required_amount": cr.required_amount,
            }
            for cr in (ach.criteria or [])
        ],
        "requires": requires,
        "required_by": required_by,
    })


# ---------------------------------------------------------------------------
# GET /api/achievements/{id}/guide — guides for an achievement (public)
# ---------------------------------------------------------------------------

@router.get("/{achievement_id}/guide")
async def get_achievement_guides(
    achievement_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    # Verify achievement exists
    ach = await db.get(Achievement, achievement_id)
    if not ach:
        raise HTTPException(404, "achievement not found")

    result = await db.execute(
        select(Guide)
        .where(Guide.achievement_id == achievement_id)
        .order_by(Guide.confidence_score.desc().nullslast())
    )
    guides = result.scalars().all()

    # Fetch community tips for each guide
    comments_result = await db.execute(
        select(Comment)
        .where(
            Comment.achievement_id == achievement_id,
            Comment.comment_type.in_(["route_tip", "correction", "time_estimate"]),
        )
        .order_by(Comment.combined_score.desc().nullslast())
        .limit(5)
    )
    tips = comments_result.scalars().all()

    return _ok({
        "guides": [
            {
                "id": str(g.id),
                "source_type": g.source_type,
                "source_url": g.source_url,
                "steps": g.steps,
                "confidence_score": g.confidence_score,
                "confidence_tier": _confidence_tier(g.confidence_score or 0),
                "scraped_at": g.scraped_at.isoformat() if g.scraped_at else None,
            }
            for g in guides
        ],
        "community_tips": [
            {
                "author": c.author,
                "text": c.raw_text[:500] if c.raw_text else "",
                "score": c.combined_score,
                "type": c.comment_type,
            }
            for c in tips
        ],
    })
