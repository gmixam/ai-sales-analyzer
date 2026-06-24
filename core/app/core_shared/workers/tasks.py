"""Shared worker tasks."""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import sys
from argparse import Namespace
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agents.call_processing import (
    CallProcessingService,
    EnsureMode,
    ProcessingScope,
    RequiredArtifactKind,
)
from app.agents.calls.run_alerts import send_run_alert
from app.agents.calls.scheduled_reporting import ScheduledReviewableReportingService
from app.core_shared.config.settings import settings
from app.core_shared.db.session import get_db
from app.core_shared.workers.celery_app import (
    MANAGER_DAILY_SLA_HARDCHECK_TASK,
    MANAGER_DAILY_SLA_PRECHECK_TASK,
    SCHEDULED_CALL_PROCESSING_UPSTREAM_TASK,
    SCHEDULED_REPORTING_TASK,
    celery_app,
)

DAILY_UPSTREAM_REQUIRED_ARTIFACTS: tuple[RequiredArtifactKind, ...] = (
    RequiredArtifactKind.TRANSCRIPT,
    RequiredArtifactKind.TRANSCRIPT_SEGMENTS,
    RequiredArtifactKind.LLM1_FIRST_PASS,
)

_REPORT_SCRIPTS_PACKAGE = "report_scripts"
_SCHEDULED_REPORTING_PREFLIGHT_MODULE = (
    f"{_REPORT_SCRIPTS_PACKAGE}.scheduled_reporting_preflight"
)
_SCHEDULED_REPORTING_PREFLIGHT_FILE = "scheduled_reporting_preflight.py"


@celery_app.task(name="calls.scan_scheduled_reviewable_reporting")
def scan_scheduled_reviewable_reporting() -> dict:
    """Scan due schedules and create reviewable report batches."""
    try:
        with get_db() as db:
            service = ScheduledReviewableReportingService(db=db)
            return service.scan_due_schedules()
    except Exception as exc:  # noqa: BLE001 - scheduled automation must notify and re-raise.
        _send_scheduled_reporting_alert(exc)
        raise


@celery_app.task(name=MANAGER_DAILY_SLA_PRECHECK_TASK)
def manager_daily_sla_precheck(*, report_date: str = "auto") -> dict[str, Any]:
    """Run the safe manager_daily SLA precheck without starting report generation."""
    return _run_manager_daily_sla_check(phase="precheck", report_date=report_date)


@celery_app.task(name=MANAGER_DAILY_SLA_HARDCHECK_TASK)
def manager_daily_sla_hardcheck(*, report_date: str = "auto") -> dict[str, Any]:
    """Run the safe manager_daily hard SLA check without starting report generation."""
    return _run_manager_daily_sla_check(phase="hard", report_date=report_date)


def _run_manager_daily_sla_check(*, phase: str, report_date: str) -> dict[str, Any]:
    """Delegate to the existing scheduled_reporting_preflight sla-check command logic."""
    task_name = (
        MANAGER_DAILY_SLA_HARDCHECK_TASK
        if phase == "hard"
        else MANAGER_DAILY_SLA_PRECHECK_TASK
    )
    started_at = datetime.now(UTC)
    try:
        scheduled_reporting_preflight = _load_scheduled_reporting_preflight()

        result = scheduled_reporting_preflight.sla_check(
            Namespace(date=report_date, phase=phase)
        )
    except Exception as exc:  # noqa: BLE001 - scheduled SLA checks must notify and fail visibly.
        _send_manager_daily_sla_task_alert(exc, phase=phase, report_date=report_date)
        raise

    return {
        "task": task_name,
        "task_status": "completed",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "phase": phase,
        "report_date": report_date,
        "billable_pipeline_started": False,
        "sla_check": result,
    }


