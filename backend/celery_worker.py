from app.core.celery_app import celery_app

celery_app.autodiscover_tasks(["app.pipeline", "app.scraper", "app.services"])

if __name__ == "__main__":
    celery_app.start()
