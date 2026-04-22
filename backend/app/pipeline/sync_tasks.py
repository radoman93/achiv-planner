"""Celery tasks for Battle.net achievement sync.

- `pipeline.sync.achievement_sync` — triggered by `POST /api/characters/{id}/sync`
- `pipeline.sync.mark_route_complete` — downstream reoptimization update
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.core.redis import get_redis_client
from app.services.sync_service import (
    SyncError,
    acquire_sync_lock,
    run_character_sync,
)


MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 30  # seconds


async def _run_sync(character_id: str, user_id: str, job_id: str) -> dict[str, Any]:
    redis = get_redis_client()
    try:
        # The lock is normally pre-set by the API handler. Acquire defensively
        # so direct-dispatch callers (tests, admin) still get lock protection;
        # the NX semantics make this a no-op when the lock already exists.
        await acquire_sync_lock(redis, character_id)
        async with AsyncSessionLocal() as db:
            result = await run_character_sync(
                character_id=character_id,
                user_id=user_id,
                job_id=job_id,
                db=db,
                redis=redis,
            )
            return result.to_dict()
    finally:
        await redis.aclose()


@celery_app.task(
    name="pipeline.sync.achievement_sync",
    queue="sync",
    bind=True,
    max_retries=MAX_RETRIES,
    acks_late=True,
)
def sync_character_achievements(
    self, character_id: str, user_id: str
) -> dict[str, Any]:
    """Celery entry point.

    `job_id` is the Celery task id (self.request.id). The same id is used
    by the API handler and the frontend to poll `sync:progress:{job_id}`.
    """
    job_id = self.request.id
    try:
        return asyncio.run(_run_sync(character_id, user_id, job_id))
    except SyncError as exc:
        # Non-retryable failure — progress already written with status=failed.
        logger.warning(
            "sync.task_failed_non_retryable",
            reason=exc.reason,
            character_id=character_id,
        )
        return {"status": "failed", "reason": exc.reason, "message": str(exc)}
    except Exception as exc:
        # Retry with exponential backoff for transient failures (Blizzard 5xx,
        # rate limit, Redis/DB blips).
        retries = self.request.retries or 0
        if retries >= MAX_RETRIES:
            logger.error(
                "sync.task_failed_max_retries",
                character_id=character_id,
                error=str(exc),
            )
            raise
        countdown = RETRY_BACKOFF_BASE * (2 ** retries)
        logger.warning(
            "sync.task_retry",
            character_id=character_id,
            retry=retries + 1,
            countdown=countdown,
            error=str(exc),
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _run_mark_complete(route_id: str, achievement_id: str) -> dict[str, Any]:
    from app.router_engine.reoptimizer import Reoptimizer

    redis = get_redis_client()
    try:
        async with AsyncSessionLocal() as db:
            reoptimizer = Reoptimizer(redis)
            result = await reoptimizer.mark_complete(route_id, achievement_id, db)
            return {
                "success": result.success,
                "newly_unblocked": result.newly_unblocked,
                "sessions_adjusted": result.sessions_adjusted,
            }
    finally:
        await redis.aclose()


@celery_app.task(
    name="pipeline.sync.mark_route_complete",
    queue="sync",
    acks_late=True,
)
def mark_route_complete(route_id: str, achievement_id: str) -> dict[str, Any]:
    """Async downstream update for a newly-completed achievement on a route.

    Dispatched by the sync task when Blizzard reports a completion that was
    previously incomplete on an active route for the character.
    """
    try:
        return asyncio.run(_run_mark_complete(route_id, achievement_id))
    except Exception as exc:
        logger.warning(
            "sync.mark_route_complete_failed",
            route_id=route_id,
            achievement_id=achievement_id,
            error=str(exc),
        )
        return {"success": False, "error": str(exc)}
