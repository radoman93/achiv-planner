"""Route assembler — combines all routing pipeline outputs into a persisted Route."""

from __future__ import annotations

import logging
from collections import defaultdict
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

# Comment types eligible for "community tips"
COMMUNITY_TIP_TYPES = ("route_tip", "correction", "time_estimate")
COMMUNITY_TIPS_PER_STOP = 3


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
        import time as _time
        _t0 = _time.perf_counter()

        def _mark(label: str) -> None:
            nonlocal _t0
            logger.info(
                "route_assembler.%s took %.0fms",
                label,
                (_time.perf_counter() - _t0) * 1000,
            )
            _t0 = _time.perf_counter()

        # 1. Build Route record
        all_stop_minutes = sum(s.estimated_minutes for s in sessions)
        seasonal_minutes = sum(
            s.achievement.estimated_minutes or 0 for s in seasonal_result.active_block
        )
        total_minutes = all_stop_minutes + seasonal_minutes

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
            session_duration_minutes=None,
            solo_only=None,
        )
        db.add(route)
        await db.flush()  # need route.id for FK on stops
        _mark("insert_route")

        # 2. Pre-fetch best guide + community tips for every achievement in one query each
        achievement_ids: set[UUID] = set()
        for ss in seasonal_result.active_block:
            achievement_ids.add(ss.achievement.id)
        for session in sessions:
            for stop in session.stops:
                achievement_ids.add(stop.achievement.id)

        best_guide_by_ach = await self._load_best_guides(db, achievement_ids)
        _mark(f"load_best_guides[{len(best_guide_by_ach)}/{len(achievement_ids)}]")
        tips_by_ach = await self._load_community_tips(db, achievement_ids)
        _mark(f"load_community_tips[{len(tips_by_ach)}]")

        # 3. Build seasonal block stops (session_number = 0)
        pending_stops: list[RouteStop] = []
        stop_guide_pairs: list[tuple[RouteStop, Guide | None]] = []

        seq = 0
        for ss in seasonal_result.active_block:
            stop = self._build_stop(
                route_id=route.id,
                achievement=ss.achievement,
                session_number=0,
                sequence_order=seq,
                is_seasonal=True,
                days_remaining=ss.days_remaining,
                best_guide=best_guide_by_ach.get(ss.achievement.id),
                tips=tips_by_ach.get(ss.achievement.id),
            )
            pending_stops.append(stop)
            stop_guide_pairs.append((stop, best_guide_by_ach.get(ss.achievement.id)))
            seq += 1

        # 4. Build main route stops
        for session in sessions:
            for stop_meta in session.stops:
                stop = self._build_stop(
                    route_id=route.id,
                    achievement=stop_meta.achievement,
                    session_number=stop_meta.session_number,
                    sequence_order=stop_meta.sequence_order,
                    is_seasonal=False,
                    days_remaining=None,
                    best_guide=best_guide_by_ach.get(stop_meta.achievement.id),
                    tips=tips_by_ach.get(stop_meta.achievement.id),
                )
                pending_stops.append(stop)
                stop_guide_pairs.append(
                    (stop, best_guide_by_ach.get(stop_meta.achievement.id))
                )

        # 5. Bulk-add stops, one flush to populate IDs
        db.add_all(pending_stops)
        await db.flush()
        _mark(f"insert_stops[{len(pending_stops)}]")

        # 6. Build RouteSteps for stops that have guides with steps JSON
        pending_steps: list[RouteStep] = []
        for stop, guide in stop_guide_pairs:
            if guide and guide.steps and isinstance(guide.steps, list):
                for idx, step_data in enumerate(guide.steps):
                    pending_steps.append(
                        RouteStep(
                            route_stop_id=stop.id,
                            sequence_order=idx,
                            description=step_data.get(
                                "label", step_data.get("description", "")
                            ),
                            step_type=step_data.get("type", "action"),
                            location=step_data.get("zone", step_data.get("location")),
                            source_reference=guide.source_url,
                        )
                    )
        if pending_steps:
            db.add_all(pending_steps)
        _mark(f"insert_steps[{len(pending_steps)}]")

        # 7. Build blocked pool
        route.blocked_pool = [
            {
                "achievement_id": str(ba.achievement.id),
                "achievement_name": ba.achievement.name,
                "reason": ba.reason.value,
                "unlocker": ba.unlocker,
            }
            for ba in filter_result.blocked
        ]

        await db.commit()
        _mark("commit")

        # 8. Return fully populated Route
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
        _mark("reload")

        logger.info(
            "Route assembled: id=%s, %d stops, %d minutes, confidence=%.2f",
            route.id,
            len(route.stops),
            route.total_estimated_minutes or 0,
            route.overall_confidence or 0,
        )
        return route

    # ------------------------------------------------------------------
    # Bulk loaders (one query each regardless of stop count)
    # ------------------------------------------------------------------

    async def _load_best_guides(
        self, db: AsyncSession, achievement_ids: set[UUID]
    ) -> dict[UUID, Guide]:
        """Return {achievement_id: guide_with_highest_confidence} in one query."""
        if not achievement_ids:
            return {}
        result = await db.execute(
            select(Guide)
            .where(Guide.achievement_id.in_(achievement_ids))
            .order_by(
                Guide.achievement_id,
                Guide.confidence_score.desc().nullslast(),
            )
        )
        best: dict[UUID, Guide] = {}
        for guide in result.scalars().all():
            # ORDER BY ensures the first row per achievement_id is the best
            if guide.achievement_id not in best:
                best[guide.achievement_id] = guide
        return best

    async def _load_community_tips(
        self, db: AsyncSession, achievement_ids: set[UUID]
    ) -> dict[UUID, list[dict]]:
        """Return {achievement_id: [top-N tip dicts]} in one query."""
        if not achievement_ids:
            return {}
        result = await db.execute(
            select(Comment)
            .where(
                Comment.achievement_id.in_(achievement_ids),
                Comment.comment_type.in_(COMMUNITY_TIP_TYPES),
            )
            .order_by(
                Comment.achievement_id,
                Comment.combined_score.desc().nullslast(),
            )
        )
        grouped: dict[UUID, list[dict]] = defaultdict(list)
        for comment in result.scalars().all():
            bucket = grouped[comment.achievement_id]
            if len(bucket) >= COMMUNITY_TIPS_PER_STOP:
                continue
            bucket.append(
                {
                    "author": comment.author,
                    "text": comment.raw_text[:500] if comment.raw_text else "",
                    "score": comment.combined_score,
                    "type": comment.comment_type,
                }
            )
        return dict(grouped)

    # ------------------------------------------------------------------
    # Stop construction (no DB I/O — caller bulk-adds)
    # ------------------------------------------------------------------

    def _build_stop(
        self,
        *,
        route_id: UUID,
        achievement: Achievement,
        session_number: int,
        sequence_order: int,
        is_seasonal: bool,
        days_remaining: int | None,
        best_guide: Guide | None,
        tips: list[dict] | None,
    ) -> RouteStop:
        return RouteStop(
            route_id=route_id,
            achievement_id=achievement.id,
            session_number=session_number,
            sequence_order=sequence_order,
            zone_id=achievement.zone_id,
            estimated_minutes=achievement.estimated_minutes,
            confidence_tier=_confidence_tier(achievement.confidence_score),
            guide_id=best_guide.id if best_guide else None,
            is_seasonal=is_seasonal,
            days_remaining=days_remaining,
            community_tips=tips if tips else None,
        )
