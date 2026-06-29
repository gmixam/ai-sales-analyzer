from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.agents.call_processing import EnsureMode, EnsureResponse, ProcessingRunStatus, ProcessingScope
from report_scripts import company_transcription_rollout_preflight as preflight


def _company_scope() -> ProcessingScope:
    return ProcessingScope.model_validate(
        {
            "scope_mode": "company",
            "fallback_department_id": "department-1",
            "manager_ids": ["manager-1", "manager-2"],
            "extensions": ["317", "325"],
            "scope_manager_count": 2,
            "scope_extension_count": 2,
            "scope_department_count": 2,
            "scope_diagnostics": ["technical_managers_excluded:1"],
            "date_from": date(2026, 6, 15),
            "date_to": date(2026, 6, 15),
            "source": "onlinepbx",
            "min_duration_sec": 15,
        }
    )


def _onlinepbx_all_scope() -> ProcessingScope:
    return ProcessingScope.model_validate(
        {
            "scope_mode": "onlinepbx_all",
            "fallback_department_id": "department-1",
            "manager_ids": [],
            "extensions": [],
            "scope_manager_count": 0,
            "scope_extension_count": 0,
            "scope_department_count": 1,
            "scope_diagnostics": ["onlinepbx_all_no_manager_directory_scope"],
            "date_from": date(2026, 6, 15),
            "date_to": date(2026, 6, 15),
            "source": "onlinepbx",
            "min_duration_sec": 15,
        }
    )


class _FakeDb:
    pass


@contextmanager
def _fake_db():
    yield _FakeDb()


class _FakeCallProcessingService:
    calls: list[dict[str, object]] = []

    def __init__(self, db: object, *, requested_by: str) -> None:
        self.db = db
        self.requested_by = requested_by

    def ensure(
        self,
        scope: ProcessingScope,
        required_artifacts: list[object],
        mode: object,
        *,
        requested_by: str,
        provider_call_budget: int | None,
    ) -> EnsureResponse:
        self.calls.append(
            {
                "scope": scope,
                "required_artifacts": required_artifacts,
                "mode": mode,
                "requested_by": requested_by,
                "provider_call_budget": provider_call_budget,
            }
        )
        return EnsureResponse(
            run_id="run-dry",
            status=ProcessingRunStatus.PARTIAL,
            scope_hash="dry-scope-hash",
            requested_by=requested_by,
            planned={
                "source_targeted_total": 5,
                "eligible_audio_calls": 3,
                "eligible_audio_calls_missing_record_url": 1,
                "no_audio_calls": 2,
                "missed_calls": 1,
                "zero_talk_calls": 1,
                "billable_minutes_estimate": 9,
                "provider_calls_estimate": 8,
                "provider_calls_budget": 20,
                "provider_calls_budget_status": "within_budget",
                "forecast_budget_status": "within_budget",
                "provider_calls_made": 0,
                "source_provider_calls_made": 0,
                "transcripts_built": 0,
                "llm1_first_pass_built": 0,
            },
            quota={"provider_calls_made": 0},
            costs={
                "forecast": True,
                "forecast_billable_minutes": 9,
                "forecast_cost_usdt": 0.42,
                "total_current_run_cost_usdt": 0.42,
                "cost_status": "ok",
            },
        )


class _FakeProcessingRunRepository:
    exact_run: object | None = None
    covering_run: object | None = None
    calls: list[dict[str, object]] = []

    def __init__(self, db: object) -> None:
        self.db = db

    def latest_for_scope(self, *, scope: ProcessingScope, required_artifacts: list[object]):
        self.calls.append(
            {
                "method": "latest_for_scope",
                "scope": scope,
                "required_artifacts": required_artifacts,
            }
        )
        return self.exact_run

    def latest_covering_for_scope(self, *, scope: ProcessingScope, required_artifacts: list[object]):
        self.calls.append(
            {
                "method": "latest_covering_for_scope",
                "scope": scope,
                "required_artifacts": required_artifacts,
            }
        )
        return self.covering_run


def _run(status: str = "ready") -> object:
    now = datetime(2026, 6, 15, 20, 0, tzinfo=UTC)
    return SimpleNamespace(
        id="run-ready",
        status=status,
        scope_hash="scope-hash-ready",
        requested_by="scheduled_call_processing_upstream",
        mode="ensure",
        required_artifacts=["transcript", "transcript_segments", "llm1_first_pass"],
        counts_json={
            "artifacts_missing": 0,
            "source_targeted_total": 5,
            "eligible_audio_calls": 3,
            "billable_minutes_estimate": 9,
            "provider_calls_estimate": 8,
            "provider_calls_budget": 20,
            "provider_calls_budget_status": "within_budget",
            "forecast_budget_status": "within_budget",
            "provider_calls_made": 8,
            "costs": {
                "forecast_cost_usdt": 0.42,
                "forecast_billable_minutes": 9,
                "cost_status": "ok",
            },
        },
        errors_json=[],
        started_at=now,
        finished_at=now,
        heartbeat_at=now,
        created_at=now,
        updated_at=now,
    )


