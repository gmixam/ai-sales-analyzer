"""Temporary department/manager bootstrap helpers for manual live validation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core_shared.db.models import Department, Manager
from app.core_shared.exceptions import DatabaseError


@dataclass(slots=True)
class ManualPilotBootstrapResult:
    """Created or resolved manual pilot entities."""

    department: Department
    manager: Manager
    department_created: bool
    manager_created: bool


def ensure_manual_pilot_entities(
    *,
    db: Session,
    department_name: str,
    manager_name: str,
    manager_extension: str,
    manager_email: str | None = None,
    manager_telegram_id: str | None = None,
) -> ManualPilotBootstrapResult:
    """Create or get the minimal master data required for one manual live run."""
    department_created = False
    manager_created = False

    try:
        department = (
            db.query(Department)
            .filter(Department.name == department_name.strip())
            .first()
        )
        if department is None:
            department = Department(
                name=department_name.strip(),
                settings={"mode": "manual_pilot_bootstrap"},
            )
            db.add(department)
            db.flush()
            department_created = True

        manager = (
            db.query(Manager)
            .filter(
                Manager.department_id == department.id,
                Manager.extension == manager_extension.strip(),
            )
            .first()
        )
        if manager is None:
            manager = (
                db.query(Manager)
                .filter(
                    Manager.department_id == department.id,
                    Manager.name == manager_name.strip(),
                )
                .first()
            )

        if manager is None:
            manager = Manager(
                department_id=department.id,
                name=manager_name.strip(),
                extension=manager_extension.strip(),
                email=(manager_email or "").strip() or None,
                telegram_id=(manager_telegram_id or "").strip() or None,
                active=True,
            )
            db.add(manager)
            db.flush()
            manager_created = True
        else:
            manager.name = manager_name.strip()
            manager.extension = manager_extension.strip()
            manager.email = (manager_email or "").strip() or manager.email
            manager.telegram_id = (manager_telegram_id or "").strip() or manager.telegram_id
            manager.active = True
            db.flush()

        return ManualPilotBootstrapResult(
            department=department,
            manager=manager,
            department_created=department_created,
            manager_created=manager_created,
        )
    except Exception as exc:
        raise DatabaseError(f"Failed to bootstrap manual pilot entities: {exc}") from exc


def bootstrap_result_to_dict(result: ManualPilotBootstrapResult) -> dict[str, str | bool]:
    """Render bootstrap result as a compact JSON-serializable dict."""
    return {
        "department_id": str(result.department.id),
        "department_name": result.department.name,
        "department_created": result.department_created,
        "manager_id": str(result.manager.id),
        "manager_name": result.manager.name,
        "manager_extension": result.manager.extension or "",
        "manager_created": result.manager_created,
    }
