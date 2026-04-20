"""Route assembler — combines all routing pipeline outputs into a persisted Route."""

from __future__ import annotations

import logging
from statistics import mean
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.achievement import Achievement
from app.models.content import Comment, Guide
from app.models.route import Route, RouteStep, RouteStop
from app.models.user import Character
from app.router_engine.constraint_filter import FilterResult
from app.router_engine.dependency_resolver import ResolvedOrder
from app.router_engine.seasonal_override import SeasonalResult
from app.router_engine.session_structurer import Session

logger = logging.getLogger(__name__)

# Confidence score → tier mapping
CONFIDENCE_TIERS = [
    (0.85, "verified"),
    (0.65, "high"),
    (0.40, "medium"),
    (0.20, "low"),
    (0.0, "research_required"),
]


def _confidence_tier(score: float) -> str:
    for threshold, tier in CONFIDENCE_TIERS:
        if score >= threshold:
            return tier
    return "research_required"


class RouteAssembler:
    """Assembles routing pipeline outputs into a fully persisted Route with stops and steps."""

    async def assemble(
        self,
        character: Character,
        mode: str,
        filter_result: FilterResult,
        resolved_order: ResolvedOrder,
        sessions: list[Session],
        seasonal_result: SeasonalResult,
        db: AsyncSession,
    ) -> Route:
        # 1. Build Route record
        all_stop_minutes = sum(s.estimated_minutes for s in sessions)
        seasonal_minutes = sum(
            s.achievement.estimated_minutes or 0 for s in seasonal_result.active_block
        )
        total_minutes = all_stop_minutes + seasonal_minutes

        # Collect all confidence scores for overall average
        all_scores: list[float] = []
        for session in sessions:
            for stop in session.stops:
                all_scores.append(stop.achievement.confidence_score)
        for ss in seasonal_result.active_block:
            all_scores.append(ss.achievement.confidence_score)

        overall_confidence = mean(all_scores) if all_scores else 0.0

        route = Route(
            user_id=character.user_id,
            character_id=character.id,
            mode=mode,
            status="active",
            total_estimated_minutes=total_minutes,
            overall_confidence=overall_confidence,
            session_duration_minutes=None,  # set by caller if needed
            solo_only=None,
        )
        db.add(route)
        await db.flush()  # get route.id

        # 2. Build seasonal block stops (session_number = 0)
        seq = 0
        for ss in seasonal_result.active_block:
            await self._create_stop(
                db=db,
                route_id=route.id,
                achievement=ss.achievement,
                session_number=0,
                sequence_order=seq,
                is_seasonal=True,
                days_remaining=ss.days_remaining,
            )
            seq += 1

        # 3. Build main route stops
        for session in sessions:
            for stop in session.stops:
                await self._create_stop(
                    db=db,
                    route_id=route.id,
                    achievement=stop.achievement,
                    session_number=stop.session_number,
                    sequence_order=stop.sequence_order,
                    is_seasonal=False,
                    days_remaining=None,
                )

        # 4. Build blocked pool
        blocked_entries = []
        for ba in filter_result.blocked:
            blocked_entries.append(
                {
                    "achievement_id": str(ba.achievement.id),
                    "achievement_name": ba.achievement.name,
                    "reason": ba.reason.value,
                    "unlocker": ba.unlocker,
                }
            )
        route.blocked_pool = blocked_entries

        await db.flush()

        # 5. Attach community tips to stops
        await self._attach_community_tips(db, route.id)

        await db.commit()

        # 6. Return fully populated Route
        result = await db.execute(
            select(Route)
            .where(Route.id == route.id)
            .options(
                selectinload(Route.stops).selectinload(RouteStop.steps),
                selectinload(Route.stops).selectinload(RouteStop.achievement),
                selectinload(Route.stops).selectinload(RouteStop.zone),
                selectinload(Route.stops).selectinload(RouteStop.guide),
            )
        )
        route = result.scalar_one()

        logger.info(
            "Route assembled: id=%s, %d stops, %d minutes, confidence=%.2f",
            route.id,
            len(route.stops),
            route.total_estimated_minutes or 0,
            route.overall_confidence or 0,
        )
        return route

    # ------------------------------------------------------------------
    # Stop creation
    # ------------------------------------------------------------------

    async def _create_stop(
        self,
        db: AsyncSession,
        route_id: UUID,
        achievement: Achievement,
        session_number: int,
        sequence_order: int,
        is_seasonal: bool,
        days_remaining: int | None,
    ) -> RouteStop:
        # Find best guide
        guide = await self._best_guide(db, achievement.id)

        stop = RouteStop(
            route_id=route_id,
            achievement_id=achievement.id,
            session_number=session_number,
            sequence_order=sequence_order,
            zone_id=achievement.zone_id,
            estimated_minutes=achievement.estimated_minutes,
            confidence_tier=_confidence_tier(achievement.confidence_score),
            guide_id=guide.id if guide else None,
            is_seasonal=is_seasonal,
            days_remaining=days_remaining,
        )
        db.add(stop)
        await db.flush()

        # Create RouteSteps from guide.steps JSON
        if guide and guide.steps and isinstance(guide.steps, list):
            for idx, step_data in enumerate(guide.steps):
                step = RouteStep(
                    route_stop_id=stop.id,
                    sequence_order=idx,
                    description=step_data.get("label", step_data.get("description", "")),
                    step_type=step_data.get("type", "action"),
                    location=step_data.get("zone", step_data.get("location")),
                    source_reference=guide.source_url,
                )
                db.add(step)

        return stop

    async def _best_guide(self, db: AsyncSession, achievement_id: UUID) -> Guide | None:
        result = await db.execute(
            select(Guide)
            .where(Guide.achievement_id == achievement_id)
            .order_by(Guide.confidence_score.desc().nullslast())
            .limit(1)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Community tips
    # ------------------------------------------------------------------

    async def _attach_community_tips(self, db: AsyncSession, route_id: UUID) -> None:
        """Fetch top 3 relevant comments for each stop and store as JSON."""
        result = await db.execute(
            select(RouteStop).where(RouteStop.route_id == route_id)
        )
        stops = result.scalars().all()

        for stop in stops:
            comments_result = await db.execute(
                select(Comment)
                .where(
                    Comment.achievement_id == stop.achievement_id,
                    Comment.comment_type.in_(["route_tip", "correction", "time_estimate"]),
                )
                .order_by(Comment.combined_score.desc().nullslast())
                .limit(3)
            )
            comments = comments_result.scalars().all()

            if comments:
                stop.community_tips = [
                    {
                        "author": c.author,
                        "text": c.raw_text[:500] if c.raw_text else "",
                        "score": c.combined_score,
                        "type": c.comment_type,
                    }
                    for c in comments
                ]
