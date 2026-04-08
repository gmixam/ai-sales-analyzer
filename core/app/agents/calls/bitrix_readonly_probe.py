"""Diagnostic CLI for Bitrix24 read-only connectivity and mapping."""

from __future__ import annotations

import argparse
import json

from app.agents.calls.bitrix_readonly import (
    Bitrix24ReadOnlyClient,
    BitrixManagerMapper,
    BitrixReadOnlyError,
)
from app.core_shared.db.session import get_db


def build_parser() -> argparse.ArgumentParser:
    """Build a small CLI for manual Bitrix24 read-only checks."""
    parser = argparse.ArgumentParser(description="Probe Bitrix24 read-only mapping.")
    parser.add_argument("--extension", help="Manager extension to test")
    parser.add_argument("--phone", help="Manager/customer phone to test")
    parser.add_argument("--limit-users", type=int, default=3, help="Number of users to sample")
    return parser


def main() -> None:
    """Run the connectivity and mapping probe."""
    args = build_parser().parse_args()
    client = Bitrix24ReadOnlyClient()
    try:
        with get_db() as db:
            mapper = BitrixManagerMapper(db=db)
            payload = {
                "config": client.safe_config_snapshot(),
                "ping": client.ping(),
                "users_sample": [
                    {
                        "bitrix_user_id": user.bitrix_user_id,
                        "full_name": user.full_name,
                        "extension": user.extension,
                        "department_ids": user.department_ids,
                        "phones": user.phones[:2],
                    }
                    for user in client.list_users(limit=args.limit_users)
                ],
                "departments_sample": [
                    {
                        "bitrix_department_id": department.bitrix_department_id,
                        "name": department.name,
                        "parent_id": department.parent_id,
                    }
                    for department in client.list_departments()[: args.limit_users]
                ],
                "mapping_probe": mapper.probe(extension=args.extension, phone=args.phone),
            }
    except BitrixReadOnlyError as exc:
        payload = {
            "config": client.safe_config_snapshot(),
            "error": str(exc),
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
