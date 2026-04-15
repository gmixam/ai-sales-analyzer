"""Celery application for bounded background processing."""

from __future__ import annotations

from celery import Celery

from app.core_shared.config.settings import settings


def create_celery_app() -> Celery:
    """Create the shared Celery application."""
    app = Celery(
        "ai_sales_analyzer",
        broker=str(settings.redis_url),
        backend=str(settings.redis_url),
        include=["app.core_shared.workers.tasks"],
    )
    app.conf.update(
        task_default_queue="default",
        task_default_exchange="default",
        task_default_routing_key="default",
        beat_schedule={
            "scheduled-reviewable-reporting-scan": {
                "task": "calls.scan_scheduled_reviewable_reporting",
                "schedule": 60.0,
                "options": {"queue": "default"},
            }
        },
        timezone="UTC",
        enable_utc=True,
    )
    return app


celery_app = create_celery_app()
app = celery_app