def test_scope_preview_uses_runtime_scope_resolver(monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []

    def fake_scope(target_date: date, db: object) -> ProcessingScope:
        calls.append({"target_date": target_date, "db": db})
        return _company_scope()

    monkeypatch.setattr(preflight, "get_db", _fake_db)
    monkeypatch.setattr(preflight, "_daily_upstream_scope", fake_scope)
    monkeypatch.setattr(
        preflight,
        "CallProcessingService",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("service not allowed")),
    )

    exit_code = preflight.main(["scope-preview", "--date", "2026-06-15", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["scope"]["scope_mode"] == "company"
    assert payload["scope"]["scope_extension_count"] == 2
    assert payload["scope"]["min_duration_sec"] == 15
    assert payload["acceptance"]["ready_for_provider_backed_trial"] is True
    assert calls[0]["target_date"] == date(2026, 6, 15)


def test_scope_preview_accepts_onlinepbx_all_without_extensions(monkeypatch, capsys) -> None:
    monkeypatch.setattr(preflight, "get_db", _fake_db)
    monkeypatch.setattr(preflight, "_daily_upstream_scope", lambda *_args: _onlinepbx_all_scope())
    monkeypatch.setattr(
        preflight,
        "CallProcessingService",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("service not allowed")),
    )

    exit_code = preflight.main(["scope-preview", "--date", "2026-06-15", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["scope"]["scope_mode"] == "onlinepbx_all"
    assert payload["scope"]["scope_extension_count"] == 0
    assert payload["acceptance"]["scope_mode_is_onlinepbx_all"] is True
    assert payload["acceptance"]["has_extensions"] is False
    assert payload["acceptance"]["ready_for_provider_backed_trial"] is True
    assert "scheduled_runtime_scope_has_no_extensions" not in payload["blockers"]
    assert "all OnlinePBX CDR" in payload["operator_next_step"]
    assert "selected manager_daily scope" in payload["operator_next_step"]


def test_dry_run_invokes_only_call_processing_dry_run_contract(monkeypatch, capsys) -> None:
    _FakeCallProcessingService.calls = []
    monkeypatch.setattr(preflight, "get_db", _fake_db)
    monkeypatch.setattr(preflight, "_daily_upstream_scope", lambda *_args: _company_scope())
    monkeypatch.setattr(preflight, "CallProcessingService", _FakeCallProcessingService)
    monkeypatch.setattr(
        preflight,
        "settings",
        SimpleNamespace(call_processing_daily_upstream_provider_call_budget=20),
    )

    exit_code = preflight.main(["dry-run", "--date", "2026-06-15", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["forecast"]["source_targeted_total"] == 5
    assert payload["forecast"]["provider_calls_estimate"] == 8
    assert payload["acceptance"]["no_provider_stt_llm_calls_in_dry_run"] is True
    assert payload["run"]["required_artifacts"] == [
        "transcript",
        "transcript_segments",
        "llm1_first_pass",
    ]
    call = _FakeCallProcessingService.calls[0]
    assert call["mode"] is EnsureMode.DRY_RUN
    assert [item.value for item in call["required_artifacts"]] == [
        "transcript",
        "transcript_segments",
        "llm1_first_pass",
    ]
    assert call["provider_call_budget"] == 20


def test_latest_run_check_reads_exact_ready_run_without_service(monkeypatch, capsys) -> None:
    _FakeProcessingRunRepository.exact_run = _run()
    _FakeProcessingRunRepository.covering_run = None
    _FakeProcessingRunRepository.calls = []
    monkeypatch.setattr(preflight, "get_db", _fake_db)
    monkeypatch.setattr(preflight, "_daily_upstream_scope", lambda *_args: _company_scope())
    monkeypatch.setattr(preflight, "ProcessingRunRepository", _FakeProcessingRunRepository)
    monkeypatch.setattr(
        preflight,
        "CallProcessingService",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("service not allowed")),
    )

    exit_code = preflight.main(["latest-run-check", "--date", "2026-06-15", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["run"]["run_id"] == "run-ready"
    assert payload["run"]["scope_match"] == "exact"
    assert payload["acceptance"]["has_ready_upstream_run"] is True
    assert [call["method"] for call in _FakeProcessingRunRepository.calls] == ["latest_for_scope"]


def test_latest_run_check_falls_back_to_covering_run(monkeypatch, capsys) -> None:
    _FakeProcessingRunRepository.exact_run = None
    _FakeProcessingRunRepository.covering_run = _run()
    _FakeProcessingRunRepository.calls = []
    monkeypatch.setattr(preflight, "get_db", _fake_db)
    monkeypatch.setattr(preflight, "_daily_upstream_scope", lambda *_args: _company_scope())
    monkeypatch.setattr(preflight, "ProcessingRunRepository", _FakeProcessingRunRepository)

    exit_code = preflight.main(["latest-run-check", "--date", "2026-06-15", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["run"]["scope_match"] == "covering"
    assert payload["run"]["covering_scope_hash"] == "scope-hash-ready"
    assert [call["method"] for call in _FakeProcessingRunRepository.calls] == [
        "latest_for_scope",
        "latest_covering_for_scope",
    ]


def test_acceptance_blocks_non_company_scope() -> None:
    scope = ProcessingScope.model_validate(
        {
            "scope_mode": "department",
            "department_id": "department-1",
            "manager_ids": ["manager-1"],
            "extensions": ["317"],
            "date_from": "2026-06-15",
            "date_to": "2026-06-15",
            "source": "onlinepbx",
        }
    )

    payload = preflight._scope_preview_payload(date(2026, 6, 15), scope)

    assert payload["status"] == "blocked"
    assert payload["acceptance"]["scope_mode_is_company"] is False
    assert "scheduled_runtime_scope_is_not_company" in payload["blockers"]


def test_help_smoke(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        preflight.main(["--help"])

    assert exc.value.code == 0
    assert "scope-preview" in capsys.readouterr().out
