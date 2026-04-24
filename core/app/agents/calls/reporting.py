"""Manual reporting pilot orchestration for bounded report runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.agents.calls.analyzer import (
    APPROVED_CHECKLIST_VERSION,
    CallsAnalyzer,
    SEMANTIC_EMPTY_ANALYSIS_REASON,
)
from app.agents.calls.bitrix_readonly import Bitrix24ReadOnlyClient, BitrixReadOnlyError
from app.agents.calls.delivery import CallsDelivery
from app.agents.calls.extractor import CallsExtractor
from app.agents.calls.intake import OnlinePBXIntake
from app.agents.calls.orchestrator import CallsManualPilotOrchestrator
from app.agents.calls.report_templates import get_active_template_version, render_report_artifact
from app.core_shared.db.models import Analysis, Department, Interaction, Manager
from app.core_shared.exceptions import ASAError, DeliveryError, SemanticAnalysisError

REPORTING_SCHEMA_VERSION = "manual_reporting_pilot_v1"
REPORTING_LOGIC_VERSION = "manual_reporting_logic_v1"
REPORTING_REUSE_POLICY_VERSION = "manual_reporting_reuse_v3"
REPORTING_MONITORING_EMAIL = "sales@dogovor24.kz"
REPORTING_ALLOWED_MODES = {
    "build_missing_and_report",
    "report_from_ready_data_only",
}
MANAGER_DAILY_MAX_WINDOW_WORKDAYS = 3
MANAGER_DAILY_FULL_REPORT_MIN_RELEVANT_CALLS = 6
MANAGER_DAILY_FULL_REPORT_MIN_READY_ANALYSES = 5
MANAGER_DAILY_FULL_REPORT_MIN_ANALYSIS_COVERAGE = 75.0
MANAGER_DAILY_SIGNAL_REPORT_MIN_READY_ANALYSES = 2
MANAGER_DAILY_FALLBACK_RECOMMENDATION_TITLE = "Пока недостаточно рекомендаций"
MANAGER_DAILY_FALLBACK_KEY_PROBLEM_TITLE = "Требует уточнения"
MANAGER_DAILY_FALLBACK_KEY_PROBLEM_DESCRIPTION = "Недостаточно данных для выделения одной главной проблемы."
REPORTING_REQUIRED_ANALYSIS_KEYS = (
    "classification",
    "score",
    "score_by_stage",
    "strengths",
    "gaps",
    "recommendations",
    "follow_up",
)


@dataclass(slots=True)
class ReportRunFilters:
    """Normalized manual filters for one report run."""

    manager_ids: set[str] = field(default_factory=set)
    manager_extensions: set[str] = field(default_factory=set)
    date_from: str = ""
    date_to: str = ""
    min_duration_sec: int | None = None
    max_duration_sec: int | None = None


@dataclass(slots=True)
class ReportPreset:
    """One supported reporting preset."""

    code: str
    title: str
    recipient_kind: str
    requires_single_day: bool = False


@dataclass(slots=True)
class ReportArtifact:
    """Persisted artifacts needed for one report call row."""

    interaction: Interaction
    analysis: Analysis | None
    manager: Manager | None
    call_started_at: datetime | None


@dataclass(slots=True, frozen=True)
class ManagerDailyWindow:
    """One candidate rolling window for manager_daily readiness."""

    workdays_used: int
    period: dict[str, str]
    included_days: tuple[str, ...]


def resolve_report_preset(code: str) -> ReportPreset:
    """Return the bounded preset config for the requested code."""
    normalized = code.strip().lower()
    presets = {
        "manager_daily": ReportPreset(
            code="manager_daily",
            title="Ежедневный разбор звонков",
            recipient_kind="manager",
            requires_single_day=True,
        ),
        "rop_weekly": ReportPreset(
            code="rop_weekly",
            title="Еженедельный отчёт",
            recipient_kind="rop",
        ),
    }
    preset = presets.get(normalized)
    if preset is None:
        supported = ", ".join(sorted(presets))
        raise ASAError(f"Unsupported report preset '{code}'. Supported presets: {supported}.")
    return preset


class CallsManualReportingOrchestrator:
    """Build bounded manual reports from persisted call artifacts."""

    def __init__(self, department_id: str, db: Session):
        self.department_id = UUID(department_id)
        self.db = db
        self.intake = OnlinePBXIntake(department_id=department_id, db=db)
        self.extractor = CallsExtractor(department_id=department_id, db=db)
        self.analyzer = CallsAnalyzer(department_id=department_id, db=db)
        self.delivery = CallsDelivery(department_id=department_id, db=db)
        self.call_orchestrator = CallsManualPilotOrchestrator(
            department_id=department_id,
            db=db,
        )

    async def run_report(
        self,
        *,
        preset_code: str,
        mode: str,
        filters: ReportRunFilters,
        model_override: str | None = None,
        send_email: bool = True,
    ) -> dict[str, Any]:
        """Execute one bounded manual reporting run."""
        preset = resolve_report_preset(preset_code)
        normalized_mode = mode.strip().lower()
        if normalized_mode not in REPORTING_ALLOWED_MODES:
            allowed = ", ".join(sorted(REPORTING_ALLOWED_MODES))
            raise ASAError(f"Unsupported report mode '{mode}'. Supported modes: {allowed}.")

        period = self._build_period(filters=filters, preset=preset)
        source_period = period
        manager_daily_windows: list[ManagerDailyWindow] = []
        if preset.code == "manager_daily":
            manager_daily_windows = self._build_manager_daily_windows(anchor_day=period["date_from"])
            source_period = manager_daily_windows[-1].period
        diagnostics_context = self._collect_run_diagnostics_context(
            preset=preset,
            mode=normalized_mode,
            filters=filters,
            period=source_period,
        )
        execution_model = self._resolve_execution_model(preset=preset)
        source_summary = self._empty_source_summary(period=source_period, execution_model=execution_model)
        source_discovery_errors: list[str] = []
        if self._allows_source_discovery(preset=preset):
            try:
                source_summary = self._discover_and_persist_source_calls(
                    filters=filters,
                    period=source_period,
                    mode=normalized_mode,
                )
                source_summary["execution_model"] = execution_model
            except ASAError as exc:
                error_token = f"source_discovery_failed:{exc}"
                if normalized_mode == "report_from_ready_data_only":
                    # Non-fatal in ready-only mode: report from whatever is already persisted.
                    source_discovery_errors.append(error_token)
                else:
                    return self._build_terminal_run_result(
                        preset=preset,
                        mode=normalized_mode,
                        period=period,
                        source_period=source_period,
                        diagnostics_context=diagnostics_context,
                        filters=filters,
                        source_summary=self._empty_source_summary(period=source_period, execution_model=execution_model),
                        build_summary=self._empty_build_summary(),
                        reports=[],
                        selected_interactions_count=0,
                        final_selected_interactions_count=0,
                        overall_status="blocked",
                        errors=[error_token],
                        artifacts=[],
                    )
        interactions = self._select_interactions(filters=filters, period=source_period)
        if not interactions:
            if preset.code == "manager_daily":
                shell_report = self._build_manager_daily_empty_state_result(
                    status="no_data",
                    artifacts=[],
                    period=period,
                    filters=filters,
                    mode=normalized_mode,
                    model_override=model_override,
                    send_email=send_email,
                    reason_codes=["no_interactions_for_selected_filters"],
                    relevant_calls=0,
                    ready_analyses=0,
                    analysis_coverage=0.0,
                    missing=["no_interactions_for_selected_filters"],
                    readiness=None,
                )
                return self._build_terminal_run_result(
                    preset=preset,
                    mode=normalized_mode,
                    period=period,
                    source_period=source_period,
                    diagnostics_context=diagnostics_context,
                    filters=filters,
                    source_summary=source_summary,
                    build_summary=self._empty_build_summary(),
                    reports=[shell_report],
                    selected_interactions_count=0,
                    final_selected_interactions_count=0,
                    overall_status="no_data",
                    errors=["no_interactions_for_selected_filters"],
                    artifacts=[],
                )
            return self._build_terminal_run_result(
                preset=preset,
                mode=normalized_mode,
                period=period,
                source_period=source_period,
                diagnostics_context=diagnostics_context,
                filters=filters,
                source_summary=source_summary,
                build_summary=self._empty_build_summary(),
                reports=[],
                selected_interactions_count=0,
                final_selected_interactions_count=0,
                overall_status="no_data",
                errors=["no_interactions_for_selected_filters"],
                artifacts=[],
            )

        artifacts, build_summary, build_errors = await self._prepare_artifacts(
            interactions=interactions,
            preset=preset,
            mode=normalized_mode,
        )

        reports = self._group_and_build_reports(
            preset=preset,
            artifacts=artifacts,
            period=period,
            source_period=source_period,
            filters=filters,
            mode=normalized_mode,
            model_override=model_override,
            send_email=send_email,
            manager_daily_windows=manager_daily_windows,
        )
        all_errors = [*source_discovery_errors, *build_errors]
        overall_status = self._derive_run_overall_status(reports=reports, build_errors=all_errors)
        return self._build_terminal_run_result(
            preset=preset,
            mode=normalized_mode,
            period=period,
            source_period=source_period,
            diagnostics_context=diagnostics_context,
            filters=filters,
            source_summary=source_summary,
            build_summary=build_summary,
            reports=reports,
            selected_interactions_count=len(interactions),
            final_selected_interactions_count=sum(
                item.get("payload", {}).get("meta", {}).get("source_artifacts", {}).get("interaction_count", 0)
                for item in reports
                if item.get("payload")
            ),
            overall_status=overall_status,
            errors=all_errors,
            send_email=send_email,
            artifacts=artifacts,
        )

    def _build_terminal_run_result(
        self,
        *,
        preset: ReportPreset,
        mode: str,
        period: dict[str, str],
        source_period: dict[str, str],
        diagnostics_context: dict[str, Any],
        filters: ReportRunFilters,
        source_summary: dict[str, int],
        build_summary: dict[str, int],
        reports: list[dict[str, Any]],
        selected_interactions_count: int,
        final_selected_interactions_count: int,
        overall_status: str,
        errors: list[str] | None = None,
        send_email: bool = True,
        artifacts: list[ReportArtifact] | None = None,
    ) -> dict[str, Any]:
        """Build the final structured run response for success and blocked outcomes."""
        return {
            "status": overall_status,
            "preset": preset.code,
            "mode": mode,
            "period": period,
            "selected_interactions": selected_interactions_count,
            "prepared_artifacts": build_summary,
            "reports": reports,
            "errors": list(errors or []),
            "observability": self._build_run_observability(
                preset=preset,
                source_summary=source_summary,
                period=period,
                source_period=source_period,
                mode=mode,
                send_email=send_email,
                selected_interactions_count=selected_interactions_count,
                build_summary=build_summary,
                reports=reports,
                overall_status=overall_status,
                errors=errors,
                artifacts=artifacts or [],
            ),
            "diagnostics": self._build_run_diagnostics(
                preset=preset,
                mode=mode,
                period=period,
                source_period=source_period,
                filters=filters,
                diagnostics_context=diagnostics_context,
                build_summary=build_summary,
                reports=reports,
                selected_interactions_count=selected_interactions_count,
                final_selected_interactions_count=final_selected_interactions_count,
                overall_status=overall_status,
                source_summary=source_summary,
                errors=errors or [],
            ),
        }

    @staticmethod
    def _derive_run_overall_status(
        *,
        reports: list[dict[str, Any]],
        build_errors: list[str],
    ) -> str:
        """Collapse report-level results into one run-level status."""
        statuses = {item.get("status") for item in reports}
        if not reports:
            return "blocked" if build_errors else "completed"
        had_success = any(status in {"ready", "delivered", "partial"} for status in statuses)
        had_skip = "skip_accumulate" in statuses
        had_blocking = any(status in {"missing_artifacts", "blocked"} for status in statuses) or bool(build_errors)
        if had_success and had_blocking:
            return "partial"
        if had_success:
            return "completed"
        if had_skip and had_blocking:
            return "partial"
        if had_skip:
            return "completed"
        return "blocked"

    @staticmethod
    def _empty_source_summary(*, period: dict[str, str], execution_model: str) -> dict[str, Any]:
        """Return a zeroed source summary for blocked early exits."""
        days_scanned = (date.fromisoformat(period["date_to"]) - date.fromisoformat(period["date_from"])).days + 1
        return {
            "execution_model": execution_model,
            "days_scanned": max(days_scanned, 0),
            "source_records_total": 0,
            "eligible_source_records_total": 0,
            "targeted_source_records_total": 0,
            "already_persisted_source_records_total": 0,
            "missing_source_records_total": 0,
            "ingest_created_total": 0,
            "ingest_skipped_total": 0,
        }

    @staticmethod
    def _resolve_execution_model(*, preset: ReportPreset) -> str:
        """Return the standing execution model for the selected preset."""
        if preset.code == "manager_daily":
            return "source_aware_full_manual"
        return "persisted_only"

    @classmethod
    def _allows_source_discovery(cls, *, preset: ReportPreset) -> bool:
        """Return True when the preset may perform source discovery and ingest."""
        return cls._resolve_execution_model(preset=preset) == "source_aware_full_manual"

    @classmethod
    def _allows_build_missing(cls, *, preset: ReportPreset, mode: str) -> bool:
        """Return True when the preset may build missing transcript/analysis artifacts."""
        return (
            cls._resolve_execution_model(preset=preset) == "source_aware_full_manual"
            and mode == "build_missing_and_report"
        )

    @staticmethod
    def _empty_build_summary() -> dict[str, int]:
        """Return a zeroed artifact summary for blocked early exits."""
        return {
            "transcripts_built": 0,
            "transcripts_reused": 0,
            "analyses_built": 0,
            "analyses_reused": 0,
            "analyses_rejected_for_reuse": 0,
            "missing_transcripts_before_build": 0,
            "missing_analyses_before_build": 0,
            "transcript_build_failed": 0,
            "analysis_build_failed": 0,
        }

    def _discover_and_persist_source_calls(
        self,
        *,
        filters: ReportRunFilters,
        period: dict[str, str],
        mode: str,
    ) -> dict[str, int]:
        """Discover source calls for the selected period and persist any missing interactions."""
        source_extensions = self._resolve_source_extensions(filters=filters)
        days_scanned = 0
        records_total = 0
        eligible_total = 0
        targeted_total = 0
        already_persisted_total = 0
        missing_before_ingest_total = 0
        ingest_created_total = 0
        ingest_skipped_total = 0

        for day in self._iter_period_days(period=period):
            days_scanned += 1
            records = self.intake.get_cdr_list(day)
            records_total += len(records)
            eligible = self.intake.filter_eligible(records)
            eligible_total += len(eligible)
            targeted = [
                record
                for record in eligible
                if self._record_matches_source_filters(
                    record=record,
                    filters=filters,
                    source_extensions=source_extensions,
                )
            ]
            targeted_total += len(targeted)
            if not targeted:
                continue

            existing_external_ids = {
                row.external_id
                for row in self.db.query(Interaction.external_id)
                .filter(
                    Interaction.department_id == self.department_id,
                    Interaction.external_id.in_([record.call_id for record in targeted]),
                )
                .all()
            }
            already_persisted_total += len(existing_external_ids)
            missing_before_ingest_total += len(
                [record for record in targeted if record.call_id not in existing_external_ids]
            )

            if mode == "build_missing_and_report":
                for record in targeted:
                    if not record.record_url:
                        record.record_url = self.intake.get_recording_url(record.call_id)

            created, skipped = self.intake.save_interactions(targeted)
            ingest_created_total += created
            ingest_skipped_total += skipped

        return {
            "days_scanned": days_scanned,
            "source_records_total": records_total,
            "eligible_source_records_total": eligible_total,
            "targeted_source_records_total": targeted_total,
            "already_persisted_source_records_total": already_persisted_total,
            "missing_source_records_total": missing_before_ingest_total,
            "ingest_created_total": ingest_created_total,
            "ingest_skipped_total": ingest_skipped_total,
        }

    @staticmethod
    def _iter_period_days(*, period: dict[str, str]) -> list[str]:
        """Return workday YYYY-MM-DD days inside the selected period (weekends skipped)."""
        current = date.fromisoformat(period["date_from"])
        end = date.fromisoformat(period["date_to"])
        days: list[str] = []
        while current <= end:
            if current.weekday() < 5:
                days.append(current.isoformat())
            current += timedelta(days=1)
        return days

    def _resolve_source_extensions(self, *, filters: ReportRunFilters) -> set[str]:
        """Resolve effective source-side extension filters from manager ids/extensions."""
        extensions = {item.strip() for item in filters.manager_extensions if item.strip()}
        if not filters.manager_ids:
            return extensions
        try:
            manager_ids = {UUID(item) for item in filters.manager_ids}
        except ValueError as exc:
            raise ASAError("manager_ids must contain valid UUID values.") from exc
        rows = (
            self.db.query(Manager)
            .filter(
                Manager.department_id == self.department_id,
                Manager.id.in_(manager_ids),
            )
            .all()
        )
        for row in rows:
            if row.extension:
                extensions.add(str(row.extension).strip())
        return {item for item in extensions if item}

    @staticmethod
    def _record_matches_source_filters(
        *,
        record: Any,
        filters: ReportRunFilters,
        source_extensions: set[str],
    ) -> bool:
        """Return True when the source record matches the selected report filters."""
        if filters.min_duration_sec is not None and (record.talk_duration or 0) < filters.min_duration_sec:
            return False
        if filters.max_duration_sec is not None and record.talk_duration is not None:
            if record.talk_duration > filters.max_duration_sec:
                return False
        if source_extensions and str(record.extension or "").strip() not in source_extensions:
            return False
        return True

    def _build_period(self, *, filters: ReportRunFilters, preset: ReportPreset) -> dict[str, str]:
        """Validate and normalize date bounds."""
        if not filters.date_from:
            raise ASAError("Provide date_from for manual report run.")
        date_to = filters.date_to or filters.date_from
        start_date = date.fromisoformat(filters.date_from)
        end_date = date.fromisoformat(date_to)
        if end_date < start_date:
            raise ASAError("date_to must be greater than or equal to date_from.")
        if preset.requires_single_day and start_date != end_date:
            raise ASAError(f"Preset '{preset.code}' currently supports one selected day only.")
        return {
            "date_from": start_date.isoformat(),
            "date_to": end_date.isoformat(),
        }

    @staticmethod
    def _build_manager_daily_windows(*, anchor_day: str) -> list[ManagerDailyWindow]:
        """Return rolling 1/2/3-workday windows anchored at the requested day."""
        anchor = date.fromisoformat(anchor_day)
        windows: list[ManagerDailyWindow] = []
        for workdays_used in range(1, MANAGER_DAILY_MAX_WINDOW_WORKDAYS + 1):
            included_days = tuple(_last_workdays(anchor=anchor, count=workdays_used))
            windows.append(
                ManagerDailyWindow(
                    workdays_used=workdays_used,
                    period={
                        "date_from": included_days[0],
                        "date_to": included_days[-1],
                    },
                    included_days=included_days,
                )
            )
        return windows

    def _select_interactions(
        self,
        *,
        filters: ReportRunFilters,
        period: dict[str, str],
    ) -> list[Interaction]:
        """Select persisted interactions for the requested period and filters."""
        interactions = (
            self.db.query(Interaction)
            .filter(Interaction.department_id == self.department_id)
            .all()
        )
        start_date = date.fromisoformat(period["date_from"])
        end_date = date.fromisoformat(period["date_to"])
        try:
            manager_ids = {UUID(item) for item in filters.manager_ids}
        except ValueError as exc:
            raise ASAError("manager_ids must contain valid UUID values.") from exc

        selected: list[Interaction] = []
        for interaction in interactions:
            metadata = dict(interaction.metadata_ or {})
            call_started_at = parse_call_started_at(metadata)
            if call_started_at is None:
                continue
            call_day = call_started_at.date()
            if call_day < start_date or call_day > end_date:
                continue
            if filters.min_duration_sec is not None and (
                interaction.duration_sec or 0
            ) < filters.min_duration_sec:
                continue
            if filters.max_duration_sec is not None and interaction.duration_sec is not None:
                if interaction.duration_sec > filters.max_duration_sec:
                    continue
            extension = str(metadata.get("extension") or "").strip()
            if manager_ids and interaction.manager_id not in manager_ids:
                continue
            if filters.manager_extensions and extension not in filters.manager_extensions:
                continue
            selected.append(interaction)
        return sorted(
            selected,
            key=lambda item: parse_call_started_at(dict(item.metadata_ or {}))
            or datetime.min.replace(tzinfo=UTC),
        )

    async def _prepare_artifacts(
        self,
        *,
        interactions: list[Interaction],
        preset: ReportPreset,
        mode: str,
    ) -> tuple[list[ReportArtifact], dict[str, int], list[str]]:
        """Reuse persisted artifacts and optionally build only missing ones."""
        analyses_by_interaction = self._load_latest_analyses_by_interaction(interactions=interactions)
        managers_by_id = self._load_managers_by_id(interactions=interactions)

        built_transcripts = 0
        reused_transcripts = 0
        built_analyses = 0
        reused_analyses = 0
        analyses_rejected_for_reuse = 0
        missing_transcripts_before_build = 0
        missing_analyses_before_build = 0
        failed_transcripts = 0
        failed_analyses = 0
        build_errors: list[str] = []
        artifacts: list[ReportArtifact] = []
        for interaction in interactions:
            analysis = analyses_by_interaction.get(interaction.id)
            if interaction.text:
                reused_transcripts += 1
            else:
                missing_transcripts_before_build += 1
            reusable_analysis, analysis_reuse_reason = _is_analysis_reusable_for_reporting(analysis)
            if reusable_analysis:
                reused_analyses += 1
            else:
                missing_analyses_before_build += 1
                if analysis is not None:
                    analyses_rejected_for_reuse += 1
                    if not (
                        self._allows_build_missing(preset=preset, mode=mode)
                        and interaction.text
                    ):
                        build_errors.append(
                            f"analysis_reuse_rejected:{interaction.id}:{analysis_reuse_reason}"
                        )
                    analysis = None
            if self._allows_build_missing(preset=preset, mode=mode):
                if not interaction.text:
                    try:
                        await self.extractor.process(interaction)
                        built_transcripts += 1
                    except ASAError as exc:
                        failed_transcripts += 1
                        build_errors.append(f"transcript_build_failed:{interaction.id}:{exc}")
                if (
                    analysis is None or not isinstance(analysis.scores_detail, dict) or not analysis.scores_detail
                ) and interaction.text:
                    try:
                        result = self.analyzer.analyze_call(interaction)
                        analysis = self.call_orchestrator.persist_analysis(
                            interaction=interaction,
                            result=result,
                        )
                        built_analyses += 1
                    except SemanticAnalysisError as exc:
                        failed_analyses += 1
                        self.call_orchestrator.persist_failed_analysis(
                            interaction=interaction,
                            error=exc,
                        )
                        build_errors.append(f"analysis_build_failed:{interaction.id}:{exc}")
                    except ASAError as exc:
                        failed_analyses += 1
                        build_errors.append(f"analysis_build_failed:{interaction.id}:{exc}")
            artifacts.append(
                ReportArtifact(
                    interaction=interaction,
                    analysis=analysis,
                    manager=managers_by_id.get(interaction.manager_id) if interaction.manager_id else None,
                    call_started_at=parse_call_started_at(dict(interaction.metadata_ or {})),
                )
            )
        return (
            artifacts,
            {
                "transcripts_built": built_transcripts,
                "transcripts_reused": reused_transcripts,
                "analyses_built": built_analyses,
                "analyses_reused": reused_analyses,
                "analyses_rejected_for_reuse": analyses_rejected_for_reuse,
                "missing_transcripts_before_build": missing_transcripts_before_build,
                "missing_analyses_before_build": missing_analyses_before_build,
                "transcript_build_failed": failed_transcripts,
                "analysis_build_failed": failed_analyses,
            },
            build_errors,
        )

    def _build_run_observability(
        self,
        *,
        preset: ReportPreset,
        source_summary: dict[str, int],
        period: dict[str, str],
        source_period: dict[str, str],
        mode: str,
        send_email: bool,
        selected_interactions_count: int,
        build_summary: dict[str, int],
        reports: list[dict[str, Any]],
        overall_status: str,
        errors: list[str] | None = None,
        artifacts: list[ReportArtifact] | None = None,
    ) -> dict[str, Any]:
        """Build a UI-facing observability snapshot without changing execution flow."""
        stage_errors: list[str] = list(errors or [])
        report_errors = [
            error
            for report in reports
            for error in report.get("errors", [])
            if error
        ]
        all_errors = [*stage_errors, *report_errors]
        delivery_summary = self._build_delivery_summary(reports=reports, send_email=send_email)
        ai_costs = self._build_ai_costs(build_summary=build_summary, reports=reports)
        return {
            "run_state": self._map_run_state(overall_status),
            "stages": [
                self._build_source_discovery_stage(
                    preset=preset,
                    source_summary=source_summary,
                    period=source_period,
                    errors=errors or [],
                ),
                self._build_persistence_check_stage(
                    preset=preset,
                    source_summary=source_summary,
                    errors=all_errors,
                ),
                self._build_ingest_missing_stage(
                    preset=preset,
                    source_summary=source_summary,
                    errors=all_errors,
                ),
                self._build_audio_fetch_stage(
                    preset=preset,
                    build_summary=build_summary,
                    mode=mode,
                    errors=all_errors,
                ),
                self._build_stt_stage(
                    preset=preset,
                    build_summary=build_summary,
                    mode=mode,
                    errors=all_errors,
                ),
                self._build_analysis_stage(
                    preset=preset,
                    build_summary=build_summary,
                    mode=mode,
                    errors=all_errors,
                ),
                self._build_report_render_stage(
                    reports=reports,
                    errors=all_errors,
                ),
                self._build_delivery_stage(
                    reports=reports,
                    send_email=send_email,
                    delivery_summary=delivery_summary,
                    errors=all_errors,
                ),
            ],
            "summary": {
                "execution_model": self._resolve_execution_model(preset=preset),
                "selected_interactions_count": selected_interactions_count,
                "reused_analyses_count": build_summary.get("analyses_reused", 0),
                "rebuilt_analyses_count": build_summary.get("analyses_built", 0),
                "final_report_status": overall_status,
                "template_version": next(
                    (
                        ((report.get("artifact") or {}).get("template_version"))
                        for report in reports
                        if (report.get("artifact") or {}).get("template_version")
                    ),
                    get_active_template_version(preset.code),
                ),
                "template_id": next(
                    (
                        ((report.get("artifact") or {}).get("template_id"))
                        for report in reports
                        if (report.get("artifact") or {}).get("template_id")
                    ),
                    get_active_template_version(preset.code),
                ),
                "render_variant": next(
                    (
                        ((report.get("artifact") or {}).get("render_variant"))
                        for report in reports
                        if (report.get("artifact") or {}).get("render_variant")
                    ),
                    f"template_pdf_{get_active_template_version(preset.code)}",
                ),
                "generator_path": next(
                    (
                        ((report.get("artifact") or {}).get("generator_path"))
                        for report in reports
                        if (report.get("artifact") or {}).get("generator_path")
                    ),
                    "app.agents.calls.report_templates.render_report_artifact",
                ),
                "artifact_type": next(
                    (
                        ((report.get("artifact") or {}).get("media_type"))
                        for report in reports
                        if (report.get("artifact") or {}).get("media_type")
                    ),
                    "application/pdf",
                ),
                "conversion_path": next(
                    (
                        ((report.get("artifact") or {}).get("conversion_path"))
                        for report in reports
                        if (report.get("artifact") or {}).get("conversion_path")
                    ),
                    None,
                ),
                "conversion_status": next(
                    (
                        ((report.get("artifact") or {}).get("conversion_status"))
                        for report in reports
                        if (report.get("artifact") or {}).get("conversion_status")
                    ),
                    None,
                ),
                "delivery": delivery_summary,
                "source": source_summary,
            },
            "ai_layers": self._build_ai_layer_summary(
                preset=preset,
                mode=mode,
                build_summary=build_summary,
                artifacts=artifacts or [],
            ),
            "ai_costs": ai_costs,
        }

    def _collect_run_diagnostics_context(
        self,
        *,
        preset: ReportPreset,
        mode: str,
        filters: ReportRunFilters,
        period: dict[str, str],
    ) -> dict[str, Any]:
        """Collect lightweight selection transparency context before the run is executed."""
        department = (
            self.db.query(Department)
            .filter(Department.id == self.department_id)
            .first()
        )
        directory_managers = (
            self.db.query(Manager)
            .filter(Manager.department_id == self.department_id)
            .all()
        )
        directory_manager_ids = {str(item.id) for item in directory_managers}
        selected_manager_ids = sorted(filters.manager_ids)
        selected_manager_extensions = sorted(filters.manager_extensions)

        period_only_interactions = self._select_interactions(
            filters=ReportRunFilters(
                date_from=filters.date_from,
                date_to=filters.date_to,
                min_duration_sec=filters.min_duration_sec,
                max_duration_sec=filters.max_duration_sec,
            ),
            period=period,
        )
        manager_only_interactions = (
            self._select_interactions(
                filters=ReportRunFilters(
                    manager_ids=set(filters.manager_ids),
                    date_from=filters.date_from,
                    date_to=filters.date_to,
                    min_duration_sec=filters.min_duration_sec,
                    max_duration_sec=filters.max_duration_sec,
                ),
                period=period,
            )
            if filters.manager_ids
            else []
        )
        extension_only_interactions = (
            self._select_interactions(
                filters=ReportRunFilters(
                    manager_extensions=set(filters.manager_extensions),
                    date_from=filters.date_from,
                    date_to=filters.date_to,
                    min_duration_sec=filters.min_duration_sec,
                    max_duration_sec=filters.max_duration_sec,
                ),
                period=period,
            )
            if filters.manager_extensions
            else []
        )

        return {
            "department_id": str(self.department_id),
            "department_name": department.name if department is not None else str(self.department_id),
            "preset": preset.code,
            "execution_model": self._resolve_execution_model(preset=preset),
            "mode": mode,
            "period": period,
            "selected_manager_ids": selected_manager_ids,
            "selected_manager_extensions": selected_manager_extensions,
            "manager_filter_logic": (
                "intersection"
                if selected_manager_ids and selected_manager_extensions
                else "manager_ids_only"
                if selected_manager_ids
                else "manager_extensions_only"
                if selected_manager_extensions
                else "department_scope"
            ),
            "missing_local_manager_ids": [
                item for item in selected_manager_ids if item not in directory_manager_ids
            ],
            "period_only_interactions_count": len(period_only_interactions),
            "manager_only_interactions_count": len(manager_only_interactions),
            "extension_only_interactions_count": len(extension_only_interactions),
        }

    def _build_run_diagnostics(
        self,
        *,
        preset: ReportPreset,
        mode: str,
        period: dict[str, str],
        source_period: dict[str, str],
        filters: ReportRunFilters,
        diagnostics_context: dict[str, Any],
        build_summary: dict[str, int],
        reports: list[dict[str, Any]],
        selected_interactions_count: int,
        final_selected_interactions_count: int,
        overall_status: str,
        source_summary: dict[str, int],
        errors: list[str],
    ) -> dict[str, Any]:
        """Return a structured diagnostics block for operator-side transparency."""
        reason_codes = self._build_diagnostics_reason_codes(
            mode=mode,
            diagnostics_context=diagnostics_context,
            build_summary=build_summary,
            reports=reports,
            selected_interactions_count=selected_interactions_count,
            final_selected_interactions_count=final_selected_interactions_count,
            errors=errors,
        )
        notes = [
            (
                "report_from_ready_data_only on manager_daily performs source discovery and may ingest missing interactions, "
                "but it still does not fetch audio or run new STT / LLM-1 / LLM-2 builds."
            )
            if preset.code == "manager_daily" and mode == "report_from_ready_data_only"
            else (
                "build_missing_and_report on manager_daily performs source discovery, persists missing interactions, "
                "and then runs audio fetch / STT / LLM-1 / LLM-2 only for missing artifacts with reuse-first behavior."
            )
            if preset.code == "manager_daily"
            else (
                "rop_weekly uses persisted-only execution: no source discovery, no ingest of missing calls, "
                "and no new audio/STT/analysis run inside weekly reporting."
            )
        ]
        if diagnostics_context["manager_filter_logic"] == "intersection":
            notes.append(
                "manager_ids and manager_extensions are both selected, so the current bounded logic uses their intersection."
            )

        return {
            "effective_preset": preset.code,
            "effective_mode": mode,
            "execution_model": diagnostics_context["execution_model"],
            "effective_department": {
                "id": diagnostics_context["department_id"],
                "name": diagnostics_context["department_name"],
            },
            "effective_period": period,
            "source_period": source_period,
            "selected_manager_ids": sorted(filters.manager_ids),
            "selected_manager_extensions": sorted(filters.manager_extensions),
            "manager_filter_logic": diagnostics_context["manager_filter_logic"],
            "uses_filters_intersection": diagnostics_context["manager_filter_logic"] == "intersection",
            "interactions_found_before_reuse_build": selected_interactions_count,
            "ready_transcripts_count": build_summary.get("transcripts_reused", 0),
            "ready_analyses_count": build_summary.get("analyses_reused", 0),
            "final_selected_interactions_count": final_selected_interactions_count,
            "reason_codes": reason_codes,
            "machine_readable_status": overall_status,
            "notes": notes,
            "report_origin": {
                "template_version": next(
                    (
                        ((report.get("artifact") or {}).get("template_version"))
                        for report in reports
                        if (report.get("artifact") or {}).get("template_version")
                    ),
                    get_active_template_version(preset.code),
                ),
                "template_id": next(
                    (
                        ((report.get("artifact") or {}).get("template_id"))
                        for report in reports
                        if (report.get("artifact") or {}).get("template_id")
                    ),
                    None,
                ),
                "render_variant": next(
                    (
                        ((report.get("artifact") or {}).get("render_variant"))
                        for report in reports
                        if (report.get("artifact") or {}).get("render_variant")
                    ),
                    f"template_pdf_{get_active_template_version(preset.code)}",
                ),
                "generator_path": next(
                    (
                        ((report.get("artifact") or {}).get("generator_path"))
                        for report in reports
                        if (report.get("artifact") or {}).get("generator_path")
                    ),
                    "app.agents.calls.report_templates.render_report_artifact",
                ),
                "artifact_type": next(
                    (
                        ((report.get("artifact") or {}).get("media_type"))
                        for report in reports
                        if (report.get("artifact") or {}).get("media_type")
                    ),
                    "application/pdf",
                ),
                "conversion_path": next(
                    (
                        ((report.get("artifact") or {}).get("conversion_path"))
                        for report in reports
                        if (report.get("artifact") or {}).get("conversion_path")
                    ),
                    None,
                ),
                "conversion_status": next(
                    (
                        ((report.get("artifact") or {}).get("conversion_status"))
                        for report in reports
                        if (report.get("artifact") or {}).get("conversion_status")
                    ),
                    None,
                ),
            },
            "source": source_summary,
            "readiness": self._build_readiness_summary(reports=reports),
            "local_directory": {
                "missing_manager_ids": diagnostics_context["missing_local_manager_ids"],
            },
        }

    @staticmethod
    def _build_readiness_summary(*, reports: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate manager_daily readiness decisions for structured diagnostics."""
        groups: list[dict[str, Any]] = []
        counts = {
            "full_report": 0,
            "signal_report": 0,
            "skip_accumulate": 0,
        }
        for report in reports:
            readiness = dict(report.get("readiness") or {})
            outcome = str(readiness.get("readiness_outcome") or "").strip()
            if not outcome:
                continue
            if outcome in counts:
                counts[outcome] += 1
            groups.append(
                {
                    "group_key": report.get("group_key"),
                    "readiness_outcome": outcome,
                    "readiness_reason_codes": list(readiness.get("readiness_reason_codes") or []),
                    "window_days_used": readiness.get("window_days_used"),
                    "relevant_calls": readiness.get("relevant_calls"),
                    "ready_analyses": readiness.get("ready_analyses"),
                    "analysis_coverage": readiness.get("analysis_coverage"),
                    "content_blocks": dict(readiness.get("content_blocks") or {}),
                }
            )
        return {
            "counts": counts,
            "groups": groups,
        }

    @staticmethod
    def _build_diagnostics_reason_codes(
        *,
        mode: str,
        diagnostics_context: dict[str, Any],
        build_summary: dict[str, int],
        reports: list[dict[str, Any]],
        selected_interactions_count: int,
        final_selected_interactions_count: int,
        errors: list[str],
    ) -> list[str]:
        """Return stable reason codes for empty or limited report-run results."""
        reason_codes: list[str] = []
        if diagnostics_context.get("missing_local_manager_ids"):
            reason_codes.append("manager_not_in_local_directory")
        if any(item.startswith("source_discovery_failed:") for item in errors):
            reason_codes.append("source_discovery_failed")
        if any(item.startswith("transcript_build_failed:") for item in errors):
            reason_codes.append("transcript_build_failed")
        if any(item.startswith("analysis_build_failed:") for item in errors):
            reason_codes.append("analysis_build_failed")
        if any(item.startswith("analysis_reuse_rejected:") for item in errors):
            reason_codes.append("analysis_reuse_rejected")
        if diagnostics_context.get("period_only_interactions_count", 0) == 0:
            reason_codes.append("date_range_has_no_persisted_calls")
        if (
            selected_interactions_count == 0
            and diagnostics_context.get("manager_filter_logic") == "intersection"
            and diagnostics_context.get("manager_only_interactions_count", 0) > 0
            and diagnostics_context.get("extension_only_interactions_count", 0) > 0
        ):
            reason_codes.append("filters_intersection_empty")
        if selected_interactions_count == 0:
            reason_codes.append("no_persisted_interactions_for_filters")
        if (
            mode == "report_from_ready_data_only"
            and selected_interactions_count > 0
            and final_selected_interactions_count == 0
            and (
                build_summary.get("transcripts_reused", 0) == 0
                or build_summary.get("analyses_reused", 0) == 0
            )
        ):
            reason_codes.append("no_ready_artifacts_for_ready_only_mode")
        if (
            mode == "report_from_ready_data_only"
            and selected_interactions_count > 0
            and final_selected_interactions_count == 0
            and reports
            and all(item.get("status") == "missing_artifacts" for item in reports)
            and "no_ready_artifacts_for_ready_only_mode" not in reason_codes
        ):
            reason_codes.append("no_ready_artifacts_for_ready_only_mode")
        for report in reports:
            readiness = dict(report.get("readiness") or {})
            for code in readiness.get("readiness_reason_codes") or []:
                reason_codes.append(str(code))
        deduped: list[str] = []
        for code in reason_codes:
            if code not in deduped:
                deduped.append(code)
        return deduped

    @staticmethod
    def _map_run_state(status: str) -> str:
        """Map internal reporting statuses to the UI run-state indicator."""
        if status in {"completed", "delivered", "ready"}:
            return "completed"
        if status in {"blocked", "partial", "no_data", "recipient_blocked", "missing_artifacts"}:
            return "blocked"
        return "failed"

    @staticmethod
    def _build_source_discovery_stage(
        *,
        preset: ReportPreset,
        source_summary: dict[str, int],
        period: dict[str, str],
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the source-discovery stage snapshot."""
        if preset.code == "rop_weekly":
            return {
                "code": "source-discovery",
                "label": "source-discovery",
                "status": "skipped",
                "summary": "Preset rop_weekly is persisted-only, so source discovery is not executed.",
                "error": None,
            }
        source_failure = next((item for item in errors if item.startswith("source_discovery_failed:")), None)
        if source_failure:
            return {
                "code": "source-discovery",
                "label": "source-discovery",
                "status": "blocked",
                "summary": (
                    f"Source discovery failed while scanning {period['date_from']}..{period['date_to']}."
                ),
                "error": source_failure,
            }
        if source_summary.get("targeted_source_records_total", 0) <= 0:
            return {
                "code": "source-discovery",
                "label": "source-discovery",
                "status": "warn",
                "summary": (
                    f"Scanned {source_summary.get('days_scanned', 0)} days for {period['date_from']}..{period['date_to']}. "
                    "No eligible source calls matched the current filters."
                ),
                "error": errors[0] if errors else None,
            }
        return {
            "code": "source-discovery",
            "label": "source-discovery",
            "status": "completed",
            "summary": (
                f"Scanned {source_summary.get('days_scanned', 0)} days, fetched "
                f"{source_summary.get('source_records_total', 0)} source calls, "
                f"{source_summary.get('eligible_source_records_total', 0)} eligible, "
                f"{source_summary.get('targeted_source_records_total', 0)} matched filters."
            ),
            "error": None,
        }

    @staticmethod
    def _build_persistence_check_stage(
        *,
        preset: ReportPreset,
        source_summary: dict[str, int],
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the persistence-check stage snapshot."""
        if preset.code == "rop_weekly":
            return {
                "code": "persistence-check",
                "label": "persistence-check",
                "status": "skipped",
                "summary": "Preset rop_weekly is persisted-only, so no source/persistence reconciliation runs.",
                "error": None,
            }
        if source_summary.get("targeted_source_records_total", 0) <= 0:
            return {
                "code": "persistence-check",
                "label": "persistence-check",
                "status": "idle",
                "summary": "Source discovery produced no matched calls, so persistence-check stayed idle.",
                "error": None,
            }
        status = "completed" if source_summary.get("missing_source_records_total", 0) == 0 else "warn"
        return {
            "code": "persistence-check",
            "label": "persistence-check",
            "status": status,
            "summary": (
                f"Already persisted {source_summary.get('already_persisted_source_records_total', 0)} "
                f"matched source calls; missing before ingest {source_summary.get('missing_source_records_total', 0)}."
            ),
            "error": errors[0] if status == "warn" and errors else None,
        }

    @staticmethod
    def _build_ingest_missing_stage(
        *,
        preset: ReportPreset,
        source_summary: dict[str, int],
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the ingest-missing stage snapshot."""
        if preset.code == "rop_weekly":
            return {
                "code": "ingest-missing",
                "label": "ingest-missing",
                "status": "skipped",
                "summary": "Preset rop_weekly is persisted-only, so no missing source calls are ingested.",
                "error": None,
            }
        if source_summary.get("targeted_source_records_total", 0) <= 0:
            return {
                "code": "ingest-missing",
                "label": "ingest-missing",
                "status": "skipped",
                "summary": "No matched source calls required ingestion.",
                "error": None,
            }
        if source_summary.get("missing_source_records_total", 0) <= 0:
            return {
                "code": "ingest-missing",
                "label": "ingest-missing",
                "status": "completed",
                "summary": "All matched source calls were already persisted; no new interactions were created.",
                "error": None,
            }
        return {
            "code": "ingest-missing",
            "label": "ingest-missing",
            "status": "completed",
            "summary": (
                f"Created {source_summary.get('ingest_created_total', 0)} interactions and "
                f"updated/skipped {source_summary.get('ingest_skipped_total', 0)} existing rows."
            ),
            "error": errors[0] if errors and source_summary.get("ingest_created_total", 0) == 0 else None,
        }

    @staticmethod
    def _build_audio_fetch_stage(
        *,
        preset: ReportPreset,
        build_summary: dict[str, int],
        mode: str,
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the audio-fetch stage snapshot."""
        if preset.code == "rop_weekly":
            return {
                "code": "audio-fetch",
                "label": "audio-fetch",
                "status": "skipped",
                "summary": "Preset rop_weekly is persisted-only, so weekly reporting never fetches new audio.",
                "error": None,
            }
        if mode != "build_missing_and_report":
            return {
                "code": "audio-fetch",
                "label": "audio-fetch",
                "status": "skipped",
                "summary": "Ready-only mode does not fetch audio for missing calls.",
                "error": None,
            }
        audio_error = next(
            (
                item
                for item in errors
                if item.startswith("transcript_build_failed:")
                and "audio" in item.lower()
            ),
            None,
        )
        if audio_error:
            return {
                "code": "audio-fetch",
                "label": "audio-fetch",
                "status": "blocked",
                "summary": "Audio fetch/download failed for at least one missing interaction.",
                "error": audio_error,
            }
        return {
            "code": "audio-fetch",
            "label": "audio-fetch",
            "status": "completed",
            "summary": (
                f"Fetched audio for {build_summary.get('transcripts_built', 0)} interactions that required transcript build."
            ),
            "error": None,
        }

    @staticmethod
    def _build_stt_stage(
        *,
        preset: ReportPreset,
        build_summary: dict[str, int],
        mode: str,
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the STT stage snapshot."""
        if preset.code == "rop_weekly":
            return {
                "code": "stt",
                "label": "STT",
                "status": "skipped",
                "summary": "Preset rop_weekly is persisted-only, so weekly reporting never runs new STT.",
                "error": None,
            }
        if mode != "build_missing_and_report":
            return {
                "code": "stt",
                "label": "STT",
                "status": "skipped",
                "summary": "Ready-only mode does not run STT for missing calls.",
                "error": None,
            }
        stt_error = next(
            (
                item
                for item in errors
                if item.startswith("transcript_build_failed:")
                and any(token in item.lower() for token in ("stt", "whisper", "transcrib", "speech"))
            ),
            None,
        )
        if stt_error:
            return {
                "code": "stt",
                "label": "STT",
                "status": "blocked",
                "summary": "STT failed for at least one missing interaction.",
                "error": stt_error,
            }
        return {
            "code": "stt",
            "label": "STT",
            "status": "completed",
            "summary": (
                f"Built {build_summary.get('transcripts_built', 0)} transcripts and reused "
                f"{build_summary.get('transcripts_reused', 0)} ready transcripts."
            ),
            "error": None,
        }

    @staticmethod
    def _build_analysis_stage(
        *,
        preset: ReportPreset,
        build_summary: dict[str, int],
        mode: str,
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the analysis stage snapshot."""
        if preset.code == "rop_weekly":
            return {
                "code": "analysis",
                "label": "analysis",
                "status": "skipped",
                "summary": "Preset rop_weekly is persisted-only, so weekly reporting reuses existing analyses only.",
                "error": None,
            }
        if mode != "build_missing_and_report":
            return {
                "code": "analysis",
                "label": "analysis",
                "status": "skipped",
                "summary": "Ready-only mode does not run new analysis for missing calls.",
                "error": None,
            }
        analysis_error = next((item for item in errors if item.startswith("analysis_build_failed:")), None)
        if analysis_error:
            return {
                "code": "analysis",
                "label": "analysis",
                "status": "blocked",
                "summary": "Analysis build failed for at least one interaction.",
                "error": analysis_error,
            }
        return {
            "code": "analysis",
            "label": "analysis",
            "status": "completed",
            "summary": (
                f"Built {build_summary.get('analyses_built', 0)} analyses and reused "
                f"{build_summary.get('analyses_reused', 0)} persisted analyses."
            ),
            "error": None,
        }

    @staticmethod
    def _build_report_render_stage(
        *,
        reports: list[dict[str, Any]],
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the report-build/render stage snapshot."""
        if not reports:
            return {
                "code": "report-build",
                "label": "report-build / render",
                "status": "idle",
                "summary": "No report groups were built.",
                "error": errors[0] if errors else None,
            }
        rendered_total = sum(1 for item in reports if item.get("payload") or item.get("preview"))
        blocked_total = sum(1 for item in reports if item.get("status") == "missing_artifacts")
        skipped_total = sum(1 for item in reports if item.get("status") == "skip_accumulate")
        if rendered_total == 0 and skipped_total == len(reports):
            return {
                "code": "report-build",
                "label": "report-build / render",
                "status": "completed",
                "summary": f"Readiness decision skipped render for {skipped_total} manager_daily groups.",
                "error": None,
            }
        status = "completed" if rendered_total > 0 else "blocked"
        if blocked_total and rendered_total:
            status = "warn"
        return {
            "code": "report-build",
            "label": "report-build / render",
            "status": status,
            "summary": f"Built {len(reports)} report groups and rendered {rendered_total} previews.",
            "error": errors[0] if status in {"blocked", "warn"} and errors else None,
        }

    @staticmethod
    def _build_delivery_stage(
        *,
        reports: list[dict[str, Any]],
        send_email: bool,
        delivery_summary: dict[str, Any],
        errors: list[str],
    ) -> dict[str, Any]:
        """Return the delivery stage snapshot."""
        if not reports:
            return {
                "code": "delivery",
                "label": "delivery",
                "status": "idle",
                "summary": "No report groups reached delivery.",
                "error": None,
            }
        if all(item.get("status") == "skip_accumulate" for item in reports):
            if any((item.get("delivery") or {}).get("transport") for item in reports):
                telegram_status = (delivery_summary.get("telegram_test_delivery") or {}).get("status", "unknown")
                email_status = (delivery_summary.get("email_delivery") or {}).get("status", "unknown")
                telegram_targets = ", ".join((delivery_summary.get("telegram_test_delivery") or {}).get("targets", [])) or "no telegram target"
                email_targets = ", ".join((delivery_summary.get("email_delivery") or {}).get("targets", [])) or "no email targets"
                status = "completed" if telegram_status == "delivered" and email_status in {"delivered", "skipped", "blocked", "not_started"} else "warn"
                return {
                    "code": "delivery",
                    "label": "delivery",
                    "status": status,
                    "summary": (
                        "Preview shell delivery for non-deliverable manager_daily: "
                        f"Telegram {telegram_status} to {telegram_targets}; "
                        f"email {email_status} to {email_targets}."
                    ),
                    "error": errors[0] if status in {"blocked", "warn"} and errors else None,
                }
            return {
                "code": "delivery",
                "label": "delivery",
                "status": "completed",
                "summary": "Readiness decision selected skip_accumulate, so delivery was intentionally skipped.",
                "error": None,
            }
        telegram_status = (delivery_summary.get("telegram_test_delivery") or {}).get("status", "unknown")
        email_status = (delivery_summary.get("email_delivery") or {}).get("status", "unknown")
        if telegram_status == "delivered" and email_status in {"delivered", "skipped", "blocked", "not_started"}:
            status = "completed"
        elif telegram_status == "delivered" and email_status == "failed":
            status = "warn"
        elif telegram_status in {"failed", "blocked"}:
            status = "blocked"
        else:
            status = "warn"
        telegram_targets = ", ".join((delivery_summary.get("telegram_test_delivery") or {}).get("targets", [])) or "no telegram target"
        email_targets = ", ".join((delivery_summary.get("email_delivery") or {}).get("targets", [])) or "no email targets"
        return {
            "code": "delivery",
            "label": "delivery",
            "status": status,
            "summary": (
                f"Telegram test delivery {telegram_status} to {telegram_targets}; "
                f"email delivery {email_status} to {email_targets}; "
                f"overall result {delivery_summary.get('result', 'unknown')}."
            ),
            "error": errors[0] if status in {"blocked", "warn"} and errors else None,
        }

    def _build_delivery_summary(
        self,
        *,
        reports: list[dict[str, Any]],
        send_email: bool,
    ) -> dict[str, Any]:
        """Return a compact delivery summary for the operator UI."""
        if not reports:
            return {
                "mode": "unknown",
                "targets": [],
                "result": "not_started",
                "telegram_test_delivery": {
                    "enabled": True,
                    "status": "not_started",
                    "targets": [],
                },
                "email_delivery": {
                    "enabled": send_email,
                    "status": "not_started",
                    "targets": [],
                },
            }
        targets: list[str] = []
        mode = "unknown"
        telegram_targets: list[str] = []
        email_targets: list[str] = []
        telegram_status = "not_started"
        email_status = "skipped" if not send_email else "not_started"
        for report in reports:
            delivery = report.get("delivery") or {}
            transport = delivery.get("transport") or {}
            if transport.get("mode"):
                mode = str(transport["mode"])

            telegram = transport.get("telegram_test_delivery") or {}
            email = transport.get("email_delivery") or {}

            telegram_target = str(telegram.get("target") or "").strip()
            if telegram_target:
                value = f"telegram:{telegram_target}"
                if value not in telegram_targets:
                    telegram_targets.append(value)
                if value not in targets:
                    targets.append(value)
            resolved_email = transport.get("resolved_email") or {}
            primary_email = str(resolved_email.get("primary_email") or email.get("primary_email") or "").strip()
            if primary_email:
                value = f"resolved-email:{primary_email}"
                if value not in email_targets:
                    email_targets.append(value)
                if value not in targets:
                    targets.append(value)
            for cc_email in resolved_email.get("cc_emails") or email.get("cc_emails") or []:
                if cc_email:
                    value = f"resolved-cc:{cc_email}"
                    if value not in email_targets:
                        email_targets.append(value)
                    if value not in targets:
                        targets.append(value)

            telegram_status = self._merge_channel_status(telegram_status, str(telegram.get("status") or "not_started"))
            email_status = self._merge_channel_status(email_status, str(email.get("status") or email_status))

        result = self._derive_overall_delivery_result(
            telegram_status=telegram_status,
            email_status=email_status,
        )
        return {
            "mode": mode,
            "targets": targets,
            "result": result,
            "telegram_test_delivery": {
                "enabled": True,
                "status": telegram_status,
                "targets": telegram_targets,
            },
            "email_delivery": {
                "enabled": send_email,
                "status": email_status,
                "targets": email_targets,
            },
        }

    @staticmethod
    def _merge_channel_status(current: str, candidate: str) -> str:
        """Merge multiple report-level channel statuses into one summary status."""
        priority = {
            "failed": 5,
            "blocked": 4,
            "delivered": 3,
            "sent": 3,
            "planned": 2,
            "skipped": 1,
            "not_started": 0,
            "unknown": 0,
        }
        return candidate if priority.get(candidate, 0) >= priority.get(current, 0) else current

    @staticmethod
    def _derive_overall_delivery_result(*, telegram_status: str, email_status: str) -> str:
        """Derive one operator-facing delivery result from split channel states."""
        if telegram_status == "failed":
            return "blocked"
        if telegram_status == "delivered" and email_status in {"delivered", "skipped", "blocked", "not_started"}:
            return "sent"
        if telegram_status == "delivered" and email_status == "failed":
            return "partial"
        if telegram_status == "blocked":
            return "blocked"
        return "unknown"

    @staticmethod
    def _flatten_delivery_targets(delivery: dict[str, Any]) -> list[str]:
        """Flatten preview/delivery target metadata into readable strings."""
        targets: list[str] = []
        primary = str(delivery.get("primary_email") or "").strip()
        if primary:
            targets.append(f"email:{primary}")
        for email in delivery.get("cc_emails") or []:
            if email:
                targets.append(f"cc:{email}")
        if delivery.get("telegram_chat_id"):
            targets.append(f"telegram:{delivery['telegram_chat_id']}")
        transport = delivery.get("resolved_email") or {}
        primary = str(transport.get("primary_email") or "").strip()
        if primary:
            targets.append(f"resolved-email:{primary}")
        for email in transport.get("cc_emails") or []:
            if email:
                targets.append(f"resolved-cc:{email}")
        deduped: list[str] = []
        for item in targets:
            if item not in deduped:
                deduped.append(item)
        return deduped

    def _build_ai_costs(
        self,
        *,
        build_summary: dict[str, int],
        reports: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Return AI node cost blocks with exact metadata when available."""
        ai_costs: list[dict[str, Any]] = []
        if build_summary.get("transcripts_built", 0) > 0:
            ai_costs.append(
                self._make_ai_cost_entry(
                    node="stt",
                    used_count=build_summary.get("transcripts_built", 0),
                    metadata_candidates=[],
                    summary="Speech-to-text ran for missing transcripts in this run.",
                )
            )
        if build_summary.get("analyses_built", 0) > 0:
            metadata_candidates = [
                report.get("payload", {})
                for report in reports
                if report.get("payload")
            ]
            ai_costs.append(
                self._make_ai_cost_entry(
                    node="llm1",
                    used_count=build_summary.get("analyses_built", 0),
                    metadata_candidates=metadata_candidates,
                    summary="LLM-1 first-pass analysis ran for rebuilt analyses in this run.",
                )
            )
            ai_costs.append(
                self._make_ai_cost_entry(
                    node="llm2",
                    used_count=build_summary.get("analyses_built", 0),
                    metadata_candidates=metadata_candidates,
                    summary="LLM-2 approved-contract generation ran for rebuilt analyses in this run.",
                )
            )
        return ai_costs

    def _build_ai_layer_summary(
        self,
        *,
        preset: ReportPreset,
        mode: str,
        build_summary: dict[str, int],
        artifacts: list[ReportArtifact],
    ) -> list[dict[str, Any]]:
        """Return per-layer execution/reuse/skip observability for the current run."""
        return [
            self._build_ai_layer_entry(
                layer="stt",
                label="STT",
                preset=preset,
                mode=mode,
                executed_count=build_summary.get("transcripts_built", 0),
                reused_count=build_summary.get("transcripts_reused", 0),
                not_activated_count=build_summary.get("missing_transcripts_before_build", 0),
                artifacts=artifacts,
            ),
            self._build_ai_layer_entry(
                layer="llm1",
                label="LLM-1",
                preset=preset,
                mode=mode,
                executed_count=build_summary.get("analyses_built", 0),
                reused_count=build_summary.get("analyses_reused", 0),
                not_activated_count=build_summary.get("missing_analyses_before_build", 0),
                artifacts=artifacts,
            ),
            self._build_ai_layer_entry(
                layer="llm2",
                label="LLM-2",
                preset=preset,
                mode=mode,
                executed_count=build_summary.get("analyses_built", 0),
                reused_count=build_summary.get("analyses_reused", 0),
                not_activated_count=build_summary.get("missing_analyses_before_build", 0),
                artifacts=artifacts,
            ),
        ]

    def _build_ai_layer_entry(
        self,
        *,
        layer: str,
        label: str,
        preset: ReportPreset,
        mode: str,
        executed_count: int,
        reused_count: int,
        not_activated_count: int,
        artifacts: list[ReportArtifact],
    ) -> dict[str, Any]:
        """Build one layer-level audit block for operator observability."""
        selected_routes = self._collect_ai_layer_routes(artifacts=artifacts, layer=layer)
        current_run_status = "idle"
        skip_reason = None
        if preset.code == "rop_weekly":
            current_run_status = "skipped"
            skip_reason = "preset_persisted_only"
        elif mode != "build_missing_and_report":
            current_run_status = "skipped"
            skip_reason = "mode_ready_only_no_new_builds"
        elif executed_count > 0:
            current_run_status = "executed"
        elif reused_count > 0:
            current_run_status = "reused_only"
        return {
            "layer": layer,
            "label": label,
            "current_run_status": current_run_status,
            "skip_reason": skip_reason,
            "executed_count": executed_count,
            "reused_count": reused_count,
            "not_activated_count": not_activated_count if current_run_status == "skipped" else 0,
            "provider_audit_available": bool(selected_routes),
            "selected_routes": selected_routes,
        }

    @staticmethod
    def _collect_ai_layer_routes(
        *,
        artifacts: list[ReportArtifact],
        layer: str,
    ) -> list[dict[str, Any]]:
        """Collect unique route metadata already persisted on source interactions."""
        routes: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for artifact in artifacts:
            metadata = dict(artifact.interaction.metadata_ or {})
            ai_routing = dict(metadata.get("ai_routing") or {})
            layer_metadata = ai_routing.get(layer)
            if not isinstance(layer_metadata, dict):
                continue
            route = {
                "selected_provider": layer_metadata.get("selected_provider"),
                "selected_account_alias": layer_metadata.get("selected_account_alias"),
                "selected_api_key_env": layer_metadata.get("selected_api_key_env"),
                "selected_model": layer_metadata.get("selected_model"),
                "selected_api_base": layer_metadata.get("selected_api_base"),
                "selected_endpoint": layer_metadata.get("selected_endpoint"),
                "executed_endpoint_path": layer_metadata.get("executed_endpoint_path"),
                "selected_execution_mode": layer_metadata.get("selected_execution_mode"),
                "request_kind": layer_metadata.get("request_kind"),
                "execution_status": layer_metadata.get("execution_status"),
                "executed": layer_metadata.get("executed"),
                "provider_failure": layer_metadata.get("provider_failure"),
                "skip_reason": layer_metadata.get("skip_reason"),
                "provider_request_id": layer_metadata.get("provider_request_id"),
                "usage": layer_metadata.get("usage"),
            }
            key = (
                route["selected_provider"],
                route["selected_account_alias"],
                route["selected_model"],
                route["selected_api_base"],
                route["selected_endpoint"],
                route["request_kind"],
                route["execution_status"],
            )
            if key in seen:
                continue
            seen.add(key)
            routes.append(route)
        return routes

    def _make_ai_cost_entry(
        self,
        *,
        node: str,
        used_count: int,
        metadata_candidates: list[dict[str, Any]],
        summary: str,
    ) -> dict[str, Any]:
        """Normalize one AI cost entry with safe fallbacks."""
        exact_cost = self._extract_known_cost_metadata(metadata_candidates)
        if exact_cost is None:
            return {
                "node": node,
                "used": True,
                "used_count": used_count,
                "cost_status": "not_available",
                "cost_usd": None,
                "tokens": None,
                "summary": f"{summary} Exact cost metadata is not available in current runtime payloads.",
            }
        return {
            "node": node,
            "used": True,
            "used_count": used_count,
            "cost_status": "available",
            "cost_usd": exact_cost.get("cost_usd"),
            "tokens": exact_cost.get("tokens"),
            "summary": summary,
        }

    @classmethod
    def _extract_known_cost_metadata(cls, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Scan nested payloads for known cost/token metadata without inventing values."""
        for candidate in candidates:
            found = cls._search_cost_metadata(candidate)
            if found is not None:
                return found
        return None

    @classmethod
    def _search_cost_metadata(cls, value: Any) -> dict[str, Any] | None:
        """Recursively search one nested payload for cost-like metadata."""
        if isinstance(value, dict):
            cost_usd = None
            for key in ("cost_usd", "usd_cost", "price_usd", "estimated_cost_usd"):
                if value.get(key) is not None:
                    cost_usd = value.get(key)
                    break
            tokens = None
            for key in ("total_tokens", "prompt_tokens", "completion_tokens", "input_tokens", "output_tokens"):
                if value.get(key) is not None:
                    tokens = {
                        token_key: value.get(token_key)
                        for token_key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")
                        if value.get(token_key) is not None
                    } or None
                    break
            if cost_usd is not None or tokens is not None:
                return {
                    "cost_usd": cost_usd,
                    "tokens": tokens,
                }
            for child in value.values():
                found = cls._search_cost_metadata(child)
                if found is not None:
                    return found
        if isinstance(value, list):
            for item in value:
                found = cls._search_cost_metadata(item)
                if found is not None:
                    return found
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError:
                return None
            return cls._search_cost_metadata(parsed)
        return None

    def _load_latest_analyses_by_interaction(
        self,
        *,
        interactions: list[Interaction],
    ) -> dict[UUID, Analysis]:
        """Return the latest analysis row for each selected interaction."""
        interaction_ids = [item.id for item in interactions]
        if not interaction_ids:
            return {}
        rows = (
            self.db.query(Analysis)
            .filter(
                Analysis.department_id == self.department_id,
                Analysis.interaction_id.in_(interaction_ids),
            )
            .order_by(Analysis.interaction_id, Analysis.created_at.desc())
            .all()
        )
        latest: dict[UUID, Analysis] = {}
        for row in rows:
            latest.setdefault(row.interaction_id, row)
        return latest

    def _load_managers_by_id(self, *, interactions: list[Interaction]) -> dict[UUID, Manager]:
        """Load manager rows referenced by the selected interactions."""
        manager_ids = sorted({item.manager_id for item in interactions if item.manager_id})
        if not manager_ids:
            return {}
        rows = (
            self.db.query(Manager)
            .filter(
                Manager.department_id == self.department_id,
                Manager.id.in_(manager_ids),
            )
            .all()
        )
        return {row.id: row for row in rows}

    def _group_and_build_reports(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
        source_period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        send_email: bool,
        manager_daily_windows: list[ManagerDailyWindow],
    ) -> list[dict[str, Any]]:
        """Build bounded reports for the selected preset."""
        if preset.code == "manager_daily":
            return self._build_manager_daily_reports_with_readiness(
                preset=preset,
                artifacts=artifacts,
                source_period=source_period,
                filters=filters,
                mode=mode,
                model_override=model_override,
                send_email=send_email,
                windows=manager_daily_windows,
            )
        grouped_artifacts = self._group_artifacts_by_preset(
            preset=preset,
            artifacts=artifacts,
            period=period,
        )
        return [
            self._build_single_report_result(
                preset=preset,
                artifacts=group,
                period=period,
                filters=filters,
                mode=mode,
                model_override=model_override,
                send_email=send_email,
            )
            for group in grouped_artifacts
        ]

    def _build_manager_daily_reports_with_readiness(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        source_period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        send_email: bool,
        windows: list[ManagerDailyWindow],
    ) -> list[dict[str, Any]]:
        """Build manager_daily groups through the bounded readiness decision layer."""
        grouped: dict[str, list[ReportArtifact]] = {}
        for artifact in artifacts:
            manager_key = str(artifact.interaction.manager_id or "unmapped")
            grouped.setdefault(manager_key, []).append(artifact)
        return [
            self._build_manager_daily_group_result(
                preset=preset,
                artifacts=group,
                source_period=source_period,
                filters=filters,
                mode=mode,
                model_override=model_override,
                send_email=send_email,
                windows=windows,
            )
            for _, group in sorted(grouped.items())
        ]

    def _build_manager_daily_group_result(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        source_period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        send_email: bool,
        windows: list[ManagerDailyWindow],
    ) -> dict[str, Any]:
        """Choose full_report, signal_report, or skip_accumulate for one manager group."""
        last_readiness = _build_manager_daily_readiness_result(
            outcome="skip_accumulate",
            reason_codes=["skip_accumulate_no_relevant_calls"],
            window=windows[-1] if windows else ManagerDailyWindow(1, source_period, (source_period["date_from"],)),
            relevant_calls=0,
            ready_analyses=0,
            analysis_coverage=0.0,
            content_blocks={},
            content_signals={},
        )
        for window in windows:
            window_artifacts = [
                item
                for item in artifacts
                if item.call_started_at is not None and item.call_started_at.date().isoformat() in window.included_days
            ]
            payload = None
            missing, usable = self._split_usable_artifacts(window_artifacts)
            if usable:
                payload = self._build_payload(
                    preset=preset,
                    artifacts=usable,
                    period=window.period,
                    filters=filters,
                    mode=mode,
                    model_override=model_override,
                )
            readiness = _evaluate_manager_daily_readiness(
                artifacts=window_artifacts,
                usable_artifacts=usable,
                payload=payload,
                window=window,
            )
            last_readiness = readiness
            if readiness["readiness_outcome"] in {"full_report", "signal_report"} and payload is not None:
                return self._render_and_deliver_report_result(
                    preset=preset,
                    usable=usable,
                    payload=payload,
                    send_email=send_email,
                    missing=missing,
                    readiness=readiness,
                )
        return self._build_manager_daily_empty_state_result(
            status="skip_accumulate",
            artifacts=artifacts,
            period=last_readiness["effective_period"],
            filters=filters,
            mode=mode,
            model_override=model_override,
            send_email=send_email,
            reason_codes=list(last_readiness["readiness_reason_codes"]),
            relevant_calls=last_readiness["relevant_calls"],
            ready_analyses=last_readiness["ready_analyses"],
            analysis_coverage=last_readiness["analysis_coverage"],
            missing=[],
            readiness=last_readiness,
        )

    def _group_artifacts_by_preset(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
    ) -> list[list[ReportArtifact]]:
        """Group selected artifacts into report-sized buckets for one preset."""
        if preset.code == "manager_daily":
            grouped: dict[tuple[str, str], list[ReportArtifact]] = {}
            for artifact in artifacts:
                manager_key = str(artifact.interaction.manager_id or "unmapped")
                day_key = (
                    artifact.call_started_at.date().isoformat()
                    if artifact.call_started_at is not None
                    else period["date_from"]
                )
                grouped.setdefault((manager_key, day_key), []).append(artifact)
            return [group for _, group in sorted(grouped.items())]
        return [artifacts]

    def _build_single_report_result(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        send_email: bool,
    ) -> dict[str, Any]:
        """Build one normalized payload, render it, and optionally deliver it."""
        missing, usable = self._split_usable_artifacts(artifacts)

        if not usable:
            if preset.code == "manager_daily":
                return self._build_manager_daily_empty_state_result(
                    status="missing_artifacts",
                    artifacts=artifacts,
                    period=period,
                    filters=filters,
                    mode=mode,
                    model_override=model_override,
                    send_email=send_email,
                    reason_codes=["missing_artifacts", "insufficient_ready_artifacts"],
                    relevant_calls=len(artifacts),
                    ready_analyses=0,
                    analysis_coverage=0.0,
                    missing=missing or ["no_usable_artifacts"],
                    readiness=None,
                )
            return {
                "status": "missing_artifacts",
                "preset": preset.code,
                "group_key": self._build_group_key(preset=preset, artifacts=artifacts, period=period),
                "errors": missing or ["no_usable_artifacts"],
                "delivery": None,
            }

        payload = self._build_payload(
            preset=preset,
            artifacts=usable,
            period=period,
            filters=filters,
            mode=mode,
            model_override=model_override,
        )
        return self._render_and_deliver_report_result(
            preset=preset,
            usable=usable,
            payload=payload,
            send_email=send_email,
            missing=missing,
            readiness=None,
        )

    @staticmethod
    def _split_usable_artifacts(artifacts: list[ReportArtifact]) -> tuple[list[str], list[ReportArtifact]]:
        """Separate ready report artifacts from rows missing transcript or analysis."""
        missing: list[str] = []
        usable: list[ReportArtifact] = []
        for artifact in artifacts:
            if artifact.analysis is None:
                missing.append(f"analysis_missing:{artifact.interaction.id}")
                continue
            if not artifact.interaction.text:
                missing.append(f"transcript_missing:{artifact.interaction.id}")
                continue
            usable.append(artifact)
        return missing, usable

    def _render_and_deliver_report_result(
        self,
        *,
        preset: ReportPreset,
        usable: list[ReportArtifact],
        payload: dict[str, Any],
        send_email: bool,
        missing: list[str],
        readiness: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Render one ready payload and run split delivery."""
        if readiness is not None:
            payload.setdefault("meta", {})["readiness"] = readiness
        rendered = render_report_email(payload, prefer_docx_first=True)

        try:
            delivery_targets = self._resolve_delivery_targets(
                preset=preset,
                artifacts=usable,
            )
            primary_email = delivery_targets["primary_email"]
            cc_emails = delivery_targets["cc_emails"]
            email_resolution_error = None
        except DeliveryError as exc:
            primary_email = None
            cc_emails = []
            email_resolution_error = str(exc)

        preview = {key: value for key, value in rendered.items() if key != "pdf_bytes"}
        result = {
            "status": "ready",
            "preset": preset.code,
            "group_key": payload["meta"]["group_key"],
            "errors": missing,
            "payload": payload,
            "preview": preview,
            "artifact": rendered.get("artifact"),
            "delivery": self.delivery.preview_report_delivery(
                primary_email=primary_email,
                cc_emails=cc_emails,
                send_business_email=send_email,
                email_resolution_error=email_resolution_error,
            ),
        }
        if readiness is not None:
            result.update(
                {
                    "readiness_outcome": readiness["readiness_outcome"],
                    "readiness_reason_codes": list(readiness["readiness_reason_codes"]),
                    "window_days_used": readiness["window_days_used"],
                    "relevant_calls": readiness["relevant_calls"],
                    "ready_analyses": readiness["ready_analyses"],
                    "analysis_coverage": readiness["analysis_coverage"],
                    "content_blocks": dict(readiness["content_blocks"]),
                    "readiness": readiness,
                }
            )
        delivery = self.delivery.deliver_operator_report(
            primary_email=primary_email,
            cc_emails=cc_emails,
            subject=rendered["subject"],
            text=rendered["text"],
            html=rendered["html"],
            pdf_bytes=rendered["pdf_bytes"],
            pdf_filename=rendered["artifact"]["filename"],
            template_meta=rendered.get("template"),
            artifact_meta=rendered.get("artifact"),
            send_business_email=send_email,
            email_resolution_error=email_resolution_error,
            morning_card_text=rendered.get("morning_card_text"),
        )
        result["delivery"] = delivery

        transport = delivery.get("transport") or {}
        telegram_status = ((transport.get("telegram_test_delivery") or {}).get("status") or "").strip()
        email_status = ((transport.get("email_delivery") or {}).get("status") or "").strip()

        if telegram_status == "delivered" and email_status in {"delivered", "skipped", "blocked", ""}:
            result["status"] = "delivered"
        elif telegram_status == "delivered" and email_status == "failed":
            result["status"] = "partial"
        else:
            result["status"] = "blocked"

        delivery_errors = [
            error
            for error in [
                (transport.get("telegram_test_delivery") or {}).get("error"),
                (transport.get("email_delivery") or {}).get("error"),
            ]
            if error
        ]
        if delivery_errors:
            result["errors"] = [*missing, *delivery_errors]
        return result

    def _build_manager_daily_empty_state_result(
        self,
        *,
        status: str,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        send_email: bool,
        reason_codes: list[str],
        relevant_calls: int,
        ready_analyses: int,
        analysis_coverage: float,
        missing: list[str],
        readiness: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Render an operator-only empty-state shell for non-deliverable manager_daily."""
        payload = self._build_manager_daily_empty_state_payload(
            artifacts=artifacts,
            period=period,
            filters=filters,
            mode=mode,
            model_override=model_override,
            status=status,
            reason_codes=reason_codes,
            relevant_calls=relevant_calls,
            ready_analyses=ready_analyses,
            analysis_coverage=analysis_coverage,
            readiness=readiness,
            missing=missing,
        )
        rendered = render_report_email(payload, prefer_docx_first=True)
        preview = {key: value for key, value in rendered.items() if key != "pdf_bytes"}
        delivery = self.delivery.deliver_operator_report(
            primary_email=None,
            cc_emails=[],
            subject=rendered["subject"],
            text=rendered["text"],
            html=rendered["html"],
            pdf_bytes=rendered["pdf_bytes"],
            pdf_filename=rendered["artifact"]["filename"],
            template_meta=rendered.get("template"),
            artifact_meta=rendered.get("artifact"),
            send_business_email=False,
            email_resolution_error=None,
            morning_card_text=rendered.get("morning_card_text"),
        )
        result = {
            "status": status,
            "preset": "manager_daily",
            "group_key": payload["meta"]["group_key"],
            "errors": list(missing),
            "payload": payload,
            "preview": preview,
            "artifact": rendered.get("artifact"),
            "delivery": delivery,
            "preview_only": True,
            "not_deliverable_manager_report": True,
            "readiness_outcome": status if status in {"skip_accumulate", "no_data", "missing_artifacts"} else "skip_accumulate",
            "readiness_reason_codes": list(reason_codes),
            "window_days_used": (readiness or {}).get("window_days_used"),
            "relevant_calls": relevant_calls,
            "ready_analyses": ready_analyses,
            "analysis_coverage": analysis_coverage,
            "content_blocks": dict((readiness or {}).get("content_blocks") or {}),
            "readiness": readiness,
        }
        return result

    def _build_manager_daily_empty_state_payload(
        self,
        *,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
        status: str,
        reason_codes: list[str],
        relevant_calls: int,
        ready_analyses: int,
        analysis_coverage: float,
        readiness: dict[str, Any] | None,
        missing: list[str],
    ) -> dict[str, Any]:
        """Build a preview-only shell payload for non-deliverable manager_daily."""
        manager_name = self._resolve_manager_daily_empty_state_manager_name(
            artifacts=artifacts,
            filters=filters,
        )
        department_name = self._resolve_department_name()
        status_label = {
            "skip_accumulate": "Недостаточно данных для deliverable отчёта",
            "missing_artifacts": "Недостаточно ready-артефактов",
            "no_data": "Нет звонков по выбранным фильтрам",
        }.get(status, "Недостаточно данных")
        formatted_coverage = round(float(analysis_coverage or 0.0), 1)
        reason_lines = [code.replace("_", " ") for code in reason_codes[:6]]
        if not reason_lines:
            reason_lines = ["Нужно больше готовых данных для полного daily report."]
        explanation = (
            f"Это preview shell для оператора. Полноценный manager_daily не собран: "
            f"найдено {relevant_calls} звонков, ready analyses {ready_analyses}, coverage {formatted_coverage}%."
        )
        if status == "no_data":
            explanation = (
                "Это preview shell для оператора. По выбранным фильтрам не найдено persisted звонков, "
                "которые можно включить в daily report без нового build."
            )
        elif status == "missing_artifacts":
            explanation = (
                "Это preview shell для оператора. Persisted звонки найдены, но ready transcript/analysis "
                "недостаточны для сборки обычного daily report."
            )

        payload = {
            "meta": _build_base_meta(
                preset="manager_daily",
                department_id=str(getattr(self, "department_id", "unknown-department")),
                period=period,
                filters=filters,
                mode=mode,
                model_override=model_override,
                artifacts=artifacts,
                group_key=f"manager_daily_preview:{manager_name}:{period['date_from']}",
            ),
            "empty_state": {
                "enabled": True,
                "status": status,
                "reason_codes": list(reason_codes),
                "summary_cards": [
                    {"label": "Найдено звонков", "value": relevant_calls, "tone": "blue"},
                    {"label": "Ready analyses", "value": ready_analyses, "tone": "yellow"},
                    {"label": "Coverage", "value": f"{formatted_coverage}%", "tone": "problem"},
                    {"label": "Окно", "value": f"{(readiness or {}).get('window_days_used', 1)} раб. дн.", "tone": "focus"},
                    {"label": "Статус", "value": status, "tone": "problem"},
                ],
                "hero_focus": "PREVIEW • insufficient data • not a deliverable manager report",
                "footer": "Preview shell · Недостаточно данных · Не отправлять менеджеру как обычный daily report",
                "generation_note": (
                    "Operator-facing preview shell only. "
                    "Этот artifact показывает layout и diagnostics, но не считается deliverable manager report."
                ),
            },
            "header": {
                "report_title": "PREVIEW — Ежедневный разбор звонков",
                "manager_id": str(artifacts[0].interaction.manager_id) if artifacts and artifacts[0].interaction.manager_id else None,
                "manager_name": manager_name,
                "report_date": _format_period_label(period),
                "department_name": department_name,
                "department_id": str(getattr(self, "department_id", "unknown-department")),
                "product_or_business_context": None,
            },
            "focus_of_week": {
                "text": "Preview shell: структура daily report показана, но данных для deliverable результата недостаточно.",
                "is_placeholder": True,
            },
            "kpi_overview": {
                "calls_count": relevant_calls,
                "average_score": None,
                "strong_calls_pct": None,
                "baseline_calls_pct": None,
                "problematic_calls_pct": None,
                "score_vs_period_avg": None,
                "delta_vs_period_avg": None,
                "interpretation_label": status_label,
            },
            "narrative_day_conclusion": {
                "text": explanation,
                "source": "preview_shell",
                "model_dependent": False,
            },
            "signal_of_day": {
                "call_time": None,
                "client_or_phone_mask": "Preview shell",
                "short_evidence": "Сильный/критичный сигнал не выделен: итоговый deliverable report не собран.",
                "reason_this_matters": "Показываем форму отчёта и диагностику, не маскируя слабую базу под рабочий daily report.",
                "is_placeholder": True,
            },
            "main_focus_for_tomorrow": {
                "text": "Следующий шаг — либо накопить больше ready persisted analyses, либо запускать build_missing_and_report отдельной задачей.",
                "source": "preview_shell",
                "model_dependent": False,
            },
            "analysis_worked": [
                {
                    "label": "Placeholder секции",
                    "signal": 0,
                    "interpretation": "Здесь будут сильные зоны, когда ready dataset станет достаточным для deliverable daily report.",
                }
            ],
            "analysis_improve": [
                {
                    "label": "Почему отчёт не собран",
                    "signal": len(reason_codes),
                    "interpretation": "; ".join(reason_lines),
                }
            ],
            "key_problem_of_day": {
                "title": "Недостаточно данных для итогового разбора",
                "description": "Отчёт за этот день не собран: звонки найдены, но анализов недостаточно для полноценного daily report.",
            },
            "recommendations": [
                {
                    "priority_tag": "На неделе",
                    "title": "Почему это preview, а не deliverable report",
                    "reason": explanation,
                    "how_it_sounded": "Reason codes: " + (", ".join(reason_codes[:5]) if reason_codes else "нет"),
                    "better_phrasing": "Не отправлять менеджеру как обычный daily report. Использовать только для operator preview и диагностики.",
                    "why_this_works": "Позволяет увидеть layout отчёта и причины недосбора без запуска новых AI шагов.",
                }
            ],
            "call_outcomes_summary": {
                "agreed_count": 0,
                "rescheduled_count": 0,
                "refusal_count": 0,
                "open_count": 0,
                "tech_service_count": 0,
            },
            "score_by_stage": [],
            "call_list": [
                {
                    "time": period["date_from"],
                    "client_or_phone": "Preview shell",
                    "duration_sec": "—",
                    "status": status,
                    "score_percent": f"{formatted_coverage}%",
                    "next_step": "Открыть diagnostics и reason codes вместо отправки обычного daily report.",
                }
            ],
            "focus_criterion_dynamics": {
                "focus_criterion_name": "Readiness / coverage",
                "current_period_value": f"{formatted_coverage}%",
                "previous_period_value": f"{ready_analyses} ready analyses",
                "delta": f"{relevant_calls} найдено",
            },
            "memo_legend": {
                "call_level_legend": [
                    "Preview shell",
                    "Insufficient data",
                    "Not a deliverable manager report",
                ],
                "call_status_legend": [
                    f"preset=manager_daily",
                    f"mode={mode}",
                    f"period={period['date_from']}..{period['date_to']}",
                ],
                "recommendation_priority_legend": [
                    f"readiness_outcome={status}",
                    f"reason_codes={', '.join(reason_codes[:4]) if reason_codes else 'n/a'}",
                    "business email intentionally disabled for this shell",
                ],
            },
            "delivery_meta": {
                "email_subject": f"[PREVIEW][INSUFFICIENT DATA] manager_daily — {manager_name} — {_format_period_label(period)}",
                "render_variant": f"template_pdf_{get_active_template_version('manager_daily')}",
            },
        }
        payload["meta"]["empty_state"] = {
            "status": status,
            "reason_codes": list(reason_codes),
            "not_deliverable_manager_report": True,
        }
        return payload

    def _resolve_department_name(self) -> str:
        """Return department name for shell/report payloads."""
        db = getattr(self, "db", None)
        if db is not None:
            department = db.query(Department).filter(Department.id == self.department_id).first()
            if department is not None and str(department.name or "").strip():
                return str(department.name)
        return "Отдел продаж"

    def _resolve_manager_daily_empty_state_manager_name(
        self,
        *,
        artifacts: list[ReportArtifact],
        filters: ReportRunFilters,
    ) -> str:
        """Resolve the display manager name for a preview-only daily shell."""
        if artifacts:
            manager = artifacts[0].manager
            if manager is not None and str(manager.name or "").strip():
                return str(manager.name)
            interaction_metadata = dict(artifacts[0].interaction.metadata_ or {})
            if str(interaction_metadata.get("manager_name") or "").strip():
                return str(interaction_metadata["manager_name"]).strip()
        if len(filters.manager_ids) == 1:
            db = getattr(self, "db", None)
            if db is not None:
                try:
                    manager_id = UUID(filters.manager_ids[0])
                except ValueError:
                    manager_id = None
                if manager_id is not None:
                    manager = db.query(Manager).filter(Manager.id == manager_id).first()
                    if manager is not None and str(manager.name or "").strip():
                        return str(manager.name)
        if len(filters.manager_extensions) == 1:
            return f"Менеджер {filters.manager_extensions[0]}"
        return "Менеджер не выбран"

    def _resolve_delivery_targets(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
    ) -> dict[str, Any]:
        """Resolve primary recipient and monitoring copy for the report."""
        department = (
            self.db.query(Department)
            .filter(Department.id == self.department_id)
            .first()
        )
        reporting_settings = dict((department.settings or {}).get("reporting") or {}) if department else {}
        monitoring_email = (
            reporting_settings.get("monitoring_email")
            or REPORTING_MONITORING_EMAIL
        )

        if preset.recipient_kind == "manager":
            manager = artifacts[0].manager
            if manager is None or not manager.email:
                raise DeliveryError(
                    "manager_daily recipient is not resolvable. Expected manager email in Bitrix-synced manager card."
                )
            return {
                "primary_email": manager.email,
                "cc_emails": [email for email in [monitoring_email] if email and email != manager.email],
            }

        primary_email = (
            reporting_settings.get("rop_weekly_email")
            or (reporting_settings.get("recipient_resolution") or {}).get("rop_weekly_email")
            or self._resolve_rop_weekly_email_from_bitrix_head(department=department)
        )
        if not primary_email:
            raise DeliveryError(
                "rop_weekly recipient is not configured. Set department.settings.reporting.rop_weekly_email "
                "or ensure Bitrix department UF_HEAD resolves to an active user with email."
            )
        return {
            "primary_email": primary_email,
            "cc_emails": [email for email in [monitoring_email] if email and email != primary_email],
        }

    def _resolve_rop_weekly_email_from_bitrix_head(
        self,
        *,
        department: Department | None,
    ) -> str | None:
        """Resolve the weekly recipient from Bitrix department head when local config is absent."""
        if department is None:
            return None
        department_settings = dict(department.settings or {})
        bitrix_department_id = str(department_settings.get("bitrix_department_id") or "").strip()
        if not bitrix_department_id:
            return None

        client = Bitrix24ReadOnlyClient()
        try:
            departments = client.list_departments()
        except BitrixReadOnlyError:
            return None

        head_user_id = next(
            (
                item.head_user_id
                for item in departments
                if item.bitrix_department_id == bitrix_department_id and item.head_user_id
            ),
            None,
        )
        if not head_user_id:
            return None

        try:
            head_user = client.get_user_by_id(head_user_id)
        except BitrixReadOnlyError:
            return None
        if head_user is None or not head_user.active or not head_user.email:
            return None
        return head_user.email

    def _build_payload(
        self,
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
        filters: ReportRunFilters,
        mode: str,
        model_override: str | None,
    ) -> dict[str, Any]:
        """Build a normalized preset payload before rendering."""
        department_id = str(getattr(self, "department_id", "unknown-department"))
        department_name = "Отдел продаж"
        db = getattr(self, "db", None)
        if db is not None:
            department = (
                db.query(Department)
                .filter(Department.id == self.department_id)
                .first()
            )
            if department is not None and str(department.name or "").strip():
                department_name = department.name
        if preset.code == "manager_daily":
            return build_manager_daily_payload(
                department_id=department_id,
                department_name=department_name,
                artifacts=artifacts,
                period=period,
                filters=filters,
                mode=mode,
                model_override=model_override,
            )
        return build_rop_weekly_payload(
            department_id=department_id,
            department_name=department_name,
            artifacts=artifacts,
            period=period,
            filters=filters,
            mode=mode,
            model_override=model_override,
        )

    @staticmethod
    def _build_group_key(
        *,
        preset: ReportPreset,
        artifacts: list[ReportArtifact],
        period: dict[str, str],
    ) -> str:
        """Build a deterministic key for one report group."""
        if preset.code == "manager_daily":
            manager_id = str(artifacts[0].interaction.manager_id or "unmapped")
            return f"{preset.code}:{manager_id}:{period['date_from']}"
        return f"{preset.code}:{period['date_from']}:{period['date_to']}"


def parse_call_started_at(metadata: dict[str, Any]) -> datetime | None:
    """Parse persisted call date metadata into UTC-aware datetime."""
    raw = str(metadata.get("call_date") or metadata.get("call_started_at") or "").strip()
    if not raw:
        return None
    candidates = (
        raw,
        raw.replace(" ", "T"),
        raw.replace("Z", "+00:00"),
    )
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _last_workdays(*, anchor: date, count: int) -> list[str]:
    """Return the last N working days inclusive of anchor, skipping weekends."""
    days: list[str] = []
    current = anchor
    while len(days) < max(count, 0):
        if current.weekday() < 5:
            days.append(current.isoformat())
        current -= timedelta(days=1)
    return list(reversed(days))


def _build_manager_daily_readiness_result(
    *,
    outcome: str,
    reason_codes: list[str],
    window: ManagerDailyWindow,
    relevant_calls: int,
    ready_analyses: int,
    analysis_coverage: float,
    content_blocks: dict[str, bool],
    content_signals: dict[str, Any],
) -> dict[str, Any]:
    """Return one normalized readiness payload for decision transparency."""
    return {
        "readiness_outcome": outcome,
        "readiness_reason_codes": reason_codes,
        "window_days_used": window.workdays_used,
        "effective_period": dict(window.period),
        "relevant_calls": relevant_calls,
        "ready_analyses": ready_analyses,
        "analysis_coverage": analysis_coverage,
        "content_blocks": content_blocks,
        "content_signals": content_signals,
    }


def _evaluate_manager_daily_readiness(
    *,
    artifacts: list[ReportArtifact],
    usable_artifacts: list[ReportArtifact],
    payload: dict[str, Any] | None,
    window: ManagerDailyWindow,
) -> dict[str, Any]:
    """Choose full_report, signal_report, or skip_accumulate for one manager_daily window."""
    relevant_calls = len(artifacts)
    ready_analyses = len(usable_artifacts)
    analysis_coverage = _pct(ready_analyses, relevant_calls) if relevant_calls else 0.0

    worked_items = list((payload or {}).get("analysis_worked") or [])
    improve_items = list((payload or {}).get("analysis_improve") or [])
    recommendations = list((payload or {}).get("recommendations") or [])
    narrative = str(((payload or {}).get("narrative_day_conclusion") or {}).get("text") or "").strip()
    key_problem = dict((payload or {}).get("key_problem_of_day") or {})
    signal_of_day = dict((payload or {}).get("signal_of_day") or {})

    strong_zones_count = len([item for item in worked_items if _is_meaningful_finding(item)])
    growth_zones_count = len([item for item in improve_items if _is_meaningful_finding(item)])
    main_problems_count = 1 if _is_meaningful_key_problem(key_problem) else 0
    normal_recommendations_count = len(
        [item for item in recommendations if _is_meaningful_recommendation(item)]
    )

    content_blocks = {
        "day_summary_ready": bool(narrative),
        "review_ready": strong_zones_count > 0 and growth_zones_count > 0,
        "key_problem_ready": main_problems_count > 0,
        "recommendations_ready": normal_recommendations_count > 0,
    }
    has_positive_signal = bool(str(signal_of_day.get("short_evidence") or "").strip()) and any(
        _score_bucket(item.analysis) == "strong" for item in usable_artifacts
    )
    has_critical_signal = main_problems_count > 0 and any(
        _score_bucket(item.analysis) == "problematic" for item in usable_artifacts
    )
    has_coaching_pattern = any(int(item.get("signal") or 0) >= 2 for item in improve_items if _is_meaningful_finding(item))
    has_manager_action = normal_recommendations_count > 0

    content_signals = {
        "strong_zones_count": strong_zones_count,
        "growth_zones_count": growth_zones_count,
        "main_problems_count": main_problems_count,
        "normal_recommendations_count": normal_recommendations_count,
        "positive_signal_available": has_positive_signal,
        "critical_signal_available": has_critical_signal,
        "coaching_pattern_available": has_coaching_pattern,
        "manager_action_available": has_manager_action,
    }

    full_reasons: list[str] = []
    if relevant_calls < MANAGER_DAILY_FULL_REPORT_MIN_RELEVANT_CALLS:
        full_reasons.append("relevant_calls_below_full_threshold")
    if ready_analyses < MANAGER_DAILY_FULL_REPORT_MIN_READY_ANALYSES:
        full_reasons.append("ready_analyses_below_full_threshold")
    if analysis_coverage < MANAGER_DAILY_FULL_REPORT_MIN_ANALYSIS_COVERAGE:
        full_reasons.append("analysis_coverage_below_full_threshold")
    if not content_blocks["day_summary_ready"]:
        full_reasons.append("content_block_day_summary_missing")
    if not content_blocks["review_ready"]:
        full_reasons.append("content_block_review_missing")
    if not content_blocks["key_problem_ready"]:
        full_reasons.append("content_block_key_problem_missing")
    if not content_blocks["recommendations_ready"]:
        full_reasons.append("content_block_recommendations_missing")
    if strong_zones_count <= 0:
        full_reasons.append("strong_zone_missing")
    if growth_zones_count <= 0:
        full_reasons.append("growth_zone_missing")
    if main_problems_count <= 0:
        full_reasons.append("main_problem_missing")
    if normal_recommendations_count <= 0:
        full_reasons.append("normal_recommendation_missing")
    if not full_reasons:
        return _build_manager_daily_readiness_result(
            outcome="full_report",
            reason_codes=["full_report_ready"],
            window=window,
            relevant_calls=relevant_calls,
            ready_analyses=ready_analyses,
            analysis_coverage=analysis_coverage,
            content_blocks=content_blocks,
            content_signals=content_signals,
        )

    signal_reasons: list[str] = list(full_reasons)
    if ready_analyses < MANAGER_DAILY_SIGNAL_REPORT_MIN_READY_ANALYSES:
        signal_reasons.append("ready_analyses_below_signal_threshold")
    if not (has_positive_signal or has_critical_signal or has_coaching_pattern):
        signal_reasons.append("signal_case_not_found")
    if not has_manager_action:
        signal_reasons.append("manager_action_missing")
    if ready_analyses >= MANAGER_DAILY_SIGNAL_REPORT_MIN_READY_ANALYSES and (
        has_positive_signal or has_critical_signal or has_coaching_pattern
    ) and has_manager_action:
        outcome_reasons = ["signal_report_ready"]
        if has_positive_signal:
            outcome_reasons.append("signal_positive_case_available")
        if has_critical_signal:
            outcome_reasons.append("signal_critical_case_available")
        if has_coaching_pattern:
            outcome_reasons.append("signal_coaching_pattern_available")
        return _build_manager_daily_readiness_result(
            outcome="signal_report",
            reason_codes=outcome_reasons,
            window=window,
            relevant_calls=relevant_calls,
            ready_analyses=ready_analyses,
            analysis_coverage=analysis_coverage,
            content_blocks=content_blocks,
            content_signals=content_signals,
        )

    deduped_reasons: list[str] = []
    for code in ["skip_accumulate_readiness_not_met", *signal_reasons]:
        if code not in deduped_reasons:
            deduped_reasons.append(code)
    return _build_manager_daily_readiness_result(
        outcome="skip_accumulate",
        reason_codes=deduped_reasons,
        window=window,
        relevant_calls=relevant_calls,
        ready_analyses=ready_analyses,
        analysis_coverage=analysis_coverage,
        content_blocks=content_blocks,
        content_signals=content_signals,
    )


def _is_meaningful_finding(item: dict[str, Any]) -> bool:
    """Return True when the finding item is populated enough for readiness."""
    return bool(str(item.get("label") or "").strip() and str(item.get("interpretation") or "").strip())


def _is_meaningful_key_problem(value: dict[str, Any]) -> bool:
    """Return True when key_problem_of_day is not a deterministic fallback."""
    title = str(value.get("title") or "").strip()
    description = str(value.get("description") or "").strip()
    if not title or not description:
        return False
    return not (
        title == MANAGER_DAILY_FALLBACK_KEY_PROBLEM_TITLE
        and description == MANAGER_DAILY_FALLBACK_KEY_PROBLEM_DESCRIPTION
    )


def _is_meaningful_recommendation(item: dict[str, Any]) -> bool:
    """Return True when the recommendation card is not the bounded fallback placeholder."""
    title = str(item.get("title") or "").strip()
    better_phrasing = str(item.get("better_phrasing") or "").strip()
    if not title or not better_phrasing:
        return False
    return title != MANAGER_DAILY_FALLBACK_RECOMMENDATION_TITLE


def build_manager_daily_payload(
    *,
    department_id: str,
    department_name: str,
    artifacts: list[ReportArtifact],
    period: dict[str, str],
    filters: ReportRunFilters,
    mode: str,
    model_override: str | None,
) -> dict[str, Any]:
    """Build the normalized manager_daily payload."""
    manager = artifacts[0].manager
    manager_name = manager.name if manager is not None else _fallback_manager_name(artifacts[0])
    calls_count = len(artifacts)
    score_values = [_extract_score_percent(item.analysis) for item in artifacts]
    average_score = round(sum(score_values) / len(score_values), 1) if score_values else None
    recent_score = _latest_call_score(artifacts)
    level_counts = {"strong": 0, "baseline": 0, "problematic": 0}
    worked_items = _aggregate_finding_items(artifacts=artifacts, key="strengths")
    improve_items = _aggregate_finding_items(artifacts=artifacts, key="gaps")
    recommendation_cards = _aggregate_recommendation_cards(artifacts=artifacts)
    product_signal = _select_most_important_product_signal(artifacts)
    evidence_fragment = _select_evidence_fragment(artifacts)
    key_problem = _build_manager_daily_key_problem(improve_items=improve_items, artifacts=artifacts, calls_count=calls_count)
    call_breakdown = _build_call_breakdown(improve_items=improve_items, artifacts=artifacts)
    voice_of_customer = _build_voice_of_customer(artifacts=artifacts)
    additional_situations = _build_additional_situations(
        improve_items=improve_items,
        worked_items=worked_items,
        top_gap_title=(improve_items[0]["label"] if improve_items else None),
    )
    call_tomorrow = _build_call_tomorrow(artifacts=artifacts)
    focus_dynamics = _build_focus_criterion_dynamics(artifacts=artifacts, improve_items=improve_items)
    call_outcomes_summary = _build_call_outcomes_summary(artifacts=artifacts)
    score_by_stage = _aggregate_stage_scores(artifacts=artifacts)
    for artifact in artifacts:
        bucket = _score_bucket(artifact.analysis)
        level_counts[bucket] += 1

    payload = {
        "meta": _build_base_meta(
            preset="manager_daily",
            department_id=department_id,
            period=period,
            filters=filters,
            mode=mode,
            model_override=model_override,
            artifacts=artifacts,
            group_key=f"manager_daily:{artifacts[0].interaction.manager_id}:{period['date_from']}",
        ),
        "header": {
            "report_title": "Ежедневный разбор звонков",
            "manager_id": str(artifacts[0].interaction.manager_id) if artifacts[0].interaction.manager_id else None,
            "manager_name": manager_name,
            "report_date": _format_period_label(period),
            "department_name": department_name,
            "department_id": department_id,
            "product_or_business_context": None,
        },
        "focus_of_week": {
            "text": _build_focus_of_week(improve_items=improve_items, worked_items=worked_items),
            "is_placeholder": False if improve_items or worked_items else True,
        },
        "kpi_overview": {
            "calls_count": calls_count,
            "average_score": average_score,
            "strong_calls_pct": _pct(level_counts["strong"], calls_count),
            "baseline_calls_pct": _pct(level_counts["baseline"], calls_count),
            "problematic_calls_pct": _pct(level_counts["problematic"], calls_count),
            "score_vs_period_avg": recent_score,
            "delta_vs_period_avg": round(recent_score - average_score, 1)
            if recent_score is not None and average_score is not None
            else None,
            "interpretation_label": _performance_label(average_score),
        },
        "narrative_day_conclusion": {
            "text": _build_manager_daily_narrative(
                manager_name=manager_name,
                average_score=average_score,
                calls_count=calls_count,
                worked_items=worked_items,
                improve_items=improve_items,
            ),
            "source": "deterministic_fallback",
            "model_dependent": True,
        },
        "signal_of_day": {
            "call_time": _best_call_time(artifacts),
            "client_or_phone_mask": _best_contact(artifacts),
            "short_evidence": _best_signal_text(artifacts, evidence_fragment=evidence_fragment),
            "reason_this_matters": _build_signal_reason(
                product_signal=product_signal,
                worked_items=worked_items,
            ),
            "is_placeholder": False if artifacts else True,
        },
        "main_focus_for_tomorrow": {
            "text": _build_main_focus(
                improve_items=improve_items,
                recommendation_cards=recommendation_cards,
            ),
            "source": "deterministic_fallback",
            "model_dependent": True,
        },
        "analysis_worked": worked_items,
        "analysis_improve": improve_items,
        "key_problem_of_day": key_problem,
        "call_breakdown": call_breakdown,
        "voice_of_customer": voice_of_customer,
        "additional_situations": additional_situations,
        "call_tomorrow": call_tomorrow,
        "recommendations": recommendation_cards,
        "call_outcomes_summary": call_outcomes_summary,
        "score_by_stage": score_by_stage,
        "call_list": [_build_daily_call_row(item) for item in artifacts],
        "focus_criterion_dynamics": focus_dynamics,
        "memo_legend": {
            "call_level_legend": ["strong", "baseline", "problematic"],
            "call_status_legend": ["agreed", "rescheduled", "refusal", "open"],
            "recommendation_priority_legend": ["Сделай завтра", "На неделе"],
        },
        "delivery_meta": {
            "email_subject": f"Ежедневный разбор звонков — {manager_name} — {_format_period_label(period)}",
            "render_variant": f"template_pdf_{get_active_template_version('manager_daily')}",
        },
        "editorial_recommendations": {
            "text": _build_manager_daily_editorial_recommendations(
                recommendation_cards=recommendation_cards,
            ),
        },
    }
    return payload


def build_rop_weekly_payload(
    *,
    department_id: str,
    department_name: str,
    artifacts: list[ReportArtifact],
    period: dict[str, str],
    filters: ReportRunFilters,
    mode: str,
    model_override: str | None,
) -> dict[str, Any]:
    """Build the normalized rop_weekly payload."""
    by_manager: dict[str, list[ReportArtifact]] = {}
    for artifact in artifacts:
        key = str(artifact.interaction.manager_id or "unmapped")
        by_manager.setdefault(key, []).append(artifact)

    dashboard_rows = [_build_weekly_dashboard_row(group) for _, group in sorted(by_manager.items())]
    risk_zone_cards = [
        _build_risk_zone_card(group)
        for group in by_manager.values()
        if _build_weekly_dashboard_row(group)["status_signal"] in {"Наблюдение", "Зона риска"}
    ]
    systemic_team_problems = _build_systemic_problems(artifacts)
    top_block, anti_top_block = _build_top_blocks(dashboard_rows)
    current_period_score = round(
        sum(row["average_score"] for row in dashboard_rows if row["average_score"] is not None)
        / max(1, len([row for row in dashboard_rows if row["average_score"] is not None])),
        1,
    ) if dashboard_rows else None
    payload = {
        "meta": _build_base_meta(
            preset="rop_weekly",
            department_id=department_id,
            period=period,
            filters=filters,
            mode=mode,
            model_override=model_override,
            artifacts=artifacts,
            group_key=f"rop_weekly:{period['date_from']}:{period['date_to']}",
        ),
        "header": {
            "report_title": "Еженедельный отчёт",
            "subtitle": "Недельный управленческий обзор по качеству звонков команды продаж",
            "department_id": department_id,
            "department_name": department_name,
            "week_label": f"{period['date_from']}..{period['date_to']}",
            "date_range": period,
            "confidentiality_note": "Только для РОП и руководства",
        },
        "what_is_inside": [
            "dashboard",
            "week_over_week_dynamics",
            "risk_zones",
            "systemic_problems",
            "top_and_anti_top",
            "rop_tasks",
            "business_results_placeholder",
        ],
        "dashboard_rows": dashboard_rows,
        "week_over_week_dynamics": {
            "previous_period_score": None,
            "current_period_score": current_period_score,
            "delta": None,
            "trend": "n/a",
            "stage_level_deltas": [],
            "best_dynamics_commentary": _build_weekly_best_commentary(
                dashboard_rows=dashboard_rows,
                top_block=top_block,
            ),
            "alarming_dynamics_commentary": _build_weekly_alarm_commentary(
                anti_top_block=anti_top_block,
                systemic_team_problems=systemic_team_problems,
            ),
        },
        "risk_zone_cards": risk_zone_cards,
        "systemic_team_problems": systemic_team_problems,
        "top_block": top_block,
        "anti_top_block": anti_top_block,
        "rop_tasks_next_week": _build_rop_tasks(risk_zone_cards=risk_zone_cards, systemic_team_problems=systemic_team_problems),
        "business_results_placeholder": {
            "status": "placeholder",
            "reason": "crm_dependent_block_not_connected_in_manual_reporting_pilot_v1",
        },
        "leader_memo": {
            "status_signal_explanation": ["Эталон", "Растёт", "Стабильно", "Наблюдение", "Зона риска"],
            "trend_explanation": "Детальная динамика будет усилена после подключения устойчивой historical comparison базы.",
            "score_scale": "0-100",
            "action_priority_explanation": ["Критично", "Высокий", "Средний", "Поддержка"],
        },
        "delivery_meta": {
            "email_subject": f"Еженедельный отчёт РОП — {period['date_from']}..{period['date_to']}",
            "render_variant": f"template_pdf_{get_active_template_version('rop_weekly')}",
        },
    }
    payload["editorial_summary"] = {
        "executive_summary": _build_rop_weekly_executive_summary(
            department_name=department_name,
            dashboard_rows=dashboard_rows,
            current_period_score=current_period_score,
        ),
        "team_risks_wording": _build_rop_weekly_team_risks(
            systemic_team_problems=systemic_team_problems,
            anti_top_block=anti_top_block,
        ),
        "rop_tasks_wording": _build_rop_weekly_tasks_commentary(
            tasks=payload["rop_tasks_next_week"],
        ),
        "final_managerial_commentary": _build_rop_weekly_final_commentary(
            top_block=top_block,
            anti_top_block=anti_top_block,
        ),
    }
    return payload


def render_report_email(payload: dict[str, Any], *, prefer_docx_first: bool = False) -> dict[str, Any]:
    """Render the final operator artifact from versioned template assets."""
    return render_report_artifact(payload, prefer_docx_first=prefer_docx_first)


def _build_base_meta(
    *,
    preset: str,
    department_id: str,
    period: dict[str, str],
    filters: ReportRunFilters,
    mode: str,
    model_override: str | None,
    artifacts: list[ReportArtifact],
    group_key: str,
) -> dict[str, Any]:
    """Build stable report metadata for audit and reuse."""
    instruction_versions = sorted(
        {
            item.analysis.instruction_version
            for item in artifacts
            if item.analysis is not None and item.analysis.instruction_version
        }
    )
    return {
        "preset": preset,
        "schema_version": REPORTING_SCHEMA_VERSION,
        "report_logic_version": REPORTING_LOGIC_VERSION,
        "reuse_policy_version": REPORTING_REUSE_POLICY_VERSION,
        "checklist_version": APPROVED_CHECKLIST_VERSION,
        "template_version": get_active_template_version(preset),
        "template_id": get_active_template_version(preset),
        "render_variant": f"template_pdf_{get_active_template_version(preset)}",
        "generator_path": "app.agents.calls.report_templates.render_report_artifact",
        "generated_at": datetime.now(UTC).isoformat(),
        "department_id": department_id,
        "period": period,
        "mode": mode,
        "group_key": group_key,
        "filters": {
            "manager_ids": sorted(filters.manager_ids),
            "manager_extensions": sorted(filters.manager_extensions),
            "min_duration_sec": filters.min_duration_sec,
            "max_duration_sec": filters.max_duration_sec,
        },
        "report_composer": {
            "enabled": False,
            "selected_model": model_override,
            "status": "not_enabled_in_v1",
        },
        "effective_versions": {
            "schema_version": REPORTING_SCHEMA_VERSION,
            "report_logic_version": REPORTING_LOGIC_VERSION,
            "reuse_policy_version": REPORTING_REUSE_POLICY_VERSION,
            "checklist_version": APPROVED_CHECKLIST_VERSION,
            "template_version": get_active_template_version(preset),
            "template_id": get_active_template_version(preset),
            "render_variant": f"template_pdf_{get_active_template_version(preset)}",
            "generator_path": "app.agents.calls.report_templates.render_report_artifact",
            "analysis_instruction_versions": instruction_versions,
        },
        "reuse": {
            "report_payload_reused": False,
            "render_reused": False,
            "enough_for_reuse": {
                "transcript": all(bool(item.interaction.text) for item in artifacts),
                "analysis": all(_is_analysis_reusable_for_reporting(item.analysis)[0] for item in artifacts),
            },
            "rebuild_on_version_mismatch": [
                "report_payload",
                "readiness_decision",
                "rendered_artifact",
            ],
        },
        "source_artifacts": {
            "interaction_count": len(artifacts),
            "analysis_count": len([item for item in artifacts if item.analysis is not None]),
            "instruction_versions": instruction_versions,
        },
    }


_STAGE_FUNNEL_ORDER: list[tuple[str, str, str]] = [
    ("contact_start", "Э1", "Первичный контакт"),
    ("qualification_primary", "Э2", "Квалификация и первичная потребность"),
    ("needs_discovery", "Э3", "Выявление детальных потребностей"),
    ("presentation", "Э4", "Формирование предложения"),
    ("objection_handling", "Э5", "Работа с возражениями"),
    ("completion_next_step", "Э6", "Завершение и договорённости"),
    ("cross_stage_transition", "Сквозной", "Сквозной критерий"),
]


def _aggregate_stage_scores(*, artifacts: list[ReportArtifact]) -> list[dict[str, Any]]:
    """Average per-call stage scores across all artifacts, ordered by funnel.

    Score scale: 0–10 (stage_score / max_stage_score * 10).
    Priority rule: first stage below 4.0 in funnel order is marked as priority.
    For the priority stage, criteria_detail is populated (avg per criterion, sorted asc).
    """
    stage_buckets: dict[str, list[float]] = {}
    crit_stage: dict[str, dict[str, list[float]]] = {}
    crit_names: dict[str, str] = {}
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for stage in detail.get("score_by_stage") or []:
            code = str(stage.get("stage_code") or "")
            stage_score = int(stage.get("stage_score") or 0)
            max_score = int(stage.get("max_stage_score") or 0)
            if max_score > 0:
                stage_buckets.setdefault(code, []).append(round(stage_score / max_score * 10, 1))
            for crit in stage.get("criteria_results") or []:
                ccode = str(crit.get("criterion_code") or "").strip()
                cname = str(crit.get("criterion_name") or ccode).strip()
                cscore = int(crit.get("score") or 0)
                cmax = int(crit.get("max_score") or 0)
                if ccode and cmax > 0:
                    crit_stage.setdefault(code, {}).setdefault(ccode, []).append(round(cscore / cmax * 10, 1))
                    crit_names.setdefault(ccode, cname)
    rows: list[dict[str, Any]] = []
    priority_found = False
    for stage_code, funnel_label, stage_name in _STAGE_FUNNEL_ORDER:
        scores = stage_buckets.get(stage_code)
        if not scores:
            continue
        avg = round(sum(scores) / len(scores), 1)
        is_priority = not priority_found and avg < 4.0
        if is_priority:
            priority_found = True
        criteria_detail: list[dict[str, Any]] | None = None
        if is_priority and crit_stage.get(stage_code):
            crits = []
            for ccode, cscores in crit_stage[stage_code].items():
                cavg = round(sum(cscores) / len(cscores), 1)
                crits.append({
                    "name": crit_names.get(ccode, ccode),
                    "score": cavg,
                    "is_weak": cavg < 5.0,
                })
            crits.sort(key=lambda x: x["score"])
            criteria_detail = crits[:5]
        rows.append({
            "stage_code": stage_code,
            "funnel_label": funnel_label,
            "stage_name": stage_name,
            "score": avg,
            "is_priority": is_priority,
            "criteria_detail": criteria_detail,
        })
    return rows


def _extract_score_percent(analysis: Analysis | None) -> float:
    """Read one normalized percentage from analysis payload."""
    if analysis is None:
        return 0.0
    if analysis.score_total is not None:
        return float(analysis.score_total)
    detail = dict(analysis.scores_detail or {})
    score = dict(detail.get("score") or {})
    checklist = dict(score.get("checklist_score") or {})
    return float(checklist.get("score_percent") or 0.0)


def _score_bucket(analysis: Analysis | None) -> str:
    """Map one call analysis to reporting bucket."""
    if analysis is None:
        return "problematic"
    detail = dict(analysis.scores_detail or {})
    score = dict(detail.get("score") or {})
    checklist = dict(score.get("checklist_score") or {})
    level = str(checklist.get("level") or "").lower()
    if level in {"excellent", "strong"}:
        return "strong"
    if level in {"basic"}:
        return "baseline"
    if level in {"problematic"}:
        return "problematic"
    score_percent = _extract_score_percent(analysis)
    if score_percent >= 80:
        return "strong"
    if score_percent >= 60:
        return "baseline"
    return "problematic"


def _aggregate_finding_items(*, artifacts: list[ReportArtifact], key: str) -> list[dict[str, Any]]:
    """Aggregate repeated strength/gap findings into compact report items."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for item in detail.get(key) or []:
            label = str(
                item.get("title")
                or item.get("criterion_name")
                or item.get("criterion_code")
                or "Без названия"
            )
            grouped.setdefault(label, []).append(item)
    result: list[dict[str, Any]] = []
    for label, items in sorted(grouped.items(), key=lambda pair: len(pair[1]), reverse=True)[:5]:
        first = items[0]
        result.append(
            {
                "label": label,
                "signal": len(items),
                "interpretation": str(
                    first.get("impact")
                    or first.get("comment")
                    or first.get("evidence")
                    or "Подтверждено в нескольких звонках."
                ),
            }
        )
    return result


def _aggregate_recommendation_cards(*, artifacts: list[ReportArtifact]) -> list[dict[str, Any]]:
    """Build daily recommendation cards from persisted recommendation payloads."""
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for item in detail.get("recommendations") or []:
            title = str(item.get("criterion_name") or item.get("criterion_code") or "Рекомендация")
            better_phrase = str(
                item.get("better_phrase")
                or item.get("recommendation")
                or item.get("problem")
                or "Уточнить формулировку и закрепить следующий шаг."
            )
            key = f"{title}:{better_phrase}"
            if key in seen:
                continue
            seen.add(key)
            cards.append(
                {
                    "priority_tag": "Сделай завтра" if len(cards) < 2 else "На неделе",
                    "title": title,
                    "reason": str(item.get("reason") or item.get("problem") or "Повторяется в нескольких звонках."),
                    "how_it_sounded": str(item.get("evidence") or "Нужен более точный пример из разговора."),
                    "better_phrasing": better_phrase,
                    "why_this_works": "Помогает сделать следующий шаг понятным и управляемым.",
                }
            )
            if len(cards) >= 5:
                return cards
    if not cards:
        cards.append(
            {
                "priority_tag": "На неделе",
                "title": "Пока недостаточно рекомендаций",
                "reason": "Для этой выборки не найдено устойчивых рекомендаций в persisted payload.",
                "how_it_sounded": "—",
                "better_phrasing": "Проверить полноту анализов и повторить запуск при необходимости.",
                "why_this_works": "Поможет закрыть пробел в данных без полного rerun.",
            }
        )
    return cards


def _build_manager_daily_narrative(
    *,
    manager_name: str,
    average_score: float | None,
    calls_count: int,
    worked_items: list[dict[str, Any]],
    improve_items: list[dict[str, Any]],
) -> str:
    """Return a bounded deterministic narrative until report-composer is activated."""
    label = _performance_label(average_score)
    top_strength = worked_items[0]["label"] if worked_items else "устойчивых сильных эпизодов"
    top_gap = improve_items[0]["label"] if improve_items else "одной доминирующей зоны роста"
    return (
        f"За период у менеджера {manager_name} по {calls_count} звонкам сформировался {label.lower()} результат. "
        f"Сильная сторона выборки: {top_strength}; главный риск: {top_gap}."
    )


def _build_main_focus(
    *,
    improve_items: list[dict[str, Any]],
    recommendation_cards: list[dict[str, Any]],
) -> str:
    """Select one short focus statement for the next day."""
    if not improve_items:
        return "Сохранить текущий темп и проверить полноту фиксации следующего шага."
    next_action = recommendation_cards[0]["better_phrasing"] if recommendation_cards else None
    if next_action:
        return (
            f"Главный фокус на следующий день: усилить '{improve_items[0]['label']}' "
            f"и закрепить это через формулировку: {next_action}"
        )
    return f"Главный фокус на следующий день: усилить '{improve_items[0]['label']}' в каждом разговоре."


def _build_manager_daily_editorial_recommendations(
    *,
    recommendation_cards: list[dict[str, Any]],
) -> str:
    """Build one short editable wording block for manager recommendations."""
    if not recommendation_cards:
        return (
            "Пока в выборке недостаточно устойчивых coaching-паттернов; держим фокус на "
            "конкретном следующем шаге и понятной договорённости."
        )
    lines = [
        f"{item['title']}: {item['better_phrasing']}"
        for item in recommendation_cards[:3]
        if str(item.get("better_phrasing") or "").strip()
    ]
    return " ; ".join(lines) if lines else recommendation_cards[0]["title"]


def _is_next_step_fixed(analysis: Analysis | None) -> bool:
    """Return whether the persisted follow_up marks a fixed next step."""
    detail = dict((analysis.scores_detail or {}) if analysis is not None else {})
    follow_up = dict(detail.get("follow_up") or {})
    return bool(follow_up.get("next_step_fixed"))


def _build_daily_call_row(artifact: ReportArtifact) -> dict[str, Any]:
    """Build one short daily call row."""
    detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
    call = dict(detail.get("call") or {})
    follow_up = dict(detail.get("follow_up") or {})
    classification = dict(detail.get("classification") or {})
    status, deadline = _derive_call_status_and_deadline(follow_up=follow_up)
    return {
        "time": artifact.call_started_at.isoformat() if artifact.call_started_at else None,
        "client_or_phone": call.get("contact_name") or call.get("contact_phone") or (artifact.interaction.metadata_ or {}).get("contact_phone"),
        "duration_sec": artifact.interaction.duration_sec,
        "call_type": classification.get("call_type"),
        "scenario_type": classification.get("scenario_type"),
        "status": status,
        "next_step": follow_up.get("next_step_text"),
        "deadline": deadline,
        "reason": str(follow_up.get("reason_not_fixed") or "").strip() or None,
        "score_percent": _extract_score_percent(artifact.analysis),
    }


def _build_weekly_dashboard_row(group: list[ReportArtifact]) -> dict[str, Any]:
    """Build one dashboard row for one manager."""
    manager_name = group[0].manager.name if group[0].manager is not None else _fallback_manager_name(group[0])
    scores = [_extract_score_percent(item.analysis) for item in group]
    avg_score = round(sum(scores) / len(scores), 1) if scores else None
    strong = sum(1 for item in group if _score_bucket(item.analysis) == "strong")
    problematic = sum(1 for item in group if _score_bucket(item.analysis) == "problematic")
    stop_flags = sum(1 for item in group if _has_stop_flag(item.analysis))
    status_signal = _weekly_status_signal(avg_score=avg_score, problematic_pct=_pct(problematic, len(group)))
    return {
        "manager_id": str(group[0].interaction.manager_id) if group[0].interaction.manager_id else None,
        "manager_name": manager_name,
        "department": str((group[0].interaction.metadata_ or {}).get("department_name") or "Отдел продаж"),
        "calls_count": len(group),
        "average_score": avg_score,
        "trend_label": "n/a",
        "strong_calls_pct": _pct(strong, len(group)),
        "problematic_calls_pct": _pct(problematic, len(group)),
        "stop_flags_pct": _pct(stop_flags, len(group)),
        "status_signal": status_signal,
    }


def _build_risk_zone_card(group: list[ReportArtifact]) -> dict[str, Any]:
    """Build one bounded risk card for a manager."""
    row = _build_weekly_dashboard_row(group)
    improve = _aggregate_finding_items(artifacts=group, key="gaps")
    return {
        "manager_name": row["manager_name"],
        "department": row["department"],
        "calls_count": row["calls_count"],
        "average_score": row["average_score"],
        "core_problem_statement": improve[0]["label"] if improve else "Нужна дополнительная проверка качества звонков",
        "action_for_rop": (
            f"Разобрать с менеджером тему '{improve[0]['label']}' и проверить фиксацию следующего шага."
            if improve
            else "Проверить выборку звонков и зафиксировать конкретную зону риска."
        ),
        "stage_profile_snapshot": improve[:3],
    }


def _build_systemic_problems(artifacts: list[ReportArtifact]) -> list[dict[str, Any]]:
    """Aggregate repeated weekly team problems."""
    grouped: dict[str, int] = {}
    for item in _aggregate_finding_items(artifacts=artifacts, key="gaps"):
        grouped[item["label"]] = int(item["signal"])
    result: list[dict[str, Any]] = []
    for label, count in sorted(grouped.items(), key=lambda pair: pair[1], reverse=True)[:5]:
        result.append(
            {
                "affected_managers_count": count,
                "problem_title": label,
                "explanation": "Проблема повторяется в нескольких звонках недели и требует системной реакции.",
                "recommended_systemic_action": f"Добавить целевую разборку по теме '{label}' на ближайшую неделю.",
                "timing_note": "На ближайшей неделе",
            }
        )
    return result


def _build_top_blocks(dashboard_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pick compact top and anti-top blocks."""
    if not dashboard_rows:
        empty = {
            "manager": None,
            "supporting_metrics": {},
            "interpretation": "Нет данных",
            "recommendation_to_rop": "Проверить, почему нет weekly выборки.",
        }
        return empty, empty
    sorted_rows = sorted(
        dashboard_rows,
        key=lambda item: item["average_score"] if item["average_score"] is not None else -1,
        reverse=True,
    )
    best = sorted_rows[0]
    worst = sorted_rows[-1]
    return (
        {
            "manager": best["manager_name"],
            "supporting_metrics": {
                "average_score": best["average_score"],
                "calls_count": best["calls_count"],
            },
            "interpretation": "Лучший результат недели по текущему качеству звонков.",
            "recommendation_to_rop": "Использовать как внутренний ориентир и источник удачных формулировок.",
        },
        {
            "manager": worst["manager_name"],
            "supporting_metrics": {
                "average_score": worst["average_score"],
                "calls_count": worst["calls_count"],
            },
            "interpretation": "Требует внимания по качеству звонков уже в ближайшую неделю.",
            "recommendation_to_rop": "Назначить короткий разбор и проверить, закреплён ли фокус на исправление.",
        },
    )


def _build_rop_tasks(
    *,
    risk_zone_cards: list[dict[str, Any]],
    systemic_team_problems: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a compact next-week ROP task list."""
    tasks: list[dict[str, Any]] = []
    for card in risk_zone_cards[:5]:
        tasks.append(
            {
                "manager": card["manager_name"],
                "priority": "Высокий",
                "task_for_next_week": card["action_for_rop"],
                "how_to_verify": "Проверить 2-3 следующих звонка после разбора.",
                "deadline": "На следующей неделе",
            }
        )
    if systemic_team_problems:
        tasks.append(
            {
                "manager": "Команда",
                "priority": "Средний",
                "task_for_next_week": systemic_team_problems[0]["recommended_systemic_action"],
                "how_to_verify": "Сравнить повторяемость проблемы в следующем weekly отчёте.",
                "deadline": "На следующей неделе",
            }
        )
    if not tasks:
        tasks.append(
            {
                "manager": "Команда",
                "priority": "Поддержка",
                "task_for_next_week": "Поддерживать текущий уровень и собрать ещё одну weekly выборку.",
                "how_to_verify": "Сравнить quality snapshot следующей недели.",
                "deadline": "Следующая неделя",
            }
        )
    return tasks


def _is_analysis_reusable_for_reporting(analysis: Analysis | None) -> tuple[bool, str]:
    """Return whether the persisted analysis is reusable for reporting."""
    if analysis is None:
        return False, "missing_analysis"
    if bool(getattr(analysis, "is_failed", False)):
        fail_reason = str(getattr(analysis, "fail_reason", "") or "").strip()
        if fail_reason:
            return False, fail_reason
        return False, "analysis_marked_failed"
    instruction_version = str(getattr(analysis, "instruction_version", "") or "").strip()
    if not instruction_version:
        return False, "missing_instruction_version"
    detail = getattr(analysis, "scores_detail", None)
    if not isinstance(detail, dict) or not detail:
        return False, "scores_detail_missing"
    missing_keys = [key for key in REPORTING_REQUIRED_ANALYSIS_KEYS if key not in detail]
    if missing_keys:
        return False, f"missing_required_keys:{','.join(missing_keys)}"
    checklist_score = dict(dict(detail.get("score") or {}).get("checklist_score") or {})
    if checklist_score.get("score_percent") is None:
        return False, "missing_checklist_score_percent"
    if not isinstance(detail.get("follow_up"), dict):
        return False, "invalid_follow_up_shape"
    if (
        not (detail.get("score_by_stage") or [])
        and not (detail.get("strengths") or [])
        and not (detail.get("gaps") or [])
        and not (detail.get("recommendations") or [])
    ):
        return False, SEMANTIC_EMPTY_ANALYSIS_REASON
    return True, "reusable"


def _build_focus_of_week(
    *,
    improve_items: list[dict[str, Any]],
    worked_items: list[dict[str, Any]],
) -> str | None:
    """Build a short focus line from the strongest repeated pattern."""
    if improve_items:
        return f"Сквозной фокус периода: {improve_items[0]['label']} повторяется чаще всего и должен стать темой ближайших разборов."
    if worked_items:
        return f"Сквозной опорный паттерн периода: {worked_items[0]['label']} стоит сохранять как образец для следующих звонков."
    return None


def _latest_call_score(artifacts: list[ReportArtifact]) -> float | None:
    """Return score of the latest call in the current group."""
    latest = max(
        artifacts,
        key=lambda item: item.call_started_at or datetime.min.replace(tzinfo=UTC),
        default=None,
    )
    if latest is None:
        return None
    return _extract_score_percent(latest.analysis)


def _build_voice_of_customer(*, artifacts: list[ReportArtifact]) -> dict[str, Any]:
    """Build up to 3 client situation snapshots from evidence_fragments and product_signals.

    Selection rule: prefer evidence_fragments with meaningful client_text (≥15 chars),
    prioritise missed_opportunity type first across all artifacts, then fill with
    product_signal quotes. Deduplicates by quote text.
    """
    situations: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _client_meta(artifact: ReportArtifact) -> tuple[str, str]:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        call_meta = dict(detail.get("call") or {})
        name = str(call_meta.get("contact_name") or call_meta.get("contact_phone")
                   or (artifact.interaction.metadata_ or {}).get("contact_phone") or "Клиент").strip()
        ts = artifact.call_started_at.strftime("%H:%M") if artifact.call_started_at else "—"
        return name, ts

    def _add_from_fragments(frag_type_priority: str | None) -> None:
        for artifact in artifacts:
            detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
            for frag in (detail.get("evidence_fragments") or []):
                if frag_type_priority and str(frag.get("fragment_type") or "") != frag_type_priority:
                    continue
                client_text = str(frag.get("client_text") or "").strip()
                if len(client_text) < 15 or client_text in seen:
                    continue
                seen.add(client_text)
                name, ts = _client_meta(artifact)
                why = str(frag.get("why") or "").strip()
                situations.append({
                    "client_label": name,
                    "time_label": ts,
                    "quote": client_text[:120] + ("…" if len(client_text) > 120 else ""),
                    "context": why[:100] + ("…" if len(why) > 100 else "") if why else None,
                })
                if len(situations) >= 3:
                    return

    _add_from_fragments("missed_opportunity")
    if len(situations) < 3:
        _add_from_fragments(None)

    if len(situations) < 3:
        for artifact in artifacts:
            detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
            name, ts = _client_meta(artifact)
            for sig in (detail.get("product_signals") or []):
                quote = str(sig.get("quote") or "").strip()
                if len(quote) < 10 or quote in seen:
                    continue
                seen.add(quote)
                topic = str(sig.get("topic") or "").strip()
                situations.append({
                    "client_label": name,
                    "time_label": ts,
                    "quote": quote[:120] + ("…" if len(quote) > 120 else ""),
                    "context": topic[:100] if topic else None,
                })
                if len(situations) >= 3:
                    break
            if len(situations) >= 3:
                break

    return {
        "is_placeholder": len(situations) == 0,
        "situations": situations[:3],
    }


def _build_additional_situations(
    *,
    improve_items: list[dict[str, Any]],
    worked_items: list[dict[str, Any]],
    top_gap_title: str | None,
) -> dict[str, Any]:
    """Build up to 3 additional coaching situations, excluding the top gap already shown in СИТУАЦИЯ ДНЯ.

    Priority: secondary gaps (improve_items[1:]) first, then strengths (worked_items) as reinforcement.
    Each situation has: kind ("gap" or "strength"), title, signal (count), interpretation.
    """
    situations: list[dict[str, Any]] = []
    seen_titles: set[str] = {str(top_gap_title or "").strip().lower()}

    for item in improve_items:
        if len(situations) >= 3:
            break
        label = str(item.get("label") or "").strip()
        if not label or label.strip().lower() in seen_titles:
            continue
        seen_titles.add(label.strip().lower())
        situations.append({
            "kind": "gap",
            "title": label,
            "signal": int(item.get("signal") or 0),
            "interpretation": str(item.get("interpretation") or "Выявлено в нескольких звонках."),
        })

    for item in worked_items:
        if len(situations) >= 3:
            break
        label = str(item.get("label") or "").strip()
        if not label or label.strip().lower() in seen_titles:
            continue
        seen_titles.add(label.strip().lower())
        situations.append({
            "kind": "strength",
            "title": label,
            "signal": int(item.get("signal") or 0),
            "interpretation": str(item.get("interpretation") or "Хорошо отработано в нескольких звонках."),
        })

    return {
        "is_placeholder": len(situations) == 0,
        "situations": situations[:3],
    }


def _call_tomorrow_opening_script(
    *,
    status: str,
    deadline: str | None,
    next_step: str,
    scenario_type: str,
) -> str:
    """Build a short manager-facing opening phrase for a follow-up call."""
    if status == "rescheduled":
        if deadline:
            return f"Добрый день! Звоню, как и договорились ({deadline})."
        return "Добрый день! Продолжаем наш разговор — готов ответить на вопросы."
    if status == "agreed":
        if next_step:
            step_short = next_step[:60].rstrip() + ("…" if len(next_step) > 60 else "")
            return f"Добрый день! Звоню уточнить детали: {step_short}"
        return "Добрый день! Готов двигаться дальше по нашей договорённости."
    if scenario_type in ("cold_outbound",):
        return "Добрый день! Хотел(а) подвести итог нашего разговора и уточнить ваш интерес."
    return "Добрый день! Звоню завершить нашу беседу — осталось уточнить пару деталей."


def _build_call_tomorrow(*, artifacts: list[ReportArtifact]) -> dict[str, Any]:
    """Build ПОЗВОНИ ЗАВТРА shortlist with opening scripts.

    Selection rule (deterministic):
    - Exclude refusal, support, internal calls
    - Priority groups: rescheduled → agreed → open
    - Within group: soonest deadline first, then call time
    - Deduplicate by client_label
    - Cap at 5 contacts total
    """
    _priority_order = ("rescheduled", "agreed", "open")
    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in _priority_order}

    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        call = dict(detail.get("call") or {})
        follow_up = dict(detail.get("follow_up") or {})
        classification = dict(detail.get("classification") or {})

        call_type = str(classification.get("call_type") or "").lower()
        if call_type in {"support", "internal"}:
            continue

        status, deadline = _derive_call_status_and_deadline(follow_up=follow_up)
        if status not in _priority_order:
            continue

        client_raw = (
            call.get("contact_name")
            or call.get("contact_phone")
            or (artifact.interaction.metadata_ or {}).get("contact_phone")
        )
        client_label = str(client_raw or "").strip()
        if not client_label:
            continue

        next_step = str(follow_up.get("next_step_text") or "").strip()
        scenario_type = str(classification.get("scenario_type") or "").lower()
        time_label = artifact.call_started_at.strftime("%H:%M") if artifact.call_started_at else "—"

        grouped[status].append({
            "client_label": client_label,
            "time_label": time_label,
            "status": status,
            "deadline": deadline,
            "next_step": next_step,
            "scenario_type": scenario_type,
            "_sort_key": str(deadline or "z"),
        })

    seen: set[str] = set()
    contacts: list[dict[str, Any]] = []
    for status in _priority_order:
        for item in sorted(grouped[status], key=lambda x: x["_sort_key"]):
            if item["client_label"] in seen:
                continue
            seen.add(item["client_label"])
            contacts.append({
                "client_label": item["client_label"],
                "time_label": item["time_label"],
                "status": item["status"],
                "deadline": item["deadline"],
                "opening_script": _call_tomorrow_opening_script(
                    status=item["status"],
                    deadline=item["deadline"],
                    next_step=item["next_step"],
                    scenario_type=item["scenario_type"],
                ),
            })
            if len(contacts) >= 5:
                break
        if len(contacts) >= 5:
            break

    return {
        "is_placeholder": len(contacts) == 0,
        "contacts": contacts,
    }


def _build_call_breakdown(
    *,
    improve_items: list[dict[str, Any]],
    artifacts: list[ReportArtifact],
) -> dict[str, Any]:
    """Build compact step-by-step breakdown of the most representative problem call.

    Selection rule: among calls containing the top gap label, pick the one with the
    lowest overall score (best illustrator of the problem).
    """
    _empty: dict[str, Any] = {
        "is_placeholder": True,
        "client_label": None,
        "time_label": None,
        "stage_steps": [],
        "worked": [],
        "to_fix": [],
        "recommendation": None,
    }
    if not improve_items or not artifacts:
        return _empty

    gap_label = improve_items[0]["label"]
    best_artifact: ReportArtifact | None = None
    best_score = float("inf")
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        has_gap = any(
            str(item.get("title") or item.get("criterion_name") or item.get("criterion_code") or "").strip() == gap_label
            for item in (detail.get("gaps") or [])
        )
        if has_gap:
            s = _extract_score_percent(artifact.analysis)
            if s < best_score:
                best_score = s
                best_artifact = artifact

    if best_artifact is None:
        return _empty

    detail = dict((best_artifact.analysis.scores_detail or {}) if best_artifact.analysis is not None else {})
    call_meta = dict(detail.get("call") or {})
    client_label = str(
        call_meta.get("contact_name") or call_meta.get("contact_phone")
        or (best_artifact.interaction.metadata_ or {}).get("contact_phone")
        or "Клиент"
    ).strip()
    time_label = best_artifact.call_started_at.strftime("%H:%M") if best_artifact.call_started_at else "—"

    # Build stage steps ordered by funnel
    raw_stages = detail.get("score_by_stage") or []
    stage_lookup = {str(s.get("stage_code") or ""): s for s in raw_stages}
    stage_steps: list[dict[str, Any]] = []
    for code, funnel_label, stage_name in _STAGE_FUNNEL_ORDER:
        if code not in stage_lookup:
            continue
        s = stage_lookup[code]
        s_score = int(s.get("stage_score") or 0)
        max_s = int(s.get("max_stage_score") or 0)
        if max_s > 0:
            normalized = round(s_score / max_s * 10, 1)
            stage_steps.append({
                "funnel_label": funnel_label,
                "stage_name": stage_name,
                "score": normalized,
                "is_weak": normalized < 4.0,
            })

    worked = [
        {
            "label": str(i.get("title") or i.get("criterion_name") or ""),
            "interpretation": str(i.get("impact") or i.get("comment") or i.get("evidence") or ""),
        }
        for i in (detail.get("strengths") or [])[:2]
        if str(i.get("title") or i.get("criterion_name") or "").strip()
    ]
    to_fix = [
        {
            "label": str(i.get("title") or i.get("criterion_name") or ""),
            "interpretation": str(i.get("impact") or i.get("comment") or i.get("evidence") or ""),
        }
        for i in (detail.get("gaps") or [])[:2]
        if str(i.get("title") or i.get("criterion_name") or "").strip()
    ]

    recs = detail.get("recommendations") or []
    recommendation = None
    if recs:
        r = recs[0]
        better_phrase = str(r.get("better_phrase") or r.get("recommendation") or r.get("problem") or "").strip()
        if better_phrase:
            recommendation = {
                "title": str(r.get("criterion_name") or r.get("criterion_code") or "Рекомендация"),
                "better_phrasing": better_phrase,
            }

    return {
        "is_placeholder": not stage_steps and not worked and not to_fix,
        "client_label": client_label,
        "time_label": time_label,
        "stage_steps": stage_steps,
        "worked": worked,
        "to_fix": to_fix,
        "recommendation": recommendation,
    }


def _build_problem_call_example(
    *,
    gap_label: str,
    artifacts: list[ReportArtifact],
) -> dict[str, Any] | None:
    """Pick one representative call that illustrates the top gap.

    Selection rule: among calls that contain the gap label, pick the one with the
    lowest overall score (most problematic illustrator). Falls back to any artifact
    with any gap if none match specifically.
    """
    candidates: list[tuple[float, ReportArtifact, str]] = []
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for gap_item in detail.get("gaps") or []:
            item_label = str(
                gap_item.get("title") or gap_item.get("criterion_name") or gap_item.get("criterion_code") or ""
            ).strip()
            if item_label == gap_label:
                reason = str(
                    gap_item.get("comment") or gap_item.get("evidence") or gap_item.get("impact") or ""
                ).strip()
                score = _extract_score_percent(artifact.analysis)
                candidates.append((score, artifact, reason))
                break
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    _score, best, reason_text = candidates[0]
    detail = dict((best.analysis.scores_detail or {}) if best.analysis is not None else {})
    call_meta = dict(detail.get("call") or {})
    client_label = str(
        call_meta.get("contact_name") or call_meta.get("contact_phone")
        or (best.interaction.metadata_ or {}).get("contact_phone")
        or "Клиент"
    ).strip()
    time_label = (
        best.call_started_at.strftime("%H:%M") if best.call_started_at else "—"
    )
    reason_short = reason_text[:80] + "…" if len(reason_text) > 80 else reason_text
    return {
        "client_label": client_label,
        "time_label": time_label,
        "reason_short": reason_short or None,
    }


def _build_manager_daily_key_problem(
    *,
    improve_items: list[dict[str, Any]],
    artifacts: list[ReportArtifact],
    calls_count: int,
) -> dict[str, Any]:
    """Build a richer key problem card from the most repeated gap."""
    if not improve_items:
        return {
            "title": MANAGER_DAILY_FALLBACK_KEY_PROBLEM_TITLE,
            "description": MANAGER_DAILY_FALLBACK_KEY_PROBLEM_DESCRIPTION,
            "pattern_count": None,
            "total_calls": calls_count,
            "call_example": None,
        }
    top_gap = improve_items[0]
    affected_calls = int(top_gap.get("signal") or 0)
    example = _first_gap_evidence(artifacts=artifacts, label=top_gap["label"])
    description = (
        f"{top_gap['interpretation']} Повторяемость: {affected_calls} звонк(ов)."
        f"{' Пример: ' + example if example else ''}"
    )
    call_example = _build_problem_call_example(gap_label=top_gap["label"], artifacts=artifacts)
    return {
        "title": top_gap["label"],
        "description": description,
        "pattern_count": affected_calls if affected_calls > 0 else None,
        "total_calls": calls_count,
        "call_example": call_example,
    }


def _build_signal_reason(
    *,
    product_signal: dict[str, Any] | None,
    worked_items: list[dict[str, Any]],
) -> str:
    """Explain why the selected signal matters."""
    if product_signal is not None:
        topic = str(product_signal.get("topic") or "ключевой теме клиента")
        importance = str(product_signal.get("importance") or "medium")
        return f"В этом эпизоде уже прозвучал важный сигнал по теме '{topic}' (importance={importance})."
    if worked_items:
        return f"Лучший звонок дня показывает рабочий паттерн по теме '{worked_items[0]['label']}'."
    return "Лучший звонок дня показывает, какие формулировки стоит повторять."


def _select_most_important_product_signal(artifacts: list[ReportArtifact]) -> dict[str, Any] | None:
    """Return the most important product signal found in the selected artifacts."""
    best: dict[str, Any] | None = None
    best_rank = -1
    rank = {"high": 3, "medium": 2, "low": 1}
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for item in detail.get("product_signals") or []:
            score = rank.get(str(item.get("importance") or "").lower(), 0)
            if score > best_rank:
                best_rank = score
                best = dict(item)
    return best


def _select_evidence_fragment(artifacts: list[ReportArtifact]) -> dict[str, Any] | None:
    """Return one evidence fragment to enrich signal text when available."""
    for artifact in sorted(
        artifacts,
        key=lambda item: _extract_score_percent(item.analysis),
        reverse=True,
    ):
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        fragments = detail.get("evidence_fragments") or []
        if fragments:
            return dict(fragments[0])
    return None


def _build_focus_criterion_dynamics(
    *,
    artifacts: list[ReportArtifact],
    improve_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build deterministic focus-criterion dynamics from current period calls."""
    focus_name = improve_items[0]["label"] if improve_items else None
    if not focus_name:
        return {
            "focus_criterion_name": None,
            "current_period_value": None,
            "previous_period_value": None,
            "delta": None,
            "is_placeholder": True,
        }
    chronological = sorted(
        artifacts,
        key=lambda item: item.call_started_at or datetime.min.replace(tzinfo=UTC),
    )
    midpoint = max(1, len(chronological) // 2)
    previous = _average_criterion_score(chronological[:midpoint], focus_name)
    current = _average_criterion_score(chronological[midpoint:], focus_name)
    if current is None:
        current = previous
    return {
        "focus_criterion_name": focus_name,
        "current_period_value": current,
        "previous_period_value": previous,
        "delta": round(current - previous, 1) if current is not None and previous is not None else None,
        "is_placeholder": current is None and previous is None,
    }


def _average_criterion_score(artifacts: list[ReportArtifact], criterion_name: str) -> float | None:
    """Average one criterion score across a slice of artifacts."""
    values: list[float] = []
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for stage in detail.get("score_by_stage") or []:
            for criterion in stage.get("criteria_results") or []:
                if str(criterion.get("criterion_name") or "").strip() == criterion_name:
                    values.append(float(criterion.get("score") or 0))
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _build_call_outcomes_summary(*, artifacts: list[ReportArtifact]) -> dict[str, Any]:
    """Build richer outcome counters from follow_up metadata and call classification."""
    agreed = 0
    rescheduled = 0
    refusal = 0
    open_count = 0
    tech_service = 0
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        call_type = str((detail.get("classification") or {}).get("call_type") or "").lower()
        if call_type in {"support", "internal"}:
            tech_service += 1
            continue
        follow_up = dict(detail.get("follow_up") or {})
        status, _deadline = _derive_call_status_and_deadline(follow_up=follow_up)
        if status == "agreed":
            agreed += 1
        elif status == "rescheduled":
            rescheduled += 1
        elif status == "refusal":
            refusal += 1
        else:
            open_count += 1
    return {
        "agreed_count": agreed,
        "rescheduled_count": rescheduled,
        "refusal_count": refusal,
        "open_count": open_count,
        "tech_service_count": tech_service,
        "source_note": "derived_from_follow_up_and_classification",
    }


def _derive_call_status_and_deadline(*, follow_up: dict[str, Any]) -> tuple[str, str | None]:
    """Classify call outcome from follow_up fields."""
    deadline = str(follow_up.get("due_date_text") or follow_up.get("due_date_iso") or "").strip() or None
    if follow_up.get("next_step_fixed"):
        return "agreed", deadline
    reason = str(follow_up.get("reason_not_fixed") or "").lower()
    if any(token in reason for token in ("позже", "перезвон", "перен", "созвон")):
        return "rescheduled", deadline
    if any(token in reason for token in ("не интересно", "отказ", "неакту", "нет надобности", "не нужно")):
        return "refusal", deadline
    return "open", deadline


def _has_stop_flag(analysis: Analysis | None) -> bool:
    """Return True when the call contains a strong stop signal for weekly aggregation."""
    detail = dict((analysis.scores_detail or {}) if analysis is not None else {})
    follow_up = dict(detail.get("follow_up") or {})
    status, _deadline = _derive_call_status_and_deadline(follow_up=follow_up)
    if status in {"refusal", "open"}:
        return True
    for item in detail.get("product_signals") or []:
        if str(item.get("signal_type") or "").lower() == "objection" and str(item.get("importance") or "").lower() == "high":
            return True
    return False


def _build_weekly_best_commentary(
    *,
    dashboard_rows: list[dict[str, Any]],
    top_block: dict[str, Any],
) -> str:
    """Build bounded positive commentary for weekly dynamics."""
    if not dashboard_rows:
        return "Недостаточно данных для weekly commentary."
    return (
        f"Опорный менеджер недели: {top_block.get('manager') or 'не определён'}. "
        "Его звонки можно использовать как источник удачных формулировок для разбора команды."
    )


def _build_weekly_alarm_commentary(
    *,
    anti_top_block: dict[str, Any],
    systemic_team_problems: list[dict[str, Any]],
) -> str:
    """Build bounded alarm commentary for weekly dynamics."""
    if systemic_team_problems:
        return (
            f"Главный системный риск недели: {systemic_team_problems[0]['problem_title']}. "
            f"Сначала стоит разобрать менеджера {anti_top_block.get('manager') or 'из зоны риска'}, затем дать общекомандное упражнение."
        )
    return (
        f"Главная зона внимания недели: {anti_top_block.get('manager') or 'не определена'}. "
        "Нужен короткий персональный разбор и повторная проверка следующих звонков."
    )


def _build_rop_weekly_executive_summary(
    *,
    department_name: str,
    dashboard_rows: list[dict[str, Any]],
    current_period_score: float | None,
) -> str:
    """Build short executive summary for weekly report."""
    score_label = "n/a" if current_period_score is None else str(current_period_score)
    return (
        f"По команде {department_name} в отчёт вошло {len(dashboard_rows)} менеджеров; "
        f"текущий средний уровень качества звонков — {score_label}."
    )


def _build_rop_weekly_team_risks(
    *,
    systemic_team_problems: list[dict[str, Any]],
    anti_top_block: dict[str, Any],
) -> str:
    """Build short wording for team risks."""
    if systemic_team_problems:
        return str(
            systemic_team_problems[0].get("explanation")
            or "Есть повторяющийся командный риск, который требует отдельного внимания РОПа."
        )
    return str(
        anti_top_block.get("interpretation")
        or "Критичных командных рисков на этой неделе не выделилось."
    )


def _build_rop_weekly_tasks_commentary(*, tasks: list[dict[str, Any]]) -> str:
    """Build one editorial wording block for ROP tasks."""
    if not tasks:
        return "На этой неделе нет новых обязательных задач сверх стандартного управленческого контроля."
    first = tasks[0]
    task_label = str(first.get("task_for_next_week") or "не определён")
    verify_label = str(first.get("how_to_verify") or "не определена")
    return (
        f"Главный управленческий фокус недели: {task_label}. "
        f"Проверка: {verify_label}."
    )


def _build_rop_weekly_final_commentary(
    *,
    top_block: dict[str, Any],
    anti_top_block: dict[str, Any],
) -> str:
    """Build final managerial commentary for weekly report."""
    top_manager = str(top_block.get("manager") or "команды")
    anti_top_manager = str(anti_top_block.get("manager") or "ключевого менеджера")
    return (
        f"Сохранить сильный паттерн у {top_manager} и отдельно "
        f"отработать зону риска у {anti_top_manager}."
    )


def _first_gap_evidence(*, artifacts: list[ReportArtifact], label: str) -> str | None:
    """Return one concrete gap evidence snippet for the selected label."""
    for artifact in artifacts:
        detail = dict((artifact.analysis.scores_detail or {}) if artifact.analysis is not None else {})
        for item in detail.get("gaps") or []:
            item_label = str(item.get("title") or item.get("criterion_name") or item.get("criterion_code") or "").strip()
            if item_label == label:
                return str(item.get("comment") or item.get("evidence") or item.get("impact") or "").strip() or None
    return None


def _render_manager_daily_text(payload: dict[str, Any]) -> str:
    """Render manager_daily plain-text email."""
    header = payload["header"]
    kpi = payload["kpi_overview"]
    recommendations = payload["recommendations"]
    call_rows = payload["call_list"]
    worked = payload["analysis_worked"]
    improve = payload["analysis_improve"]
    worked_lines = [f"- {item['label']}: {item['interpretation']}" for item in worked[:5]] or ["- Нет данных"]
    improve_lines = [f"- {item['label']}: {item['interpretation']}" for item in improve[:5]] or ["- Нет данных"]
    recommendation_lines = [
        f"- [{item['priority_tag']}] {item['title']}: {item['better_phrasing']}"
        for item in recommendations[:5]
    ]
    call_lines = [
        (
            f"- {row['time']}: {row['client_or_phone']} | {row['duration_sec']} сек | "
            f"статус {row['status']} | балл {row['score_percent']}"
        )
        for row in call_rows[:10]
    ]
    return "\n".join(
        [
            header["report_title"],
            f"Менеджер: {header['manager_name']}",
            f"Дата: {header['report_date']}",
            f"Отдел: {header['department_name']}",
            "",
            f"Звонков: {kpi['calls_count']}",
            f"Средний балл: {kpi['average_score']}",
            (
                "Доли звонков: "
                f"сильные {kpi['strong_calls_pct']}%, "
                f"базовые {kpi['baseline_calls_pct']}%, "
                f"проблемные {kpi['problematic_calls_pct']}%"
            ),
            "",
            f"Итог дня: {payload['narrative_day_conclusion']['text']}",
            f"Фокус на завтра: {payload['main_focus_for_tomorrow']['text']}",
            "",
            "Что получилось:",
            *worked_lines,
            "",
            "Над чем работать:",
            *improve_lines,
            "",
            "Рекомендации:",
            *recommendation_lines,
            "",
            "Короткий список звонков:",
            *call_lines,
        ]
    )


def _render_rop_weekly_text(payload: dict[str, Any]) -> str:
    """Render rop_weekly plain-text email."""
    header = payload["header"]
    dashboard_rows = payload["dashboard_rows"]
    risk_cards = payload["risk_zone_cards"]
    systemic = payload["systemic_team_problems"]
    tasks = payload["rop_tasks_next_week"]
    dashboard_lines = [
        (
            f"- {row['manager_name']}: {row['calls_count']} звонков | "
            f"средний балл {row['average_score']} | статус {row['status_signal']}"
        )
        for row in dashboard_rows
    ]
    risk_lines = [
        f"- {item['manager_name']}: {item['core_problem_statement']} -> {item['action_for_rop']}"
        for item in risk_cards
    ] or ["- Нет менеджеров в явной зоне риска"]
    systemic_lines = [
        f"- {item['problem_title']}: {item['recommended_systemic_action']}"
        for item in systemic
    ] or ["- Не выявлены"]
    task_lines = [
        f"- [{item['priority']}] {item['manager']}: {item['task_for_next_week']}"
        for item in tasks
    ]
    return "\n".join(
        [
            header["report_title"],
            header["subtitle"],
            f"Период: {header['week_label']}",
            f"Отдел: {header['department_name']}",
            "",
            "Dashboard недели:",
            *dashboard_lines,
            "",
            "Зона внимания:",
            *risk_lines,
            "",
            "Системные проблемы:",
            *systemic_lines,
            "",
            "Задачи РОПа на неделю:",
            *task_lines,
            "",
            "CRM-блок: пока placeholder до подключения данных результата продаж.",
        ]
    )

def _fallback_manager_name(artifact: ReportArtifact) -> str:
    """Return a readable manager fallback for unmapped rows."""
    metadata = dict(artifact.interaction.metadata_ or {})
    return str(metadata.get("manager_name") or metadata.get("extension") or "Не сопоставлен")


def _pct(numerator: int, denominator: int) -> float:
    """Return percentage rounded to one decimal place."""
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _format_period_label(period: dict[str, str]) -> str:
    """Return a compact report-period label."""
    if period.get("date_from") == period.get("date_to"):
        return str(period["date_from"])
    return f"{period['date_from']}..{period['date_to']}"


def _performance_label(score: float | None) -> str:
    """Return a compact performance label for daily report."""
    if score is None:
        return "неполный"
    if score >= 80:
        return "сильный"
    if score >= 60:
        return "базовый"
    return "зона внимания"


def _best_call_time(artifacts: list[ReportArtifact]) -> str | None:
    """Return one best-call time candidate."""
    best = sorted(
        artifacts,
        key=lambda item: _extract_score_percent(item.analysis),
        reverse=True,
    )[0]
    return best.call_started_at.isoformat() if best.call_started_at else None


def _best_contact(artifacts: list[ReportArtifact]) -> str | None:
    """Return one contact marker for the best daily signal."""
    best = sorted(
        artifacts,
        key=lambda item: _extract_score_percent(item.analysis),
        reverse=True,
    )[0]
    detail = dict((best.analysis.scores_detail or {}) if best.analysis is not None else {})
    call = dict(detail.get("call") or {})
    return call.get("contact_name") or call.get("contact_phone") or (best.interaction.metadata_ or {}).get("contact_phone")


def _best_signal_text(
    artifacts: list[ReportArtifact],
    *,
    evidence_fragment: dict[str, Any] | None = None,
) -> str:
    """Return one short best-call explanation."""
    if evidence_fragment is not None:
        fragment = str(
            evidence_fragment.get("manager_text")
            or evidence_fragment.get("client_text")
            or evidence_fragment.get("summary")
            or ""
        ).strip()
        if fragment:
            return fragment
    best = sorted(
        artifacts,
        key=lambda item: _extract_score_percent(item.analysis),
        reverse=True,
    )[0]
    detail = dict((best.analysis.scores_detail or {}) if best.analysis is not None else {})
    strengths = detail.get("strengths") or []
    if strengths:
        return str(strengths[0].get("comment") or strengths[0].get("evidence") or "Сильный разговор дня.")
    return "Сильный разговор дня по совокупному баллу."


def _weekly_status_signal(*, avg_score: float | None, problematic_pct: float) -> str:
    """Map one manager weekly summary to the bounded status vocabulary."""
    if avg_score is None:
        return "Наблюдение"
    if avg_score >= 85 and problematic_pct < 10:
        return "Эталон"
    if avg_score >= 75:
        return "Растёт"
    if avg_score >= 60:
        return "Стабильно"
    if avg_score >= 45:
        return "Наблюдение"
    return "Зона риска"


def format_report_preview_timestamp() -> str:
    """Return RFC 2822-like timestamp for delivery previews if needed later."""
    return format_datetime(datetime.now(UTC))
