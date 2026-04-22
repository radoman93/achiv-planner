"""Achievement sync service — diff Blizzard response against DB state.

Used by `pipeline.sync.achievement_sync` Celery task to synchronise a
character's achievement completion state with Blizzard's authoritative data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.achievement import Achievement
from app.models.progress import UserAchievementState
from app.models.route import Route
from app.models.user import Character, User
from app.services import battlenet


SYNC_LOCK_TTL_SECONDS = 900  # 15 min — real syncs finish in <1min; short TTL bounds crash recovery time
SYNC_PROGRESS_TTL_SECONDS = 3600  # 1 hour (after completion for late polling)
BATCH_SIZE = 100
PROGRESS_UPDATE_EVERY = 50


@dataclass
class SyncResult:
    job_id: str
    character_id: str
    total: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_unknown: int = 0
    newly_completed_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "character_id": self.character_id,
            "total": self.total,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped_unknown": self.skipped_unknown,
            "newly_completed_count": len(self.newly_completed_ids),
            "newly_completed_ids": self.newly_completed_ids,
        }


class SyncError(Exception):
    """Raised when a sync cannot proceed for a non-retryable reason."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class DuplicateSyncError(SyncError):
    """Raised when a sync is already in progress for the same character."""

    def __init__(self) -> None:
        super().__init__("duplicate_sync", "Sync already in progress")


# ---------------------------------------------------------------------------
# Redis lock + progress helpers
# ---------------------------------------------------------------------------


def _lock_key(character_id: str | UUID) -> str:
    return f"sync:lock:{character_id}"


def _progress_key(job_id: str) -> str:
    return f"sync:progress:{job_id}"


async def acquire_sync_lock(redis: aioredis.Redis, character_id: str | UUID) -> bool:
    """Try to acquire an exclusive sync lock. Returns True if acquired."""
    acquired = await redis.set(
        _lock_key(character_id), "1", ex=SYNC_LOCK_TTL_SECONDS, nx=True
    )
    return bool(acquired)


async def release_sync_lock(redis: aioredis.Redis, character_id: str | UUID) -> None:
    await redis.delete(_lock_key(character_id))


async def write_progress(
    redis: aioredis.Redis,
    job_id: str,
    payload: dict[str, Any],
    *,
    ttl: int | None = None,
) -> None:
    await redis.set(
        _progress_key(job_id),
        json.dumps(payload),
        ex=ttl if ttl is not None else SYNC_PROGRESS_TTL_SECONDS,
    )


async def enqueue_character_sync(
    character_id: str | UUID,
    user_id: str | UUID,
    redis: aioredis.Redis,
) -> tuple[bool, str | None]:
    """Acquire the sync lock and queue the Celery sync task for a character.

    Returns (acquired, job_id). If another sync is already running for the
    same character, the lock acquisition fails and returns (False, None).
    """
    acquired = await acquire_sync_lock(redis, character_id)
    if not acquired:
        return False, None

    from app.core.celery_app import celery_app

    task = celery_app.send_task(
        "pipeline.sync.achievement_sync",
        args=[str(character_id), str(user_id)],
        queue="sync",
    )

    await write_progress(
        redis,
        task.id,
        {"status": "queued", "processed": 0, "total": 0, "percent": 0},
    )
    return True, task.id


# ---------------------------------------------------------------------------
# Blizzard response parsing
# ---------------------------------------------------------------------------


