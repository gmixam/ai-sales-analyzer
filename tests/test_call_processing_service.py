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
    ProcessingErrorClass,
    ProcessingRunStatus,
    ProcessingScope,
    RequiredArtifactKind,
    is_retryable_error,
    is_stale_run,
    should_retry_error,
)
from app.agents.call_processing.repositories import ArtifactRepository, ProcessingRunRepository
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
        metadata_={"segments": segments or []},
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
