"""Bounded scheduled reviewable reporting before pilot."""

from __future__ import annotations

import asyncio
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
    render_report_email,
    resolve_report_preset,
)
from app.core_shared.db.models import (
    Department,
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
    "running": ("review_required", "failed", "paused"),
    "review_required": ("approved_for_delivery", "failed", "paused"),
    "approved_for_delivery": ("delivered", "failed"),
    "delivered": (),
    "failed": (),
    "paused": ("queued", "failed"),
}
SCHEDULED_REVIEWABLE_DEFAULT_EDITOR = "operator_ui"
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
            review_required=True,
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
            review_required=True,
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
                    ["planned", "queued", "running", "review_required", "approved_for_delivery"]
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
                    ["planned", "queued", "running", "review_required", "approved_for_delivery"]
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
            "review_required": True,
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
