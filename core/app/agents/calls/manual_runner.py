"""CLI entrypoint for a manual live OnlinePBX -> analysis -> delivery run."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.agents.calls.orchestrator import CallsManualPilotOrchestrator
from app.agents.calls.pilot_bootstrap import (
    bootstrap_result_to_dict,
    ensure_manual_pilot_entities,
)
from app.core_shared.db.session import get_db


def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for manual pilot execution."""
    parser = argparse.ArgumentParser(description="Run one manual live call pipeline.")
    parser.add_argument("--department-id", help="Department UUID")
    parser.add_argument("--date", help="OnlinePBX date in YYYY-MM-DD")
    parser.add_argument("--interaction-id", help="Existing interaction UUID for delivery replay")
    parser.add_argument("--external-id", action="append", dest="external_ids")
    parser.add_argument("--phone", action="append", dest="phones")
    parser.add_argument("--extension", action="append", dest="extensions")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--department-name", help="Create or get a pilot department by name")
    parser.add_argument("--manager-name", help="Create or get a pilot manager by name")
    parser.add_argument("--manager-extension", help="Pilot manager extension for manual mapping")
    parser.add_argument("--manager-email", help="Optional pilot manager email")
    parser.add_argument("--manager-telegram-id", help="Optional pilot manager Telegram id")
    parser.add_argument(
        "--bootstrap-only",
        action="store_true",
        help="Only create/get pilot department and manager, then print the mapping JSON.",
    )
    parser.add_argument(
        "--no-delivery",
        action="store_true",
        help="Run up to persistence only and skip Telegram/Email notification.",
    )
    parser.add_argument(
        "--replay-delivery",
        action="store_true",
        help="Replay only the test delivery stage for an already persisted interaction/analysis.",
    )
    return parser


async def _run(args: argparse.Namespace) -> dict:
    with get_db() as db:
        bootstrap = _resolve_manual_pilot_bootstrap(args=args, db=db)
        if args.bootstrap_only:
            return {"bootstrap": bootstrap}

        orchestrator = CallsManualPilotOrchestrator(
            department_id=_resolve_department_id(args=args, bootstrap=bootstrap),
            db=db,
        )
        if args.replay_delivery:
            return orchestrator.replay_delivery(
                interaction_id=args.interaction_id,
                external_id=_resolve_single_external_id(args.external_ids),
            )

        if not args.date:
            raise SystemExit("Provide --date for a live run, or use --replay-delivery.")
        result = await orchestrator.run_live(
            date=args.date,
            external_ids=args.external_ids,
            phones=args.phones,
            extensions=args.extensions,
            limit=args.limit,
            send_notification=not args.no_delivery,
        )
        if bootstrap is not None:
            result["bootstrap"] = bootstrap
        return result


def _resolve_manual_pilot_bootstrap(args: argparse.Namespace, db) -> dict | None:
    """Create or get pilot department/manager when bootstrap args are provided."""
    wants_bootstrap = any(
        [
            args.department_name,
            args.manager_name,
            args.manager_extension,
            args.manager_email,
            args.manager_telegram_id,
            args.bootstrap_only,
        ]
    )
    if not wants_bootstrap:
        return None

    missing = [
        flag
        for flag, value in (
            ("--department-name", args.department_name),
            ("--manager-name", args.manager_name),
            ("--manager-extension", args.manager_extension),
        )
        if not value
    ]
    if missing:
        missing_flags = ", ".join(missing)
        raise SystemExit(f"Bootstrap requires: {missing_flags}")

    result = ensure_manual_pilot_entities(
        db=db,
        department_name=args.department_name,
        manager_name=args.manager_name,
        manager_extension=args.manager_extension,
        manager_email=args.manager_email,
        manager_telegram_id=args.manager_telegram_id,
    )
    return bootstrap_result_to_dict(result)


def _resolve_department_id(args: argparse.Namespace, bootstrap: dict | None) -> str:
    """Choose the department id for the manual live run."""
    if args.department_id:
        return args.department_id
    if bootstrap is not None:
        return str(bootstrap["department_id"])
    raise SystemExit("Provide --department-id or bootstrap args for the pilot department.")


def _resolve_single_external_id(external_ids: list[str] | None) -> str | None:
    """Return exactly one external id for replay mode."""
    if not external_ids:
        return None
    if len(external_ids) > 1:
        raise SystemExit("Replay mode accepts only one --external-id.")
    return external_ids[0]


def main() -> None:
    """Run the CLI and print the resulting JSON."""
    parser = build_parser()
    args = parser.parse_args()
    result = asyncio.run(_run(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
