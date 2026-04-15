from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import logger
from app.models.achievement import Achievement
from app.models.pipeline import PipelineRun
from app.scraper import raw_storage
from app.scraper.blizzard_client import BlizzardClient


async def _skeleton_pass(session: AsyncSession) -> dict[str, int]:
    counts = {"new": 0, "updated": 0, "unchanged": 0, "legacy": 0}
    async with BlizzardClient() as client:
        try:
            index = await client.get_all_achievements()
        except Exception as exc:
            logger.exception("orchestrator.skeleton_pass_failed", error=str(exc))
            return counts

    api_ids: set[int] = set()
    existing_q = await session.execute(select(Achievement))
    existing_by_id: dict[int, Achievement] = {a.blizzard_id: a for a in existing_q.scalars().all()}

    async with BlizzardClient() as client:
        for entry in index:
            bid = entry.get("id")
            if bid is None:
                continue
            api_ids.add(bid)

            # Fetch detail for new/changed achievements only when minimal fields aren't enough.
            existing = existing_by_id.get(bid)
            name = entry.get("name")
            if existing is None:
                # Need more data — fetch detail
                try:
                    detail = await client.get_achievement_detail(bid)
                except Exception:
                    detail = {"id": bid, "name": name}
                category = (detail.get("category") or {}).get("name") if isinstance(detail.get("category"), dict) else None
                ach = Achievement(
                    id=uuid4(),
                    blizzard_id=bid,
                    name=detail.get("name") or name or f"Achievement {bid}",
                    description=detail.get("description"),
                    points=int(detail.get("points") or 0),
                    category=category,
                    staleness_score=1.0,
                )
                session.add(ach)
                counts["new"] += 1
            else:
                changed = False
                if name and existing.name != name:
                    existing.name = name
                    changed = True
                if changed:
                    existing.staleness_score = 1.0
                    counts["updated"] += 1
                    logger.info("orchestrator.achievement_changed", blizzard_id=bid)
                else:
                    counts["unchanged"] += 1

    # Legacy detection
    for bid, ach in existing_by_id.items():
        if bid not in api_ids:
            if not ach.is_legacy:
                ach.is_legacy = True
                counts["legacy"] += 1

    await session.commit()
    logger.info("orchestrator.skeleton_pass_complete", **counts)
    return counts


async def _dispatch_scrapes(
    session: AsyncSession, force_rescrape: bool
) -> dict[str, Any]:
    q = await session.execute(select(Achievement).where(Achievement.is_legacy == False))  # noqa: E712
    achievements = list(q.scalars().all())
    dispatched: list[str] = []
    skipped = 0
    for ach in achievements:
        ach_id_str = str(ach.blizzard_id)
        if not force_rescrape and raw_storage.raw_exists("wowhead", ach_id_str, max_age_hours=720):
            skipped += 1
            continue

        queue_name = (
            "high_priority" if (ach.staleness_score or 0.0) > 0.8 else "normal"
        )
        task = celery_app.send_task(
            "pipeline.scrape.wowhead",
            args=[ach.blizzard_id],
            queue=queue_name,
        )
        dispatched.append(task.id)
    return {"dispatched": len(dispatched), "skipped": skipped, "total": len(achievements)}


async def dispatch_bulk_enrichment(achievement_blizzard_ids: list[int]) -> dict[str, Any]:
    """Route bulk enrichment through Batch API when size warrants; else per-achievement tasks."""
    ids = [str(i) for i in achievement_blizzard_ids]
    if len(ids) >= settings.LLM_BATCH_MIN_SIZE:
        # Resolve blizzard_ids -> achievement UUIDs for the batch path
        async with AsyncSessionLocal() as session:
            q = await session.execute(
                select(Achievement).where(Achievement.blizzard_id.in_(achievement_blizzard_ids))
            )
            uuid_ids = [str(a.id) for a in q.scalars().all()]
        celery_app.send_task(
            "pipeline.llm.enrich_batch", args=[uuid_ids], queue="llm_enrichment"
        )
        return {"mode": "batch", "count": len(uuid_ids)}

    async with AsyncSessionLocal() as session:
        q = await session.execute(
            select(Achievement).where(Achievement.blizzard_id.in_(achievement_blizzard_ids))
        )
        for ach in q.scalars().all():
            celery_app.send_task(
                "pipeline.llm.enrich", args=[str(ach.id)], queue="llm_enrichment"
            )
    return {"mode": "individual", "count": len(ids)}


async def _run_pipeline(force_rescrape: bool) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        run = PipelineRun(
            id=uuid4(),
            started_at=started_at,
            achievements_processed=0,
            achievements_errored=0,
            phases_completed={"phases": []},
        )
        session.add(run)
        await session.commit()
        run_id = run.id

        # Phase 1: skeleton
        skeleton_counts = await _skeleton_pass(session)

        async with AsyncSessionLocal() as s2:
            run_q = await s2.execute(select(PipelineRun).where(PipelineRun.id == run_id))
            run_db = run_q.scalar_one()
            run_db.phases_completed = {"phases": ["skeleton"], "skeleton": skeleton_counts}
            await s2.commit()

        # Phases 2-4: per-achievement scraping (async dispatch — chain triggers downstream)
        async with AsyncSessionLocal() as s3:
            dispatch_result = await _dispatch_scrapes(s3, force_rescrape)

        completed_at = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as s4:
            run_q = await s4.execute(select(PipelineRun).where(PipelineRun.id == run_id))
            run_db = run_q.scalar_one()
            phases = run_db.phases_completed or {"phases": []}
            phases["phases"].append("dispatch")
            phases["dispatch"] = dispatch_result
            run_db.phases_completed = phases
            run_db.completed_at = completed_at
            run_db.achievements_processed = dispatch_result.get("dispatched", 0)
            await s4.commit()

    return {
        "run_id": str(run_id),
        "skeleton": skeleton_counts,
        "dispatch": dispatch_result,
    }


@celery_app.task(name="pipeline.orchestrator.run_full_pipeline", queue="high_priority")
def run_full_pipeline(force_rescrape: bool = False) -> dict[str, Any]:
    return asyncio.run(_run_pipeline(force_rescrape))


# Aliases for the beat schedule task names
@celery_app.task(name="pipeline.orchestrator.blizzard_skeleton_pass", queue="normal")
def blizzard_skeleton_pass() -> dict[str, int]:
    async def _run() -> dict[str, int]:
        async with AsyncSessionLocal() as session:
            return await _skeleton_pass(session)

    return asyncio.run(_run())


@celery_app.task(name="pipeline.orchestrator.scrape_coordinator", queue="normal")
def scrape_coordinator() -> dict[str, Any]:
    async def _run() -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            return await _dispatch_scrapes(session, force_rescrape=False)

    return asyncio.run(_run())


@celery_app.task(name="pipeline.orchestrator.patch_monitor", queue="high_priority")
def patch_monitor_alias() -> dict[str, Any]:
    from app.pipeline.patch_monitor import monitor_patches_async

    return asyncio.run(monitor_patches_async())


@celery_app.task(name="pipeline.orchestrator.seasonal_window_monitor", queue="normal")
def seasonal_window_monitor() -> dict[str, Any]:
    # Placeholder implemented in Phase 6.
    logger.info("orchestrator.seasonal_window_monitor_stub")
    return {"status": "not_implemented"}
