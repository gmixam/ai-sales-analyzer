"""Planning-oriented call-processing domain service."""

from __future__ import annotations

import asyncio
import inspect
import math
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
NO_AUDIO_INTERACTION_STATUS = "NO_AUDIO"


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
        source_counts = self._discover_and_persist_source_calls(scope_model, required, mode_model, budget)
        interactions = [] if budget.blocked and self._scope_mode(scope_model) == "company" else self._find_interactions(scope_model)
        cost_entries: list[dict[str, Any]] = []
        counts = await self._ensure_artifacts(
            interactions,
            required,
            mode_model,
            force_retry_failed=force_retry_failed,
            budget=budget,
            cost_entries=cost_entries,
        )
        source_quota_blocked = int(source_counts.pop("quota_blocked", 0) or 0)
        counts["quota_blocked"] = int(counts.get("quota_blocked", 0) or 0) + source_quota_blocked
        counts["provider_calls_made"] = int(counts.get("provider_calls_made", 0)) + int(
            source_counts.pop("provider_calls_made", 0)
        )
        counts.update(source_counts)
        costs = self._estimate_upstream_costs(cost_entries, counts, mode_model)
        self._add_budget_summary_fields(counts, costs, budget)
        status = self._status_from_counts(counts)

        self.runs.update_status(
            run,
            status,
            counts_json={**counts, "costs": costs},
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
            costs=costs,
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
        if self._scope_mode(scope) in {"company", "department"} and not scope.extensions:
            return []
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
            if self._interaction_requires_artifacts(interaction)
            and self._interaction_matches_scope(interaction, scope)
        ]

    @staticmethod
    def _interaction_requires_artifacts(interaction: Interaction) -> bool:
        status = str(getattr(interaction, "status", "") or "").strip().upper()
        return status != NO_AUDIO_INTERACTION_STATUS

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
        required: list[RequiredArtifactKind],
        mode: EnsureMode,
        budget: ProviderCallBudget,
    ) -> dict[str, Any]:
        """Discover OnlinePBX source calls for the scope when the session supports it."""
        counts = {
            "scope_mode": self._scope_mode(scope),
            "scope_manager_count": scope.scope_manager_count
            if scope.scope_manager_count is not None
            else len(set(scope.manager_ids)),
            "scope_extension_count": scope.scope_extension_count
            if scope.scope_extension_count is not None
            else len(set(scope.extensions)),
            "scope_department_count": self._scope_department_count(scope),
            "scope_diagnostics": list(scope.scope_diagnostics),
            "source_days_scanned": 0,
            "source_records_total": 0,
            "source_targeted_total": 0,
            "source_readonly_cdr_calls": 0,
            "source_ingest_created": 0,
            "source_ingest_skipped": 0,
            "source_provider_calls_made": 0,
            "provider_calls_made": 0,
            "quota_blocked": 0,
            "eligible_audio_calls": 0,
            "eligible_audio_calls_with_record_url": 0,
            "eligible_audio_calls_missing_record_url": 0,
            "no_audio_calls": 0,
            "missed_calls": 0,
            "zero_talk_calls": 0,
            "billable_minutes_estimate": 0,
        }
        fallback_department_id = scope.department_id or scope.fallback_department_id
        if not fallback_department_id:
            counts["scope_diagnostics"].append("fallback_department_not_configured")
            return counts
        if self._scope_mode(scope) in {"company", "department"} and not scope.extensions:
            counts["scope_diagnostics"].append("scope_extensions_empty")
            return counts
        if not hasattr(self.session, "query"):
            counts["scope_diagnostics"].append("manager_directory_or_source_session_unavailable")
            return counts
        intake = self._build_intake(fallback_department_id, scope=scope)
        scope_mode = self._scope_mode(scope)
        company_targeted: list[list[Any]] = []
        for day in self._iter_period_days(scope):
            if mode is not EnsureMode.DRY_RUN:
                if not budget.try_spend():
                    budget.mark_blocked(counts)
                    break
            counts["source_days_scanned"] += 1
            records = intake.get_cdr_list(day.isoformat())
            if mode is EnsureMode.DRY_RUN:
                counts["source_readonly_cdr_calls"] += 1
            else:
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
            self._add_source_forecast_counts(counts, targeted, intake)
            if mode is EnsureMode.DRY_RUN:
                continue
            if scope_mode == "company":
                company_targeted.append(targeted)
                continue
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
        self._add_provider_call_budget_fields(counts, required, budget)
        if mode is not EnsureMode.DRY_RUN and scope_mode == "company" and not budget.blocked:
            if self._provider_call_estimate_exceeds_budget(counts, budget):
                budget.mark_blocked(counts)
                self._mark_company_budget_blocker(counts)
                self._add_provider_call_budget_fields(counts, required, budget)
                return counts
            for targeted in company_targeted:
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
    def _scope_mode(scope: ProcessingScope) -> str:
        return str(scope.scope_mode or "managers").strip().lower() or "managers"

    @staticmethod
    def _scope_department_count(scope: ProcessingScope) -> int:
        if scope.scope_department_count is not None:
            return scope.scope_department_count
        departments = {
            value
            for value in (scope.department_id, scope.fallback_department_id)
            if str(value or "").strip()
        }
        return len(departments)

    def _add_source_forecast_counts(
        self,
        counts: dict[str, Any],
        records: list[Any],
        intake: Any,
    ) -> None:
        for record in records:
            talk_duration = int(getattr(record, "talk_duration", 0) or 0)
            status = str(getattr(record, "status", "") or "").strip().lower()
            if status == "missed":
                counts["missed_calls"] += 1
            if talk_duration <= 0:
                counts["zero_talk_calls"] += 1
            if self._record_is_build_eligible(intake, record):
                counts["eligible_audio_calls"] += 1
                if getattr(record, "record_url", None):
                    counts["eligible_audio_calls_with_record_url"] += 1
                else:
                    counts["eligible_audio_calls_missing_record_url"] += 1
                counts["eligible_audio_duration_sec"] = int(
                    counts.get("eligible_audio_duration_sec", 0)
                ) + talk_duration
                counts["billable_minutes_estimate"] += math.ceil(talk_duration / 60)
            else:
                counts["no_audio_calls"] += 1

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
    def _add_provider_call_budget_fields(
        counts: dict[str, Any],
        required: list[RequiredArtifactKind],
        budget: ProviderCallBudget,
    ) -> None:
        estimate = CallProcessingService._provider_calls_estimate(counts, required)
        counts["provider_calls_estimate"] = estimate
        counts["provider_calls_budget"] = budget.limit
        counts["provider_calls_budget_status"] = CallProcessingService._provider_calls_budget_status(
            estimate,
            budget.limit,
        )

    @staticmethod
    def _provider_calls_estimate(
        counts: dict[str, Any],
        required: list[RequiredArtifactKind],
    ) -> int:
        required_set = set(required)
        eligible = int(counts.get("eligible_audio_calls") or 0)
        cdr_requests = int(counts.get("source_days_scanned") or 0)
        recording_url_requests = int(counts.get("eligible_audio_calls_missing_record_url") or 0)
        transcript_requests = eligible if (
            RequiredArtifactKind.TRANSCRIPT in required_set
            or RequiredArtifactKind.TRANSCRIPT_SEGMENTS in required_set
        ) else 0
        llm1_requests = eligible if RequiredArtifactKind.LLM1_FIRST_PASS in required_set else 0
        counts["provider_calls_estimate_cdr"] = cdr_requests
        counts["provider_calls_estimate_recording_url"] = recording_url_requests
        counts["provider_calls_estimate_stt"] = transcript_requests
        counts["provider_calls_estimate_llm1"] = llm1_requests
        return cdr_requests + recording_url_requests + transcript_requests + llm1_requests

    @staticmethod
    def _provider_calls_budget_status(estimate: int, limit: int | None) -> str:
        if limit is not None and limit <= 0:
            return "no_budget_configured"
        if estimate <= 0:
            return "within_budget"
        if limit is None:
            return "no_budget_configured"
        if estimate > limit:
            return "over_budget"
        if estimate >= max(math.ceil(limit * 0.8), 1):
            return "warning"
        return "within_budget"

    @staticmethod
    def _provider_call_estimate_exceeds_budget(
        counts: dict[str, Any],
        budget: ProviderCallBudget,
    ) -> bool:
        estimate = int(counts.get("provider_calls_estimate") or 0)
        return estimate > 0 and budget.limit is not None and estimate > budget.limit

    @staticmethod
    def _mark_company_budget_blocker(counts: dict[str, Any]) -> None:
        counts.update(
            {
                "provider_calls_budget_status": "over_budget",
                "forecast_budget_status": "over_budget",
                "reason": "provider_calls_budget_insufficient",
                "error_class": ProcessingErrorClass.QUOTA_INSUFFICIENT.value,
                "admin_action_required": "increase_provider_call_budget_or_run_smaller_scope",
            }
        )

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
        talk_duration = int(getattr(record, "talk_duration", 0) or 0)
        if talk_duration <= 0:
            return False
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

    def _build_intake(self, department_id: str, *, scope: ProcessingScope | None = None) -> Any:
        if self.intake_factory is not None:
            intake = self.intake_factory(department_id, self.session)
            if scope is not None:
                setattr(intake, "company_wide_mapping", self._scope_mode(scope) == "company")
            return intake
        from app.agents.calls.intake import OnlinePBXIntake

        return OnlinePBXIntake(
            department_id=department_id,
            db=self.session,
            company_wide_mapping=scope is not None and self._scope_mode(scope) == "company",
        )

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
        cost_entries: list[dict[str, Any]] | None = None,
    ) -> dict[str, int]:
        budget = budget or ProviderCallBudget()
        artifact_interactions = [
            interaction
            for interaction in interactions
            if self._interaction_requires_artifacts(interaction)
        ]
        counts = {
            "interactions_total": len(artifact_interactions),
            "interactions_skipped_no_audio": len(interactions) - len(artifact_interactions),
            "artifact_requirements_total": len(artifact_interactions) * len(required),
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
        for interaction in artifact_interactions:
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
                            if cost_entries is not None:
                                cost_entries.append(built)
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
                            if cost_entries is not None:
                                cost_entries.append(built)
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

    async def _build_transcript_artifacts(self, interaction: Interaction) -> dict[str, Any] | None:
        """Run STT for one interaction and persist transcript artifacts."""
        if not str(getattr(interaction, "raw_ref", "") or "").strip():
            return None
        department_id = str(getattr(interaction, "department_id", "") or "")
        if not department_id:
            return None
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
            return None

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
                "speaker_a_is_manager": result.speaker_a_is_manager,
                "diarization": dict(result.diarization_metadata or {}),
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
                    "speaker_a_is_manager": result.speaker_a_is_manager,
                    "diarization": dict(result.diarization_metadata or {}),
                },
                source_updated_at=now,
                **self._artifact_provider_fields(interaction, layer="stt"),
            )
        if not str(result.full_text or "").strip():
            return None
        return self._execution_entry(
            interaction,
            layer="stt",
            request_kind="speech_to_text",
            duration_sec=result.duration_sec,
        )

    def _build_llm1_first_pass_artifact(self, interaction: Interaction) -> dict[str, Any] | None:
        """Run only LLM1 first-pass and persist its versioned artifact."""
        if not str(getattr(interaction, "text", "") or "").strip():
            return None
        department_id = str(getattr(interaction, "department_id", "") or "")
        if not department_id:
            return None
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
            return None

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
            speaker_role_mapping=dict(normalized.get("speaker_role_mapping") or {}),
            call_card=dict(normalized.get("call_card") or {}),
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
        return self._execution_entry(
            interaction,
            layer="llm1",
            request_kind="llm1_first_pass",
        )

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
        layer_meta = CallProcessingService._route_metadata(interaction, layer=layer)
        if not layer_meta:
            return {}
        return {
            "provider": layer_meta.get("provider") or layer_meta.get("selected_provider"),
            "model": layer_meta.get("model") or layer_meta.get("selected_model"),
            "account_alias": layer_meta.get("account_alias"),
            "api_key_env": layer_meta.get("api_key_env"),
            "raw_response_ref": layer_meta.get("provider_request_id"),
        }

    @staticmethod
    def _route_metadata(interaction: Interaction, *, layer: str) -> dict[str, Any]:
        metadata = getattr(interaction, "metadata_", None) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        ai_routing = metadata.get("ai_routing")
        if not isinstance(ai_routing, dict):
            return {}
        layer_meta = ai_routing.get(layer)
        return dict(layer_meta) if isinstance(layer_meta, dict) else {}

    def _execution_entry(
        self,
        interaction: Interaction,
        *,
        layer: str,
        request_kind: str,
        duration_sec: int | None = None,
    ) -> dict[str, Any]:
        route = self._route_metadata(interaction, layer=layer)
        usage = route.get("usage") if isinstance(route.get("usage"), dict) else {}
        provider = route.get("provider") or route.get("selected_provider")
        model = route.get("model") or route.get("selected_model")
        if duration_sec is not None:
            usage = {**usage, "duration_sec": duration_sec}
        return {
            "layer": layer,
            "node": layer,
            "request_kind": route.get("request_kind") or request_kind,
            "subject_key": str(getattr(interaction, "id", "") or ""),
            "provider": provider,
            "model": model,
            "selected_provider": provider,
            "selected_model": model,
            "account_alias": route.get("account_alias"),
            "api_key_env": route.get("api_key_env"),
            "provider_request_id": route.get("provider_request_id"),
            "usage": usage or None,
            "duration_sec": duration_sec or usage.get("duration_sec"),
        }

    def _estimate_upstream_costs(
        self,
        cost_entries: list[dict[str, Any]],
        counts: dict[str, Any],
        mode: EnsureMode,
    ) -> dict[str, Any]:
        if mode is EnsureMode.DRY_RUN and int(counts.get("source_readonly_cdr_calls") or 0) > 0:
            return self._forecast_upstream_costs(counts)
        helper = self._call_processing_cost_helper()
        if helper is not None:
            return self._call_processing_costs_from_helper(
                helper,
                execution_entries=cost_entries,
                counts=counts,
                mode=mode,
            )
        return self._fallback_upstream_costs(cost_entries, counts)

    def _forecast_upstream_costs(self, counts: dict[str, Any]) -> dict[str, Any]:
        eligible = int(counts.get("eligible_audio_calls") or 0)
        total_duration_sec = int(counts.get("eligible_audio_duration_sec") or 0)
        if eligible <= 0:
            costs = self._fallback_upstream_costs([], counts)
            costs["forecast"] = True
            costs["forecast_billable_minutes"] = counts.get("billable_minutes_estimate", 0)
            return costs

        stt_provider, stt_model, llm1_provider, llm1_model = self._forecast_provider_models()
        execution_entries = [
            {
                "layer": "stt",
                "request_kind": "speech_to_text",
                "subject_key": "forecast:stt",
                "provider": stt_provider,
                "model": stt_model,
                "duration_sec": total_duration_sec,
                "usage": {
                    "duration_sec": total_duration_sec,
                    "billable_minutes": counts.get("billable_minutes_estimate", 0),
                },
            },
            {
                "layer": "llm1",
                "request_kind": "llm1_first_pass",
                "subject_key": "forecast:llm1",
                "provider": llm1_provider,
                "model": llm1_model,
            },
        ]
        planned = {
            **counts,
            "transcripts_built": eligible,
            "llm1_first_pass_built": eligible,
        }
        helper = self._call_processing_cost_helper()
        if helper is not None:
            costs = helper(
                execution_entries=execution_entries,
                planned=planned,
                mode="forecast",
            )
        else:
            costs = self._fallback_upstream_costs(execution_entries, planned)
        costs["forecast"] = True
        costs["forecast_billable_minutes"] = counts.get("billable_minutes_estimate", 0)
        costs.setdefault("notes", [])
        costs["notes"] = [
            *list(costs.get("notes") or []),
            "Dry-run forecast uses read-only CDR duration and does not fetch recording URLs or run STT/LLM1.",
            "LLM1 forecast has no token usage before execution; cost may be usage_missing.",
        ]
        return costs

    @staticmethod
    def _add_budget_summary_fields(
        counts: dict[str, Any],
        costs: dict[str, Any],
        budget: ProviderCallBudget,
    ) -> None:
        estimate = int(counts.get("provider_calls_estimate") or 0)
        provider_budget_status = str(
            counts.get("provider_calls_budget_status")
            or CallProcessingService._provider_calls_budget_status(estimate, budget.limit)
        )
        forecast_budget_status = CallProcessingService._forecast_budget_status(
            provider_budget_status=provider_budget_status,
            cost_status=str(costs.get("cost_status") or ""),
        )
        forecast_cost = costs.get("total_current_run_cost_usdt")
        forecast_minutes = costs.get("forecast_billable_minutes", counts.get("billable_minutes_estimate", 0))

        summary_fields = {
            "provider_calls_estimate": estimate,
            "provider_calls_budget": budget.limit,
            "provider_calls_budget_status": provider_budget_status,
            "forecast_budget_status": forecast_budget_status,
            "forecast_cost_usdt": forecast_cost,
            "forecast_billable_minutes": forecast_minutes,
            "budget_status": forecast_budget_status,
        }
        counts.update(summary_fields)
        costs.update(summary_fields)
        costs["provider_calls_made"] = counts.get("provider_calls_made", 0)
        if int(counts.get("quota_blocked", 0) or 0) > 0:
            counts.setdefault(
                "admin_action_required",
                "increase_provider_call_budget_or_retry_after_provider_quota_reset",
            )
            counts.setdefault("error_class", ProcessingErrorClass.QUOTA_INSUFFICIENT.value)

    @staticmethod
    def _forecast_budget_status(*, provider_budget_status: str, cost_status: str) -> str:
        if provider_budget_status in {"over_budget", "warning", "no_budget_configured"}:
            return provider_budget_status
        if cost_status == "price_missing":
            return "price_missing"
        if cost_status == "usage_missing":
            return "usage_missing"
        if cost_status == "partial":
            return "warning"
        return "within_budget"

    @staticmethod
    def _forecast_provider_models() -> tuple[str, str, str, str]:
        try:
            from app.core_shared.config.settings import settings
        except Exception:
            return "unknown", "unknown", "unknown", "unknown"
        stt_provider = str(getattr(settings, "stt_provider", "") or "unknown").strip().lower()
        if stt_provider == "openai":
            stt_model = str(getattr(settings, "openai_model_stt", "") or "whisper-1")
        elif stt_provider == "assemblyai":
            stt_model = "assemblyai_default"
        else:
            stt_model = stt_provider or "unknown"
        llm1_provider = "openai"
        llm1_model = str(getattr(settings, "openai_model_classify", "") or "unknown")
        return stt_provider or "unknown", stt_model, llm1_provider, llm1_model

    @staticmethod
    def _call_processing_cost_helper() -> Callable[..., dict[str, Any]] | None:
        try:
            from app.agents.calls import ai_costs
        except Exception:
            return None
        helper = getattr(ai_costs, "estimate_call_processing_costs", None)
        return helper if callable(helper) else None

    @staticmethod
    def _call_processing_costs_from_helper(
        helper: Callable[..., dict[str, Any]],
        *,
        execution_entries: list[dict[str, Any]],
        counts: dict[str, Any],
        mode: EnsureMode,
    ) -> dict[str, Any]:
        signature = inspect.signature(helper)
        parameters = signature.parameters
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        kwargs: dict[str, Any] = {"execution_entries": execution_entries}
        if accepts_kwargs or "planned" in parameters:
            kwargs["planned"] = counts
        if accepts_kwargs or "counts" in parameters:
            kwargs["counts"] = counts
        if accepts_kwargs or "mode" in parameters:
            kwargs["mode"] = mode.value
        return helper(**kwargs)

    @staticmethod
    def _fallback_upstream_costs(
        cost_entries: list[dict[str, Any]],
        counts: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            from app.agents.calls.ai_costs import (
                PRICING_CATALOG_VERSION,
                PRICING_CURRENCY,
                USD_TO_USDT_RATE,
            )
        except Exception:
            PRICING_CATALOG_VERSION = "unknown"
            PRICING_CURRENCY = "USDT"
            USD_TO_USDT_RATE = 1.0

        by_layer = [
            CallProcessingService._fallback_cost_entry(entry)
            for entry in cost_entries
        ]
        total = round(
            sum(
                float(entry["current_run_cost_usdt"])
                for entry in by_layer
                if entry.get("current_run_cost_usdt") is not None
            ),
            6,
        )
        transcribed = int(counts.get("transcripts_built") or 0)
        return {
            "schema_version": "split_upstream_ai_costs_v1",
            "pricing_catalog_version": PRICING_CATALOG_VERSION,
            "currency": PRICING_CURRENCY,
            "usd_to_usdt_rate": USD_TO_USDT_RATE,
            "cost_status": CallProcessingService._fallback_cost_status(by_layer),
            "stt_cost_usdt": CallProcessingService._fallback_layer_total(by_layer, "stt"),
            "llm1_cost_usdt": CallProcessingService._fallback_layer_total(by_layer, "llm1"),
            "total_current_run_cost_usdt": total,
            "reused_artifact_original_cost_usdt": None,
            "cost_per_transcribed_call_usdt": round(total / transcribed, 6) if transcribed else None,
            "by_layer": by_layer,
            "by_request_kind": CallProcessingService._fallback_by_request_kind(by_layer),
            "notes": [
                "Reused, dry-run, and backfilled artifacts do not add current-run cost.",
                "Call-processing cost helper is not installed yet; "
                "upstream provider executions are reported without price calculation.",
            ],
        }

    @staticmethod
    def _fallback_cost_entry(entry: dict[str, Any]) -> dict[str, Any]:
        usage = entry.get("usage") if isinstance(entry.get("usage"), dict) else None
        has_usage = bool(usage)
        cost_status = "price_missing" if has_usage else "usage_missing"
        return {
            "layer": entry.get("layer"),
            "node": entry.get("node") or entry.get("layer"),
            "request_kind": entry.get("request_kind"),
            "subject_key": entry.get("subject_key"),
            "provider": entry.get("provider") or entry.get("selected_provider"),
            "model": entry.get("model") or entry.get("selected_model"),
            "used": True,
            "used_count": 1,
            "cost_status": cost_status,
            "current_run_cost_usdt": None,
            "tokens": usage if entry.get("layer") == "llm1" else None,
            "duration_sec": entry.get("duration_sec") or (usage or {}).get("duration_sec"),
            "billable_minutes": None,
            "pricing": None,
            "provider_request_id": entry.get("provider_request_id"),
        }

    @staticmethod
    def _fallback_cost_status(entries: list[dict[str, Any]]) -> str:
        if not entries:
            return "no_billable_work"
        statuses = {str(entry.get("cost_status") or "") for entry in entries}
        if statuses <= {"available"}:
            return "available"
        if "available" in statuses:
            return "partial"
        if "usage_missing" in statuses:
            return "usage_missing"
        return "price_missing"

    @staticmethod
    def _fallback_layer_total(entries: list[dict[str, Any]], layer: str) -> float | None:
        selected = [
            entry
            for entry in entries
            if entry.get("layer") == layer and entry.get("current_run_cost_usdt") is not None
        ]
        if selected:
            return round(
                sum(float(entry.get("current_run_cost_usdt") or 0) for entry in selected),
                6,
            )
        return None if any(entry.get("layer") == layer for entry in entries) else 0.0

    @staticmethod
    def _fallback_by_request_kind(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for entry in entries:
            key = (
                str(entry.get("layer") or ""),
                str(entry.get("request_kind") or entry.get("node") or "unknown"),
            )
            bucket = grouped.setdefault(
                key,
                {
                    "layer": key[0],
                    "request_kind": key[1],
                    "used_count": 0,
                    "current_run_cost_usdt": 0.0,
                    "cost_statuses": [],
                },
            )
            bucket["used_count"] += int(entry.get("used_count") or 0)
            status = entry.get("cost_status")
            if status and status not in bucket["cost_statuses"]:
                bucket["cost_statuses"].append(status)
        return list(grouped.values())

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
            "provider_calls_estimate": counts.get("provider_calls_estimate", 0),
            "provider_calls_budget": counts.get("provider_calls_budget", budget.limit),
            "provider_calls_budget_status": counts.get("provider_calls_budget_status"),
            "forecast_budget_status": counts.get("forecast_budget_status"),
            "provider_calls_allowed": mode is not EnsureMode.DRY_RUN and not exhausted,
            "provider_call_budget": budget.limit,
            "provider_calls_remaining": budget.remaining,
            "quota_exhausted": exhausted,
        }
        if exhausted:
            summary.update(
                {
                    "error_class": ProcessingErrorClass.QUOTA_INSUFFICIENT.value,
                    "reason": counts.get("reason") or "provider_quota_exhausted",
                    "admin_action_required": counts.get(
                        "admin_action_required",
                        "increase_provider_call_budget_or_retry_after_provider_quota_reset",
                    ),
                }
            )
        return summary

    def _commit_if_available(self) -> None:
        commit = getattr(self.session, "commit", None)
        if callable(commit):
            commit()
