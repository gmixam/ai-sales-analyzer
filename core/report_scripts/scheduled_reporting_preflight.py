#!/usr/bin/env python3
"""Inspect and operate scheduled reviewable reporting without the operator UI."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.agents.calls.scheduled_reporting import ScheduledReviewableReportingService
from app.core_shared.db.session import get_db
from app.core_shared.exceptions import ASAError


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


def create_schedule(args: argparse.Namespace) -> dict[str, Any]:
    with get_db() as db:
        service = ScheduledReviewableReportingService(db=db)
        schedule = service.create_schedule(
            department_id=args.department_id,
            manager_ids=args.manager_id or [],
            preset=args.preset,
            enabled=args.enabled,
            start_date=args.start_date,
            start_time=args.start_time,
            timezone_name=args.timezone,
            recurrence_type=args.recurrence,
            report_period_rule=args.period_rule,
            mode=args.mode,
            business_email_enabled=args.business_email_enabled,
        )
        return {"status": "ok", "action": "create_schedule", "schedule": schedule}


def approve_batch(args: argparse.Namespace) -> dict[str, Any]:
    with get_db() as db:
        service = ScheduledReviewableReportingService(db=db)
        batch = service.approve_batch(batch_id=args.batch_id, editor=args.editor)
        return {"status": "ok", "action": "approve_batch", "batch": batch}


def main() -> int:
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

    approve = subparsers.add_parser("approve", help="Approve one review batch and run delivery.")
    approve.add_argument("--batch-id", required=True)
    approve.add_argument("--editor", default="codex_cli")

    args = parser.parse_args()
    try:
        if args.command == "status":
            result = status()
        elif args.command == "scan-due":
            result = scan_due()
        elif args.command == "create":
            result = create_schedule(args)
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
