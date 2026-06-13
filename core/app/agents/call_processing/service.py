"""Planning-oriented call-processing domain service."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.agents.call_processing.repositories import (
    DEFAULT_ARTIFACT_VERSIONS,
    ArtifactRepository,
    ProcessingRunRepository,
)
from app.agents.call_processing.schemas import (
    ArtifactKind,
    ArtifactStatus,
    EnsureMode,
    EnsureResponse,
    ProcessingErrorClass,
    ProcessingRunStatus,
    ProcessingScope,
    RequiredArtifactKind,
    RETRYABLE_ERROR_CLASSES,
    stable_scope_hash,
)
from app.core_shared.db.models import Interaction

STALE_RUN_AFTER = timedelta(minutes=30)
MAX_PROVIDER_ATTEMPTS = 3


def is_retryable_error(error_class: ProcessingErrorClass | str | None) -> bool:
    """Return whether an error class is eligible for automatic retry."""
    if error_class is None:
        return False
    try:
        return ProcessingErrorClass(error_class) in RETRYABLE_ERROR_CLASSES
    except ValueError:
        return False


def should_retry_error(error_class: ProcessingErrorClass | str | None, attempt_count: int) -> bool:
    """Return whether another attempt is allowed for this error and attempt count."""
    return is_retryable_error(error_class) and attempt_count < MAX_PROVIDER_ATTEMPTS


def is_stale_run(run: Any, *, now: datetime | None = None) -> bool:
    """Detect runs with no heartbeat/progress for the approved stale window."""
    status = ProcessingRunStatus(getattr(run, "status"))
    if status not in {ProcessingRunStatus.QUEUED, ProcessingRunStatus.RUNNING}:
        return False
    heartbeat_at = getattr(run, "heartbeat_at", None) or getattr(run, "updated_at", None)
    if heartbeat_at is None:
        return False
    current = now or datetime.now(UTC)
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=UTC)
    return current - heartbeat_at > STALE_RUN_AFTER


class CallProcessingService:
    """Ensure required call-processing artifacts without making provider calls."""

    def __init__(
        self,
        session: Any,
        *,
        artifacts: ArtifactRepository | None = None,
        runs: ProcessingRunRepository | None = None,
        requested_by: str = "call_processing_service",
    ) -> None:
        self.session = session
        self.artifacts = artifacts or ArtifactRepository(session)
        self.runs = runs or ProcessingRunRepository(session)
        self.requested_by = requested_by

    def ensure(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str] | None = None,
        mode: EnsureMode | str = EnsureMode.ENSURE,
        *,
        requested_by: str | None = None,
    ) -> EnsureResponse:
        scope_model = scope if isinstance(scope, ProcessingScope) else ProcessingScope.model_validate(scope)
        mode_model = EnsureMode(mode)
        required = self._normalize_required_artifacts(required_artifacts)
        requester = requested_by or self.requested_by

        run = self.runs.create(
            scope=scope_model,
            required_artifacts=required,
            mode=mode_model,
            requested_by=requester,
            status=ProcessingRunStatus.RUNNING,
        )
        interactions = self._find_interactions(scope_model)
        counts = self._plan_and_backfill(interactions, required, mode_model)
        status = self._status_from_counts(counts)

        self.runs.update_status(
            run,
            status,
            counts_json=counts,
            finished_at=datetime.now(UTC),
        )
        self._commit_if_available()

        return EnsureResponse(
            run_id=str(run.id),
            status=status,
            scope_hash=stable_scope_hash(scope_model),
            requested_by=requester,
            planned=counts,
            quota={"provider_calls_made": 0, "provider_calls_allowed": mode_model != EnsureMode.DRY_RUN},
        )

    def _normalize_required_artifacts(
        self,
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str] | None,
    ) -> list[RequiredArtifactKind]:
        if not required_artifacts:
            return []
        normalized = [RequiredArtifactKind(str(item.value if hasattr(item, "value") else item)) for item in required_artifacts]
        return sorted(set(normalized), key=lambda item: item.value)

    def _find_interactions(self, scope: ProcessingScope) -> list[Interaction]:
        stmt = select(Interaction).where(Interaction.type == "call")
        if scope.department_id:
            stmt = stmt.where(Interaction.department_id == scope.department_id)
        if scope.source:
            stmt = stmt.where(Interaction.source == scope.source)
        if scope.manager_ids:
            stmt = stmt.where(Interaction.manager_id.in_(scope.manager_ids))
        if scope.min_duration_sec is not None:
            stmt = stmt.where(Interaction.duration_sec >= scope.min_duration_sec)
        if scope.max_duration_sec is not None:
            stmt = stmt.where(Interaction.duration_sec <= scope.max_duration_sec)
        interactions = list(self.session.scalars(stmt).all())
        return [
            interaction
            for interaction in interactions
            if self._interaction_matches_scope(interaction, scope)
        ]

    def _interaction_matches_scope(self, interaction: Interaction, scope: ProcessingScope) -> bool:
        metadata = getattr(interaction, "metadata_", None) or {}
        if not isinstance(metadata, dict):
            metadata = {}

        call_day = self._extract_call_day(metadata)
        if call_day is None or call_day < scope.date_from or call_day > scope.date_to:
            return False

        if scope.extensions:
            extension = str(metadata.get("extension") or "").strip()
            if extension not in set(scope.extensions):
                return False

        if scope.manager_ids:
            manager_id = getattr(interaction, "manager_id", None)
            if str(manager_id or "") not in set(scope.manager_ids):
                return False

        return True

    def _extract_call_day(self, metadata: dict[str, Any]) -> date | None:
        raw = metadata.get("call_date") or metadata.get("started_at") or metadata.get("call_started_at")
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None

    def _plan_and_backfill(
        self,
        interactions: list[Interaction],
        required: list[RequiredArtifactKind],
        mode: EnsureMode,
    ) -> dict[str, int]:
        counts = {
            "interactions_total": len(interactions),
            "artifact_requirements_total": len(interactions) * len(required),
            "artifacts_ready": 0,
            "artifacts_missing": 0,
            "artifacts_backfilled": 0,
            "provider_calls_planned": 0,
            "provider_calls_made": 0,
        }
        for interaction in interactions:
            for kind in required:
                artifact = self.artifacts.latest_active(
                    interaction.id,
                    kind,
                    DEFAULT_ARTIFACT_VERSIONS[kind.value],
                )
                if artifact is not None and artifact.status == ArtifactStatus.READY.value:
                    counts["artifacts_ready"] += 1
                    continue

                backfilled = self._backfill_from_legacy(interaction, kind, mode)
                if backfilled:
                    counts["artifacts_ready"] += 1
                    counts["artifacts_backfilled"] += 1
                    continue

                counts["artifacts_missing"] += 1
                if kind is RequiredArtifactKind.LLM1_FIRST_PASS:
                    counts["provider_calls_planned"] += 1
        return counts

    def _backfill_from_legacy(
        self,
        interaction: Interaction,
        kind: RequiredArtifactKind,
        mode: EnsureMode,
    ) -> bool:
        if kind is RequiredArtifactKind.TRANSCRIPT:
            text = str(getattr(interaction, "text", "") or "").strip()
            if not text:
                return False
            if mode is not EnsureMode.DRY_RUN:
                self.artifacts.write_active(
                    department_id=interaction.department_id,
                    interaction_id=interaction.id,
                    artifact_kind=ArtifactKind.TRANSCRIPT,
                    artifact_version=DEFAULT_ARTIFACT_VERSIONS[ArtifactKind.TRANSCRIPT.value],
                    status=ArtifactStatus.READY,
                    payload_json={"backfilled_from": "public.interactions.text"},
                    text_value=text,
                    source_updated_at=getattr(interaction, "analyzed_at", None) or getattr(interaction, "created_at", None),
                )
            return True

        if kind is RequiredArtifactKind.TRANSCRIPT_SEGMENTS:
            metadata = getattr(interaction, "metadata_", None) or {}
            segments = metadata.get("segments") if isinstance(metadata, dict) else None
            if not isinstance(segments, list) or not segments:
                return False
            if mode is not EnsureMode.DRY_RUN:
                self.artifacts.write_active(
                    department_id=interaction.department_id,
                    interaction_id=interaction.id,
                    artifact_kind=ArtifactKind.TRANSCRIPT_SEGMENTS,
                    artifact_version=DEFAULT_ARTIFACT_VERSIONS[ArtifactKind.TRANSCRIPT_SEGMENTS.value],
                    status=ArtifactStatus.READY,
                    payload_json={
                        "backfilled_from": "public.interactions.metadata.segments",
                        "segments": segments,
                    },
                    source_updated_at=getattr(interaction, "analyzed_at", None) or getattr(interaction, "created_at", None),
                )
            return True

        return False

    def _status_from_counts(self, counts: dict[str, int]) -> ProcessingRunStatus:
        if counts["artifact_requirements_total"] == 0:
            return ProcessingRunStatus.READY
        if counts["artifacts_missing"] == 0:
            return ProcessingRunStatus.READY
        if counts["artifacts_ready"] > 0:
            return ProcessingRunStatus.PARTIAL
        return ProcessingRunStatus.BLOCKED

    def _commit_if_available(self) -> None:
        commit = getattr(self.session, "commit", None)
        if callable(commit):
            commit()
