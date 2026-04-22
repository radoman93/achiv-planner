"""Seasonal window monitor.

Daily Celery Beat task that:
  1. Detects seasonal events opening within the next 48 hours and triggers
     high-priority re-scrapes so guides are fresh when the event opens.
  2. Detects currently-active events.
  3. Writes a daily report to Redis (`seasonal:daily_report`, TTL 25h) that
     the dashboard and API consume.
  4. Archives old seasonal data by resetting staleness for events that
     ended more than 7 days ago.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.core.redis import get_redis_client
from app.models.achievement import Achievement
from app.pipeline.scrape_coordinator import mark_queued


DAILY_REPORT_KEY = "seasonal:daily_report"
DAILY_REPORT_TTL_SECONDS = 25 * 3600  # 25h — overlaps next run
OPENING_SOON_HOURS = 48
UPCOMING_WINDOW_DAYS = 30
ARCHIVE_AFTER_DAYS = 7
CRITICAL_DAYS_REMAINING = 3


# ---------------------------------------------------------------------------
# Date adjustment (mirrors router_engine/seasonal_override.py logic)
# ---------------------------------------------------------------------------


def _adjust_seasonal_dates(
    event_start: date, event_end: date, current_date: date
) -> tuple[date, date]:
    """Adjust stored seasonal dates to the current year, handling year-wrap."""
    year = current_date.year
    adjusted_start = event_start.replace(year=year)
    adjusted_end = event_end.replace(year=year)

    if event_start.month > event_end.month:
        # Year-wrap (e.g., Dec 15 – Jan 5)
        if current_date.month <= event_end.month + 1:
            adjusted_start = event_start.replace(year=year - 1)
            adjusted_end = event_end.replace(year=year)
        else:
            adjusted_start = event_start.replace(year=year)
            adjusted_end = event_end.replace(year=year + 1)

    if adjusted_end < current_date:
        adjusted_start = event_start.replace(year=year + 1)
        adjusted_end = event_end.replace(year=year + 1)
        if event_start.month > event_end.month:
            adjusted_end = event_end.replace(year=year + 2)

    return adjusted_start, adjusted_end


@dataclass
class EventWindow:
    event_name: str
    opens_at: date
    closes_at: date
    achievements: list[Achievement]


def _group_events(
    achievements: list[Achievement], current_date: date
) -> list[EventWindow]:
    grouped: dict[str, list[Achievement]] = defaultdict(list)
    for a in achievements:
        grouped[a.seasonal_event or "Unknown"].append(a)

    out: list[EventWindow] = []
    for event_name, achs in grouped.items():
        sample = achs[0]
        if not sample.seasonal_start or not sample.seasonal_end:
            continue
        opens_at, closes_at = _adjust_seasonal_dates(
            sample.seasonal_start, sample.seasonal_end, current_date
        )
        out.append(
            EventWindow(
                event_name=event_name,
                opens_at=opens_at,
                closes_at=closes_at,
                achievements=achs,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Core steps
# ---------------------------------------------------------------------------


async def _dispatch_opening_rescrape(
    achievements: list[Achievement],
    db: AsyncSession,
    redis: aioredis.Redis,
) -> int:
    """Force staleness=1.0 and dispatch high-priority scrapes."""
    dispatched = 0
    for ach in achievements:
        ach.staleness_score = 1.0
        celery_app.send_task(
            "pipeline.scrape.wowhead",
            args=[ach.blizzard_id],
            queue="high_priority",
        )
        await mark_queued(redis, ach.blizzard_id)
        dispatched += 1
    await db.commit()
    return dispatched


async def _archive_old(
    events: list[EventWindow], db: AsyncSession, current_date: date
) -> int:
    """For events that ended > 7 days ago, reset their achievements'
    staleness_score to 0 so they drop out of the coordinator's top picks
    until a patch-driven update bumps them again.
    """
    archived = 0
    cutoff = current_date - timedelta(days=ARCHIVE_AFTER_DAYS)
    for window in events:
        if window.closes_at < cutoff:
            for ach in window.achievements:
                if ach.staleness_score > 0.0:
                    ach.staleness_score = 0.0
                    archived += 1
    if archived:
        await db.commit()
    return archived


async def _build_daily_report(
    events: list[EventWindow], current_date: date, now: datetime
) -> dict[str, Any]:
    """Build the Redis-cached daily report.

    Shape matches the phase-6-tasks.md spec: `active_events`, `opening_soon`,
    `upcoming_30_days`.
    """
    active: list[dict[str, Any]] = []
    opening_soon: list[dict[str, Any]] = []
    upcoming_30: list[dict[str, Any]] = []

    upcoming_window = current_date + timedelta(days=UPCOMING_WINDOW_DAYS)

    for window in events:
        is_active = window.opens_at <= current_date <= window.closes_at
        if is_active:
            days_remaining = (window.closes_at - current_date).days
            active.append(
                {
                    "event_name": window.event_name,
                    "opens_at": window.opens_at.isoformat(),
                    "closes_at": window.closes_at.isoformat(),
                    "days_remaining": days_remaining,
                    "achievement_count": len(window.achievements),
                    "is_critical": days_remaining <= CRITICAL_DAYS_REMAINING,
                }
            )
            continue

        # Opens soon? Compare full datetime (midnight at opens_at)
        if window.opens_at > current_date:
            opens_dt = datetime.combine(
                window.opens_at, datetime.min.time(), tzinfo=timezone.utc
            )
            hours_until = (opens_dt - now).total_seconds() / 3600.0
            if 0 <= hours_until <= OPENING_SOON_HOURS:
                opening_soon.append(
                    {
                        "event_name": window.event_name,
                        "opens_at": window.opens_at.isoformat(),
                        "hours_until_open": round(hours_until, 1),
                    }
                )
            if window.opens_at <= upcoming_window:
                upcoming_30.append(
                    {
                        "event_name": window.event_name,
                        "opens_at": window.opens_at.isoformat(),
                        "closes_at": window.closes_at.isoformat(),
                        "days_until_open": (window.opens_at - current_date).days,
                        "achievement_count": len(window.achievements),
                    }
                )

    active.sort(key=lambda e: e["days_remaining"])
    opening_soon.sort(key=lambda e: e["hours_until_open"])
    upcoming_30.sort(key=lambda e: e["days_until_open"])

    return {
        "generated_at": now.isoformat(),
        "active_events": active,
        "opening_soon": opening_soon,
        "upcoming_30_days": upcoming_30,
    }


async def _write_report(redis: aioredis.Redis, report: dict[str, Any]) -> None:
    await redis.set(
        DAILY_REPORT_KEY, json.dumps(report), ex=DAILY_REPORT_TTL_SECONDS
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def run_seasonal_monitor(
    *, current_date: date | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Execute all four steps. Dates are injectable for testing."""
    now = now or datetime.now(timezone.utc)
    current_date = current_date or now.date()

    redis = get_redis_client()
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Achievement).where(Achievement.is_seasonal == True)  # noqa: E712
            )
            seasonal_all = list(result.scalars().all())

            events = _group_events(seasonal_all, current_date)

            # Step 1: opening soon — dispatch rescrapes
            opens_dt_cutoff = now + timedelta(hours=OPENING_SOON_HOURS)
            opening_events = [
                w
                for w in events
                if w.opens_at > current_date
                and datetime.combine(
                    w.opens_at, datetime.min.time(), tzinfo=timezone.utc
                )
                <= opens_dt_cutoff
            ]
            dispatched_total = 0
            for window in opening_events:
                hours_until = (
                    datetime.combine(
                        window.opens_at, datetime.min.time(), tzinfo=timezone.utc
                    )
                    - now
                ).total_seconds() / 3600.0
                logger.info(
                    "seasonal_monitor.event_opening",
                    event_name=window.event_name,
                    hours_until=round(hours_until, 1),
                )
                dispatched_total += await _dispatch_opening_rescrape(
                    window.achievements, db, redis
                )

            # Step 4: archive old
            archived_count = await _archive_old(events, db, current_date)

        # Step 3: daily report (read-only — use separate session to avoid
        # mutating state after earlier commits)
        report = await _build_daily_report(events, current_date, now)
        await _write_report(redis, report)

        summary = {
            "generated_at": report["generated_at"],
            "active_count": len(report["active_events"]),
            "opening_soon_count": len(report["opening_soon"]),
            "upcoming_30_count": len(report["upcoming_30_days"]),
            "rescrapes_dispatched": dispatched_total,
            "archived_count": archived_count,
        }
        logger.info("seasonal_monitor.run_complete", **summary)
        return summary
    finally:
        await redis.aclose()


@celery_app.task(name="pipeline.seasonal.monitor", queue="high_priority")
def monitor_seasonal_windows() -> dict[str, Any]:
    """Celery entry point. Scheduled daily at 06:00 UTC."""
    return asyncio.run(run_seasonal_monitor())
