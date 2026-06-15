#!/usr/bin/env python3
"""Run Bitrix manager directory sync and print a pilot preflight summary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.agents.calls.bitrix_readonly import BitrixManagerMapper, BitrixReadOnlyError
from app.core_shared.db.models import Department, Manager
from app.core_shared.db.session import get_db

TECHNICAL_MANAGER_NAMES = {"Робот Договор24"}
TECHNICAL_MANAGER_BITRIX_IDS = {"102"}


def _manager_row(manager: Manager) -> dict[str, Any]:
    return {
        "id": str(manager.id),
        "name": manager.name,
        "email": manager.email,
        "extension": manager.extension,
        "bitrix_id": manager.bitrix_id,
        "active": bool(manager.active),
    }


def _select_department(
    *,
    departments: list[Department],
    department_id: str | None,
    department_name: str | None,
) -> Department:
    if department_id:
        target = UUID(department_id)
        for department in departments:
            if department.id == target:
                return department
        raise RuntimeError(f"Department id not found: {department_id}")

    if department_name:
        normalized = department_name.strip().lower()
        matches = [item for item in departments if item.name.strip().lower() == normalized]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise RuntimeError(f"Department name not found: {department_name}")
        raise RuntimeError(f"Department name is ambiguous: {department_name}")

    if len(departments) == 1:
        return departments[0]

    available = [
        {"id": str(item.id), "name": item.name, "bitrix_department_id": (item.settings or {}).get("bitrix_department_id")}
        for item in departments
    ]
    raise RuntimeError(
        "Department is required when multiple departments exist. "
        + json.dumps(available, ensure_ascii=False)
    )


def _print_text(result: dict[str, Any]) -> None:
    department = result["department"]
    summary = result["sync_summary"]
    print("Bitrix manager sync preflight")
    print(f"Department: {department['name']} ({department['id']})")
    print(f"Bitrix department id: {department.get('bitrix_department_id') or '-'}")
    print(f"Config: {result['bitrix_config']}")
    print(
        "Summary: "
        f"synced={summary.get('synced_total', 0)}, "
        f"deactivated={summary.get('deactivated_total', 0)}, "
        f"active={result['counts']['active']}, "
        f"inactive={result['counts']['inactive']}, "
        f"missing_email={result['counts']['missing_email']}, "
        f"missing_extension={result['counts']['missing_extension']}"
    )
    if result["warnings"]:
        print("Warnings:")
        for warning in result["warnings"]:
            print(f"- {warning}")
    if result["schedule_scope_candidates"]:
        print("Schedule scope candidates:")
        for manager in result["schedule_scope_candidates"]:
            print(
                f"- {manager['name']} | "
                f"email={manager.get('email') or '-'} | "
                f"ext={manager.get('extension') or '-'} | "
                f"bitrix_id={manager.get('bitrix_id') or '-'}"
            )
    print("Managers:")
    for manager in result["managers"]:
        active = "active" if manager["active"] else "inactive"
        print(
            f"- {active} | {manager['name']} | "
            f"email={manager.get('email') or '-'} | "
            f"ext={manager.get('extension') or '-'} | "
            f"bitrix_id={manager.get('bitrix_id') or '-'}"
        )


def run(*, department_id: str | None, department_name: str | None) -> dict[str, Any]:
    with get_db() as db:
        departments = db.query(Department).order_by(Department.name.asc()).all()
        if not departments:
            raise RuntimeError("No departments found in local DB.")
        department = _select_department(
            departments=departments,
            department_id=department_id,
            department_name=department_name,
        )
        mapper = BitrixManagerMapper(db=db)
        before = {
            str(item.id): _manager_row(item)
            for item in db.query(Manager).filter(Manager.department_id == department.id).all()
        }
        summary = mapper.sync_department_directory(department=department)
        managers = (
            db.query(Manager)
            .filter(Manager.department_id == department.id)
            .order_by(Manager.active.desc(), Manager.name.asc())
            .all()
        )
        rows = [_manager_row(item) for item in managers]
        active_rows = [item for item in rows if item["active"]]
        missing_email = [item for item in active_rows if not item.get("email")]
        missing_extension = [item for item in active_rows if not item.get("extension")]
        technical_managers = [
            item
            for item in active_rows
            if item.get("name") in TECHNICAL_MANAGER_NAMES
            or str(item.get("bitrix_id") or "") in TECHNICAL_MANAGER_BITRIX_IDS
        ]
        schedule_scope_candidates = [
            item
            for item in active_rows
            if item.get("email")
            and item.get("extension")
            and item not in technical_managers
        ]
        added = [item for item in rows if item["id"] not in before]
        became_inactive = [
            item
            for item in rows
            if item["id"] in before and before[item["id"]].get("active") and not item["active"]
        ]
        warnings = []
        for item in missing_email:
            warnings.append(f"active_manager_missing_email:{item['name']}")
        for item in missing_extension:
            warnings.append(f"active_manager_missing_extension:{item['name']}")
        for item in technical_managers:
            warnings.append(f"active_manager_excluded_from_schedule_scope:{item['name']}")

        return {
            "status": "ok",
            "department": {
                "id": str(department.id),
                "name": department.name,
                "bitrix_department_id": (department.settings or {}).get("bitrix_department_id"),
            },
            "bitrix_config": mapper.client.safe_config_snapshot(),
            "sync_summary": summary,
            "counts": {
                "total": len(rows),
                "active": len(active_rows),
                "inactive": len(rows) - len(active_rows),
                "missing_email": len(missing_email),
                "missing_extension": len(missing_extension),
                "added": len(added),
                "became_inactive": len(became_inactive),
                "schedule_scope_candidates": len(schedule_scope_candidates),
                "technical_excluded": len(technical_managers),
            },
            "added_managers": added,
            "became_inactive_managers": became_inactive,
            "warnings": warnings,
            "schedule_scope_candidates": schedule_scope_candidates,
            "managers": rows,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--department-id", default=None)
    parser.add_argument("--department-name", default=None)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args()

    try:
        result = run(department_id=args.department_id, department_name=args.department_name)
    except (BitrixReadOnlyError, RuntimeError, ValueError) as exc:
        payload = {"status": "failed", "error": f"{exc.__class__.__name__}: {exc}"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(payload["error"], file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
