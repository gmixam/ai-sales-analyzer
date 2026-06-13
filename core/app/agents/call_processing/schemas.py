"""Versioned contracts for the call-processing / analysis split.

Task 0 intentionally introduces only stable data shapes and constants. It does
not move runtime ownership, create migrations, or change current pilot behavior.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LLM1_FIRST_PASS_SCHEMA_VERSION = "llm1_first_pass_v1"


class ArtifactKind(StrEnum):
    """Artifact kinds owned by call-processing."""

    TRANSCRIPT = "transcript"
    TRANSCRIPT_SEGMENTS = "transcript_segments"
    LLM1_FIRST_PASS = "llm1_first_pass"


class RequiredArtifactKind(StrEnum):
    """Artifacts accepted by ensure/read requests."""

    TRANSCRIPT = "transcript"
    TRANSCRIPT_SEGMENTS = "transcript_segments"
    LLM1_FIRST_PASS = "llm1_first_pass"


class ArtifactStatus(StrEnum):
    """Durable artifact status values from the split contract."""

    READY = "ready"
    MISSING = "missing"
    PROCESSING = "processing"
    FAILED = "failed"
    SKIPPED = "skipped"
    STALE = "stale"


class ProcessingRunStatus(StrEnum):
    """Durable call-processing run status values."""

    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class ProcessingErrorClass(StrEnum):
    """Structured call-processing error classes."""

    QUOTA_INSUFFICIENT = "quota_insufficient"
    RATE_LIMITED = "rate_limited"
    AUTH_ERROR = "auth_error"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_5XX = "provider_5xx"
    SOURCE_AUDIO_EXPIRED = "source_audio_expired"
    SOURCE_AUDIO_MISSING = "source_audio_missing"
    SOURCE_RECORDING_URL_REFRESH_FAILED = "source_recording_url_refresh_failed"
    VALIDATION_ERROR = "validation_error"
    UNKNOWN_ERROR = "unknown_error"


RETRYABLE_ERROR_CLASSES: frozenset[ProcessingErrorClass] = frozenset(
    {
        ProcessingErrorClass.PROVIDER_TIMEOUT,
        ProcessingErrorClass.RATE_LIMITED,
        ProcessingErrorClass.PROVIDER_5XX,
    }
)

NON_RETRYABLE_ERROR_CLASSES: frozenset[ProcessingErrorClass] = frozenset(
    set(ProcessingErrorClass) - set(RETRYABLE_ERROR_CLASSES)
)


class ProcessingClientType(StrEnum):
    """Call-processing client identity type."""

    SERVICE = "service"
    EMPLOYEE = "employee"


class ProcessingClientRole(StrEnum):
    """Call-processing role values."""

    ADMIN = "admin"
    READER = "reader"


class EnsureMode(StrEnum):
    """Supported ensure modes."""

    ENSURE = "ensure"
    DRY_RUN = "dry_run"


class AppService(StrEnum):
    """Runtime service identity values."""

    CALL_PROCESSING = "call_processing"
    ANALYSIS = "analysis"
    MONOLITH_LEGACY = "monolith_legacy"


class CallProcessingMode(StrEnum):
    """Analysis-side call-processing mode flag."""

    LEGACY = "legacy"
    EXTERNAL_SERVICE = "external_service"


APP_SERVICE_VALUES = tuple(item.value for item in AppService)
CALL_PROCESSING_MODE_VALUES = tuple(item.value for item in CallProcessingMode)


class ArtifactError(BaseModel):
    """Structured artifact error included in persisted payloads and API responses."""

    model_config = ConfigDict(use_enum_values=True)

    class_: ProcessingErrorClass | None = Field(default=None, alias="class")
    message: str | None = None
    retryable: bool = False

    @model_validator(mode="after")
    def align_retryable_flag(self) -> ArtifactError:
        """Keep retryability deterministic for known structured classes."""
        if self.class_ is not None:
            self.retryable = ProcessingErrorClass(self.class_) in RETRYABLE_ERROR_CLASSES
        return self


class LLM1FirstPassPayload(BaseModel):
    """Persisted `llm1_first_pass_v1` payload consumed by analysis."""

    model_config = ConfigDict(populate_by_name=True, use_enum_values=True)

    schema_version: str = LLM1_FIRST_PASS_SCHEMA_VERSION
    prompt_version: str
    provider: str
    model: str
    account_alias: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: ArtifactStatus = ArtifactStatus.READY
    classification: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    follow_up: dict[str, Any] = Field(default_factory=dict)
    data_quality: dict[str, Any] = Field(default_factory=dict)
    analysis_focus: dict[str, Any] | list[Any] = Field(default_factory=dict)
    error: ArtifactError = Field(default_factory=ArtifactError)

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        """Fail loudly when analysis receives an unsupported LLM1 contract."""
        if value != LLM1_FIRST_PASS_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {value}")
        return value

    @field_validator("prompt_version", "provider", "model", mode="before")
    @classmethod
    def normalize_required_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("account_alias", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    @model_validator(mode="after")
    def validate_status_contract(self) -> LLM1FirstPassPayload:
        allowed = {ArtifactStatus.READY, ArtifactStatus.FAILED, ArtifactStatus.SKIPPED}
        if ArtifactStatus(self.status) not in allowed:
            raise ValueError("llm1_first_pass status must be ready, failed, or skipped")
        return self


class ProcessingScope(BaseModel):
    """Normalized call-processing scope used by API/CLI/client calls."""

    model_config = ConfigDict(use_enum_values=True)

    department: str | None = None
    department_id: str | None = None
    manager_ids: list[str] = Field(default_factory=list)
    extensions: list[str] = Field(default_factory=list)
    date_from: date
    date_to: date
    source: str = "onlinepbx"
    min_duration_sec: int | None = None
    max_duration_sec: int | None = None

    @field_validator("department", "department_id", "source", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    @field_validator("manager_ids", "extensions", mode="before")
    @classmethod
    def normalize_string_list(cls, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, list):
            return sorted({str(item).strip() for item in value if str(item).strip()})
        return sorted({item.strip() for item in str(value).split(",") if item.strip()})

    @model_validator(mode="after")
    def validate_date_range(self) -> ProcessingScope:
        if self.date_to < self.date_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        return self


class EnsureRequest(BaseModel):
    """Control API/CLI request for ensuring call-processing artifacts."""

    model_config = ConfigDict(use_enum_values=True)

    scope: ProcessingScope
    required_artifacts: list[RequiredArtifactKind] = Field(default_factory=list)
    mode: EnsureMode = EnsureMode.ENSURE
    force_retry_failed: bool = False
    requested_by: str

    @field_validator("requested_by", mode="before")
    @classmethod
    def normalize_requested_by(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("requested_by must not be empty")
        return text

    @field_validator("required_artifacts", mode="before")
    @classmethod
    def normalize_artifacts(cls, value: Any) -> list[Any]:
        if value in (None, "", []):
            return []
        if isinstance(value, list):
            return value
        return [item.strip() for item in str(value).split(",") if item.strip()]


class EnsureResponse(BaseModel):
    """Minimal response shape shared by API, CLI, and future client."""

    model_config = ConfigDict(use_enum_values=True)

    run_id: str
    status: ProcessingRunStatus
    scope_hash: str
    requested_by: str
    planned: dict[str, int] = Field(default_factory=dict)
    quota: dict[str, Any] = Field(default_factory=dict)


class AccessGrant(BaseModel):
    """Per service/employee call-processing access grant."""

    model_config = ConfigDict(use_enum_values=True)

    client_id: str
    client_type: ProcessingClientType
    role: ProcessingClientRole
    allowed_artifact_kinds: list[ArtifactKind] = Field(default_factory=list)
    read_surfaces: list[str] = Field(default_factory=list)
    rate_limits: dict[str, int] = Field(default_factory=dict)
    created_by_admin: str
    active: bool = True

    @property
    def provider_call_budget_per_run(self) -> int | None:
        for key in ("provider_calls_per_run", "max_provider_calls_per_run", "provider_calls"):
            raw = self.rate_limits.get(key)
            if raw is None:
                continue
            limit = int(raw)
            if limit >= 0:
                return limit
        return None

    @field_validator("client_id", "created_by_admin", mode="before")
    @classmethod
    def normalize_required_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @property
    def can_run_processing(self) -> bool:
        """Only admin grants can trigger billable processing actions."""
        return ProcessingClientRole(self.role) is ProcessingClientRole.ADMIN and self.active


def stable_scope_hash(scope: ProcessingScope | dict[str, Any]) -> str:
    """Return a deterministic scope hash for idempotent run planning."""
    model = scope if isinstance(scope, ProcessingScope) else ProcessingScope.model_validate(scope)
    payload = model.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
