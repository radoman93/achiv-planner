from celery import Celery
from kombu import Queue

from app.core.celery_beat_schedule import beat_schedule
from app.core.config import settings

celery_app = Celery(
    "wow_optimizer",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_default_queue="normal",
    task_queues=(
        Queue("high_priority"),
        Queue("normal"),
        Queue("llm_enrichment"),
        Queue("sync"),
    ),
    task_routes={
        "pipeline.scrape.*": {"queue": "normal"},
        "pipeline.llm.*": {"queue": "llm_enrichment"},
        "pipeline.sync.*": {"queue": "sync"},
    },
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,
    timezone="UTC",
    enable_utc=True,
    beat_schedule=beat_schedule,
    task_annotations={
        "pipeline.llm.*": {"rate_limit": "50/m"},
    },
)

# Task registration happens via explicit imports in celery_worker.py
