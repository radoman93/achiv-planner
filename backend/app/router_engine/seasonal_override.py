"""Seasonal override layer — identifies active/upcoming seasonal achievements and builds urgency-sorted blocks."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.models.achievement import Achievement
from app.models.user import Character
from app.router_engine.geographic_clusterer import ZoneCluster

logger = logging.getLogger(__name__)


@dataclass
class SeasonalStop:
    achievement: Achievement
    event_name: str
    days_remaining: int
    urgency: str  # 'critical' (<= 3 days), 'high' (4-7 days), 'normal' (> 7 days)
    zone_cluster: ZoneCluster | None = None


@dataclass
class UpcomingEvent:
    event_name: str
    opens_at: date
    closes_at: date
    days_until_open: int
    achievement_count: int
    user_completion_pct: float


@dataclass
class CalendarEntry:
    event_name: str
    opens_at: date
    closes_at: date
    achievements: list[Achievement] = field(default_factory=list)
    completed_count: int = 0
    total_count: int = 0


@dataclass
class SeasonalResult:
    active_block: list[SeasonalStop] = field(default_factory=list)
    upcoming_events: list[UpcomingEvent] = field(default_factory=list)
    calendar_projection: list[CalendarEntry] = field(default_factory=list)


class SeasonalOverride:
    """Detects active and upcoming seasonal events, builds urgency-sorted achievement blocks."""

    def process(
        self,
        all_achievements: list[Achievement],
        character: Character,
        current_date: date,
        lookahead_days: int = 60,
        completed_ids: set[str] | None = None,
    ) -> SeasonalResult:
        completed_ids = completed_ids or set()
        seasonal = [a for a in all_achievements if a.is_seasonal]

        if not seasonal:
            return SeasonalResult()

        # Group by event
        events: dict[str, list[Achievement]] = defaultdict(list)
        for ach in seasonal:
            events[ach.seasonal_event or "Unknown"].append(ach)

        active_stops: list[SeasonalStop] = []
        upcoming: list[UpcomingEvent] = []
        calendar: list[CalendarEntry] = []

        lookahead_end = current_date + timedelta(days=lookahead_days)

        for event_name, achs in events.items():
            # Use the first achievement's dates as representative for the event
            sample = achs[0]
            event_start = sample.seasonal_start
            event_end = sample.seasonal_end

            if not event_start or not event_end:
                continue

            # Handle year-wrap: adjust dates to current year context
            adjusted_start, adjusted_end = self._adjust_seasonal_dates(
                event_start, event_end, current_date
            )

            is_active = adjusted_start <= current_date <= adjusted_end
            days_remaining = (adjusted_end - current_date).days if is_active else 0

            # Count completion
            total = len(achs)
            completed_count = sum(1 for a in achs if str(a.id) in completed_ids)

            if is_active:
                # Build active stops
                for ach in achs:
                    if str(ach.id) in completed_ids:
                        continue
                    urgency = self._classify_urgency(days_remaining)
                    active_stops.append(
                        SeasonalStop(
                            achievement=ach,
                            event_name=event_name,
                            days_remaining=days_remaining,
                            urgency=urgency,
                        )
                    )

                # Calendar entry for active event
                calendar.append(
                    CalendarEntry(
                        event_name=event_name,
                        opens_at=adjusted_start,
                        closes_at=adjusted_end,
                        achievements=achs,
                        completed_count=completed_count,
                        total_count=total,
                    )
                )

            elif adjusted_start > current_date and adjusted_start <= lookahead_end:
                # Upcoming event
                days_until = (adjusted_start - current_date).days
                pct = (completed_count / total * 100) if total > 0 else 0.0
                upcoming.append(
                    UpcomingEvent(
                        event_name=event_name,
                        opens_at=adjusted_start,
                        closes_at=adjusted_end,
                        days_until_open=days_until,
                        achievement_count=total,
                        user_completion_pct=pct,
                    )
                )
                calendar.append(
                    CalendarEntry(
                        event_name=event_name,
                        opens_at=adjusted_start,
                        closes_at=adjusted_end,
                        achievements=achs,
                        completed_count=completed_count,
                        total_count=total,
                    )
                )

        # Sort active by days_remaining ascending (most urgent first)
        active_stops.sort(key=lambda s: s.days_remaining)

        # Cluster active seasonal achievements geographically
        self._cluster_active(active_stops)

        # Sort upcoming by opens_at
        upcoming.sort(key=lambda e: e.opens_at)
        calendar.sort(key=lambda c: c.opens_at)

        logger.info(
            "Seasonal override: %d active stops, %d upcoming events, %d calendar entries",
            len(active_stops),
            len(upcoming),
            len(calendar),
        )

        return SeasonalResult(
            active_block=active_stops,
            upcoming_events=upcoming,
            calendar_projection=calendar,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _adjust_seasonal_dates(
        self, event_start: date, event_end: date, current_date: date
    ) -> tuple[date, date]:
        """Adjust stored seasonal dates to the current year, handling year-wrap events."""
        year = current_date.year

        adjusted_start = event_start.replace(year=year)
        adjusted_end = event_end.replace(year=year)

        # Year-wrap detection: start month > end month (e.g., Dec 15 - Jan 5)
        if event_start.month > event_end.month:
            # If we're in the early part (Jan side), start was last year
            if current_date.month <= event_end.month + 1:
                adjusted_start = event_start.replace(year=year - 1)
                adjusted_end = event_end.replace(year=year)
            else:
                adjusted_start = event_start.replace(year=year)
                adjusted_end = event_end.replace(year=year + 1)

        # If the event already passed this year and lookahead is needed,
        # check next year's occurrence
        if adjusted_end < current_date:
            adjusted_start = event_start.replace(year=year + 1)
            adjusted_end = event_end.replace(year=year + 1)
            if event_start.month > event_end.month:
                adjusted_end = event_end.replace(year=year + 2)

        return adjusted_start, adjusted_end

    def _classify_urgency(self, days_remaining: int) -> str:
        if days_remaining <= 3:
            return "critical"
        elif days_remaining <= 7:
            return "high"
        return "normal"

    def _cluster_active(self, stops: list[SeasonalStop]) -> None:
        """Mini geographic clustering — group active seasonal stops by zone."""
        zone_groups: dict[str, list[SeasonalStop]] = defaultdict(list)
        for stop in stops:
            zid = str(stop.achievement.zone_id) if stop.achievement.zone_id else "unknown"
            zone_groups[zid].append(stop)

        for zid, group in zone_groups.items():
            if zid == "unknown":
                continue
            # Build a mini cluster for this zone group
            zone_obj = group[0].achievement.zone if hasattr(group[0].achievement, "zone") else None
            cluster = ZoneCluster(
                zone=zone_obj,
                achievements=[s.achievement for s in group],
                estimated_minutes=sum(s.achievement.estimated_minutes or 0 for s in group),
                exit_zone_id=zid,
            )
            for stop in group:
                stop.zone_cluster = cluster
