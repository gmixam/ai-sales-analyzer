"""Bounded scheduled reviewable reporting before pilot."""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.calls.delivery import CallsDelivery
from app.agents.calls.reporting import (
    CallsManualReportingOrchestrator,
    REPORTING_ALLOWED_MODES,
    ReportRunFilters,
    parse_call_started_at,
    render_report_email,
    resolve_report_preset,
)
from app.agents.calls.run_alerts import send_run_alert
from app.core_shared.config.settings import settings
from app.core_shared.db.models import (
    Department,
    Interaction,
    Manager,
    ReportingSchedule,
    ScheduledReportBatch,
    ScheduledReportDraft,
)
from app.core_shared.exceptions import ASAError, DeliveryError

SCHEDULED_REVIEWABLE_OPERATING_MODE = "scheduled_reviewable_reporting"
SCHEDULED_REVIEWABLE_ALLOWED_RECURRENCE = ("daily", "weekly")
SCHEDULED_REVIEWABLE_ALLOWED_PERIOD_RULES = (
    "previous_day",
    "last_7_days",
    "previous_week",
)
SCHEDULED_REVIEWABLE_BATCH_STATUSES = (
    "planned",
    "queued",
    "running",
    "review_required",
    "approved_for_delivery",
    "delivered",
    "failed",
    "paused",
)
SCHEDULED_REVIEWABLE_BATCH_ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "planned": ("queued", "failed", "paused"),
    "queued": ("running", "failed", "paused"),
    "running": ("review_required", "delivered", "failed", "paused"),
    "review_required": ("approved_for_delivery", "failed", "paused"),
    "approved_for_delivery": ("delivered", "failed"),
    "delivered": (),
    "failed": (),
    "paused": ("queued", "failed"),
}
SCHEDULED_REVIEWABLE_DEFAULT_EDITOR = "operator_ui"
SCHEDULED_ANALYSIS_LOOKBACK_DAYS_ENV = "SCHEDULED_ANALYSIS_LOOKBACK_DAYS"
SCHEDULED_ANALYSIS_DEFAULT_LOOKBACK_DAYS = 7
SCHEDULED_MANAGER_DAILY_OPEN_BATCH_STATUSES = (
    "planned",
    "queued",
    "running",
    "review_required",
    "paused",
)
SCHEDULED_MANAGER_DAILY_REPORTED_BATCH_STATUSES = (
    "review_required",
    "approved_for_delivery",
    "delivered",
)
SCHEDULED_MANAGER_DAILY_REPORTED_DRAFT_STATUSES = (
    "review_required",
    "delivered",
)
SCHEDULED_MANAGER_DAILY_IDEMPOTENCY_LOCK_NAMESPACE = "scheduled_manager_daily_v1"
MANAGER_DAILY_SLA_DEADLINE_TIME = time(10, 0)
MANAGER_DAILY_UPSTREAM_RETRY_HOURS = (5, 6, 7, 8, 9)
MANAGER_DAILY_UPSTREAM_PENDING_REASONS = {
    "waiting_upstream",
    "upstream_partial",
    "upstream_blocked",
    "upstream_missing",
    "upstream_not_ready",
}
MANAGER_DAILY_UPSTREAM_DEADLINE_REASON = "upstream_not_ready_before_deadline"
MANAGER_DAILY_MANAGER_SCOPE_NOT_CONFIGURED = "manager_daily_manager_scope_not_configured"
MANAGER_DAILY_EDITABLE_BLOCKS = (
    "top_summary",
    "focus_wording",
    "key_problem_wording",
    "recommendations_wording",
    "final_manager_note",
)
ROP_WEEKLY_EDITABLE_BLOCKS = (
    "executive_summary",
    "team_risks_wording",
    "rop_tasks_wording",
    "final_managerial_commentary",
)


@dataclass(slots=True)
class SchedulePeriod:
    """Resolved report period for one scheduled run."""

    date_from: str
    date_to: str


@dataclass(slots=True)
class ScheduledManagerDaySelection:
    """Candidate-selection diagnostics for one scheduled manager-day scan."""

    manager_id: str
    candidate_dates: list[str]
    selected_report_date: str | None
    skipped_empty_dates: list[str]
    skipped_already_reported_dates: list[str]
    skipped_already_reported_details: list[dict[str, Any]]
    skipped_not_ready_dates: list[str]
    selection_reason: str
    scheduled_timezone: str
    scan_started_at: str
    lookback_days: int

    def to_dict(self) -> dict[str, Any]:
        """Return the stable JSON shape expected by operators/tests."""
        return {
            "timezone": self.scheduled_timezone,
            "scheduled_timezone": self.scheduled_timezone,
            "scan_started_at": self.scan_started_at,
            "lookback_days": self.lookback_days,
            "manager_id": self.manager_id,
            "candidate_dates": list(self.candidate_dates),
            "selected_report_date": self.selected_report_date,
            "skipped_empty_dates": list(self.skipped_empty_dates),
            "skipped_already_reported_dates": list(self.skipped_already_reported_dates),
            "skipped_already_reported_details": [
                dict(item) for item in self.skipped_already_reported_details
            ],
            "skipped_not_ready_dates": list(self.skipped_not_ready_dates),
            "selection_reason": self.selection_reason,
        }

    def to_observability(self) -> dict[str, Any]:
        """Return the stable JSON shape expected by operators/tests."""
        return self.to_dict()


def _coerce_uuid_list(values: list[str]) -> list[str]:
    """Normalize a list of UUID-like strings."""
    normalized: list[str] = []
    for value in values:
        candidate = str(value).strip()
        if not candidate:
            continue
        UUID(candidate)
        if candidate not in normalized:
            normalized.append(candidate)
    return normalized


def _parse_schedule_time(value: str) -> time:
    """Parse `HH:MM` or `HH:MM:SS` into time."""
    candidate = str(value).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(candidate, fmt).time()
        except ValueError:
            continue
    raise ASAError("start_time must use HH:MM format.")


def _validate_timezone(value: str) -> str:
    """Validate IANA timezone name."""
    candidate = str(value).strip()
    if not candidate:
        raise ASAError("timezone is required for scheduled reviewable reporting.")
    try:
        ZoneInfo(candidate)
    except Exception as exc:  # pragma: no cover - stdlib zoneinfo edge
        raise ASAError(f"Unsupported timezone '{candidate}'.") from exc
    return candidate


def _scheduled_analysis_lookback_days() -> int:
    """Return the configured analysis lookback with a production-safe default."""
    raw = str(os.environ.get(SCHEDULED_ANALYSIS_LOOKBACK_DAYS_ENV) or "").strip()
    if not raw:
        return SCHEDULED_ANALYSIS_DEFAULT_LOOKBACK_DAYS
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ASAError(f"{SCHEDULED_ANALYSIS_LOOKBACK_DAYS_ENV} must be a positive integer.") from exc
    if parsed < 1:
        raise ASAError(f"{SCHEDULED_ANALYSIS_LOOKBACK_DAYS_ENV} must be a positive integer.")
    return parsed


def _schedule_requires_review(schedule: ReportingSchedule) -> bool:
    """Return whether the schedule should stop at operator review."""
    return bool(getattr(schedule, "review_required", True))


def _is_manager_daily_preset(value: Any) -> bool:
    """Return True when a schedule/preset value targets manager_daily reports."""
    preset = getattr(value, "preset", value)
    return str(preset or "").strip() == "manager_daily"


def _manager_daily_auto_delivery_enabled(schedule: ReportingSchedule) -> bool:
    """Return True for production manager_daily delivery schedules."""
    return (
        _is_manager_daily_preset(schedule)
        and not _schedule_requires_review(schedule)
        and bool(getattr(schedule, "business_email_enabled", False))
    )


def _manager_daily_sla_deadline(*, planned_for: datetime, timezone_name: str) -> datetime:
    """Return the manager_daily hard SLA deadline in UTC."""
    local_planned = planned_for.astimezone(ZoneInfo(timezone_name))
    local_deadline = datetime.combine(
        local_planned.date(),
        MANAGER_DAILY_SLA_DEADLINE_TIME,
        tzinfo=ZoneInfo(timezone_name),
    )
    return local_deadline.astimezone(UTC)


def _manager_daily_next_upstream_retry_at(
    *,
    planned_for: datetime,
    now_utc: datetime,
    timezone_name: str,
) -> datetime | None:
    """Return the next hourly upstream readiness checkpoint before the deadline."""
    timezone = ZoneInfo(timezone_name)
    local_day = planned_for.astimezone(timezone).date()
    for hour in MANAGER_DAILY_UPSTREAM_RETRY_HOURS:
        candidate = datetime.combine(local_day, time(hour, 0), tzinfo=timezone).astimezone(UTC)
        if candidate > now_utc:
            return candidate
    return None


def _isoformat_utc(value: datetime | None) -> str | None:
    """Serialize datetimes for JSON observability."""
    return value.astimezone(UTC).isoformat() if value is not None else None


def _candidate_dates_for_lookback(*, local_planned: datetime, rule: str, lookback_days: int) -> list[str]:
    """Return oldest-to-newest candidate dates ending at the scheduled target day."""
    scheduled_period = _compute_report_period(rule=rule, local_run_at=local_planned)
    end = date.fromisoformat(scheduled_period.date_to)
    start = end - timedelta(days=lookback_days - 1)
    return [(start + timedelta(days=offset)).isoformat() for offset in range(lookback_days)]


def _combine_local_datetime(*, start_date: date, start_time: str, timezone_name: str) -> datetime:
    """Return the local scheduled datetime with timezone."""
    parsed_time = _parse_schedule_time(start_time)
    return datetime.combine(start_date, parsed_time, tzinfo=ZoneInfo(timezone_name))


def _next_local_occurrence(
    *,
    start_date: date,
    start_time: str,
    timezone_name: str,
    recurrence_type: str,
    now_utc: datetime,
) -> datetime:
    """Compute the next local occurrence at or after now."""
    base_local = _combine_local_datetime(
        start_date=start_date,
        start_time=start_time,
        timezone_name=timezone_name,
    )
    now_local = now_utc.astimezone(ZoneInfo(timezone_name))
    if recurrence_type not in set(SCHEDULED_REVIEWABLE_ALLOWED_RECURRENCE):
        raise ASAError(
            f"Unsupported recurrence_type '{recurrence_type}'. "
            f"Supported values: {', '.join(sorted(SCHEDULED_REVIEWABLE_ALLOWED_RECURRENCE))}."
        )
    current = base_local
    step = timedelta(days=1 if recurrence_type == "daily" else 7)
    while current < now_local:
        current += step
    return current


def _compute_report_period(*, rule: str, local_run_at: datetime) -> SchedulePeriod:
    """Resolve one bounded report period rule from the local scheduled run time."""
    local_day = local_run_at.date()
    if rule == "previous_day":
        target = local_day - timedelta(days=1)
        return SchedulePeriod(date_from=target.isoformat(), date_to=target.isoformat())
    if rule == "last_7_days":
        end = local_day - timedelta(days=1)
        start = end - timedelta(days=6)
        return SchedulePeriod(date_from=start.isoformat(), date_to=end.isoformat())
    if rule == "previous_week":
        current_week_monday = local_day - timedelta(days=local_day.weekday())
        previous_week_monday = current_week_monday - timedelta(days=7)
        previous_week_sunday = previous_week_monday + timedelta(days=6)
        return SchedulePeriod(
            date_from=previous_week_monday.isoformat(),
            date_to=previous_week_sunday.isoformat(),
        )
    raise ASAError(
        f"Unsupported report_period_rule '{rule}'. "
        f"Supported values: {', '.join(sorted(SCHEDULED_REVIEWABLE_ALLOWED_PERIOD_RULES))}."
    )


def _editable_block_keys(*, preset: str) -> tuple[str, ...]:
    """Return the allowed editable block names for one preset."""
    if preset == "manager_daily":
        return MANAGER_DAILY_EDITABLE_BLOCKS
    if preset == "rop_weekly":
        return ROP_WEEKLY_EDITABLE_BLOCKS
    raise ASAError(f"Unsupported preset '{preset}' for scheduled reviewable reporting.")


def _ensure_allowed_blocks(*, preset: str, edited_blocks: dict[str, str]) -> None:
    """Reject any attempt to edit non-whitelisted blocks."""
    allowed = set(_editable_block_keys(preset=preset))
    invalid = [key for key in edited_blocks if key not in allowed]
    if invalid:
        raise ASAError(
            "scheduled_reviewable_reporting.edit_block_forbidden: "
            + ", ".join(sorted(invalid))
        )


def extract_editable_blocks(*, preset: str, payload: dict[str, Any]) -> dict[str, str]:
    """Extract the operator-editable business-facing blocks from a generated payload."""
    if preset == "manager_daily":
        return {
            "top_summary": str(((payload.get("narrative_day_conclusion") or {}).get("text")) or ""),
            "focus_wording": str(((payload.get("main_focus_for_tomorrow") or {}).get("text")) or ""),
            "key_problem_wording": str(((payload.get("key_problem_of_day") or {}).get("description")) or ""),
            "recommendations_wording": str(((payload.get("editorial_recommendations") or {}).get("text")) or ""),
            "final_manager_note": str(((payload.get("focus_of_week") or {}).get("text")) or ""),
        }
    if preset == "rop_weekly":
        return {
            "executive_summary": str(((payload.get("editorial_summary") or {}).get("executive_summary")) or ""),
            "team_risks_wording": str(((payload.get("editorial_summary") or {}).get("team_risks_wording")) or ""),
            "rop_tasks_wording": str(((payload.get("editorial_summary") or {}).get("rop_tasks_wording")) or ""),
            "final_managerial_commentary": str(
                ((payload.get("editorial_summary") or {}).get("final_managerial_commentary")) or ""
            ),
        }
    raise ASAError(f"Unsupported preset '{preset}' for scheduled reviewable reporting.")


def apply_editable_blocks(*, preset: str, payload: dict[str, Any], edited_blocks: dict[str, str]) -> dict[str, Any]:
    """Apply bounded editorial edits to the generated payload."""
    _ensure_allowed_blocks(preset=preset, edited_blocks=edited_blocks)

    updated = dict(payload)
    if preset == "manager_daily":
        updated["narrative_day_conclusion"] = dict(updated.get("narrative_day_conclusion") or {})
        updated["main_focus_for_tomorrow"] = dict(updated.get("main_focus_for_tomorrow") or {})
        updated["key_problem_of_day"] = dict(updated.get("key_problem_of_day") or {})
        updated["focus_of_week"] = dict(updated.get("focus_of_week") or {})
        updated["editorial_recommendations"] = dict(updated.get("editorial_recommendations") or {})
        if "top_summary" in edited_blocks:
            updated["narrative_day_conclusion"]["text"] = str(edited_blocks["top_summary"])
        if "focus_wording" in edited_blocks:
            updated["main_focus_for_tomorrow"]["text"] = str(edited_blocks["focus_wording"])
        if "key_problem_wording" in edited_blocks:
            updated["key_problem_of_day"]["description"] = str(edited_blocks["key_problem_wording"])
        if "recommendations_wording" in edited_blocks:
            updated["editorial_recommendations"]["text"] = str(edited_blocks["recommendations_wording"])
        if "final_manager_note" in edited_blocks:
            updated["focus_of_week"]["text"] = str(edited_blocks["final_manager_note"])
        return updated

    updated["editorial_summary"] = dict(updated.get("editorial_summary") or {})
    for key, value in edited_blocks.items():
        updated["editorial_summary"][key] = str(value)
    return updated


