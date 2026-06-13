from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.agents.call_processing import ArtifactKind, ArtifactStatus, LLM1FirstPassPayload
from app.agents.call_processing.schemas import EnsureMode, EnsureResponse, ProcessingRunStatus
from app.agents.calls.reporting import (
    CallsManualReportingOrchestrator,
    ReportRunFilters,
    resolve_report_preset,
)


def _interaction(*, text: str = "Готовый транскрипт") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        department_id=uuid4(),
        manager_id=uuid4(),
        type="call",
        text=text,
        raw_ref="https://example.test/audio.mp3",
        source="onlinepbx",
        duration_sec=180,
        metadata_={
            "call_date": "2026-06-03 10:00:00",
            "source_status": "answered",
            "direction": "out",
            "extension": "322",
        },
    )


def _analysis() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        interaction_id=uuid4(),
        instruction_version="edo_sales_mvp1_call_analysis_v15",
        score_total=80.0,
        is_failed=False,
        fail_reason=None,
        created_at=datetime(2026, 6, 3, 10, 10, tzinfo=UTC),
        scores_detail={
            "classification": {"call_type": "sales_primary"},
            "score": {"checklist_score": {"score_percent": 80.0}},
            "score_by_stage": [],
            "strengths": [{"title": "Контакт установлен"}],
            "gaps": [],
            "recommendations": [],
            "follow_up": {},
        },
    )


def _llm1_payload() -> LLM1FirstPassPayload:
    return LLM1FirstPassPayload(
        prompt_version="llm1_v1",
        provider="openai",
        model="gpt-test",
        account_alias="primary",
        classification={"call_type": "sales_primary"},
        summary={"brief": "Клиент попросил материалы."},
        follow_up={"next_step": "Отправить материалы."},
        data_quality={"transcript_quality": "sufficient"},
        analysis_focus=["Проверить договоренность."],
    )


class _FakeCallProcessingClient:
    def __init__(
        self,
        *,
        payload: LLM1FirstPassPayload | None,
        rows: list[SimpleNamespace] | None = None,
    ) -> None:
        self.payload = payload
        self.rows = rows or []
        self.artifact_reads = 0
        self.llm1_reads: list[str] = []

    def ensure_processed_calls(self, *_args, **_kwargs):
        raise AssertionError("ensure is not part of _prepare_artifacts focused test")

    def get_processed_artifacts(self, *_args, **_kwargs):
        self.artifact_reads += 1
        return self.rows

    def get_llm1_first_pass_artifact(self, interaction_id):
        self.llm1_reads.append(str(interaction_id))
        return self.payload


class _FakeEnsureClient:
    def __init__(self) -> None:
        self.ensure_calls: list[dict[str, object]] = []

    def ensure_processed_calls(self, *_args, **_kwargs):
        raise AssertionError("reporting should use async ensure in async run path")

    async def ensure_processed_calls_async(self, scope, required_artifacts, mode=EnsureMode.ENSURE):
        self.ensure_calls.append(
            {
                "scope": scope,
                "required_artifacts": list(required_artifacts),
                "mode": mode,
            }
        )
        return EnsureResponse(
            run_id="run-ensure",
            status=ProcessingRunStatus.READY,
            scope_hash="hash-ensure",
            requested_by="edo-analysis-reporting",
            planned={
                "interactions_total": 3,
                "artifacts_ready": 6,
                "artifacts_missing": 1,
                "artifacts_backfilled": 2,
            },
            quota={"provider_calls_made": 4},
        )


class _NoEnsureClient:
    def ensure_processed_calls(self, *_args, **_kwargs):
        raise AssertionError("rop_weekly must not call call-processing ensure")

    async def ensure_processed_calls_async(self, *_args, **_kwargs):
        raise AssertionError("rop_weekly must not call call-processing ensure")


