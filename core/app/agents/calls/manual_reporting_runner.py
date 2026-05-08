"""CLI entrypoint for bounded Manual Reporting Pilot runs."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.agents.calls.reporting import (
    REPORT_DELIVERY_MODES,
    CallsManualReportingOrchestrator,
    ReportRunFilters,
)
from app.core_shared.db.session import get_db


def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for manual reporting pilot execution."""
    parser = argparse.ArgumentParser(description="Run one bounded manual reporting job.")
    parser.add_argument("--department-id", required=True, help="Department UUID")
    parser.add_argument(
        "--preset",
        required=True,
        choices=("manager_daily", "rop_weekly"),
        help="Report preset",
    )
    parser.add_argument(
        "--mode",
        default="build_missing_and_report",
        choices=("build_missing_and_report", "report_from_ready_data_only"),
        help="Reporting execution mode",
    )
    parser.add_argument("--date-from", required=True, help="Start date in YYYY-MM-DD")
    parser.add_argument("--date-to", help="End date in YYYY-MM-DD")
    parser.add_argument("--manager-id", action="append", dest="manager_ids")
    parser.add_argument("--manager-extension", action="append", dest="manager_extensions")
    parser.add_argument("--min-duration-sec", type=int, default=None)
    parser.add_argument("--max-duration-sec", type=int, default=None)
    parser.add_argument(
        "--force-retry-quota-blocked",
        action="store_true",
        help="Explicitly retry calls previously marked quota_insufficient.",
    )
    parser.add_argument(
        "--include-controlled-samples",
        action="store_true",
        help="Opt in to using analyses marked controlled_sample or verification.",
    )
    parser.add_argument("--model", help="Optional report-composer model selection placeholder")
    parser.add_argument(
        "--no-delivery",
        action="store_true",
        help="Build/render artifacts without Telegram or business email delivery.",
    )
    parser.add_argument(
        "--delivery-mode",
        choices=tuple(sorted(REPORT_DELIVERY_MODES)),
        help="Explicit delivery mode. Defaults to preview_only unless a legacy channel flag is set.",
    )
    parser.add_argument(
        "--telegram-test-delivery",
        action="store_true",
        help="Explicitly send rendered artifacts to the configured operator Telegram test chat.",
    )
    parser.add_argument(
        "--send-business-email",
        action="store_true",
        help="Explicitly send rendered artifacts to resolved business email recipients.",
    )
    return parser


async def _run(args: argparse.Namespace) -> dict:
    with get_db() as db:
        orchestrator = CallsManualReportingOrchestrator(
            department_id=args.department_id,
            db=db,
        )
        filters = ReportRunFilters(
            manager_ids=set(args.manager_ids or []),
            manager_extensions=set(args.manager_extensions or []),
            date_from=args.date_from,
            date_to=args.date_to or args.date_from,
            min_duration_sec=args.min_duration_sec,
            max_duration_sec=args.max_duration_sec,
            force_retry_quota_blocked=args.force_retry_quota_blocked,
            include_controlled_samples=args.include_controlled_samples,
        )
        delivery_mode = "preview_only" if args.no_delivery else args.delivery_mode
        return await orchestrator.run_report(
            preset_code=args.preset,
            mode=args.mode,
            filters=filters,
            model_override=args.model,
            send_email=args.send_business_email,
            delivery_mode=delivery_mode,
            send_telegram_test=args.telegram_test_delivery,
        )


def main() -> None:
    """Run the CLI and print JSON result."""
    parser = build_parser()
    args = parser.parse_args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
