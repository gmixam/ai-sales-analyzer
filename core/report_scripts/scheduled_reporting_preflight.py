#!/usr/bin/env python3
"""Inspect and operate scheduled reviewable reporting without the operator UI."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen
from uuid import UUID
from zoneinfo import ZoneInfo

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.agents.calls.reporting import parse_call_started_at
from app.agents.calls.run_alerts import send_run_alert
from app.agents.calls.scheduled_reporting import (
    SCHEDULED_REVIEWABLE_BATCH_ALLOWED_TRANSITIONS,
    ScheduledReviewableReportingService,
)
from app.core_shared.db.models import (
    Analysis,
    CallArtifact,
    Interaction,
    Manager,
    ReportingSchedule,
    ScheduledReportBatch,
    ScheduledReportDraft,
)
from app.core_shared.db.session import get_db
from app.core_shared.exceptions import ASAError
from app.core_shared.runtime_identity import REQUIRED_CODE_MARKERS
from app.core_shared.workers.celery_app import (
    ANALYSIS_QUEUE,
    CALL_PROCESSING_QUEUE,
    RUNTIME_IDENTITY_TASK,
    celery_app,
)


SLA_TIMEZONE = "Asia/Almaty"
SLA_PRECHECK_TIME = time(hour=9, minute=30)
SLA_HARD_TIME = time(hour=10, minute=0)
NO_AUDIO_INTERACTION_STATUS = "NO_AUDIO"
UPSTREAM_ARTIFACT_KINDS = ("transcript", "transcript_segments", "llm1_first_pass")
ACTIVE_MANAGER_DAILY_BATCH_STATUSES = (
    "planned",
    "queued",
    "running",
    "review_required",
    "approved_for_delivery",
    "delivered",
    "failed",
    "paused",
)
OPEN_BATCH_STATUSES = (
    "planned",
    "queued",
    "running",
    "review_required",
    "approved_for_delivery",
)
RECOVERABLE_BATCH_STATUSES = (*OPEN_BATCH_STATUSES, "paused")
SLA_ALERT_MAX_AFFECTED = 5
POST_RUN_AUDIT_MAX_ITEMS = 5
ROP_DIGEST_SENT_STATUSES = {"sent", "delivered"}
ROP_DIGEST_FAILED_STATUSES = {"failed", "error"}
ROP_DIGEST_BLOCKED_STATUSES = {"blocked"}
ROP_DIGEST_NO_CALLS_REASONS = {
    "no_calls",
    "no_calls_for_report_day",
    "no_candidate_empty_previous_day",
    "no_audio_calls_for_report_day",
}
DEFAULT_RECOVERY_REASON = (
    "closed_by_operator_recovery: "
    "superseded_test_batch_blocked_production_schedule"
)
SLA_REASON_LABELS = {
    "sla_missed": "отчет не доставлен до SLA",
    "missing_artifacts": "не хватило готовых данных для отчета",
    "email_failed": "ошибка отправки email",
    "manager_email_failed": "письмо менеджеру не отправлено",
    "manager_email_blocked": "доставка письма менеджеру заблокирована",
    "manager_email_not_started": "отправка письма менеджеру не началась",
    "manager_email_planned": "отправка письма менеджеру еще не завершена",
    "no_calls": "за день нет звонков в scope",
    "no_audio": "звонки есть, но аудио недоступно",
    "stt_error": "ошибка транскрибации",
    "llm_error": "ошибка анализа",
    "llm2_admission_non_commercial_or_unusable": "звонок не принят в коммерческий разбор",
    "quota": "ограничение бюджета или лимита",
    "budget": "ограничение бюджета или лимита",
    "read_timeout": "таймаут при ожидании сервиса",
    "ReadTimeout": "таймаут при ожидании сервиса",
    "no_calls_for_report_day": "за день нет звонков в scope",
    "no_audio_calls_for_report_day": "звонки есть, но аудио недоступно",
    "upstream_stt_not_ready": "транскрибация еще не готова",
    "upstream_llm1_not_ready": "первичный анализ еще не готов",
    "analysis_not_ready": "анализ еще не готов",
    "missing_recipient": "нет email получателя для отчета",
    "delivery_failed": "техническая ошибка отправки отчета",
    "scheduled_batch_missing": "нет готового batch для отчета",
    "scheduled_draft_missing": "нет готового черновика отчета",
    "pdf_not_ready": "нет готового PDF отчета",
    "manager_report_not_delivered": "отчет менеджеру не доставлен",
}


def _resolve_sla_report_date(
    raw_date: str | None,
    *,
    now_utc: datetime | None = None,
) -> date:
    normalized = str(raw_date or "auto").strip().lower()
    if normalized in {"", "auto", "previous_day", "prev_day", "yesterday"}:
        current_utc = now_utc or datetime.now(UTC)
        if current_utc.tzinfo is None:
            current_utc = current_utc.replace(tzinfo=UTC)
        local_now = current_utc.astimezone(ZoneInfo(SLA_TIMEZONE))
        return local_now.date() - timedelta(days=1)
    return date.fromisoformat(str(raw_date))


def _normalize_manager_ids(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        candidate = str(value).strip()
        if not candidate:
            continue
        UUID(candidate)
        if candidate not in normalized:
            normalized.append(candidate)
    return normalized


def _manager_ids_overlap(existing: list[str], requested: list[str]) -> bool:
    if not existing or not requested:
        return True
    return bool(set(existing) & set(requested))


def _active_schedule_conflicts(
    schedules: list[dict[str, Any]],
    *,
    department_id: str,
    preset: str,
    manager_ids: list[str],
    recurrence: str,
    period_rule: str,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for item in schedules:
        if item.get("deleted"):
            continue
        if not item.get("enabled"):
            continue
        if str(item.get("department_id")) != str(department_id):
            continue
        if str(item.get("preset")) != str(preset):
            continue
        if str(item.get("recurrence_type")) != str(recurrence):
            continue
        if str(item.get("report_period_rule")) != str(period_rule):
            continue
        existing_manager_ids = [str(value) for value in item.get("manager_ids") or []]
        if _manager_ids_overlap(existing_manager_ids, manager_ids):
            conflicts.append(item)
    return conflicts


def _summarize_conflicts(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "preset": item.get("preset"),
            "enabled": item.get("enabled"),
            "department_id": item.get("department_id"),
            "manager_ids": item.get("manager_ids") or [],
            "start_time": item.get("start_time"),
            "timezone": item.get("timezone"),
            "mode": item.get("mode"),
            "business_email_enabled": item.get("business_email_enabled"),
            "next_run_at": item.get("next_run_at"),
        }
        for item in conflicts
    ]


def _print_status(result: dict[str, Any]) -> None:
    print("Scheduled reporting preflight")
    print(f"Schedules: {len(result['schedules'])}")
    for item in result["schedules"]:
        print(
            f"- {item['id']} | {item['preset']} | enabled={item['enabled']} | "
            f"next_run_at={item.get('next_run_at') or '-'} | "
            f"mode={item['mode']} | business_email={item['business_email_enabled']}"
        )
    print(f"Recent batches: {len(result['review_queue'])}")
    for batch in result["review_queue"][:10]:
        print(
            f"- {batch['id']} | {batch['preset']} | status={batch['status']} | "
            f"planned_for={batch.get('planned_for') or '-'} | drafts={len(batch.get('drafts') or [])}"
        )


def _emit(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if result.get("action") == "status":
        _print_status(result)
    elif result.get("action") == "runtime_status":
        print(_format_runtime_status(result))
    elif result.get("action") == "sla_status":
        print(_format_sla_status(result))
    elif result.get("action") == "post_run_audit":
        print(_format_post_run_audit(result))
    elif result.get("action") == "open_batch_diagnostics":
        print(_format_open_batch_diagnostics(result))
    elif result.get("action") == "open_batch_recovery":
        print(_format_recovery_plan(result))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def status() -> dict[str, Any]:
    with get_db() as db:
        service = ScheduledReviewableReportingService(db=db)
        return {
            "status": "ok",
            "action": "status",
            "schedules": service.list_schedules(),
            "review_queue": service.list_review_batches(),
        }


def scan_due() -> dict[str, Any]:
    with get_db() as db:
        service = ScheduledReviewableReportingService(db=db)
        summary = service.scan_due_schedules()
        return {"status": "ok", "action": "scan_due", **summary}


def _repo_head() -> str:
    candidates = (APP_ROOT, APP_ROOT.parent, Path.cwd())
    for candidate in candidates:
        value = _repo_head_from(candidate)
        if value != "unknown":
            return value
    for env_name in ("APP_GIT_COMMIT", "GIT_COMMIT", "COMMIT_SHA", "SOURCE_VERSION"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    return "unknown"


def _repo_head_from(repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repo_root), "rev-parse", "HEAD"),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:  # noqa: BLE001 - preflight may run in a slim container.
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _fetch_api_runtime(api_url: str, timeout_sec: float) -> dict[str, Any]:
    status_url = api_url.rstrip("/")
    if not status_url.endswith("/status"):
        status_url = f"{status_url}/status"
    try:
        with urlopen(status_url, timeout=timeout_sec) as response:  # noqa: S310 - operator URL.
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {
            "target": "api",
            "probe_status": "failed",
            "api_url": status_url,
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    runtime = payload.get("runtime") if isinstance(payload, dict) else None
    if not isinstance(runtime, dict):
        return {
            "target": "api",
            "probe_status": "failed",
            "api_url": status_url,
            "error": "status response has no runtime object",
        }
    return {"target": "api", "probe_status": "ok", "api_url": status_url, "runtime": runtime}


def _fetch_worker_runtime(queue: str, timeout_sec: float) -> dict[str, Any]:
    try:
        result = celery_app.send_task(RUNTIME_IDENTITY_TASK, queue=queue).get(timeout=timeout_sec)
    except Exception as exc:  # noqa: BLE001 - operator-visible probe failure.
        return {
            "target": "worker",
            "probe_status": "failed",
            "queue": queue,
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    runtime = result.get("runtime") if isinstance(result, dict) else None
    if runtime is None and isinstance(result, dict):
        runtime = result
    if not isinstance(runtime, dict):
        return {
            "target": "worker",
            "probe_status": "failed",
            "queue": queue,
            "error": "runtime.identity returned no runtime object",
        }
    return {"target": "worker", "probe_status": "ok", "queue": queue, "runtime": runtime}


def _commit_matches(actual: str, expected: str) -> bool:
    actual = str(actual or "").strip()
    expected = str(expected or "").strip()
    if not actual or not expected:
        return False
    return actual == expected or actual.startswith(expected) or expected.startswith(actual)


def _evaluate_runtime_target(
    probe: dict[str, Any],
    *,
    expected_commit: str,
    required_markers: tuple[str, ...],
) -> dict[str, Any]:
    target = str(probe.get("target") or "unknown")
    if probe.get("probe_status") != "ok":
        return {
            **probe,
            "status": "blocked",
            "problems": [probe.get("error") or "runtime probe failed"],
            "restart_hint": _runtime_restart_hint(
                target,
                queue=str(probe.get("queue") or ""),
                service=str(probe.get("service") or ""),
                api_url=str(probe.get("api_url") or ""),
            ),
        }

    runtime = dict(probe["runtime"])
    markers = dict(runtime.get("code_markers") or {})
    problems: list[str] = []
    warnings: list[str] = []
    for marker in required_markers:
        if markers.get(marker) is not True:
            problems.append(f"required marker is false or missing: {marker}")

    actual_commit = str(runtime.get("git_commit") or "unknown")
    if actual_commit == "unknown":
        warnings.append("runtime git_commit is unknown")
    elif expected_commit == "unknown":
        warnings.append("expected commit is unknown")
    elif not _commit_matches(actual_commit, expected_commit):
        problems.append(
            f"commit mismatch: runtime={actual_commit} expected={expected_commit}"
        )

    status = "blocked" if problems else "warning" if warnings else "ok"
    return {
        **probe,
        "status": status,
        "runtime": runtime,
        "problems": problems,
        "warnings": warnings,
        "restart_hint": _runtime_restart_hint(
            target,
            queue=str(probe.get("queue") or ""),
            service=str(runtime.get("service") or ""),
            api_url=str(probe.get("api_url") or ""),
        )
        if problems
        else None,
    }


def _runtime_restart_hint(target: str, *, queue: str = "", service: str = "", api_url: str = "") -> str:
    normalized_queue = queue.strip().lower()
    normalized_service = service.strip().lower()
    normalized_api_url = api_url.strip().lower()
    if target == "api":
        if normalized_service == "call_processing" or "call_processing" in normalized_api_url:
            return "restart call_processing_api service"
        return "restart analysis_api/api service"
    if target == "worker":
        if normalized_queue == CALL_PROCESSING_QUEUE or normalized_service == "call_processing":
            return "restart call_processing_worker service"
        return "restart analysis_worker/worker service"
    return "restart affected runtime service"


def _worst_runtime_status(items: list[dict[str, Any]]) -> str:
    statuses = {str(item.get("status") or "blocked") for item in items}
    if "blocked" in statuses:
        return "blocked"
    if "warning" in statuses:
        return "warning"
    return "ok"


def _runtime_operator_summary(items: list[dict[str, Any]]) -> str:
    blocked = [item for item in items if item.get("status") == "blocked"]
    if not blocked:
        return "Runtime identity check passed; no restart is required."
    lines = ["Runtime identity check blocked.", "", "Что не так:"]
    for item in blocked:
        target = str(item.get("target") or "unknown")
        for problem in item.get("problems") or ["runtime probe failed"]:
            lines.append(f"- {target}: {problem}")
    lines.extend(["", "Что сделать:"])
    for hint in dict.fromkeys(str(item.get("restart_hint")) for item in blocked):
        lines.append(f"- {hint}")
    return "\n".join(lines)


def _format_runtime_status(result: dict[str, Any]) -> str:
    lines = [
        "Runtime identity preflight",
        f"Status: {result.get('status')}",
        f"Expected commit: {result.get('expected_commit')}",
    ]
    for item in result.get("targets") or []:
        runtime = item.get("runtime") or {}
        markers = runtime.get("code_markers") or {}
        marker_state = ", ".join(
            f"{name}={bool(markers.get(name))}"
            for name in result.get("required_markers") or REQUIRED_CODE_MARKERS
        )
        lines.append(
            f"- {item.get('target')}: status={item.get('status')} "
            f"service={runtime.get('service', '-')} "
            f"process={runtime.get('process_type', '-')} "
            f"commit={runtime.get('git_commit', '-')} "
            f"pid={runtime.get('pid', '-')} markers=[{marker_state}]"
        )
        for problem in item.get("problems") or []:
            lines.append(f"  problem: {problem}")
        for warning in item.get("warnings") or []:
            lines.append(f"  warning: {warning}")
    lines.extend(["", str(result.get("operator_summary") or "")])
    return "\n".join(lines)


def runtime_status(args: argparse.Namespace) -> dict[str, Any]:
    expected_commit = str(args.expected_commit or "").strip() or _repo_head()
    required_markers = tuple(args.required_marker or REQUIRED_CODE_MARKERS)
    timeout_sec = float(args.timeout)
    target = str(getattr(args, "target", "both") or "both").strip().lower()
    probes = []
    if target in {"api", "both"}:
        probes.append(_fetch_api_runtime(args.api_url, timeout_sec))
    if target in {"worker", "both"}:
        probes.append(_fetch_worker_runtime(args.worker_queue, timeout_sec))
    targets = [
        _evaluate_runtime_target(
            probe,
            expected_commit=expected_commit,
            required_markers=required_markers,
        )
        for probe in probes
    ]
    status = _worst_runtime_status(targets)
    return {
        "status": status,
        "action": "runtime_status",
        "expected_commit": expected_commit,
        "required_markers": list(required_markers),
        "target": target,
        "api_url": args.api_url,
        "worker_queue": args.worker_queue,
        "billable_pipeline_started": False,
        "targets": targets,
        "operator_summary": _runtime_operator_summary(targets),
    }


def _as_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _sla_local_dt(report_date: date, local_time: time) -> datetime:
    return datetime.combine(report_date, local_time, tzinfo=ZoneInfo(SLA_TIMEZONE))


def _sla_window(report_date: date) -> dict[str, str]:
    precheck = _sla_local_dt(report_date, SLA_PRECHECK_TIME)
    deadline = _sla_local_dt(report_date, SLA_HARD_TIME)
    return {
        "timezone": SLA_TIMEZONE,
        "sla_precheck_at": precheck.isoformat(),
        "sla_precheck_at_utc": precheck.astimezone(UTC).isoformat(),
        "sla_deadline_at": deadline.isoformat(),
        "sla_deadline_at_utc": deadline.astimezone(UTC).isoformat(),
    }


def _active_manager_daily_schedules(db: Any) -> list[Any]:
    return (
        db.query(ReportingSchedule)
        .filter(
            ReportingSchedule.deleted_at.is_(None),
            ReportingSchedule.enabled.is_(True),
            ReportingSchedule.preset == "manager_daily",
        )
        .order_by(ReportingSchedule.created_at.asc())
        .all()
    )


def _manager_scope_from_schedules(db: Any, schedules: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for schedule in schedules:
        manager_ids = [
            str(item)
            for item in (schedule.manager_ids or [])
            if str(item or "").strip()
        ]
        if manager_ids:
            managers = {
                str(item.id): item
                for item in db.query(Manager)
                .filter(Manager.id.in_([UUID(item) for item in manager_ids]))
                .all()
            }
            for manager_id in manager_ids:
                key = (str(schedule.id), manager_id)
                if key in seen:
                    continue
                seen.add(key)
                manager = managers.get(manager_id)
                rows.append(
                    {
                        "schedule_id": str(schedule.id),
                        "department_id": str(schedule.department_id),
                        "manager_id": manager_id,
                        "manager_name": getattr(manager, "name", None),
                        "manager_email": getattr(manager, "email", None),
                        "manager_card_email": getattr(manager, "email", None),
                        "manager_active": (
                            bool(getattr(manager, "active", False))
                            if manager is not None
                            else False
                        ),
                        "manager_found": manager is not None,
                        "schedule": _schedule_summary(schedule),
                    }
                )
            continue

        managers = (
            db.query(Manager)
            .filter(
                Manager.department_id == schedule.department_id,
                Manager.active.is_(True),
            )
            .order_by(Manager.name.asc())
            .all()
        )
        for manager in managers:
            manager_id = str(manager.id)
            key = (str(schedule.id), manager_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "schedule_id": str(schedule.id),
                    "department_id": str(schedule.department_id),
                    "manager_id": manager_id,
                    "manager_name": manager.name,
                    "manager_email": manager.email,
                    "manager_card_email": manager.email,
                    "manager_active": bool(manager.active),
                    "manager_found": True,
                    "schedule": _schedule_summary(schedule),
                }
            )
    return rows


def _schedule_summary(schedule: Any) -> dict[str, Any]:
    return {
        "id": str(schedule.id),
        "department_id": str(schedule.department_id),
        "enabled": bool(schedule.enabled),
        "preset": schedule.preset,
        "start_time": schedule.start_time,
        "timezone": schedule.timezone,
        "recurrence_type": schedule.recurrence_type,
        "report_period_rule": schedule.report_period_rule,
        "mode": schedule.mode,
        "business_email_enabled": bool(schedule.business_email_enabled),
        "review_required": bool(getattr(schedule, "review_required", True)),
        "next_run_at": _as_iso(schedule.next_run_at),
    }


def _load_manager_day_interactions(
    db: Any,
    *,
    department_id: str,
    manager_id: str,
    report_date: date,
) -> list[Any]:
    rows = (
        db.query(Interaction)
        .filter(
            Interaction.department_id == UUID(department_id),
            Interaction.manager_id == UUID(manager_id),
            Interaction.type == "call",
        )
        .all()
    )
    selected: list[Any] = []
    for interaction in rows:
        started_at = parse_call_started_at(dict(interaction.metadata_ or {}))
        if started_at is not None and started_at.date() == report_date:
            selected.append(interaction)
    return selected


def _interaction_requires_upstream(interaction: Any) -> bool:
    status = str(getattr(interaction, "status", "") or "").strip().upper()
    return status != NO_AUDIO_INTERACTION_STATUS


def _load_artifact_counts(db: Any, interactions: list[Any]) -> dict[str, Any]:
    required_ids = [item.id for item in interactions if _interaction_requires_upstream(item)]
    counts = {
        "required_interactions": len(required_ids),
        "ready_by_kind": {kind: 0 for kind in UPSTREAM_ARTIFACT_KINDS},
        "present_by_kind": {kind: 0 for kind in UPSTREAM_ARTIFACT_KINDS},
        "stt_ready": False,
        "llm1_ready": False,
    }
    if not required_ids:
        counts["stt_ready"] = True
        counts["llm1_ready"] = True
        return counts
    artifacts = (
        db.query(CallArtifact)
        .filter(
            CallArtifact.interaction_id.in_(required_ids),
            CallArtifact.artifact_kind.in_(list(UPSTREAM_ARTIFACT_KINDS)),
            CallArtifact.is_active.is_(True),
        )
        .all()
    )
    seen_ready: set[tuple[str, str]] = set()
    seen_present: set[tuple[str, str]] = set()
    for artifact in artifacts:
        kind = str(artifact.artifact_kind or "")
        if kind not in UPSTREAM_ARTIFACT_KINDS:
            continue
        interaction_id = str(artifact.interaction_id)
        seen_present.add((interaction_id, kind))
        if str(artifact.status or "").strip().lower() == "ready":
            seen_ready.add((interaction_id, kind))
    for kind in UPSTREAM_ARTIFACT_KINDS:
        counts["present_by_kind"][kind] = sum(
            1 for _, item_kind in seen_present if item_kind == kind
        )
        counts["ready_by_kind"][kind] = sum(1 for _, item_kind in seen_ready if item_kind == kind)
    counts["stt_ready"] = all(
        (str(interaction_id), "transcript") in seen_ready
        and (str(interaction_id), "transcript_segments") in seen_ready
        for interaction_id in required_ids
    )
    counts["llm1_ready"] = all(
        (str(interaction_id), "llm1_first_pass") in seen_ready
        for interaction_id in required_ids
    )
    return counts


def _load_analysis_counts(db: Any, interactions: list[Any]) -> dict[str, Any]:
    required_ids = [item.id for item in interactions if _interaction_requires_upstream(item)]
    counts = {
        "required_interactions": len(required_ids),
        "present": 0,
        "ready": 0,
        "failed": 0,
        "analysis_ready": False,
    }
    if not required_ids:
        counts["analysis_ready"] = True
        return counts
    rows = db.query(Analysis).filter(Analysis.interaction_id.in_(required_ids)).all()
    seen_present = {str(item.interaction_id) for item in rows}
    seen_ready = {
        str(item.interaction_id)
        for item in rows
        if not bool(getattr(item, "is_failed", False))
    }
    seen_failed = {
        str(item.interaction_id)
        for item in rows
        if bool(getattr(item, "is_failed", False))
    }
    counts["present"] = len(seen_present)
    counts["ready"] = len(seen_ready)
    counts["failed"] = len(seen_failed)
    counts["analysis_ready"] = all(str(item) in seen_ready for item in required_ids)
    return counts


def _load_manager_day_batch(
    db: Any,
    *,
    schedule_id: str,
    department_id: str,
    manager_id: str,
    report_date: date,
) -> tuple[Any | None, list[Any], dict[str, Any]]:
    batches = (
        db.query(ScheduledReportBatch)
        .filter(
            ScheduledReportBatch.schedule_id == UUID(schedule_id),
            ScheduledReportBatch.department_id == UUID(department_id),
            ScheduledReportBatch.preset == "manager_daily",
            ScheduledReportBatch.status.in_(list(ACTIVE_MANAGER_DAILY_BATCH_STATUSES)),
        )
        .order_by(ScheduledReportBatch.created_at.desc())
        .all()
    )
    report_day = report_date.isoformat()
    candidates: list[dict[str, Any]] = []
    for batch in batches:
        if not _batch_matches_manager_day(
            batch=batch,
            manager_id=manager_id,
            report_day=report_day,
        ):
            continue
        drafts = (
            db.query(ScheduledReportDraft)
            .filter(ScheduledReportDraft.batch_id == batch.id)
            .order_by(ScheduledReportDraft.created_at.asc())
            .all()
        )
        matching_drafts = [
            draft
            for draft in drafts
            if _draft_matches_manager_day(draft=draft, manager_id=manager_id, report_day=report_day)
        ]
        candidate_drafts = matching_drafts or drafts
        priority, priority_reason = _manager_day_batch_priority(batch, candidate_drafts)
        candidates.append(
            {
                "batch": batch,
                "drafts": candidate_drafts,
                "priority": priority,
                "priority_reason": priority_reason,
            }
        )
    if not candidates:
        return None, [], {
            "selection_strategy": "manager_day_priority",
            "selected_batch_id": None,
            "batch_candidates": [],
        }

    ordered = sorted(candidates, key=_manager_day_batch_sort_key)
    selected = ordered[0]
    selected_batch_id = str(getattr(selected["batch"], "id"))
    diagnostics = {
        "selection_strategy": "manager_day_priority",
        "selected_batch_id": selected_batch_id,
        "batch_candidates": [
            _manager_day_batch_candidate_summary(
                candidate,
                selected_batch_id=selected_batch_id,
            )
            for candidate in ordered
        ],
    }
    return selected["batch"], selected["drafts"], diagnostics


def _manager_day_batch_sort_key(candidate: dict[str, Any]) -> tuple[int, float, str]:
    batch = candidate["batch"]
    return (
        int(candidate["priority"]),
        -_batch_sort_timestamp(batch),
        str(getattr(batch, "id", "")),
    )


def _batch_sort_timestamp(batch: Any) -> float:
    for value in (
        getattr(batch, "created_at", None),
        getattr(batch, "planned_for", None),
        getattr(batch, "delivered_at", None),
        getattr(batch, "failed_at", None),
    ):
        if value is None:
            continue
        if hasattr(value, "timestamp"):
            return float(value.timestamp())
    return 0.0


def _manager_day_batch_priority(batch: Any, drafts: list[Any]) -> tuple[int, str]:
    existing = _existing_sla_fields(batch, drafts)
    batch_status = str(getattr(batch, "status", "") or "").strip()
    sla_status = str(existing.get("sla_status") or "").strip()
    manager_email_status = str(
        existing.get("manager_email_status")
        or _extract_manager_email_status(drafts).get("status")
        or ""
    ).strip()
    reason_text = " ".join(_manager_day_batch_reason_tokens(batch, drafts, existing)).lower()

    if (
        batch_status == "delivered"
        or getattr(batch, "delivered_at", None) is not None
        or manager_email_status == "delivered"
        or sla_status in {"on_time", "late"}
        or any(str(getattr(draft, "status", "") or "") == "delivered" for draft in drafts)
    ):
        return 0, "delivered_or_manager_email_sent"

    if (
        batch_status in {"review_required", "approved_for_delivery"}
        or sla_status == "blocked"
        or manager_email_status == "blocked"
        or "missing_recipient" in reason_text
        or "review_required" in reason_text
    ):
        return 1, "blocked_missing_recipient_or_review_required"

    if (
        batch_status == "failed"
        or sla_status == "not_applicable"
        or "no_calls" in reason_text
        or "no_candidate" in reason_text
    ):
        return 2, "failed_no_calls_or_not_applicable"

    return 3, "fallback_latest"


def _manager_day_batch_reason_tokens(
    batch: Any,
    drafts: list[Any],
    existing: dict[str, Any],
) -> list[str]:
    tokens: list[str] = []
    observability = dict(getattr(batch, "observability", None) or {})
    diagnostics = dict(getattr(batch, "diagnostics", None) or {})
    selection = dict(
        observability.get("scheduled_candidate_selection")
        or diagnostics.get("scheduled_candidate_selection")
        or {}
    )
    for source in (
        existing,
        observability,
        diagnostics,
        selection,
    ):
        for key in (
            "sla_missed_reason",
            "failure_reason",
            "selection_reason",
            "reason",
            "status",
            "run_state",
        ):
            value = source.get(key)
            if value not in (None, ""):
                tokens.append(str(value))
    tokens.extend(str(item) for item in list(getattr(batch, "errors", None) or []))
    for draft in drafts:
        tokens.extend(str(item) for item in list(getattr(draft, "errors", None) or []))
    return tokens


def _manager_day_batch_candidate_summary(
    candidate: dict[str, Any],
    *,
    selected_batch_id: str,
) -> dict[str, Any]:
    batch = candidate["batch"]
    drafts = list(candidate.get("drafts") or [])
    existing = _existing_sla_fields(batch, drafts)
    observability = dict(getattr(batch, "observability", None) or {})
    diagnostics = dict(getattr(batch, "diagnostics", None) or {})
    selection = dict(
        observability.get("scheduled_candidate_selection")
        or diagnostics.get("scheduled_candidate_selection")
        or {}
    )
    batch_id = str(getattr(batch, "id"))
    return {
        "id": batch_id,
        "selected": batch_id == selected_batch_id,
        "selection_priority": int(candidate["priority"]),
        "selection_reason": candidate["priority_reason"],
        "status": getattr(batch, "status", None),
        "created_at": _as_iso(getattr(batch, "created_at", None)),
        "planned_for": _as_iso(getattr(batch, "planned_for", None)),
        "delivered_at": _as_iso(getattr(batch, "delivered_at", None)),
        "failed_at": _as_iso(getattr(batch, "failed_at", None)),
        "sla_status": existing.get("sla_status"),
        "sla_missed_reason": existing.get("sla_missed_reason"),
        "manager_email_status": existing.get("manager_email_status")
        or _extract_manager_email_status(drafts).get("status"),
        "scheduled_candidate_selection_reason": selection.get("selection_reason"),
        "draft_ids": [str(getattr(draft, "id")) for draft in drafts],
        "draft_statuses": {
            str(getattr(draft, "id")): getattr(draft, "status", None) for draft in drafts
        },
        "errors": list(getattr(batch, "errors", None) or []),
    }


def _batch_matches_manager_day(*, batch: Any, manager_id: str, report_day: str) -> bool:
    period = dict(batch.period or {})
    if str(period.get("date_from") or "") != report_day:
        return False
    if str(period.get("date_to") or report_day) != report_day:
        return False
    filters = dict(batch.filters or {})
    manager_ids = {str(item) for item in filters.get("manager_ids") or []}
    if manager_id in manager_ids:
        return True
    observability = dict(batch.observability or {})
    selection = dict(observability.get("scheduled_candidate_selection") or {})
    return str(selection.get("manager_id") or "") == manager_id


def _draft_matches_manager_day(*, draft: Any, manager_id: str, report_day: str) -> bool:
    if str(draft.group_key or "") == f"manager_daily:{manager_id}:{report_day}":
        return True
    payload = dict(draft.generated_payload or {})
    meta = dict(payload.get("meta") or {})
    header = dict(payload.get("header") or {})
    period = dict(meta.get("period") or {})
    payload_report_day = str(header.get("report_date") or period.get("date_from") or "").strip()
    payload_manager_id = str(meta.get("manager_id") or header.get("manager_id") or "").strip()
    return payload_report_day == report_day and payload_manager_id == manager_id


def _extract_manager_email_status(drafts: list[Any]) -> dict[str, Any]:
    if not drafts:
        return {"status": "not_started", "primary_email": None, "error": None}
    for draft in drafts:
        delivery = dict(draft.delivery or {})
        transport = dict(delivery.get("transport") or delivery)
        email = dict(transport.get("email_delivery") or {})
        if email:
            return {
                "status": str(email.get("status") or "unknown"),
                "primary_email": email.get("primary_email")
                or (transport.get("resolved_email") or {}).get("primary_email"),
                "error": email.get("error"),
                "artifact": email.get("artifact"),
            }
    return {"status": "unknown", "primary_email": None, "error": None}


def _extract_rop_status(batch: Any | None) -> dict[str, Any]:
    if batch is None:
        return {"status": "not_started", "reason": "batch_missing", "available": False}
    observability = dict(batch.observability or {})
    candidates = [
        ((observability.get("summary") or {}).get("rop_daily_delivery") or {}),
        (observability.get("rop_daily_delivery") or {}),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            return {
                "status": str(candidate.get("status") or "unknown"),
                "reason": candidate.get("reason"),
                "available": True,
                "attachments_count": candidate.get("attachments_count"),
                "target": candidate.get("target"),
            }
    return {"status": "unknown", "reason": "rop_status_not_recorded", "available": False}


def _draft_pdf_ready(drafts: list[Any]) -> bool:
    return any(
        bool((dict(draft.artifact or {})).get("filename") or dict(draft.artifact or {}))
        for draft in drafts
    )


def _existing_sla_fields(batch: Any | None, drafts: list[Any]) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    if batch is not None:
        observability = dict(batch.observability or {})
        sources.extend([dict(observability.get("sla") or {}), observability])
    for draft in drafts:
        delivery = dict(draft.delivery or {})
        sources.extend([dict(delivery.get("sla") or {}), delivery])
    merged: dict[str, Any] = {}
    for source in sources:
        for key in (
            "sla_deadline_at",
            "sla_precheck_at",
            "sla_hardcheck_at",
            "delivered_at",
            "sla_status",
            "sla_missed",
            "sla_missed_reason",
            "late_delivery_at",
            "manager_email_status",
            "rop_email_status",
        ):
            if source.get(key) not in (None, ""):
                merged[key] = source[key]
    return merged


def _derive_sla_state(
    *,
    report_date: date,
    calls_total: int,
    with_audio_calls: int,
    upstream: dict[str, Any],
    analysis: dict[str, Any],
    batch: Any | None,
    drafts: list[Any],
    manager_email: dict[str, Any],
    rop: dict[str, Any],
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    existing = _existing_sla_fields(batch, drafts)
    window = _sla_window(report_date)
    deadline_utc = datetime.fromisoformat(window["sla_deadline_at_utc"])
    now_utc = now_utc or datetime.now(UTC)
    pdf_ready = _draft_pdf_ready(drafts)
    email_status = str(manager_email.get("status") or "not_started")
    delivered_at = existing.get("delivered_at") or _as_iso(getattr(batch, "delivered_at", None))
    batch_delivered = bool(
        batch is not None
        and (
            str(getattr(batch, "status", "") or "") == "delivered"
            or delivered_at
            or str(existing.get("manager_email_status") or "") == "delivered"
        )
    )
    if calls_total == 0:
        derived_status = "not_applicable"
        reason = "no_calls_for_report_day"
    elif with_audio_calls == 0:
        derived_status = "not_applicable"
        reason = "no_audio_calls_for_report_day"
    elif not bool(upstream.get("stt_ready")):
        derived_status = "missed_pending" if now_utc >= deadline_utc else "not_applicable"
        reason = "upstream_stt_not_ready"
    elif not bool(upstream.get("llm1_ready")):
        derived_status = "missed_pending" if now_utc >= deadline_utc else "not_applicable"
        reason = "upstream_llm1_not_ready"
    elif not bool(analysis.get("analysis_ready")):
        derived_status = "missed_pending" if now_utc >= deadline_utc else "not_applicable"
        reason = "analysis_not_ready"
    elif batch is None:
        derived_status = "missed_pending" if now_utc >= deadline_utc else "not_applicable"
        reason = "scheduled_batch_missing"
    elif batch_delivered:
        delivered_dt = _as_datetime(delivered_at)
        missed = bool(existing.get("sla_missed"))
        if "sla_missed" not in existing and delivered_dt is not None:
            missed = delivered_dt > deadline_utc
        derived_status = "late" if missed else "on_time"
        reason = "delivered_after_sla_deadline" if missed else "manager_email_delivered"
    elif not drafts:
        derived_status = "missed_pending" if now_utc >= deadline_utc else "not_applicable"
        reason = "scheduled_draft_missing"
    elif not pdf_ready:
        derived_status = "missed_pending" if now_utc >= deadline_utc else "not_applicable"
        reason = "pdf_not_ready"
    elif email_status == "delivered":
        if bool(existing.get("sla_missed")):
            derived_status = "late"
            reason = existing.get("sla_missed_reason") or "delivered_after_recorded_sla_miss"
        else:
            derived_status = "on_time"
            reason = "manager_email_delivered"
    elif email_status in {"blocked", "failed"}:
        derived_status = "blocked"
        primary_email = str(manager_email.get("primary_email") or "").strip()
        if pdf_ready and not primary_email:
            reason = "missing_recipient"
        elif primary_email:
            reason = "delivery_failed"
        else:
            reason = manager_email.get("error") or f"manager_email_{email_status}"
    elif now_utc >= deadline_utc:
        derived_status = "missed_pending"
        reason = f"manager_email_{email_status or 'not_delivered'}"
    else:
        derived_status = "not_applicable"
        reason = "sla_deadline_not_reached"

    status = str(existing.get("sla_status") or derived_status)
    missed_reason = existing.get("sla_missed_reason") or reason
    return {
        **window,
        "delivered_at": delivered_at,
        "sla_status": status,
        "sla_missed": bool(
            existing.get("sla_missed", status in {"missed_pending", "blocked", "late"})
        ),
        "sla_missed_reason": missed_reason,
        "late_delivery_at": existing.get("late_delivery_at"),
        "manager_email_status": existing.get("manager_email_status")
        or ("delivered" if batch_delivered else email_status),
        "rop_email_status": existing.get("rop_email_status") or rop.get("status"),
        "reason": missed_reason,
    }


def _build_manager_sla_row(
    db: Any,
    *,
    scope: dict[str, Any],
    report_date: date,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    interactions = _load_manager_day_interactions(
        db,
        department_id=scope["department_id"],
        manager_id=scope["manager_id"],
        report_date=report_date,
    )
    with_audio = [item for item in interactions if _interaction_requires_upstream(item)]
    upstream = _load_artifact_counts(db, with_audio)
    analysis = _load_analysis_counts(db, with_audio)
    batch, drafts, batch_diagnostics = _load_manager_day_batch(
        db,
        schedule_id=scope["schedule_id"],
        department_id=scope["department_id"],
        manager_id=scope["manager_id"],
        report_date=report_date,
    )
    manager_email = _extract_manager_email_status(drafts)
    rop = _extract_rop_status(batch)
    sla = _derive_sla_state(
        report_date=report_date,
        calls_total=len(interactions),
        with_audio_calls=len(with_audio),
        upstream=upstream,
        analysis=analysis,
        batch=batch,
        drafts=drafts,
        manager_email=manager_email,
        rop=rop,
        now_utc=now_utc,
    )
    manager_card_email = scope.get("manager_card_email")
    if manager_card_email is None and not isinstance(scope.get("manager_email"), dict):
        manager_card_email = scope.get("manager_email")
    return {
        **scope,
        "report_date": report_date.isoformat(),
        "calls": {
            "total": len(interactions),
            "with_audio": len(with_audio),
            "no_audio": len(interactions) - len(with_audio),
            "presence": bool(interactions),
        },
        "upstream": upstream,
        "analysis": analysis,
        "batch": _batch_summary(batch),
        "drafts": [_draft_summary(item) for item in drafts],
        "draft_pdf_ready": _draft_pdf_ready(drafts),
        "manager_card_email": manager_card_email,
        "manager_email": manager_email,
        "rop_email": rop,
        "sla": sla,
        "diagnostics": batch_diagnostics,
    }


def _batch_summary(batch: Any | None) -> dict[str, Any] | None:
    if batch is None:
        return None
    return {
        "id": str(batch.id),
        "status": batch.status,
        "planned_for": _as_iso(batch.planned_for),
        "business_email_enabled": bool(batch.business_email_enabled),
        "review_required": bool(batch.review_required),
        "delivered_at": _as_iso(batch.delivered_at),
        "failed_at": _as_iso(batch.failed_at),
        "errors": list(batch.errors or []),
    }


def _draft_summary(draft: Any) -> dict[str, Any]:
    return {
        "id": str(draft.id),
        "status": draft.status,
        "group_key": draft.group_key,
        "artifact": dict(draft.artifact or {}),
        "pdf_ready": bool(dict(draft.artifact or {})),
        "errors": list(draft.errors or []),
    }


def _needs_sla_attention(row: dict[str, Any], *, phase: str) -> bool:
    if row["calls"]["with_audio"] <= 0:
        return False
    email_status = str((row.get("manager_email") or {}).get("status") or "")
    if email_status == "delivered":
        return False
    sla_status = str((row.get("sla") or {}).get("sla_status") or "")
    if phase == "precheck":
        return True
    return (
        sla_status in {"missed_pending", "blocked", "not_applicable"}
        or email_status != "delivered"
    )


def _attention_reason(row: dict[str, Any]) -> str:
    sla = row.get("sla") or {}
    reason = str(sla.get("reason") or sla.get("sla_missed_reason") or "").strip()
    return reason or "manager_report_not_delivered"


def _human_sla_reason(reason: Any) -> str:
    raw = str(reason or "").strip()
    if not raw:
        return SLA_REASON_LABELS["manager_report_not_delivered"]
    if raw in SLA_REASON_LABELS:
        return SLA_REASON_LABELS[raw]
    lowered = raw.lower()
    for code, label in SLA_REASON_LABELS.items():
        if lowered == code.lower():
            return label
    if raw.startswith(("{", "[")):
        return "техническая ошибка доставки"
    one_line = " ".join(raw.split())
    return one_line[:77] + "..." if len(one_line) > 80 else one_line


def _manager_alert_label(row: dict[str, Any]) -> str:
    name = str(row.get("manager_name") or "").strip()
    if name:
        return name
    email = str(row.get("manager_card_email") or "").strip()
    if email:
        return email
    manager_id = str(row.get("manager_id") or "").strip()
    return manager_id[:8] if manager_id else "unknown manager"


def _sla_alert_line(row: dict[str, Any]) -> str:
    return f"{_manager_alert_label(row)}: {_human_sla_reason(_attention_reason(row))}"


def _bounded_lines(
    lines: list[str],
    *,
    max_items: int,
    omitted_label: str,
) -> list[str]:
    if len(lines) <= max_items:
        return lines
    omitted = len(lines) - max_items
    return [*lines[:max_items], omitted_label.format(omitted=omitted)]


def _sla_operator_summary(
    *,
    phase: str,
    report_date: date,
    rows: list[dict[str, Any]],
) -> str:
    run_id = f"manager_daily_sla:{report_date.isoformat()}:{phase}"
    alert_lines = _bounded_lines(
        [_sla_alert_line(row) for row in rows],
        max_items=SLA_ALERT_MAX_AFFECTED,
        omitted_label="Еще {omitted} см. в observability/logs.",
    )
    if phase == "hard":
        title = f"Отчеты за {report_date.isoformat()}: SLA доставки пропущен"
        happened = (
            f"К 10:00 отчеты не доставлены. Затронуто менеджеров: {len(rows)}."
        )
        impact = "Менеджеры не получили ежедневный отчет вовремя."
    else:
        title = f"Отчеты за {report_date.isoformat()}: риск SLA доставки"
        happened = (
            f"К 09:30 есть отчеты не в delivered-состоянии. "
            f"Затронуто менеджеров: {len(rows)}."
        )
        impact = "Менеджеры могут не получить ежедневный отчет вовремя."
    affected_block = "\n".join(f"- {line}" for line in alert_lines) or "- none"
    return "\n".join(
        [
            title,
            "",
            "Что случилось:",
            happened,
            "",
            "Кого затронуло:",
            affected_block,
            "",
            "На что влияет:",
            impact,
            "",
            "Что проверить:",
            "scheduled reporting batch, draft delivery, email delivery result.",
            "",
            f"Run: {run_id}",
        ]
    )


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str((row.get("sla") or {}).get("sla_status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _manager_row_delivered(row: dict[str, Any]) -> bool:
    manager_email_status = str((row.get("manager_email") or {}).get("status") or "")
    sla_status = str((row.get("sla") or {}).get("sla_status") or "")
    batch_status = str((row.get("batch") or {}).get("status") or "")
    return (
        manager_email_status == "delivered"
        or batch_status == "delivered"
        or sla_status in {"on_time", "late"}
    )


def _manager_row_digest_not_required(row: dict[str, Any]) -> bool:
    sla = dict(row.get("sla") or {})
    reason = str(sla.get("reason") or sla.get("sla_missed_reason") or "").strip()
    status = str(sla.get("sla_status") or "").strip()
    calls = dict(row.get("calls") or {})
    return (
        reason in ROP_DIGEST_NO_CALLS_REASONS
        or (status == "not_applicable" and int(calls.get("total") or 0) <= 0)
        or (status == "not_applicable" and int(calls.get("with_audio") or 0) <= 0)
    )


def _rop_digest_payload_from_batch(batch: Any) -> dict[str, Any] | None:
    for source in (
        dict(getattr(batch, "observability", None) or {}),
        dict(getattr(batch, "diagnostics", None) or {}),
    ):
        digest = source.get("scheduled_rop_daily_digest")
        if isinstance(digest, dict) and digest:
            return dict(digest)
    return None


def _rop_digest_report_date_matches(
    *,
    batch: Any,
    digest: dict[str, Any],
    report_date: date,
) -> bool:
    report_day = report_date.isoformat()
    digest_report_date = str(digest.get("report_date") or "").strip()
    if digest_report_date == report_day:
        return True
    period = dict(getattr(batch, "period", None) or {})
    return (
        str(period.get("date_from") or "") == report_day
        or str(period.get("date_to") or "") == report_day
    )


def _rop_delivery_metadata(digest: dict[str, Any]) -> dict[str, Any] | None:
    metadata = dict(digest.get("delivery_metadata") or {})
    delivery = dict(digest.get("delivery") or {})
    for key in (
        "status",
        "channel",
        "target",
        "message_id",
        "document_id",
        "artifact",
    ):
        value = delivery.get(key)
        if value not in (None, "") and key not in metadata:
            metadata[key] = value
    return metadata or None


def _normalize_rop_digest_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    raw_status = str(candidate.get("status") or "").strip() or "unknown"
    if raw_status in ROP_DIGEST_SENT_STATUSES:
        status = "sent"
    elif raw_status in ROP_DIGEST_FAILED_STATUSES:
        status = "failed"
    elif raw_status in ROP_DIGEST_BLOCKED_STATUSES:
        status = "blocked"
    else:
        status = raw_status
    metadata = _rop_delivery_metadata(candidate)
    message_id = (
        candidate.get("message_id")
        or (metadata or {}).get("message_id")
        or candidate.get("smtp_message_id")
    )
    return {
        "status": status,
        "raw_status": raw_status,
        "sent": status == "sent",
        "recipient": candidate.get("recipient") or candidate.get("target"),
        "attachments_count": candidate.get("attachments_count"),
        "rows_count": candidate.get("rows_count"),
        "message_id": message_id,
        "delivery_metadata": metadata,
        "reason": candidate.get("reason"),
        "report_date": candidate.get("report_date"),
        "subject": candidate.get("subject"),
        "batch_id": candidate.get("batch_id"),
        "batch_status": candidate.get("batch_status"),
        "created_at": candidate.get("created_at"),
    }


def _rop_digest_candidate_priority(candidate: dict[str, Any]) -> tuple[int, float, str]:
    status = str(candidate.get("status") or "")
    priority = (
        0
        if status == "sent"
        else 1
        if status in {"failed", "blocked"}
        else 2
        if status == "skipped"
        else 3
    )
    created_at = _as_datetime(candidate.get("created_at"))
    timestamp = created_at.timestamp() if created_at is not None else 0.0
    return (priority, -timestamp, str(candidate.get("batch_id") or ""))


def _rop_digest_operator_action(status: str) -> str:
    if status == "missing_digest":
        return "check scheduled_rop_daily_digest observability and resend the ROP digest if needed"
    if status in {"failed", "blocked"}:
        return "inspect the digest delivery reason and retry after fixing the blocker"
    if status == "sent":
        return "none"
    if status == "not_required":
        return "none"
    return "inspect scheduled reporting observability if this state is unexpected"


def _rop_digest_operator_summary(digest: dict[str, Any]) -> str:
    status = str(digest.get("status") or "unknown")
    reason = str(digest.get("reason") or "").strip()
    if status == "sent":
        return "ROP digest sent; no operator action is required."
    if status == "missing_digest":
        return (
            "Manager reports were delivered, but scheduled_rop_daily_digest is missing. "
            "Check the scheduled run observability and resend the ROP digest if needed."
        )
    if status == "not_required":
        return "ROP digest is not required for this date; manager days are no-calls/not_applicable or no manager report was delivered."
    if status in {"failed", "blocked"}:
        return f"ROP digest delivery is {status}; reason={reason or 'not recorded'}."
    return f"ROP digest status is {status}; reason={reason or 'not recorded'}."


def _derive_rop_digest_status(
    *,
    report_date: date,
    managers: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized_candidates = [
        _normalize_rop_digest_candidate(candidate) for candidate in candidates
    ]
    if normalized_candidates:
        selected = sorted(normalized_candidates, key=_rop_digest_candidate_priority)[0]
        result = {**selected, "candidates": normalized_candidates}
    else:
        delivered_count = sum(1 for row in managers if _manager_row_delivered(row))
        not_required = bool(managers) and all(
            _manager_row_digest_not_required(row) for row in managers
        )
        if delivered_count > 0:
            result = {
                "status": "missing_digest",
                "raw_status": None,
                "sent": False,
                "recipient": None,
                "attachments_count": 0,
                "rows_count": len(managers),
                "message_id": None,
                "delivery_metadata": None,
                "reason": "manager_reports_delivered_but_scheduled_rop_daily_digest_missing",
                "report_date": report_date.isoformat(),
                "subject": None,
                "batch_id": None,
                "batch_status": None,
                "created_at": None,
                "delivered_manager_reports_count": delivered_count,
                "candidates": [],
            }
        elif not_required:
            result = {
                "status": "not_required",
                "raw_status": None,
                "sent": False,
                "recipient": None,
                "attachments_count": 0,
                "rows_count": len(managers),
                "message_id": None,
                "delivery_metadata": None,
                "reason": "all_manager_days_not_applicable",
                "report_date": report_date.isoformat(),
                "subject": None,
                "batch_id": None,
                "batch_status": None,
                "created_at": None,
                "candidates": [],
            }
        else:
            result = {
                "status": "not_required",
                "raw_status": None,
                "sent": False,
                "recipient": None,
                "attachments_count": 0,
                "rows_count": len(managers),
                "message_id": None,
                "delivery_metadata": None,
                "reason": "no_delivered_manager_reports",
                "report_date": report_date.isoformat(),
                "subject": None,
                "batch_id": None,
                "batch_status": None,
                "created_at": None,
                "candidates": [],
            }
    result["operator_action"] = _rop_digest_operator_action(str(result.get("status") or ""))
    result["operator_summary"] = _rop_digest_operator_summary(result)
    return result


def _load_rop_digest_status(
    db: Any,
    *,
    schedules: list[Any],
    report_date: date,
    managers: list[dict[str, Any]],
) -> dict[str, Any]:
    if not schedules:
        return _derive_rop_digest_status(
            report_date=report_date,
            managers=managers,
            candidates=[],
        )
    batches = (
        db.query(ScheduledReportBatch)
        .filter(
            ScheduledReportBatch.schedule_id.in_([schedule.id for schedule in schedules]),
            ScheduledReportBatch.preset == "manager_daily",
            ScheduledReportBatch.status.in_(list(ACTIVE_MANAGER_DAILY_BATCH_STATUSES)),
        )
        .order_by(ScheduledReportBatch.created_at.desc())
        .all()
    )
    candidates: list[dict[str, Any]] = []
    for batch in batches:
        digest = _rop_digest_payload_from_batch(batch)
        if digest is None:
            continue
        if not _rop_digest_report_date_matches(
            batch=batch,
            digest=digest,
            report_date=report_date,
        ):
            continue
        candidates.append(
            {
                **digest,
                "batch_id": str(getattr(batch, "id")),
                "batch_status": getattr(batch, "status", None),
                "created_at": _as_iso(getattr(batch, "created_at", None)),
            }
        )
    return _derive_rop_digest_status(
        report_date=report_date,
        managers=managers,
        candidates=candidates,
    )


def _sla_status_operator_summary(rop_digest: dict[str, Any]) -> str:
    return str(rop_digest.get("operator_summary") or "")


def _send_sla_alert(
    *,
    phase: str,
    report_date: date,
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not rows:
        return None
    level = "critical" if phase == "hard" else "warning"
    event = "failed" if phase == "hard" else "blocked"
    errors = _bounded_lines(
        [_sla_alert_line(row) for row in rows],
        max_items=SLA_ALERT_MAX_AFFECTED,
        omitted_label="Еще {omitted} см. в observability/logs.",
    )
    run_id = f"manager_daily_sla:{report_date.isoformat()}:{phase}"
    try:
        return send_run_alert(
            event,
            run_id=run_id,
            title=f"manager_daily SLA {phase}",
            level=level,
            requested_by="scheduled_reporting_preflight.sla-check",
            scope={
                "report_date": report_date.isoformat(),
                "preset": "manager_daily",
                "phase": phase,
            },
            counts={"affected_managers": len(rows)},
            errors=errors,
            operator_summary=_sla_operator_summary(
                phase=phase,
                report_date=report_date,
                rows=rows,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - SLA checks must not fail because alerting failed
        return {
            "channel": "run_alert",
            "event": event,
            "level": level,
            "run_id": run_id,
            "status": "failed",
            "error": str(exc),
            "error_class": exc.__class__.__name__,
        }


def _mark_hard_sla_missed(
    db: Any,
    *,
    rows: list[dict[str, Any]],
    report_date: date,
) -> dict[str, Any]:
    marked: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    checked_at = datetime.now(UTC).isoformat()
    window = _sla_window(report_date)
    for row in rows:
        batch_id = ((row.get("batch") or {}).get("id")) if row.get("batch") else None
        if not batch_id:
            gaps.append(
                {
                    "manager_id": row["manager_id"],
                    "reason": "scheduled_batch_missing_no_safe_persistent_target",
                }
            )
            continue
        batch = (
            db.query(ScheduledReportBatch)
            .filter(ScheduledReportBatch.id == UUID(batch_id))
            .first()
        )
        if batch is None:
            gaps.append({"manager_id": row["manager_id"], "reason": "scheduled_batch_not_found"})
            continue
        reason = _attention_reason(row)
        manager_email_status = str((row.get("manager_email") or {}).get("status") or "")
        sla_status = (
            "blocked"
            if manager_email_status in {"blocked", "failed"}
            else "missed_pending"
        )
        sla_payload = {
            **window,
            "sla_hardcheck_at": checked_at,
            "sla_status": sla_status,
            "sla_missed": True,
            "sla_missed_reason": reason,
            "manager_email_status": (row.get("manager_email") or {}).get("status"),
            "rop_email_status": (row.get("rop_email") or {}).get("status"),
        }
        observability = dict(batch.observability or {})
        manager_days = dict(
            (observability.get("manager_daily_sla") or {}).get("manager_days") or {}
        )
        manager_days[row["manager_id"]] = sla_payload
        observability["manager_daily_sla"] = {
            **dict(observability.get("manager_daily_sla") or {}),
            "last_hardcheck_at": checked_at,
            "manager_days": manager_days,
        }
        observability.update(
            {key: value for key, value in sla_payload.items() if key.startswith("sla_")}
        )
        batch.observability = observability

        drafts = (
            db.query(ScheduledReportDraft)
            .filter(ScheduledReportDraft.batch_id == batch.id)
            .all()
        )
        for draft in drafts:
            if not _draft_matches_manager_day(
                draft=draft,
                manager_id=row["manager_id"],
                report_day=report_date.isoformat(),
            ):
                continue
            delivery = dict(draft.delivery or {})
            delivery["sla"] = {**dict(delivery.get("sla") or {}), **sla_payload}
            delivery.update(
                {key: value for key, value in sla_payload.items() if key.startswith("sla_")}
            )
            draft.delivery = delivery
        marked.append(
            {
                "manager_id": row["manager_id"],
                "batch_id": batch_id,
                "sla_status": sla_status,
                "reason": reason,
            }
        )
    if marked:
        db.flush()
    return {"marked": marked, "implementation_gaps": gaps}


def _format_sla_status(result: dict[str, Any]) -> str:
    managers = list(result.get("managers") or [])
    rop_digest = dict(result.get("rop_digest") or {})
    counts = dict(result.get("sla_status_counts") or {})
    count_text = ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "-"
    lines = [
        "Scheduled reporting SLA status",
        f"Report date: {result.get('report_date')}",
        f"Active schedules: {result.get('active_schedules_count', 0)}",
        f"Active managers: {result.get('active_managers_count', 0)}",
        f"SLA counts: {count_text}",
        (
            "ROP digest: "
            f"status={rop_digest.get('status') or '-'} "
            f"sent={_format_bool(rop_digest.get('sent'))} "
            f"recipient={rop_digest.get('recipient') or '-'} "
            f"attachments={rop_digest.get('attachments_count') if rop_digest.get('attachments_count') is not None else '-'} "
            f"rows={rop_digest.get('rows_count') if rop_digest.get('rows_count') is not None else '-'} "
            f"message_id={rop_digest.get('message_id') or '-'} "
            f"reason={rop_digest.get('reason') or '-'}"
        ),
    ]
    if rop_digest.get("delivery_metadata"):
        lines.append(
            "ROP delivery metadata: "
            + json.dumps(rop_digest["delivery_metadata"], ensure_ascii=False, sort_keys=True)
        )
    lines.extend(
        [
            f"Operator summary: {result.get('operator_summary') or '-'}",
            f"Operator action: {rop_digest.get('operator_action') or '-'}",
        ]
    )
    if not managers:
        lines.append("No active manager_daily managers found.")
        return "\n".join(lines)

    lines.append("Managers:")
    for row in managers:
        sla = dict(row.get("sla") or {})
        manager_email = dict(row.get("manager_email") or {})
        batch = dict(row.get("batch") or {})
        label = _manager_alert_label(row)
        lines.append(
            " | ".join(
                [
                    f"- {label}",
                    f"sla={sla.get('sla_status') or '-'}",
                    f"reason={sla.get('reason') or sla.get('sla_missed_reason') or '-'}",
                    f"manager_email={manager_email.get('status') or '-'}",
                    f"batch={batch.get('status') or '-'}",
                ]
            )
        )
    return "\n".join(lines)


def sla_status(args: argparse.Namespace) -> dict[str, Any]:
    report_date = _resolve_sla_report_date(args.date)
    with get_db() as db:
        schedules = _active_manager_daily_schedules(db)
        scope = _manager_scope_from_schedules(db, schedules)
        managers = [
            _build_manager_sla_row(db, scope=item, report_date=report_date)
            for item in scope
        ]
        rop_digest = _load_rop_digest_status(
            db,
            schedules=schedules,
            report_date=report_date,
            managers=managers,
        )
    return {
        "status": "ok",
        "action": "sla_status",
        "report_date": report_date.isoformat(),
        "sla": _sla_window(report_date),
        "active_schedules_count": len(schedules),
        "active_managers_count": len(managers),
        "sla_status_counts": _status_counts(managers),
        "rop_digest": rop_digest,
        "operator_summary": _sla_status_operator_summary(rop_digest),
        "managers": managers,
    }


def _audit_scope_summary(schedules: list[Any], scope: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "active_schedules_count": len(schedules),
        "active_managers_count": len(scope),
        "schedules": [_schedule_summary(schedule) for schedule in schedules],
        "managers": [
            {
                "schedule_id": item.get("schedule_id"),
                "department_id": item.get("department_id"),
                "manager_id": item.get("manager_id"),
                "manager_name": item.get("manager_name"),
                "manager_email": item.get("manager_card_email") or item.get("manager_email"),
                "manager_active": item.get("manager_active"),
                "manager_found": item.get("manager_found"),
            }
            for item in scope
        ],
    }


def _audit_manager_outcome(row: dict[str, Any]) -> dict[str, Any]:
    sla = dict(row.get("sla") or {})
    manager_email = dict(row.get("manager_email") or {})
    batch = dict(row.get("batch") or {})
    calls = dict(row.get("calls") or {})
    return {
        "schedule_id": row.get("schedule_id"),
        "department_id": row.get("department_id"),
        "manager_id": row.get("manager_id"),
        "manager_name": row.get("manager_name"),
        "sla_status": sla.get("sla_status"),
        "manager_email_status": manager_email.get("status"),
        "batch_status": batch.get("status"),
        "batch_id": batch.get("id"),
        "reason": sla.get("reason") or sla.get("sla_missed_reason"),
        "calls_total": int(calls.get("total") or 0),
        "calls_with_audio": int(calls.get("with_audio") or 0),
        "calls_no_audio": int(calls.get("no_audio") or 0),
        "readiness": {
            "stt_ready": (row.get("upstream") or {}).get("stt_ready"),
            "llm1_ready": (row.get("upstream") or {}).get("llm1_ready"),
            "analysis_ready": (row.get("analysis") or {}).get("analysis_ready"),
            "draft_pdf_ready": row.get("draft_pdf_ready"),
        },
        "upstream": row.get("upstream") or {},
        "analysis": row.get("analysis") or {},
    }


def _audit_open_batches_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = [row for row in rows if row.get("potential_manager_daily_blocker")]
    return {
        "count": len(rows),
        "blockers_count": len(blockers),
        "blockers": [
            {
                "batch_id": row.get("batch_id"),
                "schedule_id": row.get("schedule_id"),
                "status": row.get("status"),
                "period": row.get("period"),
                "manager_ids": row.get("manager_ids") or [],
                "reasons": row.get("blocker_reasons") or [],
                "blocked_by_draft_ids": row.get("blocked_by_draft_ids") or [],
                "recovery_hint": row.get("recovery_hint"),
            }
            for row in blockers[:POST_RUN_AUDIT_MAX_ITEMS]
        ],
    }


def _audit_message(kind: str, **values: Any) -> str:
    if kind == "no_scope":
        return "No active manager_daily schedules found."
    if kind == "no_managers":
        return "Active manager_daily schedules have no managers in scope."
    if kind == "open_blockers":
        return f"Open manager_daily blockers: {values.get('count')}."
    if kind == "rop_missing":
        return "ROP digest is missing after delivered manager reports."
    if kind == "rop_failed":
        return f"ROP digest is {values.get('status')}."
    if kind == "manager_blocked":
        return (
            f"{values.get('label')}: blocked "
            f"({values.get('reason') or 'reason not recorded'})."
        )
    if kind == "manager_missed":
        return (
            f"{values.get('label')}: missed pending "
            f"({values.get('reason') or 'reason not recorded'})."
        )
    if kind == "manager_email_failed":
        return (
            f"{values.get('label')}: manager email "
            f"{values.get('status')} ({values.get('reason') or 'reason not recorded'})."
        )
    if kind == "timeout":
        return f"{values.get('label')}: timeout/read_timeout recorded."
    if kind == "errors":
        return f"{values.get('label')}: recorded technical errors."
    return str(values.get("message") or kind)


def _audit_finding(
    *,
    severity: str,
    code: str,
    message: str,
    manager_id: str | None = None,
    manager_name: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "manager_id": manager_id,
        "manager_name": manager_name,
        "batch_id": batch_id,
    }


def _manager_row_error_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    batch = dict(row.get("batch") or {})
    parts.extend(str(item) for item in list(batch.get("errors") or []))
    for draft in list(row.get("drafts") or []):
        parts.extend(str(item) for item in list((draft or {}).get("errors") or []))
    diagnostics = dict(row.get("diagnostics") or {})
    for candidate in diagnostics.get("batch_candidates") or []:
        parts.extend(str(item) for item in list((candidate or {}).get("errors") or []))
    return " ".join(parts)


def _audit_technical_findings(
    *,
    schedules: list[Any],
    scope: list[dict[str, Any]],
    managers: list[dict[str, Any]],
    rop_digest: dict[str, Any],
    open_batches_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not schedules:
        findings.append(
            _audit_finding(
                severity="blocked",
                code="no_active_manager_daily_schedules",
                message=_audit_message("no_scope"),
            )
        )
    elif not scope:
        findings.append(
            _audit_finding(
                severity="blocked",
                code="no_active_manager_daily_managers",
                message=_audit_message("no_managers"),
            )
        )

    if int(open_batches_summary.get("blockers_count") or 0) > 0:
        findings.append(
            _audit_finding(
                severity="blocked",
                code="open_manager_daily_blockers",
                message=_audit_message(
                    "open_blockers",
                    count=open_batches_summary.get("blockers_count"),
                ),
            )
        )

    digest_status = str(rop_digest.get("status") or "").strip()
    if digest_status == "missing_digest":
        findings.append(
            _audit_finding(
                severity="attention_required",
                code="missing_digest",
                message=_audit_message("rop_missing"),
                batch_id=rop_digest.get("batch_id"),
            )
        )
    elif digest_status in {"failed", "blocked"}:
        findings.append(
            _audit_finding(
                severity="blocked",
                code=f"rop_digest_{digest_status}",
                message=_audit_message("rop_failed", status=digest_status),
                batch_id=rop_digest.get("batch_id"),
            )
        )

    for row in managers:
        sla = dict(row.get("sla") or {})
        manager_email = dict(row.get("manager_email") or {})
        batch = dict(row.get("batch") or {})
        status = str(sla.get("sla_status") or "").strip()
        email_status = str(manager_email.get("status") or "").strip()
        reason = str(sla.get("reason") or sla.get("sla_missed_reason") or "").strip()
        label = _manager_alert_label(row)
        common = {
            "manager_id": row.get("manager_id"),
            "manager_name": row.get("manager_name"),
            "batch_id": batch.get("id"),
        }
        if status == "blocked":
            findings.append(
                _audit_finding(
                    severity="blocked",
                    code="manager_blocked",
                    message=_audit_message("manager_blocked", label=label, reason=reason),
                    **common,
                )
            )
        elif status == "missed_pending":
            findings.append(
                _audit_finding(
                    severity="attention_required",
                    code="manager_missed_pending",
                    message=_audit_message("manager_missed", label=label, reason=reason),
                    **common,
                )
            )

        if email_status in {"failed", "blocked"} and not _manager_row_digest_not_required(row):
            findings.append(
                _audit_finding(
                    severity="blocked" if email_status == "blocked" else "attention_required",
                    code=f"manager_email_{email_status}",
                    message=_audit_message(
                        "manager_email_failed",
                        label=label,
                        status=email_status,
                        reason=reason,
                    ),
                    **common,
                )
            )

        searchable = " ".join([reason, _manager_row_error_text(row)]).lower()
        if "timeout" in searchable or "read_timeout" in searchable:
            findings.append(
                _audit_finding(
                    severity="attention_required",
                    code="timeout_or_read_timeout",
                    message=_audit_message("timeout", label=label),
                    **common,
                )
            )
        elif _manager_row_error_text(row) and not _manager_row_digest_not_required(row):
            findings.append(
                _audit_finding(
                    severity="attention_required",
                    code="recorded_technical_errors",
                    message=_audit_message("errors", label=label),
                    **common,
                )
            )
    return findings[: POST_RUN_AUDIT_MAX_ITEMS * 2]


def _audit_status(findings: list[dict[str, Any]]) -> str:
    severities = {str(item.get("severity") or "") for item in findings}
    if "blocked" in severities:
        return "blocked"
    if findings:
        return "attention_required"
    return "ok"


def _audit_recommended_next_actions(
    *,
    status: str,
    findings: list[dict[str, Any]],
    rop_digest: dict[str, Any],
    open_batches_summary: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    codes = {str(item.get("code") or "") for item in findings}
    if status == "ok":
        return ["No action required; keep observing the next scheduled run."]
    if "no_active_manager_daily_schedules" in codes:
        actions.append("Check scheduled_reporting_preflight.py status and restore the active manager_daily schedule if it was disabled intentionally.")
    if "no_active_manager_daily_managers" in codes:
        actions.append("Check active schedule manager_ids and Bitrix manager sync before the next run.")
    if int(open_batches_summary.get("blockers_count") or 0) > 0:
        actions.append("Inspect open-batches for blocker ids; use recover-open-batches only after operator review.")
    digest_status = str(rop_digest.get("status") or "")
    if digest_status == "missing_digest":
        actions.append("Inspect scheduled_rop_daily_digest observability and resend the ROP digest if needed.")
    elif digest_status in {"failed", "blocked"}:
        actions.append("Inspect the ROP digest delivery reason and retry only after fixing the blocker.")
    if any(code.startswith("manager_email_") for code in codes):
        actions.append("Inspect manager draft delivery metadata and recipient resolution for affected managers.")
    if "manager_missed_pending" in codes:
        actions.append("Inspect scheduled batch/draft/readiness for missed_pending managers.")
    if "timeout_or_read_timeout" in codes:
        actions.append("Check API/worker timeout logs before retrying the affected report path.")
    if "recorded_technical_errors" in codes:
        actions.append("Inspect batch and draft errors in scheduled reporting observability.")
    return list(dict.fromkeys(actions)) or ["Review technical_findings and decide the operator action."]


def _format_audit_manager_line(row: dict[str, Any]) -> str:
    label = row.get("manager_name") or row.get("manager_id") or "unknown manager"
    return (
        f"- {label}: sla={row.get('sla_status') or '-'}, "
        f"email={row.get('manager_email_status') or '-'}, "
        f"batch={row.get('batch_status') or '-'}, "
        f"calls={row.get('calls_total', 0)}/{row.get('calls_with_audio', 0)}, "
        f"reason={row.get('reason') or '-'}"
    )


def _format_post_run_audit(result: dict[str, Any]) -> str:
    scope = dict(result.get("scope") or {})
    digest = dict(result.get("rop_digest") or {})
    open_batches = dict(result.get("open_batches") or {})
    findings = list(result.get("technical_findings") or [])
    managers = list(result.get("manager_outcomes") or [])
    lines = [
        "Post-run audit",
        f"Итог дня: status={result.get('status')} report_date={result.get('report_date')} billable_pipeline_started=no",
        (
            "Scope: "
            f"schedules={scope.get('active_schedules_count', 0)} "
            f"managers={scope.get('active_managers_count', 0)}"
        ),
        "",
        "Менеджеры:",
    ]
    if managers:
        lines.extend(_bounded_lines(
            [_format_audit_manager_line(row) for row in managers],
            max_items=POST_RUN_AUDIT_MAX_ITEMS,
            omitted_label="- Еще {omitted} менеджеров см. в JSON.",
        ))
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            (
                "ROP digest: "
                f"status={digest.get('status') or '-'} "
                f"sent={_format_bool(digest.get('sent'))} "
                f"recipient={digest.get('recipient') or '-'} "
                f"attachments={digest.get('attachments_count') if digest.get('attachments_count') is not None else '-'} "
                f"rows={digest.get('rows_count') if digest.get('rows_count') is not None else '-'} "
                f"reason={digest.get('reason') or '-'}"
            ),
            "",
            (
                "Open batches / blockers: "
                f"open_batches={open_batches.get('count', 0)} "
                f"blockers={open_batches.get('blockers_count', 0)}"
            ),
        ]
    )
    blockers = list(open_batches.get("blockers") or [])
    for blocker in blockers:
        reasons = ", ".join(blocker.get("reasons") or []) or "-"
        lines.append(
            f"- batch={blocker.get('batch_id')} status={blocker.get('status')} reasons={reasons}"
        )
    if findings:
        lines.extend(["", "Technical findings:"])
        for finding in findings[:POST_RUN_AUDIT_MAX_ITEMS]:
            lines.append(f"- {finding.get('severity')}: {finding.get('message')}")
        if len(findings) > POST_RUN_AUDIT_MAX_ITEMS:
            lines.append(f"- Еще {len(findings) - POST_RUN_AUDIT_MAX_ITEMS} findings см. в JSON.")
    lines.extend(["", "Что сделать дальше:"])
    for action in result.get("recommended_next_actions") or []:
        lines.append(f"- {action}")
    return "\n".join(lines)


def post_run_audit(args: argparse.Namespace) -> dict[str, Any]:
    report_date = _resolve_sla_report_date(args.date)
    with get_db() as db:
        schedules = _active_manager_daily_schedules(db)
        scope = _manager_scope_from_schedules(db, schedules)
        managers = [
            _build_manager_sla_row(db, scope=item, report_date=report_date)
            for item in scope
        ]
        rop_digest = _load_rop_digest_status(
            db,
            schedules=schedules,
            report_date=report_date,
            managers=managers,
        )
        _, open_rows = _load_open_batch_rows(
            db,
            preset="manager_daily",
            schedule_id=None,
            report_date=report_date,
        )
        scope_summary = _audit_scope_summary(schedules, scope)
    open_batches_summary = _audit_open_batches_summary(open_rows)
    findings = _audit_technical_findings(
        schedules=schedules,
        scope=scope,
        managers=managers,
        rop_digest=rop_digest,
        open_batches_summary=open_batches_summary,
    )
    status = _audit_status(findings)
    return {
        "status": status,
        "action": "post_run_audit",
        "report_date": report_date.isoformat(),
        "scope": scope_summary,
        "manager_outcomes": [_audit_manager_outcome(row) for row in managers],
        "rop_digest": rop_digest,
        "open_batches": open_batches_summary,
        "technical_findings": findings,
        "recommended_next_actions": _audit_recommended_next_actions(
            status=status,
            findings=findings,
            rop_digest=rop_digest,
            open_batches_summary=open_batches_summary,
        ),
        "billable_pipeline_started": False,
    }


def sla_check(args: argparse.Namespace) -> dict[str, Any]:
    report_date = _resolve_sla_report_date(args.date)
    phase = str(args.phase)
    with get_db() as db:
        schedules = _active_manager_daily_schedules(db)
        scope = _manager_scope_from_schedules(db, schedules)
        managers = [
            _build_manager_sla_row(db, scope=item, report_date=report_date)
            for item in scope
        ]
        affected = [row for row in managers if _needs_sla_attention(row, phase=phase)]
        hard_mark = (
            _mark_hard_sla_missed(db, rows=affected, report_date=report_date)
            if phase == "hard"
            else {"marked": [], "implementation_gaps": []}
        )
        alert = _send_sla_alert(phase=phase, report_date=report_date, rows=affected)
    return {
        "status": "ok",
        "action": "sla_check",
        "phase": phase,
        "report_date": report_date.isoformat(),
        "sla": _sla_window(report_date),
        "affected_managers_count": len(affected),
        "affected_managers": [
            {
                "schedule_id": row["schedule_id"],
                "department_id": row["department_id"],
                "manager_id": row["manager_id"],
                "manager_name": row.get("manager_name"),
                "reason": _attention_reason(row),
                "sla_status": (row.get("sla") or {}).get("sla_status"),
                "manager_email_status": (row.get("manager_email") or {}).get("status"),
                "batch_id": (row.get("batch") or {}).get("id") if row.get("batch") else None,
            }
            for row in affected
        ],
        "affected_manager_statuses": affected,
        "hard_mark": hard_mark,
        "alert": alert
        or {
            "status": "skipped",
            "reason": "no_affected_managers",
            "payload": {
                "report_date": report_date.isoformat(),
                "phase": phase,
                "affected_managers_count": 0,
            },
        },
        "manager_statuses": managers,
    }


def _batch_period_summary(batch: Any) -> dict[str, Any]:
    period = dict(getattr(batch, "period", None) or {})
    return {
        "date_from": period.get("date_from"),
        "date_to": period.get("date_to"),
        "raw": period,
    }


def _batch_manager_ids(batch: Any) -> list[str]:
    filters = dict(getattr(batch, "filters", None) or {})
    manager_ids = [
        str(item)
        for item in filters.get("manager_ids") or []
        if str(item or "").strip()
    ]
    observability = dict(getattr(batch, "observability", None) or {})
    selection = dict(observability.get("scheduled_candidate_selection") or {})
    selected_manager = str(selection.get("manager_id") or "").strip()
    if selected_manager and selected_manager not in manager_ids:
        manager_ids.append(selected_manager)
    return manager_ids


def _is_manager_daily_blocker(schedule: Any, batch: Any) -> bool:
    return (
        str(getattr(schedule, "preset", "") or "") == "manager_daily"
        and str(getattr(batch, "status", "") or "") in OPEN_BATCH_STATUSES
    )


def _blocker_reasons(schedule: Any, batch: Any) -> list[str]:
    if not _is_manager_daily_blocker(schedule, batch):
        return []
    reasons = ["open batch on active manager_daily schedule"]
    if bool(getattr(batch, "review_required", False)):
        reasons.append("review_required=true")
    if not bool(getattr(batch, "business_email_enabled", False)):
        reasons.append("business_email_enabled=false")
    return reasons


def _blocked_by_draft_ids(drafts: list[Any]) -> list[str]:
    return [str(getattr(draft, "id")) for draft in drafts if getattr(draft, "id", None)]


def _blocked_by_draft_statuses(drafts: list[Any]) -> dict[str, str | None]:
    return {
        str(getattr(draft, "id")): getattr(draft, "status", None)
        for draft in drafts
        if getattr(draft, "id", None)
    }


def _open_batch_recovery_hint(batch: Any, *, is_blocker: bool) -> str | None:
    if not is_blocker:
        return None
    batch_id = str(getattr(batch, "id"))
    return (
        "scheduled_reporting_preflight.py recover-open-batches "
        f"--batch-id {batch_id} --target-status paused --apply"
    )


def _open_batch_row(schedule: Any, batch: Any, drafts: list[Any] | None = None) -> dict[str, Any]:
    drafts = drafts or []
    reasons = _blocker_reasons(schedule, batch)
    is_blocker = bool(reasons)
    batch_id = str(getattr(batch, "id"))
    batch_status = getattr(batch, "status", None)
    return {
        "schedule_id": str(getattr(schedule, "id")),
        "schedule_preset": getattr(schedule, "preset", None),
        "schedule_enabled": bool(getattr(schedule, "enabled", False)),
        "schedule_next_run_at": _as_iso(getattr(schedule, "next_run_at", None)),
        "batch_id": batch_id,
        "status": batch_status,
        "period": _batch_period_summary(batch),
        "manager_ids": _batch_manager_ids(batch),
        "business_email_enabled": bool(getattr(batch, "business_email_enabled", False)),
        "review_required": bool(getattr(batch, "review_required", False)),
        "planned_for": _as_iso(getattr(batch, "planned_for", None)),
        "created_at": _as_iso(getattr(batch, "created_at", None)),
        "potential_manager_daily_blocker": is_blocker,
        "blocker_reasons": reasons,
        "blocked_by_batch_id": batch_id if is_blocker else None,
        "blocked_by_batch_status": batch_status if is_blocker else None,
        "blocked_by_draft_ids": _blocked_by_draft_ids(drafts) if is_blocker else [],
        "blocked_by_draft_statuses": _blocked_by_draft_statuses(drafts) if is_blocker else {},
        "blocker_scope": "open_batch_visibility" if is_blocker else None,
        "recovery_hint": _open_batch_recovery_hint(batch, is_blocker=is_blocker),
    }


def _load_open_batch_rows(
    db: Any,
    *,
    preset: str,
    schedule_id: str | None,
    report_date: date | None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    schedule_query = db.query(ReportingSchedule).filter(
        ReportingSchedule.deleted_at.is_(None),
        ReportingSchedule.enabled.is_(True),
    )
    if schedule_id:
        schedule_query = schedule_query.filter(ReportingSchedule.id == UUID(schedule_id))
    if preset != "all":
        schedule_query = schedule_query.filter(ReportingSchedule.preset == preset)
    schedules = schedule_query.order_by(ReportingSchedule.created_at.asc()).all()
    if not schedules:
        return [], []

    schedule_by_id = {str(schedule.id): schedule for schedule in schedules}
    batches = (
        db.query(ScheduledReportBatch)
        .filter(
            ScheduledReportBatch.schedule_id.in_([schedule.id for schedule in schedules]),
            ScheduledReportBatch.status.in_(list(OPEN_BATCH_STATUSES)),
        )
        .order_by(ScheduledReportBatch.created_at.desc())
        .all()
    )
    draft_rows = []
    if batches:
        draft_rows = (
            db.query(ScheduledReportDraft)
            .filter(ScheduledReportDraft.batch_id.in_([batch.id for batch in batches]))
            .order_by(ScheduledReportDraft.created_at.asc())
            .all()
        )
    drafts_by_batch_id: dict[str, list[Any]] = {}
    for draft in draft_rows:
        drafts_by_batch_id.setdefault(str(draft.batch_id), []).append(draft)
    rows = [
        _open_batch_row(
            schedule_by_id[str(batch.schedule_id)],
            batch,
            drafts=drafts_by_batch_id.get(str(batch.id), []),
        )
        for batch in batches
    ]
    if report_date is not None:
        day = report_date.isoformat()
        rows = [
            row
            for row in rows
            if (row["period"].get("date_from") == day or row["period"].get("date_to") == day)
        ]
    return schedules, rows


def open_batches(args: argparse.Namespace) -> dict[str, Any]:
    report_date = date.fromisoformat(args.date) if args.date else None
    with get_db() as db:
        schedules, rows = _load_open_batch_rows(
            db,
            preset=args.preset,
            schedule_id=args.schedule_id,
            report_date=report_date,
        )
    blockers = [row for row in rows if row["potential_manager_daily_blocker"]]
    return {
        "status": "ok",
        "action": "open_batch_diagnostics",
        "preset": args.preset,
        "schedule_id": args.schedule_id,
        "report_date": report_date.isoformat() if report_date else None,
        "active_schedules_count": len(schedules),
        "open_batches_count": len(rows),
        "potential_manager_daily_blockers_count": len(blockers),
        "open_batches": rows,
    }


def _format_bool(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _format_open_batch_diagnostics(result: dict[str, Any]) -> str:
    rows = list(result.get("open_batches") or [])
    blockers = int(result.get("potential_manager_daily_blockers_count") or 0)
    lines = [
        "Scheduled reporting open batch diagnostics",
        f"Active schedules checked: {result.get('active_schedules_count', 0)}",
        f"Open batches: {len(rows)}",
        f"Potential manager_daily blockers: {blockers}",
    ]
    if not rows:
        lines.append("No open batches found for the selected active schedules.")
        return "\n".join(lines)

    for row in rows:
        period = dict(row.get("period") or {})
        date_from = period.get("date_from") or "-"
        date_to = period.get("date_to") or date_from
        managers = ", ".join(row.get("manager_ids") or []) or "all/unknown"
        marker = "BLOCKER" if row.get("potential_manager_daily_blocker") else "open"
        lines.append(
            " | ".join(
                [
                    f"- {marker}",
                    f"batch={row.get('batch_id')}",
                    f"schedule={row.get('schedule_id')}",
                    f"preset={row.get('schedule_preset')}",
                    f"status={row.get('status')}",
                    f"period={date_from}..{date_to}",
                    f"manager_ids={managers}",
                    f"business_email_enabled={_format_bool(row.get('business_email_enabled'))}",
                    f"review_required={_format_bool(row.get('review_required'))}",
                ]
            )
        )
        reasons = row.get("blocker_reasons") or []
        if reasons:
            lines.append(f"  blocker_reason: {', '.join(reasons)}")
        if row.get("blocked_by_batch_id"):
            draft_ids = ", ".join(row.get("blocked_by_draft_ids") or []) or "-"
            lines.append(
                "  blocked_by: "
                f"batch={row.get('blocked_by_batch_id')} "
                f"status={row.get('blocked_by_batch_status') or '-'} "
                f"drafts={draft_ids}"
            )
        if row.get("recovery_hint"):
            lines.append(f"  recovery_hint: {row['recovery_hint']}")
    return "\n".join(lines)


def _batch_period_starts_before(batch: Any, before_date: date) -> bool:
    period = dict(getattr(batch, "period", None) or {})
    raw_date = str(period.get("date_from") or "").strip()
    if not raw_date:
        return False
    return date.fromisoformat(raw_date) < before_date


def _recovery_plan_item(
    *,
    schedule: Any,
    batch: Any,
    target_status: str,
    reason: str,
) -> dict[str, Any]:
    current_status = str(getattr(batch, "status", "") or "")
    allowed_targets = SCHEDULED_REVIEWABLE_BATCH_ALLOWED_TRANSITIONS.get(current_status, ())
    allowed = target_status in allowed_targets
    return {
        **_open_batch_row(schedule, batch),
        "current_status": current_status,
        "target_status": target_status,
        "transition_allowed": allowed,
        "action": "transition" if allowed else "skip",
        "skip_reason": None if allowed else f"transition_not_allowed:{current_status}->{target_status}",
        "recovery_reason": reason,
    }


def _build_recovery_plan(
    *,
    schedules: list[Any],
    batches: list[Any],
    target_status: str,
    reason: str,
) -> list[dict[str, Any]]:
    schedule_by_id = {str(schedule.id): schedule for schedule in schedules}
    return [
        _recovery_plan_item(
            schedule=schedule_by_id[str(batch.schedule_id)],
            batch=batch,
            target_status=target_status,
            reason=reason,
        )
        for batch in batches
        if str(batch.schedule_id) in schedule_by_id
    ]


def _load_recovery_targets(
    db: Any,
    *,
    preset: str,
    schedule_id: str | None,
    batch_ids: list[str],
    before_date: date | None,
    statuses: list[str],
) -> tuple[list[Any], list[Any]]:
    schedule_query = db.query(ReportingSchedule).filter(
        ReportingSchedule.deleted_at.is_(None),
        ReportingSchedule.enabled.is_(True),
    )
    if schedule_id:
        schedule_query = schedule_query.filter(ReportingSchedule.id == UUID(schedule_id))
    if preset != "all":
        schedule_query = schedule_query.filter(ReportingSchedule.preset == preset)
    schedules = schedule_query.order_by(ReportingSchedule.created_at.asc()).all()
    if not schedules:
        return [], []

    batch_query = db.query(ScheduledReportBatch).filter(
        ScheduledReportBatch.schedule_id.in_([schedule.id for schedule in schedules]),
        ScheduledReportBatch.status.in_(statuses),
    )
    if batch_ids:
        batch_query = batch_query.filter(
            ScheduledReportBatch.id.in_([UUID(batch_id) for batch_id in batch_ids])
        )
    batches = batch_query.order_by(ScheduledReportBatch.created_at.desc()).all()
    if before_date is not None and not batch_ids:
        batches = [batch for batch in batches if _batch_period_starts_before(batch, before_date)]
    return schedules, batches


def _apply_recovery_plan(
    db: Any,
    *,
    service: ScheduledReviewableReportingService,
    plan: list[dict[str, Any]],
    target_status: str,
    reason: str,
) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    applied_at = datetime.now(UTC).isoformat()
    for item in plan:
        if item.get("action") != "transition":
            continue
        batch = (
            db.query(ScheduledReportBatch)
            .filter(ScheduledReportBatch.id == UUID(str(item["batch_id"])))
            .first()
        )
        if batch is None:
            applied.append({**item, "applied": False, "apply_error": "batch_not_found"})
            continue
        service._transition_batch_status(batch, target_status)
        if target_status == "paused":
            batch.paused_at = datetime.now(UTC)
        elif target_status == "failed":
            batch.failed_at = datetime.now(UTC)
        errors = list(batch.errors or [])
        errors.append(reason)
        batch.errors = errors
        observability = dict(batch.observability or {})
        history = list(observability.get("operator_recovery") or [])
        history.append(
            {
                "applied_at": applied_at,
                "from_status": item.get("current_status"),
                "to_status": target_status,
                "reason": reason,
                "tool": "scheduled_reporting_preflight.recover-open-batches",
            }
        )
        observability["operator_recovery"] = history
        batch.observability = observability
        applied.append({**item, "applied": True, "applied_at": applied_at})
    if applied:
        db.flush()
    return applied


def recover_open_batches(args: argparse.Namespace) -> dict[str, Any]:
    batch_ids = [str(item).strip() for item in args.batch_id or [] if str(item).strip()]
    if not batch_ids and not args.before_date:
        raise ASAError("recover-open-batches requires --before-date or one or more --batch-id values")
    before_date = date.fromisoformat(args.before_date) if args.before_date else None
    statuses = args.status or list(OPEN_BATCH_STATUSES)
    reason = args.reason or DEFAULT_RECOVERY_REASON
    with get_db() as db:
        schedules, batches = _load_recovery_targets(
            db,
            preset=args.preset,
            schedule_id=args.schedule_id,
            batch_ids=batch_ids,
            before_date=before_date,
            statuses=statuses,
        )
        service = ScheduledReviewableReportingService(db=db)
        plan = _build_recovery_plan(
            schedules=schedules,
            batches=batches,
            target_status=args.target_status,
            reason=reason,
        )
        applied = (
            _apply_recovery_plan(
                db,
                service=service,
                plan=plan,
                target_status=args.target_status,
                reason=reason,
            )
            if args.apply
            else []
        )
    return {
        "status": "ok",
        "action": "open_batch_recovery",
        "mode": "apply" if args.apply else "dry_run",
        "preset": args.preset,
        "schedule_id": args.schedule_id,
        "before_date": before_date.isoformat() if before_date else None,
        "target_status": args.target_status,
        "reason": reason,
        "matched_batches_count": len(plan),
        "planned_transitions_count": len([item for item in plan if item["action"] == "transition"]),
        "skipped_count": len([item for item in plan if item["action"] != "transition"]),
        "applied_count": len([item for item in applied if item.get("applied")]),
        "plan": plan,
        "applied": applied,
    }


def _format_recovery_plan(result: dict[str, Any]) -> str:
    mode = str(result.get("mode") or "dry_run")
    plan = list(result.get("plan") or [])
    lines = [
        "Scheduled reporting open batch recovery",
        f"Mode: {mode}",
        f"Matched batches: {result.get('matched_batches_count', 0)}",
        f"Planned transitions: {result.get('planned_transitions_count', 0)}",
        f"Skipped: {result.get('skipped_count', 0)}",
        f"Target status: {result.get('target_status')}",
    ]
    if mode != "apply":
        lines.append("Dry run only: no database rows were changed. Re-run with --apply to apply.")
    if not plan:
        lines.append("No matching blocking batches found.")
        return "\n".join(lines)
    for item in plan:
        period = dict(item.get("period") or {})
        managers = ", ".join(item.get("manager_ids") or []) or "all/unknown"
        action = item.get("action")
        transition = f"{item.get('current_status')}->{item.get('target_status')}"
        lines.append(
            " | ".join(
                [
                    f"- {action}",
                    f"batch={item.get('batch_id')}",
                    f"schedule={item.get('schedule_id')}",
                    f"transition={transition}",
                    f"period={period.get('date_from') or '-'}..{period.get('date_to') or period.get('date_from') or '-'}",
                    f"manager_ids={managers}",
                    f"business_email_enabled={_format_bool(item.get('business_email_enabled'))}",
                    f"review_required={_format_bool(item.get('review_required'))}",
                ]
            )
        )
        if item.get("skip_reason"):
            lines.append(f"  skip_reason: {item['skip_reason']}")
    if mode == "apply":
        lines.append(f"Applied transitions: {result.get('applied_count', 0)}")
    return "\n".join(lines)


def _create_schedule_with_guardrails(
    *,
    service: ScheduledReviewableReportingService,
    department_id: str,
    manager_ids: list[str],
    preset: str,
    enabled: bool,
    start_date: str,
    start_time: str,
    timezone_name: str,
    recurrence: str,
    period_rule: str,
    mode: str,
    business_email_enabled: bool,
    review_required: bool,
    allow_conflicts: bool,
    dry_run: bool = False,
) -> dict[str, Any]:
    normalized_manager_ids = _normalize_manager_ids(manager_ids)
    existing_schedules = service.list_schedules()
    conflicts = []
    if enabled:
        conflicts = _active_schedule_conflicts(
            existing_schedules,
            department_id=department_id,
            preset=preset,
            manager_ids=normalized_manager_ids,
            recurrence=recurrence,
            period_rule=period_rule,
        )
    if conflicts and not allow_conflicts:
        raise ASAError(
            "active schedule conflict detected; use status or --allow-conflicts after operator review. "
            + json.dumps(_summarize_conflicts(conflicts), ensure_ascii=False)
        )

    requested = {
        "department_id": department_id,
        "manager_ids": normalized_manager_ids,
        "preset": preset,
        "enabled": bool(enabled),
        "start_date": start_date,
        "start_time": start_time,
        "timezone": timezone_name,
        "recurrence_type": recurrence,
        "report_period_rule": period_rule,
        "mode": mode,
        "business_email_enabled": bool(business_email_enabled),
        "review_required": bool(review_required),
    }
    if dry_run:
        return {
            "status": "ok",
            "action": "dry_run_create_schedule",
            "would_create": requested,
            "conflicts": _summarize_conflicts(conflicts),
            "conflicts_allowed": bool(allow_conflicts),
        }

    schedule = service.create_schedule(
        department_id=department_id,
        manager_ids=normalized_manager_ids,
        preset=preset,
        enabled=enabled,
        start_date=start_date,
        start_time=start_time,
        timezone_name=timezone_name,
        recurrence_type=recurrence,
        report_period_rule=period_rule,
        mode=mode,
        business_email_enabled=business_email_enabled,
        review_required=review_required,
    )
    return {
        "status": "ok",
        "action": "create_schedule",
        "schedule": schedule,
        "conflicts": _summarize_conflicts(conflicts),
        "conflicts_allowed": bool(allow_conflicts),
    }


def create_schedule(args: argparse.Namespace) -> dict[str, Any]:
    with get_db() as db:
        service = ScheduledReviewableReportingService(db=db)
        return _create_schedule_with_guardrails(
            service=service,
            department_id=args.department_id,
            manager_ids=args.manager_id or [],
            preset=args.preset,
            enabled=args.enabled,
            start_date=args.start_date,
            start_time=args.start_time,
            timezone_name=args.timezone,
            recurrence=args.recurrence,
            period_rule=args.period_rule,
            mode=args.mode,
            business_email_enabled=args.business_email_enabled,
            review_required=args.review_required,
            allow_conflicts=args.allow_conflicts,
        )


def create_production_manager_daily_schedule(args: argparse.Namespace) -> dict[str, Any]:
    manager_ids = _normalize_manager_ids(args.manager_id or [])
    if len(manager_ids) != args.expected_manager_count:
        raise ASAError(
            f"Expected {args.expected_manager_count} manager_ids, got {len(manager_ids)}."
        )
    first_report_date = date.fromisoformat(args.first_report_date)
    start_date = (first_report_date + timedelta(days=1)).isoformat()
    with get_db() as db:
        service = ScheduledReviewableReportingService(db=db)
        result = _create_schedule_with_guardrails(
            service=service,
            department_id=args.department_id,
            manager_ids=manager_ids,
            preset="manager_daily",
            enabled=args.enabled,
            start_date=start_date,
            start_time=args.start_time,
            timezone_name=args.timezone,
            recurrence="daily",
            period_rule="previous_day",
            mode=args.mode,
            business_email_enabled=args.business_email_enabled,
            review_required=args.review_required,
            allow_conflicts=args.allow_conflicts,
            dry_run=args.dry_run,
        )
        result["production_smoke"] = {
            "first_report_date": first_report_date.isoformat(),
            "derived_schedule_start_date": start_date,
            "manager_count": len(manager_ids),
            "review_gate": bool(args.review_required),
            "billable_pipeline_started": False,
        }
        return result


def approve_batch(args: argparse.Namespace) -> dict[str, Any]:
    with get_db() as db:
        service = ScheduledReviewableReportingService(db=db)
        batch = service.approve_batch(batch_id=args.batch_id, editor=args.editor)
        return {"status": "ok", "action": "approve_batch", "batch": batch}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="List schedules and recent review batches.")
    subparsers.add_parser("scan-due", help="Run one due-schedule scan.")

    runtime_parser = subparsers.add_parser(
        "runtime-status",
        help="Check API and worker loaded commit/feature markers without billable work.",
    )
    runtime_parser.add_argument(
        "--target",
        choices=["api", "worker", "both"],
        default="both",
        help="Runtime target to probe.",
    )
    runtime_parser.add_argument(
        "--api-url",
        default="http://localhost:8000/status",
        help="API base URL or /status URL.",
    )
    runtime_parser.add_argument(
        "--worker-queue",
        default=ANALYSIS_QUEUE,
        help=f"Celery queue to probe with runtime.identity, e.g. {ANALYSIS_QUEUE} or {CALL_PROCESSING_QUEUE}.",
    )
    runtime_parser.add_argument(
        "--expected-commit",
        help="Expected git commit; defaults to current repo HEAD.",
    )
    runtime_parser.add_argument(
        "--required-marker",
        action="append",
        choices=list(REQUIRED_CODE_MARKERS),
        help="Required code marker; may be repeated. Defaults to all required markers.",
    )
    runtime_parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP/Celery probe timeout in seconds.",
    )

    open_batch_parser = subparsers.add_parser(
        "open-batches",
        help="Show open batches on active schedules and flag manager_daily blockers.",
    )
    open_batch_parser.add_argument("--preset", default="manager_daily")
    open_batch_parser.add_argument("--schedule-id")
    open_batch_parser.add_argument(
        "--date",
        help="Optional report date filter in YYYY-MM-DD format.",
    )

    recovery_parser = subparsers.add_parser(
        "recover-open-batches",
        help="Dry-run-first recovery plan for old blocking open batches.",
    )
    recovery_parser.add_argument("--preset", default="manager_daily")
    recovery_parser.add_argument("--schedule-id")
    recovery_parser.add_argument("--batch-id", action="append", default=[])
    recovery_parser.add_argument(
        "--before-date",
        help="Only target batches whose period.date_from is before this YYYY-MM-DD date.",
    )
    recovery_parser.add_argument(
        "--status",
        action="append",
        choices=list(RECOVERABLE_BATCH_STATUSES),
        help="Limit target batch statuses; may be repeated.",
    )
    recovery_parser.add_argument("--target-status", default="paused", choices=["paused", "failed"])
    recovery_parser.add_argument("--reason", default=DEFAULT_RECOVERY_REASON)
    recovery_parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the planned allowed status transitions. Without this flag no rows are changed.",
    )

    sla_status_parser = subparsers.add_parser(
        "sla-status",
        help="Inspect manager_daily SLA readiness for one report date.",
    )
    sla_status_parser.add_argument(
        "--date",
        default="auto",
        help=(
            "Report date in YYYY-MM-DD format; default/auto means previous day "
            f"in {SLA_TIMEZONE}."
        ),
    )

    post_run_audit_parser = subparsers.add_parser(
        "post-run-audit",
        help="Read-only post-run audit for one manager_daily report date.",
    )
    post_run_audit_parser.add_argument(
        "--date",
        required=True,
        help="Report date in YYYY-MM-DD format.",
    )

    sla_check_parser = subparsers.add_parser(
        "sla-check",
        help="Run a safe manager_daily SLA precheck or hard check for one report date.",
    )
    sla_check_parser.add_argument(
        "--date",
        default="auto",
        help=(
            "Report date in YYYY-MM-DD format; default/auto means previous day "
            f"in {SLA_TIMEZONE}."
        ),
    )
    sla_check_parser.add_argument("--phase", required=True, choices=["precheck", "hard"])

    create = subparsers.add_parser("create", help="Create one schedule.")
    create.add_argument("--department-id", required=True)
    create.add_argument("--manager-id", action="append", default=[])
    create.add_argument("--preset", default="manager_daily")
    create.add_argument("--mode", default="report_from_ready_data_only")
    create.add_argument("--start-date", required=True)
    create.add_argument("--start-time", required=True)
    create.add_argument("--timezone", default="Asia/Almaty")
    create.add_argument("--recurrence", default="daily", choices=["daily", "weekly"])
    create.add_argument("--period-rule", default="previous_day")
    create.add_argument("--enabled", action=argparse.BooleanOptionalAction, default=True)
    create.add_argument("--business-email-enabled", action=argparse.BooleanOptionalAction, default=False)
    create.add_argument("--review-required", action=argparse.BooleanOptionalAction, default=True)
    create.add_argument(
        "--allow-conflicts",
        action="store_true",
        help="Create even if an active overlapping schedule already exists.",
    )

    prod_create = subparsers.add_parser(
        "create-production-manager-daily",
        help="Safely create the pilot manager_daily production schedule.",
    )
    prod_create.add_argument("--department-id", required=True)
    prod_create.add_argument("--manager-id", action="append", required=True)
    prod_create.add_argument(
        "--first-report-date",
        required=True,
        help="First manager_daily report date; schedule start_date is derived as the next day.",
    )
    prod_create.add_argument("--start-time", default="04:00")
    prod_create.add_argument("--timezone", default="Asia/Almaty")
    prod_create.add_argument("--mode", default="build_missing_and_report")
    prod_create.add_argument("--expected-manager-count", type=int, default=4)
    prod_create.add_argument("--enabled", action=argparse.BooleanOptionalAction, default=True)
    prod_create.add_argument("--business-email-enabled", action=argparse.BooleanOptionalAction, default=True)
    prod_create.add_argument("--review-required", action=argparse.BooleanOptionalAction, default=False)
    prod_create.add_argument("--allow-conflicts", action="store_true")
    prod_create.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the schedule payload without writing to the database.",
    )

    approve = subparsers.add_parser("approve", help="Approve one review batch and run delivery.")
    approve.add_argument("--batch-id", required=True)
    approve.add_argument("--editor", default="codex_cli")

    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            result = status()
        elif args.command == "scan-due":
            result = scan_due()
        elif args.command == "runtime-status":
            result = runtime_status(args)
        elif args.command == "open-batches":
            result = open_batches(args)
        elif args.command == "recover-open-batches":
            result = recover_open_batches(args)
        elif args.command == "sla-status":
            result = sla_status(args)
        elif args.command == "post-run-audit":
            result = post_run_audit(args)
        elif args.command == "sla-check":
            result = sla_check(args)
        elif args.command == "create":
            result = create_schedule(args)
        elif args.command == "create-production-manager-daily":
            result = create_production_manager_daily_schedule(args)
        elif args.command == "approve":
            result = approve_batch(args)
        else:  # pragma: no cover - argparse enforces this
            raise RuntimeError(f"Unsupported command: {args.command}")
    except (ASAError, RuntimeError, ValueError) as exc:
        payload = {"status": "failed", "error": f"{exc.__class__.__name__}: {exc}"}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else payload["error"], file=sys.stderr)
        return 2

    _emit(result, as_json=args.json)
    if result.get("action") == "runtime_status" and result.get("status") == "blocked":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
