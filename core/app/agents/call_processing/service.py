"""Planning-oriented call-processing domain service."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable

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
    LLM1FirstPassPayload,
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


class ProviderCallBudget:
    """Small per-run billable provider-call budget guard."""

    def __init__(self, limit: int | None = None) -> None:
        self.limit = limit if limit is None or limit >= 0 else None
        self.made = 0
        self.blocked = False

    @property
    def exhausted(self) -> bool:
        return self.blocked or (self.limit is not None and self.made >= self.limit)

    @property
    def remaining(self) -> int | None:
        if self.limit is None:
            return None
        return max(self.limit - self.made, 0)

    def try_spend(self) -> bool:
        if self.limit is not None and self.made >= self.limit:
            self.blocked = True
            return False
        self.made += 1
        return True

    def mark_blocked(self, counts: dict[str, Any]) -> None:
        self.blocked = True
        counts["quota_blocked"] = int(counts.get("quota_blocked", 0)) + 1


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
    """Ensure required call-processing artifacts and own upstream provider work."""

    def __init__(
        self,
        session: Any,
        *,
        artifacts: ArtifactRepository | None = None,
        runs: ProcessingRunRepository | None = None,
        requested_by: str = "call_processing_service",
        intake_factory: Callable[[str, Any], Any] | None = None,
        extractor_factory: Callable[[str, Any], Any] | None = None,
        analyzer_factory: Callable[[str, Any], Any] | None = None,
    ) -> None:
        self.session = session
        self.artifacts = artifacts or ArtifactRepository(session)
        self.runs = runs or ProcessingRunRepository(session)
        self.requested_by = requested_by
        self.intake_factory = intake_factory
        self.extractor_factory = extractor_factory
        self.analyzer_factory = analyzer_factory

    def ensure(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str] | None = None,
        mode: EnsureMode | str = EnsureMode.ENSURE,
        *,
        requested_by: str | None = None,
        force_retry_failed: bool = False,
        provider_call_budget: int | None = None,
    ) -> EnsureResponse:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.ensure_async(
                    scope,
                    required_artifacts,
                    mode,
                    requested_by=requested_by,
                    force_retry_failed=force_retry_failed,
                    provider_call_budget=provider_call_budget,
                )
            )
        raise RuntimeError("CallProcessingService.ensure() cannot run inside an active event loop; use ensure_async().")

    async def ensure_async(
        self,
        scope: ProcessingScope | dict[str, Any],
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str] | None = None,
        mode: EnsureMode | str = EnsureMode.ENSURE,
        *,
        requested_by: str | None = None,
        force_retry_failed: bool = False,
        provider_call_budget: int | None = None,
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
        budget = ProviderCallBudget(provider_call_budget)
        source_counts = self._discover_and_persist_source_calls(scope_model, mode_model, budget)
        interactions = self._find_interactions(scope_model)
        counts = await self._ensure_artifacts(
            interactions,
            required,
            mode_model,
            force_retry_failed=force_retry_failed,
            budget=budget,
        )
        source_quota_blocked = int(source_counts.pop("quota_blocked", 0) or 0)
        counts["quota_blocked"] = int(counts.get("quota_blocked", 0) or 0) + source_quota_blocked
        counts["provider_calls_made"] = int(counts.get("provider_calls_made", 0)) + int(
            source_counts.pop("provider_calls_made", 0)
        )
        counts.update(source_counts)
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
            quota=self._quota_summary(counts, mode_model, budget),
        )

    def _normalize_required_artifacts(
        self,
        required_artifacts: list[RequiredArtifactKind | ArtifactKind | str] | None,
    ) -> list[RequiredArtifactKind]:
        if not required_artifacts:
            return []
        normalized = [RequiredArtifactKind(str(item.value if hasattr(item, "value") else item)) for item in required_artifacts]
        order = {
            RequiredArtifactKind.TRANSCRIPT: 0,
            RequiredArtifactKind.TRANSCRIPT_SEGMENTS: 1,
            RequiredArtifactKind.LLM1_FIRST_PASS: 2,
        }
        return sorted(set(normalized), key=lambda item: order[item])

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

    def _discover_and_persist_source_calls(
        self,
        scope: ProcessingScope,
        mode: EnsureMode,
        budget: ProviderCallBudget,
    ) -> dict[str, int]:
        """Discover OnlinePBX source calls for the scope when the session supports it."""
        counts = {
            "source_days_scanned": 0,
            "source_records_total": 0,
            "source_targeted_total": 0,
            "source_ingest_created": 0,
            "source_ingest_skipped": 0,
            "source_provider_calls_made": 0,
            "provider_calls_made": 0,
            "quota_blocked": 0,
        }
        if mode is EnsureMode.DRY_RUN or not scope.department_id or not hasattr(self.session, "query"):
            return counts
        intake = self._build_intake(scope.department_id)
        for day in self._iter_period_days(scope):
            if not budget.try_spend():
                budget.mark_blocked(counts)
                break
            counts["source_days_scanned"] += 1
            records = intake.get_cdr_list(day.isoformat())
            counts["source_provider_calls_made"] += 1
            counts["provider_calls_made"] += 1
            counts["source_records_total"] += len(records)
            targeted = [
                record
                for record in records
                if self._record_matches_scope(record, scope)
                and self._record_matches_filters(record, scope)
            ]
            counts["source_targeted_total"] += len(targeted)
            for record in targeted:
                if self._record_is_build_eligible(intake, record) and not getattr(record, "record_url", None):
                    if not budget.try_spend():
                        budget.mark_blocked(counts)
                        break
                    record.record_url = intake.get_recording_url(record.call_id)
                    counts["source_provider_calls_made"] += 1
                    counts["provider_calls_made"] += 1
            if budget.blocked:
                break
            created, skipped = intake.save_interactions(targeted)
            counts["source_ingest_created"] += created
            counts["source_ingest_skipped"] += skipped
        return counts

    @staticmethod
    def _iter_period_days(scope: ProcessingScope) -> list[date]:
        current = scope.date_from
        days: list[date] = []
        while current <= scope.date_to:
            days.append(current)
            current += timedelta(days=1)
        return days

    @staticmethod
    def _record_matches_scope(record: Any, scope: ProcessingScope) -> bool:
        if scope.extensions:
            extension = str(getattr(record, "extension", "") or "").strip()
            if extension not in set(scope.extensions):
                return False
        return True

    @staticmethod
    def _record_matches_filters(record: Any, scope: ProcessingScope) -> bool:
        talk_duration = int(getattr(record, "talk_duration", 0) or 0)
        if scope.min_duration_sec is not None and talk_duration < scope.min_duration_sec:
            return False
        if scope.max_duration_sec is not None and talk_duration > scope.max_duration_sec:
            return False
        return True

    @staticmethod
    def _record_is_build_eligible(intake: Any, record: Any) -> bool:
        config = getattr(intake, "config", None)
        allowed_statuses = set(getattr(config, "allowed_statuses", []) or [])
        allowed_directions = set(getattr(config, "allowed_directions", []) or [])
        status = str(getattr(record, "status", "") or "")
        direction = str(getattr(record, "direction", "") or "")
        if allowed_statuses and status not in allowed_statuses:
            return False
        if allowed_directions and direction not in allowed_directions:
            return False
        return True

    def _build_intake(self, department_id: str) -> Any:
        if self.intake_factory is not None:
            return self.intake_factory(department_id, self.session)
        from app.agents.calls.intake import OnlinePBXIntake

        return OnlinePBXIntake(department_id=department_id, db=self.session)

    def _build_extractor(self, department_id: str) -> Any:
        if self.extractor_factory is not None:
            return self.extractor_factory(department_id, self.session)
        from app.agents.calls.extractor import CallsExtractor

        return CallsExtractor(department_id=department_id, db=self.session)

    def _build_analyzer(self, department_id: str) -> Any:
        if self.analyzer_factory is not None:
            return self.analyzer_factory(department_id, self.session)
        from app.agents.calls.analyzer import CallsAnalyzer

        return CallsAnalyzer(department_id=department_id, db=self.session)

    async def _ensure_artifacts(
        self,
        interactions: list[Interaction],
        required: list[RequiredArtifactKind],
        mode: EnsureMode,
        *,
        force_retry_failed: bool = False,
        budget: ProviderCallBudget | None = None,
    ) -> dict[str, int]:
        budget = budget or ProviderCallBudget()
        counts = {
            "interactions_total": len(interactions),
            "artifact_requirements_total": len(interactions) * len(required),
            "artifacts_ready": 0,
            "artifacts_missing": 0,
            "artifacts_backfilled": 0,
            "provider_calls_planned": 0,
            "provider_calls_made": 0,
            "transcripts_built": 0,
            "llm1_first_pass_built": 0,
            "artifact_build_failed": 0,
            "artifact_retry_blocked": 0,
            "quota_blocked": 0,
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
                if (
                    artifact is not None
                    and artifact.status == ArtifactStatus.FAILED.value
                    and not force_retry_failed
                    and not bool(getattr(artifact, "retryable", False))
                ):
                    counts["artifacts_missing"] += 1
                    counts["artifact_retry_blocked"] += 1
                    continue

                backfilled = self._backfill_from_legacy(interaction, kind, mode)
                if backfilled:
                    counts["artifacts_ready"] += 1
                    counts["artifacts_backfilled"] += 1
                    continue

                if kind is RequiredArtifactKind.TRANSCRIPT:
                    counts["provider_calls_planned"] += 1
                    if (
                        mode is not EnsureMode.DRY_RUN
                        and self._transcript_provider_input_available(interaction)
                        and not budget.try_spend()
                    ):
                        budget.mark_blocked(counts)
                        counts["artifacts_missing"] += 1
                        continue
                    if mode is not EnsureMode.DRY_RUN:
                        built = await self._build_transcript_artifacts(interaction)
                        if built:
                            counts["artifacts_ready"] += 1
                            counts["transcripts_built"] += 1
                            counts["provider_calls_made"] += 1
                            continue
                    counts["artifacts_missing"] += 1
                    continue

                if kind is RequiredArtifactKind.TRANSCRIPT_SEGMENTS:
                    counts["artifacts_missing"] += 1
                    continue

                if kind is RequiredArtifactKind.LLM1_FIRST_PASS:
                    counts["provider_calls_planned"] += 1
                    if (
                        mode is not EnsureMode.DRY_RUN
                        and self._llm1_provider_input_available(interaction)
                        and not budget.try_spend()
                    ):
                        budget.mark_blocked(counts)
                        counts["artifacts_missing"] += 1
                        continue
                    if mode is not EnsureMode.DRY_RUN:
                        built = self._build_llm1_first_pass_artifact(interaction)
                        if built:
                            counts["artifacts_ready"] += 1
                            counts["llm1_first_pass_built"] += 1
                            counts["provider_calls_made"] += 1
                            continue
                    counts["artifacts_missing"] += 1
                    continue

                counts["artifacts_missing"] += 1
        return counts

    def _plan_and_backfill(
        self,
        interactions: list[Interaction],
        required: list[RequiredArtifactKind],
        mode: EnsureMode,
    ) -> dict[str, int]:
        """Compatibility wrapper for older unit tests."""
        return asyncio.run(self._ensure_artifacts(interactions, required, mode))

    @staticmethod
    def _transcript_provider_input_available(interaction: Interaction) -> bool:
        return bool(str(getattr(interaction, "raw_ref", "") or "").strip()) and bool(
            str(getattr(interaction, "department_id", "") or "").strip()
        )

    @staticmethod
    def _llm1_provider_input_available(interaction: Interaction) -> bool:
        return bool(str(getattr(interaction, "text", "") or "").strip()) and bool(
            str(getattr(interaction, "department_id", "") or "").strip()
        )

    async def _build_transcript_artifacts(self, interaction: Interaction) -> bool:
        """Run STT for one interaction and persist transcript artifacts."""
        if not str(getattr(interaction, "raw_ref", "") or "").strip():
            return False
        department_id = str(getattr(interaction, "department_id", "") or "")
        if not department_id:
            return False
        try:
            extractor = self._build_extractor(department_id)
            result = await extractor.process(interaction)
        except Exception as exc:
            self._write_failed_artifact(
                interaction=interaction,
                kind=ArtifactKind.TRANSCRIPT,
                error_class=ProcessingErrorClass.UNKNOWN_ERROR,
                error_reason=str(exc),
            )
            return False

        now = datetime.now(UTC)
        self.artifacts.write_active(
            department_id=interaction.department_id,
            interaction_id=interaction.id,
            artifact_kind=ArtifactKind.TRANSCRIPT,
            artifact_version=DEFAULT_ARTIFACT_VERSIONS[ArtifactKind.TRANSCRIPT.value],
            status=ArtifactStatus.READY,
            payload_json={
                "created_by": "call_processing_service",
                "duration_sec": result.duration_sec,
                "confidence": result.confidence,
            },
            text_value=result.full_text,
            source_updated_at=now,
            **self._artifact_provider_fields(interaction, layer="stt"),
        )
        if result.segments:
            self.artifacts.write_active(
                department_id=interaction.department_id,
                interaction_id=interaction.id,
                artifact_kind=ArtifactKind.TRANSCRIPT_SEGMENTS,
                artifact_version=DEFAULT_ARTIFACT_VERSIONS[ArtifactKind.TRANSCRIPT_SEGMENTS.value],
                status=ArtifactStatus.READY,
                payload_json={
                    "created_by": "call_processing_service",
                    "segments": [segment.model_dump() for segment in result.segments],
                },
                source_updated_at=now,
                **self._artifact_provider_fields(interaction, layer="stt"),
            )
        return bool(str(result.full_text or "").strip())

    def _build_llm1_first_pass_artifact(self, interaction: Interaction) -> bool:
        """Run only LLM1 first-pass and persist its versioned artifact."""
        if not str(getattr(interaction, "text", "") or "").strip():
            return False
        department_id = str(getattr(interaction, "department_id", "") or "")
        if not department_id:
            return False
        instruction_version = "edo_sales_mvp1_call_analysis_v15_block_ready"
        try:
            analyzer = self._build_analyzer(department_id)
            normalized = analyzer._request_llm1_first_pass(
                interaction=interaction,
                instruction_version=instruction_version,
            )
        except Exception as exc:
            self._write_failed_artifact(
                interaction=interaction,
                kind=ArtifactKind.LLM1_FIRST_PASS,
                error_class=ProcessingErrorClass.UNKNOWN_ERROR,
                error_reason=str(exc),
            )
            return False

        provider_fields = self._artifact_provider_fields(interaction, layer="llm1")
        payload = LLM1FirstPassPayload(
            prompt_version=f"{instruction_version}:llm1",
            provider=provider_fields.get("provider") or "unknown",
            model=provider_fields.get("model") or "unknown",
            account_alias=provider_fields.get("account_alias"),
            classification=dict(normalized.get("classification") or {}),
            summary=dict(normalized.get("summary") or {}),
            follow_up=dict(normalized.get("follow_up") or {}),
            data_quality=dict(normalized.get("data_quality") or {}),
            analysis_focus=normalized.get("analysis_focus") or {},
        )
        self.artifacts.write_active(
            department_id=interaction.department_id,
            interaction_id=interaction.id,
            artifact_kind=ArtifactKind.LLM1_FIRST_PASS,
            artifact_version=DEFAULT_ARTIFACT_VERSIONS[ArtifactKind.LLM1_FIRST_PASS.value],
            status=ArtifactStatus.READY,
            payload_json=payload.model_dump(mode="json"),
            source_updated_at=datetime.now(UTC),
            **provider_fields,
        )
        return True

    def _write_failed_artifact(
        self,
        *,
        interaction: Interaction,
        kind: ArtifactKind,
        error_class: ProcessingErrorClass,
        error_reason: str,
    ) -> None:
        """Persist failed artifact diagnostics for admin retry/reconciliation."""
        self.artifacts.write_active(
            department_id=interaction.department_id,
            interaction_id=interaction.id,
            artifact_kind=kind,
            artifact_version=DEFAULT_ARTIFACT_VERSIONS[kind.value],
            status=ArtifactStatus.FAILED,
            payload_json={"created_by": "call_processing_service"},
            error_class=error_class.value,
            error_reason=error_reason[:1000],
            retryable=is_retryable_error(error_class),
            source_updated_at=datetime.now(UTC),
        )

    @staticmethod
    def _artifact_provider_fields(interaction: Interaction, *, layer: str) -> dict[str, Any]:
        """Extract provider/model metadata written by existing STT/LLM routing."""
        metadata = getattr(interaction, "metadata_", None) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        ai_routing = metadata.get("ai_routing")
        if not isinstance(ai_routing, dict):
            return {}
        layer_meta = ai_routing.get(layer)
        if not isinstance(layer_meta, dict):
            return {}
        return {
            "provider": layer_meta.get("provider"),
            "model": layer_meta.get("model"),
            "account_alias": layer_meta.get("account_alias"),
            "api_key_env": layer_meta.get("api_key_env"),
            "raw_response_ref": layer_meta.get("provider_request_id"),
        }

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
        if int(counts.get("quota_blocked", 0) or 0) > 0:
            return ProcessingRunStatus.BLOCKED
        if counts["artifact_requirements_total"] == 0:
            return ProcessingRunStatus.READY
        if counts["artifacts_missing"] == 0:
            return ProcessingRunStatus.READY
        if counts["artifacts_ready"] > 0:
            return ProcessingRunStatus.PARTIAL
        return ProcessingRunStatus.BLOCKED

    def _quota_summary(
        self,
        counts: dict[str, Any],
        mode: EnsureMode,
        budget: ProviderCallBudget,
    ) -> dict[str, Any]:
        exhausted = int(counts.get("quota_blocked", 0) or 0) > 0
        summary: dict[str, Any] = {
            "provider_calls_made": counts.get("provider_calls_made", 0),
            "provider_calls_planned": counts.get("provider_calls_planned", 0),
            "provider_calls_allowed": mode is not EnsureMode.DRY_RUN and not exhausted,
            "provider_call_budget": budget.limit,
            "provider_calls_remaining": budget.remaining,
            "quota_exhausted": exhausted,
        }
        if exhausted:
            summary.update(
                {
                    "error_class": ProcessingErrorClass.QUOTA_INSUFFICIENT.value,
                    "admin_action_required": "increase_provider_call_budget_or_retry_after_provider_quota_reset",
                }
            )
        return summary

    def _commit_if_available(self) -> None:
        commit = getattr(self.session, "commit", None)
        if callable(commit):
            commit()
