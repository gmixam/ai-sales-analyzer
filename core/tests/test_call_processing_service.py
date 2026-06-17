from __future__ import annotations

import uuid
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from app.agents.call_processing import (
    MAX_PROVIDER_ATTEMPTS,
    STALE_RUN_AFTER,
    ArtifactKind,
    ArtifactStatus,
    CallProcessingService,
    EnsureMode,
    EnsureResponse,
    ProcessingErrorClass,
    ProcessingRunStatus,
    ProcessingScope,
    RequiredArtifactKind,
    is_retryable_error,
    is_stale_run,
    should_retry_error,
)
from app.agents.call_processing.repositories import ArtifactRepository, ProcessingRunRepository
from app.agents.calls.intake import OnlinePBXIntake
from app.agents.calls.schemas import CDRRecord, SpeakerSegment, TranscriptResult
from app.core_shared.db.models import Interaction


class _ScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def all(self) -> list[object]:
        return self.rows

    def first(self) -> object | None:
        return self.rows[0] if self.rows else None


class _FakeSession:
    def __init__(self, scalars_rows: list[object] | None = None) -> None:
        self.scalars_rows = scalars_rows or []
        self.added: list[object] = []
        self.new: list[object] = []
        self.commits = 0
        self.flushes = 0

    def add(self, row: object) -> None:
        self.added.append(row)
        self.new.append(row)

    def commit(self) -> None:
        self.commits += 1

    def flush(self) -> None:
        self.flushes += 1
        self.new.clear()

    @property
    def no_autoflush(self):
        return nullcontext()

    def scalars(self, _stmt: object) -> _ScalarResult:
        return _ScalarResult(self.scalars_rows)


class _MemoryArtifactRepository:
    def __init__(self) -> None:
        self.rows: list[SimpleNamespace] = []

    def latest_active(
        self,
        interaction_id: uuid.UUID | str,
        artifact_kind: ArtifactKind | RequiredArtifactKind | str,
        artifact_version: str | None = None,
    ) -> SimpleNamespace | None:
        kind = str(artifact_kind.value if hasattr(artifact_kind, "value") else artifact_kind)
        active = [
            row
            for row in self.rows
            if row.interaction_id == interaction_id
            and row.artifact_kind == kind
            and row.is_active
            and (artifact_version is None or row.artifact_version == artifact_version)
        ]
        return active[-1] if active else None

    def write_active(self, **kwargs: object) -> SimpleNamespace:
        existing = self.latest_active(kwargs["interaction_id"], kwargs["artifact_kind"], kwargs.get("artifact_version"))
        if existing is not None:
            existing.is_active = False
        kind = kwargs["artifact_kind"]
        row = SimpleNamespace(
            id=uuid.uuid4(),
            is_active=True,
            artifact_kind=str(kind.value if hasattr(kind, "value") else kind),
            status=str(kwargs["status"].value if hasattr(kwargs["status"], "value") else kwargs["status"]),
            **{key: value for key, value in kwargs.items() if key not in {"artifact_kind", "status"}},
        )
        self.rows.append(row)
        return row


def _scope() -> ProcessingScope:
    return ProcessingScope(
        department_id=str(uuid.uuid4()),
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        source="onlinepbx",
    )


