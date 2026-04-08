"""CLI for temporary manual pilot department/manager bootstrap."""

from __future__ import annotations

import argparse
import json

from app.agents.calls.pilot_bootstrap import (
    bootstrap_result_to_dict,
    ensure_manual_pilot_entities,
)
from app.core_shared.db.session import get_db


def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for the manual pilot bootstrap."""
    parser = argparse.ArgumentParser(description="Bootstrap department and manager for manual pilot.")
    parser.add_argument("--department-name", required=True, help="Pilot department name")
    parser.add_argument("--manager-name", required=True, help="Pilot manager name")
    parser.add_argument("--manager-extension", required=True, help="Pilot manager extension")
    parser.add_argument("--manager-email", help="Optional pilot manager email")
    parser.add_argument("--manager-telegram-id", help="Optional pilot manager Telegram id")
    return parser


def main() -> None:
    """Run bootstrap and print the created or resolved entities."""
    args = build_parser().parse_args()
    with get_db() as db:
        result = ensure_manual_pilot_entities(
            db=db,
            department_name=args.department_name,
            manager_name=args.manager_name,
            manager_extension=args.manager_extension,
            manager_email=args.manager_email,
            manager_telegram_id=args.manager_telegram_id,
        )
        payload = bootstrap_result_to_dict(result)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
