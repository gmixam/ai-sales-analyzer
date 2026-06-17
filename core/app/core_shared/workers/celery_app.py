"""Celery application for bounded background processing."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core_shared.config.settings import settings

CALL_PROCESSING_QUEUE = "call_processing"
ANALYSIS_QUEUE = "analysis"
LEGACY_CALLS_QUEUE = "calls"
DEFAULT_QUEUE = "default"
SCHEDULED_REPORTING_TASK = "calls.scan_scheduled_reviewable_reporting"
SCHEDULED_CALL_PROCESSING_UPSTREAM_TASK = "call_processing.ensure_daily_upstream"
MANAGER_DAILY_SLA_PRECHECK_TASK = "calls.manager_daily_sla_precheck"
MANAGER_DAILY_SLA_HARDCHECK_TASK = "calls.manager_daily_sla_hardcheck"
MANAGER_DAILY_SLA_TIMEZONE = "Asia/Almaty"
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
        SCHEDULED_CALL_PROCESSING_UPSTREAM_TASK: {"queue": CALL_PROCESSING_QUEUE},
        MANAGER_DAILY_SLA_PRECHECK_TASK: {"queue": scheduled_reporting_queue(app_service)},
        MANAGER_DAILY_SLA_HARDCHECK_TASK: {"queue": scheduled_reporting_queue(app_service)},
    }


def build_beat_schedule(
    app_service: str,
    *,
    call_processing_daily_upstream_enabled: bool = False,
    call_processing_daily_upstream_hour: int = 0,
    call_processing_daily_upstream_minute: int = 0,
) -> dict[str, dict[str, object]]:
    """Build service-specific beat entries without crossing split boundaries."""
    normalized = str(app_service or APP_SERVICE_MONOLITH_LEGACY).strip().lower()
    schedule: dict[str, dict[str, object]] = {}

    if normalized in {APP_SERVICE_ANALYSIS, APP_SERVICE_MONOLITH_LEGACY}:
        schedule["scheduled-reviewable-reporting-scan"] = {
            "task": SCHEDULED_REPORTING_TASK,
            "schedule": 60.0,
            "options": {"queue": scheduled_reporting_queue(normalized)},
        }
        schedule["manager_daily_sla_precheck"] = {
            "task": MANAGER_DAILY_SLA_PRECHECK_TASK,
            "schedule": crontab(minute=30, hour=9, day_of_week="1-5"),
            "kwargs": {"report_date": "auto"},
            "options": {"queue": scheduled_reporting_queue(normalized)},
        }
        schedule["manager_daily_sla_hardcheck"] = {
            "task": MANAGER_DAILY_SLA_HARDCHECK_TASK,
            "schedule": crontab(minute=0, hour=10, day_of_week="1-5"),
            "kwargs": {"report_date": "auto"},
            "options": {"queue": scheduled_reporting_queue(normalized)},
        }

    if normalized == APP_SERVICE_CALL_PROCESSING and call_processing_daily_upstream_enabled:
        schedule["scheduled-call-processing-daily-upstream"] = {
            "task": SCHEDULED_CALL_PROCESSING_UPSTREAM_TASK,
            "schedule": crontab(
                minute=call_processing_daily_upstream_minute,
                hour=call_processing_daily_upstream_hour,
            ),
            "options": {"queue": CALL_PROCESSING_QUEUE},
        }

    return schedule


def create_celery_app() -> Celery:
    """Create the shared Celery application."""
    normalized_service = str(settings.app_service or APP_SERVICE_MONOLITH_LEGACY).strip().lower()
    timezone = settings.call_processing_daily_upstream_timezone
    if normalized_service != APP_SERVICE_CALL_PROCESSING:
        timezone = MANAGER_DAILY_SLA_TIMEZONE
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
        beat_schedule=build_beat_schedule(
            settings.app_service,
            call_processing_daily_upstream_enabled=settings.call_processing_daily_upstream_enabled,
            call_processing_daily_upstream_hour=settings.call_processing_daily_upstream_hour,
            call_processing_daily_upstream_minute=settings.call_processing_daily_upstream_minute,
        ),
        timezone=timezone,
        enable_utc=True,
    )
    return app


celery_app = create_celery_app()
app = celery_app
