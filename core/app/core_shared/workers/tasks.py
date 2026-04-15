"""Shared worker tasks."""

from __future__ import annotations

from collections.abc import Sequence

from app.agents.calls.scheduled_reporting import ScheduledReviewableReportingService
from app.core_shared.db.session import get_db
from app.core_shared.workers.celery_app import celery_app


@celery_app.task(name="calls.scan_scheduled_reviewable_reporting")
def scan_scheduled_reviewable_reporting() -> dict:
    """Scan due schedules and create reviewable report batches."""
    with get_db() as db:
        service = ScheduledReviewableReportingService(db=db)
        return service.scan_due_schedules()


def get_registered_tasks() -> Sequence[str]:
    """Return registered bounded worker tasks."""
    return ("calls.scan_scheduled_reviewable_reporting",)
