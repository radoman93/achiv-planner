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


@router.post("/clear-and-rescrape")
async def clear_and_rescrape():
    """Purge all pending Celery tasks and re-trigger Wowhead scraping."""
    celery_app.control.purge()
    result = celery_app.send_task("pipeline.orchestrator.scrape_coordinator")
    return JSONResponse({"task_id": result.id, "status": "queue_cleared_and_rescrape_triggered"})


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    result = celery_app.AsyncResult(task_id)
    return JSONResponse({
        "task_id": task_id,
        "status": result.status,
        "result": str(result.result) if result.ready() else None,
    })