def _load_scheduled_reporting_preflight() -> ModuleType:
    """Import the runtime-mounted scheduled reporting preflight module."""
    _ensure_report_scripts_import_roots()
    try:
        return importlib.import_module(_SCHEDULED_REPORTING_PREFLIGHT_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name not in {
            _REPORT_SCRIPTS_PACKAGE,
            _SCHEDULED_REPORTING_PREFLIGHT_MODULE,
        }:
            raise
        module_path = _find_scheduled_reporting_preflight_path()
        if module_path is None:
            raise
        return _load_report_script_module_from_path(module_path)


def _ensure_report_scripts_import_roots() -> None:
    """Make report_scripts importable without relying on Celery's cwd."""
    for root in _report_scripts_import_root_candidates():
        if not (root / _REPORT_SCRIPTS_PACKAGE).is_dir():
            continue
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)


def _report_scripts_import_root_candidates() -> tuple[Path, ...]:
    core_root = Path(__file__).resolve().parents[3]
    return _unique_paths((core_root, Path("/app")))


def _find_scheduled_reporting_preflight_path() -> Path | None:
    core_root = Path(__file__).resolve().parents[3]
    candidates = _unique_paths(
        (
            core_root / _REPORT_SCRIPTS_PACKAGE / _SCHEDULED_REPORTING_PREFLIGHT_FILE,
            Path("/app") / _REPORT_SCRIPTS_PACKAGE / _SCHEDULED_REPORTING_PREFLIGHT_FILE,
            core_root.parent / "scripts" / _SCHEDULED_REPORTING_PREFLIGHT_FILE,
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _load_report_script_module_from_path(module_path: Path) -> ModuleType:
    package = sys.modules.get(_REPORT_SCRIPTS_PACKAGE)
    if package is None:
        package = ModuleType(_REPORT_SCRIPTS_PACKAGE)
        package.__path__ = [str(module_path.parent)]  # type: ignore[attr-defined]
        package.__package__ = _REPORT_SCRIPTS_PACKAGE
        package.__spec__ = importlib.machinery.ModuleSpec(
            _REPORT_SCRIPTS_PACKAGE,
            loader=None,
            is_package=True,
        )
        sys.modules[_REPORT_SCRIPTS_PACKAGE] = package

    spec = importlib.util.spec_from_file_location(
        _SCHEDULED_REPORTING_PREFLIGHT_MODULE,
        module_path,
    )
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(
            f"Cannot load {_SCHEDULED_REPORTING_PREFLIGHT_MODULE} from {module_path}"
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[_SCHEDULED_REPORTING_PREFLIGHT_MODULE] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(_SCHEDULED_REPORTING_PREFLIGHT_MODULE, None)
        raise
    setattr(package, "scheduled_reporting_preflight", module)
    return module


def _unique_paths(paths: Sequence[Path]) -> tuple[Path, ...]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return tuple(unique)


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
        alert = _send_daily_upstream_alert(
            "blocked",
            run_id="scheduled-call-processing-upstream",
            status="blocked",
            title="Daily call-processing upstream blocked",
            level="warning",
            scope={},
            counts={},
            errors=["provider_call_budget_not_configured"],
            details={"reason": "provider_call_budget_not_configured"},
        )
        return {
            **base_payload,
            "task_status": "skipped",
            "reason": "provider_call_budget_not_configured",
            "alerts": [alert],
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
        alert = _send_daily_upstream_alert(
            "failed",
            run_id="scheduled-call-processing-upstream",
            status="failed",
            title="Daily call-processing upstream failed",
            level="error",
            scope={},
            counts={},
            errors=[{"class": exc.__class__.__name__, "message": str(exc)}],
            details={"phase": "call_processing.ensure_daily_upstream"},
        )
        return {
            **base_payload,
            "task_status": "failed",
            "finished_at": datetime.now(UTC).isoformat(),
            "error": {
                "class": exc.__class__.__name__,
                "message": str(exc),
            },
            "alerts": [alert],
        }

    response_payload = response.model_dump(mode="json")
    status = str(response_payload.get("status") or "")
    alert = None
    if not dry_run and status not in {"ready", "completed"}:
        alert = _send_daily_upstream_alert(
            "blocked",
            run_id=str(response_payload.get("run_id") or "scheduled-call-processing-upstream"),
            status=status or "unknown",
            title="Daily call-processing upstream needs attention",
            level="warning",
            scope=scope.model_dump(mode="json", exclude_none=True),
            counts=response_payload.get("planned", {}),
            errors=response_payload.get("errors", []),
            details={
                "quota": response_payload.get("quota", {}),
                "costs": response_payload.get("costs", {}),
            },
        )
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
        "alerts": [alert] if alert is not None else [],
    }


def _send_daily_upstream_alert(
    event: str,
    *,
    run_id: str,
    status: str,
    title: str,
    level: str,
    scope: dict[str, Any],
    counts: dict[str, Any],
    errors: list[Any],
    details: dict[str, Any],
) -> dict[str, Any]:
    """Send fail-safe technical alert for scheduled call-processing upstream."""
    attempt = send_run_alert(
        event,
        run_id=run_id,
        status=status,
        title=title,
        level=level,
        requested_by="scheduled_call_processing_upstream",
        scope=scope,
        counts=counts,
        errors=errors,
        details=details,
    )
    attempt["kind"] = "scheduled_call_processing_upstream"
    attempt["trigger"] = status
    attempt["severity"] = level
    return attempt


def _send_scheduled_reporting_alert(exc: Exception) -> dict[str, Any]:
    """Send fail-safe technical alert when scheduled reporting scan itself fails."""
    attempt = send_run_alert(
        "failed",
        run_id="scheduled-reviewable-reporting-scan",
        status="failed",
        title="Scheduled reporting scan failed",
        level="error",
        requested_by="scheduled_reviewable_reporting",
        scope={"task": SCHEDULED_REPORTING_TASK},
        counts={},
        errors=[{"class": exc.__class__.__name__, "message": str(exc)}],
        details={"phase": "scan_due_schedules"},
    )
    attempt["kind"] = "scheduled_reviewable_reporting_scan"
    attempt["trigger"] = "task_exception"
    attempt["severity"] = "error"
    return attempt


def _send_manager_daily_sla_task_alert(
    exc: Exception,
    *,
    phase: str,
    report_date: str,
) -> dict[str, Any]:
    """Send a short human-readable alert when the scheduled SLA task itself fails."""
    level = "critical" if phase == "hard" else "warning"
    event = "failed" if phase == "hard" else "blocked"
    run_id = f"manager_daily_sla:{report_date}:{phase}"
    attempt = send_run_alert(
        event,
        run_id=run_id,
        status="failed",
        title=f"manager_daily SLA {phase} task failed",
        level=level,
        requested_by="scheduled_manager_daily_sla",
        scope={"preset": "manager_daily", "phase": phase, "report_date": report_date},
        counts={},
        errors=[f"{exc.__class__.__name__}: {exc}"],
        details={"phase": "scheduled_reporting_preflight.sla-check"},
        operator_summary="\n".join(
            [
                f"manager_daily SLA {phase} не завершился.",
                "",
                "Что проверить:",
                "scheduled_reporting_preflight.sla-check, DB access, delivery config.",
                "",
                f"Run: {run_id}",
            ]
        ),
    )
    attempt["kind"] = "manager_daily_sla_check"
    attempt["trigger"] = "task_exception"
    attempt["severity"] = level
    return attempt


def get_registered_tasks() -> Sequence[str]:
    """Return registered bounded worker tasks."""
    return (
        SCHEDULED_REPORTING_TASK,
        SCHEDULED_CALL_PROCESSING_UPSTREAM_TASK,
        MANAGER_DAILY_SLA_PRECHECK_TASK,
        MANAGER_DAILY_SLA_HARDCHECK_TASK,
    )
