"""Scheduled scrape coordinator.

Runs every 6 hours via Celery Beat. Selects the top 50 most stale
achievements, dispatches them to the scrape pipeline, and tracks in-flight
work in a Redis set to prevent double-queuing.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.core.redis import get_redis_client
from app.models.achievement import Achievement


QUEUED_SET_KEY = "scrape:queued"
QUEUED_TTL_SECONDS = 24 * 3600  # 24h per-entry — auto-cleans stuck tasks
LAST_RUN_KEY = "scrape:coordinator:last_run"
RUN_LOG_KEY = "scrape:coordinator:log"
RUN_LOG_MAX = 100

BATCH_SIZE = 50
HIGH_PRIORITY_THRESHOLD = 0.8

# Staleness scoring constants
STALENESS_BASE_WINDOW_DAYS = 30.0
STALENESS_PATCH_RECENT_DAYS = 7
STALENESS_SEASONAL_WINDOW_DAYS = 14
STALENESS_PATCH_MULTIPLIER = 1.5
STALENESS_SEASONAL_MULTIPLIER = 1.3
STALENESS_LOW_CONFIDENCE_MULTIPLIER = 1.2
STALENESS_LOW_CONFIDENCE_THRESHOLD = 0.4


def compute_staleness_score(
    last_scraped_at: datetime | None,
    *,
    now: datetime | None = None,
    patch_flagged_at: datetime | None = None,
    seasonal_opens_at: datetime | None = None,
    confidence_score: float = 1.0,
) -> float:
    """Compute a staleness score in [0.0, 1.0].

    Base: days_since_scrape / 30 (capped at 1.0). Multiplied by:
    - 1.5 if a patch event flagged the achievement within the last 7 days
    - 1.3 if a seasonal event opens within 14 days
    - 1.2 if current confidence_score < 0.4

    Result is capped at 1.0.
    """
    now = now or datetime.now(timezone.utc)
    if last_scraped_at is None:
        base = 1.0
    else:
        days = max(0.0, (now - last_scraped_at).total_seconds() / 86400.0)
        base = min(days / STALENESS_BASE_WINDOW_DAYS, 1.0)

    score = base
    if patch_flagged_at is not None:
        delta_days = (now - patch_flagged_at).total_seconds() / 86400.0
        if 0 <= delta_days <= STALENESS_PATCH_RECENT_DAYS:
            score *= STALENESS_PATCH_MULTIPLIER
    if seasonal_opens_at is not None:
        delta_days = (seasonal_opens_at - now).total_seconds() / 86400.0
        if 0 <= delta_days <= STALENESS_SEASONAL_WINDOW_DAYS:
            score *= STALENESS_SEASONAL_MULTIPLIER
    if confidence_score < STALENESS_LOW_CONFIDENCE_THRESHOLD:
        score *= STALENESS_LOW_CONFIDENCE_MULTIPLIER

    return min(score, 1.0)


# ---------------------------------------------------------------------------
# Public Redis helpers — called from the wowhead scrape task on completion
# ---------------------------------------------------------------------------


async def mark_queued(redis: aioredis.Redis, blizzard_id: int) -> None:
    """Add an achievement blizzard_id to the queued set with per-member TTL.

    Redis sets don't support per-member TTL natively, so we use a separate
    key `scrape:queued:{id}` with TTL 24h, and the membership check reads
    it via EXISTS. This pattern gives us O(1) check + auto-expiration.
    """
    key = f"{QUEUED_SET_KEY}:{blizzard_id}"
    await redis.set(key, "1", ex=QUEUED_TTL_SECONDS)


async def unmark_queued(redis: aioredis.Redis, blizzard_id: int) -> None:
    await redis.delete(f"{QUEUED_SET_KEY}:{blizzard_id}")


async def is_queued(redis: aioredis.Redis, blizzard_id: int) -> bool:
    exists = await redis.exists(f"{QUEUED_SET_KEY}:{blizzard_id}")
    return bool(exists)


# ---------------------------------------------------------------------------
# Coordinator core
# ---------------------------------------------------------------------------


async def _select_stale(
    db: AsyncSession, redis: aioredis.Redis, limit: int
) -> tuple[list[tuple[int, float]], int]:
    """Return (selected, skipped_already_queued).

    Selects up to `limit` (blizzard_id, staleness_score) pairs ordered by
    descending staleness, skipping any id already marked in-flight in Redis.
    Over-fetches to account for in-flight exclusions.
    """
    result = await db.execute(
        select(Achievement.blizzard_id, Achievement.staleness_score)
        .where(Achievement.is_legacy == False)  # noqa: E712
        .order_by(Achievement.staleness_score.desc())
        .limit(limit * 3)
    )
    candidates = [(int(bid), float(score or 0.0)) for bid, score in result.all()]

    selected: list[tuple[int, float]] = []
    skipped_already_queued = 0
    for bid, score in candidates:
        if await is_queued(redis, bid):
            skipped_already_queued += 1
            continue
        selected.append((bid, score))
        if len(selected) >= limit:
            break

    return selected, skipped_already_queued


async def _dispatch(
    redis: aioredis.Redis, selected: list[tuple[int, float]]
) -> tuple[int, int]:
    """Dispatch scrape tasks. Returns (high_priority_count, normal_count)."""
    high_count = 0
    normal_count = 0
    for bid, score in selected:
        queue_name = "high_priority" if score > HIGH_PRIORITY_THRESHOLD else "normal"
        celery_app.send_task(
            "pipeline.scrape.wowhead",
            args=[bid],
            queue=queue_name,
        )
        await mark_queued(redis, bid)
        if queue_name == "high_priority":
            high_count += 1
        else:
            normal_count += 1
    return high_count, normal_count


async def _record_run(redis: aioredis.Redis, entry: dict[str, Any]) -> None:
    payload = json.dumps(entry)
    await redis.set(LAST_RUN_KEY, payload)
    # Keep a rolling log of the last RUN_LOG_MAX runs.
    pipe = redis.pipeline()
    pipe.lpush(RUN_LOG_KEY, payload)
    pipe.ltrim(RUN_LOG_KEY, 0, RUN_LOG_MAX - 1)
    await pipe.execute()


async def run_coordinator() -> dict[str, Any]:
    redis = get_redis_client()
    try:
        async with AsyncSessionLocal() as db:
            selected, skipped = await _select_stale(db, redis, BATCH_SIZE)
            high, normal = await _dispatch(redis, selected)

        entry = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "dispatched_count": high + normal,
            "high_priority_count": high,
            "normal_count": normal,
            "skipped_already_queued": skipped,
        }
        await _record_run(redis, entry)
        logger.info("scrape_coordinator.run_complete", **entry)
        return entry
    finally:
        await redis.aclose()


@celery_app.task(name="pipeline.scrape.coordinate", queue="high_priority")
def coordinate_scrapes() -> dict[str, Any]:
    """Celery entry point. Scheduled by Celery Beat every 6 hours."""
    return asyncio.run(run_coordinator())
