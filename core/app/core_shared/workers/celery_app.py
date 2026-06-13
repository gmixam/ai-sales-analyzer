"""Celery application for bounded background processing."""

from __future__ import annotations

from celery import Celery

from app.core_shared.config.settings import settings

CALL_PROCESSING_QUEUE = "call_processing"
ANALYSIS_QUEUE = "analysis"
LEGACY_CALLS_QUEUE = "calls"
DEFAULT_QUEUE = "default"
SCHEDULED_REPORTING_TASK = "calls.scan_scheduled_reviewable_reporting"
APP_SERVICE_CALL_PROCESSING = "call_processing"
APP_SERVICE_ANALYSIS = "analysis"
APP_SERVICE_MONOLITH_LEGACY = "monolith_legacy"


def build_worker_queues(app_service: str) -> str:
    """Return the expected Celery queue list for one runtime service identity."""
    normalized = str(app_service or APP_SERVICE_MONOLITH_LEGACY).strip().lower()
    if normalized == APP_SERVICE_CALL_PROCESSING:
        return CALL_PROCESSING_QUEUE
    if normalized == APP_SERVICE_ANALYSIS:
        return f"{ANALYSIS_QUEUE},{DEFAULT_QUEUE}"
    return f"{LEGACY_CALLS_QUEUE},{DEFAULT_QUEUE},{ANALYSIS_QUEUE},{CALL_PROCESSING_QUEUE}"


def scheduled_reporting_queue(app_service: str) -> str:
    """Route scheduled EDO reporting to analysis in split mode, default in legacy."""
    normalized = str(app_service or APP_SERVICE_MONOLITH_LEGACY).strip().lower()
    if normalized == APP_SERVICE_ANALYSIS:
        return ANALYSIS_QUEUE
    return DEFAULT_QUEUE


def build_task_routes(app_service: str) -> dict[str, dict[str, str]]:
    """Build explicit task routes for service-split queue isolation."""
    return {
        SCHEDULED_REPORTING_TASK: {"queue": scheduled_reporting_queue(app_service)},
    }


def create_celery_app() -> Celery:
    """Create the shared Celery application."""
    scheduled_queue = scheduled_reporting_queue(settings.app_service)
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
        task_routes=build_task_routes(settings.app_service),
        beat_schedule={
            "scheduled-reviewable-reporting-scan": {
                "task": SCHEDULED_REPORTING_TASK,
                "schedule": 60.0,
                "options": {"queue": scheduled_queue},
            }
        },
        timezone="UTC",
        enable_utc=True,
    )
    return app


celery_app = create_celery_app()
app = celery_app