def _make_orchestrator(client: _FakeCallProcessingClient) -> CallsManualReportingOrchestrator:
    orchestrator = object.__new__(CallsManualReportingOrchestrator)
    orchestrator.department_id = uuid4()
    orchestrator.call_processing_client = client
    orchestrator.extractor = SimpleNamespace(
        process=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("external_service mode must not run STT from reporting")
        )
    )
    orchestrator.call_orchestrator = SimpleNamespace(
        persist_analysis=lambda **kwargs: kwargs["result"],
        persist_failed_analysis=lambda **kwargs: _analysis(),
    )
    setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **_kwargs: {})
    setattr(orchestrator, "_load_managers_by_id", lambda **_kwargs: {})
    return orchestrator


def test_prepare_artifacts_external_service_injects_llm1_artifact_without_stt() -> None:
    interaction = _interaction()
    captured: dict[str, object] = {}
    client = _FakeCallProcessingClient(payload=_llm1_payload())
    orchestrator = _make_orchestrator(client)

    def _analyze_call(item, **kwargs):
        captured["interaction_id"] = item.id
        captured["llm1_first_pass_artifact"] = kwargs.get("llm1_first_pass_artifact")
        return _analysis()

    orchestrator.analyzer = SimpleNamespace(analyze_call=_analyze_call)

    previous = os.environ.get("CALL_PROCESSING_MODE")
    os.environ["CALL_PROCESSING_MODE"] = "external_service"
    try:
        artifacts, build_summary, build_errors = asyncio.run(
            CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[interaction],
                preset=resolve_report_preset("manager_daily"),
                mode="build_missing_and_report",
            )
        )
    finally:
        if previous is None:
            os.environ.pop("CALL_PROCESSING_MODE", None)
        else:
            os.environ["CALL_PROCESSING_MODE"] = previous

    assert len(artifacts) == 1
    assert build_summary["analyses_built"] == 1
    assert build_summary["call_processing_mode"] == "external_service"
    assert build_summary["missing_llm1_first_pass_before_analysis"] == 0
    assert build_errors == []
    assert captured["interaction_id"] == interaction.id
    assert isinstance(captured["llm1_first_pass_artifact"], LLM1FirstPassPayload)
    assert client.llm1_reads == [str(interaction.id)]


def test_prepare_artifacts_external_service_missing_llm1_is_partial_not_provider_call() -> None:
    interaction = _interaction()
    client = _FakeCallProcessingClient(payload=None)
    orchestrator = _make_orchestrator(client)
    orchestrator.analyzer = SimpleNamespace(
        analyze_call=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("missing upstream LLM1 must not call analyzer")
        )
    )

    previous = os.environ.get("CALL_PROCESSING_MODE")
    os.environ["CALL_PROCESSING_MODE"] = "external_service"
    try:
        artifacts, build_summary, build_errors = asyncio.run(
            CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[interaction],
                preset=resolve_report_preset("manager_daily"),
                mode="build_missing_and_report",
            )
        )
    finally:
        if previous is None:
            os.environ.pop("CALL_PROCESSING_MODE", None)
        else:
            os.environ["CALL_PROCESSING_MODE"] = previous

    assert len(artifacts) == 1
    assert artifacts[0].analysis is None
    assert build_summary["analyses_built"] == 0
    assert build_summary["missing_llm1_first_pass_before_analysis"] == 1
    assert build_errors == [f"llm1_first_pass_missing:{interaction.id}"]


