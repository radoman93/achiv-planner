from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.celery_app import celery_app

router = APIRouter()


@router.post("/trigger/full")
async def trigger_full_pipeline():
    result = celery_app.send_task("pipeline.orchestrator.run_full_pipeline")
    return JSONResponse({"task_id": result.id, "status": "queued"})


@router.post("/trigger/skeleton")
async def trigger_skeleton_pass():
    result = celery_app.send_task("pipeline.orchestrator.blizzard_skeleton_pass")
    return JSONResponse({"task_id": result.id, "status": "queued"})


@router.post("/trigger/scrape")
async def trigger_scrape_coordinator():
    result = celery_app.send_task("pipeline.orchestrator.scrape_coordinator")
    return JSONResponse({"task_id": result.id, "status": "queued"})


@router.post("/clear-queue")
async def clear_queue():
    """Purge all pending Celery tasks."""
    celery_app.control.purge()
    return JSONResponse({"status": "queue_cleared"})


@router.post("/clear-and-rescrape")
async def clear_and_rescrape():
    """Purge all pending Celery tasks and re-trigger Wowhead scraping."""
    celery_app.control.purge()
    result = celery_app.send_task("pipeline.orchestrator.scrape_coordinator")
    return JSONResponse({"task_id": result.id, "status": "queue_cleared_and_rescrape_triggered"})


@router.post("/trigger/enrich-samples")
async def trigger_enrich_samples():
    """Directly trigger LLM enrichment for the sample achievement IDs."""
    from sqlalchemy import select as sa_select
    from app.core.database import AsyncSessionLocal
    from app.models.achievement import Achievement
    from app.core.config import settings

    sample_blizzard_ids = [int(x.strip()) for x in (settings.LLM_SAMPLE_IDS or "").split(",") if x.strip()]
    dispatched = []

    async with AsyncSessionLocal() as session:
        for bid in sample_blizzard_ids:
            row = (await session.execute(
                sa_select(Achievement.id).where(Achievement.blizzard_id == bid)
            )).scalar_one_or_none()
            if row:
                celery_app.send_task(
                    "pipeline.llm.enrich",
                    args=[str(row)],
                    queue="llm_enrichment",
                )
                dispatched.append({"blizzard_id": bid, "uuid": str(row)})

    return JSONResponse({"dispatched": dispatched, "count": len(dispatched)})


@router.post("/trigger/enrich-all")
async def trigger_enrich_all():
    """Dispatch LLM enrichment for all achievements that don't have a guide yet."""
    from sqlalchemy import select as sa_select
    from app.core.database import AsyncSessionLocal
    from app.models.achievement import Achievement
    from app.models.content import Guide

    async with AsyncSessionLocal() as session:
        # Get achievements that have been scraped but have no llm_enriched guide
        enriched_ids = sa_select(Guide.achievement_id).where(Guide.source_type == "llm_enriched")
        rows = (await session.execute(
            sa_select(Achievement.id)
            .where(Achievement.last_scraped_at.isnot(None))
            .where(Achievement.id.notin_(enriched_ids))
        )).scalars().all()

    dispatched = 0
    for ach_id in rows:
        celery_app.send_task(
            "pipeline.llm.enrich",
            args=[str(ach_id)],
            queue="llm_enrichment",
        )
        dispatched += 1

    return JSONResponse({
        "dispatched": dispatched,
        "status": "enrichment_triggered",
    })


@router.post("/reset-llm-budget")
async def reset_llm_budget():
    """Reset the LLM spend counters in Redis (use after switching providers)."""
    from app.core.redis import get_redis_client
    redis = get_redis_client()
    try:
        old_total = await redis.get("llm:spend:total_usd_cents")
        await redis.delete("llm:spend:total_usd_cents")
        await redis.delete("llm:spend:thresholds_hit")
        return JSONResponse({
            "status": "budget_reset",
            "old_total_usd": int(old_total or 0) / 10_000,
        })
    finally:
        await redis.aclose()


@router.post("/trigger/rescrape-failed")
async def trigger_rescrape_failed():
    """Dispatch Wowhead scrapes for achievements that were never successfully scraped."""
    from sqlalchemy import select as sa_select
    from app.core.database import AsyncSessionLocal
    from app.models.achievement import Achievement

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            sa_select(Achievement.blizzard_id)
            .where(Achievement.last_scraped_at.is_(None))
            .where(Achievement.is_legacy == False)
        )).scalars().all()

    dispatched = 0
    for bid in rows:
        celery_app.send_task(
            "pipeline.scrape.wowhead",
            args=[bid],
            queue="normal",
        )
        dispatched += 1

    return JSONResponse({
        "dispatched": dispatched,
        "total_unscraped": len(rows),
        "status": "rescrape_triggered",
    })


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    result = celery_app.AsyncResult(task_id)
    return JSONResponse({
        "task_id": task_id,
        "status": result.status,
        "result": str(result.result) if result.ready() else None,
    })
