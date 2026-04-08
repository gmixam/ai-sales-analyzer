"""Minimal Bitrix24 read-only client and manager mapping helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
import structlog
from sqlalchemy.orm import Session

from app.core_shared.config.settings import settings
from app.core_shared.db.models import Department, Manager
from app.core_shared.exceptions import ASAError, DatabaseError, IntakeError


class BitrixReadOnlyError(ASAError):
    """Raised when Bitrix24 read-only connectivity or parsing fails."""


@dataclass(slots=True)
class BitrixDepartmentRecord:
    """Normalized Bitrix24 department/section record."""

    bitrix_department_id: str
    name: str
    parent_id: str | None = None
    head_user_id: str | None = None


@dataclass(slots=True)
class BitrixUserRecord:
    """Normalized Bitrix24 user record used for mapping."""

    bitrix_user_id: str
    full_name: str
    active: bool
    email: str | None
    extension: str | None
    phones: list[str]
    department_ids: list[str]


@dataclass(slots=True)
class BitrixMappingResult:
    """Resolved local manager/department plus diagnostic details."""

    manager: Manager | None
    department_id: UUID
    source: str
    bitrix_user_id: str | None = None
    bitrix_department_id: str | None = None
    diagnostics: list[str] | None = None


class Bitrix24ReadOnlyClient:
    """Small read-only wrapper over a Bitrix24 incoming webhook."""

    def __init__(self) -> None:
        self.webhook_url = settings.bitrix24_webhook_url.strip().rstrip("/")
        self.logger = structlog.get_logger().bind(module="calls.bitrix24")

    def assert_configured(self) -> None:
        """Fail fast when Bitrix24 read-only mode is not usable."""
        if not settings.has_bitrix24_readonly:
            raise BitrixReadOnlyError(
                "Bitrix24 read-only mapping is not configured. "
                f"config={self.safe_config_snapshot()}"
            )

    def ping(self) -> dict[str, Any]:
        """Run a cheap read-only request to validate connectivity."""
        users = self.list_users(limit=1)
        return {
            "webhook": self.safe_webhook_url(),
            "configured": settings.has_bitrix24_readonly,
            "users_sampled": len(users),
        }

    def list_users(self, *, limit: int | None = None) -> list[BitrixUserRecord]:
        """Fetch active Bitrix24 users for mapping."""
        self.assert_configured()
        payload = self._request("user.get", params={"FILTER[ACTIVE]": "Y"})
        raw_users = payload.get("result") or []
        if not isinstance(raw_users, list):
            raise BitrixReadOnlyError(
                "Bitrix24 user.get returned an unsupported payload. "
                f"webhook={self.safe_webhook_url()}"
            )

        users = [self._normalize_user(item) for item in raw_users]
        if limit is not None:
            return users[:limit]
        return users

    def list_departments(self) -> list[BitrixDepartmentRecord]:
        """Fetch Bitrix24 departments/sections when supported by the webhook."""
        self.assert_configured()
        payload = self._request("department.get")
        raw_departments = payload.get("result") or []
        if not isinstance(raw_departments, list):
            raise BitrixReadOnlyError(
                "Bitrix24 department.get returned an unsupported payload. "
                f"webhook={self.safe_webhook_url()}"
            )
        return [self._normalize_department(item) for item in raw_departments]

    def get_user_by_id(self, user_id: str) -> BitrixUserRecord | None:
        """Fetch one Bitrix user by id when available."""
        self.assert_configured()
        normalized_user_id = str(user_id).strip()
        if not normalized_user_id:
            return None
        payload = self._request("user.get", params={"FILTER[ID]": normalized_user_id})
        raw_users = payload.get("result") or []
        if not isinstance(raw_users, list):
            raise BitrixReadOnlyError(
                "Bitrix24 user.get returned an unsupported payload. "
                f"webhook={self.safe_webhook_url()}"
            )
        if not raw_users:
            return None
        return self._normalize_user(raw_users[0])

    def safe_webhook_url(self) -> str:
        """Return a masked webhook URL for diagnostics."""
        if not self.webhook_url:
            return ""
        parsed = urlparse(self.webhook_url)
        host = parsed.netloc
        path_parts = [part for part in parsed.path.split("/") if part]
        masked_tail = "***"
        if len(path_parts) >= 2:
            masked_tail = f"{path_parts[0]}/***/"
        return f"{parsed.scheme}://{host}/{masked_tail}"

    def safe_config_snapshot(self) -> str:
        """Return a compact masked snapshot of the Bitrix24 settings."""
        return (
            f"enabled={settings.bitrix24_readonly_enabled} "
            f"configured={settings.has_bitrix24_readonly} "
            f"webhook={self.safe_webhook_url()} "
            f"target_departments={settings.bitrix24_target_department_ids}"
        )

    def _request(self, method: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a Bitrix24 webhook call with masked diagnostics."""
        url = f"{self.webhook_url}/{method}.json"
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(url, params=params or {})
        except httpx.RequestError as exc:
            raise BitrixReadOnlyError(
                f"Bitrix24 {method} request failed: {exc}. webhook={self.safe_webhook_url()}"
            ) from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            preview = response.text[:300].replace("\n", " ")
            raise BitrixReadOnlyError(
                f"Bitrix24 {method} returned HTTP {response.status_code}. "
                f"webhook={self.safe_webhook_url()} body_preview={preview}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            preview = response.text[:300].replace("\n", " ")
            raise BitrixReadOnlyError(
                f"Bitrix24 {method} returned invalid JSON. "
                f"webhook={self.safe_webhook_url()} body_preview={preview}"
            ) from exc

        if "error" in payload:
            raise BitrixReadOnlyError(
                f"Bitrix24 {method} returned API error "
                f"{payload.get('error')}: {payload.get('error_description')}. "
                f"webhook={self.safe_webhook_url()}"
            )
        return payload

    def _normalize_user(self, raw: dict[str, Any]) -> BitrixUserRecord:
        """Convert a raw Bitrix user into the local normalized form."""
        extension = self._extract_extension(raw)
        department_ids = self._normalize_to_list(raw.get("UF_DEPARTMENT"))
        phones = []
        for key in ("PERSONAL_MOBILE", "PERSONAL_PHONE", "WORK_PHONE", "UF_PHONE_INNER"):
            value = raw.get(key)
            if value:
                phones.extend(self._normalize_to_list(value))
        normalized_phones = []
        for phone in phones:
            cleaned = self._normalize_phone(phone)
            if cleaned and cleaned not in normalized_phones:
                normalized_phones.append(cleaned)

        name_parts = [str(raw.get("NAME") or "").strip(), str(raw.get("LAST_NAME") or "").strip()]
        full_name = " ".join(part for part in name_parts if part).strip() or str(raw.get("ID"))
        return BitrixUserRecord(
            bitrix_user_id=str(raw.get("ID") or ""),
            full_name=full_name,
            active=self._normalize_active(raw.get("ACTIVE", "Y")),
            email=(str(raw.get("EMAIL") or "").strip() or None),
            extension=extension,
            phones=normalized_phones,
            department_ids=[str(item) for item in department_ids if str(item).strip()],
        )

    @staticmethod
    def _normalize_department(raw: dict[str, Any]) -> BitrixDepartmentRecord:
        """Convert a raw Bitrix department into the local normalized form."""
        return BitrixDepartmentRecord(
            bitrix_department_id=str(raw.get("ID") or ""),
            name=str(raw.get("NAME") or "").strip() or str(raw.get("ID")),
            parent_id=(str(raw.get("PARENT") or "").strip() or None),
            head_user_id=(str(raw.get("UF_HEAD") or "").strip() or None),
        )

    @staticmethod
    def _normalize_to_list(value: Any) -> list[str]:
        """Normalize Bitrix scalar/list fields to a list of strings."""
        if value in (None, "", []):
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, tuple):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value).strip()
        if "," in text:
            return [item.strip() for item in text.split(",") if item.strip()]
        return [text]

    @staticmethod
    def _normalize_phone(value: str | None) -> str | None:
        """Normalize a phone or extension-like string to digits/+digits."""
        if value is None:
            return None
        stripped = str(value).strip()
        if stripped == "":
            return None
        plus = stripped.startswith("+")
        digits = "".join(char for char in stripped if char.isdigit())
        if digits == "":
            return None
        return f"+{digits}" if plus else digits

    @classmethod
    def _extract_extension(cls, raw: dict[str, Any]) -> str | None:
        """Extract one deterministic inner extension from a Bitrix user record."""
        candidates = cls._normalize_to_list(raw.get("UF_PHONE_INNER"))
        for candidate in candidates:
            digits = cls._normalize_phone(candidate)
            if digits:
                return digits.lstrip("+")
        return None

    @staticmethod
    def _normalize_active(value: Any) -> bool:
        """Normalize Bitrix active flag from bool or string payloads."""
        if isinstance(value, bool):
            return value
        return str(value).strip().upper() in {"Y", "1", "TRUE"}


