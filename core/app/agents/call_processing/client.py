"""Analysis-facing client for call-processing artifacts."""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from pydantic import ValidationError

from app.agents.call_processing.repositories import (
    DEFAULT_ARTIFACT_VERSIONS,
    ArtifactRepository,
)
from app.agents.call_processing.schemas import (
    LLM1_FIRST_PASS_SCHEMA_VERSION,
    ArtifactKind,
    ArtifactStatus,
    EnsureMode,
    EnsureResponse,
    LLM1FirstPassPayload,
    ProcessingScope,
    RequiredArtifactKind,
)
from app.agents.call_processing.service import CallProcessingService


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

    def get_processed_artifacts(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str],
    ) -> list[Any]:
        """Return latest active artifacts for in-scope calls."""

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