class ScheduledReviewableReportingService:
    """Persistence and review flow for bounded scheduled reviewable reporting."""

    def __init__(self, db: Session):
        self.db = db

    def list_schedules(self) -> list[dict[str, Any]]:
        """Return all schedules for the operator UI."""
        schedules = (
            self.db.query(ReportingSchedule)
            .filter(ReportingSchedule.deleted_at.is_(None))
            .order_by(ReportingSchedule.created_at.desc())
            .all()
        )
        return [self._serialize_schedule(item) for item in schedules]

    def list_review_batches(self) -> list[dict[str, Any]]:
        """Return recent scheduled review batches with nested drafts."""
        batches = (
            self.db.query(ScheduledReportBatch)
            .order_by(ScheduledReportBatch.created_at.desc())
            .limit(20)
            .all()
        )
        return [self._serialize_batch(item) for item in batches]

    def create_schedule(
        self,
        *,
        department_id: str,
        manager_ids: list[str],
        preset: str,
        enabled: bool,
        start_date: str,
        start_time: str,
        timezone_name: str,
        recurrence_type: str,
        report_period_rule: str,
        mode: str,
        business_email_enabled: bool,
        review_required: bool = True,
    ) -> dict[str, Any]:
        """Create one bounded schedule."""
        resolve_report_preset(preset)
        normalized_manager_ids = _coerce_uuid_list(manager_ids)
        if _is_manager_daily_preset(preset) and not normalized_manager_ids:
            raise ASAError(
                "manager_daily requires explicit non-empty manager_ids "
                f"({MANAGER_DAILY_MANAGER_SCOPE_NOT_CONFIGURED})."
            )
        normalized_timezone = _validate_timezone(timezone_name)
        normalized_mode = str(mode).strip().lower()
        if normalized_mode not in REPORTING_ALLOWED_MODES:
            raise ASAError(
                f"Unsupported mode '{mode}'. Supported modes: {', '.join(sorted(REPORTING_ALLOWED_MODES))}."
            )
        normalized_recurrence = str(recurrence_type).strip().lower()
        if normalized_recurrence not in set(SCHEDULED_REVIEWABLE_ALLOWED_RECURRENCE):
            raise ASAError(
                "recurrence_type must be one of: "
                + ", ".join(sorted(SCHEDULED_REVIEWABLE_ALLOWED_RECURRENCE))
                + "."
            )
        normalized_period_rule = str(report_period_rule).strip().lower()
        if normalized_period_rule not in set(SCHEDULED_REVIEWABLE_ALLOWED_PERIOD_RULES):
            raise ASAError(
                "report_period_rule must be one of: "
                + ", ".join(sorted(SCHEDULED_REVIEWABLE_ALLOWED_PERIOD_RULES))
                + "."
            )

        department_uuid = UUID(department_id)
        department = self.db.query(Department).filter(Department.id == department_uuid).first()
        if department is None:
            raise ASAError("Department not found.")
        if normalized_manager_ids:
            known_manager_ids = {
                str(item.id)
                for item in self.db.query(Manager)
                .filter(
                    Manager.department_id == department_uuid,
                    Manager.id.in_([UUID(item) for item in normalized_manager_ids]),
                )
                .all()
            }
            missing_manager_ids = [item for item in normalized_manager_ids if item not in known_manager_ids]
            if missing_manager_ids:
                raise ASAError(
                    "Unknown manager_ids for department: " + ", ".join(sorted(missing_manager_ids))
                )

        parsed_start_date = date.fromisoformat(start_date)
        _parse_schedule_time(start_time)
        now_utc = datetime.now(UTC)
        next_local = _next_local_occurrence(
            start_date=parsed_start_date,
            start_time=start_time,
            timezone_name=normalized_timezone,
            recurrence_type=normalized_recurrence,
            now_utc=now_utc,
        )
        schedule = ReportingSchedule(
            department_id=department_uuid,
            preset=preset,
            manager_ids=normalized_manager_ids,
            enabled=bool(enabled),
            start_date=parsed_start_date,
            start_time=start_time,
            timezone=normalized_timezone,
            recurrence_type=normalized_recurrence,
            report_period_rule=normalized_period_rule,
            mode=normalized_mode,
            business_email_enabled=bool(business_email_enabled),
            review_required=bool(review_required),
            next_run_at=next_local.astimezone(UTC) if enabled else None,
        )
        self.db.add(schedule)
        self.db.flush()
        return self._serialize_schedule(schedule)

    def set_schedule_enabled(self, *, schedule_id: str, enabled: bool) -> dict[str, Any]:
        """Pause or resume one schedule."""
        schedule = self._get_schedule(schedule_id)
        if schedule.deleted_at is not None:
            raise ASAError("Deleted schedules cannot be resumed or paused.")
        schedule.enabled = bool(enabled)
        if schedule.enabled:
            next_local = _next_local_occurrence(
                start_date=schedule.start_date,
                start_time=schedule.start_time,
                timezone_name=schedule.timezone,
                recurrence_type=schedule.recurrence_type,
                now_utc=datetime.now(UTC),
            )
            schedule.next_run_at = next_local.astimezone(UTC)
        else:
            schedule.next_run_at = None
            open_batch = self._get_latest_open_batch(schedule_id=schedule.id)
            if open_batch is not None and open_batch.status in {"planned", "queued", "running", "review_required"}:
                self._transition_batch_status(open_batch, "paused")
                open_batch.paused_at = datetime.now(UTC)
        self.db.flush()
        return self._serialize_schedule(schedule)

    def delete_schedule(self, *, schedule_id: str) -> dict[str, Any]:
        """Archive one schedule without deleting historical batches/drafts."""
        schedule = self._get_schedule(schedule_id)
        if schedule.deleted_at is None:
            schedule.enabled = False
            schedule.next_run_at = None
            schedule.deleted_at = datetime.now(UTC)
        self.db.flush()
        return {
            "id": str(schedule.id),
            "deleted": True,
            "deleted_at": schedule.deleted_at.isoformat() if schedule.deleted_at else None,
        }

    def edit_draft(
        self,
        *,
        draft_id: str,
        edited_blocks: dict[str, str],
        editor: str = SCHEDULED_REVIEWABLE_DEFAULT_EDITOR,
    ) -> dict[str, Any]:
        """Persist bounded editorial changes for one draft."""
        draft = self._get_draft(draft_id)
        if draft.status != "review_required":
            raise ASAError("Only drafts in review_required status can be edited.")
        _ensure_allowed_blocks(preset=draft.preset, edited_blocks=edited_blocks)
        payload = dict(draft.generated_payload or {})
        current_edits = dict(draft.edited_blocks or {})
        for key, value in edited_blocks.items():
            current_edits[key] = str(value)
        apply_editable_blocks(
            preset=draft.preset,
            payload=payload,
            edited_blocks=current_edits,
        )
        audit = list(draft.edit_audit or [])
        audit.append(
            {
                "edited_blocks": {
                    key: {
                        "original_generated_block": str((draft.generated_blocks or {}).get(key) or ""),
                        "edited_block": str(value),
                    }
                    for key, value in edited_blocks.items()
                },
                "editor": str(editor or SCHEDULED_REVIEWABLE_DEFAULT_EDITOR),
                "edited_at": datetime.now(UTC).isoformat(),
            }
        )
        draft.edited_blocks = current_edits
        draft.edit_audit = audit
        self.db.flush()
        return self._serialize_draft(draft)

    def approve_batch(
        self,
        *,
        batch_id: str,
        editor: str = SCHEDULED_REVIEWABLE_DEFAULT_EDITOR,
    ) -> dict[str, Any]:
        """Approve one review batch and send business delivery manually."""
        batch = self._get_batch(batch_id)
        if batch.status != "review_required":
            raise ASAError("Only review_required batches can be approved.")
        drafts = self._load_batch_drafts(batch.id)
        if not drafts:
            raise ASAError("Scheduled batch has no drafts to approve.")
        if any(draft.status != "review_required" for draft in drafts):
            raise ASAError("All scheduled drafts must stay in review_required before approve.")

        self._transition_batch_status(batch, "approved_for_delivery")
        batch.approved_at = datetime.now(UTC)
        batch.approved_by = str(editor or SCHEDULED_REVIEWABLE_DEFAULT_EDITOR)
        self.db.flush()

        orchestrator = CallsManualReportingOrchestrator(
            department_id=str(batch.department_id),
            db=self.db,
        )
        delivery_errors: list[str] = []
        any_delivered = False
        for draft in drafts:
            effective_payload = apply_editable_blocks(
                preset=draft.preset,
                payload=dict(draft.generated_payload or {}),
                edited_blocks=dict(draft.edited_blocks or {}),
            )
            rendered = render_report_email(effective_payload, prefer_docx_first=True)
            transport = dict((draft.delivery or {}).get("transport") or {})
            resolved_email = dict(transport.get("resolved_email") or {})
            primary_email = str(resolved_email.get("primary_email") or "").strip() or None
            cc_emails = list(resolved_email.get("cc_emails") or [])
            email_resolution_error = None
            if batch.business_email_enabled and not primary_email:
                email_resolution_error = (
                    "Business email delivery is enabled, but primary recipient is not resolved."
                )
            delivery = orchestrator.delivery.deliver_operator_report(
                primary_email=primary_email,
                cc_emails=cc_emails,
                subject=rendered["subject"],
                text=rendered["text"],
                html=rendered["html"],
                pdf_bytes=rendered["pdf_bytes"],
                pdf_filename=rendered["artifact"]["filename"],
                template_meta=rendered.get("template"),
                artifact_meta=rendered.get("artifact"),
                send_business_email=batch.business_email_enabled,
                email_resolution_error=email_resolution_error,
                morning_card_text=rendered.get("morning_card_text"),
            )
            preview = {key: value for key, value in rendered.items() if key != "pdf_bytes"}
            draft.preview = preview
            draft.artifact = rendered.get("artifact")
            draft.delivery = delivery
            transport = dict(delivery.get("transport") or {})
            telegram_status = str(
                ((transport.get("telegram_test_delivery") or {}).get("status")) or ""
            ).strip()
            email_status = str(((transport.get("email_delivery") or {}).get("status")) or "").strip()
            allowed_email_statuses = (
                {"delivered"}
                if batch.business_email_enabled
                else {"", "skipped"}
            )
            draft.errors = [
                error
                for error in [
                    (transport.get("telegram_test_delivery") or {}).get("error"),
                    (transport.get("email_delivery") or {}).get("error"),
                ]
                if error
            ]
            next_draft_status = (
                "delivered"
                if telegram_status == "delivered"
                and email_status in allowed_email_statuses
                else "failed"
            )
            draft.status = next_draft_status
            if draft.status == "delivered":
                any_delivered = True
            else:
                delivery_errors.extend(list(draft.errors or []))
        batch.errors = delivery_errors
        if any_delivered and not delivery_errors:
            self._transition_batch_status(batch, "delivered")
            batch.delivered_at = datetime.now(UTC)
        elif any_delivered:
            self._transition_batch_status(batch, "failed")
            batch.failed_at = datetime.now(UTC)
        else:
            self._transition_batch_status(batch, "failed")
            batch.failed_at = datetime.now(UTC)
        self.db.flush()
        return self._serialize_batch(batch)

    def scan_due_schedules(self) -> dict[str, Any]:
        """Create and execute scheduled reviewable batches that are due now."""
        now_utc = datetime.now(UTC)
        due_schedules = (
            self.db.query(ReportingSchedule)
            .filter(
                ReportingSchedule.enabled.is_(True),
                ReportingSchedule.next_run_at.is_not(None),
                ReportingSchedule.next_run_at <= now_utc,
            )
            .order_by(ReportingSchedule.next_run_at.asc())
            .all()
        )
        processed: list[str] = []
        for schedule in due_schedules:
            self._run_due_schedule(schedule=schedule, now_utc=now_utc)
            processed.append(str(schedule.id))
        return {"processed_schedule_ids": processed, "processed_count": len(processed)}

    def _run_due_schedule(self, *, schedule: ReportingSchedule, now_utc: datetime) -> None:
        """Execute one due schedule into a review batch."""
        if not schedule.enabled or schedule.next_run_at is None:
            return
        if schedule.next_run_at > now_utc:
            return

        if _is_manager_daily_preset(schedule) and not list(getattr(schedule, "manager_ids", None) or []):
            self._block_manager_daily_without_analysis_scope(schedule=schedule, now_utc=now_utc)
            return
        if self._uses_manager_daily_candidate_selection(schedule=schedule):
            self._run_due_manager_daily_schedule(schedule=schedule, now_utc=now_utc)
            return
        if self._has_open_batch(schedule_id=schedule.id):
            schedule.last_planned_at = schedule.next_run_at
            schedule.next_run_at = self._advance_schedule(schedule=schedule, after_utc=now_utc)
            return

        planned_for = schedule.next_run_at or now_utc
        existing = self._get_batch_for_occurrence(schedule_id=schedule.id, planned_for=planned_for)
        if existing is not None:
            schedule.last_planned_at = planned_for
            schedule.next_run_at = self._advance_schedule(schedule=schedule, after_utc=now_utc)
            self.db.flush()
            return
        local_planned = planned_for.astimezone(ZoneInfo(schedule.timezone))
        period = _compute_report_period(rule=schedule.report_period_rule, local_run_at=local_planned)
        filters = ReportRunFilters(
            manager_ids=set(schedule.manager_ids or []),
            date_from=period.date_from,
            date_to=period.date_to,
        )
        batch = ScheduledReportBatch(
            schedule_id=schedule.id,
            department_id=schedule.department_id,
            preset=schedule.preset,
            mode=schedule.mode,
            report_period_rule=schedule.report_period_rule,
            status="planned",
            planned_for=planned_for,
            period={"date_from": period.date_from, "date_to": period.date_to},
            filters={
                "manager_ids": list(schedule.manager_ids or []),
                "manager_extensions": [],
            },
            business_email_enabled=bool(schedule.business_email_enabled),
            review_required=_schedule_requires_review(schedule),
            errors=[],
        )
        self.db.add(batch)
        self.db.flush()

        self._transition_batch_status(batch, "queued")
        batch.queued_at = datetime.now(UTC)
        self.db.flush()

        self._transition_batch_status(batch, "running")
        batch.started_at = datetime.now(UTC)
        self.db.flush()

        orchestrator = CallsManualReportingOrchestrator(
            department_id=str(schedule.department_id),
            db=self.db,
        )
        try:
            result = asyncio.run(
                orchestrator.run_report(
                    preset_code=schedule.preset,
                    mode=schedule.mode,
                    filters=filters,
                    model_override=None,
                    send_email=False,
                )
            )
        except Exception as exc:
            self._transition_batch_status(batch, "failed")
            batch.failed_at = datetime.now(UTC)
            batch.errors = [f"{exc.__class__.__name__}: {exc}"]
            schedule.last_planned_at = planned_for
            schedule.next_run_at = self._advance_schedule(schedule=schedule, after_utc=now_utc)
            self.db.flush()
            return

        source_summary = dict(
            ((result.get("observability") or {}).get("summary") or {}).get("source") or {}
        )
        analysis_scope = self._scheduled_analysis_scope_diagnostics(
            schedule=schedule,
            period=period,
            manager_ids=list(schedule.manager_ids or []),
            source_summary=source_summary,
        )
        batch.observability = {**dict(result.get("observability") or {}), **analysis_scope}
        batch.diagnostics = {
            **dict(result.get("diagnostics") or {}),
            **analysis_scope,
            "analysis_scope": analysis_scope,
        }
        batch.errors = list(result.get("errors") or [])

        drafts_created = 0
        for report in result.get("reports") or []:
            payload = dict(report.get("payload") or {})
            draft_status = "review_required" if payload else "failed"
            draft = ScheduledReportDraft(
                batch_id=batch.id,
                department_id=schedule.department_id,
                preset=schedule.preset,
                group_key=str(report.get("group_key") or batch.id),
                status=draft_status,
                generated_payload=payload or None,
                generated_blocks=extract_editable_blocks(preset=schedule.preset, payload=payload) if payload else {},
                edited_blocks={},
                edit_audit=[],
                preview=dict(report.get("preview") or {}) or None,
                artifact=dict(report.get("artifact") or {}) or None,
                delivery=dict(report.get("delivery") or {}) or None,
                errors=list(report.get("errors") or []),
            )
            self.db.add(draft)
            drafts_created += 1

        next_batch_status = "review_required" if drafts_created > 0 else "failed"
        self._transition_batch_status(batch, next_batch_status)
        if batch.status == "review_required":
            batch.review_required_at = datetime.now(UTC)
        else:
            batch.failed_at = datetime.now(UTC)

        schedule.last_planned_at = planned_for
        schedule.next_run_at = self._advance_schedule(schedule=schedule, after_utc=now_utc)
        self.db.flush()

    def _uses_manager_daily_candidate_selection(self, *, schedule: ReportingSchedule) -> bool:
        """Return True for split scheduled manager-day scans with explicit managers."""
        return (
            _is_manager_daily_preset(schedule)
            and str(getattr(schedule, "recurrence_type", "") or "").strip().lower() == "daily"
            and bool(list(getattr(schedule, "manager_ids", None) or []))
        )

    def _block_manager_daily_without_analysis_scope(
        self,
        *,
        schedule: ReportingSchedule,
        now_utc: datetime,
    ) -> None:
        """Record a diagnostic blocker instead of falling back to department scope."""
        planned_for = schedule.next_run_at or now_utc
        existing = self._get_batch_for_occurrence(schedule_id=schedule.id, planned_for=planned_for)
        if existing is not None:
            schedule.last_planned_at = planned_for
            schedule.next_run_at = self._advance_schedule(schedule=schedule, after_utc=now_utc)
            self.db.flush()
            return

        local_planned = planned_for.astimezone(ZoneInfo(schedule.timezone))
        period = _compute_report_period(rule=schedule.report_period_rule, local_run_at=local_planned)
        analysis_scope = self._scheduled_analysis_scope_diagnostics(
            schedule=schedule,
            period=period,
            manager_ids=[],
            scope_source="reporting_schedule.manager_ids_empty",
        )
        batch = ScheduledReportBatch(
            schedule_id=schedule.id,
            department_id=schedule.department_id,
            preset=schedule.preset,
            mode=schedule.mode,
            report_period_rule=schedule.report_period_rule,
            status="failed",
            planned_for=planned_for,
            period={"date_from": period.date_from, "date_to": period.date_to},
            filters={"manager_ids": [], "manager_extensions": []},
            business_email_enabled=bool(schedule.business_email_enabled),
            review_required=_schedule_requires_review(schedule),
            observability={
                **analysis_scope,
                "status": "blocked",
                "run_state": "blocked_without_report_runner",
                "failure_reason": MANAGER_DAILY_MANAGER_SCOPE_NOT_CONFIGURED,
                "blockers": [MANAGER_DAILY_MANAGER_SCOPE_NOT_CONFIGURED],
            },
            diagnostics={
                **analysis_scope,
                "analysis_scope": dict(analysis_scope),
                "reason": MANAGER_DAILY_MANAGER_SCOPE_NOT_CONFIGURED,
                "report_runner_started": False,
                "scheduled_manager_daily_run": {
                    "schema_version": "scheduled_manager_daily_run_v1",
                    "schedule_id": str(schedule.id),
                    "planned_for": _isoformat_utc(planned_for),
                    "status": "blocked",
                    "failure_reason": MANAGER_DAILY_MANAGER_SCOPE_NOT_CONFIGURED,
                    "report_batches_created": 0,
                    "batches_created": 0,
                    "diagnostic_batches_created": 1,
                },
            },
            errors=[MANAGER_DAILY_MANAGER_SCOPE_NOT_CONFIGURED],
            failed_at=datetime.now(UTC),
        )
        self.db.add(batch)
        schedule.last_planned_at = planned_for
        schedule.next_run_at = self._advance_schedule(schedule=schedule, after_utc=now_utc)
        self.db.flush()

    def _run_due_manager_daily_schedule(self, *, schedule: ReportingSchedule, now_utc: datetime) -> None:
        """Execute one due manager_daily schedule through data-driven candidate selection."""
        planned_for = schedule.next_run_at or now_utc
        local_planned = planned_for.astimezone(ZoneInfo(schedule.timezone))
        if schedule.report_period_rule == "previous_day":
            lookback_days = 1
            period = _compute_report_period(rule=schedule.report_period_rule, local_run_at=local_planned)
            candidate_dates = [period.date_to]
        else:
            lookback_days = _scheduled_analysis_lookback_days()
            candidate_dates = _candidate_dates_for_lookback(
                local_planned=local_planned,
                rule=schedule.report_period_rule,
                lookback_days=lookback_days,
            )
        scan_started_at = datetime.now(UTC).isoformat()
        created_batches: list[ScheduledReportBatch] = []
        rop_digest_report_items: list[dict[str, Any]] = []
        selected_manager_days_count = 0
        skipped_manager_days = 0
        idempotency_blocked_manager_days = 0
        selection_details: list[dict[str, Any]] = []
        for manager_id in list(schedule.manager_ids or []):
            selection = self._select_manager_day_candidate(
                schedule=schedule,
                manager_id=str(manager_id),
                candidate_dates=candidate_dates,
                lookback_days=lookback_days,
                scan_started_at=scan_started_at,
            )
            if selection.selected_report_date:
                duplicate_diagnostics = self._manager_day_creation_guard_diagnostics(
                    schedule=schedule,
                    planned_for=planned_for,
                    selection=selection,
                )
                if duplicate_diagnostics["has_duplicate"]:
                    blocked_selection = self._selection_blocked_by_creation_guard(
                        selection=selection,
                        duplicate_diagnostics=duplicate_diagnostics,
                    )
                    selection_details.append(blocked_selection.to_observability())
                    skipped_manager_days += 1
                    idempotency_blocked_manager_days += 1
                    continue

                selection_details.append(selection.to_observability())
                selected_manager_days_count += 1
                batch = self._run_due_manager_day_selection(
                    schedule=schedule,
                    planned_for=planned_for,
                    selection=selection,
                    creation_guarded=True,
                    rop_digest_report_items=rop_digest_report_items,
                )
            else:
                pending_retry = self._pending_upstream_retry_for_selection(selection=selection)
                if pending_retry is not None:
                    retry_selection, existing_batch = pending_retry
                    selection_details.append(retry_selection.to_observability())
                    selected_manager_days_count += 1
                    batch = self._run_due_manager_day_selection(
                        schedule=schedule,
                        planned_for=planned_for,
                        selection=retry_selection,
                        creation_guarded=True,
                        existing_batch=existing_batch,
                        rop_digest_report_items=rop_digest_report_items,
                    )
                else:
                    selection_details.append(selection.to_observability())
                    skipped_manager_days += 1
                    batch = self._record_skipped_manager_day_selection(
                        schedule=schedule,
                        planned_for=planned_for,
                        selection=selection,
                    )
            if batch is not None:
                created_batches.append(batch)

        created_batches_before_guard_count = len(created_batches)
        failure_reason = None
        alert_records: list[dict[str, Any]] = []
        manager_scope = [str(item) for item in list(schedule.manager_ids or [])]
        has_expected_or_candidate_scope = bool(manager_scope) or bool(selection_details)
        if created_batches_before_guard_count <= 0 and idempotency_blocked_manager_days > 0:
            self.db.flush()
            return
        if created_batches_before_guard_count <= 0 and has_expected_or_candidate_scope:
            failure_reason = "manager_daily_zero_batches_after_candidate_selection"
            preliminary_summary = self._manager_daily_run_summary(
                schedule=schedule,
                planned_for=planned_for,
                candidate_dates=candidate_dates,
                lookback_days=lookback_days,
                scan_started_at=scan_started_at,
                selected_manager_days_count=selected_manager_days_count,
                skipped_manager_days=skipped_manager_days,
                created_batches_count=0,
                created_batches_before_guard_count=0,
                batch_status_counts=self._manager_daily_batch_status_counts([]),
                failure_reason=failure_reason,
                alert_records=[],
                selection_details=selection_details,
            )
            alert_records = [
                self._send_manager_daily_zero_batch_alert(
                    schedule=schedule,
                    planned_for=planned_for,
                    run_summary=preliminary_summary,
                )
            ]
            diagnostic_batch = self._record_manager_daily_zero_batch_failure(
                schedule=schedule,
                planned_for=planned_for,
                failure_reason=failure_reason,
                alert_records=alert_records,
            )
            created_batches.append(diagnostic_batch)
        elif created_batches_before_guard_count > 0:
            batch_status_counts = self._manager_daily_batch_status_counts(created_batches)
            preliminary_summary = self._manager_daily_run_summary(
                schedule=schedule,
                planned_for=planned_for,
                candidate_dates=candidate_dates,
                lookback_days=lookback_days,
                scan_started_at=scan_started_at,
                selected_manager_days_count=selected_manager_days_count,
                skipped_manager_days=skipped_manager_days,
                created_batches_count=len(created_batches),
                created_batches_before_guard_count=created_batches_before_guard_count,
                batch_status_counts=batch_status_counts,
                failure_reason=None,
                alert_records=[],
                selection_details=selection_details,
            )
            if (
                preliminary_summary["status"] == "failed"
                and int(preliminary_summary["failed_batches_count"] or 0) > 0
                and int(preliminary_summary["report_ready_batches_count"] or 0) <= 0
            ):
                failure_reason = str(
                    preliminary_summary.get("failure_reason")
                    or "manager_daily_failed_batches_without_report_ready_batches"
                )
                alert_records = [
                    self._send_manager_daily_failed_no_ready_alert(
                        schedule=schedule,
                        planned_for=planned_for,
                        run_summary={
                            **preliminary_summary,
                            "failure_reason": failure_reason,
                        },
                    )
                ]

        run_summary = self._manager_daily_run_summary(
            schedule=schedule,
            planned_for=planned_for,
            candidate_dates=candidate_dates,
            lookback_days=lookback_days,
            scan_started_at=scan_started_at,
            selected_manager_days_count=selected_manager_days_count,
            skipped_manager_days=skipped_manager_days,
            created_batches_count=len(created_batches),
            created_batches_before_guard_count=created_batches_before_guard_count,
            batch_status_counts=self._manager_daily_batch_status_counts(
                created_batches[:created_batches_before_guard_count]
            ),
            failure_reason=failure_reason,
            alert_records=alert_records,
            selection_details=selection_details,
        )
        for batch in created_batches:
            batch.observability = self._with_manager_daily_run_summary(
                observability=dict(batch.observability or {}),
                run_summary=run_summary,
            )
            batch.diagnostics = self._with_manager_daily_run_summary(
                observability=dict(batch.diagnostics or {}),
                run_summary=run_summary,
            )

        upstream_waiting_batches = [
            batch for batch in created_batches if self._is_upstream_waiting_batch(batch)
        ]
        schedule.last_planned_at = planned_for
        scheduled_rop_digest = {
            "enabled": bool(settings.manager_daily_rop_email_enabled),
            "target": str(settings.manager_daily_rop_email_to or "").strip() or None,
            "status": "skipped",
            "reason": "not_attempted",
        }
        if upstream_waiting_batches:
            retry_at = _manager_daily_next_upstream_retry_at(
                planned_for=planned_for,
                now_utc=now_utc,
                timezone_name=str(schedule.timezone),
            )
            if retry_at is not None:
                schedule.next_run_at = retry_at
                scheduled_rop_digest["reason"] = "waiting_upstream_retry_scheduled"
            else:
                for batch in upstream_waiting_batches:
                    self._finalize_upstream_not_ready_before_deadline(
                        batch=batch,
                        planned_for=planned_for,
                        timezone_name=str(schedule.timezone),
                    )
                scheduled_rop_digest = self._send_scheduled_manager_daily_rop_digest(
                    schedule=schedule,
                    planned_for=planned_for,
                    run_summary=run_summary,
                    batches=created_batches,
                    report_items=rop_digest_report_items,
                )
                schedule.next_run_at = self._advance_schedule(schedule=schedule, after_utc=now_utc)
        else:
            if _manager_daily_auto_delivery_enabled(schedule):
                scheduled_rop_digest = self._send_scheduled_manager_daily_rop_digest(
                    schedule=schedule,
                    planned_for=planned_for,
                    run_summary=run_summary,
                    batches=created_batches,
                    report_items=rop_digest_report_items,
                )
            else:
                scheduled_rop_digest["reason"] = "production_auto_delivery_disabled"
            schedule.next_run_at = self._advance_schedule(schedule=schedule, after_utc=now_utc)
        for batch in created_batches:
            batch.observability = self._with_scheduled_rop_daily_digest(
                observability=dict(batch.observability or {}),
                digest=scheduled_rop_digest,
            )
            batch.diagnostics = self._with_scheduled_rop_daily_digest(
                observability=dict(batch.diagnostics or {}),
                digest=scheduled_rop_digest,
            )
        self.db.flush()

    @staticmethod
    def _manager_daily_run_summary(
        *,
        schedule: ReportingSchedule,
        planned_for: datetime,
        candidate_dates: list[str],
        lookback_days: int,
        scan_started_at: str,
        selected_manager_days_count: int,
        skipped_manager_days: int,
        created_batches_count: int,
        created_batches_before_guard_count: int,
        batch_status_counts: dict[str, int],
        failure_reason: str | None,
        alert_records: list[dict[str, Any]],
        selection_details: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Return stable run-level diagnostics for one scheduled manager_daily scan."""
        manager_scope = [str(item) for item in list(getattr(schedule, "manager_ids", None) or [])]
        report_date = candidate_dates[-1] if candidate_dates else None
        selection_summary = [
            ScheduledReviewableReportingService._manager_daily_selection_summary(item)
            for item in selection_details
        ]
        skipped = [
            dict(item)
            for item in selection_summary
            if str(item.get("selection_status") or "") != "selected"
        ]
        failed_batches_count = int(batch_status_counts.get("failed_batches_count") or 0)
        review_required_batches_count = int(
            batch_status_counts.get("review_required_batches_count") or 0
        )
        approved_for_delivery_batches_count = int(
            batch_status_counts.get("approved_for_delivery_batches_count") or 0
        )
        delivered_batches_count = int(batch_status_counts.get("delivered_batches_count") or 0)
        upstream_waiting_batches_count = int(
            batch_status_counts.get("upstream_waiting_batches_count") or 0
        )
        report_ready_batches_count = int(batch_status_counts.get("report_ready_batches_count") or 0)
        effective_failure_reason = failure_reason
        if effective_failure_reason is None and failed_batches_count > 0 and report_ready_batches_count <= 0:
            effective_failure_reason = "manager_daily_failed_batches_without_report_ready_batches"
        if effective_failure_reason:
            status = "failed"
        elif upstream_waiting_batches_count > 0:
            status = "waiting_upstream"
        elif failed_batches_count > 0:
            status = "partial"
        else:
            status = "ok"
        diagnostic_batches_created = max(
            0,
            created_batches_count - created_batches_before_guard_count,
        )
        return {
            "schema_version": "scheduled_manager_daily_run_v1",
            "schedule_id": str(schedule.id),
            "planned_for": _isoformat_utc(planned_for),
            "timezone": str(schedule.timezone),
            "report_period_rule": str(schedule.report_period_rule),
            "report_date": report_date,
            "candidate_dates": list(candidate_dates),
            "lookback_days": lookback_days,
            "scan_started_at": scan_started_at,
            "manager_scope": manager_scope,
            "managers_count": len(manager_scope),
            "expected_managers": len(manager_scope),
            "expected_manager_days": len(manager_scope) * len(candidate_dates),
            "candidate_manager_days": len(selection_details),
            "selected_manager_days": selected_manager_days_count,
            "selected_manager_days_count": selected_manager_days_count,
            "skipped": skipped,
            "skipped_manager_days": skipped_manager_days,
            "report_batches_created": created_batches_before_guard_count,
            "batches_created": created_batches_before_guard_count,
            "diagnostic_batches_created": diagnostic_batches_created,
            "records_created": created_batches_count,
            "created_batches_count": created_batches_count,
            "created_batches_before_guard_count": created_batches_before_guard_count,
            "failed_batches_count": failed_batches_count,
            "review_required_batches_count": review_required_batches_count,
            "approved_for_delivery_batches_count": approved_for_delivery_batches_count,
            "delivered_batches_count": delivered_batches_count,
            "upstream_waiting_batches_count": upstream_waiting_batches_count,
            "report_ready_batches_count": report_ready_batches_count,
            "status": status,
            "failure_reason": effective_failure_reason,
            "alerts": [dict(item) for item in alert_records],
            "selection_summary": selection_summary,
            "selection_details": [dict(item) for item in selection_details],
        }

    def _send_scheduled_manager_daily_rop_digest(
        self,
        *,
        schedule: ReportingSchedule,
        planned_for: datetime,
        run_summary: dict[str, Any],
        batches: list[ScheduledReportBatch],
        report_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Send one daily ROP digest for the whole scheduled manager_daily scan."""
        target = str(settings.manager_daily_rop_email_to or "").strip()
        report_date = str(run_summary.get("report_date") or planned_for.date().isoformat())
        rows = self._scheduled_manager_daily_rop_rows(
            schedule=schedule,
            run_summary=run_summary,
            batches=batches,
            report_items=report_items,
        )
        attachments = self._scheduled_manager_daily_rop_attachments(report_items=report_items)
        summary: dict[str, Any] = {
            "schema_version": "scheduled_manager_daily_rop_digest_v1",
            "enabled": bool(settings.manager_daily_rop_email_enabled),
            "target": target or None,
            "status": "skipped",
            "reason": None,
            "report_date": report_date,
            "rows_count": len(rows),
            "attachments_count": len(attachments),
            "attached_reports": [
                {
                    "manager_id": item.get("manager_id"),
                    "manager_name": item.get("manager_name"),
                    "filename": item.get("filename"),
                    "email_status": item.get("email_status"),
                }
                for item in report_items
                if isinstance(item.get("attachment"), dict)
            ],
            "rows": rows,
        }
        if not _manager_daily_auto_delivery_enabled(schedule):
            summary["reason"] = "production_auto_delivery_disabled"
            return summary
        if not settings.manager_daily_rop_email_enabled:
            summary["reason"] = "manager_daily_rop_email_disabled"
            return summary
        if not target:
            summary.update({"status": "blocked", "reason": "manager_daily_rop_email_to_missing"})
            return summary
        if not settings.has_smtp:
            summary.update({"status": "blocked", "reason": "smtp_not_configured"})
            return summary
        if not rows:
            summary["reason"] = "no_manager_rows"
            return summary

        subject = f"Ежедневная сводка по отчётам ЭДО — {report_date}"
        text = self._render_scheduled_manager_daily_rop_digest_text(
            report_date=report_date,
            rows=rows,
            attachments_count=len(attachments),
        )
        try:
            delivery = CallsDelivery(
                department_id=str(schedule.department_id),
                db=self.db,
            ).send_email_message(
                email_to=target,
                subject=subject,
                text=text,
                attachments=attachments,
            )
        except DeliveryError as exc:
            summary.update({"status": "failed", "reason": str(exc), "subject": subject})
            return summary

        summary.update(
            {
                "status": delivery.get("status") or "sent",
                "reason": None,
                "subject": subject,
                "message_id": delivery.get("message_id"),
                "delivery_metadata": {
                    key: delivery.get(key)
                    for key in ("status", "channel", "target", "message_id", "artifact")
                    if delivery.get(key) not in (None, "")
                },
                "delivery": delivery,
            }
        )
        return summary

    def _scheduled_manager_daily_rop_rows(
        self,
        *,
        schedule: ReportingSchedule,
        run_summary: dict[str, Any],
        batches: list[ScheduledReportBatch],
        report_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return one ROP digest row per manager in schedule scope."""
        manager_ids = [str(item) for item in list(getattr(schedule, "manager_ids", None) or [])]
        manager_names = self._manager_names_by_id(manager_ids=manager_ids)
        selection_by_manager = {
            str(item.get("manager_id") or ""): dict(item)
            for item in list(run_summary.get("selection_summary") or [])
            if isinstance(item, dict)
        }
        batch_by_manager = {
            manager_id: batch
            for batch in batches
            for manager_id in self._batch_manager_ids(batch=batch)
        }
        item_by_manager = {
            str(item.get("manager_id") or ""): dict(item)
            for item in report_items
            if isinstance(item, dict)
        }
        rows: list[dict[str, Any]] = []
        for manager_id in manager_ids:
            selection = selection_by_manager.get(manager_id, {})
            batch = batch_by_manager.get(manager_id)
            item = item_by_manager.get(manager_id, {})
            manager_name = (
                str(item.get("manager_name") or "").strip()
                or str(selection.get("manager_name") or "").strip()
                or manager_names.get(manager_id)
                or manager_id
            )
            report_date = (
                str(item.get("report_date") or "").strip()
                or str(selection.get("report_date") or "").strip()
                or str(run_summary.get("report_date") or "").strip()
                or None
            )
            status, reason = self._scheduled_manager_daily_rop_status(
                selection=selection,
                batch=batch,
                report_item=item,
            )
            row = {
                "manager_id": manager_id,
                "manager_name": manager_name,
                "report_date": report_date,
                "status": status,
                "reason": reason,
                "manager_email_status": item.get("email_status")
                or self._batch_observability_value(batch=batch, key="manager_email_status")
                or "not_started",
                "batch_status": str(getattr(batch, "status", "") or "") or None,
                "attachment": "attached" if isinstance(item.get("attachment"), dict) else "not_attached",
            }
            rows.append(row)
        return rows

    @staticmethod
    def _scheduled_manager_daily_rop_status(
        *,
        selection: dict[str, Any],
        batch: ScheduledReportBatch | None,
        report_item: dict[str, Any],
    ) -> tuple[str, str]:
        email_status = str(report_item.get("email_status") or "").strip()
        if email_status == "delivered":
            return "delivered", "отчёт отправлен менеджеру; PDF приложен к сводке РОП"
        if email_status in {"failed", "blocked"}:
            reason = str(report_item.get("reason") or "").strip()
            if "missing_recipient" in reason or "recipient" in reason:
                return "missing_recipient", reason or "не найден email получателя"
            return "delivery_failed", reason or "ошибка доставки менеджеру"

        if batch is not None:
            batch_status = str(getattr(batch, "status", "") or "").strip()
            observability = dict(getattr(batch, "observability", None) or {})
            missed_reason = str(observability.get("sla_missed_reason") or "").strip()
            upstream_reason = str(observability.get("upstream_waiting_reason") or "").strip()
            if batch_status == "paused" or observability.get("upstream_waiting"):
                return "will_retry", upstream_reason or "ожидаем готовность транскрибации/LLM1"
            if batch_status == "failed":
                if missed_reason == "no_calls_for_report_day":
                    return "no_calls", missed_reason
                if missed_reason == "no_audio_calls_for_report_day":
                    return "not_applicable", missed_reason
                if missed_reason == MANAGER_DAILY_UPSTREAM_DEADLINE_REASON:
                    return "not_ready", "артефакты не готовы до дедлайна"
                return "blocked", missed_reason or "отчёт не сформирован"
            if batch_status in {"review_required", "approved_for_delivery"}:
                return "review_required", "отчёт готов, но не отправлен автоматически"
            if batch_status == "delivered":
                return "delivered", "отчёт доставлен"

        selection_reason = str(selection.get("reason") or selection.get("selection_reason") or "").strip()
        if selection_reason in {"no_calls", "no_calls_for_report_day", "no_candidate_empty_previous_day"}:
            return "no_calls", selection_reason if selection_reason != "no_calls" else "за день нет звонков для отчёта"
        if selection_reason in {"analysis_not_ready", "not_ready"}:
            return "not_ready", "анализ ещё не готов"
        if selection_reason in {"already_reported", "blocked_by_open_batch"}:
            return "already_reported", "отчёт уже был создан или есть открытый batch"
        return "not_ready", selection_reason or "нет готового отчёта"

    @staticmethod
    def _scheduled_manager_daily_rop_attachments(
        *,
        report_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        attachments: list[dict[str, Any]] = []
        used_filenames: set[str] = set()
        for item in report_items:
            attachment = item.get("attachment")
            if not isinstance(attachment, dict) or not attachment.get("content"):
                continue
            filename = ScheduledReviewableReportingService._dedupe_attachment_filename(
                str(attachment.get("filename") or "manager_daily_report.pdf"),
                used_filenames=used_filenames,
            )
            item["filename"] = filename
            attachments.append(
                {
                    "filename": filename,
                    "content": attachment["content"],
                    "maintype": "application",
                    "subtype": "pdf",
                }
            )
        return attachments

    @staticmethod
    def _render_scheduled_manager_daily_rop_digest_text(
        *,
        report_date: str,
        rows: list[dict[str, Any]],
        attachments_count: int,
    ) -> str:
        delivered = sum(1 for row in rows if row.get("status") == "delivered")
        blocked = sum(1 for row in rows if row.get("status") in {"blocked", "delivery_failed", "missing_recipient"})
        pending = sum(1 for row in rows if row.get("status") in {"not_ready", "will_retry", "review_required"})
        no_calls = sum(1 for row in rows if row.get("status") == "no_calls")
        status_lines = [
            (
                f"- {row.get('manager_name')}: {row.get('status')} — "
                f"{row.get('reason') or 'без комментария'}"
            )
            for row in rows
        ]
        return "\n".join(
            [
                "Добрый день.",
                "",
                f"Ежедневная сводка по отчётам менеджеров ЭДО за {report_date}.",
                "",
                (
                    f"Итог: отправлено менеджерам — {delivered}; не готово/ожидает — {pending}; "
                    f"нет звонков — {no_calls}; требует внимания — {blocked}."
                ),
                f"PDF во вложении: {attachments_count}.",
                "",
                "Статусы по менеджерам:",
                *status_lines,
                "",
                "Это автоматическая сводка после scheduled manager_daily delivery.",
            ]
        )

    def _scheduled_rop_digest_report_item(
        self,
        *,
        schedule: ReportingSchedule,
        selection: ScheduledManagerDaySelection,
        report: dict[str, Any],
        assessment: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(report.get("payload") or {})
        header = dict(payload.get("header") or {})
        manager_name = str(header.get("manager_name") or "").strip()
        if not manager_name:
            manager_name = self._manager_names_by_id(manager_ids=[selection.manager_id]).get(
                selection.manager_id,
                selection.manager_id,
            )
        email_status = str(assessment.get("manager_email_status") or "").strip() or "unknown"
        runtime_attachment = report.get("_runtime_rop_bundle_attachment")
        attachment = None
        if (
            email_status == "delivered"
            and isinstance(runtime_attachment, dict)
            and runtime_attachment.get("content")
        ):
            attachment = {
                "filename": runtime_attachment.get("filename") or "manager_daily_report.pdf",
                "content": runtime_attachment["content"],
            }
        return {
            "manager_id": selection.manager_id,
            "manager_name": manager_name,
            "report_date": selection.selected_report_date,
            "report_status": report.get("status"),
            "email_status": email_status,
            "sla_status": assessment.get("sla_status"),
            "reason": assessment.get("sla_missed_reason"),
            "attachment": attachment,
            "department_id": str(schedule.department_id),
        }

    def _manager_names_by_id(self, *, manager_ids: list[str]) -> dict[str, str]:
        """Best-effort manager-name lookup for scheduled digest rows."""
        normalized = [str(item) for item in manager_ids if str(item or "").strip()]
        if not normalized:
            return {}
        try:
            rows = self.db.query(Manager).filter(Manager.id.in_([UUID(item) for item in normalized])).all()
        except Exception:  # noqa: BLE001 - diagnostics must not depend on ORM availability in tests
            return {}
        result: dict[str, str] = {}
        for row in rows:
            manager_id = str(getattr(row, "id", "") or "")
            name = str(getattr(row, "name", "") or "").strip()
            if manager_id and name:
                result[manager_id] = name
        return result

    @staticmethod
    def _batch_manager_ids(*, batch: ScheduledReportBatch) -> list[str]:
        filters = dict(getattr(batch, "filters", None) or {})
        return [str(item) for item in list(filters.get("manager_ids") or []) if str(item or "").strip()]

    @staticmethod
    def _batch_observability_value(*, batch: ScheduledReportBatch | None, key: str) -> Any:
        if batch is None:
            return None
        return dict(getattr(batch, "observability", None) or {}).get(key)

    @staticmethod
    def _dedupe_attachment_filename(filename: str, *, used_filenames: set[str]) -> str:
        candidate = filename.strip() or "manager_daily_report.pdf"
        if candidate not in used_filenames:
            used_filenames.add(candidate)
            return candidate
        if "." in candidate:
            stem, suffix = candidate.rsplit(".", 1)
            suffix = f".{suffix}"
        else:
            stem, suffix = candidate, ""
        counter = 2
        while True:
            next_candidate = f"{stem}_{counter}{suffix}"
            if next_candidate not in used_filenames:
                used_filenames.add(next_candidate)
                return next_candidate
            counter += 1

    @staticmethod
    def _with_scheduled_rop_daily_digest(
        *,
        observability: dict[str, Any],
        digest: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(observability or {})
        safe_digest = {
            key: value
            for key, value in dict(digest or {}).items()
            if key not in {"delivery"}
        }
        merged["scheduled_rop_daily_digest"] = safe_digest
        return merged

    @staticmethod
    def _manager_daily_batch_status_counts(
        batches: list[ScheduledReportBatch],
    ) -> dict[str, int]:
        """Count real manager-day batch outcomes; diagnostic guard records are passed separately."""
        statuses = [str(getattr(batch, "status", "") or "") for batch in batches]
        review_required_batches_count = statuses.count("review_required")
        approved_for_delivery_batches_count = statuses.count("approved_for_delivery")
        delivered_batches_count = statuses.count("delivered")
        upstream_waiting_batches_count = sum(
            1
            for batch in batches
            if ScheduledReviewableReportingService._is_upstream_waiting_batch(batch)
        )
        report_ready_batches_count = (
            review_required_batches_count
            + approved_for_delivery_batches_count
            + delivered_batches_count
        )
        return {
            "failed_batches_count": statuses.count("failed"),
            "review_required_batches_count": review_required_batches_count,
            "approved_for_delivery_batches_count": approved_for_delivery_batches_count,
            "delivered_batches_count": delivered_batches_count,
            "upstream_waiting_batches_count": upstream_waiting_batches_count,
            "report_ready_batches_count": report_ready_batches_count,
        }

    @staticmethod
    def _manager_daily_selection_summary(selection: dict[str, Any]) -> dict[str, Any]:
        """Reduce raw candidate-selection diagnostics to one operator-readable row."""
        candidate_dates = [str(item) for item in list(selection.get("candidate_dates") or [])]
        selected_report_date = str(selection.get("selected_report_date") or "").strip()
        skipped_already_reported_dates = [
            str(item) for item in list(selection.get("skipped_already_reported_dates") or [])
        ]
        skipped_empty_dates = [
            str(item) for item in list(selection.get("skipped_empty_dates") or [])
        ]
        skipped_not_ready_dates = [
            str(item) for item in list(selection.get("skipped_not_ready_dates") or [])
        ]
        blocker_details = [
            dict(item)
            for item in list(selection.get("skipped_already_reported_details") or [])
            if isinstance(item, dict)
        ]
        blocker = blocker_details[0] if blocker_details else {}
        report_date = (
            selected_report_date
            or str(blocker.get("report_date") or "").strip()
            or (skipped_already_reported_dates[-1] if skipped_already_reported_dates else "")
            or (skipped_empty_dates[-1] if skipped_empty_dates else "")
            or (skipped_not_ready_dates[-1] if skipped_not_ready_dates else "")
            or (candidate_dates[-1] if candidate_dates else "")
            or None
        )
        selection_reason = str(selection.get("selection_reason") or "").strip()
        blocked_by_reason = str(blocker.get("blocked_by_reason") or "").strip()
        if selected_report_date:
            selection_status = "selected"
            reason = "selected"
        elif blocker:
            selection_status = "blocked"
            if blocked_by_reason == "matching_open_batch":
                reason = "blocked_by_open_batch"
            elif blocked_by_reason == "manager_day_idempotency_lock_busy":
                reason = "blocked_by_idempotency_lock"
            else:
                reason = "already_reported"
        elif skipped_empty_dates:
            selection_status = "skipped"
            reason = "no_calls"
        elif skipped_not_ready_dates:
            selection_status = "skipped"
            reason = "analysis_not_ready"
        else:
            selection_status = "skipped"
            reason = selection_reason or "no_candidate"

        return {
            "manager_id": str(selection.get("manager_id") or ""),
            "manager_name": selection.get("manager_name"),
            "report_date": report_date,
            "selection_status": selection_status,
            "reason": reason,
            "selection_reason": selection_reason,
            "calls_total": 0 if reason == "no_calls" else None,
            "calls_with_audio": None,
            "stt_ready": None,
            "llm1_ready": None,
            "analysis_ready": None,
            "blocked_by_batch_id": blocker.get("blocked_by_batch_id"),
            "blocked_by_batch_status": blocker.get("blocked_by_batch_status"),
            "blocked_by_draft_id": blocker.get("blocked_by_draft_id"),
            "blocked_by_draft_status": blocker.get("blocked_by_draft_status"),
            "blocked_by_reason": blocker.get("blocked_by_reason"),
            "match_source": blocker.get("match_source"),
            "recovery_hint": (
                f"inspect scheduled_report_batches id={blocker.get('blocked_by_batch_id')}"
                if blocker.get("blocked_by_batch_id")
                else None
            ),
        }

    @staticmethod
    def _with_manager_daily_run_summary(
        *,
        observability: dict[str, Any],
        run_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """Attach stable manager_daily run counters without hiding existing fields."""
        merged = dict(observability or {})
        payload = dict(run_summary)
        merged["scheduled_manager_daily_run"] = payload
        for key in (
            "report_batches_created",
            "batches_created",
            "created_batches_count",
            "diagnostic_batches_created",
            "expected_managers",
            "selected_manager_days",
            "selected_manager_days_count",
            "skipped_manager_days",
            "failed_batches_count",
            "review_required_batches_count",
            "report_ready_batches_count",
            "status",
            "failure_reason",
        ):
            merged[key] = payload.get(key)
        return merged

    def _send_manager_daily_zero_batch_alert(
        self,
        *,
        schedule: ReportingSchedule,
        planned_for: datetime,
        run_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a short fail-safe alert when a scheduled manager_daily run created no batch."""
        failure_reason = str(run_summary.get("failure_reason") or "manager_daily_zero_batches")
        report_date = str(run_summary.get("report_date") or planned_for.date().isoformat())
        run_id = f"manager_daily:{schedule.id}:{report_date}"
        operator_summary = self._manager_daily_zero_batch_operator_summary(
            schedule=schedule,
            run_summary=run_summary,
            run_id=run_id,
        )
        try:
            attempt = send_run_alert(
                "blocked",
                run_id=run_id,
                status="blocked",
                title="Manager daily scheduled run created no batch",
                level="warning",
                requested_by="scheduled_reviewable_reporting",
                scope={
                    "preset": "manager_daily",
                    "schedule_id": str(schedule.id),
                    "department_id": str(schedule.department_id),
                    "planned_for": _isoformat_utc(planned_for),
                    "candidate_dates": list(run_summary.get("candidate_dates") or []),
                },
                counts={
                    "expected_managers": run_summary.get("expected_managers"),
                    "selected_manager_days": run_summary.get("selected_manager_days"),
                    "skipped_manager_days": run_summary.get("skipped_manager_days"),
                    "created_batches": run_summary.get("batches_created"),
                },
                errors=[failure_reason],
                details={
                    "failure_reason": failure_reason,
                    "scheduled_manager_daily_run": run_summary,
                },
                operator_summary=operator_summary,
            )
        except Exception as exc:  # noqa: BLE001 - diagnostic batch must still be persisted
            attempt = {
                "channel": "email",
                "recipient": None,
                "status": "failed",
                "subject": None,
                "error": str(exc),
                "error_class": exc.__class__.__name__,
            }
        alert = {
            "kind": "manager_daily_scheduled_zero_batch",
            "channel": attempt.get("channel", "email"),
            "target": attempt.get("recipient"),
            "severity": "warning",
            "trigger": failure_reason,
            "status": attempt.get("status", "unknown"),
            "subject": attempt.get("subject"),
            "reason_codes": [failure_reason],
            "operator_summary": operator_summary,
        }
        for key in ("delivery", "reason", "error", "error_class"):
            if attempt.get(key) is not None:
                alert[key] = attempt[key]
        return alert

    def _send_manager_daily_failed_no_ready_alert(
        self,
        *,
        schedule: ReportingSchedule,
        planned_for: datetime,
        run_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """Alert when manager_daily created only failed/no-draft manager-day records."""
        failure_reason = str(
            run_summary.get("failure_reason")
            or "manager_daily_failed_batches_without_report_ready_batches"
        )
        report_date = str(run_summary.get("report_date") or planned_for.date().isoformat())
        run_id = f"manager_daily:{schedule.id}:{report_date}"
        operator_summary = self._manager_daily_failed_no_ready_operator_summary(
            run_summary=run_summary,
            run_id=run_id,
        )
        try:
            attempt = send_run_alert(
                "blocked",
                run_id=run_id,
                status="blocked",
                title="Manager daily reports are not ready",
                level="warning",
                requested_by="scheduled_reviewable_reporting",
                scope={
                    "preset": "manager_daily",
                    "schedule_id": str(schedule.id),
                    "department_id": str(schedule.department_id),
                    "planned_for": _isoformat_utc(planned_for),
                    "candidate_dates": list(run_summary.get("candidate_dates") or []),
                },
                counts={
                    "expected_managers": run_summary.get("expected_managers"),
                    "selected_manager_days": run_summary.get("selected_manager_days"),
                    "skipped_manager_days": run_summary.get("skipped_manager_days"),
                    "failed_batches": run_summary.get("failed_batches_count"),
                    "report_ready_batches": run_summary.get("report_ready_batches_count"),
                    "created_batches": run_summary.get("batches_created"),
                },
                errors=[failure_reason],
                details={
                    "failure_reason": failure_reason,
                    "scheduled_manager_daily_run": run_summary,
                },
                operator_summary=operator_summary,
            )
        except Exception as exc:  # noqa: BLE001 - schedule advancement must not depend on alerting
            attempt = {
                "channel": "email",
                "recipient": None,
                "status": "failed",
                "subject": None,
                "error": str(exc),
                "error_class": exc.__class__.__name__,
            }
        alert = {
            "kind": "manager_daily_scheduled_failed_no_ready_batch",
            "channel": attempt.get("channel", "email"),
            "target": attempt.get("recipient"),
            "severity": "warning",
            "trigger": failure_reason,
            "status": attempt.get("status", "unknown"),
            "subject": attempt.get("subject"),
            "reason_codes": [failure_reason],
            "operator_summary": operator_summary,
        }
        for key in ("delivery", "reason", "error", "error_class"):
            if attempt.get(key) is not None:
                alert[key] = attempt[key]
        return alert

    @staticmethod
    def _manager_daily_zero_batch_operator_summary(
        *,
        schedule: ReportingSchedule,
        run_summary: dict[str, Any],
        run_id: str,
    ) -> str:
        """Build a short operator alert body without embedding raw diagnostics JSON."""
        report_date = str(run_summary.get("report_date") or "-")
        selected = int(run_summary.get("selected_manager_days") or 0)
        skipped = int(run_summary.get("skipped_manager_days") or 0)
        expected = int(run_summary.get("expected_managers") or 0)
        rows = [dict(item) for item in list(run_summary.get("selection_summary") or [])]
        affected_lines: list[str] = []
        for row in rows[:5]:
            label = str(row.get("manager_name") or row.get("manager_id") or "unknown")
            reason = str(row.get("reason") or row.get("selection_reason") or "not_created")
            analysis_ready = row.get("analysis_ready")
            blocker = row.get("blocked_by_batch_id")
            suffix = "batch not created"
            if analysis_ready is not None:
                suffix = f"analysis_ready={analysis_ready}, {suffix}"
            if blocker:
                suffix = (
                    f"{suffix}; blocker batch={blocker}"
                    f" status={row.get('blocked_by_batch_status') or '-'}"
                )
            affected_lines.append(f"- {label}: {reason}, {suffix}")
        if len(rows) > 5:
            affected_lines.append(f"- {len(rows) - 5} more in observability/logs.")
        if not affected_lines:
            affected_lines.append("- No manager selection rows were recorded.")

        lines = [
            f"Daily reports: batches were not created for {report_date}",
            "",
            "What happened:",
            "Scheduled analysis processed the manager_daily schedule but created no report batches.",
            "",
            "Affected scope:",
            *affected_lines,
            "",
            "Impact:",
            "Managers and ROP will not receive daily reports automatically.",
            "",
            "What to check:",
            "scheduled_candidate_selection, open-batches diagnostics, analysis_worker logs.",
            "",
            (
                f"Summary: expected_managers={expected}, selected={selected}, "
                f"skipped={skipped}, batches_created=0."
            ),
            f"Run: {run_id}",
        ]
        text = "\n".join(lines)
        if len(text) <= 1500:
            return text
        return text[:1450].rstrip() + f"\nRun: {run_id}"

    @staticmethod
    def _manager_daily_failed_no_ready_operator_summary(
        *,
        run_summary: dict[str, Any],
        run_id: str,
    ) -> str:
        """Build a short alert body for failed manager-day batches without raw JSON."""
        report_date = str(run_summary.get("report_date") or "-")
        failed = int(run_summary.get("failed_batches_count") or 0)
        ready = int(run_summary.get("report_ready_batches_count") or 0)
        created = int(run_summary.get("batches_created") or 0)
        rows = [dict(item) for item in list(run_summary.get("selection_summary") or [])]
        affected_lines: list[str] = []
        for row in rows[:5]:
            label = str(row.get("manager_name") or row.get("manager_id") or "unknown")
            reason = str(row.get("reason") or row.get("selection_reason") or "failed")
            affected_lines.append(f"- {label}: {reason}, report not ready")
        if len(rows) > 5:
            affected_lines.append(f"- {len(rows) - 5} more in observability/logs.")
        if not affected_lines:
            affected_lines.append("- Manager-day batch failed before report-ready output.")
        lines = [
            f"Daily reports: reports are not ready for {report_date}",
            "",
            "What happened:",
            "Scheduled analysis created manager_daily batch records, but none became report-ready.",
            "",
            "Affected scope:",
            *affected_lines,
            "",
            "Impact:",
            "Reports are not ready; managers may not receive daily emails automatically.",
            "",
            "What to check:",
            "scheduled_candidate_selection, batch errors, report rendering/delivery observability.",
            "",
            f"Summary: batches_created={created}, failed_batches={failed}, report_ready={ready}.",
            f"Run: {run_id}",
        ]
        text = "\n".join(lines)
        if len(text) <= 1500:
            return text
        return text[:1450].rstrip() + f"\nRun: {run_id}"

    def _select_manager_day_candidate(
        self,
        *,
        schedule: ReportingSchedule,
        manager_id: str,
        candidate_dates: list[str],
        lookback_days: int,
        scan_started_at: str,
    ) -> ScheduledManagerDaySelection:
        """Pick the oldest not-yet-reported manager day with actual calls."""
        interactions_by_day = self._load_manager_interactions_by_day(
            department_id=schedule.department_id,
            manager_id=manager_id,
            candidate_dates=candidate_dates,
        )
        skipped_empty_dates: list[str] = []
        skipped_already_reported_dates: list[str] = []
        skipped_already_reported_details: list[dict[str, Any]] = []
        skipped_not_ready_dates: list[str] = []
        selected_report_date: str | None = None
        selection_reason = "no_candidate_empty_window"
        for candidate_date in candidate_dates:
            if not interactions_by_day.get(candidate_date):
                skipped_empty_dates.append(candidate_date)
                continue
            duplicate_diagnostics = self._manager_day_duplicate_diagnostics(
                schedule_id=schedule.id,
                department_id=schedule.department_id,
                preset=schedule.preset,
                manager_id=manager_id,
                report_date=candidate_date,
            )
            if duplicate_diagnostics["has_duplicate"]:
                skipped_already_reported_dates.append(candidate_date)
                skipped_already_reported_details.append(dict(duplicate_diagnostics))
                continue
            if selected_report_date is None:
                selected_report_date = candidate_date
                selection_reason = (
                    "selected_previous_day_with_calls"
                    if schedule.report_period_rule == "previous_day"
                    else "selected_oldest_unreported_date_with_calls"
                )
        if selected_report_date is None:
            if (
                schedule.report_period_rule == "previous_day"
                and skipped_empty_dates
                and not skipped_already_reported_dates
            ):
                selection_reason = "no_candidate_empty_previous_day"
            elif skipped_already_reported_dates and not skipped_empty_dates and not skipped_not_ready_dates:
                selection_reason = "no_candidate_all_reported"
            elif skipped_already_reported_dates or skipped_not_ready_dates:
                selection_reason = "no_candidate_after_skips"
        return ScheduledManagerDaySelection(
            manager_id=manager_id,
            candidate_dates=list(candidate_dates),
            selected_report_date=selected_report_date,
            skipped_empty_dates=skipped_empty_dates,
            skipped_already_reported_dates=skipped_already_reported_dates,
            skipped_already_reported_details=skipped_already_reported_details,
            skipped_not_ready_dates=skipped_not_ready_dates,
            selection_reason=selection_reason,
            scheduled_timezone=str(schedule.timezone),
            scan_started_at=scan_started_at,
            lookback_days=lookback_days,
        )

    def _load_manager_interactions_by_day(
        self,
        *,
        department_id: UUID,
        manager_id: str,
        candidate_dates: list[str],
    ) -> dict[str, list[Interaction]]:
        """Return persisted call interactions grouped by report-day string."""
        candidate_set = set(candidate_dates)
        try:
            manager_uuid = UUID(manager_id)
        except ValueError as exc:
            raise ASAError("manager_ids must contain valid UUID values.") from exc
        rows = (
            self.db.query(Interaction)
            .filter(
                Interaction.department_id == department_id,
                Interaction.manager_id == manager_uuid,
            )
            .all()
        )
        grouped: dict[str, list[Interaction]] = {item: [] for item in candidate_dates}
        for interaction in rows:
            call_started_at = parse_call_started_at(dict(interaction.metadata_ or {}))
            if call_started_at is None:
                continue
            call_day = call_started_at.date().isoformat()
            if call_day in candidate_set:
                grouped.setdefault(call_day, []).append(interaction)
        return grouped

    def _has_manager_day_duplicate(
        self,
        *,
        schedule_id: UUID,
        department_id: UUID,
        preset: str,
        manager_id: str,
        report_date: str,
    ) -> bool:
        """Return True when a manager-day scheduled record already protects this key."""
        return bool(
            self._manager_day_duplicate_diagnostics(
                schedule_id=schedule_id,
                department_id=department_id,
                preset=preset,
                manager_id=manager_id,
                report_date=report_date,
            )["has_duplicate"]
        )

    @staticmethod
    def _is_upstream_waiting_batch(batch: ScheduledReportBatch) -> bool:
        observability = dict(getattr(batch, "observability", None) or {})
        return (
            str(getattr(batch, "status", "") or "") == "paused"
            and bool(observability.get("upstream_waiting"))
            and str(observability.get("upstream_waiting_reason") or "")
            in MANAGER_DAILY_UPSTREAM_PENDING_REASONS
        )

    def _load_scheduled_batch_by_id(self, batch_id: str) -> ScheduledReportBatch | None:
        try:
            batch_uuid = UUID(str(batch_id))
        except ValueError:
            return None
        get = getattr(self.db, "get", None)
        if callable(get):
            row = get(ScheduledReportBatch, batch_uuid)
            if row is not None:
                return row
        rows = self.db.query(ScheduledReportBatch).filter(ScheduledReportBatch.id == batch_uuid).all()
        for row in rows:
            if str(getattr(row, "id", "") or "") == str(batch_uuid):
                return row
        return None

    def _find_upstream_waiting_batch_by_key(
        self,
        *,
        manager_id: str,
        report_date: str,
    ) -> ScheduledReportBatch | None:
        rows = (
            self.db.query(ScheduledReportBatch)
            .filter(ScheduledReportBatch.status == "paused")
            .all()
        )
        for row in rows:
            if not self._is_upstream_waiting_batch(row):
                continue
            if self._batch_matches_manager_day_key(
                batch=row,
                manager_id=manager_id,
                report_date=report_date,
            ):
                return row
        return None

    def _pending_upstream_retry_for_selection(
        self,
        *,
        selection: ScheduledManagerDaySelection,
    ) -> tuple[ScheduledManagerDaySelection, ScheduledReportBatch] | None:
        """Return an existing pending-upstream batch that should be retried now."""
        for detail in selection.skipped_already_reported_details:
            if str(detail.get("blocked_by_reason") or "") != "matching_open_batch":
                continue
            batch_id = str(detail.get("blocked_by_batch_id") or "").strip()
            batch = self._load_scheduled_batch_by_id(batch_id)
            report_date = str(detail.get("report_date") or "").strip()
            if not report_date:
                continue
            if batch is None:
                batch = self._find_upstream_waiting_batch_by_key(
                    manager_id=selection.manager_id,
                    report_date=report_date,
                )
            if batch is None or not self._is_upstream_waiting_batch(batch):
                continue
            retry_selection = replace(
                selection,
                selected_report_date=report_date,
                skipped_already_reported_dates=[
                    item for item in selection.skipped_already_reported_dates if item != report_date
                ],
                selection_reason="retry_waiting_upstream",
            )
            return retry_selection, batch
        return None

    def _manager_day_duplicate_diagnostics(
        self,
        *,
        schedule_id: UUID,
        department_id: UUID,
        preset: str,
        manager_id: str,
        report_date: str,
    ) -> dict[str, Any]:
        """Return concrete duplicate blocker diagnostics for one manager-day key."""
        diagnostics = self._empty_manager_day_duplicate_diagnostics(
            schedule_id=schedule_id,
            manager_id=manager_id,
            report_date=report_date,
        )
        legacy_checker = self.__dict__.get("_has_manager_day_duplicate")
        if legacy_checker is not None:
            diagnostics["has_duplicate"] = bool(
                legacy_checker(
                    schedule_id=schedule_id,
                    department_id=department_id,
                    preset=preset,
                    manager_id=manager_id,
                    report_date=report_date,
                )
            )
            if diagnostics["has_duplicate"]:
                diagnostics["blocked_by_reason"] = "matching_legacy_duplicate_guard"
            return diagnostics

        duplicate_statuses = tuple(
            dict.fromkeys(
                [
                    *SCHEDULED_MANAGER_DAILY_OPEN_BATCH_STATUSES,
                    *SCHEDULED_MANAGER_DAILY_REPORTED_BATCH_STATUSES,
                    "failed",
                ]
            )
        )
        batches = (
            self.db.query(ScheduledReportBatch)
            .filter(
                ScheduledReportBatch.schedule_id == schedule_id,
                ScheduledReportBatch.department_id == department_id,
                ScheduledReportBatch.preset == preset,
                ScheduledReportBatch.status.in_(list(duplicate_statuses)),
            )
            .all()
        )
        for batch in batches:
            batch_status = str(batch.status or "")
            batch_id = str(getattr(batch, "id", "") or "").strip() or None
            batch_matches = self._batch_matches_manager_day_key(
                batch=batch,
                manager_id=manager_id,
                report_date=report_date,
            )
            if batch_matches and batch_status in SCHEDULED_MANAGER_DAILY_OPEN_BATCH_STATUSES:
                diagnostics.update(
                    {
                        "has_duplicate": True,
                        "blocked_by_batch_id": batch_id,
                        "blocked_by_batch_status": batch_status,
                        "blocked_by_reason": "matching_open_batch",
                        "match_source": "batch_key",
                    }
                )
                return diagnostics
            if batch_matches and batch_status in SCHEDULED_MANAGER_DAILY_REPORTED_BATCH_STATUSES:
                diagnostics.update(
                    {
                        "has_duplicate": True,
                        "blocked_by_batch_id": batch_id,
                        "blocked_by_batch_status": batch_status,
                        "blocked_by_reason": "matching_reported_batch",
                        "match_source": "batch_key",
                    }
                )
                return diagnostics
            for draft in self._load_batch_drafts(batch.id):
                if str(draft.status or "") not in SCHEDULED_MANAGER_DAILY_REPORTED_DRAFT_STATUSES:
                    continue
                draft_match_source = self._draft_manager_day_match_source(
                    draft=draft,
                    preset=preset,
                    manager_id=manager_id,
                    report_date=report_date,
                )
                if draft_match_source is not None:
                    diagnostics.update(
                        {
                            "has_duplicate": True,
                            "blocked_by_batch_id": batch_id,
                            "blocked_by_batch_status": batch_status,
                            "blocked_by_draft_id": (
                                str(getattr(draft, "id", "") or "").strip() or None
                            ),
                            "blocked_by_draft_status": str(draft.status or ""),
                            "blocked_by_reason": "matching_reported_draft",
                            "match_source": draft_match_source,
                        }
                    )
                    return diagnostics
        return diagnostics

    def _manager_day_creation_guard_diagnostics(
        self,
        *,
        schedule: ReportingSchedule,
        planned_for: datetime,
        selection: ScheduledManagerDaySelection,
    ) -> dict[str, Any]:
        """Protect manager_daily batch creation for one schedule/planned/manager/day key."""
        report_date = str(selection.selected_report_date or "")
        diagnostics = self._manager_day_duplicate_diagnostics(
            schedule_id=schedule.id,
            department_id=schedule.department_id,
            preset=schedule.preset,
            manager_id=selection.manager_id,
            report_date=report_date,
        )
        if diagnostics["has_duplicate"]:
            return diagnostics

        lock_key = self._manager_day_creation_lock_key(
            schedule_id=schedule.id,
            planned_for=planned_for,
            manager_id=selection.manager_id,
            report_date=report_date,
        )
        if not self._try_acquire_manager_day_creation_lock(lock_key=lock_key):
            diagnostics.update(
                {
                    "has_duplicate": True,
                    "blocked_by_reason": "manager_day_idempotency_lock_busy",
                    "match_source": "advisory_lock",
                    "planned_for": _isoformat_utc(planned_for),
                    "lock_key": lock_key,
                }
            )
            return diagnostics

        return self._manager_day_duplicate_diagnostics(
            schedule_id=schedule.id,
            department_id=schedule.department_id,
            preset=schedule.preset,
            manager_id=selection.manager_id,
            report_date=report_date,
        )

    def _try_acquire_manager_day_creation_lock(self, *, lock_key: str) -> bool:
        """Acquire a PostgreSQL transaction advisory lock, falling back open in non-DB tests."""
        execute = getattr(self.db, "execute", None)
        if not callable(execute):
            return True

        bind = None
        get_bind = getattr(self.db, "get_bind", None)
        if callable(get_bind):
            bind = get_bind()
        dialect_name = str(getattr(getattr(bind, "dialect", None), "name", "") or "")
        if dialect_name and dialect_name != "postgresql":
            return True

        result = execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
            {"lock_id": self._manager_day_creation_lock_id(lock_key)},
        )
        scalar = getattr(result, "scalar", None)
        if callable(scalar):
            return bool(scalar())
        scalar_one = getattr(result, "scalar_one", None)
        if callable(scalar_one):
            return bool(scalar_one())
        return bool(result)

    @staticmethod
    def _manager_day_creation_lock_key(
        *,
        schedule_id: UUID,
        planned_for: datetime,
        manager_id: str,
        report_date: str,
    ) -> str:
        """Return the stable idempotency key for one scheduled manager-day occurrence."""
        return ":".join(
            [
                SCHEDULED_MANAGER_DAILY_IDEMPOTENCY_LOCK_NAMESPACE,
                str(schedule_id),
                _isoformat_utc(planned_for),
                str(manager_id),
                str(report_date),
            ]
        )

    @staticmethod
    def _manager_day_creation_lock_id(lock_key: str) -> int:
        """Map a lock key to PostgreSQL's signed bigint advisory-lock namespace."""
        digest = hashlib.blake2b(lock_key.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, byteorder="big", signed=False)
        if value >= 2**63:
            value -= 2**64
        return value

    @staticmethod
    def _selection_blocked_by_creation_guard(
        *,
        selection: ScheduledManagerDaySelection,
        duplicate_diagnostics: dict[str, Any],
    ) -> ScheduledManagerDaySelection:
        """Return selection diagnostics for a race blocked after candidate selection."""
        report_date = str(selection.selected_report_date or "")
        skipped_dates = list(selection.skipped_already_reported_dates)
        if report_date and report_date not in skipped_dates:
            skipped_dates.append(report_date)
        return replace(
            selection,
            selected_report_date=None,
            skipped_already_reported_dates=skipped_dates,
            skipped_already_reported_details=[
                *list(selection.skipped_already_reported_details),
                dict(duplicate_diagnostics),
            ],
            selection_reason="no_candidate_after_idempotency_guard",
        )

    @staticmethod
    def _empty_manager_day_duplicate_diagnostics(
        *,
        schedule_id: UUID,
        manager_id: str,
        report_date: str,
    ) -> dict[str, Any]:
        """Return the stable diagnostic shape for duplicate guard results."""
        return {
            "has_duplicate": False,
            "blocked_by_batch_id": None,
            "blocked_by_batch_status": None,
            "blocked_by_draft_id": None,
            "blocked_by_draft_status": None,
            "blocked_by_reason": None,
            "manager_id": manager_id,
            "report_date": report_date,
            "schedule_id": str(schedule_id),
            "match_source": None,
        }

    @staticmethod
    def _batch_matches_manager_day_key(
        *,
        batch: ScheduledReportBatch,
        manager_id: str,
        report_date: str,
    ) -> bool:
        """Match duplicate key fields available on the scheduled batch JSON columns."""
        observability = dict(batch.observability or {})
        selection = dict(observability.get("scheduled_candidate_selection") or {})
        if selection and selection.get("selected_report_date") != report_date:
            return False
        period = dict(batch.period or {})
        if str(period.get("date_from") or "") != report_date:
            return False
        if str(period.get("date_to") or report_date) != report_date:
            return False
        filters = dict(batch.filters or {})
        manager_ids = {str(item) for item in list(filters.get("manager_ids") or [])}
        return manager_id in manager_ids

    @staticmethod
    def _draft_matches_manager_day_key(
        *,
        draft: ScheduledReportDraft,
        preset: str,
        manager_id: str,
        report_date: str,
    ) -> bool:
        """Match duplicate key fields embedded in draft group/payload metadata."""
        return (
            ScheduledReviewableReportingService._draft_manager_day_match_source(
                draft=draft,
                preset=preset,
                manager_id=manager_id,
                report_date=report_date,
            )
            is not None
        )

    @staticmethod
    def _draft_manager_day_match_source(
        *,
        draft: ScheduledReportDraft,
        preset: str,
        manager_id: str,
        report_date: str,
    ) -> str | None:
        """Return which draft metadata source matched the manager-day key."""
        group_key = str(draft.group_key or "")
        if group_key == f"{preset}:{manager_id}:{report_date}":
            return "draft_group_key"
        payload = dict(draft.generated_payload or {})
        meta = dict(payload.get("meta") or {})
        period = dict(meta.get("period") or {})
        header = dict(payload.get("header") or {})
        payload_report_date = (
            str(header.get("report_date") or "").strip()
            or str(period.get("date_from") or "").strip()
        )
        if payload_report_date != report_date:
            return None
        payload_manager_id = (
            str(meta.get("manager_id") or "").strip()
            or str(header.get("manager_id") or "").strip()
        )
        if payload_manager_id == manager_id:
            return "draft_payload_meta"
        return None

    def _run_due_manager_day_selection(
        self,
        *,
        schedule: ReportingSchedule,
        planned_for: datetime,
        selection: ScheduledManagerDaySelection,
        creation_guarded: bool = False,
        existing_batch: ScheduledReportBatch | None = None,
        rop_digest_report_items: list[dict[str, Any]] | None = None,
    ) -> ScheduledReportBatch | None:
        """Run the orchestrator for one selected manager/report-date pair."""
        report_date = str(selection.selected_report_date or "")
        if not report_date:
            return None
        if not creation_guarded and existing_batch is None:
            duplicate_diagnostics = self._manager_day_creation_guard_diagnostics(
                schedule=schedule,
                planned_for=planned_for,
                selection=selection,
            )
            if duplicate_diagnostics["has_duplicate"]:
                return None
        period = SchedulePeriod(date_from=report_date, date_to=report_date)
        production_auto_delivery = _manager_daily_auto_delivery_enabled(schedule)
        sla_deadline = _manager_daily_sla_deadline(
            planned_for=planned_for,
            timezone_name=str(schedule.timezone),
        )
        filters = ReportRunFilters(
            manager_ids={selection.manager_id},
            date_from=period.date_from,
            date_to=period.date_to,
        )
        batch = existing_batch or self._create_scheduled_batch(
            schedule=schedule,
            planned_for=planned_for,
            period=period,
            manager_ids=[selection.manager_id],
            selection=selection,
        )
        if existing_batch is not None:
            batch.planned_for = planned_for
            batch.period = {"date_from": period.date_from, "date_to": period.date_to}
            batch.filters = {
                "manager_ids": [selection.manager_id],
                "manager_extensions": [],
            }
        self._transition_batch_status(batch, "queued")
        batch.queued_at = datetime.now(UTC)
        self.db.flush()

        self._transition_batch_status(batch, "running")
        batch.started_at = datetime.now(UTC)
        self.db.flush()

        orchestrator = CallsManualReportingOrchestrator(
            department_id=str(schedule.department_id),
            db=self.db,
        )
        try:
            result = asyncio.run(
                orchestrator.run_report(
                    preset_code=schedule.preset,
                    mode=schedule.mode,
                    filters=filters,
                    model_override=None,
                    send_email=production_auto_delivery,
                    send_manager_daily_rop_bundle=False,
                    retain_runtime_rop_bundle_attachments=production_auto_delivery,
                )
            )
        except Exception as exc:
            self._transition_batch_status(batch, "failed")
            batch.failed_at = datetime.now(UTC)
            batch.errors = [f"{exc.__class__.__name__}: {exc}"]
            batch.observability = self._with_manager_daily_sla_observability(
                observability=self._with_candidate_selection_observability(
                    observability=dict(batch.observability or {}),
                    selection=selection,
                ),
                sla_deadline=sla_deadline,
                review_required=_schedule_requires_review(schedule),
                status="not_applicable" if _schedule_requires_review(schedule) else "blocked",
                missed_reason="report_run_failed",
            )
            self.db.flush()
            return batch

        source_summary = dict(
            ((result.get("observability") or {}).get("summary") or {}).get("source") or {}
        )
        analysis_scope = self._scheduled_analysis_scope_diagnostics(
            schedule=schedule,
            period=period,
            manager_ids=[selection.manager_id],
            source_summary=source_summary,
        )
        base_observability = self._with_candidate_selection_observability(
            observability={**dict(result.get("observability") or {}), **analysis_scope},
            selection=selection,
        )
        batch.diagnostics = {
            **dict(result.get("diagnostics") or {}),
            **analysis_scope,
            "analysis_scope": analysis_scope,
            "scheduled_candidate_selection": selection.to_observability(),
        }
        batch.errors = list(result.get("errors") or [])

        drafts_created = 0
        draft_assessments: list[dict[str, Any]] = []
        rop_daily_delivery = dict(result.get("rop_daily_delivery") or {})
        completed_at = datetime.now(UTC)
        upstream_pending_reason = self._manager_daily_upstream_pending_reason(result)
        for report in result.get("reports") or []:
            payload = dict(report.get("payload") or {})
            if not payload:
                continue
            assessment = self._assess_manager_daily_scheduled_delivery(
                report=report,
                production_auto_delivery=production_auto_delivery,
                completed_at=completed_at,
                sla_deadline=sla_deadline,
            )
            draft_delivery = self._with_manager_daily_draft_delivery_observability(
                delivery=dict(report.get("delivery") or {}),
                assessment=assessment,
                rop_daily_delivery=rop_daily_delivery,
            )
            draft_errors = self._unique_errors(
                [
                    *list(report.get("errors") or []),
                    *list(assessment.get("errors") or []),
                ]
            )
            draft = ScheduledReportDraft(
                batch_id=batch.id,
                department_id=schedule.department_id,
                preset=schedule.preset,
                group_key=str(
                    report.get("group_key")
                    or f"{schedule.preset}:{selection.manager_id}:{report_date}"
                ),
                status=str(assessment["draft_status"]),
                generated_payload=payload,
                generated_blocks=extract_editable_blocks(preset=schedule.preset, payload=payload),
                edited_blocks={},
                edit_audit=[],
                preview=dict(report.get("preview") or {}) or None,
                artifact=dict(report.get("artifact") or {}) or None,
                delivery=draft_delivery,
                errors=draft_errors,
            )
            self.db.add(draft)
            drafts_created += 1
            draft_assessments.append(assessment)
            if production_auto_delivery and rop_digest_report_items is not None:
                rop_digest_report_items.append(
                    self._scheduled_rop_digest_report_item(
                        schedule=schedule,
                        selection=selection,
                        report=report,
                        assessment=assessment,
                    )
                )

        if production_auto_delivery:
            if upstream_pending_reason:
                next_batch_status = "paused"
            else:
                next_batch_status = self._manager_daily_production_batch_status(
                    drafts_created=drafts_created,
                    assessments=draft_assessments,
                )
        else:
            next_batch_status = "review_required" if drafts_created > 0 else "failed"
        batch.observability = self._with_manager_daily_batch_delivery_observability(
            observability=base_observability,
            assessments=draft_assessments,
            drafts_created=drafts_created,
            production_auto_delivery=production_auto_delivery,
            sla_deadline=sla_deadline,
            rop_daily_delivery=rop_daily_delivery,
        )
        if upstream_pending_reason:
            batch.observability = self._with_manager_daily_upstream_wait_observability(
                observability=dict(batch.observability or {}),
                selection=selection,
                sla_deadline=sla_deadline,
                reason=upstream_pending_reason,
                source_summary=dict(result.get("observability", {}).get("summary", {}).get("source") or {}),
            )
        batch.errors = self._unique_errors(
            [
                *list(batch.errors or []),
                *([upstream_pending_reason] if upstream_pending_reason else []),
                *[
                    error
                    for assessment in draft_assessments
                    for error in list(assessment.get("errors") or [])
                ],
            ]
        )
        self._transition_batch_status(batch, next_batch_status)
        if batch.status == "review_required":
            batch.review_required_at = datetime.now(UTC)
        elif batch.status == "delivered":
            batch.delivered_at = completed_at
        elif batch.status == "paused":
            batch.paused_at = datetime.now(UTC)
        else:
            batch.failed_at = datetime.now(UTC)
        self.db.flush()
        return batch

    @staticmethod
    def _unique_errors(values: list[Any]) -> list[str]:
        """Return non-empty error strings without duplicates, preserving order."""
        errors: list[str] = []
        for value in values:
            error = str(value or "").strip()
            if error and error not in errors:
                errors.append(error)
        return errors

    @staticmethod
    def _manager_daily_upstream_pending_reason(result: dict[str, Any]) -> str | None:
        """Return the upstream waiting reason from a reporting run result."""
        status = str(result.get("status") or "").strip()
        if status in MANAGER_DAILY_UPSTREAM_PENDING_REASONS:
            return status
        errors = {str(item).strip() for item in list(result.get("errors") or [])}
        for reason in MANAGER_DAILY_UPSTREAM_PENDING_REASONS:
            if reason in errors:
                return reason
        source = dict(
            ((result.get("observability") or {}).get("summary") or {}).get("source")
            or {}
        )
        reason = str(source.get("call_processing_readiness") or "").strip()
        if reason in MANAGER_DAILY_UPSTREAM_PENDING_REASONS and bool(
            source.get("call_processing_waiting_upstream")
        ):
            return reason
        return None

    def _with_manager_daily_upstream_wait_observability(
        self,
        *,
        observability: dict[str, Any],
        selection: ScheduledManagerDaySelection,
        sla_deadline: datetime,
        reason: str,
        source_summary: dict[str, Any],
    ) -> dict[str, Any]:
        """Attach pending upstream handoff details to one manager-day batch."""
        rop_email_status = str(observability.get("rop_email_status") or "skipped")
        merged = self._with_manager_daily_sla_observability(
            observability=observability,
            sla_deadline=sla_deadline,
            review_required=False,
            status="blocked",
            missed_reason=reason,
            manager_email_status="not_started",
            rop_email_status=rop_email_status,
            sla_missed=False,
        )
        merged.update(
            {
                "status": reason,
                "run_state": "waiting_upstream",
                "upstream_waiting": True,
                "upstream_waiting_reason": reason,
                "manager_email_status": "not_started",
                "scheduled_candidate_selection": selection.to_observability(),
                "call_processing_run_id": source_summary.get("call_processing_run_id"),
                "call_processing_scope_hash": source_summary.get("call_processing_scope_hash"),
                "call_processing_status": source_summary.get("call_processing_status"),
                "call_processing_readiness": source_summary.get("call_processing_readiness") or reason,
                "artifacts_ready": source_summary.get("call_processing_artifacts_ready"),
                "artifacts_missing": source_summary.get("call_processing_artifacts_missing"),
                "last_finished_at": source_summary.get("last_finished_at"),
                "last_seen_at": source_summary.get("last_seen_at"),
                "next_action": "retry_upstream_readiness",
                "blockers": [reason],
            }
        )
        if rop_email_status:
            merged["rop_email_status"] = rop_email_status
        return merged

    def _finalize_upstream_not_ready_before_deadline(
        self,
        *,
        batch: ScheduledReportBatch,
        planned_for: datetime,
        timezone_name: str,
    ) -> None:
        """Turn an exhausted upstream wait into a terminal manager-day status."""
        sla_deadline = _manager_daily_sla_deadline(
            planned_for=planned_for,
            timezone_name=timezone_name,
        )
        observability = dict(batch.observability or {})
        observability.update(
            {
                "status": MANAGER_DAILY_UPSTREAM_DEADLINE_REASON,
                "run_state": "failed",
                "upstream_waiting": False,
                "upstream_waiting_reason": MANAGER_DAILY_UPSTREAM_DEADLINE_REASON,
                "next_action": "manual_upstream_check",
                "blockers": [MANAGER_DAILY_UPSTREAM_DEADLINE_REASON],
            }
        )
        batch.observability = self._with_manager_daily_sla_observability(
            observability=observability,
            sla_deadline=sla_deadline,
            review_required=False,
            status="blocked",
            missed_reason=MANAGER_DAILY_UPSTREAM_DEADLINE_REASON,
            manager_email_status="not_started",
            rop_email_status=str(observability.get("rop_email_status") or "skipped"),
            sla_missed=True,
        )
        batch.errors = self._unique_errors(
            [*list(batch.errors or []), MANAGER_DAILY_UPSTREAM_DEADLINE_REASON]
        )
        self._transition_batch_status(batch, "failed")
        batch.failed_at = datetime.now(UTC)

    @staticmethod
    def _manager_daily_report_gate_block_reason(report: dict[str, Any]) -> str | None:
        """Return a stable blocker when manager-facing gates reject business delivery."""
        gate = dict(report.get("manager_facing_completeness") or {})
        strict_gate = dict(report.get("strict_report_day_gate") or {})
        payload = dict(report.get("payload") or {})
        meta = dict(payload.get("meta") or {})
        if not gate:
            gate = dict(meta.get("manager_facing_completeness") or {})
        if not strict_gate:
            strict_gate = dict(meta.get("strict_report_day_gate") or {})

        if gate and not bool(gate.get("manager_report_allowed")):
            return "manager_facing_gate_failed"
        if strict_gate and not bool(strict_gate.get("manager_report_allowed")):
            reason_codes = list(strict_gate.get("reason_codes") or [])
            if reason_codes:
                return "strict_report_day_gate_failed:" + ",".join(
                    str(item) for item in reason_codes
                )
            return "strict_report_day_gate_failed"
        if str(report.get("status") or "").strip() == "review_required":
            errors = [str(item) for item in list(report.get("errors") or [])]
            if any(item.startswith("manager_facing_gate_failed") for item in errors):
                return "manager_facing_gate_failed"
            if any(item.startswith("manager_daily_strict_report_day_failed") for item in errors):
                return "strict_report_day_gate_failed"
        return None

    def _assess_manager_daily_scheduled_delivery(
        self,
        *,
        report: dict[str, Any],
        production_auto_delivery: bool,
        completed_at: datetime,
        sla_deadline: datetime,
    ) -> dict[str, Any]:
        """Classify one manager_daily report for scheduled batch/draft status."""
        transport = dict((report.get("delivery") or {}).get("transport") or {})
        email = dict(transport.get("email_delivery") or {})
        resolved_email = dict(transport.get("resolved_email") or {})
        primary_email = str(
            resolved_email.get("primary_email") or email.get("primary_email") or ""
        ).strip()
        email_status = str(email.get("status") or "").strip()
        email_error = str(email.get("error") or "").strip()
        artifact = dict(report.get("artifact") or {})
        pdf_filename = str(artifact.get("filename") or "").strip()
        gate_block_reason = self._manager_daily_report_gate_block_reason(report)
        cc_emails = list(resolved_email.get("cc_emails") or email.get("cc_emails") or [])

        if not production_auto_delivery:
            return {
                "sla_deadline_at": _isoformat_utc(sla_deadline),
                "draft_status": "review_required",
                "sla_status": "not_applicable",
                "sla_missed": False,
                "sla_missed_reason": None,
                "manager_email_status": email_status or "skipped",
                "primary_email": primary_email or None,
                "cc_emails": cc_emails,
                "recipient_resolve_status": "resolved" if primary_email else "not_required",
                "delivered_at": None,
                "late_delivery_at": None,
                "errors": [],
            }

        blocker: str | None = None
        if not pdf_filename:
            blocker = "missing_pdf"
        elif not primary_email:
            blocker = "missing_recipient"
        elif gate_block_reason:
            blocker = "analysis_not_ready"

        if blocker:
            missed = completed_at > sla_deadline
            return {
                "sla_deadline_at": _isoformat_utc(sla_deadline),
                "draft_status": "failed",
                "sla_status": "blocked",
                "sla_missed": missed,
                "sla_missed_reason": blocker,
                "manager_email_status": "blocked",
                "primary_email": primary_email or None,
                "cc_emails": cc_emails,
                "recipient_resolve_status": "missing" if blocker == "missing_recipient" else "resolved",
                "delivered_at": None,
                "late_delivery_at": None,
                "errors": (
                    [blocker]
                    if blocker == gate_block_reason
                    else self._unique_errors([blocker, gate_block_reason])
                ),
            }

        if email_status == "delivered":
            late = completed_at > sla_deadline
            return {
                "sla_deadline_at": _isoformat_utc(sla_deadline),
                "draft_status": "delivered",
                "sla_status": "late" if late else "on_time",
                "sla_missed": late,
                "sla_missed_reason": "delivered_after_sla_deadline" if late else None,
                "manager_email_status": "delivered",
                "primary_email": primary_email or None,
                "cc_emails": cc_emails,
                "recipient_resolve_status": "resolved",
                "delivered_at": completed_at,
                "late_delivery_at": completed_at if late else None,
                "errors": [],
            }

        delivery_failed = email_status in {"failed", "blocked"} or bool(email_error)
        reason = "delivery_failed" if delivery_failed else "manager_email_not_delivered"
        if email_error:
            reason = f"{reason}:{email_error}"
        missed = completed_at > sla_deadline
        return {
            "sla_deadline_at": _isoformat_utc(sla_deadline),
            "draft_status": "failed",
            "sla_status": "blocked" if delivery_failed else "missed_pending",
            "sla_missed": missed,
            "sla_missed_reason": reason,
            "manager_email_status": email_status or "not_started",
            "primary_email": primary_email or None,
            "cc_emails": cc_emails,
            "recipient_resolve_status": "resolved",
            "delivered_at": None,
            "late_delivery_at": None,
            "errors": [reason],
        }

    @staticmethod
    def _with_manager_daily_draft_delivery_observability(
        *,
        delivery: dict[str, Any],
        assessment: dict[str, Any],
        rop_daily_delivery: dict[str, Any],
    ) -> dict[str, Any]:
        """Attach manager_daily SLA/delivery fields to draft.delivery JSON."""
        merged = dict(delivery or {})
        delivered_at = assessment.get("delivered_at")
        late_delivery_at = assessment.get("late_delivery_at")
        merged.update(
            {
                "sla_deadline_at": assessment.get("sla_deadline_at"),
                "delivered_at": (
                    _isoformat_utc(delivered_at)
                    if isinstance(delivered_at, datetime)
                    else None
                ),
                "sla_status": assessment.get("sla_status"),
                "sla_missed": bool(assessment.get("sla_missed")),
                "sla_missed_reason": assessment.get("sla_missed_reason"),
                "late_delivery_at": (
                    _isoformat_utc(late_delivery_at)
                    if isinstance(late_delivery_at, datetime)
                    else None
                ),
                "manager_email_status": assessment.get("manager_email_status"),
                "primary_email": assessment.get("primary_email"),
                "cc_emails": list(assessment.get("cc_emails") or []),
                "recipient_resolve_status": assessment.get("recipient_resolve_status"),
                "rop_email_status": str(rop_daily_delivery.get("status") or "skipped"),
                "rop_daily_delivery": rop_daily_delivery,
            }
        )
        return merged

    @staticmethod
    def _manager_daily_production_batch_status(
        *,
        drafts_created: int,
        assessments: list[dict[str, Any]],
    ) -> str:
        """Derive the scheduled batch status from production delivery outcomes."""
        if drafts_created <= 0 or not assessments:
            return "failed"
        statuses = {str(item.get("draft_status") or "") for item in assessments}
        if statuses == {"delivered"}:
            return "delivered"
        if statuses and statuses.issubset({"failed"}):
            return "failed"
        return "failed"

    def _with_manager_daily_batch_delivery_observability(
        self,
        *,
        observability: dict[str, Any],
        assessments: list[dict[str, Any]],
        drafts_created: int,
        production_auto_delivery: bool,
        sla_deadline: datetime,
        rop_daily_delivery: dict[str, Any],
    ) -> dict[str, Any]:
        """Attach aggregate manager_daily SLA/delivery fields to batch observability."""
        merged = dict(observability or {})
        if not production_auto_delivery:
            return self._with_manager_daily_sla_observability(
                observability=merged,
                sla_deadline=sla_deadline,
                review_required=True,
                status="not_applicable",
                missed_reason=None,
            )
        if not assessments:
            now_utc = datetime.now(UTC)
            return self._with_manager_daily_sla_observability(
                observability=merged,
                sla_deadline=sla_deadline,
                review_required=False,
                status="missed_pending" if now_utc > sla_deadline else "blocked",
                missed_reason="no_deliverable_report",
                manager_email_status="not_started",
                rop_email_status=str(rop_daily_delivery.get("status") or "skipped"),
                sla_missed=now_utc > sla_deadline,
            )

        delivered_assessments = [
            item for item in assessments if str(item.get("draft_status") or "") == "delivered"
        ]
        first = assessments[0]
        delivered_at = first.get("delivered_at")
        late_delivery_at = first.get("late_delivery_at")
        primary_email = str(first.get("primary_email") or "").strip() or None
        cc_emails = list(first.get("cc_emails") or [])
        recipient_resolve_status = str(first.get("recipient_resolve_status") or "").strip() or None
        if len(delivered_assessments) == len(assessments):
            status = (
                "late"
                if any(bool(item.get("sla_missed")) for item in assessments)
                else "on_time"
            )
            missed = status == "late"
            reason = "delivered_after_sla_deadline" if missed else None
        else:
            status = (
                "blocked"
                if any(str(item.get("sla_status") or "") == "blocked" for item in assessments)
                else "missed_pending"
            )
            missed = any(bool(item.get("sla_missed")) for item in assessments)
            reason = str(first.get("sla_missed_reason") or "manager_daily_delivery_blocked")
        return self._with_manager_daily_sla_observability(
            observability=merged,
            sla_deadline=sla_deadline,
            review_required=False,
            status=status,
            missed_reason=reason,
            manager_email_status=str(first.get("manager_email_status") or "unknown"),
            rop_email_status=str(rop_daily_delivery.get("status") or "skipped"),
            primary_email=primary_email,
            cc_emails=cc_emails,
            recipient_resolve_status=recipient_resolve_status,
            sla_missed=missed,
            delivered_at=delivered_at if isinstance(delivered_at, datetime) else None,
            late_delivery_at=late_delivery_at if isinstance(late_delivery_at, datetime) else None,
        )

    @staticmethod
    def _with_manager_daily_sla_observability(
        *,
        observability: dict[str, Any],
        sla_deadline: datetime,
        review_required: bool,
        status: str,
        missed_reason: str | None,
        manager_email_status: str | None = None,
        rop_email_status: str | None = None,
        primary_email: str | None = None,
        cc_emails: list[str] | None = None,
        recipient_resolve_status: str | None = None,
        sla_missed: bool | None = None,
        delivered_at: datetime | None = None,
        late_delivery_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Return observability with stable SLA/delivery keys."""
        merged = dict(observability or {})
        missed = bool(sla_missed) if sla_missed is not None else False
        merged.update(
            {
                "sla_deadline_at": _isoformat_utc(sla_deadline),
                "delivered_at": _isoformat_utc(delivered_at),
                "sla_status": status,
                "sla_missed": missed,
                "sla_missed_reason": missed_reason,
                "late_delivery_at": _isoformat_utc(late_delivery_at),
                "manager_email_status": manager_email_status,
                "primary_email": primary_email,
                "cc_emails": list(cc_emails or []),
                "recipient_resolve_status": recipient_resolve_status,
                "rop_email_status": rop_email_status,
                "review_required": bool(review_required),
            }
        )
        return merged

    def _record_skipped_manager_day_selection(
        self,
        *,
        schedule: ReportingSchedule,
        planned_for: datetime,
        selection: ScheduledManagerDaySelection,
    ) -> ScheduledReportBatch:
        """Persist an operator-visible no-draft record for empty/already-reported windows."""
        fallback_period = _compute_report_period(
            rule=schedule.report_period_rule,
            local_run_at=planned_for.astimezone(ZoneInfo(schedule.timezone)),
        )
        batch = self._create_scheduled_batch(
            schedule=schedule,
            planned_for=planned_for,
            period=fallback_period,
            manager_ids=[selection.manager_id],
            selection=selection,
        )
        self._transition_batch_status(batch, "queued")
        batch.queued_at = datetime.now(UTC)
        self._transition_batch_status(batch, "running")
        batch.started_at = datetime.now(UTC)
        skip_reason = (
            "no_calls_for_report_day"
            if selection.selection_reason == "no_candidate_empty_previous_day"
            else selection.selection_reason
        )
        analysis_scope = self._scheduled_analysis_scope_diagnostics(
            schedule=schedule,
            period=fallback_period,
            manager_ids=[selection.manager_id],
        )
        batch.observability = self._with_manager_daily_sla_observability(
            observability=self._with_candidate_selection_observability(
                observability={
                    **analysis_scope,
                    "status": "skipped",
                    "run_state": "skipped_without_manager_report",
                    "blockers": [],
                    "alerts": [],
                    "summary": {"alerts": {"attempted": 0, "statuses": []}},
                },
                selection=selection,
            ),
            sla_deadline=_manager_daily_sla_deadline(
                planned_for=planned_for,
                timezone_name=str(schedule.timezone),
            ),
            review_required=_schedule_requires_review(schedule),
            status="not_applicable",
            missed_reason=skip_reason,
        )
        batch.diagnostics = {
            **analysis_scope,
            "analysis_scope": dict(analysis_scope),
            "scheduled_candidate_selection": selection.to_observability(),
        }
        batch.errors = [selection.selection_reason]
        self._transition_batch_status(batch, "failed")
        batch.failed_at = datetime.now(UTC)
        self.db.flush()
        return batch

    def _record_manager_daily_zero_batch_failure(
        self,
        *,
        schedule: ReportingSchedule,
        planned_for: datetime,
        failure_reason: str,
        alert_records: list[dict[str, Any]],
    ) -> ScheduledReportBatch:
        """Persist a diagnostic failed batch when a due manager_daily scan made no records."""
        fallback_period = _compute_report_period(
            rule=schedule.report_period_rule,
            local_run_at=planned_for.astimezone(ZoneInfo(schedule.timezone)),
        )
        batch = self._create_scheduled_batch(
            schedule=schedule,
            planned_for=planned_for,
            period=fallback_period,
            manager_ids=[str(item) for item in list(schedule.manager_ids or [])],
            selection=None,
        )
        analysis_scope = self._scheduled_analysis_scope_diagnostics(
            schedule=schedule,
            period=fallback_period,
            manager_ids=[str(item) for item in list(schedule.manager_ids or [])],
        )
        batch.observability = self._with_manager_daily_sla_observability(
            observability={
                **analysis_scope,
                "status": "failed",
                "run_state": "failed_without_scheduled_batch",
                "failure_reason": failure_reason,
                "blockers": [failure_reason],
                "alerts": [dict(item) for item in alert_records],
                "summary": {
                    "alerts": {
                        "attempted": len(alert_records),
                        "statuses": [
                            str(item.get("status") or "unknown") for item in alert_records
                        ],
                    }
                },
            },
            sla_deadline=_manager_daily_sla_deadline(
                planned_for=planned_for,
                timezone_name=str(schedule.timezone),
            ),
            review_required=_schedule_requires_review(schedule),
            status="blocked",
            missed_reason=failure_reason,
        )
        batch.diagnostics = {
            **analysis_scope,
            "analysis_scope": dict(analysis_scope),
            "scheduled_manager_daily_run": {
                "failure_reason": failure_reason,
                "created_batches_before_guard_count": 0,
            }
        }
        batch.errors = [failure_reason]
        self._transition_batch_status(batch, "failed")
        batch.failed_at = datetime.now(UTC)
        self.db.flush()
        return batch

    def _create_scheduled_batch(
        self,
        *,
        schedule: ReportingSchedule,
        planned_for: datetime,
        period: SchedulePeriod,
        manager_ids: list[str],
        selection: ScheduledManagerDaySelection | None = None,
    ) -> ScheduledReportBatch:
        """Create the common scheduled batch row without running delivery."""
        analysis_scope = self._scheduled_analysis_scope_diagnostics(
            schedule=schedule,
            period=period,
            manager_ids=manager_ids,
        )
        observability = (
            self._with_candidate_selection_observability(
                observability=dict(analysis_scope),
                selection=selection,
            )
            if selection is not None
            else dict(analysis_scope)
        )
        batch = ScheduledReportBatch(
            schedule_id=schedule.id,
            department_id=schedule.department_id,
            preset=schedule.preset,
            mode=schedule.mode,
            report_period_rule=schedule.report_period_rule,
            status="planned",
            planned_for=planned_for,
            period={"date_from": period.date_from, "date_to": period.date_to},
            filters={
                "manager_ids": list(manager_ids),
                "manager_extensions": [],
            },
            business_email_enabled=bool(schedule.business_email_enabled),
            review_required=_schedule_requires_review(schedule),
            observability=observability,
            diagnostics=(
                {
                    **analysis_scope,
                    "analysis_scope": dict(analysis_scope),
                    "scheduled_candidate_selection": selection.to_observability(),
                }
                if selection is not None
                else {**analysis_scope, "analysis_scope": dict(analysis_scope)}
            ),
            errors=[],
        )
        self.db.add(batch)
        self.db.flush()
        return batch

    @staticmethod
    def _scheduled_analysis_scope_diagnostics(
        *,
        schedule: ReportingSchedule,
        period: SchedulePeriod,
        manager_ids: list[str],
        source_summary: dict[str, Any] | None = None,
        scope_source: str = "reporting_schedule.manager_ids",
    ) -> dict[str, Any]:
        """Return downstream analysis scope separately from upstream source scope."""
        normalized_manager_ids = [
            str(item)
            for item in list(manager_ids or [])
            if str(item or "").strip()
        ]
        source = dict(source_summary or {})
        upstream_scope_match = str(source.get("call_processing_scope_match") or "").strip() or None
        upstream_scope_wider_than_analysis = (
            True if upstream_scope_match == "covering" and bool(normalized_manager_ids) else None
        )
        diagnostics: dict[str, Any] = {
            "analysis_scope_source": scope_source,
            "analysis_department_id": str(schedule.department_id),
            "analysis_manager_ids": normalized_manager_ids,
            "analysis_manager_count": len(normalized_manager_ids),
            "analysis_date_from": period.date_from,
            "analysis_date_to": period.date_to,
            "analysis_dates": {
                "date_from": period.date_from,
                "date_to": period.date_to,
            },
        }
        for key in (
            "call_processing_scope_match",
            "call_processing_requested_scope_hash",
            "call_processing_covering_scope_hash",
        ):
            if source.get(key) is not None:
                diagnostics[key] = source.get(key)
        if upstream_scope_wider_than_analysis is not None:
            diagnostics["upstream_scope_wider_than_analysis"] = upstream_scope_wider_than_analysis
        return diagnostics

    @staticmethod
    def _with_candidate_selection_observability(
        *,
        observability: dict[str, Any],
        selection: ScheduledManagerDaySelection | None,
    ) -> dict[str, Any]:
        """Attach candidate diagnostics both top-level and under a named block."""
        if selection is None:
            return observability
        merged = dict(observability)
        selection_payload = selection.to_observability()
        merged["scheduled_candidate_selection"] = selection_payload
        for key, value in selection_payload.items():
            merged[key] = value
        return merged

    def _advance_schedule(self, *, schedule: ReportingSchedule, after_utc: datetime) -> datetime:
        """Advance next_run_at after one execution."""
        next_local = _next_local_occurrence(
            start_date=schedule.start_date,
            start_time=schedule.start_time,
            timezone_name=schedule.timezone,
            recurrence_type=schedule.recurrence_type,
            now_utc=after_utc + timedelta(seconds=1),
        )
        return next_local.astimezone(UTC)

    def _has_open_batch(self, *, schedule_id: UUID) -> bool:
        """Return True when schedule already has an unfinished batch."""
        return (
            self.db.query(ScheduledReportBatch)
            .filter(
                ScheduledReportBatch.schedule_id == schedule_id,
                ScheduledReportBatch.status.in_(
                    [
                        "planned",
                        "queued",
                        "running",
                        "review_required",
                        "approved_for_delivery",
                        "paused",
                    ]
                ),
            )
            .first()
            is not None
        )

    def _get_batch_for_occurrence(
        self,
        *,
        schedule_id: UUID,
        planned_for: datetime,
    ) -> ScheduledReportBatch | None:
        """Return an already created batch for the exact due occurrence."""
        return (
            self.db.query(ScheduledReportBatch)
            .filter(
                ScheduledReportBatch.schedule_id == schedule_id,
                ScheduledReportBatch.planned_for == planned_for,
            )
            .first()
        )

    def _get_latest_open_batch(self, *, schedule_id: UUID) -> ScheduledReportBatch | None:
        """Return the newest unfinished batch for one schedule."""
        return (
            self.db.query(ScheduledReportBatch)
            .filter(
                ScheduledReportBatch.schedule_id == schedule_id,
                ScheduledReportBatch.status.in_(
                    [
                        "planned",
                        "queued",
                        "running",
                        "review_required",
                        "approved_for_delivery",
                        "paused",
                    ]
                ),
            )
            .order_by(ScheduledReportBatch.created_at.desc())
            .first()
        )

    def _transition_batch_status(
        self,
        batch: ScheduledReportBatch,
        next_status: str,
    ) -> None:
        """Enforce the allowed scheduled batch lifecycle transitions."""
        current_status = str(batch.status)
        allowed = SCHEDULED_REVIEWABLE_BATCH_ALLOWED_TRANSITIONS.get(current_status, ())
        if next_status not in allowed:
            raise ASAError(
                "scheduled_reviewable_reporting.invalid_batch_transition: "
                f"{current_status} -> {next_status}"
            )
        batch.status = next_status

    def _get_schedule(self, schedule_id: str) -> ReportingSchedule:
        """Load one schedule or fail."""
        item = (
            self.db.query(ReportingSchedule)
            .filter(ReportingSchedule.id == UUID(schedule_id))
            .first()
        )
        if item is None:
            raise ASAError("Schedule not found.")
        return item

    def _get_batch(self, batch_id: str) -> ScheduledReportBatch:
        """Load one batch or fail."""
        item = (
            self.db.query(ScheduledReportBatch)
            .filter(ScheduledReportBatch.id == UUID(batch_id))
            .first()
        )
        if item is None:
            raise ASAError("Scheduled review batch not found.")
        return item

    def _get_draft(self, draft_id: str) -> ScheduledReportDraft:
        """Load one draft or fail."""
        item = (
            self.db.query(ScheduledReportDraft)
            .filter(ScheduledReportDraft.id == UUID(draft_id))
            .first()
        )
        if item is None:
            raise ASAError("Scheduled review draft not found.")
        return item

    def _load_batch_drafts(self, batch_id: UUID) -> list[ScheduledReportDraft]:
        """Load drafts for one batch."""
        return (
            self.db.query(ScheduledReportDraft)
            .filter(ScheduledReportDraft.batch_id == batch_id)
            .order_by(ScheduledReportDraft.created_at.asc())
            .all()
        )

    def _serialize_schedule(self, schedule: ReportingSchedule) -> dict[str, Any]:
        """Serialize one schedule for UI/API responses."""
        department = (
            self.db.query(Department)
            .filter(Department.id == schedule.department_id)
            .first()
        )
        department_name = department.name if department is not None else "Не найден департамент"
        manager_ids = list(schedule.manager_ids or [])
        manager_map = {
            str(item.id): item
            for item in self.db.query(Manager)
            .filter(Manager.id.in_([UUID(item) for item in manager_ids]) if manager_ids else False)
            .all()
        } if manager_ids else {}
        manager_labels = []
        for manager_id in manager_ids:
            manager = manager_map.get(manager_id)
            if manager is None:
                manager_labels.append(
                    {
                        "id": manager_id,
                        "label": "Не найден менеджер",
                        "secondary_label": manager_id,
                    }
                )
                continue
            primary = manager.name
            if manager.extension:
                primary = f"{manager.name} ({manager.extension})"
            manager_labels.append(
                {
                    "id": manager_id,
                    "label": primary,
                    "secondary_label": manager_id,
                }
            )
        return {
            "id": str(schedule.id),
            "operating_mode": SCHEDULED_REVIEWABLE_OPERATING_MODE,
            "department_id": str(schedule.department_id),
            "department_label": {
                "label": department_name,
                "secondary_label": str(schedule.department_id),
            },
            "preset": schedule.preset,
            "manager_ids": manager_ids,
            "manager_labels": manager_labels,
            "enabled": bool(schedule.enabled),
            "start_date": schedule.start_date.isoformat(),
            "start_time": schedule.start_time,
            "timezone": schedule.timezone,
            "recurrence_type": schedule.recurrence_type,
            "report_period_rule": schedule.report_period_rule,
            "mode": schedule.mode,
            "business_email_enabled": bool(schedule.business_email_enabled),
            "review_required": _schedule_requires_review(schedule),
            "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
            "last_planned_at": schedule.last_planned_at.isoformat() if schedule.last_planned_at else None,
            "deleted": schedule.deleted_at is not None,
            "deleted_at": schedule.deleted_at.isoformat() if schedule.deleted_at else None,
        }

    def _serialize_batch(self, batch: ScheduledReportBatch) -> dict[str, Any]:
        """Serialize one batch with its drafts."""
        drafts = self._load_batch_drafts(batch.id)
        return {
            "id": str(batch.id),
            "schedule_id": str(batch.schedule_id),
            "department_id": str(batch.department_id),
            "preset": batch.preset,
            "mode": batch.mode,
            "report_period_rule": batch.report_period_rule,
            "status": batch.status,
            "planned_for": batch.planned_for.isoformat(),
            "period": dict(batch.period or {}),
            "filters": dict(batch.filters or {}),
            "business_email_enabled": bool(batch.business_email_enabled),
            "review_required": bool(batch.review_required),
            "approved_by": batch.approved_by,
            "errors": list(batch.errors or []),
            "observability": dict(batch.observability or {}),
            "diagnostics": dict(batch.diagnostics or {}),
            "drafts": [self._serialize_draft(item) for item in drafts],
        }

    def _serialize_draft(self, draft: ScheduledReportDraft) -> dict[str, Any]:
        """Serialize one reviewable draft."""
        generated_blocks = dict(draft.generated_blocks or {})
        edited_blocks = dict(draft.edited_blocks or {})
        effective_payload = (
            apply_editable_blocks(
                preset=draft.preset,
                payload=dict(draft.generated_payload or {}),
                edited_blocks=edited_blocks,
            )
            if draft.generated_payload
            else None
        )
        return {
            "id": str(draft.id),
            "batch_id": str(draft.batch_id),
            "preset": draft.preset,
            "group_key": draft.group_key,
            "status": draft.status,
            "generated_blocks": generated_blocks,
            "edited_blocks": edited_blocks,
            "editable_block_keys": list(_editable_block_keys(preset=draft.preset)),
            "preview": dict(draft.preview or {}),
            "artifact": dict(draft.artifact or {}),
            "delivery": dict(draft.delivery or {}),
            "errors": list(draft.errors or []),
            "edit_audit": list(draft.edit_audit or []),
            "effective_payload": effective_payload,
        }
