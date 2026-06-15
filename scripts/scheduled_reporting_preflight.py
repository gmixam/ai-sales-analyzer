#!/usr/bin/env python3
"""Inspect and operate scheduled reviewable reporting without the operator UI."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.agents.calls.scheduled_reporting import ScheduledReviewableReportingService
from app.core_shared.db.session import get_db
from app.core_shared.exceptions import ASAError


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
        "review_required": True,
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
            allow_conflicts=args.allow_conflicts,
            dry_run=args.dry_run,
        )
        result["production_smoke"] = {
            "first_report_date": first_report_date.isoformat(),
            "derived_schedule_start_date": start_date,
            "manager_count": len(manager_ids),
            "review_gate": True,
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
    prod_create.add_argument("--start-time", default="08:00")
    prod_create.add_argument("--timezone", default="Asia/Almaty")
    prod_create.add_argument("--mode", default="build_missing_and_report")
    prod_create.add_argument("--expected-manager-count", type=int, default=4)
    prod_create.add_argument("--enabled", action=argparse.BooleanOptionalAction, default=True)
    prod_create.add_argument("--business-email-enabled", action=argparse.BooleanOptionalAction, default=False)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
