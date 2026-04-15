from celery.schedules import crontab

beat_schedule = {
    "blizzard-skeleton-pass": {
        "task": "pipeline.orchestrator.blizzard_skeleton_pass",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "normal"},
    },
    "scrape-coordinator": {
        "task": "pipeline.orchestrator.scrape_coordinator",
        "schedule": crontab(minute=0, hour="*/6"),
        "options": {"queue": "normal"},
    },
    "patch-monitor": {
        "task": "pipeline.orchestrator.patch_monitor",
        "schedule": crontab(hour=4, minute=0),
        "options": {"queue": "normal"},
    },
    "seasonal-window-monitor": {
        "task": "pipeline.orchestrator.seasonal_window_monitor",
        "schedule": crontab(hour=6, minute=0),
        "options": {"queue": "normal"},
    },
}