def test_prepare_artifacts_marks_late_source_artifacts_without_auto_rerun() -> None:
    interaction = _interaction()
    ready_analysis = _analysis()
    ready_analysis.interaction_id = interaction.id
    ready_analysis.created_at = datetime(2026, 6, 3, 10, 10, tzinfo=UTC)
    late_row = SimpleNamespace(
        interaction_id=interaction.id,
        artifact_kind=ArtifactKind.LLM1_FIRST_PASS.value,
        status=ArtifactStatus.READY.value,
        is_active=True,
        source_updated_at=datetime(2026, 6, 3, 10, 30, tzinfo=UTC),
        updated_at=datetime(2026, 6, 3, 10, 30, tzinfo=UTC),
    )
    client = _FakeCallProcessingClient(payload=_llm1_payload(), rows=[late_row])
    orchestrator = _make_orchestrator(client)
    orchestrator.analyzer = SimpleNamespace(
        analyze_call=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("late marker must not automatically rerun analysis")
        )
    )
    setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **_kwargs: {interaction.id: ready_analysis})

    previous = os.environ.get("CALL_PROCESSING_MODE")
    os.environ["CALL_PROCESSING_MODE"] = "external_service"
    try:
        artifacts, build_summary, build_errors = asyncio.run(
            CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[interaction],
                preset=resolve_report_preset("manager_daily"),
                mode="build_missing_and_report",
            )
        )
    finally:
        if previous is None:
            os.environ.pop("CALL_PROCESSING_MODE", None)
        else:
            os.environ["CALL_PROCESSING_MODE"] = previous

    assert artifacts[0].analysis is ready_analysis
    assert artifacts[0].analysis_reuse_reason == "source_artifacts_updated_after_analysis"
    assert build_summary["analyses_reused"] == 1
    assert build_summary["source_artifacts_updated_after_analysis"] == 1
    assert build_errors == [f"source_artifacts_updated_after_analysis:{interaction.id}"]


def test_prepare_artifacts_force_rebuild_supersedes_late_source_marker() -> None:
    interaction = _interaction()
    stale_analysis = _analysis()
    stale_analysis.interaction_id = interaction.id
    stale_analysis.created_at = datetime(2026, 6, 3, 10, 10, tzinfo=UTC)
    rebuilt_analysis = _analysis()
    rebuilt_analysis.interaction_id = interaction.id
    rebuilt_analysis.created_at = datetime(2026, 6, 3, 10, 45, tzinfo=UTC)
    late_row = SimpleNamespace(
        interaction_id=interaction.id,
        artifact_kind=ArtifactKind.LLM1_FIRST_PASS.value,
        status=ArtifactStatus.READY.value,
        is_active=True,
        source_updated_at=datetime(2026, 6, 3, 10, 30, tzinfo=UTC),
        updated_at=datetime(2026, 6, 3, 10, 30, tzinfo=UTC),
    )
    client = _FakeCallProcessingClient(payload=_llm1_payload(), rows=[late_row])
    orchestrator = _make_orchestrator(client)
    captured: dict[str, object] = {}

    def _analyze_call(item, **kwargs):
        captured["interaction_id"] = item.id
        captured["llm1_first_pass_artifact"] = kwargs.get("llm1_first_pass_artifact")
        return rebuilt_analysis

    orchestrator.analyzer = SimpleNamespace(analyze_call=_analyze_call)
    orchestrator.call_orchestrator = SimpleNamespace(
        persist_analysis=lambda **_kwargs: rebuilt_analysis,
        persist_failed_analysis=lambda **kwargs: _analysis(),
    )
    setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **_kwargs: {interaction.id: stale_analysis})

    previous = os.environ.get("CALL_PROCESSING_MODE")
    os.environ["CALL_PROCESSING_MODE"] = "external_service"
    try:
        artifacts, build_summary, build_errors = asyncio.run(
            CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[interaction],
                preset=resolve_report_preset("manager_daily"),
                mode="build_missing_and_report",
                force_rebuild_analyses=True,
            )
        )
    finally:
        if previous is None:
            os.environ.pop("CALL_PROCESSING_MODE", None)
        else:
            os.environ["CALL_PROCESSING_MODE"] = previous

    assert artifacts[0].analysis is rebuilt_analysis
    assert artifacts[0].original_analysis is stale_analysis
    assert artifacts[0].analysis_reuse_reason == "reusable"
    assert captured["interaction_id"] == interaction.id
    assert isinstance(captured["llm1_first_pass_artifact"], LLM1FirstPassPayload)
    assert build_summary["analyses_built"] == 1
    assert build_summary["analyses_reused"] == 0
    assert build_summary["source_artifacts_updated_after_analysis"] == 0
    assert build_summary["source_artifacts_force_rebuilt_after_update"] == 1
    assert build_errors == []


