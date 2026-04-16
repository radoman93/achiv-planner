from app.core.celery_app import celery_app

# Explicitly import task modules so @celery_app.task decorators register
import app.pipeline.orchestrator  # noqa: F401
import app.pipeline.comment_processor  # noqa: F401
import app.pipeline.llm_enrichment  # noqa: F401
import app.pipeline.patch_monitor  # noqa: F401
import app.scraper.wowhead_scraper  # noqa: F401
import app.scraper.spiders.orchestrator  # noqa: F401

if __name__ == "__main__":
    celery_app.start()
