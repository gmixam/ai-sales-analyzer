from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from uuid import uuid4

from app.agents.call_processing import EnsureResponse, ProcessingRunStatus, ProcessingScope
from app.agents.call_processing import cli as call_processing_cli


def _grant(role: str = "admin") -> str:
    return json.dumps(
        {
            "client_id": "edo-analysis",
            "client_type": "service",
            "role": role,
            "allowed_artifact_kinds": ["transcript", "llm1_first_pass"],
            "read_surfaces": ["processed_calls_v1", "transcripts_v1"],
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
    ) -> EnsureResponse:
        self.calls.append(
            {
                "scope": scope,
                "required_artifacts": required_artifacts,
                "mode": mode,
                "requested_by": requested_by,
                "force_retry_failed": force_retry_failed,
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
    def __init__(self, _db: object) -> None:
        pass

    def get(self, run_id: str):
        if run_id != "run-1":
            return None
        return type(
            "Run",
            (),
            {
                "scope_json": json.loads(_scope()),
                "required_artifacts": ["transcript", "llm1_first_pass"],
            },
        )()


@contextmanager
def _fake_db():
    yield object()


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