def test_manager_daily_external_service_ensure_uses_async_client_and_exposes_source_summary() -> None:
    client = _FakeEnsureClient()
    orchestrator = object.__new__(CallsManualReportingOrchestrator)
    orchestrator.department_id = uuid4()
    orchestrator.call_processing_client = client

    summary = asyncio.run(
        CallsManualReportingOrchestrator._ensure_call_processing_source_artifacts(
            orchestrator,
            filters=ReportRunFilters(
                manager_extensions={"322"},
                date_from="2026-06-03",
                date_to="2026-06-03",
                min_duration_sec=30,
            ),
            period={"date_from": "2026-06-03", "date_to": "2026-06-03"},
            mode="build_missing_and_report",
        )
    )

    assert len(client.ensure_calls) == 1
    assert client.ensure_calls[0]["mode"] == EnsureMode.ENSURE
    assert summary["call_processing_mode"] == "external_service"
    assert summary["call_processing_run_id"] == "run-ensure"
    assert summary["call_processing_artifacts_ready"] == 6
    assert summary["call_processing_artifacts_missing"] == 1
    assert summary["call_processing_artifacts_backfilled"] == 2
    assert summary["call_processing_provider_calls_made"] == 4
    assert summary["targeted_source_records_total"] == 3


def test_rop_weekly_external_service_remains_persisted_only_and_does_not_ensure() -> None:
    orchestrator = object.__new__(CallsManualReportingOrchestrator)
    orchestrator.department_id = uuid4()
    orchestrator.call_processing_client = _NoEnsureClient()
    orchestrator.db = SimpleNamespace()
    setattr(
        orchestrator,
        "_collect_run_diagnostics_context",
        lambda **kwargs: {
            "department_id": str(orchestrator.department_id),
            "department_name": "Pilot Department",
            "preset": kwargs["preset"].code,
            "execution_model": CallsManualReportingOrchestrator._resolve_execution_model(
                preset=kwargs["preset"]
            ),
            "mode": kwargs["mode"],
            "period": kwargs["period"],
            "analysis_instruction_version": None,
            "selected_manager_ids": [],
            "selected_manager_extensions": [],
            "manager_filter_logic": "department_scope",
            "missing_local_manager_ids": [],
            "period_only_interactions_count": 0,
            "manager_only_interactions_count": 0,
            "extension_only_interactions_count": 0,
        },
    )
    setattr(orchestrator, "_select_interactions", lambda **_kwargs: [])

    previous = os.environ.get("CALL_PROCESSING_MODE")
    os.environ["CALL_PROCESSING_MODE"] = "external_service"
    try:
        result = asyncio.run(
            CallsManualReportingOrchestrator.run_report(
                orchestrator,
                preset_code="rop_weekly",
                mode="build_missing_and_report",
                filters=ReportRunFilters(date_from="2026-06-01", date_to="2026-06-07"),
                delivery_mode="preview_only",
            )
        )
    finally:
        if previous is None:
            os.environ.pop("CALL_PROCESSING_MODE", None)
        else:
            os.environ["CALL_PROCESSING_MODE"] = previous

    assert result["preset"] == "rop_weekly"
    assert result["status"] == "no_data"
    assert result["observability"]["summary"]["source"]["execution_model"] == "persisted_only"
    assert "call_processing_mode" not in result["observability"]["summary"]["source"]
    assert result["diagnostics"]["execution_model"] == "persisted_only"
    assert any("rop_weekly uses persisted-only execution" in note for note in result["diagnostics"]["notes"])
