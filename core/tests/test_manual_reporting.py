"""Mirrored unit tests for the bounded Manual Reporting Pilot slice."""

from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import sqlalchemy as sa

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test_db")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "user")
os.environ.setdefault("POSTGRES_PASSWORD", "pass")
os.environ.setdefault("REDIS_URL", "redis://:pass@localhost:6379/0")
os.environ.setdefault("REDIS_PASSWORD", "pass")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("ASSEMBLYAI_API_KEY", "test-key")
os.environ.setdefault("ONLINEPBX_DOMAIN", "example.onpbx.ru")
os.environ.setdefault("ONLINEPBX_API_KEY", "test-key")


CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.agents.calls.reporting import (  # noqa: E402
    CallsManualReportingOrchestrator,
    MEANINGFUL_ABSOLUTE_MIN_DURATION_SEC,
    ReportArtifact,
    ReportRunFilters,
    _build_meaningful_call_list,
    _build_selection_model_counters,
    _classify_meaningful_call,
    build_manager_daily_payload,
    build_rop_weekly_payload,
    render_report_email,
    resolve_report_preset,
)
from app.agents.calls.report_templates import build_report_render_model  # noqa: E402
from app.agents.calls.verification_report_runner import (  # noqa: E402
    build_canonical_verification_bundle,
)
from app.agents.calls.intake import OnlinePBXIntake  # noqa: E402
from app.agents.calls.delivery import CallsDelivery  # noqa: E402
from app.agents.calls.scheduled_reporting import (  # noqa: E402
    SCHEDULED_REVIEWABLE_BATCH_STATUSES,
    SCHEDULED_REVIEWABLE_BATCH_ALLOWED_TRANSITIONS,
    SCHEDULED_REVIEWABLE_ALLOWED_PERIOD_RULES,
    ScheduledReviewableReportingService,
    _compute_report_period,
    _next_local_occurrence,
    apply_editable_blocks,
    extract_editable_blocks,
)
from app.core_shared.api.main import app  # noqa: E402
from app.core_shared.exceptions import ASAError, DeliveryError  # noqa: E402

try:
    from fastapi.testclient import TestClient  # noqa: E402
except ImportError:  # pragma: no cover
    TestClient = None


def _analysis(
    score_percent: float,
    level: str,
    *,
    next_step_fixed: bool = True,
    strengths: list[dict[str, str]] | None = None,
    gaps: list[dict[str, str]] | None = None,
    recommendations: list[dict[str, str]] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        interaction_id=uuid4(),
        instruction_version="analysis_v1",
        score_total=score_percent,
        scores_detail={
            "call": {
                "contact_phone": "+77070000000",
            },
            "score": {
                "checklist_score": {
                    "score_percent": score_percent,
                    "level": level,
                }
            },
            "score_by_stage": [
                {
                    "stage_code": "completion_next_step",
                    "stage_name": "Завершение и следующий шаг",
                    "criteria_results": [
                        {
                            "criterion_code": "next_step_fixed",
                            "criterion_name": "Фиксация следующего шага",
                            "score": 1 if next_step_fixed else 0,
                            "max_score": 1,
                        }
                    ],
                }
            ],
            "strengths": strengths
            if strengths is not None
            else [
                {
                    "title": "Сильный контакт",
                    "comment": "Хорошо держит структуру звонка.",
                }
            ],
            "gaps": gaps
            if gaps is not None
            else [
                {
                    "title": "Фиксация следующего шага",
                    "comment": "Не всегда закрепляет итог разговора.",
                }
            ],
            "recommendations": recommendations
            if recommendations is not None
            else [
                {
                    "criterion_name": "Фиксация следующего шага",
                    "recommendation": "В конце звонка проговаривать следующий шаг и дедлайн.",
                    "problem": "Следующий шаг звучит неуверенно.",
                }
            ],
            "follow_up": {
                "next_step_fixed": next_step_fixed,
                "next_step_text": "Созвон завтра в 11:00",
            },
            "product_signals": [],
            "evidence_fragments": [],
        },
    )


def _interaction(*, manager_id=None, text: str = "Текст звонка", call_date: str = "2026-03-25 10:00:00") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        department_id=uuid4(),
        manager_id=manager_id,
        text=text,
        duration_sec=420,
        metadata_={
            "call_date": call_date,
            "manager_name": "Эльмира Кешубаева",
            "contact_phone": "+77070000000",
            "department_name": "Отдел продаж",
        },
    )


def _manager() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        name="Эльмира Кешубаева",
        email="elmira@example.com",
    )


def _artifact(
    score_percent: float = 82.0,
    level: str = "strong",
    *,
    call_date: str = "2026-03-25 10:00:00",
    strengths: list[dict[str, str]] | None = None,
    gaps: list[dict[str, str]] | None = None,
    recommendations: list[dict[str, str]] | None = None,
) -> ReportArtifact:
    manager = _manager()
    interaction = _interaction(manager_id=manager.id, call_date=call_date)
    return ReportArtifact(
        interaction=interaction,
        analysis=_analysis(
            score_percent,
            level,
            strengths=strengths,
            gaps=gaps,
            recommendations=recommendations,
        ),
        manager=manager,
        call_started_at=datetime.fromisoformat(call_date.replace(" ", "T")).replace(tzinfo=UTC),
    )


def _artifact_for_manager(
    manager: SimpleNamespace,
    *,
    score_percent: float = 82.0,
    level: str = "strong",
    call_date: str = "2026-03-25 10:00:00",
    strengths: list[dict[str, str]] | None = None,
    gaps: list[dict[str, str]] | None = None,
    recommendations: list[dict[str, str]] | None = None,
) -> ReportArtifact:
    interaction = _interaction(manager_id=manager.id, call_date=call_date)
    return ReportArtifact(
        interaction=interaction,
        analysis=_analysis(
            score_percent,
            level,
            strengths=strengths,
            gaps=gaps,
            recommendations=recommendations,
        ),
        manager=manager,
        call_started_at=datetime.fromisoformat(call_date.replace(" ", "T")).replace(tzinfo=UTC),
    )


