from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from app.agents.call_processing import EnsureResponse, ProcessingRunStatus, ProcessingScope
from app.agents.call_processing import cli as call_processing_cli


def _grant(role: str = "admin", *, rate_limits: dict[str, int] | None = None) -> str:
    return json.dumps(
        {
            "client_id": "edo-analysis",
            "client_type": "service",
            "role": role,
            "allowed_artifact_kinds": ["transcript", "llm1_first_pass"],
            "read_surfaces": ["processed_calls_v1", "transcripts_v1"],
            "rate_limits": rate_limits or {},
            "created_by_admin": "operator",
            "active": True,
        }
    )


def _scope() -> str:
    return json.dumps(
        {
            "department_id": str(uuid4()),
            "date_from": date(2026, 6, 1).isoformat(),
            "date_to": date(2026, 6, 1).isoformat(),
            "source": "onlinepbx",
        }
    )


class _FakeCallProcessingService:
    calls: list[dict[str, object]] = []

    def __init__(self, _db: object, *, requested_by: str = "tester") -> None:
        self.requested_by = requested_by

    def ensure(
        self,
        scope: ProcessingScope,
        required_artifacts: list[object],
        mode: object,
        *,
        requested_by: str,
        force_retry_failed: bool = False,
        provider_call_budget: int | None = None,
    ) -> EnsureResponse:
        self.calls.append(
            {
                "scope": scope,
                "required_artifacts": required_artifacts,
                "mode": mode,
                "requested_by": requested_by,
                "force_retry_failed": force_retry_failed,
                "provider_call_budget": provider_call_budget,
            }
        )
        return EnsureResponse(
            run_id="run-1",
            status=ProcessingRunStatus.READY,
            scope_hash="scope-hash",
            requested_by=requested_by,
            planned={"artifact_requirements_total": len(required_artifacts)},
            quota={"provider_calls_made": 0},
        )


