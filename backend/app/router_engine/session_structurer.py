"""Session structurer — splits clustered route into time-budgeted play sessions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.models.achievement import Achievement
from app.models.zone import Zone
from app.router_engine.geographic_clusterer import ZoneCluster

logger = logging.getLogger(__name__)


@dataclass
class RouteStop:
    achievement: Achievement
    zone: Zone | None
    estimated_minutes: int
    session_number: int
    sequence_order: int


@dataclass
class Session:
    session_number: int
    clusters: list[ZoneCluster] = field(default_factory=list)
    stops: list[RouteStop] = field(default_factory=list)
    estimated_minutes: int = 0
    primary_zone: Zone | None = None
    entry_zone: Zone | None = None
    is_well_connected: bool = False


class SessionStructurer:
    """Splits an ordered list of zone clusters into time-budgeted play sessions."""

    def structure(
        self,
        clusters: list[ZoneCluster],
        session_budget_minutes: int,
        partially_completed: dict[str, float] | None = None,
    ) -> list[Session]:
        if not clusters:
            return []

        partially_completed = partially_completed or {}

        # Step 1: Promote partially completed achievements
        self._promote_partial(clusters, partially_completed)

        # Step 2: Accumulate into sessions
        sessions = self._accumulate_sessions(clusters, session_budget_minutes)

        # Step 3: Session opener optimization
        self._optimize_openers(sessions)

        # Step 4: Flatten to stops
        self._flatten_stops(sessions)

        logger.info(
            "Session structurer: %d sessions, %d total minutes, budget=%d",
            len(sessions),
            sum(s.estimated_minutes for s in sessions),
            session_budget_minutes,
        )
        return sessions

    # ------------------------------------------------------------------
    # Step 1: Promote partially completed achievements
    # ------------------------------------------------------------------

    def _promote_partial(
        self,
        clusters: list[ZoneCluster],
        partially_completed: dict[str, float],
    ) -> None:
        if not partially_completed:
            return

        for cl in clusters:
            promoted = []
            rest = []
            for ach in cl.achievements:
                aid = str(ach.id)
                if aid in partially_completed and partially_completed[aid] > 0:
                    promoted.append(ach)
                else:
                    rest.append(ach)

            if promoted:
                logger.debug("Promoted %d partially completed achievements", len(promoted))
                cl.achievements = promoted + rest

    # ------------------------------------------------------------------
    # Step 2: Accumulate into sessions
    # ------------------------------------------------------------------

    def _accumulate_sessions(
        self,
        clusters: list[ZoneCluster],
        budget: int,
    ) -> list[Session]:
        sessions: list[Session] = []
        current = Session(session_number=1)
        session_minutes = 0

        for cl in clusters:
            cluster_cost = cl.estimated_minutes + int(cl.entry_travel_cost)

            # Case: cluster fits in current session
            if session_minutes + cluster_cost <= budget:
                current.clusters.append(cl)
                session_minutes += cluster_cost
                continue

            # Case: cluster alone exceeds budget — must split
            if cluster_cost > budget and not current.clusters:
                self._split_cluster_into_sessions(
                    cl, budget, sessions, current, session_minutes
                )
                # Start fresh after split
                current = Session(session_number=len(sessions) + 1)
                session_minutes = 0
                continue

            # Case: cluster alone exceeds budget but current session has content
            if cluster_cost > budget and current.clusters:
                # Close current session
                current.estimated_minutes = session_minutes
                sessions.append(current)
                # Split the oversized cluster into new sessions
                current = Session(session_number=len(sessions) + 1)
                session_minutes = 0
                self._split_cluster_into_sessions(
                    cl, budget, sessions, current, session_minutes
                )
                current = Session(session_number=len(sessions) + 1)
                session_minutes = 0
                continue

            # Case: would exceed budget — close current session, start new
            current.estimated_minutes = session_minutes
            sessions.append(current)
            current = Session(session_number=len(sessions) + 1)
            current.clusters.append(cl)
            session_minutes = cluster_cost

        # Don't forget the last session
        if current.clusters:
            current.estimated_minutes = session_minutes
            sessions.append(current)

        # Assign session metadata
        for session in sessions:
            self._compute_session_metadata(session)

        return sessions

    def _split_cluster_into_sessions(
        self,
        cluster: ZoneCluster,
        budget: int,
        sessions: list[Session],
        current: Session,
        session_minutes: int,
    ) -> None:
        """Split an oversized cluster across sessions, one achievement at a time."""
        entry_cost = int(cluster.entry_travel_cost)
        remaining_achs = list(cluster.achievements)

        # Account for entry cost only on first sub-cluster
        first = True
        for ach in remaining_achs:
            ach_cost = (ach.estimated_minutes or 0) + (entry_cost if first else 0)
            first = False

            if session_minutes + ach_cost > budget and current.clusters:
                current.estimated_minutes = session_minutes
                sessions.append(current)
                current_num = len(sessions) + 1
                current.__init__(session_number=current_num)  # type: ignore[misc]
                session_minutes = 0

            # Add achievement as a mini-cluster
            mini = ZoneCluster(
                zone=cluster.zone,
                achievements=[ach],
                estimated_minutes=ach.estimated_minutes or 0,
                entry_travel_cost=0.0,
                exit_zone_id=cluster.exit_zone_id,
            )
            current.clusters.append(mini)
            session_minutes += ach_cost

        current.estimated_minutes = session_minutes
        sessions.append(current)

    # ------------------------------------------------------------------
    # Step 3: Session opener optimization
    # ------------------------------------------------------------------

    def _optimize_openers(self, sessions: list[Session]) -> None:
        """If a session's first cluster isn't well-connected, try swapping with a nearby one."""
        for session in sessions:
            if len(session.clusters) < 2:
                continue

            first = session.clusters[0]
            if first.zone and first.zone.has_portal:
                continue  # Already well-connected

            # Find a well-connected cluster that could swap with minimal overhead
            for i in range(1, min(4, len(session.clusters))):
                candidate = session.clusters[i]
                if candidate.zone and candidate.zone.has_portal:
                    swap_overhead = candidate.entry_travel_cost
                    if swap_overhead < 5:
                        session.clusters[0], session.clusters[i] = (
                            session.clusters[i],
                            session.clusters[0],
                        )
                        break

    # ------------------------------------------------------------------
    # Step 4: Flatten to stops
    # ------------------------------------------------------------------

    def _flatten_stops(self, sessions: list[Session]) -> None:
        for session in sessions:
            seq = 0
            for cl in session.clusters:
                for ach in cl.achievements:
                    session.stops.append(
                        RouteStop(
                            achievement=ach,
                            zone=cl.zone,
                            estimated_minutes=ach.estimated_minutes or 0,
                            session_number=session.session_number,
                            sequence_order=seq,
                        )
                    )
                    seq += 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_session_metadata(self, session: Session) -> None:
        """Set primary_zone, entry_zone, is_well_connected for a session."""
        if not session.clusters:
            return

        # Primary zone = zone with most achievements
        zone_counts: dict[str, tuple[int, Zone | None]] = {}
        for cl in session.clusters:
            if cl.zone:
                zid = str(cl.zone.id) if cl.zone.id else "unknown"
                count, _ = zone_counts.get(zid, (0, None))
                zone_counts[zid] = (count + len(cl.achievements), cl.zone)

        if zone_counts:
            best_zid = max(zone_counts, key=lambda k: zone_counts[k][0])
            session.primary_zone = zone_counts[best_zid][1]

        # Entry zone = first cluster's zone
        session.entry_zone = session.clusters[0].zone
        session.is_well_connected = bool(
            session.entry_zone and session.entry_zone.has_portal
        )
