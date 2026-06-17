"""Bounded scheduled reviewable reporting before pilot."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.agents.calls.reporting import (
    CallsManualReportingOrchestrator,
    REPORTING_ALLOWED_MODES,
    ReportRunFilters,
    parse_call_started_at,
    render_report_email,
    resolve_report_preset,
)
from app.core_shared.db.models import (
    Department,
    Interaction,
    Manager,
    ReportingSchedule,
    ScheduledReportBatch,
    ScheduledReportDraft,
)
from app.core_shared.exceptions import ASAError

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
MANAGER_DAILY_SLA_DEADLINE_TIME = time(10, 0)
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


def _manager_daily_auto_delivery_enabled(schedule: ReportingSchedule) -> bool:
    """Return True for production manager_daily delivery schedules."""
    return (
        str(getattr(schedule, "preset", "") or "").strip() == "manager_daily"
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

        batch.observability = dict(result.get("observability") or {})
        batch.diagnostics = dict(result.get("diagnostics") or {})
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
            str(getattr(schedule, "preset", "") or "").strip() == "manager_daily"
            and str(getattr(schedule, "recurrence_type", "") or "").strip().lower() == "daily"
            and bool(list(getattr(schedule, "manager_ids", None) or []))
        )

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
        for manager_id in list(schedule.manager_ids or []):
            selection = self._select_manager_day_candidate(
                schedule=schedule,
                manager_id=str(manager_id),
                candidate_dates=candidate_dates,
                lookback_days=lookback_days,
                scan_started_at=scan_started_at,
            )
            if selection.selected_report_date:
                self._run_due_manager_day_selection(
                    schedule=schedule,
                    planned_for=planned_for,
                    selection=selection,
                )
            else:
                self._record_skipped_manager_day_selection(
                    schedule=schedule,
                    planned_for=planned_for,
                    selection=selection,
                )

        schedule.last_planned_at = planned_for
        schedule.next_run_at = self._advance_schedule(schedule=schedule, after_utc=now_utc)
        self.db.flush()

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
    ) -> None:
        """Run the orchestrator for one selected manager/report-date pair."""
        report_date = str(selection.selected_report_date or "")
        if not report_date:
            return
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
        batch = self._create_scheduled_batch(
            schedule=schedule,
            planned_for=planned_for,
            period=period,
            manager_ids=[selection.manager_id],
            selection=selection,
        )
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
            return

        base_observability = self._with_candidate_selection_observability(
            observability=dict(result.get("observability") or {}),
            selection=selection,
        )
        batch.diagnostics = {
            **dict(result.get("diagnostics") or {}),
            "scheduled_candidate_selection": selection.to_observability(),
        }
        batch.errors = list(result.get("errors") or [])

        drafts_created = 0
        draft_assessments: list[dict[str, Any]] = []
        rop_daily_delivery = dict(result.get("rop_daily_delivery") or {})
        completed_at = datetime.now(UTC)
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

        if production_auto_delivery:
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
        batch.errors = self._unique_errors(
            [
                *list(batch.errors or []),
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
        else:
            batch.failed_at = datetime.now(UTC)
        self.db.flush()

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

        if not production_auto_delivery:
            return {
                "sla_deadline_at": _isoformat_utc(sla_deadline),
                "draft_status": "review_required",
                "sla_status": "not_applicable",
                "sla_missed": False,
                "sla_missed_reason": None,
                "manager_email_status": email_status or "skipped",
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
            blocker = gate_block_reason

        if blocker:
            missed = completed_at > sla_deadline
            return {
                "sla_deadline_at": _isoformat_utc(sla_deadline),
                "draft_status": "review_required",
                "sla_status": "blocked",
                "sla_missed": missed,
                "sla_missed_reason": blocker,
                "manager_email_status": email_status or "blocked",
                "delivered_at": None,
                "late_delivery_at": None,
                "errors": [blocker],
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
                "delivered_at": completed_at,
                "late_delivery_at": completed_at if late else None,
                "errors": [],
            }

        delivery_failed = email_status in {"failed", "blocked"} or bool(email_error)
        reason = (
            "manager_email_delivery_failed"
            if delivery_failed
            else "manager_email_not_delivered"
        )
        if email_error:
            reason = f"{reason}:{email_error}"
        missed = completed_at > sla_deadline
        return {
            "sla_deadline_at": _isoformat_utc(sla_deadline),
            "draft_status": "failed" if delivery_failed else "review_required",
            "sla_status": "blocked" if delivery_failed else "missed_pending",
            "sla_missed": missed,
            "sla_missed_reason": reason,
            "manager_email_status": email_status or "not_started",
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
        return "review_required"

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
    ) -> None:
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
        batch.observability = self._with_manager_daily_sla_observability(
            observability=self._with_candidate_selection_observability(
                observability={
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
        batch.diagnostics = {"scheduled_candidate_selection": selection.to_observability()}
        batch.errors = [selection.selection_reason]
        self._transition_batch_status(batch, "failed")
        batch.failed_at = datetime.now(UTC)
        self.db.flush()

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
        observability = (
            self._with_candidate_selection_observability(observability={}, selection=selection)
            if selection is not None
            else None
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
                {"scheduled_candidate_selection": selection.to_observability()}
                if selection is not None
                else None
            ),
            errors=[],
        )
        self.db.add(batch)
        self.db.flush()
        return batch

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