class _FakeProcessingRunRepository:
    rows: list[object] = []
    updated: list[object] = []

    def __init__(self, _db: object) -> None:
        pass

    def get(self, run_id: str):
        if run_id != "run-1":
            return None
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        return type(
            "Run",
            (),
            {
                "id": "run-1",
                "requested_by": "edo-analysis",
                "scope_json": json.loads(_scope()),
                "scope_hash": "scope-hash",
                "required_artifacts": ["transcript", "llm1_first_pass"],
                "mode": "dry_run",
                "status": "ready",
                "counts_json": {"provider_calls_made": 0},
                "errors_json": [],
                "started_at": now,
                "finished_at": now,
                "heartbeat_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )()

    def list_open(self):
        return list(self.rows)

    def update_status(self, run, status, **kwargs):
        run.status = str(status)
        run.errors_json = kwargs.get("errors_json", run.errors_json)
        run.finished_at = kwargs.get("finished_at", run.finished_at)
        self.updated.append(run)
        return run


class _FakeDb:
    commits = 0

    def commit(self) -> None:
        type(self).commits += 1


@contextmanager
def _fake_db():
    yield _FakeDb()


def test_cli_dry_run_requires_admin_grant(capsys) -> None:
    exit_code = call_processing_cli.main(
        [
            "--grant",
            _grant("reader"),
            "dry-run",
            "--scope",
            _scope(),
            "--required-artifacts",
            "transcript",
        ]
    )

    assert exit_code == 1
    assert "admin grant required" in capsys.readouterr().out


def test_cli_dry_run_prints_json_response(monkeypatch, capsys) -> None:
    _FakeCallProcessingService.calls = []
    monkeypatch.setattr(call_processing_cli, "get_db", _fake_db)
    monkeypatch.setattr(call_processing_cli, "CallProcessingService", _FakeCallProcessingService)

    exit_code = call_processing_cli.main(
        [
            "--grant",
            _grant("admin"),
            "dry-run",
            "--scope",
            _scope(),
            "--required-artifacts",
            "transcript,llm1_first_pass",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ready"
    assert payload["requested_by"] == "edo-analysis"
    assert payload["planned"]["artifact_requirements_total"] == 2
    assert _FakeCallProcessingService.calls[0]["provider_call_budget"] is None


def test_cli_passes_provider_call_budget_from_grant_rate_limits(monkeypatch, capsys) -> None:
    _FakeCallProcessingService.calls = []
    monkeypatch.setattr(call_processing_cli, "get_db", _fake_db)
    monkeypatch.setattr(call_processing_cli, "CallProcessingService", _FakeCallProcessingService)

    exit_code = call_processing_cli.main(
        [
            "--grant",
            _grant("admin", rate_limits={"max_provider_calls_per_run": 2}),
            "ensure",
            "--scope",
            _scope(),
            "--required-artifacts",
            "transcript",
        ]
    )

    assert exit_code == 0
    json.loads(capsys.readouterr().out)
    assert _FakeCallProcessingService.calls[0]["provider_call_budget"] == 2


def test_cli_retry_failed_is_admin_only(capsys) -> None:
    exit_code = call_processing_cli.main(
        [
            "--grant",
            _grant("reader"),
            "retry-failed",
            "--run-id",
            "run-1",
        ]
    )

    assert exit_code == 1
    assert "admin grant required" in capsys.readouterr().out


def test_cli_run_status_prints_persisted_run(monkeypatch, capsys) -> None:
    monkeypatch.setattr(call_processing_cli, "get_db", _fake_db)
    monkeypatch.setattr(call_processing_cli, "ProcessingRunRepository", _FakeProcessingRunRepository)

    exit_code = call_processing_cli.main(
        [
            "--grant",
            _grant("reader"),
            "run-status",
            "--run-id",
            "run-1",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == "run-1"
    assert payload["status"] == "ready"
    assert payload["counts"]["provider_calls_made"] == 0


def test_cli_retry_failed_replays_run_scope_with_force(monkeypatch, capsys) -> None:
    _FakeCallProcessingService.calls = []
    monkeypatch.setattr(call_processing_cli, "get_db", _fake_db)
    monkeypatch.setattr(call_processing_cli, "CallProcessingService", _FakeCallProcessingService)
    monkeypatch.setattr(call_processing_cli, "ProcessingRunRepository", _FakeProcessingRunRepository)

    exit_code = call_processing_cli.main(
        [
            "--grant",
            _grant("admin"),
            "retry-failed",
            "--run-id",
            "run-1",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["retried_from_run_id"] == "run-1"
    assert payload["retry_run"]["status"] == "ready"
    assert _FakeCallProcessingService.calls[0]["force_retry_failed"] is True
    assert len(_FakeCallProcessingService.calls[0]["required_artifacts"]) == 2


def test_cli_cleanup_stale_runs_marks_only_stale_open_runs(monkeypatch, capsys) -> None:
    now = datetime.now(UTC)
    stale = type(
        "Run",
        (),
        {
            "id": "stale-run",
            "status": "running",
            "errors_json": [],
            "finished_at": None,
            "heartbeat_at": now - timedelta(hours=3),
            "updated_at": now - timedelta(hours=3),
        },
    )()
    fresh = type(
        "Run",
        (),
        {
            "id": "fresh-run",
            "status": "running",
            "errors_json": [],
            "finished_at": None,
            "heartbeat_at": now,
            "updated_at": now,
        },
    )()
    _FakeProcessingRunRepository.rows = [stale, fresh]
    _FakeProcessingRunRepository.updated = []
    _FakeDb.commits = 0
    monkeypatch.setattr(call_processing_cli, "get_db", _fake_db)
    monkeypatch.setattr(call_processing_cli, "ProcessingRunRepository", _FakeProcessingRunRepository)

    exit_code = call_processing_cli.main(
        [
            "--grant",
            _grant("admin"),
            "cleanup-stale-runs",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stale_runs_cleaned"] == 1
    assert payload["runs"][0]["run_id"] == "stale-run"
    assert stale.status == "stale"
    assert stale.finished_at is not None
    assert stale.errors_json[0]["error_class"] == "stale_processing_run"
    assert fresh.status == "running"
    assert _FakeProcessingRunRepository.updated == [stale]
    assert _FakeDb.commits == 1


def test_cli_cleanup_stale_runs_dry_run_does_not_commit(monkeypatch, capsys) -> None:
    now = datetime.now(UTC)
    stale = type(
        "Run",
        (),
        {
            "id": "stale-run",
            "status": "running",
            "errors_json": [],
            "finished_at": None,
            "heartbeat_at": now - timedelta(hours=3),
            "updated_at": now - timedelta(hours=3),
        },
    )()
    _FakeProcessingRunRepository.rows = [stale]
    _FakeProcessingRunRepository.updated = []
    _FakeDb.commits = 0
    monkeypatch.setattr(call_processing_cli, "get_db", _fake_db)
    monkeypatch.setattr(call_processing_cli, "ProcessingRunRepository", _FakeProcessingRunRepository)

    exit_code = call_processing_cli.main(
        [
            "--grant",
            _grant("admin"),
            "cleanup-stale-runs",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stale_runs_cleaned"] == 1
    assert payload["runs"][0]["dry_run"] is True
    assert stale.status == "running"
    assert _FakeProcessingRunRepository.updated == []
    assert _FakeDb.commits == 0
