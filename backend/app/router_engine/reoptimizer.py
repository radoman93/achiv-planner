"""Reoptimization handler — mark complete/skipped and full route regeneration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.achievement import Achievement, AchievementDependency
from app.models.route import Route, RouteStop
from app.models.user import Character
from app.models.progress import UserAchievementState

logger = logging.getLogger(__name__)

REOPTIMIZE_COOLDOWN = 3600  # 1 hour in seconds


class RateLimitError(Exception):
    """Raised when reoptimization is attempted too soon."""

    def __init__(self, minutes_remaining: int) -> None:
        self.minutes_remaining = minutes_remaining
        super().__init__(f"Reoptimization available in {minutes_remaining} minutes")


@dataclass
class ReoptimizeResult:
    success: bool = True
    action: str = ""  # 'completed' | 'skipped' | 'full_reoptimize'
    newly_unblocked: list[str] = field(default_factory=list)
    sessions_adjusted: list[int] = field(default_factory=list)
    session_time_freed: int = 0
    new_route: Route | None = None


class Reoptimizer:
    """Handles incremental route updates and full reoptimization."""

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Method 1: Mark Complete
    # ------------------------------------------------------------------

    async def mark_complete(
        self,
        route_id: str,
        achievement_id: str,
        db: AsyncSession,
    ) -> ReoptimizeResult:
        # Find the stop
        result = await db.execute(
            select(RouteStop).where(
                RouteStop.route_id == route_id,
                RouteStop.achievement_id == achievement_id,
            )
        )
        stop = result.scalar_one_or_none()
        if not stop:
            return ReoptimizeResult(success=False, action="completed")

        # 1. Mark completed
        stop.completed = True
        stop.completed_at = datetime.now(timezone.utc)
        session_num = stop.session_number
        freed_minutes = stop.estimated_minutes or 0

        # 2. Check for newly unblockable achievements
        newly_unblocked = await self._check_unblocked(
            route_id, achievement_id, db
        )

        # 3. Add newly unblocked to route
        if newly_unblocked:
            route = await db.get(Route, route_id)
            if route:
                await self._add_unblocked_to_route(
                    route, newly_unblocked, db
                )

        await db.commit()

        return ReoptimizeResult(
            success=True,
            action="completed",
            newly_unblocked=[str(a.id) for a in newly_unblocked],
            sessions_adjusted=[session_num] if session_num is not None else [],
            session_time_freed=freed_minutes,
        )

    async def _check_unblocked(
        self,
        route_id: str,
        completed_achievement_id: str,
        db: AsyncSession,
    ) -> list[Achievement]:
        """Find achievements in the blocked pool that are now unblocked."""
        # Get the route's blocked pool
        route = await db.get(Route, route_id)
        if not route or not route.blocked_pool:
            return []

        # Find dependencies where this achievement is required
        deps_result = await db.execute(
            select(AchievementDependency).where(
                AchievementDependency.required_achievement_id == completed_achievement_id,
                AchievementDependency.dependency_type != "soft",
            )
        )
        deps = deps_result.scalars().all()
        dependent_ids = {str(d.dependent_achievement_id) for d in deps}

        blocked_ids = {
            entry["achievement_id"]
            for entry in route.blocked_pool
            if entry.get("reason") == "prerequisite_missing"
        }

        candidates = dependent_ids & blocked_ids
        if not candidates:
            return []

        # For each candidate, check if ALL prerequisites are now complete
        newly_unblocked: list[Achievement] = []
        for cand_id in candidates:
            all_prereqs_result = await db.execute(
                select(AchievementDependency.required_achievement_id).where(
                    AchievementDependency.dependent_achievement_id == cand_id,
                    AchievementDependency.dependency_type != "soft",
                )
            )
            prereq_ids = {str(r[0]) for r in all_prereqs_result.all()}

            # Check which are completed in the route
            completed_result = await db.execute(
                select(RouteStop.achievement_id).where(
                    RouteStop.route_id == route_id,
                    RouteStop.completed == True,  # noqa: E712
                )
            )
            completed_ids = {str(r[0]) for r in completed_result.all()}

            if prereq_ids.issubset(completed_ids):
                ach = await db.get(Achievement, cand_id)
                if ach:
                    newly_unblocked.append(ach)

        # Remove unblocked from blocked_pool
        if newly_unblocked:
            unblocked_ids = {str(a.id) for a in newly_unblocked}
            route.blocked_pool = [
                entry
                for entry in route.blocked_pool
                if entry["achievement_id"] not in unblocked_ids
            ]

        return newly_unblocked

    async def _add_unblocked_to_route(
        self,
        route: Route,
        achievements: list[Achievement],
        db: AsyncSession,
    ) -> None:
        """Add newly unblocked achievements to appropriate sessions."""
        # Find the last session number
        result = await db.execute(
            select(RouteStop.session_number)
            .where(RouteStop.route_id == route.id)
            .order_by(RouteStop.session_number.desc())
            .limit(1)
        )
        last_session = result.scalar_one_or_none() or 1

        # Find max sequence in that session
        result = await db.execute(
            select(RouteStop.sequence_order)
            .where(
                RouteStop.route_id == route.id,
                RouteStop.session_number == last_session,
            )
            .order_by(RouteStop.sequence_order.desc())
            .limit(1)
        )
        max_seq = result.scalar_one_or_none() or 0

        for ach in achievements:
            max_seq += 1
            stop = RouteStop(
                route_id=route.id,
                achievement_id=ach.id,
                session_number=last_session,
                sequence_order=max_seq,
                zone_id=ach.zone_id,
                estimated_minutes=ach.estimated_minutes,
                confidence_tier=self._confidence_tier(ach.confidence_score),
            )
            db.add(stop)

    # ------------------------------------------------------------------
    # Method 2: Mark Skipped
    # ------------------------------------------------------------------

    async def mark_skipped(
        self,
        route_id: str,
        achievement_id: str,
        db: AsyncSession,
    ) -> ReoptimizeResult:
        # Find the stop
        result = await db.execute(
            select(RouteStop).where(
                RouteStop.route_id == route_id,
                RouteStop.achievement_id == achievement_id,
            )
        )
        stop = result.scalar_one_or_none()
        if not stop:
            return ReoptimizeResult(success=False, action="skipped")

        # 1. Mark skipped
        stop.skipped = True
        session_num = stop.session_number
        freed_minutes = stop.estimated_minutes or 0

        # 2. Move to deferred pool
        route = await db.get(Route, route_id)
        if route:
            deferred = route.deferred_pool or []
            deferred.append(
                {
                    "achievement_id": str(achievement_id),
                    "skipped_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            route.deferred_pool = deferred

        await db.commit()

        return ReoptimizeResult(
            success=True,
            action="skipped",
            sessions_adjusted=[session_num] if session_num is not None else [],
            session_time_freed=freed_minutes,
        )

    # ------------------------------------------------------------------
    # Method 3: Full Reoptimize
    # ------------------------------------------------------------------

    async def full_reoptimize(
        self,
        character_id: str,
        mode: str,
        db: AsyncSession,
    ) -> Route:
        # Import here to avoid circular dependencies
        from app.router_engine.constraint_filter import ConstraintFilter
        from app.router_engine.dependency_resolver import DependencyResolver
        from app.router_engine.geographic_clusterer import GeographicClusterer
        from app.router_engine.route_assembler import RouteAssembler
        from app.router_engine.seasonal_override import SeasonalOverride
        from app.router_engine.session_structurer import SessionStructurer
        from app.router_engine.zone_graph import ZoneGraph

        # 1. Rate limit check
        cache_key = f"reoptimize:last:{character_id}"
        last_run = await self._redis.get(cache_key)
        if last_run:
            ttl = await self._redis.ttl(cache_key)
            minutes_remaining = max(1, ttl // 60)
            raise RateLimitError(minutes_remaining)

        # 2. Archive existing active route
        await db.execute(
            update(Route)
            .where(
                Route.character_id == character_id,
                Route.status == "active",
            )
            .values(status="archived", archived_at=datetime.now(timezone.utc))
        )

        # 3. Load character
        character = await db.get(Character, character_id)
        if not character:
            raise ValueError(f"Character {character_id} not found")

        # 4. Load uncompleted, non-skipped achievements
        completed_result = await db.execute(
            select(UserAchievementState.achievement_id).where(
                UserAchievementState.character_id == character_id,
                UserAchievementState.completed == True,  # noqa: E712
            )
        )
        completed_ids = {r[0] for r in completed_result.all()}

        # Get skipped achievement IDs from any prior route's deferred pool
        skipped_ids: set[str] = set()
        prior_route_result = await db.execute(
            select(Route)
            .where(
                Route.character_id == character_id,
                Route.status == "archived",
            )
            .order_by(Route.archived_at.desc().nullslast())
            .limit(1)
        )
        prior_route = prior_route_result.scalar_one_or_none()
        if prior_route and prior_route.deferred_pool:
            skipped_ids = {
                entry["achievement_id"] for entry in prior_route.deferred_pool
            }

        # Load all achievements
        all_achs_result = await db.execute(
            select(Achievement).options(
                selectinload(Achievement.guides),
                selectinload(Achievement.zone),
            )
        )
        all_achs = list(all_achs_result.scalars().all())

        # Filter to uncompleted, non-skipped
        eligible_pool = [
            a for a in all_achs
            if a.id not in completed_ids and str(a.id) not in skipped_ids
        ]

        # Load dependencies
        from app.models.achievement import AchievementDependency
        deps_result = await db.execute(select(AchievementDependency))
        all_deps = list(deps_result.scalars().all())

        # Load zones
        from app.models.zone import Zone
        zones_result = await db.execute(select(Zone))
        all_zones = list(zones_result.scalars().all())

        # 5. Run full pipeline
        constraint_filter = ConstraintFilter()
        filter_result = constraint_filter.filter(eligible_pool, character)

        resolver = DependencyResolver()
        resolved_order = resolver.resolve(filter_result.eligible, all_deps)

        zone_graph = ZoneGraph(self._redis)
        await zone_graph.build_graph(all_zones, character)

        clusterer = GeographicClusterer()
        clusters = await clusterer.cluster(resolved_order, character, zone_graph)

        # Load partial progress
        partial_result = await db.execute(
            select(UserAchievementState).where(
                UserAchievementState.character_id == character_id,
                UserAchievementState.completed == False,  # noqa: E712
            )
        )
        partial_states = partial_result.scalars().all()
        partially_completed: dict[str, float] = {}
        for state in partial_states:
            if state.criteria_progress:
                total = sum(v for v in state.criteria_progress.values() if isinstance(v, (int, float)))
                partially_completed[str(state.achievement_id)] = min(total, 99.0)

        structurer = SessionStructurer()
        session_budget = character.user.session_duration_minutes if hasattr(character, "user") and character.user else 120
        sessions = structurer.structure(clusters, session_budget, partially_completed)

        from datetime import date as date_type
        seasonal = SeasonalOverride()
        seasonal_result = seasonal.process(
            all_achievements=filter_result.eligible,
            character=character,
            current_date=date_type.today(),
            completed_ids={str(cid) for cid in completed_ids},
        )

        assembler = RouteAssembler()
        new_route = await assembler.assemble(
            character=character,
            mode=mode,
            filter_result=filter_result,
            resolved_order=resolved_order,
            sessions=sessions,
            seasonal_result=seasonal_result,
            db=db,
        )

        # 6. Set rate limit key
        await self._redis.set(cache_key, "1", ex=REOPTIMIZE_COOLDOWN)

        logger.info(
            "Full reoptimize complete: character=%s, new route=%s",
            character_id,
            new_route.id,
        )
        return new_route

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _confidence_tier(score: float) -> str:
        tiers = [(0.85, "verified"), (0.65, "high"), (0.40, "medium"), (0.20, "low")]
        for threshold, tier in tiers:
            if score >= threshold:
                return tier
        return "research_required"