class BitrixManagerMapper:
    """Resolve and mirror managers/departments from Bitrix24 in read-only mode."""

    def __init__(self, *, db: Session):
        self.db = db
        self.client = Bitrix24ReadOnlyClient()
        self.logger = structlog.get_logger().bind(module="calls.bitrix_mapper")
        self._users: list[BitrixUserRecord] | None = None
        self._departments_by_id: dict[str, BitrixDepartmentRecord] | None = None

    def resolve_for_call(
        self,
        *,
        fallback_department_id: UUID,
        extension: str | None,
        phone: str | None,
    ) -> BitrixMappingResult | None:
        """Resolve a call to a local manager/department through Bitrix read-only data."""
        if not settings.has_bitrix24_readonly:
            return None

        diagnostics: list[str] = []
        try:
            users = self._load_users()
        except BitrixReadOnlyError as exc:
            diagnostics.append(str(exc))
            return BitrixMappingResult(
                manager=None,
                department_id=fallback_department_id,
                source="manual_fallback",
                diagnostics=diagnostics,
            )

        normalized_extension = Bitrix24ReadOnlyClient._normalize_phone(extension)
        normalized_phone = Bitrix24ReadOnlyClient._normalize_phone(phone)

        if normalized_extension:
            by_extension = [
                user
                for user in users
                if user.active and user.extension == normalized_extension.lstrip("+")
            ]
            if len(by_extension) == 1:
                return self._upsert_match(
                    user=by_extension[0],
                    fallback_department_id=fallback_department_id,
                    source="bitrix_extension",
                    diagnostics=diagnostics,
                )
            if len(by_extension) > 1:
                diagnostics.append(
                    f"ambiguous_bitrix_extension_match:{normalized_extension.lstrip('+')}"
                )

        if normalized_phone:
            by_phone = [
                user for user in users if user.active and normalized_phone in user.phones
            ]
            if len(by_phone) == 1:
                return self._upsert_match(
                    user=by_phone[0],
                    fallback_department_id=fallback_department_id,
                    source="bitrix_phone",
                    diagnostics=diagnostics,
                )
            if len(by_phone) > 1:
                diagnostics.append(f"ambiguous_bitrix_phone_match:{normalized_phone}")

        if diagnostics:
            return BitrixMappingResult(
                manager=None,
                department_id=fallback_department_id,
                source="manual_fallback",
                diagnostics=diagnostics,
            )
        return None

    def probe(self, *, extension: str | None = None, phone: str | None = None) -> dict[str, Any]:
        """Return a compact probe payload for manual verification."""
        users = self._load_users()
        departments = self._load_departments_map(raise_on_error=False)
        fallback_department = self.db.query(Department).order_by(Department.created_at.asc()).first()
        resolution = self.resolve_for_call(
            fallback_department_id=fallback_department.id if fallback_department is not None else UUID(int=0),
            extension=extension,
            phone=phone,
        )
        return {
            "config": self.client.safe_config_snapshot(),
            "users_total": len(users),
            "departments_total": len(departments),
            "resolution": {
                "source": resolution.source if resolution else None,
                "manager_id": str(resolution.manager.id) if resolution and resolution.manager else None,
                "department_id": str(resolution.department_id) if resolution else None,
                "bitrix_user_id": resolution.bitrix_user_id if resolution else None,
                "bitrix_department_id": resolution.bitrix_department_id if resolution else None,
                "diagnostics": resolution.diagnostics if resolution else [],
            },
        }

    def sync_department_directory(self, *, department: Department) -> dict[str, Any]:
        """Refresh one local department manager directory from Bitrix."""
        bitrix_department_id = str((department.settings or {}).get("bitrix_department_id") or "").strip()
        if not bitrix_department_id:
            raise BitrixReadOnlyError(
                f"Department '{department.name}' has no settings.bitrix_department_id for Bitrix sync."
            )

        users = self._load_users()
        synced: list[Manager] = []
        synced_bitrix_ids: set[str] = set()

        for user in users:
            if bitrix_department_id not in user.department_ids:
                continue
            manager = self._upsert_user_into_department(
                user=user,
                local_department=department,
            )
            synced.append(manager)
            if user.bitrix_user_id:
                synced_bitrix_ids.add(user.bitrix_user_id)

        deactivated_total = 0
        mirrored_managers = (
            self.db.query(Manager)
            .filter(
                Manager.department_id == department.id,
                Manager.bitrix_id.isnot(None),
            )
            .all()
        )
        for manager in mirrored_managers:
            if manager.bitrix_id and manager.bitrix_id not in synced_bitrix_ids and manager.active:
                manager.active = False
                deactivated_total += 1

        self.db.flush()
        return {
            "department_id": str(department.id),
            "department_name": department.name,
            "bitrix_department_id": bitrix_department_id,
            "synced_total": len(synced),
            "deactivated_total": deactivated_total,
        }

    def _load_users(self) -> list[BitrixUserRecord]:
        """Load and cache active Bitrix users."""
        if self._users is None:
            self._users = self.client.list_users()
        return self._users

    def _load_departments_map(self, *, raise_on_error: bool = True) -> dict[str, BitrixDepartmentRecord]:
        """Load and cache Bitrix departments by id."""
        if self._departments_by_id is not None:
            return self._departments_by_id
        try:
            departments = self.client.list_departments()
        except BitrixReadOnlyError:
            if raise_on_error:
                raise
            self._departments_by_id = {}
            return self._departments_by_id
        self._departments_by_id = {
            item.bitrix_department_id: item for item in departments if item.bitrix_department_id
        }
        return self._departments_by_id

    def _upsert_match(
        self,
        *,
        user: BitrixUserRecord,
        fallback_department_id: UUID,
        source: str,
        diagnostics: list[str],
    ) -> BitrixMappingResult:
        """Mirror a Bitrix match into local departments/managers."""
        local_department = self._resolve_local_department(
            user=user,
            fallback_department_id=fallback_department_id,
        )
        manager = self._upsert_user_into_department(
            user=user,
            local_department=local_department,
        )

        bitrix_department_id = self._pick_bitrix_department_id(user)
        return BitrixMappingResult(
            manager=manager,
            department_id=local_department.id,
            source=source,
            bitrix_user_id=user.bitrix_user_id,
            bitrix_department_id=bitrix_department_id,
            diagnostics=diagnostics,
        )

    def _upsert_user_into_department(
        self,
        *,
        user: BitrixUserRecord,
        local_department: Department,
    ) -> Manager:
        """Mirror one Bitrix user into a chosen local department."""
        try:
            manager = (
                self.db.query(Manager)
                .filter(
                    Manager.department_id == local_department.id,
                    Manager.bitrix_id == user.bitrix_user_id,
                )
                .first()
            )
            if manager is None and user.extension:
                manager = (
                    self.db.query(Manager)
                    .filter(
                        Manager.department_id == local_department.id,
                        Manager.extension == user.extension,
                    )
                    .first()
                )
            if manager is None and user.email:
                manager = (
                    self.db.query(Manager)
                    .filter(
                        Manager.department_id == local_department.id,
                        Manager.email == user.email,
                    )
                    .first()
                )

            if manager is None:
                manager = Manager(
                    department_id=local_department.id,
                    name=user.full_name,
                    extension=user.extension,
                    bitrix_id=user.bitrix_user_id,
                    email=user.email,
                    active=user.active,
                )
                self.db.add(manager)
                self.db.flush()
            else:
                manager.name = user.full_name
                manager.extension = user.extension or manager.extension
                manager.bitrix_id = user.bitrix_user_id
                manager.email = user.email or manager.email
                manager.active = user.active
                self.db.flush()
        except Exception as exc:
            raise DatabaseError(f"Failed to mirror Bitrix24 manager locally: {exc}") from exc
        return manager

    def _resolve_local_department(
        self,
        *,
        user: BitrixUserRecord,
        fallback_department_id: UUID,
    ) -> Department:
        """Resolve or create a local department mirror for the matched Bitrix user."""
        bitrix_department_id = self._pick_bitrix_department_id(user)
        if not bitrix_department_id:
            department = self.db.query(Department).filter(Department.id == fallback_department_id).first()
            if department is None:
                raise DatabaseError(
                    f"Fallback department {fallback_department_id} was not found for Bitrix mapping."
                )
            return department

        try:
            department = (
                self.db.query(Department)
                .filter(Department.settings["bitrix_department_id"].astext == bitrix_department_id)
                .first()
            )
        except Exception:
            department = None

        departments_by_id = self._load_departments_map(raise_on_error=False)
        bitrix_department = departments_by_id.get(bitrix_department_id)
        department_name = (
            bitrix_department.name
            if bitrix_department is not None
            else f"Bitrix Department {bitrix_department_id}"
        )

        if department is None:
            department = (
                self.db.query(Department)
                .filter(Department.name == department_name)
                .first()
            )

        try:
            if department is None:
                department = Department(
                    name=department_name,
                    settings={
                        "mode": "bitrix24_readonly",
                        "bitrix_department_id": bitrix_department_id,
                    },
                )
                self.db.add(department)
                self.db.flush()
            else:
                merged_settings = dict(department.settings or {})
                merged_settings.update(
                    {
                        "mode": merged_settings.get("mode") or "bitrix24_readonly",
                        "bitrix_department_id": bitrix_department_id,
                    }
                )
                department.settings = merged_settings
                self.db.flush()
        except Exception as exc:
            raise DatabaseError(f"Failed to mirror Bitrix24 department locally: {exc}") from exc
        return department

    @staticmethod
    def _pick_bitrix_department_id(user: BitrixUserRecord) -> str | None:
        """Pick one deterministic Bitrix department id from the user record."""
        if not user.department_ids:
            return None
        target_ids = set(settings.bitrix24_target_department_ids)
        if target_ids:
            for department_id in user.department_ids:
                if department_id in target_ids:
                    return department_id
        return user.department_ids[0]
