from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.call_processing import EnsureResponse, ProcessingRunStatus
from app.core_shared.workers import tasks


def _settings(**overrides: object) -> SimpleNamespace:
    data: dict[str, object] = {
        "app_service": "call_processing",
        "call_processing_daily_upstream_enabled": True,
        "call_processing_daily_upstream_timezone": "Asia/Almaty",
        "call_processing_daily_upstream_scope_mode": "managers",
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


def test_scheduled_reporting_scan_failure_sends_alert(monkeypatch) -> None:
    sent: list[dict[str, object]] = []

    class FailingScheduledReportingService:
        def __init__(self, db: object) -> None:
            self.db = db

        def scan_due_schedules(self):
            raise RuntimeError("db unavailable")

    @contextmanager
    def fake_get_db():
        yield object()

    def fake_send_run_alert(*args, **kwargs):
        sent.append({"args": args, "kwargs": kwargs})
        return {"channel": "telegram", "status": "sent"}

    monkeypatch.setattr(tasks, "get_db", fake_get_db)
    monkeypatch.setattr(tasks, "ScheduledReviewableReportingService", FailingScheduledReportingService)
    monkeypatch.setattr(tasks, "send_run_alert", fake_send_run_alert)

    try:
        tasks.scan_scheduled_reviewable_reporting()
    except RuntimeError as exc:
        assert str(exc) == "db unavailable"
    else:  # pragma: no cover - explicit guard for readability
        raise AssertionError("scan_scheduled_reviewable_reporting should re-raise failures")

    assert len(sent) == 1
    assert sent[0]["args"] == ("failed",)
    assert sent[0]["kwargs"]["run_id"] == "scheduled-reviewable-reporting-scan"
    assert sent[0]["kwargs"]["level"] == "error"


def test_manager_daily_sla_precheck_delegates_to_sla_check_auto_date(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_sla_check(args):
        calls.append({"date": args.date, "phase": args.phase})
        return {
            "status": "ok",
            "action": "sla_check",
            "report_date": "2026-06-16",
            "phase": args.phase,
        }

    fake_preflight = SimpleNamespace(sla_check=fake_sla_check)
    import report_scripts

    monkeypatch.setattr(report_scripts, "scheduled_reporting_preflight", fake_preflight, raising=False)
    monkeypatch.setitem(
        sys.modules,
        "report_scripts.scheduled_reporting_preflight",
        fake_preflight,
    )

    result = tasks.manager_daily_sla_precheck()

    assert calls == [{"date": "auto", "phase": "precheck"}]
    assert result["task"] == "calls.manager_daily_sla_precheck"
    assert result["task_status"] == "completed"
    assert result["billable_pipeline_started"] is False
    assert result["sla_check"]["action"] == "sla_check"


def test_manager_daily_sla_hardcheck_delegates_to_sla_check_not_scan_due(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FailingScheduledReportingService:
        def __init__(self, db: object) -> None:
            raise AssertionError("SLA task must not call scan_due_schedules")

    def fake_sla_check(args):
        calls.append({"date": args.date, "phase": args.phase})
        return {
            "status": "ok",
            "action": "sla_check",
            "report_date": "2026-06-16",
            "phase": args.phase,
        }

    fake_preflight = SimpleNamespace(sla_check=fake_sla_check)
    import report_scripts

    monkeypatch.setattr(tasks, "ScheduledReviewableReportingService", FailingScheduledReportingService)
    monkeypatch.setattr(report_scripts, "scheduled_reporting_preflight", fake_preflight, raising=False)
    monkeypatch.setitem(
        sys.modules,
        "report_scripts.scheduled_reporting_preflight",
        fake_preflight,
    )

    result = tasks.manager_daily_sla_hardcheck()

    assert calls == [{"date": "auto", "phase": "hard"}]
    assert result["task"] == "calls.manager_daily_sla_hardcheck"
    assert result["task_status"] == "completed"
    assert result["billable_pipeline_started"] is False


def test_manager_daily_sla_preflight_import_does_not_depend_on_cwd_sys_path(monkeypatch) -> None:
    core_root = Path(tasks.__file__).resolve().parents[3]

    monkeypatch.setattr(sys, "path", [item for item in sys.path if item != str(core_root)])
    monkeypatch.delitem(sys.modules, "report_scripts.scheduled_reporting_preflight", raising=False)
    monkeypatch.delitem(sys.modules, "report_scripts", raising=False)

    module = tasks._load_scheduled_reporting_preflight()

    assert hasattr(module, "sla_check")
    assert str(core_root) in sys.path


def test_manager_daily_sla_failure_alerts_and_reraises(monkeypatch) -> None:
    sent: list[dict[str, object]] = []

    def fake_load_preflight():
        raise ModuleNotFoundError("No module named 'report_scripts'")

    def fake_send_run_alert(*args, **kwargs):
        sent.append({"args": args, "kwargs": kwargs})
        return {"channel": "telegram", "status": "sent"}

    monkeypatch.setattr(tasks, "_load_scheduled_reporting_preflight", fake_load_preflight)
    monkeypatch.setattr(tasks, "send_run_alert", fake_send_run_alert)

    with pytest.raises(ModuleNotFoundError, match="report_scripts"):
        tasks.manager_daily_sla_hardcheck(report_date="2026-06-18")

    assert len(sent) == 1
    assert sent[0]["args"] == ("failed",)
    assert sent[0]["kwargs"]["run_id"] == "manager_daily_sla:2026-06-18:hard"
    assert sent[0]["kwargs"]["level"] == "critical"
    assert "scheduled_reporting_preflight.sla-check" in sent[0]["kwargs"]["operator_summary"]


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
    assert result["scope"]["scope_mode"] == "managers"


class _FakeManagerQuery:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    def filter(self, *_args: object):
        return self

    def all(self) -> list[SimpleNamespace]:
        return self.rows


class _FakeManagerDb:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    def query(self, *_args: object) -> _FakeManagerQuery:
        return _FakeManagerQuery(self.rows)


def test_daily_upstream_department_scope_resolves_active_managers_with_extensions(monkeypatch) -> None:
    department_id = "472cda28-ce71-494c-9068-25d3ffbf7399"
    other_department_id = "11111111-1111-4111-8111-111111111111"
    rows = [
        SimpleNamespace(
            id="manager-1",
            department_id=department_id,
            extension="317",
            active=True,
            name="Alice",
            email="alice@example.test",
        ),
        SimpleNamespace(
            id="manager-2",
            department_id=department_id,
            extension="",
            active=True,
            name="No Extension",
            email="noext@example.test",
        ),
        SimpleNamespace(
            id="manager-3",
            department_id=other_department_id,
            extension="325",
            active=True,
            name="Other Department",
            email="other@example.test",
        ),
    ]
    monkeypatch.setattr(
        tasks,
        "settings",
        _settings(
            call_processing_daily_upstream_scope_mode="department",
            call_processing_daily_upstream_department_id=department_id,
            call_processing_daily_upstream_manager_ids=[],
        ),
    )

    scope = tasks._daily_upstream_scope(
        tasks._parse_report_date("2026-06-15", "Asia/Almaty"),
        _FakeManagerDb(rows),
    )

    assert scope.scope_mode == "department"
    assert scope.department_id == department_id
    assert scope.manager_ids == ["manager-1"]
    assert scope.extensions == ["317"]
    assert scope.scope_manager_count == 1
    assert scope.scope_extension_count == 1
    assert scope.scope_department_count == 1
    assert "managers_without_extension_excluded:1" in scope.scope_diagnostics


def test_scheduled_upstream_company_dry_run_uses_upstream_only_and_not_reporting(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    rows = [
        SimpleNamespace(
            id="manager-1",
            department_id="472cda28-ce71-494c-9068-25d3ffbf7399",
            extension="317",
            active=True,
            name="Alice",
            email="alice@example.test",
        ),
        SimpleNamespace(
            id="manager-2",
            department_id="22222222-2222-4222-8222-222222222222",
            extension="325",
            active=True,
            name="Bob",
            email="bob@example.test",
        ),
        SimpleNamespace(
            id="robot-1",
            department_id="22222222-2222-4222-8222-222222222222",
            extension="999",
            active=True,
            name="Робот обзвона",
            email="robot@example.test",
        ),
        SimpleNamespace(
            id="inactive-1",
            department_id="33333333-3333-4333-8333-333333333333",
            extension="888",
            active=False,
            name="Inactive",
            email="inactive@example.test",
        ),
    ]

    @contextmanager
    def fake_get_db():
        yield _FakeManagerDb(rows)

    class FailingScheduledReportingService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("scheduled upstream must not instantiate reporting")

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
                run_id="run-company",
                status=ProcessingRunStatus.READY,
                scope_hash="scope-hash",
                requested_by=requested_by,
                planned={
                    "scope_mode": scope.scope_mode,
                    "scope_manager_count": scope.scope_manager_count,
                    "scope_extension_count": scope.scope_extension_count,
                    "scope_department_count": scope.scope_department_count,
                    "scope_diagnostics": scope.scope_diagnostics,
                    "provider_calls_made": 0,
                },
                quota={"provider_calls_made": 0},
                costs={"forecast": True, "total_current_run_cost_usdt": 0.0},
            )

    monkeypatch.setattr(
        tasks,
        "settings",
        _settings(
            call_processing_daily_upstream_scope_mode="company",
            call_processing_daily_upstream_department_id="",
            call_processing_daily_upstream_manager_ids=[],
            call_processing_daily_upstream_provider_call_budget=0,
        ),
    )
    monkeypatch.setattr(tasks, "get_db", fake_get_db)
    monkeypatch.setattr(tasks, "ScheduledReviewableReportingService", FailingScheduledReportingService)
    monkeypatch.setattr(tasks, "CallProcessingService", FakeCallProcessingService)

    result = tasks.ensure_daily_call_processing_upstream(report_date="2026-06-15", dry_run=True)

    assert result["task_status"] == "completed"
    assert result["scope_mode"] == "company"
    assert result["billable_pipeline_started"] is False
    assert result["required_artifacts"] == [
        "transcript",
        "transcript_segments",
        "llm1_first_pass",
    ]
    assert "department_id" not in result["scope"]
    assert result["scope"]["manager_ids"] == ["manager-1", "manager-2"]
    assert result["scope"]["extensions"] == ["317", "325"]
    assert result["scope_manager_count"] == 2
    assert result["scope_extension_count"] == 2
    assert result["scope_department_count"] == 2
    assert "technical_managers_excluded:1" in result["scope_diagnostics"]
    assert "inactive_managers_excluded:1" in result["scope_diagnostics"]
    assert len(calls) == 1
    assert [item.value for item in calls[0]["required_artifacts"]] == [
        "transcript",
        "transcript_segments",
        "llm1_first_pass",
    ]
    assert calls[0]["mode"].value == "dry_run"


def test_daily_upstream_onlinepbx_all_scope_uses_fallback_without_manager_directory(monkeypatch) -> None:
    class FailingManagerDb:
        def query(self, *_args: object):
            raise AssertionError("onlinepbx_all scope must not read manager directory")

    monkeypatch.setattr(
        tasks,
        "settings",
        _settings(
            call_processing_daily_upstream_scope_mode="onlinepbx_all",
            call_processing_daily_upstream_department_id="472cda28-ce71-494c-9068-25d3ffbf7399",
            call_processing_daily_upstream_manager_ids=["manager-should-not-be-used"],
            call_processing_daily_upstream_min_duration_sec=15,
        ),
    )

    scope = tasks._daily_upstream_scope(
        tasks._parse_report_date("2026-06-15", "Asia/Almaty"),
        FailingManagerDb(),
    )

    assert scope.scope_mode == "onlinepbx_all"
    assert scope.department_id is None
    assert scope.fallback_department_id == "472cda28-ce71-494c-9068-25d3ffbf7399"
    assert scope.manager_ids == []
    assert scope.extensions == []
    assert scope.scope_manager_count == 0
    assert scope.scope_extension_count == 0
    assert scope.scope_department_count == 1
    assert scope.min_duration_sec == 15
    assert "onlinepbx_all_no_manager_directory_scope" in scope.scope_diagnostics


def test_scheduled_upstream_company_budget_alert_uses_short_operator_summary(monkeypatch) -> None:
    sent: list[dict[str, object]] = []

    def fake_send_run_alert(*args, **kwargs):
        sent.append({"args": args, "kwargs": kwargs})
        return {"channel": "email", "status": "sent"}

    monkeypatch.setattr(tasks, "send_run_alert", fake_send_run_alert)

    alert = tasks._send_daily_upstream_alert(
        "blocked",
        run_id="run-company-budget",
        status="blocked",
        title="Daily call-processing upstream needs attention",
        level="warning",
        scope={
            "scope_mode": "company",
            "date_from": "2026-06-15",
            "date_to": "2026-06-15",
        },
        counts={
            "scope_mode": "company",
            "provider_calls_estimate": 4,
            "provider_calls_budget": 3,
            "provider_calls_budget_status": "over_budget",
            "forecast_budget_status": "over_budget",
            "quota_blocked": 1,
        },
        errors=[{"reason": "provider_calls_budget_insufficient", "raw": {"hidden": True}}],
        details={
            "quota": {
                "quota_exhausted": True,
                "provider_calls_estimate": 4,
                "provider_calls_budget": 3,
            },
            "costs": {
                "forecast_budget_status": "over_budget",
                "raw": {"hidden": True},
            },
        },
    )

    assert alert["kind"] == "scheduled_call_processing_upstream"
    assert len(sent) == 1
    summary = sent[0]["kwargs"]["operator_summary"]
    assert summary.startswith("Корпоративная транскрибация за 2026-06-15")
    assert "прогноз 4 provider calls превышает budget 3" in summary
    assert "Влияние:" in summary
    assert "Действие:" in summary
    assert "{" not in summary
    assert "raw" not in summary
