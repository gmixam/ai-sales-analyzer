"""Persistence helpers for call-processing runs and artifacts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.agents.call_processing.schemas import (
    ArtifactKind,
    ArtifactStatus,
    EnsureMode,
    ProcessingRunStatus,
    ProcessingScope,
    RequiredArtifactKind,
    stable_scope_hash,
)
from app.core_shared.db.models import CallArtifact, CallProcessingRun


DEFAULT_ARTIFACT_VERSIONS: dict[str, str] = {
    ArtifactKind.TRANSCRIPT.value: "transcript_v1",
    ArtifactKind.TRANSCRIPT_SEGMENTS.value: "transcript_segments_v1",
    ArtifactKind.LLM1_FIRST_PASS.value: "llm1_first_pass_v1",
}


def _coerce_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _same_identity(left: Any, right: Any) -> bool:
    return str(left or "") == str(right or "")


class ArtifactRepository:
    """Read and write active call-processing artifacts."""

    def __init__(self, session: Any) -> None:
        self.session = session

    def latest_active(
        self,
        interaction_id: uuid.UUID | str,
        artifact_kind: ArtifactKind | RequiredArtifactKind | str,
        artifact_version: str | None = None,
    ) -> CallArtifact | None:
        kind = str(_coerce_value(artifact_kind))
        version = artifact_version or DEFAULT_ARTIFACT_VERSIONS[kind]
        stmt = (
            select(CallArtifact)
            .where(CallArtifact.interaction_id == interaction_id)
            .where(CallArtifact.artifact_kind == kind)
            .where(CallArtifact.artifact_version == version)
            .where(CallArtifact.is_active.is_(True))
            .order_by(CallArtifact.updated_at.desc(), CallArtifact.created_at.desc())
        )
        return self.session.scalars(stmt).first()

    def list_latest_active(
        self,
        interaction_ids: list[uuid.UUID | str],
        artifact_kinds: list[ArtifactKind | RequiredArtifactKind | str],
    ) -> list[CallArtifact]:
        if not interaction_ids or not artifact_kinds:
            return []
        kinds = [str(_coerce_value(kind)) for kind in artifact_kinds]
        stmt = (
            select(CallArtifact)
            .where(CallArtifact.interaction_id.in_(interaction_ids))
            .where(CallArtifact.artifact_kind.in_(kinds))
            .where(CallArtifact.is_active.is_(True))
        )
        return list(self.session.scalars(stmt).all())

    def write_active(
        self,
        *,
        department_id: uuid.UUID | str,
        interaction_id: uuid.UUID | str,
        artifact_kind: ArtifactKind | RequiredArtifactKind | str,
        status: ArtifactStatus | str,
        artifact_version: str | None = None,
        payload_json: dict[str, Any] | None = None,
        text_value: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        account_alias: str | None = None,
        api_key_env: str | None = None,
        raw_response_ref: str | None = None,
        error_class: str | None = None,
        error_reason: str | None = None,
        retryable: bool | None = None,
        source_updated_at: datetime | None = None,
    ) -> CallArtifact:
        kind = str(_coerce_value(artifact_kind))
        version = artifact_version or DEFAULT_ARTIFACT_VERSIONS[kind]
        self._deactivate_pending_active(interaction_id, kind, version)
        no_autoflush = getattr(self.session, "no_autoflush", None)
        if no_autoflush is not None:
            with no_autoflush:
                existing = self.latest_active(interaction_id, kind, version)
        else:
            existing = self.latest_active(interaction_id, kind, version)
        if existing is not None:
            existing.is_active = False
            flush = getattr(self.session, "flush", None)
            if callable(flush):
                flush()

        artifact = CallArtifact(
            id=uuid.uuid4(),
            department_id=department_id,
            interaction_id=interaction_id,
            artifact_kind=kind,
            artifact_version=version,
            status=str(_coerce_value(status)),
            is_active=True,
            payload_json=payload_json,
            text_value=text_value,
            provider=provider,
            model=model,
            account_alias=account_alias,
            api_key_env=api_key_env,
            raw_response_ref=raw_response_ref,
            error_class=error_class,
            error_reason=error_reason,
            retryable=retryable,
            source_updated_at=source_updated_at or datetime.now(UTC),
        )
        self.session.add(artifact)
        return artifact

    def _deactivate_pending_active(
        self,
        interaction_id: uuid.UUID | str,
        artifact_kind: str,
        artifact_version: str,
    ) -> None:
        pending = getattr(self.session, "new", None)
        if pending is None:
            return
        for artifact in list(pending):
            if not isinstance(artifact, CallArtifact):
                continue
            if not bool(getattr(artifact, "is_active", False)):
                continue
            if not _same_identity(getattr(artifact, "interaction_id", None), interaction_id):
                continue
            if getattr(artifact, "artifact_kind", None) != artifact_kind:
                continue
            if getattr(artifact, "artifact_version", None) != artifact_version:
                continue
            artifact.is_active = False


class ProcessingRunRepository:
    """Persistence helper for durable call-processing runs."""

    def __init__(self, session: Any) -> None:
        self.session = session

    def create(
        self,
        *,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | str],
        mode: EnsureMode | str,
        requested_by: str,
        status: ProcessingRunStatus = ProcessingRunStatus.QUEUED,
        counts_json: dict[str, Any] | None = None,
        errors_json: list[dict[str, Any]] | None = None,
    ) -> CallProcessingRun:
        model = scope if isinstance(scope, ProcessingScope) else ProcessingScope.model_validate(scope)
        run = CallProcessingRun(
            id=uuid.uuid4(),
            requested_by=requested_by,
            scope_json=model.model_dump(mode="json", exclude_none=True),
            scope_hash=stable_scope_hash(model),
            required_artifacts=[str(_coerce_value(kind)) for kind in required_artifacts],
            mode=str(_coerce_value(mode)),
            status=str(_coerce_value(status)),
            heartbeat_at=datetime.now(UTC),
            counts_json=counts_json or {},
            errors_json=errors_json or [],
        )
        self.session.add(run)
        return run

    def update_status(
        self,
        run: CallProcessingRun,
        status: ProcessingRunStatus | str,
        *,
        counts_json: dict[str, Any] | None = None,
        errors_json: list[dict[str, Any]] | None = None,
        finished_at: datetime | None = None,
    ) -> CallProcessingRun:
        now = datetime.now(UTC)
        run.status = str(_coerce_value(status))
        run.heartbeat_at = now
        if counts_json is not None:
            run.counts_json = counts_json
        if errors_json is not None:
            run.errors_json = errors_json
        if finished_at is not None:
            run.finished_at = finished_at
        return run

    def get(self, run_id: uuid.UUID | str) -> CallProcessingRun | None:
        try:
            normalized_run_id = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))
        except (TypeError, ValueError, AttributeError):
            return None
        if hasattr(self.session, "get"):
            return self.session.get(CallProcessingRun, normalized_run_id)
        stmt = select(CallProcessingRun).where(CallProcessingRun.id == normalized_run_id)
        return self.session.scalars(stmt).first()

    def list_open(self) -> list[CallProcessingRun]:
        stmt = (
            select(CallProcessingRun)
            .where(
                CallProcessingRun.status.in_(
                    [
                        str(ProcessingRunStatus.QUEUED),
                        str(ProcessingRunStatus.RUNNING),
                    ]
                )
            )
            .order_by(CallProcessingRun.updated_at.asc())
        )
        return list(self.session.scalars(stmt).all())

    def latest_for_scope(
        self,
        *,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | str] | None = None,
    ) -> CallProcessingRun | None:
        """Return the newest run for an exact normalized processing scope."""
        model = scope if isinstance(scope, ProcessingScope) else ProcessingScope.model_validate(scope)
        scope_hash = stable_scope_hash(model)
        stmt = select(CallProcessingRun).where(CallProcessingRun.scope_hash == scope_hash)
        stmt = stmt.order_by(
            CallProcessingRun.updated_at.desc(),
            CallProcessingRun.created_at.desc(),
        )
        if required_artifacts:
            required = sorted({str(_coerce_value(kind)) for kind in required_artifacts})
            for run in self.session.scalars(stmt).all():
                actual = sorted({str(item) for item in list(run.required_artifacts or [])})
                if actual == required:
                    return run
            return None
        return self.session.scalars(stmt).first()

    def status(self, run_id: uuid.UUID | str) -> ProcessingRunStatus | None:
        run = self.get(run_id)
        return ProcessingRunStatus(run.status) if run is not None else None