class ManualReportingPayloadTests(unittest.TestCase):
    def test_resolve_report_preset_supports_bounded_presets(self) -> None:
        self.assertEqual(resolve_report_preset("manager_daily").code, "manager_daily")
        self.assertEqual(resolve_report_preset("rop_weekly").code, "rop_weekly")

    def test_build_manager_daily_payload_contains_required_sections(self) -> None:
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[_artifact(86.0, "strong"), _artifact(61.0, "basic")],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        self.assertEqual(payload["meta"]["preset"], "manager_daily")
        self.assertEqual(payload["header"]["manager_name"], "Эльмира Кешубаева")
        self.assertEqual(payload["kpi_overview"]["calls_count"], 2)
        self.assertIn("recommendations", payload)
        self.assertIn("call_list", payload)
        self.assertIn("delivery_meta", payload)
        self.assertEqual(payload["meta"]["reuse_policy_version"], "manual_reporting_reuse_v3")
        self.assertIn("effective_versions", payload["meta"])
        self.assertIn("reuse", payload["meta"])

    def test_build_manager_daily_payload_enriches_outcomes_focus_and_dynamics(self) -> None:
        manager = _manager()
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[
                _artifact_for_manager(
                    manager,
                    score_percent=88.0,
                    level="strong",
                    call_date="2026-03-24 10:00:00",
                    gaps=[
                        {
                            "title": "Фиксация следующего шага",
                            "comment": "На ранних звонках следующий шаг формулируется размыто.",
                        }
                    ],
                ),
                _artifact_for_manager(
                    manager,
                    score_percent=72.0,
                    level="basic",
                    call_date="2026-03-25 10:00:00",
                    gaps=[
                        {
                            "title": "Фиксация следующего шага",
                            "comment": "Паттерн повторяется и мешает закрывать разговор договоренностью.",
                        }
                    ],
                ),
            ],
            period={"date_from": "2026-03-24", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        self.assertFalse(payload["focus_of_week"]["is_placeholder"])
        self.assertEqual(payload["call_outcomes_summary"]["agreed_count"], 2)
        self.assertEqual(payload["focus_criterion_dynamics"]["focus_criterion_name"], "Фиксация следующего шага")
        self.assertIsNotNone(payload["focus_criterion_dynamics"]["current_period_value"])
        self.assertIn("Повторяемость", payload["key_problem_of_day"]["description"])

    def test_build_manager_daily_payload_contains_selection_model_contract(self) -> None:
        """SM-1: selection_model section is present with all required counter fields."""
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[_artifact(86.0, "strong"), _artifact(61.0, "basic")],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        sm = payload["selection_model"]
        required_counters = [
            "raw_calls_total",
            "meaningful_calls_total",
            "service_calls_total",
            "coaching_candidate_calls_total",
            "analyzed_calls_total",
            "included_in_report_total",
            "exclusion_reasons",
        ]
        for field in required_counters:
            self.assertIn(field, sm, f"selection_model missing field: {field}")

        reasons = sm["exclusion_reasons"]
        required_reasons = [
            "too_short_or_no_speech",
            "ivr_or_autoanswer",
            "support_internal",
            "not_enough_analysis",
            "not_selected_for_core_review",
        ]
        for code in required_reasons:
            self.assertIn(code, reasons, f"exclusion_reasons missing code: {code}")

    def test_build_manager_daily_payload_selection_model_counts_correctly(self) -> None:
        """SM-1: selection_model counters are consistent with provided artifacts."""
        usable = [_artifact(86.0, "strong"), _artifact(61.0, "basic")]
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=usable,
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        sm = payload["selection_model"]
        self.assertEqual(sm["raw_calls_total"], 2)
        self.assertEqual(sm["meaningful_calls_total"], 2)
        self.assertEqual(sm["service_calls_total"], 0)
        self.assertEqual(sm["coaching_candidate_calls_total"], 2)
        self.assertEqual(sm["analyzed_calls_total"], 2)
        self.assertEqual(sm["included_in_report_total"], 2)
        self.assertEqual(sm["exclusion_reasons"]["support_internal"], 0)
        self.assertEqual(sm["exclusion_reasons"]["not_enough_analysis"], 0)

    def test_build_manager_daily_payload_selection_model_separates_service_calls(self) -> None:
        """SM-1: service_calls_total counts support/internal calls; coaching_candidate excludes them."""
        def _support_artifact() -> ReportArtifact:
            manager = _manager()
            interaction = _interaction(manager_id=manager.id)
            analysis = _analysis(50.0, "basic")
            detail = dict(analysis.scores_detail)
            detail["classification"] = {"call_type": "support", "scenario_type": "technical"}
            analysis = SimpleNamespace(
                id=uuid4(),
                interaction_id=interaction.id,
                instruction_version="analysis_v1",
                score_total=50.0,
                scores_detail=detail,
                is_failed=False,
                fail_reason=None,
            )
            return ReportArtifact(
                interaction=interaction,
                analysis=analysis,
                manager=manager,
                call_started_at=datetime.fromisoformat("2026-03-25T10:00:00").replace(tzinfo=UTC),
            )

        sales_artifact = _artifact(82.0, "strong")
        support_artifact = _support_artifact()
        all_window = [sales_artifact, support_artifact]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[sales_artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=all_window,
        )

        sm = payload["selection_model"]
        self.assertEqual(sm["raw_calls_total"], 2)
        self.assertEqual(sm["service_calls_total"], 1)
        self.assertEqual(sm["coaching_candidate_calls_total"], 1)
        self.assertEqual(sm["analyzed_calls_total"], 1)
        self.assertEqual(sm["included_in_report_total"], 1)
        self.assertEqual(sm["exclusion_reasons"]["support_internal"], 1)

    def test_build_manager_daily_payload_selection_model_counts_missing_analyses(self) -> None:
        """SM-1: not_enough_analysis counts artifacts without analysis."""
        usable_artifact = _artifact(82.0, "strong")
        no_analysis_artifact = ReportArtifact(
            interaction=_interaction(),
            analysis=None,
            manager=_manager(),
            call_started_at=datetime.fromisoformat("2026-03-25T11:00:00").replace(tzinfo=UTC),
        )
        all_window = [usable_artifact, no_analysis_artifact]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[usable_artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=all_window,
        )

        sm = payload["selection_model"]
        self.assertEqual(sm["raw_calls_total"], 2)
        self.assertEqual(sm["analyzed_calls_total"], 1)
        self.assertEqual(sm["exclusion_reasons"]["not_enough_analysis"], 1)

    # --- SM-2 acceptance tests ---

    def test_classify_meaningful_call_short_no_speech_excluded(self) -> None:
        """SM-2 R1/R2: call below floor with no transcript → too_short_or_no_speech."""
        interaction = SimpleNamespace(
            id=uuid4(),
            duration_sec=10,
            text="",
        )
        artifact = ReportArtifact(
            interaction=interaction,
            analysis=None,
            manager=_manager(),
            call_started_at=None,
        )
        is_meaningful, reason = _classify_meaningful_call(artifact)
        self.assertFalse(is_meaningful)
        self.assertEqual(reason, "too_short_or_no_speech")

    def test_classify_meaningful_call_zero_duration_no_speech_excluded(self) -> None:
        """SM-2 R1: zero duration and no transcript → too_short_or_no_speech."""
        interaction = SimpleNamespace(id=uuid4(), duration_sec=0, text="")
        artifact = ReportArtifact(
            interaction=interaction,
            analysis=None,
            manager=_manager(),
            call_started_at=None,
        )
        is_meaningful, reason = _classify_meaningful_call(artifact)
        self.assertFalse(is_meaningful)
        self.assertEqual(reason, "too_short_or_no_speech")

    def test_classify_meaningful_call_ivr_excluded(self) -> None:
        """SM-2 R4: call_type=other + analysis_eligibility=not_eligible + no transcript → ivr_or_autoanswer."""
        interaction = SimpleNamespace(
            id=uuid4(),
            duration_sec=30,
            text="",
        )
        analysis = SimpleNamespace(
            id=uuid4(),
            scores_detail={
                "classification": {
                    "call_type": "other",
                    "analysis_eligibility": "not_eligible",
                }
            },
            is_failed=False,
        )
        artifact = ReportArtifact(
            interaction=interaction,
            analysis=analysis,
            manager=_manager(),
            call_started_at=None,
        )
        is_meaningful, reason = _classify_meaningful_call(artifact)
        self.assertFalse(is_meaningful)
        self.assertEqual(reason, "ivr_or_autoanswer")

    def test_classify_meaningful_call_with_transcript_is_meaningful(self) -> None:
        """SM-2 R3: any call with transcript is meaningful regardless of duration or call_type."""
        interaction = SimpleNamespace(
            id=uuid4(),
            duration_sec=10,
            text="Алло, здравствуйте",
        )
        artifact = ReportArtifact(
            interaction=interaction,
            analysis=None,
            manager=_manager(),
            call_started_at=None,
        )
        is_meaningful, reason = _classify_meaningful_call(artifact)
        self.assertTrue(is_meaningful)
        self.assertIsNone(reason)

    def test_classify_meaningful_call_support_with_transcript_is_meaningful(self) -> None:
        """SM-2: support call with transcript → meaningful (service call, counted separately)."""
        interaction = SimpleNamespace(
            id=uuid4(),
            duration_sec=300,
            text="Добрый день, у меня вопрос по договору",
        )
        analysis = SimpleNamespace(
            id=uuid4(),
            scores_detail={
                "classification": {
                    "call_type": "support",
                    "analysis_eligibility": "not_eligible",
                }
            },
            is_failed=False,
        )
        artifact = ReportArtifact(
            interaction=interaction,
            analysis=analysis,
            manager=_manager(),
            call_started_at=None,
        )
        is_meaningful, reason = _classify_meaningful_call(artifact)
        self.assertTrue(is_meaningful)
        self.assertIsNone(reason)

    def test_build_selection_model_counters_sm2_too_short_counted(self) -> None:
        """SM-2: too_short_or_no_speech exclusion reason is populated from real classification."""
        short_no_speech = ReportArtifact(
            interaction=SimpleNamespace(id=uuid4(), duration_sec=5, text=""),
            analysis=None,
            manager=_manager(),
            call_started_at=None,
        )
        normal = _artifact(82.0, "strong")
        counters = _build_selection_model_counters(
            window_artifacts=[short_no_speech, normal],
            usable_artifacts=[normal],
        )
        self.assertEqual(counters["raw_calls_total"], 2)
        self.assertEqual(counters["meaningful_calls_total"], 1)
        self.assertEqual(counters["exclusion_reasons"]["too_short_or_no_speech"], 1)
        self.assertEqual(counters["exclusion_reasons"]["ivr_or_autoanswer"], 0)

    def test_build_selection_model_counters_sm2_ivr_counted(self) -> None:
        """SM-2: ivr_or_autoanswer exclusion reason is populated from real classification."""
        ivr_analysis = SimpleNamespace(
            id=uuid4(),
            scores_detail={
                "classification": {"call_type": "other", "analysis_eligibility": "not_eligible"}
            },
            is_failed=False,
        )
        ivr_artifact = ReportArtifact(
            interaction=SimpleNamespace(id=uuid4(), duration_sec=30, text=""),
            analysis=ivr_analysis,
            manager=_manager(),
            call_started_at=None,
        )
        normal = _artifact(82.0, "strong")
        counters = _build_selection_model_counters(
            window_artifacts=[ivr_artifact, normal],
            usable_artifacts=[normal],
        )
        self.assertEqual(counters["raw_calls_total"], 2)
        self.assertEqual(counters["meaningful_calls_total"], 1)
        self.assertEqual(counters["exclusion_reasons"]["ivr_or_autoanswer"], 1)
        self.assertEqual(counters["exclusion_reasons"]["too_short_or_no_speech"], 0)

    def test_build_selection_model_counters_sm2_no_sm1_notes(self) -> None:
        """SM-2: _sm1_notes proxy key is no longer present in the counters dict."""
        counters = _build_selection_model_counters(
            window_artifacts=[_artifact(82.0, "strong")],
            usable_artifacts=[_artifact(82.0, "strong")],
        )
        self.assertNotIn("_sm1_notes", counters)

    # --- SM-3 acceptance tests ---

    def test_sm3_call_list_includes_meaningful_non_coaching_calls(self) -> None:
        """SM-3: call_list includes meaningful calls beyond coaching_core (wider than usable)."""
        coaching_artifact = _artifact(82.0, "strong")
        # A support call with transcript — meaningful but not usable/coaching_core
        support_interaction = _interaction(manager_id=coaching_artifact.interaction.manager_id, text="Добрый день, помогите с договором")
        support_analysis = SimpleNamespace(
            id=uuid4(),
            score_total=None,
            scores_detail={
                "classification": {"call_type": "support", "analysis_eligibility": "not_eligible"},
                "call": {"contact_name": "Клиент Сервис"},
                "follow_up": {},
            },
            is_failed=False,
        )
        support_artifact = ReportArtifact(
            interaction=support_interaction,
            analysis=support_analysis,
            manager=coaching_artifact.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T09:00:00").replace(tzinfo=UTC),
        )
        all_window = [coaching_artifact, support_artifact]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[coaching_artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=all_window,
        )

        call_list = payload["call_list"]
        self.assertEqual(len(call_list), 2, "call_list should include both coaching and support meaningful calls")

    def test_sm3_call_list_excludes_beep_and_ivr(self) -> None:
        """SM-3: call_list does not include IVR/beep/no-speech calls."""
        coaching_artifact = _artifact(82.0, "strong")
        ivr_analysis = SimpleNamespace(
            id=uuid4(),
            score_total=None,
            scores_detail={
                "classification": {"call_type": "other", "analysis_eligibility": "not_eligible"},
                "call": {},
                "follow_up": {},
            },
            is_failed=False,
        )
        ivr_artifact = ReportArtifact(
            interaction=SimpleNamespace(id=uuid4(), duration_sec=20, text=""),
            analysis=ivr_analysis,
            manager=coaching_artifact.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T08:00:00").replace(tzinfo=UTC),
        )
        beep_artifact = ReportArtifact(
            interaction=SimpleNamespace(id=uuid4(), duration_sec=5, text=""),
            analysis=None,
            manager=coaching_artifact.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T07:00:00").replace(tzinfo=UTC),
        )
        all_window = [coaching_artifact, ivr_artifact, beep_artifact]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[coaching_artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=all_window,
        )

        call_list = payload["call_list"]
        self.assertEqual(len(call_list), 1, "call_list should exclude IVR and beep calls")

    def test_sm3_coaching_blocks_unchanged_when_call_list_widens(self) -> None:
        """SM-3: coaching-relevant aggregate fields (analysis_worked, analysis_improve) use coaching_core only."""
        coaching_artifact = _artifact(82.0, "strong")
        support_interaction = _interaction(manager_id=coaching_artifact.interaction.manager_id, text="Тех. вопрос")
        support_artifact = ReportArtifact(
            interaction=support_interaction,
            analysis=SimpleNamespace(
                id=uuid4(),
                score_total=None,
                scores_detail={
                    "classification": {"call_type": "support", "analysis_eligibility": "not_eligible"},
                    "call": {},
                    "follow_up": {},
                },
                is_failed=False,
            ),
            manager=coaching_artifact.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T09:30:00").replace(tzinfo=UTC),
        )
        all_window = [coaching_artifact, support_artifact]

        payload_with_support = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[coaching_artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=all_window,
        )
        payload_coaching_only = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[coaching_artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        # call_list is wider with support
        self.assertGreater(len(payload_with_support["call_list"]), len(payload_coaching_only["call_list"]))
        # coaching aggregate blocks are identical
        self.assertEqual(payload_with_support["kpi_overview"]["calls_count"], payload_coaching_only["kpi_overview"]["calls_count"])
        self.assertEqual(payload_with_support["analysis_worked"], payload_coaching_only["analysis_worked"])
        self.assertEqual(payload_with_support["analysis_improve"], payload_coaching_only["analysis_improve"])

    def test_sm3_call_list_sorted_by_time(self) -> None:
        """SM-3: call_list rows are sorted by call time ascending."""
        a1 = _artifact(82.0, "strong", call_date="2026-03-25 11:00:00")
        a2 = _artifact(70.0, "basic", call_date="2026-03-25 09:00:00")
        a3 = _artifact(65.0, "basic", call_date="2026-03-25 15:00:00")

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[a1, a2, a3],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        times = [row["time"] for row in payload["call_list"] if row["time"]]
        self.assertEqual(times, sorted(times), "call_list rows must be sorted by time ascending")

    def test_sm3_build_meaningful_call_list_direct(self) -> None:
        """SM-3: _build_meaningful_call_list excludes non-meaningful, includes support with transcript."""
        normal = _artifact(82.0, "strong")
        support_interaction = _interaction(text="Вопрос по документам")
        support_artifact = ReportArtifact(
            interaction=support_interaction,
            analysis=SimpleNamespace(
                id=uuid4(),
                score_total=None,
                scores_detail={"classification": {"call_type": "support", "analysis_eligibility": "not_eligible"}, "call": {}, "follow_up": {}},
                is_failed=False,
            ),
            manager=normal.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T08:00:00").replace(tzinfo=UTC),
        )
        beep = ReportArtifact(
            interaction=SimpleNamespace(id=uuid4(), duration_sec=3, text=""),
            analysis=None,
            manager=normal.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T07:00:00").replace(tzinfo=UTC),
        )
        result = _build_meaningful_call_list(window_artifacts=[normal, support_artifact, beep])
        self.assertEqual(len(result), 2)
        self.assertNotIn("too_short_or_no_speech", [r.get("call_type") for r in result])

    def test_build_rop_weekly_payload_keeps_crm_placeholder(self) -> None:
        payload = build_rop_weekly_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[_artifact(88.0, "strong"), _artifact(52.0, "problematic")],
            period={"date_from": "2026-03-20", "date_to": "2026-03-26"},
            filters=ReportRunFilters(date_from="2026-03-20", date_to="2026-03-26"),
            mode="report_from_ready_data_only",
            model_override="gpt-4.1-mini",
        )

        self.assertEqual(payload["meta"]["preset"], "rop_weekly")
        self.assertEqual(payload["business_results_placeholder"]["status"], "placeholder")
        self.assertIn("dashboard_rows", payload)
        self.assertIn("rop_tasks_next_week", payload)
        self.assertIn(payload["week_over_week_dynamics"]["trend"], {"n/a", "up", "down", "flat"})

    def test_render_report_email_uses_delivery_meta_subject(self) -> None:
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[_artifact()],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        rendered = render_report_email(payload)

        self.assertIn("Ежедневный разбор звонков", rendered["subject"])
        self.assertIn("СИТУАЦИЯ ДНЯ", rendered["text"])
        self.assertIn("<html>", rendered["html"])
        self.assertIn("ДЕНЬГИ НА СТОЛЕ", rendered["html"])
        self.assertIn("PIPELINE ТЁПЛЫХ ЛИДОВ", rendered["html"])
        self.assertIn("ЧЕЛЛЕНДЖ НА ЗАВТРА", rendered["html"])
        self.assertIn("СВОДНАЯ ТАБЛИЦА ЗВОНКОВ", rendered["html"])
        self.assertIn("УТРЕННЯЯ КАРТОЧКА", rendered["html"])
        self.assertNotIn("КЛЮЧЕВАЯ ПРОБЛЕМА ДНЯ", rendered["html"])
        self.assertNotIn("РЕКОМЕНДАЦИИ", rendered["html"])
        self.assertNotIn("ПАМЯТКА", rendered["html"])
        self.assertNotIn("not available", rendered["html"])
        self.assertNotIn("not available", rendered["text"])
        self.assertNotIn("Note:", rendered["html"])
        self.assertNotIn("Note:", rendered["text"])
        self.assertNotIn("Generated at", rendered["html"])
        self.assertNotIn("manager_daily_template_v1", rendered["html"])
        self.assertEqual(rendered["artifact"]["media_type"], "application/pdf")
        self.assertGreater(rendered["artifact"]["size_bytes"], 0)
        self.assertGreaterEqual(rendered["artifact"]["page_count"], 6)
        self.assertEqual(rendered["template"]["version"], "manager_daily_template_v2")
        self.assertEqual(payload["meta"]["template_version"], "manager_daily_template_v2")
        self.assertEqual(rendered["artifact"]["render_variant"], "template_pdf_manager_daily_template_v2")
        self.assertEqual(rendered["artifact"]["generator_path"], "app.agents.calls.report_templates.render_report_artifact")
        ordered_labels = [
            "ШАПКА",
            "СВОДНАЯ ТАБЛИЦА ЗВОНКОВ",
            "ДЕНЬГИ НА СТОЛЕ",
            "PIPELINE ТЁПЛЫХ ЛИДОВ",
            "БАЛЛЫ ПО ЭТАПАМ",
            "СИТУАЦИЯ ДНЯ",
            "РАЗБОР ЗВОНКА",
            "ГОЛОС КЛИЕНТА",
            "ДОПОЛНИТЕЛЬНЫЕ 3 СИТУАЦИИ",
            "ЧЕЛЛЕНДЖ НА ЗАВТРА",
            "ПОЗВОНИ ЗАВТРА",
            "СПИСОК ВСЕХ ЗВОНКОВ ДНЯ",
            "УТРЕННЯЯ КАРТОЧКА",
        ]
        positions = [rendered["html"].index(f">{label}</div>") for label in ordered_labels]
        self.assertEqual(positions, sorted(positions))

    def test_canonical_verification_bundle_renders_rich_same_payload_report(self) -> None:
        bundle = build_canonical_verification_bundle()

        payload = bundle["payload"]
        rendered = render_report_email(payload)

        self.assertEqual(bundle["case"]["manager_name"], "Эльмира Кешубаева")
        self.assertEqual(bundle["case"]["date_from"], "2026-04-06")
        self.assertEqual(bundle["case"]["date_to"], "2026-04-06")
        self.assertEqual(len(bundle["case"]["selected_calls"]), 8)
        self.assertEqual(payload["meta"]["canonical_verification_case"]["manager_name"], "Эльмира Кешубаева")
        self.assertEqual(payload["meta"]["canonical_verification_case"]["date_from"], "2026-04-06")
        self.assertEqual(payload["header"]["report_date"], "2026-04-06")
        self.assertEqual(payload["kpi_overview"]["calls_count"], 8)
        self.assertNotIn("PREVIEW", rendered["subject"])
        self.assertNotIn("insufficient data", rendered["text"].lower())
        self.assertNotIn("preview shell", rendered["text"].lower())
        self.assertGreaterEqual(rendered["artifact"]["page_count"], 6)
        self.assertIn("0:10", rendered["text"])
        self.assertIn("10:30", rendered["text"])
        self.assertIn("~180 000 тенге", rendered["text"])
        self.assertIn("Что имел в виду", rendered["text"])

    def test_render_report_email_prefers_docx_first_when_requested(self) -> None:
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[_artifact()],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        with patch(
            "app.agents.calls.report_templates._render_docx_first_pdf_report",
            return_value=(
                b"%PDF-docx-first",
                7,
                "template_docx_first_pdf_manager_daily_template_v2",
                {
                    "build_path": "docx_first_pdf_delivery",
                    "conversion_path": "soffice --headless --convert-to pdf",
                    "conversion_status": "converted",
                    "source_artifact": {
                        "kind": "docx_report",
                        "filename": "report.docx",
                        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        "size_bytes": 1234,
                        "generator_path": "scripts/generate_docx_report.js",
                    },
                },
                {
                    "conversion_path": "soffice --headless --convert-to pdf",
                    "conversion_status": "converted",
                },
            ),
        ):
            rendered = render_report_email(payload, prefer_docx_first=True)

        self.assertEqual(rendered["artifact"]["render_variant"], "template_docx_first_pdf_manager_daily_template_v2")
        self.assertEqual(rendered["artifact"]["conversion_status"], "converted")
        self.assertEqual(rendered["artifact"]["source_artifact"]["kind"], "docx_report")
        self.assertEqual(rendered["template"]["source_of_truth_generator_path"], "scripts/generate_docx_report.js")


class ManualReportingStatusTests(unittest.TestCase):
    def test_execution_model_differs_between_presets(self) -> None:
        self.assertEqual(
            CallsManualReportingOrchestrator._resolve_execution_model(
                preset=resolve_report_preset("manager_daily")
            ),
            "source_aware_full_manual",
        )
        self.assertEqual(
            CallsManualReportingOrchestrator._resolve_execution_model(
                preset=resolve_report_preset("rop_weekly")
            ),
            "persisted_only",
        )

    def test_resolve_rop_weekly_email_from_bitrix_head_returns_active_head_email(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        department = SimpleNamespace(settings={"bitrix_department_id": "7"})

        fake_departments = [SimpleNamespace(bitrix_department_id="7", head_user_id="620")]
        fake_head_user = SimpleNamespace(active=True, email="b.urkenay@dogovor24.kz")

        with patch("app.agents.calls.reporting.Bitrix24ReadOnlyClient") as client_cls:
            client = client_cls.return_value
            client.list_departments.return_value = fake_departments
            client.get_user_by_id.return_value = fake_head_user

            result = CallsManualReportingOrchestrator._resolve_rop_weekly_email_from_bitrix_head(
                orchestrator,
                department=department,
            )

        self.assertEqual(result, "b.urkenay@dogovor24.kz")

    def test_single_report_result_returns_missing_artifacts_status(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        orchestrator.delivery = SimpleNamespace(
            deliver_operator_report=lambda **kwargs: {
                "targets": [{"channel": "telegram", "target": "74665909", "status": "sent"}],
                "transport": {
                    "mode": "split_operator_delivery",
                    "telegram_test_delivery": {"enabled": True, "status": "delivered", "target": "74665909"},
                    "email_delivery": {"enabled": False, "status": "skipped"},
                    "resolved_email": {"primary_email": None, "cc_emails": []},
                },
            },
        )
        artifact = ReportArtifact(
            interaction=_interaction(manager_id=uuid4(), text=""),
            analysis=None,
            manager=_manager(),
            call_started_at=None,
        )

        result = CallsManualReportingOrchestrator._build_single_report_result(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            send_email=False,
        )

        self.assertEqual(result["status"], "missing_artifacts")
        self.assertIn("analysis_missing", result["errors"][0])
        self.assertTrue(result["preview_only"])
        self.assertTrue(result["not_deliverable_manager_report"])
        self.assertIn("PREVIEW", result["payload"]["header"]["report_title"])
        self.assertEqual(result["delivery"]["transport"]["telegram_test_delivery"]["status"], "delivered")

    def test_single_report_result_returns_recipient_blocked_when_resolution_fails(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        setattr(
            orchestrator,
            "_build_payload",
            lambda **kwargs: build_manager_daily_payload(
                department_id=str(uuid4()),
                department_name="Отдел продаж",
                artifacts=kwargs["artifacts"],
                period=kwargs["period"],
                filters=kwargs["filters"],
                mode=kwargs["mode"],
                model_override=kwargs["model_override"],
            ),
        )
        setattr(
            orchestrator,
            "_resolve_delivery_targets",
            lambda **kwargs: (_ for _ in ()).throw(
                DeliveryError("manager_daily recipient is not resolvable")
            ),
        )
        orchestrator.delivery = SimpleNamespace(
            preview_report_delivery=lambda **kwargs: {
                "mode": "split_operator_delivery",
                "telegram_test_delivery": {"enabled": True, "status": "planned", "target": "74665909"},
                "email_delivery": {"enabled": True, "status": "blocked", "error": kwargs["email_resolution_error"]},
                "resolved_email": {"primary_email": None, "cc_emails": []},
            },
            deliver_operator_report=lambda **kwargs: {
                "targets": [{"channel": "telegram", "target": "74665909", "status": "sent"}],
                "transport": {
                    "mode": "split_operator_delivery",
                    "telegram_test_delivery": {"enabled": True, "status": "delivered", "target": "74665909"},
                    "email_delivery": {"enabled": True, "status": "blocked", "error": kwargs["email_resolution_error"]},
                    "resolved_email": {"primary_email": None, "cc_emails": []},
                },
            },
        )

        result = CallsManualReportingOrchestrator._build_single_report_result(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            artifacts=[_artifact()],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            send_email=True,
        )

        self.assertEqual(result["status"], "delivered")
        self.assertIn("recipient is not resolvable", result["errors"][-1])
        self.assertEqual(result["delivery"]["transport"]["telegram_test_delivery"]["status"], "delivered")
        self.assertEqual(result["delivery"]["transport"]["email_delivery"]["status"], "blocked")

    def test_single_report_result_delivers_ready_payload(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        setattr(
            orchestrator,
            "_build_payload",
            lambda **kwargs: build_manager_daily_payload(
                department_id=str(uuid4()),
                department_name="Отдел продаж",
                artifacts=kwargs["artifacts"],
                period=kwargs["period"],
                filters=kwargs["filters"],
                mode=kwargs["mode"],
                model_override=kwargs["model_override"],
            ),
        )
        setattr(
            orchestrator,
            "_resolve_delivery_targets",
            lambda **kwargs: {
                "primary_email": "elmira@example.com",
                "cc_emails": ["sales@dogovor24.kz"],
            },
        )
        orchestrator.delivery = SimpleNamespace(
            preview_report_delivery=lambda **kwargs: {
                "mode": "split_operator_delivery",
                "telegram_test_delivery": {"enabled": True, "status": "planned", "target": "74665909"},
                "email_delivery": {"enabled": True, "status": "planned", "primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
                "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
            },
            deliver_operator_report=lambda **kwargs: {
                "targets": [
                    {"channel": "telegram", "target": "74665909", "status": "sent"},
                    {"channel": "email", "target": "elmira@example.com", "status": "sent"},
                ],
                "transport": {
                    "mode": "split_operator_delivery",
                    "telegram_test_delivery": {"enabled": True, "status": "delivered", "target": "74665909"},
                    "email_delivery": {"enabled": True, "status": "delivered", "primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
                    "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
                },
            },
        )

        result = CallsManualReportingOrchestrator._build_single_report_result(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            artifacts=[_artifact()],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            send_email=True,
        )

        self.assertEqual(result["status"], "delivered")
        self.assertEqual(result["delivery"]["targets"][0]["channel"], "telegram")
        self.assertEqual(result["delivery"]["transport"]["email_delivery"]["status"], "delivered")

    def test_single_report_result_returns_blocked_when_delivery_fails(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        setattr(
            orchestrator,
            "_build_payload",
            lambda **kwargs: build_manager_daily_payload(
                department_id=str(uuid4()),
                department_name="Отдел продаж",
                artifacts=kwargs["artifacts"],
                period=kwargs["period"],
                filters=kwargs["filters"],
                mode=kwargs["mode"],
                model_override=kwargs["model_override"],
            ),
        )
        setattr(
            orchestrator,
            "_resolve_delivery_targets",
            lambda **kwargs: {
                "primary_email": "elmira@example.com",
                "cc_emails": ["sales@dogovor24.kz"],
            },
        )
        orchestrator.delivery = SimpleNamespace(
            preview_report_delivery=lambda **kwargs: {
                "mode": "split_operator_delivery",
                "telegram_test_delivery": {"enabled": True, "status": "planned", "target": "74665909"},
                "email_delivery": {"enabled": True, "status": "planned", "primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
                "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
            },
            deliver_operator_report=lambda **kwargs: {
                "targets": [{"channel": "telegram", "target": "74665909", "status": "sent"}],
                "transport": {
                    "mode": "split_operator_delivery",
                    "telegram_test_delivery": {"enabled": True, "status": "delivered", "target": "74665909"},
                    "email_delivery": {"enabled": True, "status": "failed", "error": "Email delivery failed: SMTP auth error 535"},
                    "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
                },
            },
        )

        result = CallsManualReportingOrchestrator._build_single_report_result(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            artifacts=[_artifact()],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            send_email=True,
        )

        self.assertEqual(result["status"], "partial")
        self.assertIn("SMTP auth error 535", result["errors"][-1])

    def test_single_report_result_keeps_ready_preview_when_delivery_disabled(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        setattr(
            orchestrator,
            "_build_payload",
            lambda **kwargs: build_manager_daily_payload(
                department_id=str(uuid4()),
                department_name="Отдел продаж",
                artifacts=kwargs["artifacts"],
                period=kwargs["period"],
                filters=kwargs["filters"],
                mode=kwargs["mode"],
                model_override=kwargs["model_override"],
            ),
        )
        setattr(
            orchestrator,
            "_resolve_delivery_targets",
            lambda **kwargs: {
                "primary_email": "elmira@example.com",
                "cc_emails": ["sales@dogovor24.kz"],
            },
        )
        orchestrator.delivery = SimpleNamespace(
            preview_report_delivery=lambda **kwargs: {
                "mode": "split_operator_delivery",
                "telegram_test_delivery": {"enabled": True, "status": "planned", "target": "74665909"},
                "email_delivery": {"enabled": False, "status": "skipped", "primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
                "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
            },
            deliver_operator_report=lambda **kwargs: {
                "targets": [{"channel": "telegram", "target": "74665909", "status": "sent"}],
                "transport": {
                    "mode": "split_operator_delivery",
                    "telegram_test_delivery": {"enabled": True, "status": "delivered", "target": "74665909"},
                    "email_delivery": {"enabled": False, "status": "skipped"},
                    "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
                },
            },
        )

        result = CallsManualReportingOrchestrator._build_single_report_result(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            artifacts=[_artifact()],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            send_email=False,
        )

        self.assertEqual(result["status"], "delivered")
        self.assertEqual(result["delivery"]["transport"]["email_delivery"]["status"], "skipped")

    def test_manager_daily_group_result_returns_full_report_when_day_is_ready(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        manager = _manager()
        setattr(
            orchestrator,
            "_build_payload",
            lambda **kwargs: build_manager_daily_payload(
                department_id=str(uuid4()),
                department_name="Отдел продаж",
                artifacts=kwargs["artifacts"],
                period=kwargs["period"],
                filters=kwargs["filters"],
                mode=kwargs["mode"],
                model_override=kwargs["model_override"],
            ),
        )
        setattr(
            orchestrator,
            "_resolve_delivery_targets",
            lambda **kwargs: {
                "primary_email": "elmira@example.com",
                "cc_emails": ["sales@dogovor24.kz"],
            },
        )
        orchestrator.delivery = SimpleNamespace(
            preview_report_delivery=lambda **kwargs: {
                "mode": "split_operator_delivery",
                "telegram_test_delivery": {"enabled": True, "status": "planned", "target": "74665909"},
                "email_delivery": {"enabled": False, "status": "skipped"},
                "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
            },
            deliver_operator_report=lambda **kwargs: {
                "targets": [{"channel": "telegram", "target": "74665909", "status": "sent"}],
                "transport": {
                    "mode": "split_operator_delivery",
                    "telegram_test_delivery": {"enabled": True, "status": "delivered", "target": "74665909"},
                    "email_delivery": {"enabled": False, "status": "skipped"},
                    "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
                },
            },
        )
        artifacts = [
            _artifact_for_manager(manager, score_percent=92.0, level="strong", call_date=f"2026-03-25 0{i}:00:00")
            for i in range(1, 7)
        ]

        result = CallsManualReportingOrchestrator._build_manager_daily_group_result(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            artifacts=artifacts,
            source_period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            send_email=False,
            windows=CallsManualReportingOrchestrator._build_manager_daily_windows(anchor_day="2026-03-25"),
        )

        self.assertEqual(result["readiness_outcome"], "full_report")
        self.assertEqual(result["window_days_used"], 1)
        self.assertEqual(result["relevant_calls"], 6)
        self.assertEqual(result["ready_analyses"], 6)
        self.assertEqual(result["analysis_coverage"], 100.0)
        self.assertEqual(result["status"], "delivered")

    def test_manager_daily_group_result_expands_to_signal_report_on_second_workday_window(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        manager = _manager()
        setattr(
            orchestrator,
            "_build_payload",
            lambda **kwargs: build_manager_daily_payload(
                department_id=str(uuid4()),
                department_name="Отдел продаж",
                artifacts=kwargs["artifacts"],
                period=kwargs["period"],
                filters=kwargs["filters"],
                mode=kwargs["mode"],
                model_override=kwargs["model_override"],
            ),
        )
        setattr(
            orchestrator,
            "_resolve_delivery_targets",
            lambda **kwargs: {
                "primary_email": "elmira@example.com",
                "cc_emails": ["sales@dogovor24.kz"],
            },
        )
        orchestrator.delivery = SimpleNamespace(
            preview_report_delivery=lambda **kwargs: {
                "mode": "split_operator_delivery",
                "telegram_test_delivery": {"enabled": True, "status": "planned", "target": "74665909"},
                "email_delivery": {"enabled": False, "status": "skipped"},
                "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
            },
            deliver_operator_report=lambda **kwargs: {
                "targets": [{"channel": "telegram", "target": "74665909", "status": "sent"}],
                "transport": {
                    "mode": "split_operator_delivery",
                    "telegram_test_delivery": {"enabled": True, "status": "delivered", "target": "74665909"},
                    "email_delivery": {"enabled": False, "status": "skipped"},
                    "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
                },
            },
        )
        missing_artifact = _artifact_for_manager(
            manager,
            score_percent=62.0,
            level="baseline",
            call_date="2026-03-25 11:00:00",
        )
        missing_artifact.analysis = None
        artifacts = [
            _artifact_for_manager(
                manager,
                score_percent=90.0,
                level="strong",
                call_date="2026-03-24 10:00:00",
                gaps=[
                    {
                        "title": "Фиксация следующего шага",
                        "comment": "Паттерн повторяется и требует коррекции.",
                    }
                ],
                recommendations=[
                    {
                        "criterion_name": "Фиксация следующего шага",
                        "recommendation": "В каждом звонке фиксировать дату и формат следующего контакта.",
                        "problem": "Следующий шаг звучит слишком общо.",
                    }
                ],
            ),
            _artifact_for_manager(
                manager,
                score_percent=58.0,
                level="problematic",
                call_date="2026-03-25 10:00:00",
                gaps=[
                    {
                        "title": "Фиксация следующего шага",
                        "comment": "Паттерн повторяется и требует коррекции.",
                    }
                ],
                recommendations=[
                    {
                        "criterion_name": "Фиксация следующего шага",
                        "recommendation": "В конце звонка сразу фиксировать дедлайн следующего шага.",
                        "problem": "Клиент уходит без ясной договоренности.",
                    }
                ],
            ),
            missing_artifact,
        ]

        result = CallsManualReportingOrchestrator._build_manager_daily_group_result(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            artifacts=artifacts,
            source_period={"date_from": "2026-03-24", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            send_email=False,
            windows=CallsManualReportingOrchestrator._build_manager_daily_windows(anchor_day="2026-03-25"),
        )

        self.assertEqual(result["readiness_outcome"], "signal_report")
        self.assertEqual(result["window_days_used"], 2)
        self.assertEqual(result["relevant_calls"], 3)
        self.assertEqual(result["ready_analyses"], 2)
        self.assertIn("signal_report_ready", result["readiness_reason_codes"])
        self.assertEqual(result["status"], "delivered")
        self.assertIn("Сигнальный отчёт", result["preview"]["text"])
        self.assertIn("Найдено в телефонии: 3", result["preview"]["text"])
        self.assertIn("вошло в отчёт: 2", result["preview"]["text"])

    def test_signal_report_model_uses_manager_facing_polish_rules(self) -> None:
        manager = _manager()
        artifacts = [
            _artifact_for_manager(manager, score_percent=58.0, level="problematic"),
            _artifact_for_manager(manager, score_percent=90.0, level="strong", call_date="2026-03-25 11:00:00"),
        ]
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=artifacts,
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        payload["meta"]["readiness"] = {
            "readiness_outcome": "signal_report",
            "relevant_calls": 4,
            "ready_analyses": 2,
            "readiness_reason_codes": ["signal_report_ready"],
            "window_days_used": 1,
            "analysis_coverage": 50.0,
            "content_blocks": {},
            "content_signals": {},
        }
        payload["voice_of_customer"] = {
            "rows": [
                ["Клиент 1", "Нужно подумать", "Смысл: клиенту не хватило конкретики. Ответить: уточнить задачу."],
                ["Клиент 2", "Пока не уверен", "Смысл: клиенту не хватило конкретики. Ответить: уточнить задачу."],
                ["Клиент 3", "Сначала согласуем внутри", "Смысл: клиенту не хватило конкретики. Ответить: уточнить задачу."],
            ]
        }
        payload["score_by_stage"] = [
            {
                "stage_code": "completion_next_step",
                "stage_name": "Завершение и следующий шаг",
                "score": 6.0,
                "is_priority": True,
                "criteria_detail": [],
            }
        ]

        report = build_report_render_model(payload)
        sections = {section["id"]: section for section in report["sections"]}

        self.assertIn("Сигнальный отчёт", sections["report_header"]["selection_note"])
        self.assertIn("/5", sections["main_focus_for_tomorrow"]["situation_title"])
        self.assertNotIn("первый этап ниже", sections["main_focus_for_tomorrow"]["situation_title"])
        self.assertEqual(len(sections["voice_of_customer"]["rows"]), 1)
        self.assertEqual(
            sections["call_tomorrow"]["rows"][0][:3],
            ["🔴 Горячий", "+77070000000", "Повод: подтвердить договорённость"],
        )
        self.assertEqual(len(sections["call_tomorrow"]["rows"][0]), 5)
        self.assertIn("Подтвердить договорённость", sections["call_tomorrow"]["rows"][0][3])
        self.assertIn("Хочу подтвердить", sections["call_tomorrow"]["rows"][0][4])

    def test_manager_daily_group_result_returns_skip_accumulate_when_readiness_is_not_met(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        manager = _manager()
        orchestrator.delivery = SimpleNamespace(
            deliver_operator_report=lambda **kwargs: {
                "targets": [{"channel": "telegram", "target": "74665909", "status": "sent"}],
                "transport": {
                    "mode": "split_operator_delivery",
                    "telegram_test_delivery": {"enabled": True, "status": "delivered", "target": "74665909"},
                    "email_delivery": {"enabled": False, "status": "skipped"},
                    "resolved_email": {"primary_email": None, "cc_emails": []},
                },
            },
        )
        artifacts = [
            _artifact_for_manager(
                manager,
                score_percent=63.0,
                level="basic",
                call_date="2026-03-25 10:00:00",
                strengths=[],
                gaps=[],
                recommendations=[],
            )
        ]

        result = CallsManualReportingOrchestrator._build_manager_daily_group_result(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            artifacts=artifacts,
            source_period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            send_email=False,
            windows=CallsManualReportingOrchestrator._build_manager_daily_windows(anchor_day="2026-03-25"),
        )

        self.assertEqual(result["status"], "skip_accumulate")
        self.assertEqual(result["readiness_outcome"], "skip_accumulate")
        self.assertIn("skip_accumulate_readiness_not_met", result["readiness_reason_codes"])
        self.assertTrue(result["preview_only"])
        self.assertTrue(result["not_deliverable_manager_report"])
        self.assertIsNotNone(result["artifact"])
        self.assertEqual(result["delivery"]["transport"]["telegram_test_delivery"]["status"], "delivered")

    def test_manager_daily_empty_state_result_supports_no_data_shell(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        orchestrator.delivery = SimpleNamespace(
            deliver_operator_report=lambda **kwargs: {
                "targets": [{"channel": "telegram", "target": "74665909", "status": "sent"}],
                "transport": {
                    "mode": "split_operator_delivery",
                    "telegram_test_delivery": {"enabled": True, "status": "delivered", "target": "74665909"},
                    "email_delivery": {"enabled": False, "status": "skipped"},
                    "resolved_email": {"primary_email": None, "cc_emails": []},
                },
            },
        )

        result = CallsManualReportingOrchestrator._build_manager_daily_empty_state_result(
            orchestrator,
            status="no_data",
            artifacts=[],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(
                date_from="2026-03-25",
                date_to="2026-03-25",
                manager_extensions=["322"],
            ),
            mode="report_from_ready_data_only",
            model_override=None,
            send_email=False,
            reason_codes=["no_interactions_for_selected_filters"],
            relevant_calls=0,
            ready_analyses=0,
            analysis_coverage=0.0,
            missing=["no_interactions_for_selected_filters"],
            readiness=None,
        )

        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["readiness_outcome"], "no_data")
        self.assertTrue(result["preview_only"])
        self.assertIn("insufficient data", result["payload"]["empty_state"]["hero_focus"].lower())
        self.assertEqual(result["delivery"]["transport"]["telegram_test_delivery"]["status"], "delivered")

    def test_build_run_observability_reports_stage_summary_and_safe_cost_fallback(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)

        observability = CallsManualReportingOrchestrator._build_run_observability(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            source_summary={
                "execution_model": "source_aware_full_manual",
                "days_scanned": 1,
                "source_records_total": 2,
                "eligible_source_records_total": 2,
                "targeted_source_records_total": 2,
                "already_persisted_source_records_total": 1,
                "missing_source_records_total": 1,
                "ingest_created_total": 1,
                "ingest_skipped_total": 1,
            },
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            source_period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            mode="build_missing_and_report",
            send_email=True,
            selected_interactions_count=2,
            build_summary={
                "transcripts_built": 1,
                "transcripts_reused": 1,
                "analyses_built": 1,
                "analyses_reused": 1,
                "missing_transcripts_before_build": 1,
                "missing_analyses_before_build": 1,
            },
            reports=[
                {
                    "status": "delivered",
                    "errors": [],
                    "payload": {"meta": {"group_key": "manager_daily:test"}},
                    "preview": {"subject": "subject"},
                    "delivery": {
                        "targets": [{"channel": "telegram", "target": "74665909", "status": "sent"}],
                        "transport": {
                            "mode": "split_operator_delivery",
                            "telegram_test_delivery": {
                                "enabled": True,
                                "status": "delivered",
                                "target": "74665909",
                            },
                            "email_delivery": {
                                "enabled": True,
                                "status": "delivered",
                                "primary_email": "elmira@example.com",
                                "cc_emails": ["sales@dogovor24.kz"],
                            },
                            "resolved_email": {
                                "primary_email": "elmira@example.com",
                                "cc_emails": ["sales@dogovor24.kz"],
                            },
                        },
                    },
                }
            ],
            overall_status="completed",
        )

        self.assertEqual(observability["run_state"], "completed")
        self.assertEqual(observability["summary"]["execution_model"], "source_aware_full_manual")
        self.assertEqual(observability["summary"]["selected_interactions_count"], 2)
        self.assertEqual(observability["summary"]["reused_analyses_count"], 1)
        self.assertEqual(observability["summary"]["rebuilt_analyses_count"], 1)
        self.assertEqual(observability["summary"]["source"]["ingest_created_total"], 1)
        self.assertEqual(observability["summary"]["delivery"]["mode"], "split_operator_delivery")
        self.assertEqual(observability["summary"]["template_version"], "manager_daily_template_v2")
        self.assertEqual(observability["summary"]["render_variant"], "template_pdf_manager_daily_template_v2")
        self.assertEqual(observability["summary"]["generator_path"], "app.agents.calls.report_templates.render_report_artifact")
        self.assertEqual(observability["stages"][-1]["status"], "completed")
        self.assertEqual(observability["stages"][0]["code"], "source-discovery")
        self.assertEqual(observability["ai_costs"][0]["cost_status"], "not_available")

    def test_build_run_observability_marks_no_data_as_blocked_selection(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)

        observability = CallsManualReportingOrchestrator._build_run_observability(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            source_summary={
                "execution_model": "source_aware_full_manual",
                "days_scanned": 1,
                "source_records_total": 0,
                "eligible_source_records_total": 0,
                "targeted_source_records_total": 0,
                "already_persisted_source_records_total": 0,
                "missing_source_records_total": 0,
                "ingest_created_total": 0,
                "ingest_skipped_total": 0,
            },
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            source_period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            mode="report_from_ready_data_only",
            send_email=False,
            selected_interactions_count=0,
            build_summary={
                "transcripts_built": 0,
                "transcripts_reused": 0,
                "analyses_built": 0,
                "analyses_reused": 0,
                "missing_transcripts_before_build": 0,
                "missing_analyses_before_build": 0,
            },
            reports=[],
            overall_status="no_data",
            errors=["no_interactions_for_selected_filters"],
        )

        self.assertEqual(observability["run_state"], "blocked")
        self.assertEqual(observability["stages"][0]["status"], "warn")
        self.assertEqual(observability["summary"]["delivery"]["result"], "not_started")

    def test_build_run_observability_marks_rop_weekly_as_persisted_only(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)

        observability = CallsManualReportingOrchestrator._build_run_observability(
            orchestrator,
            preset=resolve_report_preset("rop_weekly"),
            source_summary={
                "execution_model": "persisted_only",
                "days_scanned": 0,
                "source_records_total": 0,
                "eligible_source_records_total": 0,
                "targeted_source_records_total": 0,
                "already_persisted_source_records_total": 0,
                "missing_source_records_total": 0,
                "ingest_created_total": 0,
                "ingest_skipped_total": 0,
            },
            period={"date_from": "2026-03-20", "date_to": "2026-03-26"},
            source_period={"date_from": "2026-03-20", "date_to": "2026-03-26"},
            mode="build_missing_and_report",
            send_email=False,
            selected_interactions_count=2,
            build_summary={
                "transcripts_built": 0,
                "transcripts_reused": 2,
                "analyses_built": 0,
                "analyses_reused": 2,
                "missing_transcripts_before_build": 0,
                "missing_analyses_before_build": 0,
                "transcript_build_failed": 0,
                "analysis_build_failed": 0,
            },
            reports=[],
            overall_status="completed",
        )

        self.assertEqual(observability["summary"]["execution_model"], "persisted_only")
        self.assertEqual(observability["stages"][0]["status"], "skipped")
        self.assertEqual(observability["stages"][5]["status"], "skipped")

    def test_build_run_diagnostics_reports_empty_intersection_and_local_directory_issue(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)

        diagnostics = CallsManualReportingOrchestrator._build_run_diagnostics(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            mode="report_from_ready_data_only",
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            source_period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(
                manager_ids={"missing-manager-id"},
                manager_extensions={"322"},
                date_from="2026-03-25",
                date_to="2026-03-25",
            ),
            diagnostics_context={
                "department_id": str(uuid4()),
                "department_name": "Отдел продаж",
                "preset": "manager_daily",
                "execution_model": "source_aware_full_manual",
                "mode": "report_from_ready_data_only",
                "period": {"date_from": "2026-03-25", "date_to": "2026-03-25"},
                "selected_manager_ids": ["missing-manager-id"],
                "selected_manager_extensions": ["322"],
                "manager_filter_logic": "intersection",
                "missing_local_manager_ids": ["missing-manager-id"],
                "period_only_interactions_count": 3,
                "manager_only_interactions_count": 1,
                "extension_only_interactions_count": 2,
            },
            build_summary={
                "transcripts_built": 0,
                "transcripts_reused": 0,
                "analyses_built": 0,
                "analyses_reused": 0,
                "missing_transcripts_before_build": 0,
                "missing_analyses_before_build": 0,
            },
            reports=[],
            selected_interactions_count=0,
            final_selected_interactions_count=0,
            overall_status="no_data",
            source_summary={
                "days_scanned": 1,
                "source_records_total": 4,
                "eligible_source_records_total": 3,
                "targeted_source_records_total": 0,
                "already_persisted_source_records_total": 0,
                "missing_source_records_total": 0,
                "ingest_created_total": 0,
                "ingest_skipped_total": 0,
            },
            errors=[],
        )

        self.assertTrue(diagnostics["uses_filters_intersection"])
        self.assertIn("filters_intersection_empty", diagnostics["reason_codes"])
        self.assertIn("manager_not_in_local_directory", diagnostics["reason_codes"])
        self.assertIn("no_persisted_interactions_for_filters", diagnostics["reason_codes"])

    def test_build_run_diagnostics_reports_ready_only_reason_when_no_ready_artifacts_exist(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)

        diagnostics = CallsManualReportingOrchestrator._build_run_diagnostics(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            mode="report_from_ready_data_only",
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            source_period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            diagnostics_context={
                "department_id": str(uuid4()),
                "department_name": "Отдел продаж",
                "preset": "manager_daily",
                "execution_model": "source_aware_full_manual",
                "mode": "report_from_ready_data_only",
                "period": {"date_from": "2026-03-25", "date_to": "2026-03-25"},
                "selected_manager_ids": [],
                "selected_manager_extensions": [],
                "manager_filter_logic": "department_scope",
                "missing_local_manager_ids": [],
                "period_only_interactions_count": 2,
                "manager_only_interactions_count": 0,
                "extension_only_interactions_count": 0,
            },
            build_summary={
                "transcripts_built": 0,
                "transcripts_reused": 0,
                "analyses_built": 0,
                "analyses_reused": 0,
                "missing_transcripts_before_build": 2,
                "missing_analyses_before_build": 2,
            },
            reports=[{"status": "missing_artifacts", "errors": ["analysis_missing:test"]}],
            selected_interactions_count=2,
            final_selected_interactions_count=0,
            overall_status="blocked",
            source_summary={
                "days_scanned": 1,
                "source_records_total": 2,
                "eligible_source_records_total": 2,
                "targeted_source_records_total": 2,
                "already_persisted_source_records_total": 2,
                "missing_source_records_total": 0,
                "ingest_created_total": 0,
                "ingest_skipped_total": 2,
            },
            errors=[],
        )

        self.assertIn("no_ready_artifacts_for_ready_only_mode", diagnostics["reason_codes"])

    def test_prepare_artifacts_keeps_rop_weekly_persisted_only_even_in_build_missing_mode(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        interaction = _interaction(text="")
        setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **kwargs: {})
        setattr(orchestrator, "_load_managers_by_id", lambda **kwargs: {})
        orchestrator.extractor = SimpleNamespace(
            process=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("extractor should not run"))
        )
        orchestrator.analyzer = SimpleNamespace(
            analyze_call=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("analyzer should not run"))
        )
        orchestrator.call_orchestrator = SimpleNamespace(
            persist_analysis=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("persist_analysis should not run"))
        )

        async def _run():
            return await CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[interaction],
                preset=resolve_report_preset("rop_weekly"),
                mode="build_missing_and_report",
            )

        import asyncio

        artifacts, build_summary, build_errors = asyncio.run(_run())

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(build_summary["transcripts_built"], 0)
        self.assertEqual(build_summary["analyses_built"], 0)
        self.assertEqual(build_summary["missing_transcripts_before_build"], 1)
        self.assertEqual(build_summary["missing_analyses_before_build"], 1)
        self.assertEqual(build_errors, [])

    def test_prepare_artifacts_rejects_semantically_empty_analysis_for_reuse_and_rebuilds_it(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        interaction = _interaction()
        stale_analysis = SimpleNamespace(
            id=uuid4(),
            interaction_id=interaction.id,
            instruction_version="analysis_v1",
            is_failed=False,
            scores_detail={
                "classification": {},
                "score": {"checklist_score": {"score_percent": 72.0, "level": "basic"}},
                "score_by_stage": [],
                "strengths": [],
                "gaps": [],
                "recommendations": [],
                "follow_up": {},
            },
        )
        rebuilt_analysis = _analysis(81.0, "strong")
        setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **kwargs: {interaction.id: stale_analysis})
        setattr(orchestrator, "_load_managers_by_id", lambda **kwargs: {})
        orchestrator.extractor = SimpleNamespace(
            process=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("extractor should not run"))
        )
        orchestrator.analyzer = SimpleNamespace(analyze_call=lambda *_args, **_kwargs: rebuilt_analysis)
        orchestrator.call_orchestrator = SimpleNamespace(
            persist_analysis=lambda *_args, **_kwargs: rebuilt_analysis
        )

        async def _run():
            return await CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[interaction],
                preset=resolve_report_preset("manager_daily"),
                mode="build_missing_and_report",
            )

        import asyncio

        artifacts, build_summary, build_errors = asyncio.run(_run())

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(build_summary["analyses_reused"], 0)
        self.assertEqual(build_summary["analyses_rejected_for_reuse"], 1)
        self.assertEqual(build_summary["analyses_built"], 1)
        self.assertEqual(build_errors, [])

    def test_prepare_artifacts_reports_semantically_empty_reuse_rejection_in_ready_only_mode(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        interaction = _interaction()
        stale_analysis = SimpleNamespace(
            id=uuid4(),
            interaction_id=interaction.id,
            instruction_version="analysis_v1",
            is_failed=False,
            scores_detail={
                "classification": {},
                "score": {"checklist_score": {"score_percent": 0.0}},
                "score_by_stage": [],
                "strengths": [],
                "gaps": [],
                "recommendations": [],
                "follow_up": {},
            },
        )
        setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **kwargs: {interaction.id: stale_analysis})
        setattr(orchestrator, "_load_managers_by_id", lambda **kwargs: {})
        orchestrator.extractor = SimpleNamespace(process=lambda *_args, **_kwargs: None)
        orchestrator.analyzer = SimpleNamespace(analyze_call=lambda *_args, **_kwargs: None)
        orchestrator.call_orchestrator = SimpleNamespace(persist_analysis=lambda *_args, **_kwargs: None)

        async def _run():
            return await CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[interaction],
                preset=resolve_report_preset("manager_daily"),
                mode="report_from_ready_data_only",
            )

        import asyncio

        artifacts, build_summary, build_errors = asyncio.run(_run())

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(build_summary["analyses_reused"], 0)
        self.assertEqual(build_summary["analyses_rejected_for_reuse"], 1)
        self.assertEqual(build_summary["missing_analyses_before_build"], 1)
        self.assertTrue(any(item.startswith("analysis_reuse_rejected:") for item in build_errors))
        self.assertTrue(any(item.endswith(":semantically_empty_analysis") for item in build_errors))

    def test_ai_layer_summary_marks_full_chain_execution_for_build_missing_mode(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        interaction = _interaction()
        interaction.metadata_["ai_routing"] = {
            "stt": {
                "selected_provider": "openai",
                "selected_account_alias": "stt_primary",
                "selected_api_key_env": "OPENAI_API_KEY",
                "selected_model": "whisper-1",
                "selected_endpoint": "/audio/transcriptions",
                "executed_endpoint_path": "/audio/transcriptions",
                "selected_execution_mode": "openai_compatible",
                "execution_status": "executed",
                "executed": True,
                "request_kind": "speech_to_text",
                "provider_request_id": "req_stt_123",
            },
            "llm1": {
                "selected_provider": "openai",
                "selected_account_alias": "llm1_primary",
                "selected_api_key_env": "OPENAI_API_KEY",
                "selected_model": "gpt-4o-mini",
                "selected_execution_mode": "openai_compatible",
                "execution_status": "executed",
                "executed": True,
                "request_kind": "classification_first_pass",
                "usage": {"total_tokens": 18},
            },
            "llm2": {
                "selected_provider": "openai",
                "selected_account_alias": "llm2_primary",
                "selected_api_key_env": "OPENAI_API_KEY",
                "selected_model": "gpt-4o",
                "selected_execution_mode": "openai_compatible",
                "execution_status": "executed",
                "executed": True,
                "request_kind": "approved_contract_generation",
                "usage": {"total_tokens": 44},
            },
        }
        summary = CallsManualReportingOrchestrator._build_ai_layer_summary(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            mode="build_missing_and_report",
            build_summary={
                "transcripts_built": 1,
                "transcripts_reused": 0,
                "analyses_built": 1,
                "analyses_reused": 0,
                "missing_transcripts_before_build": 1,
                "missing_analyses_before_build": 1,
            },
            artifacts=[
                ReportArtifact(
                    interaction=interaction,
                    analysis=_analysis(82.0, "strong"),
                    manager=None,
                    call_started_at=None,
                )
            ],
        )

        self.assertEqual(summary[0]["current_run_status"], "executed")
        self.assertEqual(summary[1]["current_run_status"], "executed")
        self.assertEqual(summary[2]["current_run_status"], "executed")
        self.assertEqual(summary[0]["selected_routes"][0]["executed_endpoint_path"], "/audio/transcriptions")
        self.assertEqual(summary[0]["selected_routes"][0]["provider_request_id"], "req_stt_123")
        self.assertEqual(summary[1]["selected_routes"][0]["selected_account_alias"], "llm1_primary")
        self.assertEqual(summary[2]["selected_routes"][0]["request_kind"], "approved_contract_generation")

    def test_ai_layer_summary_marks_ready_only_skip_reason_with_reuse_audit(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        interaction = _interaction()
        interaction.metadata_["ai_routing"] = {
            "stt": {
                "selected_provider": "openai",
                "selected_account_alias": "stt_primary",
                "selected_model": "whisper-1",
                "execution_status": "executed",
                "executed": True,
                "request_kind": "speech_to_text",
            },
            "llm1": {
                "selected_provider": "openai",
                "selected_account_alias": "llm1_primary",
                "selected_model": "gpt-4o-mini",
                "execution_status": "executed",
                "executed": True,
                "request_kind": "classification_first_pass",
            },
            "llm2": {
                "selected_provider": "openai",
                "selected_account_alias": "llm2_primary",
                "selected_model": "gpt-4o",
                "execution_status": "executed",
                "executed": True,
                "request_kind": "approved_contract_generation",
            },
        }
        summary = CallsManualReportingOrchestrator._build_ai_layer_summary(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            mode="report_from_ready_data_only",
            build_summary={
                "transcripts_built": 0,
                "transcripts_reused": 1,
                "analyses_built": 0,
                "analyses_reused": 1,
                "missing_transcripts_before_build": 1,
                "missing_analyses_before_build": 1,
            },
            artifacts=[
                ReportArtifact(
                    interaction=interaction,
                    analysis=_analysis(75.0, "basic"),
                    manager=None,
                    call_started_at=None,
                )
            ],
        )

        self.assertEqual(summary[0]["current_run_status"], "skipped")
        self.assertEqual(summary[1]["current_run_status"], "skipped")
        self.assertEqual(summary[2]["current_run_status"], "skipped")
        self.assertEqual(summary[1]["skip_reason"], "mode_ready_only_no_new_builds")
        self.assertEqual(summary[1]["reused_count"], 1)
        self.assertTrue(summary[1]["provider_audit_available"])


class ManualReportingDeliveryModeTests(unittest.TestCase):
    def test_operator_report_delivery_always_sends_telegram_and_skips_email_when_disabled(self) -> None:
        delivery = object.__new__(CallsDelivery)
        delivery.logger = SimpleNamespace(info=lambda *args, **kwargs: None)

        with patch(
            "app.agents.calls.delivery.settings",
            new=SimpleNamespace(
                has_test_telegram_delivery=True,
                test_delivery_telegram_chat_id="74665909",
                telegram_bot_token="test-bot-token",
            ),
        ):
            with patch.object(
                CallsDelivery,
                "send_telegram_document",
                return_value={"channel": "telegram", "target": "74665909", "status": "sent"},
            ) as send_telegram_document:
                result = CallsDelivery.deliver_operator_report(
                    delivery,
                    primary_email="elmira@example.com",
                    cc_emails=["sales@dogovor24.kz"],
                    subject="Weekly report",
                    text="Body",
                    html="<p>Body</p>",
                    pdf_bytes=b"%PDF-test",
                    pdf_filename="weekly_report_v1.pdf",
                    template_meta={"template_id": "rop_weekly_template_v1", "version": "rop_weekly_template_v1"},
                    send_business_email=False,
                )

        send_telegram_document.assert_called_once()
        self.assertEqual(result["targets"][0]["channel"], "telegram")
        self.assertEqual(result["transport"]["mode"], "split_operator_delivery")
        self.assertEqual(result["transport"]["telegram_test_delivery"]["status"], "delivered")
        self.assertEqual(result["transport"]["email_delivery"]["status"], "skipped")
        self.assertEqual(result["transport"]["resolved_email"]["primary_email"], "elmira@example.com")
        self.assertEqual(result["artifact"]["filename"], "weekly_report_v1.pdf")


class OnlinePBXIntakeUrlTests(unittest.TestCase):
    def test_build_cdr_url_defaults_to_http_api_for_onlinepbx_hosts(self) -> None:
        intake = object.__new__(OnlinePBXIntake)
        intake.domain = "d24kz.onpbx.ru"
        intake.api_key = "test-key"
        intake.base_url = "https://d24kz.onpbx.ru/api"

        with patch(
            "app.agents.calls.intake.settings",
            new=SimpleNamespace(
                onlinepbx_cdr_url="",
            ),
        ):
            cdr_url = OnlinePBXIntake._build_cdr_url(intake)
            intake.cdr_url = cdr_url
            auth_url = OnlinePBXIntake._build_auth_url(intake)

        self.assertEqual(cdr_url, "https://api.onlinepbx.ru/d24kz.onpbx.ru/mongo_history/search.json")
        self.assertEqual(auth_url, "https://api.onlinepbx.ru/d24kz.onpbx.ru/auth.json")


@unittest.skipIf(TestClient is None, "FastAPI test client is not available")
class ManualReportingApiErrorEnvelopeTests(unittest.TestCase):
    def test_report_run_returns_json_error_envelope_for_asa_error(self) -> None:
        @contextmanager
        def fake_db():
            yield SimpleNamespace()

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def run_report(self, **kwargs):
                raise ASAError("synthetic reporting failure")

        with patch("app.core_shared.api.routes.pipeline.get_db", fake_db):
            with patch("app.core_shared.api.routes.pipeline.CallsManualReportingOrchestrator", FakeOrchestrator):
                client = TestClient(app)
                response = client.post(
                    "/pipeline/calls/report-run",
                    json={
                        "department_id": str(uuid4()),
                        "preset": "manager_daily",
                        "mode": "build_missing_and_report",
                        "date_from": "2026-03-25",
                        "date_to": "2026-03-25",
                        "send_email": False,
                    },
                )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers["content-type"].split(";")[0], "application/json")
        payload = response.json()
        self.assertEqual(payload["error"]["title"], "Manual report run failed")
        self.assertEqual(payload["error"]["type"], "manual_report_run_error")
        self.assertIn("synthetic reporting failure", payload["detail"])

    def test_report_run_returns_json_error_envelope_for_unexpected_exception(self) -> None:
        @contextmanager
        def fake_db():
            yield SimpleNamespace()

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def run_report(self, **kwargs):
                raise RuntimeError("unexpected synthetic failure")

        with patch("app.core_shared.api.routes.pipeline.get_db", fake_db):
            with patch("app.core_shared.api.routes.pipeline.CallsManualReportingOrchestrator", FakeOrchestrator):
                client = TestClient(app)
                response = client.post(
                    "/pipeline/calls/report-run",
                    json={
                        "department_id": str(uuid4()),
                        "preset": "rop_weekly",
                        "mode": "report_from_ready_data_only",
                        "date_from": "2026-03-20",
                        "date_to": "2026-03-26",
                        "send_email": False,
                    },
                )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["content-type"].split(";")[0], "application/json")
        payload = response.json()
        self.assertEqual(payload["error"]["title"], "Unexpected manual report run failure")
        self.assertEqual(payload["error"]["type"], "unexpected_manual_report_run_failure")
        self.assertIn("unexpected synthetic failure", payload["detail"])


class ScheduledReviewableReportingHelpersTests(unittest.TestCase):
    def test_extract_and_apply_manager_daily_editable_blocks(self) -> None:
        payload = {
            "narrative_day_conclusion": {"text": "Initial summary"},
            "main_focus_for_tomorrow": {"text": "Initial focus"},
            "key_problem_of_day": {"description": "Initial problem"},
            "editorial_recommendations": {"text": "Initial recommendation wording"},
            "focus_of_week": {"text": "Initial note"},
        }

        blocks = extract_editable_blocks(preset="manager_daily", payload=payload)
        self.assertEqual(blocks["top_summary"], "Initial summary")
        updated = apply_editable_blocks(
            preset="manager_daily",
            payload=payload,
            edited_blocks={
                "top_summary": "Edited summary",
                "recommendations_wording": "Edited recommendations",
            },
        )

        self.assertEqual(updated["narrative_day_conclusion"]["text"], "Edited summary")
        self.assertEqual(updated["editorial_recommendations"]["text"], "Edited recommendations")
        self.assertEqual(updated["main_focus_for_tomorrow"]["text"], "Initial focus")

    def test_apply_editable_blocks_rejects_unknown_keys(self) -> None:
        with self.assertRaises(ASAError):
            apply_editable_blocks(
                preset="rop_weekly",
                payload={"editorial_summary": {"executive_summary": "x"}},
                edited_blocks={"raw_analyzer_json": "not allowed"},
            )

    def test_scheduled_lifecycle_and_period_rule_order_are_stable(self) -> None:
        self.assertEqual(
            list(SCHEDULED_REVIEWABLE_BATCH_STATUSES),
            [
                "planned",
                "queued",
                "running",
                "review_required",
                "approved_for_delivery",
                "delivered",
                "failed",
                "paused",
            ],
        )
        self.assertEqual(
            list(SCHEDULED_REVIEWABLE_ALLOWED_PERIOD_RULES),
            ["previous_day", "last_7_days", "previous_week"],
        )

    def test_period_rule_resolution_is_deterministic(self) -> None:
        local_run_at = datetime(2026, 4, 15, 9, 0, tzinfo=UTC)
        previous_day = _compute_report_period(rule="previous_day", local_run_at=local_run_at)
        last_7_days = _compute_report_period(rule="last_7_days", local_run_at=local_run_at)
        previous_week = _compute_report_period(rule="previous_week", local_run_at=local_run_at)

        self.assertEqual((previous_day.date_from, previous_day.date_to), ("2026-04-14", "2026-04-14"))
        self.assertEqual((last_7_days.date_from, last_7_days.date_to), ("2026-04-08", "2026-04-14"))
        self.assertEqual((previous_week.date_from, previous_week.date_to), ("2026-04-06", "2026-04-12"))

    def test_next_local_occurrence_does_not_start_future_schedule_early(self) -> None:
        now_utc = datetime(2026, 4, 15, 8, 0, tzinfo=UTC)
        next_occurrence = _next_local_occurrence(
            start_date=date(2026, 4, 20),
            start_time="09:30",
            timezone_name="Etc/UTC",
            recurrence_type="daily",
            now_utc=now_utc,
        )
        self.assertEqual(next_occurrence.isoformat(), "2026-04-20T09:30:00+00:00")

    def test_apply_editable_blocks_rejects_forbidden_raw_fields_with_structured_error(self) -> None:
        with self.assertRaises(ASAError) as error:
            apply_editable_blocks(
                preset="manager_daily",
                payload={},
                edited_blocks={"raw_analyzer_json": "forbidden"},
            )
        self.assertIn("scheduled_reviewable_reporting.edit_block_forbidden", str(error.exception))


class ScheduledReviewableReportingServiceTests(unittest.TestCase):
    def _make_service(self) -> ScheduledReviewableReportingService:
        service = object.__new__(ScheduledReviewableReportingService)
        service.db = SimpleNamespace(add=lambda *_args, **_kwargs: None, flush=lambda: None)
        return service

    def test_batch_transition_map_is_explicit(self) -> None:
        self.assertEqual(SCHEDULED_REVIEWABLE_BATCH_ALLOWED_TRANSITIONS["planned"], ("queued", "failed", "paused"))
        self.assertEqual(SCHEDULED_REVIEWABLE_BATCH_ALLOWED_TRANSITIONS["review_required"], ("approved_for_delivery", "failed", "paused"))

    def test_invalid_batch_transition_is_rejected(self) -> None:
        service = self._make_service()
        batch = SimpleNamespace(status="planned")
        with self.assertRaises(ASAError) as error:
            service._transition_batch_status(batch, "delivered")
        self.assertIn("scheduled_reviewable_reporting.invalid_batch_transition", str(error.exception))

    def test_edit_draft_persists_audit_with_original_and_edited_blocks(self) -> None:
        service = self._make_service()
        draft = SimpleNamespace(
            id=uuid4(),
            status="review_required",
            preset="manager_daily",
            generated_payload={
                "narrative_day_conclusion": {"text": "Generated summary"},
                "main_focus_for_tomorrow": {"text": "Generated focus"},
            },
            generated_blocks={"top_summary": "Generated summary", "focus_wording": "Generated focus"},
            edited_blocks={},
            edit_audit=[],
        )
        service._get_draft = lambda _draft_id: draft
        service._serialize_draft = lambda item: {"id": str(item.id), "edited_blocks": item.edited_blocks, "edit_audit": item.edit_audit}

        result = service.edit_draft(
            draft_id=str(draft.id),
            edited_blocks={"top_summary": "Edited summary"},
            editor="tester",
        )

        self.assertEqual(result["edited_blocks"]["top_summary"], "Edited summary")
        audit_entry = result["edit_audit"][0]
        self.assertEqual(audit_entry["edited_blocks"]["top_summary"]["original_generated_block"], "Generated summary")
        self.assertEqual(audit_entry["edited_blocks"]["top_summary"]["edited_block"], "Edited summary")
        self.assertEqual(audit_entry["editor"], "tester")
        self.assertIn("edited_at", audit_entry)

    def test_edit_draft_rejects_forbidden_block_server_side(self) -> None:
        service = self._make_service()
        draft = SimpleNamespace(
            id=uuid4(),
            status="review_required",
            preset="manager_daily",
            generated_payload={},
            generated_blocks={},
            edited_blocks={},
            edit_audit=[],
        )
        service._get_draft = lambda _draft_id: draft
        with self.assertRaises(ASAError) as error:
            service.edit_draft(
                draft_id=str(draft.id),
                edited_blocks={"computed_metrics": "forbidden"},
                editor="tester",
            )
        self.assertIn("scheduled_reviewable_reporting.edit_block_forbidden", str(error.exception))

    def test_approve_before_review_required_is_forbidden(self) -> None:
        service = self._make_service()
        batch = SimpleNamespace(id=uuid4(), status="queued")
        service._get_batch = lambda _batch_id: batch
        with self.assertRaises(ASAError):
            service.approve_batch(batch_id=str(batch.id), editor="tester")

    def test_due_scan_skips_disabled_and_future_schedules(self) -> None:
        service = self._make_service()
        created = []
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 4, 16, 9, 0, tzinfo=UTC)
        service.db = SimpleNamespace(add=lambda item: created.append(item), flush=lambda: None)

        disabled = SimpleNamespace(enabled=False, next_run_at=datetime(2026, 4, 15, 9, 0, tzinfo=UTC))
        future = SimpleNamespace(enabled=True, next_run_at=datetime(2026, 4, 20, 9, 0, tzinfo=UTC))
        service._run_due_schedule(schedule=disabled, now_utc=datetime(2026, 4, 15, 10, 0, tzinfo=UTC))
        service._run_due_schedule(schedule=future, now_utc=datetime(2026, 4, 15, 10, 0, tzinfo=UTC))

        self.assertEqual(created, [])

    def test_due_scan_occurrence_idempotency_does_not_create_duplicate_batch(self) -> None:
        service = self._make_service()
        created = []
        planned_for = datetime(2026, 4, 15, 9, 0, tzinfo=UTC)
        schedule = SimpleNamespace(
            id=uuid4(),
            enabled=True,
            next_run_at=planned_for,
            timezone="Etc/UTC",
            start_date=date(2026, 4, 15),
            start_time="09:00",
            recurrence_type="daily",
            last_planned_at=None,
        )
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: SimpleNamespace(id=uuid4(), planned_for=planned_for)
        service._advance_schedule = lambda **_kwargs: datetime(2026, 4, 16, 9, 0, tzinfo=UTC)
        service.db = SimpleNamespace(add=lambda item: created.append(item), flush=lambda: None)

        service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 4, 15, 9, 30, tzinfo=UTC))

        self.assertEqual(created, [])
        self.assertEqual(schedule.last_planned_at, planned_for)
        self.assertEqual(schedule.next_run_at, datetime(2026, 4, 16, 9, 0, tzinfo=UTC))

    def test_delete_schedule_archives_without_touching_history(self) -> None:
        service = self._make_service()
        schedule = SimpleNamespace(
            id=uuid4(),
            enabled=True,
            next_run_at=datetime(2026, 4, 15, 9, 0, tzinfo=UTC),
            deleted_at=None,
        )
        service._get_schedule = lambda _schedule_id: schedule

        result = service.delete_schedule(schedule_id=str(schedule.id))

        self.assertTrue(result["deleted"])
        self.assertFalse(schedule.enabled)
        self.assertIsNone(schedule.next_run_at)
        self.assertIsNotNone(schedule.deleted_at)

    def test_serialize_schedule_resolves_human_labels_with_fallbacks(self) -> None:
        department_id = uuid4()
        manager_id = str(uuid4())
        missing_manager_id = str(uuid4())
        service = self._make_service()

        class FakeResult:
            def __init__(self, items):
                self.items = items

            def filter(self, *_args, **_kwargs):
                return self

            def first(self):
                return self.items[0] if self.items else None

            def all(self):
                return self.items

        department = SimpleNamespace(id=department_id, name="Отдел продаж")
        manager = SimpleNamespace(id=UUID(manager_id), name="Эльмира", extension="322")

        def fake_query(model):
            if model.__name__ == "Department":
                return FakeResult([department])
            if model.__name__ == "Manager":
                return FakeResult([manager])
            raise AssertionError("unexpected model")

        service.db = SimpleNamespace(query=fake_query)
        schedule = SimpleNamespace(
            id=uuid4(),
            department_id=department_id,
            preset="manager_daily",
            manager_ids=[manager_id, missing_manager_id],
            enabled=True,
            start_date=date(2026, 4, 15),
            start_time="09:00",
            timezone="Etc/UTC",
            recurrence_type="daily",
            report_period_rule="previous_day",
            mode="build_missing_and_report",
            business_email_enabled=False,
            review_required=True,
            next_run_at=None,
            last_planned_at=None,
            deleted_at=None,
        )

        result = service._serialize_schedule(schedule)

        self.assertEqual(result["department_label"]["label"], "Отдел продаж")
        self.assertEqual(result["manager_labels"][0]["label"], "Эльмира (322)")
        self.assertEqual(result["manager_labels"][1]["label"], "Не найден менеджер")

    def test_scheduled_run_stops_at_review_required_and_disables_business_email_in_run_call(self) -> None:
        service = self._make_service()
        added = []
        schedule = SimpleNamespace(
            id=uuid4(),
            department_id=uuid4(),
            preset="manager_daily",
            mode="build_missing_and_report",
            report_period_rule="previous_day",
            enabled=True,
            business_email_enabled=True,
            manager_ids=[],
            timezone="Etc/UTC",
            start_date=date(2026, 4, 15),
            start_time="09:00",
            recurrence_type="daily",
            next_run_at=datetime(2026, 4, 15, 9, 0, tzinfo=UTC),
            last_planned_at=None,
        )
        service.db = SimpleNamespace(
            add=lambda item: added.append(item),
            flush=lambda: None,
        )
        service._has_open_batch = lambda **_kwargs: False
        service._get_batch_for_occurrence = lambda **_kwargs: None
        service._advance_schedule = lambda **_kwargs: datetime(2026, 4, 16, 9, 0, tzinfo=UTC)

        run_calls = []

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = SimpleNamespace()

            async def run_report(self, **kwargs):
                run_calls.append(kwargs)
                return {
                    "reports": [
                        {
                            "group_key": "manager_daily:test",
                            "payload": {
                                "narrative_day_conclusion": {"text": "Summary"},
                                "main_focus_for_tomorrow": {"text": "Focus"},
                                "key_problem_of_day": {"description": "Problem"},
                                "editorial_recommendations": {"text": "Recommendations"},
                                "focus_of_week": {"text": "Note"},
                            },
                            "preview": {"subject": "subject"},
                            "artifact": {"filename": "report.pdf"},
                            "delivery": {"transport": {"telegram_test_delivery": {"status": "delivered"}}},
                            "errors": [],
                        }
                    ],
                    "observability": {},
                    "diagnostics": {},
                    "errors": [],
                }

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            service._run_due_schedule(schedule=schedule, now_utc=datetime(2026, 4, 15, 9, 30, tzinfo=UTC))

        self.assertEqual(run_calls[0]["send_email"], False)
        batch = added[0]
        draft = added[1]
        self.assertEqual(batch.status, "review_required")
        self.assertEqual(draft.status, "review_required")

    def test_approve_uses_draft_path_and_returns_structured_failed_state(self) -> None:
        service = self._make_service()
        batch = SimpleNamespace(
            id=uuid4(),
            status="review_required",
            department_id=uuid4(),
            business_email_enabled=True,
            approved_at=None,
            approved_by=None,
            delivered_at=None,
            failed_at=None,
            errors=[],
        )
        draft = SimpleNamespace(
            id=uuid4(),
            preset="manager_daily",
            status="review_required",
            generated_payload={
                "narrative_day_conclusion": {"text": "Summary"},
                "main_focus_for_tomorrow": {"text": "Focus"},
                "key_problem_of_day": {"description": "Problem"},
                "editorial_recommendations": {"text": "Recommendations"},
                "focus_of_week": {"text": "Note"},
                "meta": {"preset": "manager_daily"},
                "delivery_meta": {"email_subject": "Subject"},
                "header": {"report_title": "Title", "manager_name": "Manager", "report_date": "2026-04-15", "department_name": "Dept"},
                "kpi_overview": {"calls_count": 1},
                "signal_of_day": {},
                "analysis_worked": [],
                "analysis_improve": [],
                "recommendations": [],
                "call_outcomes_summary": {},
                "call_list": [],
                "focus_criterion_dynamics": {},
                "memo_legend": {"call_level_legend": [], "call_status_legend": [], "recommendation_priority_legend": []},
            },
            edited_blocks={"top_summary": "Edited summary"},
            delivery={"transport": {"resolved_email": {}}},
            preview={},
            artifact={},
            errors=[],
        )
        service._get_batch = lambda _batch_id: batch
        service._load_batch_drafts = lambda _batch_id: [draft]
        service._serialize_batch = lambda item: {"id": str(item.id), "status": item.status, "errors": item.errors}

        class FakeDelivery:
            def deliver_operator_report(self, **kwargs):
                return {
                    "transport": {
                        "telegram_test_delivery": {"status": "delivered"},
                        "email_delivery": {"status": "blocked", "error": "missing business recipient"},
                    }
                }

        class FakeOrchestrator:
            def __init__(self, *args, **kwargs) -> None:
                self.delivery = FakeDelivery()

        with patch("app.agents.calls.scheduled_reporting.CallsManualReportingOrchestrator", FakeOrchestrator):
            with patch("app.agents.calls.scheduled_reporting.render_report_email", return_value={
                "subject": "Subject",
                "text": "Text",
                "html": "<p>Html</p>",
                "pdf_bytes": b"pdf",
                "artifact": {"filename": "report.pdf"},
                "template": {"version": "v1"},
            }):
                result = service.approve_batch(batch_id=str(batch.id), editor="tester")

        self.assertEqual(result["status"], "failed")
        self.assertIn("missing business recipient", result["errors"])


@unittest.skipIf(TestClient is None, "FastAPI test client is not available")
class ScheduledReviewableReportingApiTests(unittest.TestCase):
    def test_report_ui_context_includes_scheduled_reviewable_reporting(self) -> None:
        class FakeScheduleService:
            def __init__(self, db) -> None:
                self.db = db

            def list_schedules(self):
                return [{"id": "schedule-1", "preset": "manager_daily", "enabled": True}]

            def list_review_batches(self):
                return [{"id": "batch-1", "status": "review_required", "drafts": []}]

        fake_department = SimpleNamespace(id=uuid4(), name="Dept", settings={"reporting": {}})
        fake_manager = SimpleNamespace(
            id=uuid4(),
            department_id=fake_department.id,
            name="Manager",
            extension="322",
            email="m@example.com",
            bitrix_id="1",
            active=True,
        )

        class FakeQuery:
            def __init__(self, items):
                self.items = items

            def order_by(self, *_args, **_kwargs):
                return self

            def all(self):
                return self.items

        fake_db_obj = SimpleNamespace(
            query=lambda model: FakeQuery([fake_department] if model.__name__ == "Department" else [fake_manager]),
        )

        @contextmanager
        def fake_db_context():
            yield fake_db_obj

        with patch("app.core_shared.api.routes.pipeline.get_db", fake_db_context):
            with patch("app.core_shared.api.routes.pipeline.ScheduledReviewableReportingService", FakeScheduleService):
                client = TestClient(app)
                response = client.get("/pipeline/calls/report-ui/context")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("scheduled_reviewable_reporting", payload)
        self.assertEqual(
            payload["scheduled_reviewable_reporting"]["report_period_rules"],
            ["previous_day", "last_7_days", "previous_week"],
        )
        self.assertEqual(
            payload["scheduled_reviewable_reporting"]["lifecycle"],
            list(SCHEDULED_REVIEWABLE_BATCH_STATUSES),
        )

    def test_report_ui_context_keeps_static_choices_when_scheduled_storage_is_unavailable(self) -> None:
        fake_department = SimpleNamespace(id=uuid4(), name="Dept", settings={"reporting": {}})

        class FakeQuery:
            def __init__(self, items):
                self.items = items

            def order_by(self, *_args, **_kwargs):
                return self

            def all(self):
                return self.items

        fake_db_obj = SimpleNamespace(
            query=lambda model: FakeQuery([fake_department] if model.__name__ == "Department" else []),
        )

        @contextmanager
        def fake_db_context():
            yield fake_db_obj

        class FailingScheduleService:
            def __init__(self, db) -> None:
                self.db = db

            def list_schedules(self):
                raise sa.exc.ProgrammingError("select", {}, Exception("missing table"))

            def list_review_batches(self):
                raise AssertionError("should not be called after list_schedules failure")

        with patch("app.core_shared.api.routes.pipeline.get_db", fake_db_context):
            with patch("app.core_shared.api.routes.pipeline.ScheduledReviewableReportingService", FailingScheduleService):
                client = TestClient(app)
                response = client.get("/pipeline/calls/report-ui/context")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["presets"][0]["code"], "manager_daily")
        self.assertEqual(payload["modes"][0]["code"], "build_missing_and_report")
        self.assertEqual(payload["departments"][0]["name"], "Dept")
        self.assertEqual(payload["managers"], [])
        self.assertFalse(payload["scheduled_reviewable_reporting"]["available"])
        self.assertEqual(
            payload["scheduled_reviewable_reporting"]["availability_reason"],
            "scheduled_reviewable_reporting_storage_unavailable",
        )

    def test_create_schedule_endpoint_returns_created_schedule(self) -> None:
        @contextmanager
        def fake_db():
            yield SimpleNamespace()

        class FakeScheduleService:
            def __init__(self, db) -> None:
                self.db = db

            def create_schedule(self, **kwargs):
                return {"id": "schedule-1", **kwargs, "review_required": True}

        with patch("app.core_shared.api.routes.pipeline.get_db", fake_db):
            with patch("app.core_shared.api.routes.pipeline.ScheduledReviewableReportingService", FakeScheduleService):
                client = TestClient(app)
                response = client.post(
                    "/pipeline/calls/report-schedules",
                    json={
                        "department_id": str(uuid4()),
                        "manager_ids": [str(uuid4())],
                        "preset": "manager_daily",
                        "enabled": True,
                        "start_date": "2026-04-16",
                        "start_time": "09:00",
                        "timezone": "Etc/UTC",
                        "recurrence_type": "daily",
                        "report_period_rule": "previous_day",
                        "mode": "build_missing_and_report",
                        "business_email_enabled": False,
                    },
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "created")
        self.assertEqual(payload["schedule"]["report_period_rule"], "previous_day")
        self.assertTrue(payload["schedule"]["review_required"])

    def test_edit_and_approve_endpoints_return_review_objects(self) -> None:
        @contextmanager
        def fake_db():
            yield SimpleNamespace()

        class FakeScheduleService:
            def __init__(self, db) -> None:
                self.db = db

            def edit_draft(self, **kwargs):
                return {"id": "draft-1", **kwargs}

            def approve_batch(self, **kwargs):
                return {"id": "batch-1", **kwargs, "status": "delivered"}

        with patch("app.core_shared.api.routes.pipeline.get_db", fake_db):
            with patch("app.core_shared.api.routes.pipeline.ScheduledReviewableReportingService", FakeScheduleService):
                client = TestClient(app)
                edit_response = client.post(
                    "/pipeline/calls/report-review/drafts/draft-1/edit",
                    json={"edited_blocks": {"top_summary": "Edited"}, "editor": "operator_ui"},
                )
                approve_response = client.post(
                    "/pipeline/calls/report-review/batches/batch-1/approve",
                    json={"editor": "operator_ui"},
                )

        self.assertEqual(edit_response.status_code, 200)
        self.assertEqual(edit_response.json()["status"], "edited")
        self.assertEqual(approve_response.status_code, 200)
        self.assertEqual(approve_response.json()["batch"]["status"], "delivered")

    def test_delete_schedule_endpoint_returns_deleted_status(self) -> None:
        @contextmanager
        def fake_db():
            yield SimpleNamespace()

        class FakeScheduleService:
            def __init__(self, db) -> None:
                self.db = db

            def delete_schedule(self, **kwargs):
                return {"id": "schedule-1", "deleted": True, **kwargs}

        with patch("app.core_shared.api.routes.pipeline.get_db", fake_db):
            with patch("app.core_shared.api.routes.pipeline.ScheduledReviewableReportingService", FakeScheduleService):
                client = TestClient(app)
                response = client.post(
                    "/pipeline/calls/report-schedules/schedule-1/delete",
                    json={"confirm": True},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "deleted")
        self.assertTrue(payload["schedule"]["deleted"])


if __name__ == "__main__":
    unittest.main()