def _parse_blizzard_achievements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise a Blizzard character achievements response.

    The Blizzard profile achievements endpoint returns:
    {
      "total_quantity": N,
      "total_points": N,
      "achievements": [
        {
          "id": 12345,
          "achievement": {...},
          "criteria": {...},
          "completed_timestamp": 1715817600000  # ms since epoch, optional
        }
      ]
    }
    """
    out: list[dict[str, Any]] = []
    for entry in payload.get("achievements") or []:
        blizzard_id = entry.get("id") or (entry.get("achievement") or {}).get("id")
        if not blizzard_id:
            continue
        ts = entry.get("completed_timestamp")
        completed_at: datetime | None = None
        if ts:
            # Blizzard returns ms since epoch
            completed_at = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        criteria_progress: dict[str, Any] = {}
        crit = entry.get("criteria")
        if crit:
            # Criteria can be nested as a tree; flatten any immediate children
            # and record their id + amount.
            for child in crit.get("child_criteria") or []:
                cid = child.get("id")
                if cid is None:
                    continue
                criteria_progress[str(cid)] = child.get("amount", 0)
            # Top-level criterion with amount
            if crit.get("id") is not None and "amount" in crit:
                criteria_progress[str(crit["id"])] = crit["amount"]
        out.append(
            {
                "blizzard_id": int(blizzard_id),
                "completed_at": completed_at,
                "completed": completed_at is not None,
                "criteria_progress": criteria_progress,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Diff + write logic
# ---------------------------------------------------------------------------


async def _load_existing_state(
    db: AsyncSession, character_id: UUID
) -> dict[UUID, UserAchievementState]:
    """Return {achievement_id: state_row} for all existing rows on this character."""
    result = await db.execute(
        select(UserAchievementState).where(
            UserAchievementState.character_id == character_id
        )
    )
    return {row.achievement_id: row for row in result.scalars().all()}


async def _load_achievement_index(db: AsyncSession) -> dict[int, UUID]:
    """Return {blizzard_id: achievement_uuid} for all non-legacy achievements."""
    result = await db.execute(
        select(Achievement.blizzard_id, Achievement.id)
    )
    return {row[0]: row[1] for row in result.all()}


async def _recalculate_character_stats(
    db: AsyncSession, character_id: UUID
) -> tuple[float, dict[str, Any]]:
    """Return (completion_pct, stats_by_expansion)."""
    total_q = await db.execute(select(func.count(Achievement.id)))
    total = total_q.scalar() or 0

    completed_q = await db.execute(
        select(func.count(UserAchievementState.id)).where(
            UserAchievementState.character_id == character_id,
            UserAchievementState.completed == True,  # noqa: E712
        )
    )
    completed = completed_q.scalar() or 0
    pct = round(completed / total * 100, 2) if total > 0 else 0.0

    by_exp_result = await db.execute(
        select(
            Achievement.expansion,
            func.count(Achievement.id).label("total"),
            func.count(UserAchievementState.id).filter(
                UserAchievementState.completed == True  # noqa: E712
            ).label("completed"),
        )
        .outerjoin(
            UserAchievementState,
            (UserAchievementState.achievement_id == Achievement.id)
            & (UserAchievementState.character_id == character_id),
        )
        .where(Achievement.expansion.isnot(None))
        .group_by(Achievement.expansion)
    )
    by_expansion: dict[str, Any] = {}
    for expansion, total_e, completed_e in by_exp_result.all():
        if not expansion:
            continue
        by_expansion[expansion] = {
            "total": int(total_e or 0),
            "completed": int(completed_e or 0),
        }
    return pct, by_expansion


async def _find_active_route_id(
    db: AsyncSession, character_id: UUID
) -> UUID | None:
    result = await db.execute(
        select(Route.id).where(
            Route.character_id == character_id,
            Route.status == "active",
        ).limit(1)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public entry point called by the Celery task
# ---------------------------------------------------------------------------


async def run_character_sync(
    character_id: str,
    user_id: str,
    job_id: str,
    db: AsyncSession,
    redis: aioredis.Redis,
) -> SyncResult:
    """Execute the full sync flow for one character.

    Caller is responsible for instantiating db session + redis client.
    Caller must have already acquired the sync lock — this function will
    not double-acquire, but it WILL release the lock in its own finally.
    """

    char_uuid = UUID(character_id)
    user_uuid = UUID(user_id)

    result = SyncResult(job_id=job_id, character_id=character_id)

    started_at = datetime.now(timezone.utc).isoformat()

    try:
        # --- Pre-flight: load character + user --------------------------------
        char = await db.get(Character, char_uuid)
        if char is None or char.user_id != user_uuid:
            raise SyncError("character_not_found", "Character not found")
        user = await db.get(User, user_uuid)
        if user is None:
            raise SyncError("user_not_found", "User not found")
        if not user.battlenet_token:
            raise SyncError("token_missing", "Battle.net token not linked")

        # Refresh token if near expiry
        try:
            await battlenet.refresh_battlenet_token(user, db)
        except Exception as exc:
            logger.warning("sync.token_refresh_failed", error=str(exc))
            raise SyncError("token_expired", "Battle.net token could not be refreshed")

        region = char.region or user.battlenet_region or "us"

        # --- Fetch from Blizzard ---------------------------------------------
        try:
            blizzard_payload = await battlenet.fetch_character_achievements(
                char, region, user.battlenet_token
            )
        except Exception as exc:
            import httpx

            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
                # Character exists on the Battle.net account list but has no
                # public achievement profile (low-level alt, deleted, recently
                # transferred, etc.). Treat as a successful empty sync so the
                # user can still generate a route — we just won't have any
                # completion data for this character.
                logger.warning(
                    "sync.character_no_public_profile",
                    character_id=character_id,
                    realm=char.realm,
                    name=char.name,
                )
                char.last_synced_at = datetime.now(timezone.utc)
                await db.commit()
                completed_at_iso = datetime.now(timezone.utc).isoformat()
                await write_progress(
                    redis,
                    job_id,
                    {
                        "status": "completed",
                        "processed": 0,
                        "total": 0,
                        "percent": 100,
                        "started_at": started_at,
                        "completed_at": completed_at_iso,
                        "newly_completed_count": 0,
                        "newly_completed_ids": [],
                        "inserted": 0,
                        "updated": 0,
                        "skipped_unknown": 0,
                        "completion_pct": 0.0,
                        "note": "no_public_profile",
                    },
                    ttl=SYNC_PROGRESS_TTL_SECONDS,
                )
                return result
            # Let Celery handle retry for transient errors (rate limits, 5xx).
            raise

        entries = _parse_blizzard_achievements(blizzard_payload)
        total = len(entries)
        result.total = total

        await write_progress(
            redis,
            job_id,
            {
                "status": "in_progress",
                "processed": 0,
                "total": total,
                "percent": 0,
                "started_at": started_at,
            },
            ttl=SYNC_PROGRESS_TTL_SECONDS,
        )

        # --- Load state snapshots --------------------------------------------
        achievement_index = await _load_achievement_index(db)
        existing_by_ach_id = await _load_existing_state(db, char_uuid)
        uuid_to_blizzard: dict[UUID, int] = {
            ach_id: bid for bid, ach_id in achievement_index.items()
        }
        existing_by_blizzard_id: dict[int, UserAchievementState] = {
            bid: state
            for ach_uuid, state in existing_by_ach_id.items()
            if (bid := uuid_to_blizzard.get(ach_uuid)) is not None
        }

        # --- Process entries -------------------------------------------------
        newly_completed_achievement_ids: list[UUID] = []
        pending_flush = 0
        processed = 0

        for entry in entries:
            blizzard_id = entry["blizzard_id"]
            ach_uuid = achievement_index.get(blizzard_id)
            if ach_uuid is None:
                result.skipped_unknown += 1
                logger.info(
                    "sync.unknown_blizzard_id",
                    blizzard_id=blizzard_id,
                    character_id=character_id,
                )
                processed += 1
                if processed % PROGRESS_UPDATE_EVERY == 0:
                    await write_progress(
                        redis,
                        job_id,
                        {
                            "status": "in_progress",
                            "processed": processed,
                            "total": total,
                            "percent": int(processed / total * 100) if total else 0,
                            "started_at": started_at,
                        },
                    )
                continue

            state = existing_by_blizzard_id.get(blizzard_id)
            completed_now = entry["completed"]
            completed_at = entry["completed_at"]
            criteria_progress = entry["criteria_progress"] or None

            if state is None:
                state = UserAchievementState(
                    character_id=char_uuid,
                    achievement_id=ach_uuid,
                    completed=completed_now,
                    completed_at=completed_at,
                    criteria_progress=criteria_progress,
                )
                db.add(state)
                result.inserted += 1
                if completed_now:
                    newly_completed_achievement_ids.append(ach_uuid)
                pending_flush += 1
            else:
                changed = False
                if completed_now and not state.completed:
                    state.completed = True
                    state.completed_at = completed_at
                    newly_completed_achievement_ids.append(ach_uuid)
                    changed = True
                elif completed_now and state.completed and completed_at and state.completed_at != completed_at:
                    state.completed_at = completed_at
                    changed = True
                if criteria_progress and state.criteria_progress != criteria_progress:
                    state.criteria_progress = criteria_progress
                    changed = True
                if changed:
                    result.updated += 1
                    pending_flush += 1

            processed += 1
            if pending_flush >= BATCH_SIZE:
                await db.flush()
                pending_flush = 0

            if processed % PROGRESS_UPDATE_EVERY == 0:
                await write_progress(
                    redis,
                    job_id,
                    {
                        "status": "in_progress",
                        "processed": processed,
                        "total": total,
                        "percent": int(processed / total * 100) if total else 0,
                        "started_at": started_at,
                    },
                )

        if pending_flush:
            await db.flush()

        # --- Update character record ----------------------------------------
        pct, by_expansion = await _recalculate_character_stats(db, char_uuid)
        # char.achievement_completion_pct / stats_cache don't exist as columns
        # on the current schema. Prefer last_synced_at, which does.
        char.last_synced_at = datetime.now(timezone.utc)

        await db.commit()

        # Refresh the materialized view so dashboard reads reflect the new
        # completion state without recalculating on every request.
        try:
            from sqlalchemy import text as sa_text

            await db.execute(sa_text("SELECT refresh_character_stats(:cid)"), {"cid": str(char_uuid)})
            await db.commit()
        except Exception as exc:
            # Refresh is best-effort — the view may not exist in test DBs
            # or may be locked by a concurrent refresh. Log and continue.
            logger.warning("sync.materialized_view_refresh_failed", error=str(exc))
            await db.rollback()

        # --- Dispatch reoptimize for newly-completed achievements ----------
        if newly_completed_achievement_ids:
            active_route_id = await _find_active_route_id(db, char_uuid)
            if active_route_id is not None:
                from app.core.celery_app import celery_app

                for ach_uuid in newly_completed_achievement_ids:
                    celery_app.send_task(
                        "pipeline.sync.mark_route_complete",
                        args=[str(active_route_id), str(ach_uuid)],
                        queue="sync",
                    )

        result.newly_completed_ids = [str(x) for x in newly_completed_achievement_ids]

        completed_at_iso = datetime.now(timezone.utc).isoformat()
        await write_progress(
            redis,
            job_id,
            {
                "status": "completed",
                "processed": total,
                "total": total,
                "percent": 100,
                "started_at": started_at,
                "completed_at": completed_at_iso,
                "newly_completed_count": len(result.newly_completed_ids),
                "newly_completed_ids": result.newly_completed_ids,
                "inserted": result.inserted,
                "updated": result.updated,
                "skipped_unknown": result.skipped_unknown,
                "completion_pct": pct,
            },
            ttl=SYNC_PROGRESS_TTL_SECONDS,
        )

        logger.info(
            "sync.completed",
            character_id=character_id,
            total=total,
            inserted=result.inserted,
            updated=result.updated,
            skipped_unknown=result.skipped_unknown,
            newly_completed=len(result.newly_completed_ids),
        )
        return result

    except SyncError as exc:
        await write_progress(
            redis,
            job_id,
            {
                "status": "failed",
                "reason": exc.reason,
                "error": str(exc),
                "started_at": started_at,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
            ttl=SYNC_PROGRESS_TTL_SECONDS,
        )
        logger.warning("sync.failed", reason=exc.reason, character_id=character_id)
        raise
    finally:
        await release_sync_lock(redis, character_id)