def _interaction(scope: ProcessingScope, *, text: str | None = None, segments: list[dict] | None = None) -> Interaction:
    return Interaction(
        id=uuid.uuid4(),
        department_id=uuid.UUID(scope.department_id or str(uuid.uuid4())),
        type="call",
        source="onlinepbx",
        text=text,
        metadata_={"segments": segments or [], "call_date": scope.date_from.isoformat()},
        duration_sec=120,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


def test_processing_run_repository_creates_and_updates_durable_run() -> None:
    session = _FakeSession()
    repo = ProcessingRunRepository(session)
    scope = _scope()

    run = repo.create(
        scope=scope,
        required_artifacts=[RequiredArtifactKind.TRANSCRIPT],
        mode=EnsureMode.DRY_RUN,
        requested_by="tester",
    )
    repo.update_status(run, ProcessingRunStatus.READY, counts_json={"artifacts_ready": 1})

    assert session.added == [run]
    assert run.id is not None
    assert run.scope_hash
    assert run.required_artifacts == ["transcript"]
    assert run.mode == "dry_run"
    assert run.status == "ready"
    assert run.counts_json == {"artifacts_ready": 1}


def test_ensure_response_costs_default_is_backward_compatible() -> None:
    response = EnsureResponse(
        run_id="run-1",
        status=ProcessingRunStatus.READY,
        scope_hash="scope-hash",
        requested_by="tester",
        planned={"provider_calls_made": 0},
        quota={"provider_calls_made": 0},
    )

    assert response.costs == {}


def test_artifact_repository_write_active_deactivates_previous_artifact() -> None:
    session = _FakeSession()
    repo = ArtifactRepository(session)
    scope = _scope()
    interaction = _interaction(scope)

    first = repo.write_active(
        department_id=interaction.department_id,
        interaction_id=interaction.id,
        artifact_kind=ArtifactKind.TRANSCRIPT,
        status=ArtifactStatus.READY,
        text_value="first",
    )
    session.scalars_rows = [first]
    second = repo.write_active(
        department_id=interaction.department_id,
        interaction_id=interaction.id,
        artifact_kind=ArtifactKind.TRANSCRIPT,
        status=ArtifactStatus.READY,
        text_value="second",
    )

    assert first.is_active is False
    assert second.is_active is True
    assert second.text_value == "second"
    assert session.added == [first, second]
    assert session.flushes == 1


def test_artifact_repository_write_active_deactivates_pending_duplicate() -> None:
    session = _FakeSession()
    repo = ArtifactRepository(session)
    scope = _scope()
    interaction = _interaction(scope)

    first = repo.write_active(
        department_id=interaction.department_id,
        interaction_id=interaction.id,
        artifact_kind=ArtifactKind.TRANSCRIPT_SEGMENTS,
        status=ArtifactStatus.READY,
        payload_json={"segments": [{"text": "first"}]},
    )
    second = repo.write_active(
        department_id=interaction.department_id,
        interaction_id=interaction.id,
        artifact_kind=ArtifactKind.TRANSCRIPT_SEGMENTS,
        status=ArtifactStatus.READY,
        payload_json={"segments": [{"text": "second"}]},
    )

    assert first.is_active is False
    assert second.is_active is True
    assert session.flushes == 0
    assert session.added == [first, second]


def test_ensure_backfills_legacy_transcript_and_segments_without_provider_calls() -> None:
    scope = _scope()
    interaction = _interaction(scope, text="hello client", segments=[{"speaker": "manager", "text": "hello"}])
    artifacts = _MemoryArtifactRepository()
    service = CallProcessingService(_FakeSession([interaction]), artifacts=artifacts, requested_by="tester")

    response = service.ensure(
        scope,
        [RequiredArtifactKind.TRANSCRIPT, RequiredArtifactKind.TRANSCRIPT_SEGMENTS],
    )

    assert response.status == ProcessingRunStatus.READY
    assert response.planned["artifacts_backfilled"] == 2
    assert response.planned["artifacts_ready"] == 2
    assert response.planned["provider_calls_made"] == 0
    assert response.costs["cost_status"] == "no_billable_work"
    assert response.costs["total_current_run_cost_usdt"] == 0.0
    assert {row.artifact_kind for row in artifacts.rows} == {"transcript", "transcript_segments"}


def test_ensure_is_idempotent_by_reusing_active_ready_artifacts() -> None:
    scope = _scope()
    interaction = _interaction(scope, text="legacy text")
    artifacts = _MemoryArtifactRepository()
    service = CallProcessingService(_FakeSession([interaction]), artifacts=artifacts, requested_by="tester")

    first = service.ensure(scope, [RequiredArtifactKind.TRANSCRIPT])
    second = service.ensure(scope, [RequiredArtifactKind.TRANSCRIPT])

    assert first.planned["artifacts_backfilled"] == 1
    assert second.planned["artifacts_backfilled"] == 0
    assert second.planned["artifacts_ready"] == 1
    assert second.costs["cost_status"] == "no_billable_work"
    assert len([row for row in artifacts.rows if row.is_active]) == 1


def test_dry_run_plans_backfill_but_does_not_write_artifacts() -> None:
    scope = _scope()
    interaction = _interaction(scope, text="legacy text")
    artifacts = _MemoryArtifactRepository()
    service = CallProcessingService(_FakeSession([interaction]), artifacts=artifacts)

    response = service.ensure(scope, [RequiredArtifactKind.TRANSCRIPT], mode=EnsureMode.DRY_RUN)

    assert response.status == ProcessingRunStatus.READY
    assert response.planned["artifacts_backfilled"] == 1
    assert response.quota["provider_calls_made"] == 0
    assert response.costs["cost_status"] == "no_billable_work"
    assert artifacts.rows == []


def test_missing_llm1_is_planned_without_provider_call() -> None:
    scope = _scope()
    interaction = _interaction(scope)
    service = CallProcessingService(_FakeSession([interaction]))

    response = service.ensure(scope, [RequiredArtifactKind.LLM1_FIRST_PASS])

    assert response.status == ProcessingRunStatus.BLOCKED
    assert response.planned["artifacts_missing"] == 1
    assert response.planned["provider_calls_planned"] == 1
    assert response.planned["provider_calls_made"] == 0


def test_no_audio_interactions_do_not_create_artifact_requirements() -> None:
    scope = _scope()
    interaction = _interaction(
        scope,
        text="legacy text should not be backfilled",
        segments=[{"speaker": "manager", "text": "legacy"}],
    )
    interaction.status = "NO_AUDIO"
    interaction.raw_ref = "https://recordings.test/should-not-run.mp3"
    artifacts = _MemoryArtifactRepository()
    service = CallProcessingService(_FakeSession([interaction]), artifacts=artifacts)

    counts = service._plan_and_backfill(
        [interaction],
        [
            RequiredArtifactKind.TRANSCRIPT,
            RequiredArtifactKind.TRANSCRIPT_SEGMENTS,
            RequiredArtifactKind.LLM1_FIRST_PASS,
        ],
        EnsureMode.ENSURE,
    )

    assert counts["interactions_total"] == 0
    assert counts["interactions_skipped_no_audio"] == 1
    assert counts["artifact_requirements_total"] == 0
    assert counts["artifacts_missing"] == 0
    assert counts["provider_calls_planned"] == 0
    assert artifacts.rows == []


class _DiscoverySession(_FakeSession):
    def query(self, *_args: object):
        return self

    def filter(self, *_args: object):
        return self

    def first(self):
        return None


class _NoopLogger:
    def info(self, *_args: object, **_kwargs: object) -> None:
        return None


def _build_test_intake(session: _FakeSession, scope: ProcessingScope) -> OnlinePBXIntake:
    intake = OnlinePBXIntake.__new__(OnlinePBXIntake)
    intake.db = session
    intake.department_id = uuid.UUID(scope.department_id or str(uuid.uuid4()))
    intake.config = SimpleNamespace(
        allowed_statuses={"answered"},
        allowed_directions={"out"},
    )
    intake.logger = _NoopLogger()
    intake.resolve_manager_mapping = lambda _record: (
        None,
        intake.department_id,
        {"mapping_source": "test"},
    )
    return intake


class _FakeIntake:
    def __init__(self, session: _FakeSession, scope: ProcessingScope) -> None:
        self.session = session
        self.scope = scope
        self.config = SimpleNamespace(
            allowed_statuses={"answered"},
            allowed_directions={"out"},
        )
        self.recording_requests: list[str] = []
        self.cdr_requests: list[str] = []

    def get_cdr_list(self, day: str) -> list[CDRRecord]:
        self.cdr_requests.append(day)
        return [
            CDRRecord(
                call_id="call-1",
                call_date=f"{day}T10:00:00+00:00",
                duration=180,
                talk_duration=150,
                direction="out",
                status="answered",
                extension="322",
                phone="+77070000000",
                record_url=None,
            )
        ]

    def get_recording_url(self, call_id: str) -> str:
        self.recording_requests.append(call_id)
        return f"https://recordings.test/{call_id}.mp3"

    def save_interactions(self, records: list[CDRRecord]) -> tuple[int, int]:
        for record in records:
            self.session.scalars_rows.append(
                _interaction(
                    self.scope,
                    text=None,
                    segments=[],
                )
            )
            self.session.scalars_rows[-1].external_id = record.call_id
            self.session.scalars_rows[-1].raw_ref = record.record_url
            self.session.scalars_rows[-1].metadata_ = {
                "call_date": record.call_date,
                "extension": record.extension,
            }
        return len(records), 0


def test_ensure_discovers_and_persists_source_calls_in_ensure_mode() -> None:
    scope = ProcessingScope(
        department_id=str(uuid.uuid4()),
        extensions=["322"],
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        source="onlinepbx",
    )
    session = _DiscoverySession([])
    intake_holder: dict[str, _FakeIntake] = {}

    def _intake_factory(_department_id: str, db: _FakeSession) -> _FakeIntake:
        intake = _FakeIntake(db, scope)
        intake_holder["intake"] = intake
        return intake

    service = CallProcessingService(
        session,
        artifacts=_MemoryArtifactRepository(),
        intake_factory=_intake_factory,
    )

    response = service.ensure(scope, [], mode=EnsureMode.ENSURE)

    assert response.planned["source_days_scanned"] == 1
    assert response.planned["source_records_total"] == 1
    assert response.planned["source_targeted_total"] == 1
    assert response.planned["source_ingest_created"] == 1
    assert response.planned["source_provider_calls_made"] == 2
    assert response.planned["provider_calls_made"] == 2
    assert response.quota["provider_calls_made"] == 2
    assert intake_holder["intake"].recording_requests == ["call-1"]
    assert len(session.scalars_rows) == 1


def test_split_discovery_persists_missed_zero_talk_duration_as_no_audio() -> None:
    scope = ProcessingScope(
        department_id=str(uuid.uuid4()),
        extensions=["322"],
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        source="onlinepbx",
    )
    session = _DiscoverySession([])
    intake = _build_test_intake(session, scope)
    recording_requests: list[str] = []

    def get_cdr_list(day: str) -> list[CDRRecord]:
        return [
            CDRRecord(
                call_id="missed-1",
                call_date=f"{day}T10:00:00+00:00",
                duration=0,
                talk_duration=0,
                direction="out",
                status="missed",
                extension="322",
                phone="+77070000000",
                record_url=None,
            )
        ]

    def get_recording_url(call_id: str) -> str:
        recording_requests.append(call_id)
        return f"https://recordings.test/{call_id}.mp3"

    intake.get_cdr_list = get_cdr_list
    intake.get_recording_url = get_recording_url
    service = CallProcessingService(
        session,
        artifacts=_MemoryArtifactRepository(),
        intake_factory=lambda _department_id, _db: intake,
    )

    response = service.ensure(scope, [], mode=EnsureMode.ENSURE)

    assert response.planned["source_targeted_total"] == 1
    assert response.planned["source_ingest_created"] == 1
    assert response.planned["source_provider_calls_made"] == 1
    assert recording_requests == []
    assert len(session.added) == 2
    interaction = session.added[1]
    assert interaction.external_id == "missed-1"
    assert interaction.status == "NO_AUDIO"
    assert interaction.duration_sec == 0
    assert interaction.raw_ref is None
    assert interaction.metadata_["source_status"] == "missed"


def test_split_discovery_persists_answered_with_audio_as_eligible() -> None:
    scope = ProcessingScope(
        department_id=str(uuid.uuid4()),
        extensions=["322"],
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        source="onlinepbx",
    )
    session = _DiscoverySession([])
    intake = _build_test_intake(session, scope)
    recording_requests: list[str] = []

    def get_cdr_list(day: str) -> list[CDRRecord]:
        return [
            CDRRecord(
                call_id="answered-1",
                call_date=f"{day}T10:00:00+00:00",
                duration=180,
                talk_duration=150,
                direction="out",
                status="answered",
                extension="322",
                phone="+77070000000",
                record_url=None,
            )
        ]

    def get_recording_url(call_id: str) -> str:
        recording_requests.append(call_id)
        return f"https://recordings.test/{call_id}.mp3"

    intake.get_cdr_list = get_cdr_list
    intake.get_recording_url = get_recording_url
    service = CallProcessingService(
        session,
        artifacts=_MemoryArtifactRepository(),
        intake_factory=lambda _department_id, _db: intake,
    )

    response = service.ensure(scope, [], mode=EnsureMode.ENSURE)

    assert response.planned["source_targeted_total"] == 1
    assert response.planned["source_ingest_created"] == 1
    assert response.planned["source_provider_calls_made"] == 2
    assert recording_requests == ["answered-1"]
    assert len(session.added) == 2
    interaction = session.added[1]
    assert interaction.external_id == "answered-1"
    assert interaction.status == "ELIGIBLE"
    assert interaction.duration_sec == 150
    assert interaction.raw_ref == "https://recordings.test/answered-1.mp3"
    assert interaction.metadata_["source_status"] == "answered"


def test_ensure_blocks_source_discovery_when_provider_budget_is_exhausted() -> None:
    scope = ProcessingScope(
        department_id=str(uuid.uuid4()),
        extensions=["322"],
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        source="onlinepbx",
    )
    session = _DiscoverySession([])
    intake_holder: dict[str, _FakeIntake] = {}

    def _intake_factory(_department_id: str, db: _FakeSession) -> _FakeIntake:
        intake = _FakeIntake(db, scope)
        intake_holder["intake"] = intake
        return intake

    service = CallProcessingService(
        session,
        artifacts=_MemoryArtifactRepository(),
        intake_factory=_intake_factory,
    )

    response = service.ensure(scope, [], mode=EnsureMode.ENSURE, provider_call_budget=0)

    assert response.status == ProcessingRunStatus.BLOCKED
    assert response.planned["quota_blocked"] == 1
    assert response.planned["source_provider_calls_made"] == 0
    assert response.planned["provider_calls_made"] == 0
    assert response.quota["quota_exhausted"] is True
    assert intake_holder["intake"].cdr_requests == []
    assert intake_holder["intake"].recording_requests == []
    assert session.scalars_rows == []


class _FakeExtractor:
    async def process(self, interaction: Interaction) -> TranscriptResult:
        interaction.text = "Клиент попросил материалы."
        interaction.metadata_ = {
            **dict(interaction.metadata_ or {}),
            "segments": [{"speaker": "A", "text": "Клиент попросил материалы.", "start_ms": 0, "end_ms": 1000}],
            "ai_routing": {
                "stt": {
                    "provider": "openai",
                    "model": "whisper-1",
                    "account_alias": "stt_main",
                    "api_key_env": "OPENAI_API_KEY_STT_MAIN",
                    "provider_request_id": "stt-request-1",
                }
            },
        }
        return TranscriptResult(
            interaction_id=str(interaction.id),
            full_text=interaction.text,
            segments=[
                SpeakerSegment(
                    speaker="A",
                    text="Клиент попросил материалы.",
                    start_ms=0,
                    end_ms=1000,
                )
            ],
            speaker_a_is_manager=False,
            diarization_metadata={
                "source": "openai_whisper_time_segments",
                "stt_provider": "openai",
                "stt_model": "whisper-1",
                "diarization_source": "whisper_time_segments_without_speaker_labels",
                "diarization_quality": "low",
                "warnings": ["technical_speaker_labels_unavailable"],
            },
            confidence=0.91,
            duration_sec=60,
        )


class _CountingExtractor(_FakeExtractor):
    def __init__(self) -> None:
        self.calls = 0

    async def process(self, interaction: Interaction) -> TranscriptResult:
        self.calls += 1
        return await super().process(interaction)


def test_ensure_builds_transcript_and_segments_artifacts_via_stt() -> None:
    scope = _scope()
    interaction = _interaction(scope)
    interaction.raw_ref = "https://recordings.test/call.mp3"
    artifacts = _MemoryArtifactRepository()
    service = CallProcessingService(
        _FakeSession([interaction]),
        artifacts=artifacts,
        extractor_factory=lambda _department_id, _db: _FakeExtractor(),
    )

    response = service.ensure(
        scope,
        [RequiredArtifactKind.TRANSCRIPT, RequiredArtifactKind.TRANSCRIPT_SEGMENTS],
    )

    assert response.status == ProcessingRunStatus.READY
    assert response.planned["transcripts_built"] == 1
    assert response.planned["provider_calls_made"] == 1
    assert response.costs["schema_version"] == "split_upstream_ai_costs_v1"
    assert response.costs["cost_status"] == "price_missing"
    assert response.costs["stt_cost_usdt"] is None
    assert response.costs["total_current_run_cost_usdt"] == 0.0
    assert response.costs["by_layer"][0]["layer"] == "stt"
    assert response.costs["by_layer"][0]["duration_sec"] == 60
    active = {row.artifact_kind: row for row in artifacts.rows if row.is_active}
    assert active["transcript"].text_value == "Клиент попросил материалы."
    assert active["transcript"].provider == "openai"
    assert active["transcript"].payload_json["speaker_a_is_manager"] is False
    assert (
        active["transcript"].payload_json["diarization"]["diarization_source"]
        == "whisper_time_segments_without_speaker_labels"
    )
    assert active["transcript_segments"].payload_json["segments"][0]["text"] == "Клиент попросил материалы."
    assert active["transcript_segments"].payload_json["speaker_a_is_manager"] is False


def test_ensure_blocks_billable_provider_work_when_quota_exhausted() -> None:
    scope = _scope()
    interaction = _interaction(scope)
    interaction.raw_ref = "https://recordings.test/call.mp3"
    artifacts = _MemoryArtifactRepository()
    extractor = _CountingExtractor()
    service = CallProcessingService(
        _FakeSession([interaction]),
        artifacts=artifacts,
        extractor_factory=lambda _department_id, _db: extractor,
    )

    response = service.ensure(
        scope,
        [RequiredArtifactKind.TRANSCRIPT],
        provider_call_budget=0,
    )

    assert response.status == ProcessingRunStatus.BLOCKED
    assert response.planned["quota_blocked"] == 1
    assert response.planned["provider_calls_planned"] == 1
    assert response.planned["provider_calls_made"] == 0
    assert response.quota["quota_exhausted"] is True
    assert response.quota["error_class"] == ProcessingErrorClass.QUOTA_INSUFFICIENT.value
    assert response.quota["admin_action_required"]
    assert extractor.calls == 0
    assert artifacts.rows == []


def test_ensure_does_not_retry_non_retryable_failed_artifact_without_force() -> None:
    scope = _scope()
    interaction = _interaction(scope)
    interaction.raw_ref = "https://recordings.test/call.mp3"
    artifacts = _MemoryArtifactRepository()
    artifacts.write_active(
        department_id=interaction.department_id,
        interaction_id=interaction.id,
        artifact_kind=ArtifactKind.TRANSCRIPT,
        artifact_version="transcript_v1",
        status=ArtifactStatus.FAILED,
        error_class=ProcessingErrorClass.AUTH_ERROR.value,
        error_reason="bad key",
        retryable=False,
    )
    extractor = _CountingExtractor()
    service = CallProcessingService(
        _FakeSession([interaction]),
        artifacts=artifacts,
        extractor_factory=lambda _department_id, _db: extractor,
    )

    response = service.ensure(scope, [RequiredArtifactKind.TRANSCRIPT])

    assert response.status == ProcessingRunStatus.BLOCKED
    assert response.planned["artifact_retry_blocked"] == 1
    assert response.planned["provider_calls_made"] == 0
    assert extractor.calls == 0
    assert artifacts.latest_active(interaction.id, ArtifactKind.TRANSCRIPT).status == ArtifactStatus.FAILED.value


def test_ensure_force_retries_failed_artifact_and_replaces_active_row() -> None:
    scope = _scope()
    interaction = _interaction(scope)
    interaction.raw_ref = "https://recordings.test/call.mp3"
    artifacts = _MemoryArtifactRepository()
    failed = artifacts.write_active(
        department_id=interaction.department_id,
        interaction_id=interaction.id,
        artifact_kind=ArtifactKind.TRANSCRIPT,
        artifact_version="transcript_v1",
        status=ArtifactStatus.FAILED,
        error_class=ProcessingErrorClass.AUTH_ERROR.value,
        error_reason="bad key",
        retryable=False,
    )
    extractor = _CountingExtractor()
    service = CallProcessingService(
        _FakeSession([interaction]),
        artifacts=artifacts,
        extractor_factory=lambda _department_id, _db: extractor,
    )

    response = service.ensure(
        scope,
        [RequiredArtifactKind.TRANSCRIPT],
        force_retry_failed=True,
    )

    assert response.status == ProcessingRunStatus.READY
    assert response.planned["artifact_retry_blocked"] == 0
    assert response.planned["transcripts_built"] == 1
    assert response.planned["provider_calls_made"] == 1
    assert extractor.calls == 1
    assert failed.is_active is False
    active = artifacts.latest_active(interaction.id, ArtifactKind.TRANSCRIPT)
    assert active.status == ArtifactStatus.READY.value
    assert active.text_value == "Клиент попросил материалы."


class _FakeAnalyzer:
    def _request_llm1_first_pass(self, *, interaction: Interaction, instruction_version: str) -> dict:
        interaction.metadata_ = {
            **dict(interaction.metadata_ or {}),
            "ai_routing": {
                "llm1": {
                    "provider": "openai",
                    "model": "gpt-test",
                    "account_alias": "llm1_main",
                    "api_key_env": "OPENAI_API_KEY_LLM1_MAIN",
                    "provider_request_id": "llm1-request-1",
                }
            },
        }
        return {
            "classification": {"call_type": "sales_primary"},
            "summary": {"brief": "Клиент попросил материалы."},
            "follow_up": {"next_step": "Отправить материалы."},
            "data_quality": {"transcript_quality": "sufficient"},
            "analysis_focus": ["Проверить договоренность."],
            "speaker_role_mapping": {
                "source": "llm1_role_attribution",
                "diarization_source": "whisper_time_segments_without_speaker_labels",
                "roles": [
                    {
                        "raw_speaker": "A",
                        "role": "unknown",
                        "confidence": "low",
                        "evidence": [],
                    }
                ],
                "quality": {
                    "diarization_quality": "low",
                    "role_attribution_quality": "low",
                    "warnings": ["technical_speaker_labels_unavailable"],
                },
            },
        }

    def analyze_call(self, *_args, **_kwargs):
        raise AssertionError("call-processing LLM1 artifact build must not run LLM2 analyze_call")


def test_ensure_builds_llm1_first_pass_artifact_without_llm2() -> None:
    scope = _scope()
    interaction = _interaction(scope, text="Клиент попросил материалы.")
    artifacts = _MemoryArtifactRepository()
    service = CallProcessingService(
        _FakeSession([interaction]),
        artifacts=artifacts,
        analyzer_factory=lambda _department_id, _db: _FakeAnalyzer(),
    )

    response = service.ensure(scope, [RequiredArtifactKind.LLM1_FIRST_PASS])

    assert response.status == ProcessingRunStatus.READY
    assert response.planned["llm1_first_pass_built"] == 1
    assert response.planned["provider_calls_made"] == 1
    assert response.costs["schema_version"] == "split_upstream_ai_costs_v1"
    assert response.costs["cost_status"] == "price_missing"
    assert response.costs["llm1_cost_usdt"] is None
    assert response.costs["by_layer"][0]["layer"] == "llm1"
    artifact = artifacts.latest_active(
        interaction.id,
        RequiredArtifactKind.LLM1_FIRST_PASS,
        "llm1_first_pass_v1",
    )
    assert artifact is not None
    assert artifact.provider == "openai"
    assert artifact.payload_json["schema_version"] == "llm1_first_pass_v1"
    assert artifact.payload_json["summary"]["brief"] == "Клиент попросил материалы."
    assert artifact.payload_json["speaker_role_mapping"]["roles"][0]["role"] == "unknown"
    assert (
        "technical_speaker_labels_unavailable"
        in artifact.payload_json["speaker_role_mapping"]["quality"]["warnings"]
    )


def test_ensure_uses_call_processing_cost_helper_when_available(monkeypatch) -> None:
    from app.agents.calls import ai_costs

    scope = _scope()
    interaction = _interaction(scope)
    interaction.raw_ref = "https://recordings.test/call.mp3"
    artifacts = _MemoryArtifactRepository()
    calls: list[dict[str, object]] = []

    def fake_estimate_call_processing_costs(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {
            "schema_version": "split_upstream_ai_costs_v1",
            "pricing_catalog_version": "test",
            "currency": "USDT",
            "cost_status": "available",
            "stt_cost_usdt": 0.006,
            "llm1_cost_usdt": 0.0,
            "total_current_run_cost_usdt": 0.006,
            "reused_artifact_original_cost_usdt": None,
            "cost_per_transcribed_call_usdt": 0.006,
            "by_layer": [],
            "by_request_kind": [],
            "notes": [],
        }

    monkeypatch.setattr(
        ai_costs,
        "estimate_call_processing_costs",
        fake_estimate_call_processing_costs,
        raising=False,
    )
    session = _FakeSession([interaction])
    service = CallProcessingService(
        session,
        artifacts=artifacts,
        extractor_factory=lambda _department_id, _db: _FakeExtractor(),
    )

    response = service.ensure(scope, [RequiredArtifactKind.TRANSCRIPT])

    assert response.costs["total_current_run_cost_usdt"] == 0.006
    assert calls[0]["counts"]["transcripts_built"] == 1
    assert calls[0]["execution_entries"][0]["layer"] == "stt"
    assert session.added[0].counts_json["costs"] == response.costs


def test_ensure_filters_interactions_by_scope_date() -> None:
    scope = _scope()
    in_scope = _interaction(scope, text="in scope")
    out_of_scope = _interaction(scope, text="old")
    out_of_scope.metadata_ = {"call_date": "2026-05-31"}
    artifacts = _MemoryArtifactRepository()
    service = CallProcessingService(
        _FakeSession([in_scope, out_of_scope]),
        artifacts=artifacts,
        requested_by="tester",
    )

    response = service.ensure(scope, [RequiredArtifactKind.TRANSCRIPT])

    assert response.planned["interactions_total"] == 1
    assert response.planned["artifacts_backfilled"] == 1
    assert artifacts.rows[0].interaction_id == in_scope.id


def test_retry_policy_and_stale_run_helpers_follow_split_contract() -> None:
    now = datetime(2026, 6, 13, 12, 0, tzinfo=UTC)
    stale_run = SimpleNamespace(status="running", heartbeat_at=now - STALE_RUN_AFTER - timedelta(seconds=1))
    fresh_run = SimpleNamespace(status="running", heartbeat_at=now - timedelta(minutes=5))
    ready_run = SimpleNamespace(status="ready", heartbeat_at=now - STALE_RUN_AFTER - timedelta(hours=1))

    assert MAX_PROVIDER_ATTEMPTS == 3
    assert is_retryable_error(ProcessingErrorClass.RATE_LIMITED) is True
    assert is_retryable_error(ProcessingErrorClass.AUTH_ERROR) is False
    assert should_retry_error(ProcessingErrorClass.PROVIDER_5XX, attempt_count=2) is True
    assert should_retry_error(ProcessingErrorClass.PROVIDER_5XX, attempt_count=3) is False
    assert should_retry_error(ProcessingErrorClass.SOURCE_AUDIO_MISSING, attempt_count=1) is False
    assert is_stale_run(stale_run, now=now) is True
    assert is_stale_run(fresh_run, now=now) is False
    assert is_stale_run(ready_run, now=now) is False
