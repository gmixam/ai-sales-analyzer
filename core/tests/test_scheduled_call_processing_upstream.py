from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from app.agents.call_processing import EnsureResponse, ProcessingRunStatus
from app.core_shared.workers import tasks


def _settings(**overrides: object) -> SimpleNamespace:
    data: dict[str, object] = {
        "app_service": "call_processing",
        "call_processing_daily_upstream_enabled": True,
        "call_processing_daily_upstream_timezone": "Asia/Almaty",
        "call_processing_daily_upstream_department_id": "472cda28-ce71-494c-9068-25d3ffbf7399",
        "call_processing_daily_upstream_manager_ids": ["manager-1", "manager-2"],
        "call_processing_daily_upstream_min_duration_sec": None,
        "call_processing_daily_upstream_provider_call_budget": 200,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_scheduled_upstream_skips_outside_call_processing_service(monkeypatch) -> None:
    monkeypatch.setattr(tasks, "settings", _settings(app_service="analysis"))

    result = tasks.ensure_daily_call_processing_upstream(report_date="2026-06-15", dry_run=True)

    assert result["task_status"] == "skipped"
    assert result["reason"] == "wrong_app_service"


def test_scheduled_upstream_requires_scope_before_billable_run(monkeypatch) -> None:
    monkeypatch.setattr(tasks, "settings", _settings(call_processing_daily_upstream_manager_ids=[]))

    result = tasks.ensure_daily_call_processing_upstream(report_date="2026-06-15")

    assert result["task_status"] == "skipped"
    assert result["reason"] == "manager_scope_not_configured"
    assert result["billable_pipeline_started"] is False


def test_scheduled_upstream_requires_provider_budget_for_ensure(monkeypatch) -> None:
    monkeypatch.setattr(tasks, "settings", _settings(call_processing_daily_upstream_provider_call_budget=0))

    result = tasks.ensure_daily_call_processing_upstream(report_date="2026-06-15")

    assert result["task_status"] == "skipped"
    assert result["reason"] == "provider_call_budget_not_configured"
    assert result["billable_pipeline_started"] is False


def test_scheduled_upstream_dry_run_uses_call_processing_ensure_contract(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    @contextmanager
    def fake_get_db():
        yield object()

    class FakeCallProcessingService:
        def __init__(self, db: object, *, requested_by: str) -> None:
            self.db = db
            self.requested_by = requested_by

        def ensure(self, scope, required_artifacts, mode, *, requested_by, provider_call_budget):
            calls.append(
                {
                    "scope": scope,
                    "required_artifacts": required_artifacts,
                    "mode": mode,
                    "requested_by": requested_by,
                    "provider_call_budget": provider_call_budget,
                }
            )
            return EnsureResponse(
                run_id="run-1",
                status=ProcessingRunStatus.READY,
                scope_hash="scope-hash",
                requested_by=requested_by,
                planned={"artifacts_ready": 6, "provider_calls_made": 0},
                quota={"provider_calls_made": 0},
                costs={"total_current_run_cost_usdt": 0.0, "cost_status": "dry_run"},
            )

    monkeypatch.setattr(tasks, "settings", _settings(call_processing_daily_upstream_enabled=False))
    monkeypatch.setattr(tasks, "get_db", fake_get_db)
    monkeypatch.setattr(tasks, "CallProcessingService", FakeCallProcessingService)

    result = tasks.ensure_daily_call_processing_upstream(report_date="2026-06-15", dry_run=True)

    assert result["task_status"] == "completed"
    assert result["mode"] == "dry_run"
    assert result["report_date"] == "2026-06-15"
    assert result["billable_pipeline_started"] is False
    assert result["status"] == "ready"
    assert result["required_artifacts"] == [
        "transcript",
        "transcript_segments",
        "llm1_first_pass",
    ]
    assert len(calls) == 1
    call = calls[0]
    assert [item.value for item in call["required_artifacts"]] == [
        "transcript",
        "transcript_segments",
        "llm1_first_pass",
    ]
    assert call["mode"].value == "dry_run"
    assert call["requested_by"] == "scheduled_call_processing_upstream"
    assert result["scope"]["department_id"] == "472cda28-ce71-494c-9068-25d3ffbf7399"
    assert result["scope"]["manager_ids"] == ["manager-1", "manager-2"]
