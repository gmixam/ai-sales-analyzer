#!/usr/bin/env python3
"""Operator preflight for controlled company-wide transcription rollout."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.agents.call_processing import (  # noqa: E402
    CallProcessingService,
    EnsureMode,
    ProcessingRunStatus,
    ProcessingScope,
    RequiredArtifactKind,
    stable_scope_hash,
)
from app.agents.call_processing.repositories import ProcessingRunRepository  # noqa: E402
from app.core_shared.config.settings import settings  # noqa: E402
from app.core_shared.db.session import get_db  # noqa: E402
from app.core_shared.workers.tasks import (  # noqa: E402
    DAILY_UPSTREAM_REQUIRED_ARTIFACTS,
    _daily_upstream_scope,
)

REQUIRED_ARTIFACTS: tuple[RequiredArtifactKind, ...] = DAILY_UPSTREAM_REQUIRED_ARTIFACTS
BLOCKING_BUDGET_STATUSES = {"over_budget", "no_budget_configured"}
WARNING_BUDGET_STATUSES = {"warning", "price_missing", "usage_missing"}
READY_RUN_STATUSES = {ProcessingRunStatus.READY.value, "completed"}


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


def _print_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(f"status: {payload.get('status')}")
    print(f"date: {payload.get('date')}")
    print(f"operator_next_step: {payload.get('operator_next_step')}")


def _target_date(value: str) -> date:
    return date.fromisoformat(value)


def _runtime_scope(target_date: date, db: Any) -> ProcessingScope:
    return _daily_upstream_scope(target_date, db)


def _required_artifact_values() -> list[str]:
    return [item.value for item in REQUIRED_ARTIFACTS]


def _scope_summary(scope: ProcessingScope) -> dict[str, Any]:
    payload = scope.model_dump(mode="json", exclude_none=True)
    return {
        "scope_mode": scope.scope_mode,
        "scope_hash": stable_scope_hash(scope),
        "date_from": payload.get("date_from"),
        "date_to": payload.get("date_to"),
        "source": payload.get("source"),
        "department_id": payload.get("department_id"),
        "fallback_department_id": payload.get("fallback_department_id"),
        "min_duration_sec": payload.get("min_duration_sec"),
        "scope_manager_count": scope.scope_manager_count
        if scope.scope_manager_count is not None
        else len(scope.manager_ids),
        "scope_extension_count": scope.scope_extension_count
        if scope.scope_extension_count is not None
        else len(scope.extensions),
        "scope_department_count": scope.scope_department_count,
        "scope_diagnostics": list(scope.scope_diagnostics),
        "manager_ids": list(scope.manager_ids),
        "extensions": list(scope.extensions),
    }


def _run_costs_from_counts(counts: dict[str, Any]) -> dict[str, Any]:
    costs = counts.get("costs")
    return dict(costs) if isinstance(costs, dict) else {}


def _forecast_summary(counts: dict[str, Any], costs: dict[str, Any] | None = None) -> dict[str, Any]:
    costs = costs or {}
    return {
        "source_targeted_total": int(counts.get("source_targeted_total") or 0),
        "eligible_audio_calls": int(counts.get("eligible_audio_calls") or 0),
        "eligible_audio_calls_with_record_url": int(
            counts.get("eligible_audio_calls_with_record_url") or 0
        ),
        "eligible_audio_calls_missing_record_url": int(
            counts.get("eligible_audio_calls_missing_record_url") or 0
        ),
        "no_audio_calls": int(counts.get("no_audio_calls") or 0),
        "missed_calls": int(counts.get("missed_calls") or 0),
        "zero_talk_calls": int(counts.get("zero_talk_calls") or 0),
        "billable_minutes_estimate": int(
            counts.get("billable_minutes_estimate")
            or counts.get("forecast_billable_minutes")
            or costs.get("forecast_billable_minutes")
            or 0
        ),
        "provider_calls_estimate": int(counts.get("provider_calls_estimate") or 0),
        "provider_calls_budget": counts.get("provider_calls_budget"),
        "provider_calls_budget_status": counts.get("provider_calls_budget_status")
        or costs.get("provider_calls_budget_status"),
        "forecast_budget_status": counts.get("forecast_budget_status")
        or costs.get("forecast_budget_status")
        or costs.get("budget_status"),
        "forecast_cost_usdt": counts.get("forecast_cost_usdt")
        if counts.get("forecast_cost_usdt") is not None
        else costs.get("forecast_cost_usdt")
        if costs.get("forecast_cost_usdt") is not None
        else costs.get("total_current_run_cost_usdt"),
        "cost_status": costs.get("cost_status"),
    }


def _budget_not_blocked(forecast: dict[str, Any] | None, counts: dict[str, Any] | None = None) -> bool:
    forecast = forecast or {}
    counts = counts or {}
    provider_status = str(forecast.get("provider_calls_budget_status") or "")
    forecast_status = str(forecast.get("forecast_budget_status") or forecast.get("cost_status") or "")
    if provider_status in BLOCKING_BUDGET_STATUSES or forecast_status in BLOCKING_BUDGET_STATUSES:
        return False
    if int(counts.get("quota_blocked") or 0) > 0:
        return False
    return str(counts.get("error_class") or "") != "quota_insufficient"


def _no_provider_calls_in_dry_run(counts: dict[str, Any] | None) -> bool:
    counts = counts or {}
    guarded_fields = (
        "provider_calls_made",
        "source_provider_calls_made",
        "transcripts_built",
        "llm1_first_pass_built",
    )
    return all(int(counts.get(field) or 0) == 0 for field in guarded_fields)


def _acceptance(
    scope: ProcessingScope,
    *,
    forecast: dict[str, Any] | None = None,
    counts: dict[str, Any] | None = None,
    ready_run: bool | None = None,
    enforce_no_provider_dry_run: bool = True,
) -> dict[str, Any]:
    scope_mode_is_company = str(scope.scope_mode or "").strip().lower() == "company"
    has_extensions = bool(scope.extensions)
    has_fallback_department = bool(scope.fallback_department_id or scope.department_id)
    budget_ok = _budget_not_blocked(forecast, counts)
    no_provider_calls = (
        _no_provider_calls_in_dry_run(counts) if enforce_no_provider_dry_run else True
    )
    ready_for_trial = (
        scope_mode_is_company
        and has_extensions
        and has_fallback_department
        and budget_ok
        and no_provider_calls
    )
    if ready_run is not None:
        ready_for_trial = ready_for_trial and ready_run
    return {
        "scope_mode_is_company": scope_mode_is_company,
        "has_extensions": has_extensions,
        "has_fallback_department": has_fallback_department,
        "budget_not_blocked": budget_ok,
        "no_provider_stt_llm_calls_in_dry_run": no_provider_calls,
        "has_ready_upstream_run": ready_run,
        "ready_for_provider_backed_trial": ready_for_trial,
    }


def _status_from_acceptance(
    acceptance: dict[str, Any],
    *,
    forecast: dict[str, Any] | None = None,
    run_status: str | None = None,
) -> str:
    if not acceptance.get("scope_mode_is_company"):
        return "blocked"
    if not acceptance.get("has_extensions") or not acceptance.get("has_fallback_department"):
        return "blocked"
    if not acceptance.get("budget_not_blocked"):
        return "blocked"
    if not acceptance.get("no_provider_stt_llm_calls_in_dry_run"):
        return "blocked"
    if run_status is not None and run_status not in READY_RUN_STATUSES:
        return "warning" if run_status in {"partial", "running", "queued", "stale"} else "blocked"
    forecast = forecast or {}
    if str(forecast.get("provider_calls_budget_status") or "") in WARNING_BUDGET_STATUSES:
        return "warning"
    if str(forecast.get("forecast_budget_status") or "") in WARNING_BUDGET_STATUSES:
        return "warning"
    if acceptance.get("has_ready_upstream_run") is False:
        return "blocked"
    return "ok"


def _blockers(
    acceptance: dict[str, Any],
    *,
    forecast: dict[str, Any] | None = None,
    counts: dict[str, Any] | None = None,
    run: dict[str, Any] | None = None,
) -> list[str]:
    blockers: list[str] = []
    if not acceptance.get("scope_mode_is_company"):
        blockers.append("scheduled_runtime_scope_is_not_company")
    if not acceptance.get("has_extensions"):
        blockers.append("scheduled_runtime_scope_has_no_extensions")
    if not acceptance.get("has_fallback_department"):
        blockers.append("fallback_department_not_configured")
    if not acceptance.get("budget_not_blocked"):
        blockers.append("budget_or_quota_blocked")
    if not acceptance.get("no_provider_stt_llm_calls_in_dry_run"):
        blockers.append("dry_run_recorded_provider_stt_or_llm_calls")
    if acceptance.get("has_ready_upstream_run") is False:
        blockers.append("ready_upstream_run_not_found")
    if run and str(run.get("status") or "") not in READY_RUN_STATUSES:
        blockers.append(f"latest_run_status:{run.get('status')}")
    for diagnostic in list((counts or {}).get("scope_diagnostics") or []):
        if diagnostic in {"fallback_department_not_configured", "scope_extensions_empty"}:
            blockers.append(diagnostic)
    forecast = forecast or {}
    if str(forecast.get("provider_calls_budget_status") or "") in BLOCKING_BUDGET_STATUSES:
        blockers.append(f"provider_calls_budget_status:{forecast.get('provider_calls_budget_status')}")
    if str(forecast.get("forecast_budget_status") or "") in BLOCKING_BUDGET_STATUSES:
        blockers.append(f"forecast_budget_status:{forecast.get('forecast_budget_status')}")
    return sorted(set(blockers))


def _scope_preview_payload(target_date: date, scope: ProcessingScope) -> dict[str, Any]:
    acceptance = _acceptance(scope)
    status = _status_from_acceptance(acceptance)
    return {
        "action": "scope-preview",
        "status": status,
        "date": target_date.isoformat(),
        "scope": _scope_summary(scope),
        "forecast": None,
        "acceptance": acceptance,
        "blockers": _blockers(acceptance),
        "operator_next_step": _next_step(status, action="scope-preview"),
    }


def _dry_run_payload(target_date: date, scope: ProcessingScope, response: Any) -> dict[str, Any]:
    response_payload = response.model_dump(mode="json") if hasattr(response, "model_dump") else dict(response)
    counts = dict(response_payload.get("planned") or {})
    costs = dict(response_payload.get("costs") or {})
    forecast = _forecast_summary(counts, costs)
    acceptance = _acceptance(scope, forecast=forecast, counts=counts)
    status = _status_from_acceptance(acceptance, forecast=forecast)
    return {
        "action": "dry-run",
        "status": status,
        "date": target_date.isoformat(),
        "scope": _scope_summary(scope),
        "forecast": forecast,
        "run": {
            "run_id": response_payload.get("run_id"),
            "status": response_payload.get("status"),
            "scope_hash": response_payload.get("scope_hash"),
            "requested_by": response_payload.get("requested_by"),
            "mode": EnsureMode.DRY_RUN.value,
            "required_artifacts": _required_artifact_values(),
        },
        "counts": counts,
        "costs": costs,
        "quota": response_payload.get("quota") or {},
        "acceptance": acceptance,
        "blockers": _blockers(acceptance, forecast=forecast, counts=counts),
        "operator_next_step": _next_step(status, action="dry-run"),
    }


def _run_summary(run: Any, *, scope_match: str, requested_scope_hash: str) -> dict[str, Any]:
    counts = dict(getattr(run, "counts_json", None) or {})
    costs = _run_costs_from_counts(counts)
    scope_hash = str(getattr(run, "scope_hash", "") or "")
    return {
        "run_id": str(getattr(run, "id", "") or ""),
        "status": str(getattr(run, "status", "") or ""),
        "scope_hash": scope_hash,
        "scope_match": scope_match,
        "requested_scope_hash": requested_scope_hash,
        "covering_scope_hash": scope_hash if scope_match == "covering" else None,
        "requested_by": getattr(run, "requested_by", None),
        "mode": getattr(run, "mode", None),
        "required_artifacts": list(getattr(run, "required_artifacts", None) or []),
        "counts": counts,
        "costs": costs,
        "errors": list(getattr(run, "errors_json", None) or []),
        "started_at": getattr(run, "started_at", None),
        "finished_at": getattr(run, "finished_at", None),
        "heartbeat_at": getattr(run, "heartbeat_at", None),
        "created_at": getattr(run, "created_at", None),
        "updated_at": getattr(run, "updated_at", None),
    }


def _latest_run_payload(target_date: date, scope: ProcessingScope, run: Any | None, *, scope_match: str | None) -> dict[str, Any]:
    requested_hash = stable_scope_hash(scope)
    if run is None:
        acceptance = _acceptance(scope, ready_run=False)
        status = _status_from_acceptance(acceptance, run_status="missing")
        return {
            "action": "latest-run-check",
            "status": status,
            "date": target_date.isoformat(),
            "scope": _scope_summary(scope),
            "forecast": None,
            "run": None,
            "counts": {},
            "costs": {},
            "blockers": _blockers(acceptance),
            "acceptance": acceptance,
            "operator_next_step": _next_step(status, action="latest-run-check"),
        }

    run_payload = _run_summary(run, scope_match=scope_match or "exact", requested_scope_hash=requested_hash)
    counts = dict(run_payload["counts"])
    costs = dict(run_payload["costs"])
    forecast = _forecast_summary(counts, costs)
    ready_run = (
        str(run_payload.get("status") or "") in READY_RUN_STATUSES
        and int(counts.get("artifacts_missing") or 0) <= 0
    )
    acceptance = _acceptance(
        scope,
        forecast=forecast,
        counts=counts,
        ready_run=ready_run,
        enforce_no_provider_dry_run=False,
    )
    status = _status_from_acceptance(
        acceptance,
        forecast=forecast,
        run_status=str(run_payload.get("status") or ""),
    )
    return {
        "action": "latest-run-check",
        "status": status,
        "date": target_date.isoformat(),
        "scope": _scope_summary(scope),
        "forecast": forecast,
        "run": run_payload,
        "counts": counts,
        "costs": costs,
        "blockers": _blockers(acceptance, forecast=forecast, counts=counts, run=run_payload),
        "acceptance": acceptance,
        "operator_next_step": _next_step(status, action="latest-run-check"),
    }


def _next_step(status: str, *, action: str) -> str:
    if action == "scope-preview":
        if status == "ok":
            return "Run dry-run for this date and 2-3 representative working days; compare forecast volume and budget before approving a provider-backed trial."
        return "Fix scheduled upstream scope settings so runtime scope is company-wide with extensions and fallback department, then rerun scope-preview."
    if action == "dry-run":
        if status == "ok":
            return "After operator approval only, run one provider-backed company upstream trial; do not enable permanent schedule yet."
        if status == "warning":
            return "Review forecast warnings and budget notes before approving any provider-backed trial."
        return "Do not run provider-backed company upstream; resolve blockers and rerun dry-run."
    if status == "ok":
        return "Verify EDO reports through covering lookup and confirm no LLM2/LLM3/report generation outside selected downstream scope before permanent schedule changes."
    return "Do not continue rollout; inspect latest run blockers and rerun upstream only after operator approval."


def scope_preview(args: argparse.Namespace) -> dict[str, Any]:
    target_date = _target_date(args.date)
    with get_db() as db:
        scope = _runtime_scope(target_date, db)
    return _scope_preview_payload(target_date, scope)


def dry_run(args: argparse.Namespace) -> dict[str, Any]:
    target_date = _target_date(args.date)
    with get_db() as db:
        scope = _runtime_scope(target_date, db)
        response = CallProcessingService(
            db,
            requested_by="company_transcription_rollout_preflight",
        ).ensure(
            scope,
            list(REQUIRED_ARTIFACTS),
            mode=EnsureMode.DRY_RUN,
            requested_by="company_transcription_rollout_preflight",
            provider_call_budget=settings.call_processing_daily_upstream_provider_call_budget,
        )
    return _dry_run_payload(target_date, scope, response)


def latest_run_check(args: argparse.Namespace) -> dict[str, Any]:
    target_date = _target_date(args.date)
    with get_db() as db:
        scope = _runtime_scope(target_date, db)
        repo = ProcessingRunRepository(db)
        required = list(REQUIRED_ARTIFACTS)
        run = repo.latest_for_scope(scope=scope, required_artifacts=required)
        scope_match = "exact" if run is not None else None
        if run is None:
            run = repo.latest_covering_for_scope(scope=scope, required_artifacts=required)
            scope_match = "covering" if run is not None else None
    return _latest_run_payload(target_date, scope, run, scope_match=scope_match)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("scope-preview", "dry-run", "latest-run-check"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--date", required=True, help="Rollout target date in YYYY-MM-DD.")
        subparser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "scope-preview":
            payload = scope_preview(args)
        elif args.command == "dry-run":
            payload = dry_run(args)
        elif args.command == "latest-run-check":
            payload = latest_run_check(args)
        else:  # pragma: no cover - argparse enforces this
            raise ValueError(f"unknown command: {args.command}")
    except Exception as exc:  # noqa: BLE001 - operator CLI must return visible JSON failure.
        payload = {
            "status": "blocked",
            "error": {"class": exc.__class__.__name__, "message": str(exc)},
            "operator_next_step": "Fix the preflight error, then rerun the command before any provider-backed rollout.",
        }
        print(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    _print_payload(payload, as_json=bool(args.json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
