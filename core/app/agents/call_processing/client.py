"""Analysis-facing client for call-processing artifacts."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, NoReturn, Protocol

import httpx
from pydantic import ValidationError

from app.agents.call_processing.repositories import (
    DEFAULT_ARTIFACT_VERSIONS,
    ArtifactRepository,
    ProcessingRunRepository,
)
from app.agents.call_processing.schemas import (
    AccessGrant,
    LLM1_FIRST_PASS_SCHEMA_VERSION,
    ArtifactKind,
    ArtifactStatus,
    CallProcessingMode,
    EnsureMode,
    EnsureRequest,
    EnsureResponse,
    LLM1FirstPassPayload,
    ProcessingRunReadiness,
    ProcessingScope,
    RequiredArtifactKind,
)
from app.agents.call_processing.service import CallProcessingService
from app.core_shared.config.settings import settings
from app.core_shared.exceptions import ASAError


class CallProcessingArtifactError(ValueError):
    """Raised when a persisted call-processing artifact violates its contract."""


class CallProcessingClient(Protocol):
    """Client boundary consumed by analysis/reporting code."""

    def ensure_processed_calls(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
        mode: EnsureMode | str = EnsureMode.ENSURE,
    ) -> EnsureResponse:
        """Ensure the requested artifacts exist or are planned for the scope."""

    async def ensure_processed_calls_async(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
        mode: EnsureMode | str = EnsureMode.ENSURE,
    ) -> EnsureResponse:
        """Async variant for report runs that already execute inside an event loop."""

    def get_processed_artifacts(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
    ) -> list[Any]:
        """Return latest active artifacts for in-scope calls."""

    def get_latest_run_for_scope(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
    ) -> ProcessingRunReadiness | None:
        """Return the newest upstream run for the exact normalized scope."""

    def get_llm1_first_pass_artifact(
        self,
        interaction_id: uuid.UUID | str,
    ) -> LLM1FirstPassPayload | None:
        """Return the ready LLM-1 first-pass artifact for one interaction, if present."""


def _coerce_required_artifacts(
    required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
) -> list[RequiredArtifactKind]:
    return [
        RequiredArtifactKind(str(item.value if hasattr(item, "value") else item))
        for item in required_artifacts
    ]


def llm1_first_pass_payload_from_artifact(artifact: Any) -> LLM1FirstPassPayload:
    """Validate and adapt a durable artifact row to the analysis LLM-1 payload."""
    artifact_kind = getattr(artifact, "artifact_kind", None)
    if artifact_kind != ArtifactKind.LLM1_FIRST_PASS.value:
        raise CallProcessingArtifactError(
            f"expected llm1_first_pass artifact, got {artifact_kind!r}"
        )

    artifact_version = getattr(artifact, "artifact_version", None)
    if artifact_version != LLM1_FIRST_PASS_SCHEMA_VERSION:
        raise CallProcessingArtifactError(
            f"expected llm1_first_pass_v1 artifact, got {artifact_version!r}"
        )

    if getattr(artifact, "is_active", None) is not True:
        raise CallProcessingArtifactError("llm1_first_pass_v1 artifact is not active")

    artifact_status = getattr(artifact, "status", None)
    if artifact_status != ArtifactStatus.READY.value:
        raise CallProcessingArtifactError(
            f"llm1_first_pass_v1 artifact is not ready: status={artifact_status!r}"
        )

    raw_payload = getattr(artifact, "payload_json", None)
    if not isinstance(raw_payload, dict):
        raise CallProcessingArtifactError("llm1_first_pass_v1 artifact payload must be an object")

    payload = dict(raw_payload)
    payload.setdefault("schema_version", LLM1_FIRST_PASS_SCHEMA_VERSION)
    payload.setdefault("status", artifact_status)
    for field_name in ("provider", "model", "account_alias"):
        value = getattr(artifact, field_name, None)
        if value is not None:
            payload.setdefault(field_name, value)

    try:
        validated = LLM1FirstPassPayload.model_validate(payload)
    except ValidationError as exc:
        raise CallProcessingArtifactError(
            f"invalid llm1_first_pass_v1 artifact payload: {exc}"
        ) from exc

    if ArtifactStatus(validated.status) != ArtifactStatus.READY:
        raise CallProcessingArtifactError(
            f"llm1_first_pass_v1 payload is not ready: status={validated.status!r}"
        )
    return validated


def processing_run_readiness_from_row(row: Any) -> ProcessingRunReadiness:
    """Adapt a persisted call-processing run to the read-only client contract."""
    return ProcessingRunReadiness(
        run_id=str(row.id),
        status=getattr(row, "status", None),
        scope_hash=str(getattr(row, "scope_hash", "") or ""),
        requested_by=getattr(row, "requested_by", None),
        required_artifacts=list(getattr(row, "required_artifacts", None) or []),
        mode=getattr(row, "mode", None),
        counts=dict(getattr(row, "counts_json", None) or {}),
        errors=list(getattr(row, "errors_json", None) or []),
        started_at=getattr(row, "started_at", None),
        finished_at=getattr(row, "finished_at", None),
        heartbeat_at=getattr(row, "heartbeat_at", None),
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


class LocalCallProcessingClient:
    """In-process client implementation for the monolith transition period."""

    def __init__(
        self,
        session: Any,
        *,
        service: CallProcessingService | None = None,
        artifacts: ArtifactRepository | None = None,
        requested_by: str = "analysis",
    ) -> None:
        self.session = session
        self.artifacts = artifacts or ArtifactRepository(session)
        self.runs = ProcessingRunRepository(session)
        self.service = service or CallProcessingService(
            session,
            artifacts=self.artifacts,
            requested_by=requested_by,
        )
        self.requested_by = requested_by

    def ensure_processed_calls(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
        mode: EnsureMode | str = EnsureMode.ENSURE,
    ) -> EnsureResponse:
        return self.service.ensure(
            scope,
            _coerce_required_artifacts(required_artifacts),
            mode,
            requested_by=self.requested_by,
        )

    async def ensure_processed_calls_async(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
        mode: EnsureMode | str = EnsureMode.ENSURE,
    ) -> EnsureResponse:
        return await self.service.ensure_async(
            scope,
            _coerce_required_artifacts(required_artifacts),
            mode,
            requested_by=self.requested_by,
        )

    def get_processed_artifacts(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
    ) -> list[Any]:
        scope_model = scope if isinstance(scope, ProcessingScope) else ProcessingScope.model_validate(scope)
        required = _coerce_required_artifacts(required_artifacts)
        interactions = self.service._find_interactions(scope_model)
        interaction_ids = [interaction.id for interaction in interactions]
        return self.artifacts.list_latest_active(interaction_ids, required)

    def get_latest_run_for_scope(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
    ) -> ProcessingRunReadiness | None:
        row = self.runs.latest_for_scope(
            scope=scope,
            required_artifacts=_coerce_required_artifacts(required_artifacts),
        )
        if row is None:
            return None
        return processing_run_readiness_from_row(row)

    def get_llm1_first_pass_artifact(
        self,
        interaction_id: uuid.UUID | str,
    ) -> LLM1FirstPassPayload | None:
        artifact = self.artifacts.latest_active(
            interaction_id,
            RequiredArtifactKind.LLM1_FIRST_PASS,
            DEFAULT_ARTIFACT_VERSIONS[RequiredArtifactKind.LLM1_FIRST_PASS.value],
        )
        if artifact is None:
            return None
        return llm1_first_pass_payload_from_artifact(artifact)


def _artifact_row_from_api(payload: dict[str, Any]) -> SimpleNamespace:
    """Adapt API artifact JSON to the row-like shape used by the local adapter."""
    return SimpleNamespace(
        id=payload.get("artifact_id"),
        department_id=payload.get("department_id"),
        interaction_id=payload.get("interaction_id"),
        artifact_kind=payload.get("artifact_kind"),
        artifact_version=payload.get("artifact_version"),
        status=payload.get("status"),
        is_active=payload.get("is_active"),
        payload_json=payload.get("payload"),
        text_value=payload.get("text"),
        provider=payload.get("provider"),
        model=payload.get("model"),
        account_alias=payload.get("account_alias"),
        raw_response_ref=payload.get("raw_response_ref"),
        error_class=payload.get("error_class"),
        error_reason=payload.get("error_reason"),
        retryable=payload.get("retryable"),
        source_updated_at=payload.get("source_updated_at"),
        created_at=payload.get("created_at"),
        updated_at=payload.get("updated_at"),
    )


class HttpCallProcessingClient:
    """HTTP client implementation for split analysis deployments."""

    READ_TIMEOUT_REASON = "call_processing_client_read_timeout"

    def __init__(
        self,
        *,
        base_url: str,
        access_grant: AccessGrant | dict[str, Any] | str,
        timeout_sec: int = 30,
        requested_by: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        if not self.base_url:
            raise ASAError("CALL_PROCESSING_API_BASE_URL must not be empty.")
        if isinstance(access_grant, AccessGrant):
            self.access_grant = access_grant
        elif isinstance(access_grant, str):
            self.access_grant = AccessGrant.model_validate_json(access_grant)
        else:
            self.access_grant = AccessGrant.model_validate(access_grant)
        self.requested_by = requested_by or self.access_grant.client_id
        self.timeout_sec = timeout_sec

    def _raise_read_timeout(self, operation: str, exc: httpx.ReadTimeout) -> NoReturn:
        raise ASAError(
            f"{self.READ_TIMEOUT_REASON}: operation={operation} timeout_sec={self.timeout_sec}"
        ) from exc

    def _headers(self) -> dict[str, str]:
        return {
            "X-Call-Processing-Grant": self.access_grant.model_dump_json(),
        }

    def ensure_processed_calls(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
        mode: EnsureMode | str = EnsureMode.ENSURE,
    ) -> EnsureResponse:
        request = EnsureRequest(
            scope=scope if isinstance(scope, ProcessingScope) else ProcessingScope.model_validate(scope),
            required_artifacts=_coerce_required_artifacts(required_artifacts),
            mode=EnsureMode(mode),
            requested_by=self.requested_by,
        )
        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                response = client.post(
                    f"{self.base_url}/call-processing/ensure",
                    json=request.model_dump(mode="json"),
                    headers=self._headers(),
                )
        except httpx.ReadTimeout as exc:
            self._raise_read_timeout("ensure_processed_calls", exc)
        if response.status_code >= 400:
            raise ASAError(f"call-processing ensure failed: status={response.status_code} body={response.text[:500]}")
        return EnsureResponse.model_validate(response.json())

    async def ensure_processed_calls_async(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
        mode: EnsureMode | str = EnsureMode.ENSURE,
    ) -> EnsureResponse:
        request = EnsureRequest(
            scope=scope if isinstance(scope, ProcessingScope) else ProcessingScope.model_validate(scope),
            required_artifacts=_coerce_required_artifacts(required_artifacts),
            mode=EnsureMode(mode),
            requested_by=self.requested_by,
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                response = await client.post(
                    f"{self.base_url}/call-processing/ensure",
                    json=request.model_dump(mode="json"),
                    headers=self._headers(),
                )
        except httpx.ReadTimeout as exc:
            self._raise_read_timeout("ensure_processed_calls_async", exc)
        if response.status_code >= 400:
            raise ASAError(f"call-processing ensure failed: status={response.status_code} body={response.text[:500]}")
        return EnsureResponse.model_validate(response.json())

    def get_processed_artifacts(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
    ) -> list[Any]:
        scope_model = scope if isinstance(scope, ProcessingScope) else ProcessingScope.model_validate(scope)
        kinds = _coerce_required_artifacts(required_artifacts)
        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                response = client.get(
                    f"{self.base_url}/call-processing/artifacts",
                    params={
                        "scope": scope_model.model_dump_json(exclude_none=True),
                        "artifact_kinds": ",".join(kind.value for kind in kinds),
                    },
                    headers=self._headers(),
                )
        except httpx.ReadTimeout as exc:
            self._raise_read_timeout("get_processed_artifacts", exc)
        if response.status_code >= 400:
            raise ASAError(f"call-processing artifact read failed: status={response.status_code} body={response.text[:500]}")
        payload = response.json()
        return [_artifact_row_from_api(item) for item in payload.get("artifacts", [])]

    def get_latest_run_for_scope(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
    ) -> ProcessingRunReadiness | None:
        scope_model = scope if isinstance(scope, ProcessingScope) else ProcessingScope.model_validate(scope)
        kinds = _coerce_required_artifacts(required_artifacts)
        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                response = client.get(
                    f"{self.base_url}/call-processing/runs/latest",
                    params={
                        "scope": scope_model.model_dump_json(exclude_none=True),
                        "required_artifacts": ",".join(kind.value for kind in kinds),
                    },
                    headers=self._headers(),
                )
        except httpx.ReadTimeout as exc:
            self._raise_read_timeout("get_latest_run_for_scope", exc)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise ASAError(f"call-processing run read failed: status={response.status_code} body={response.text[:500]}")
        return ProcessingRunReadiness.model_validate(response.json())

    def get_llm1_first_pass_artifact(
        self,
        interaction_id: uuid.UUID | str,
    ) -> LLM1FirstPassPayload | None:
        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                response = client.get(
                    f"{self.base_url}/call-processing/artifacts/{interaction_id}/llm1_first_pass",
                    headers=self._headers(),
                )
        except httpx.ReadTimeout as exc:
            self._raise_read_timeout("get_llm1_first_pass_artifact", exc)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise ASAError(f"call-processing llm1 artifact read failed: status={response.status_code} body={response.text[:500]}")
        return llm1_first_pass_payload_from_artifact(_artifact_row_from_api(response.json()))


def build_call_processing_client(
    session: Any,
    *,
    requested_by: str = "edo-analysis-reporting",
) -> CallProcessingClient:
    """Build the right client implementation for current runtime settings."""
    if (
        settings.app_service == "analysis"
        and settings.call_processing_mode == CallProcessingMode.EXTERNAL_SERVICE.value
    ):
        return HttpCallProcessingClient(
            base_url=settings.call_processing_api_base_url,
            access_grant=settings.call_processing_access_grant_json,
            timeout_sec=settings.call_processing_client_timeout_sec,
            requested_by=requested_by,
        )
    return LocalCallProcessingClient(session, requested_by=requested_by)
