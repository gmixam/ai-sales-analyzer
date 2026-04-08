"""OnlinePBX intake for fetching eligible calls and persisting interactions."""

from __future__ import annotations

from datetime import UTC, date as dt_date, datetime, time, timedelta
from urllib.parse import quote, urlparse
from uuid import UUID

import httpx
import structlog
from sqlalchemy.orm import Session

from app.agents.calls.bitrix_readonly import BitrixManagerMapper
from app.agents.calls.config import calls_config
from app.agents.calls.schemas import CDRRecord, InteractionCreate
from app.core_shared.config.settings import settings
from app.core_shared.db.models import Interaction, Manager
from app.core_shared.exceptions import DatabaseError, IntakeError


class OnlinePBXIntake:
    """Fetch call records from OnlinePBX and store eligible interactions."""

    def __init__(self, department_id: str, db: Session):
        self.department_id = UUID(department_id)
        self.db = db
        self.base_url = settings.onlinepbx_base_url
        self.domain = settings.onlinepbx_domain.strip()
        self.api_key = settings.onlinepbx_api_key
        self.cdr_url = self._build_cdr_url()
        self.auth_url = self._build_auth_url()
        self.config = calls_config
        self.logger = structlog.get_logger().bind(
            module="calls.intake",
            department_id=department_id,
        )
        self.bitrix_mapper = BitrixManagerMapper(db=db)

    def get_cdr_list(self, date: str) -> list[CDRRecord]:
        """Fetch raw CDR records from OnlinePBX for a single day."""
        if self.auth_url:
            return self._get_cdr_list_http_api(date)

        url = self.cdr_url
        payload = {
            "date_from": f"{date} 00:00:00",
            "date_to": f"{date} 23:59:59",
        }
        safe_url = self._safe_url(url)

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise IntakeError(
                message=(
                    "OnlinePBX CDR URL is malformed. "
                    f"url={safe_url} config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )

        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                response = client.post(url, json=payload, headers={"Content-Type": "application/json"})
        except httpx.InvalidURL as exc:
            raise IntakeError(
                message=(
                    "OnlinePBX CDR URL is invalid. "
                    f"url={safe_url} config={self._safe_config_snapshot()} error={exc}"
                ),
                source="onlinepbx",
                original=exc,
            ) from exc
        except httpx.RequestError as exc:
            raise IntakeError(
                message=(
                    f"Failed to reach OnlinePBX CDR endpoint for {date}. "
                    f"url={safe_url} config={self._safe_config_snapshot()} error={exc}"
                ),
                source="onlinepbx",
                original=exc,
            ) from exc

        if response.is_redirect:
            raise IntakeError(
                message=(
                    "OnlinePBX CDR endpoint returned redirect instead of JSON. "
                    f"url={safe_url} redirect={response.headers.get('location')} "
                    f"status={response.status_code} config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            response_preview = response.text[:300].replace("\n", " ")
            raise IntakeError(
                message=(
                    f"OnlinePBX CDR request failed for {date}. "
                    f"url={safe_url} status={response.status_code} "
                    f"config={self._safe_config_snapshot()} body_preview={response_preview}"
                ),
                source="onlinepbx",
                original=exc,
            ) from exc

        try:
            raw_payload = response.json()
        except ValueError as exc:
            response_preview = response.text[:300].replace("\n", " ")
            raise IntakeError(
                message=(
                    f"OnlinePBX returned invalid JSON for {date}. "
                    f"url={safe_url} config={self._safe_config_snapshot()} "
                    f"body_preview={response_preview}"
                ),
                source="onlinepbx",
                original=exc,
            ) from exc

        if raw_payload in ({}, None, ""):
            raise IntakeError(
                message=(
                    f"OnlinePBX returned empty API response for {date}. "
                    f"url={safe_url} config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )

        raw_records = self._extract_records_payload(raw_payload)
        try:
            records = [CDRRecord.model_validate(item) for item in raw_records]
        except Exception as exc:
            raise IntakeError(
                message=f"Failed to parse OnlinePBX CDR payload for {date}: {exc}",
                source="onlinepbx",
                original=exc,
            ) from exc

        self.logger.info("intake.cdr_fetched", date=date, fetched=len(records))
        return records

    def get_recording_url(self, call_id: str) -> str:
        """Fetch a downloadable recording URL for one OnlinePBX call."""
        if self.auth_url is None:
            raise IntakeError(
                message=(
                    "OnlinePBX recording URL lookup is only supported for the HTTP API flow. "
                    f"cdr_url={self._safe_url(self.cdr_url)} config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )

        safe_url = self._safe_url(self.cdr_url)
        auth_header = self._get_http_api_auth_header()
        payload = {"uuid": call_id, "download": "1"}

        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                response = client.post(
                    self.cdr_url,
                    data=payload,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "x-pbx-authentication": auth_header,
                    },
                )
        except httpx.RequestError as exc:
            raise IntakeError(
                message=(
                    "Failed to fetch OnlinePBX recording URL. "
                    f"url={safe_url} call_id={call_id} config={self._safe_config_snapshot()} error={exc}"
                ),
                source="onlinepbx",
                original=exc,
            ) from exc

        raw_payload = self._parse_http_response(
            response=response,
            url=self.cdr_url,
            operation=f"recording lookup for {call_id}",
        )
        if not isinstance(raw_payload, dict):
            raise IntakeError(
                message=(
                    "OnlinePBX recording lookup returned an unsupported payload. "
                    f"url={safe_url} call_id={call_id} config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )

        if str(raw_payload.get("status")) != "1":
            raise IntakeError(
                message=(
                    "OnlinePBX recording lookup failed. "
                    f"url={safe_url} call_id={call_id} comment={raw_payload.get('comment')} "
                    f"error_code={raw_payload.get('errorCode')} is_not_auth={raw_payload.get('isNotAuth')} "
                    f"config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )

        recording_url = raw_payload.get("data")
        if not isinstance(recording_url, str) or not recording_url:
            raise IntakeError(
                message=(
                    "OnlinePBX recording lookup returned an empty download URL. "
                    f"url={safe_url} call_id={call_id} config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )
        return recording_url

    def filter_eligible(self, records: list[CDRRecord]) -> list[CDRRecord]:
        """Filter calls that are eligible for downstream analysis."""
        eligible = [
            record
            for record in records
            if record.talk_duration >= self.config.min_duration_sec
            and record.status in self.config.allowed_statuses
            and record.direction in self.config.allowed_directions
        ]

        self.logger.info(
            "intake.filtered",
            total=len(records),
            eligible=len(eligible),
        )
        return eligible

    def get_manager_by_extension(self, extension: str) -> Manager | None:
        """Find an active department manager by internal extension."""
        return (
            self.db.query(Manager)
            .filter(
                Manager.extension == extension,
                Manager.department_id == self.department_id,
                Manager.active.is_(True),
            )
            .first()
        )

    def resolve_manager_mapping(self, record: CDRRecord) -> tuple[Manager | None, UUID, dict[str, object]]:
        """Resolve the manager/department for a call via local data, Bitrix, or fallback."""
        diagnostics: list[str] = []
        manager = self.get_manager_by_extension(record.extension)
        if manager is not None:
            return (
                manager,
                manager.department_id,
                {
                    "mapping_source": "local_extension",
                    "mapping_diagnostics": diagnostics,
                },
            )

        bitrix_result = self.bitrix_mapper.resolve_for_call(
            fallback_department_id=self.department_id,
            extension=record.extension,
            phone=record.phone,
        )
        if bitrix_result is not None:
            diagnostics.extend(bitrix_result.diagnostics or [])
            metadata = {
                "mapping_source": bitrix_result.source,
                "mapping_diagnostics": diagnostics,
            }
            if bitrix_result.bitrix_user_id:
                metadata["bitrix_user_id"] = bitrix_result.bitrix_user_id
            if bitrix_result.bitrix_department_id:
                metadata["bitrix_department_id"] = bitrix_result.bitrix_department_id
            if bitrix_result.manager is not None:
                return bitrix_result.manager, bitrix_result.department_id, metadata

            metadata["mapping_source"] = "manual_fallback"
            return None, bitrix_result.department_id, metadata

        diagnostics.append("no_local_or_bitrix_match")
        return (
            None,
            self.department_id,
            {
                "mapping_source": "manual_fallback",
                "mapping_diagnostics": diagnostics,
            },
        )

    def save_interactions(self, records: list[CDRRecord]) -> tuple[int, int]:
        """Persist eligible call records as interactions."""
        created = 0
        skipped = 0

        try:
            for record in records:
                existing = (
                    self.db.query(Interaction)
                    .filter(Interaction.external_id == record.call_id)
                    .first()
                )
                manager, resolved_department_id, mapping_metadata = self.resolve_manager_mapping(record)
                metadata = {
                    "external_call_code": record.call_id,
                    "direction": record.direction,
                    "phone": record.phone,
                    "call_date": record.call_date,
                    "extension": record.extension,
                    "manager_name": manager.name if manager is not None else record.extension,
                    "contact_phone": record.phone,
                }
                metadata.update(mapping_metadata)
                if existing is not None:
                    existing.raw_ref = record.record_url or existing.raw_ref
                    existing.duration_sec = record.talk_duration or existing.duration_sec
                    existing.manager_id = existing.manager_id or (manager.id if manager is not None else None)
                    existing.department_id = manager.department_id if manager is not None else existing.department_id
                    existing.metadata_ = {**dict(existing.metadata_ or {}), **metadata}
                    skipped += 1
                    continue

                payload = InteractionCreate(
                    department_id=resolved_department_id,
                    manager_id=manager.id if manager is not None else None,
                    external_id=record.call_id,
                    raw_ref=record.record_url,
                    duration_sec=record.talk_duration,
                    metadata=metadata,
                    status="ELIGIBLE",
                )
                interaction = Interaction(
                    department_id=payload.department_id,
                    manager_id=payload.manager_id,
                    type=payload.type,
                    source=payload.source,
                    external_id=payload.external_id,
                    raw_ref=payload.raw_ref,
                    duration_sec=payload.duration_sec,
                    metadata_=payload.metadata_,
                    status=payload.status,
                )
                self.db.add(interaction)
                created += 1

            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            raise DatabaseError(f"Failed to save interactions: {exc}") from exc

        self.logger.info("intake.saved", created=created, skipped=skipped)
        return created, skipped

    async def run(self, date: str | None = None) -> dict:
        """Run intake for a specific date or for yesterday by default."""
        if date is None:
            date = (dt_date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

        self.logger.info("intake.start", date=date)
        records = self.get_cdr_list(date)
        eligible = self.filter_eligible(records)
        created, skipped = self.save_interactions(eligible)

        result = {
            "date": date,
            "total_fetched": len(records),
            "eligible": len(eligible),
            "created": created,
            "skipped": skipped,
        }
        self.logger.info("intake.done", **result)
        return result

    @staticmethod
    def _extract_records_payload(raw_payload: object) -> list[dict]:
        """Normalize possible OnlinePBX response envelopes to a plain list."""
        if isinstance(raw_payload, list):
            return raw_payload
        if isinstance(raw_payload, dict):
            for key in ("data", "result", "records", "cdr", "items"):
                value = raw_payload.get(key)
                if isinstance(value, list):
                    return value
                if isinstance(value, dict):
                    nested = value.get("items") or value.get("records")
                    if isinstance(nested, list):
                        return nested
        raise IntakeError(
            message="OnlinePBX returned an unsupported CDR response format",
            source="onlinepbx",
        )

    def _build_cdr_url(self) -> str:
        """Return the final CDR endpoint with optional explicit override."""
        if settings.onlinepbx_cdr_url:
            configured = settings.onlinepbx_cdr_url
            return self._replace_url_placeholders(configured)
        domain_host = self._extract_domain_host()
        if domain_host.endswith(".onpbx.ru") or domain_host.endswith(".onlinepbx.ru"):
            return f"https://api.onlinepbx.ru/{domain_host}/mongo_history/search.json"
        return f"{self.base_url}/{self.api_key}/cdr/get"

    def _build_auth_url(self) -> str | None:
        """Build the HTTP API auth URL when the configured CDR route requires it."""
        parsed = urlparse(self.cdr_url)
        if not parsed.scheme or not parsed.netloc:
            return None

        normalized_path = parsed.path.rstrip("/")
        for suffix in ("/mongo_history/search.json", "/history/search.json"):
            if normalized_path.endswith(suffix):
                return f"{parsed.scheme}://{parsed.netloc}{normalized_path[: -len(suffix)]}/auth.json"
        return None

    def _get_cdr_list_http_api(self, date: str) -> list[CDRRecord]:
        """Fetch CDR data through the OnlinePBX HTTP API flow."""
        safe_url = self._safe_url(self.cdr_url)
        auth_header = self._get_http_api_auth_header()
        start_dt = datetime.combine(dt_date.fromisoformat(date), time.min, tzinfo=UTC)
        end_dt = datetime.combine(dt_date.fromisoformat(date), time.max, tzinfo=UTC)
        payload = {
            "start_stamp_from": str(int(start_dt.timestamp())),
            "start_stamp_to": str(int(end_dt.timestamp())),
        }

        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                response = client.post(
                    self.cdr_url,
                    data=payload,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "x-pbx-authentication": auth_header,
                    },
                )
        except httpx.RequestError as exc:
            raise IntakeError(
                message=(
                    f"Failed to reach OnlinePBX HTTP CDR endpoint for {date}. "
                    f"url={safe_url} config={self._safe_config_snapshot()} error={exc}"
                ),
                source="onlinepbx",
                original=exc,
            ) from exc

        raw_payload = self._parse_http_response(
            response=response,
            url=self.cdr_url,
            operation=f"CDR fetch for {date}",
        )
        if not isinstance(raw_payload, dict):
            raise IntakeError(
                message=(
                    f"OnlinePBX HTTP API returned an unsupported payload for {date}. "
                    f"url={safe_url} config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )

        if str(raw_payload.get("status")) != "1":
            raise IntakeError(
                message=(
                    f"OnlinePBX HTTP API rejected CDR fetch for {date}. "
                    f"url={safe_url} comment={raw_payload.get('comment')} "
                    f"error_code={raw_payload.get('errorCode')} is_not_auth={raw_payload.get('isNotAuth')} "
                    f"config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )

        raw_records = raw_payload.get("data") or []
        if not isinstance(raw_records, list):
            raise IntakeError(
                message=(
                    f"OnlinePBX HTTP API returned a non-list CDR payload for {date}. "
                    f"url={safe_url} config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )

        try:
            records = [
                CDRRecord.model_validate(self._normalize_http_api_record(item))
                for item in raw_records
            ]
        except Exception as exc:
            raise IntakeError(
                message=f"Failed to parse OnlinePBX HTTP CDR payload for {date}: {exc}",
                source="onlinepbx",
                original=exc,
            ) from exc

        self.logger.info("intake.cdr_fetched", date=date, fetched=len(records), api_mode="http_api")
        return records

    def _get_http_api_auth_header(self) -> str:
        """Authenticate against the OnlinePBX HTTP API and return x-pbx-authentication."""
        if self.auth_url is None:
            raise IntakeError(
                message=(
                    "OnlinePBX HTTP API auth URL is not configured. "
                    f"cdr_url={self._safe_url(self.cdr_url)} config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )

        payload = {"auth_key": self.api_key}
        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                response = client.post(
                    self.auth_url,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.RequestError as exc:
            raise IntakeError(
                message=(
                    "Failed to reach OnlinePBX auth endpoint. "
                    f"url={self._safe_url(self.auth_url)} config={self._safe_config_snapshot()} error={exc}"
                ),
                source="onlinepbx",
                original=exc,
            ) from exc

        raw_payload = self._parse_http_response(
            response=response,
            url=self.auth_url,
            operation="auth",
        )
        if not isinstance(raw_payload, dict):
            raise IntakeError(
                message=(
                    "OnlinePBX auth returned an unsupported payload. "
                    f"url={self._safe_url(self.auth_url)} config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )

        data = raw_payload.get("data") or {}
        key_id = data.get("key_id")
        secret = data.get("key")
        if str(raw_payload.get("status")) != "1" or not key_id or not secret:
            raise IntakeError(
                message=(
                    "OnlinePBX auth failed. "
                    f"url={self._safe_url(self.auth_url)} comment={raw_payload.get('comment')} "
                    f"error_code={raw_payload.get('errorCode')} is_not_auth={raw_payload.get('isNotAuth')} "
                    f"config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )
        return f"{key_id}:{secret}"

    def _parse_http_response(self, *, response: httpx.Response, url: str, operation: str) -> object:
        """Parse an HTTP response with consistent masked diagnostics."""
        safe_url = self._safe_url(url)
        if response.is_redirect:
            raise IntakeError(
                message=(
                    f"OnlinePBX {operation} returned redirect instead of JSON. "
                    f"url={safe_url} redirect={response.headers.get('location')} "
                    f"status={response.status_code} config={self._safe_config_snapshot()}"
                ),
                source="onlinepbx",
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            response_preview = response.text[:300].replace("\n", " ")
            raise IntakeError(
                message=(
                    f"OnlinePBX {operation} failed. "
                    f"url={safe_url} status={response.status_code} content_type={response.headers.get('content-type')} "
                    f"config={self._safe_config_snapshot()} body_preview={response_preview}"
                ),
                source="onlinepbx",
                original=exc,
            ) from exc

        try:
            return response.json()
        except ValueError as exc:
            response_preview = response.text[:300].replace("\n", " ")
            raise IntakeError(
                message=(
                    f"OnlinePBX {operation} returned invalid JSON. "
                    f"url={safe_url} content_type={response.headers.get('content-type')} "
                    f"config={self._safe_config_snapshot()} body_preview={response_preview}"
                ),
                source="onlinepbx",
                original=exc,
            ) from exc

    def _normalize_http_api_record(self, item: dict) -> dict[str, object]:
        """Map OnlinePBX HTTP API records into the local CDR schema."""
        call_id = str(item.get("uuid") or "")
        if not call_id:
            raise IntakeError(
                message="OnlinePBX HTTP CDR payload is missing uuid",
                source="onlinepbx",
            )

        duration = int(item.get("duration") or 0)
        talk_duration = int(item.get("user_talk_time") or 0)
        direction = self._normalize_direction(item)
        phone = self._extract_phone(item, direction)
        extension = self._extract_extension(item, direction)
        start_stamp = int(item.get("start_stamp") or 0)
        if start_stamp:
            call_date = datetime.fromtimestamp(start_stamp, tz=UTC).isoformat()
        else:
            call_date = ""

        return {
            "call_id": call_id,
            "call_date": call_date,
            "duration": duration,
            "talk_duration": talk_duration,
            "direction": direction,
            "status": "answered" if talk_duration > 0 else "missed",
            "extension": extension,
            "phone": phone,
            "record_url": item.get("record_url"),
        }

    @staticmethod
    def _normalize_direction(item: dict) -> str:
        """Convert OnlinePBX accountcode values into the local direction enum."""
        accountcode = str(item.get("accountcode") or "").strip().lower()
        if accountcode in {"outbound", "out"}:
            return "out"
        if accountcode in {"inbound", "in", "missed"}:
            return "in"
        return accountcode or "unknown"

    def _extract_extension(self, item: dict, direction: str) -> str:
        """Pick the internal extension for manager mapping."""
        events = item.get("events") or []
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                number = str(event.get("number") or "").strip()
                if event.get("type") == "user" and self._looks_like_extension(number):
                    return number

        ordered_candidates = []
        if direction == "out":
            ordered_candidates.extend(
                [
                    item.get("caller_id_number"),
                    item.get("caller_id_name"),
                    item.get("destination_number"),
                ]
            )
        else:
            ordered_candidates.extend(
                [
                    item.get("destination_number"),
                    item.get("caller_id_name"),
                    item.get("caller_id_number"),
                ]
            )

        for candidate in ordered_candidates:
            value = str(candidate or "").strip()
            if self._looks_like_extension(value):
                return value
        return str(item.get("caller_id_name") or item.get("caller_id_number") or "").strip()

    def _extract_phone(self, item: dict, direction: str) -> str:
        """Pick the customer-side phone number for targeting and reporting."""
        ordered_candidates = []
        if direction == "out":
            ordered_candidates.extend(
                [
                    item.get("destination_number"),
                    item.get("gateway"),
                    item.get("caller_id_number"),
                ]
            )
        else:
            ordered_candidates.extend(
                [
                    item.get("caller_id_number"),
                    item.get("gateway"),
                    item.get("destination_number"),
                ]
            )

        for candidate in ordered_candidates:
            value = str(candidate or "").strip()
            if value and not self._looks_like_extension(value):
                return value
        return str(ordered_candidates[0] or "").strip()

    @staticmethod
    def _looks_like_extension(value: str) -> bool:
        """Heuristic for internal extension values in OnlinePBX records."""
        digits = value.replace("+", "").strip()
        return digits.isdigit() and len(digits) <= 6

    def _replace_url_placeholders(self, value: str) -> str:
        """Substitute supported OnlinePBX URL placeholders from current settings."""
        replacements = {
            "{api_key}": self.api_key,
            "{domain}": self._extract_domain_host(),
            "{host}": self._extract_domain_host(),
            "{subdomain}": self._extract_domain_host().split(".")[0],
        }
        resolved = value
        for source, target in replacements.items():
            resolved = resolved.replace(source, target)
        return resolved

    def _extract_domain_host(self) -> str:
        """Return the OnlinePBX host without scheme or trailing slash."""
        candidate = self.domain
        if candidate.startswith("http://") or candidate.startswith("https://"):
            return urlparse(candidate).netloc.strip().lower()
        return candidate.strip().strip("/").lower()

    def _safe_config_snapshot(self) -> str:
        """Return a safe config snapshot for diagnostics without secrets."""
        return (
            "{"
            f"domain='{settings.onlinepbx_domain}', "
            f"base_url='{settings.onlinepbx_base_url}', "
            f"api_base_url_override='{settings.onlinepbx_api_base_url or ''}', "
            f"cdr_url_override='{self._safe_url(settings.onlinepbx_cdr_url) if settings.onlinepbx_cdr_url else ''}'"
            "}"
        )

    def _safe_url(self, url: str) -> str:
        """Mask the API key before logging or surfacing URLs."""
        if not url:
            return url
        return url.replace(self.api_key, "***")
