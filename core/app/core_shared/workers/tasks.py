"""Shared worker tasks."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agents.call_processing import (
    CallProcessingService,
    EnsureMode,
    ProcessingScope,
    RequiredArtifactKind,
)
from app.agents.calls.scheduled_reporting import ScheduledReviewableReportingService
from app.core_shared.config.settings import settings
from app.core_shared.db.session import get_db
from app.core_shared.workers.celery_app import (
    SCHEDULED_CALL_PROCESSING_UPSTREAM_TASK,
    SCHEDULED_REPORTING_TASK,
    celery_app,
)

DAILY_UPSTREAM_REQUIRED_ARTIFACTS: tuple[RequiredArtifactKind, ...] = (
    RequiredArtifactKind.TRANSCRIPT,
    RequiredArtifactKind.TRANSCRIPT_SEGMENTS,
    RequiredArtifactKind.LLM1_FIRST_PASS,
)


@celery_app.task(name="calls.scan_scheduled_reviewable_reporting")
def scan_scheduled_reviewable_reporting() -> dict:
    """Scan due schedules and create reviewable report batches."""
    with get_db() as db:
        service = ScheduledReviewableReportingService(db=db)
        return service.scan_due_schedules()


def _parse_report_date(value: str | None, timezone_name: str) -> date:
    if value:
        return date.fromisoformat(value)
    try:
        tzinfo = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown CALL_PROCESSING_DAILY_UPSTREAM_TIMEZONE: {timezone_name}") from exc
    return datetime.now(tzinfo).date() - timedelta(days=1)


def _daily_upstream_scope(target_date: date) -> ProcessingScope:
    payload: dict[str, Any] = {
        "department_id": settings.call_processing_daily_upstream_department_id,
        "manager_ids": settings.call_processing_daily_upstream_manager_ids,
        "date_from": target_date,
        "date_to": target_date,
        "source": "onlinepbx",
    }
    if settings.call_processing_daily_upstream_min_duration_sec is not None:
        payload["min_duration_sec"] = settings.call_processing_daily_upstream_min_duration_sec
    return ProcessingScope.model_validate(payload)


@celery_app.task(name=SCHEDULED_CALL_PROCESSING_UPSTREAM_TASK)
def ensure_daily_call_processing_upstream(
    *,
    report_date: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Prepare previous-day upstream artifacts inside the call-processing service."""
    started_at = datetime.now(UTC)
    base_payload: dict[str, Any] = {
        "task": SCHEDULED_CALL_PROCESSING_UPSTREAM_TASK,
        "started_at": started_at.isoformat(),
        "app_service": settings.app_service,
        "enabled": settings.call_processing_daily_upstream_enabled,
        "billable_pipeline_started": False,
    }

    if settings.app_service != "call_processing":
        return {
            **base_payload,
            "task_status": "skipped",
            "reason": "wrong_app_service",
            "expected_app_service": "call_processing",
        }
    if not settings.call_processing_daily_upstream_enabled and not dry_run:
        return {
            **base_payload,
            "task_status": "skipped",
            "reason": "disabled",
        }
    if not settings.call_processing_daily_upstream_department_id.strip():
        return {
            **base_payload,
            "task_status": "skipped",
            "reason": "department_scope_not_configured",
        }
    if not settings.call_processing_daily_upstream_manager_ids:
        return {
            **base_payload,
            "task_status": "skipped",
            "reason": "manager_scope_not_configured",
        }
    if not dry_run and settings.call_processing_daily_upstream_provider_call_budget <= 0:
        return {
            **base_payload,
            "task_status": "skipped",
            "reason": "provider_call_budget_not_configured",
        }

    try:
        target_date = _parse_report_date(report_date, settings.call_processing_daily_upstream_timezone)
        scope = _daily_upstream_scope(target_date)
        mode = EnsureMode.DRY_RUN if dry_run else EnsureMode.ENSURE
        with get_db() as db:
            service = CallProcessingService(db, requested_by="scheduled_call_processing_upstream")
            response = service.ensure(
                scope,
                list(DAILY_UPSTREAM_REQUIRED_ARTIFACTS),
                mode=mode,
                requested_by="scheduled_call_processing_upstream",
                provider_call_budget=settings.call_processing_daily_upstream_provider_call_budget,
            )
    except Exception as exc:  # noqa: BLE001 - task must return operator-visible failure payload.
        return {
            **base_payload,
            "task_status": "failed",
            "finished_at": datetime.now(UTC).isoformat(),
            "error": {
                "class": exc.__class__.__name__,
                "message": str(exc),
            },
        }

    response_payload = response.model_dump(mode="json")
    return {
        **base_payload,
        "task_status": "completed",
        "finished_at": datetime.now(UTC).isoformat(),
        "report_date": target_date.isoformat(),
        "mode": mode.value,
        "scope": scope.model_dump(mode="json", exclude_none=True),
        "required_artifacts": [item.value for item in DAILY_UPSTREAM_REQUIRED_ARTIFACTS],
        "billable_pipeline_started": not dry_run,
        "ensure_response": response_payload,
        "status": response_payload.get("status"),
        "planned": response_payload.get("planned", {}),
        "quota": response_payload.get("quota", {}),
        "costs": response_payload.get("costs", {}),
    }


def get_registered_tasks() -> Sequence[str]:
    """Return registered bounded worker tasks."""
    return (SCHEDULED_REPORTING_TASK, SCHEDULED_CALL_PROCESSING_UPSTREAM_TASK)
