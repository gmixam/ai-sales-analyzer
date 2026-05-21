"""Mirrored unit tests for the bounded Manual Reporting Pilot slice."""

from __future__ import annotations

import os
import json
import sys
import unittest
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
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
    BusinessOutcomeResolver,
    CallsManualReportingOrchestrator,
    MEANINGFUL_ABSOLUTE_MIN_DURATION_SEC,
    MEANINGFUL_NO_TRANSCRIPT_MIN_DURATION_SEC,
    ReportArtifact,
    ReportRunFilters,
    _build_meaningful_call_list,
    _build_report_evidence_situation,
    _build_selection_model_counters,
    _semantic_case_block_rejection_reason,
    _call_tomorrow_rejection_reason,
    _classify_meaningful_call,
    _select_stable_analysis_for_reporting,
    _validated_report_block_candidates,
    classify_provider_error,
    build_manager_daily_payload,
    build_rop_weekly_payload,
    render_report_email,
    resolve_report_delivery_options,
    resolve_report_preset,
)
from app.agents.calls.analyzer import APPROVED_INSTRUCTION_VERSION  # noqa: E402
from app.agents.calls.analysis_purpose import (  # noqa: E402
    ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
    ANALYSIS_PURPOSE_PRODUCTION,
    ANALYSIS_PURPOSE_VERIFICATION,
    analysis_purpose_from_analysis,
    is_controlled_analysis,
    mark_scores_detail_analysis_purpose,
)
from app.agents.calls.report_evidence import validate_report_evidence  # noqa: E402
from app.agents.calls.schemas import CDRRecord  # noqa: E402
from app.agents.calls.report_templates import (  # noqa: E402
    _call_context_label,
    build_report_render_model,
)
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
from app.core_shared.exceptions import ASAError, DeliveryError, LLMResponseError  # noqa: E402

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
        instruction_version=APPROVED_INSTRUCTION_VERSION,
        score_total=score_percent,
        scores_detail={
            "call": {
                "contact_phone": "+77070000000",
            },
            "classification": {
                "call_type": "sales_primary",
                "scenario_type": "cold_outbound",
                "analysis_eligibility": "eligible",
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


def _valid_report_evidence_detail() -> dict[str, Any]:
    return {
        "report_evidence_version": "v1",
        "report_evidence": {
            "business_outcome": {
                "status": "open",
                "confidence": "high",
                "reason": "Client asked to review the materials.",
                "evidence_quote": "Скиньте в WhatsApp, я посмотрю.",
                "evidence_speaker": "client",
                "needs_human_review": False,
            },
            "call_report_summary": {
                "short_topic": "Клиент попросил материалы в WhatsApp",
                "short_context": "Клиент готов посмотреть материалы, но срок возврата ещё не зафиксирован.",
                "client_display_name": "Алия",
                "client_name_confidence": "high",
                "hotness": "warm",
                "hotness_reason": "Есть интерес и запрос материалов, но нет обязательства по следующему шагу.",
                "manager_next_action": "Отправить материалы и согласовать дату следующего контакта.",
                "suggested_manager_phrase": "Алия, добрый день. Отправляю материалы, как договорились. Когда удобно обсудить?",
            },
            "situation_candidates": [
                {
                    "stage_code": "qualification_primary",
                    "problem_type": "missing_process",
                    "situation_title": "Контекст процесса не уточнён",
                    "priority": "high",
                    "evidence_quality": "direct",
                    "dialogue_fragment": [
                        {
                            "speaker": "client",
                            "text": "Скиньте в WhatsApp, я посмотрю.",
                            "timestamp_start": None,
                            "timestamp_end": None,
                        },
                        {
                            "speaker": "manager",
                            "text": "Хорошо, отправлю информацию.",
                            "timestamp_start": None,
                            "timestamp_end": None,
                        },
                    ],
                    "what_happened": "Менеджер согласился отправить материалы без уточнения процесса.",
                    "what_it_means": "Открытый интерес может остаться без конкретного следующего шага.",
                    "what_was_missing": "Не хватило вопроса о текущем документообороте.",
                    "next_time_action": "Уточнить текущий процесс до отправки материалов.",
                    "scripts": ["Как сейчас у вас подписываются документы?"],
                    "usable_in_report": True,
                }
            ],
            "manager_coaching_moments": [
                {
                    "stage_code": "completion_next_step",
                    "moment_type": "missed",
                    "priority": "medium",
                    "evidence_quality": "direct",
                    "dialogue_fragment": [
                        {
                            "speaker": "manager",
                            "text": "Хорошо, отправлю информацию.",
                            "timestamp_start": None,
                            "timestamp_end": None,
                        }
                    ],
                    "what_happened": "Следующий шаг остался общим.",
                    "what_better": "Закрепить срок повторного контакта.",
                    "usable_in_report": True,
                }
            ],
            "voice_of_customer": [
                {
                    "quote": "Скиньте в WhatsApp, я посмотрю.",
                    "speaker": "client",
                    "topic": "product_interest",
                    "meaning": "Client accepts materials and keeps the conversation open.",
                    "business_signal": "medium",
                    "stage_code": "completion_next_step",
                    "usable_in_report": True,
                }
            ],
            "additional_situations": [
                {
                    "type": "growth_zone",
                    "title": "Открытый интерес без срока возврата",
                    "priority": "medium",
                    "evidence_quality": "indirect",
                    "what_happened": "Клиент попросил материалы.",
                    "why_it_matters": "Без срока возврата follow-up слабее.",
                    "recommended_action": "Согласовать дату следующего контакта.",
                    "stage_code": "completion_next_step",
                    "usable_in_report": True,
                }
            ],
            "follow_up_candidates": [
                {
                    "status": "open",
                    "client_label": "Алия",
                    "next_step": "Отправить материалы и вернуться с вопросом.",
                    "deadline": "завтра",
                    "priority": "open",
                    "first_phrase": "Алия, добрый день. Отправляю материалы, как договорились.",
                    "why_follow_up": "Client asked to review materials.",
                    "usable_in_report": True,
                }
            ],
            "quote_bank": [
                {
                    "quote": "Скиньте в WhatsApp, я посмотрю.",
                    "speaker": "client",
                    "topic": "product_interest",
                    "stage_code": "completion_next_step",
                    "evidence_quality": "direct",
                    "usable_in_report": True,
                }
            ],
        },
    }


def _valid_semantic_case() -> dict[str, Any]:
    return {
        "case_title": "Открытый интерес без срока возврата",
        "case_type": "growth_zone",
        "stage_code": "completion_next_step",
        "priority": "high",
        "evidence_quality": "direct",
        "core_meaning": "Клиент готов посмотреть материалы, но менеджер не закрепил дату следующего контакта.",
        "why_this_call_matters": "Открытый интерес может потеряться, если не перевести его в конкретное действие.",
        "customer_signal": "Клиент попросил отправить материалы в WhatsApp и оставил разговор открытым.",
        "manager_behavior": "Менеджер согласился отправить информацию, но не уточнил срок возврата к обсуждению.",
        "coaching_diagnosis": "Интерес клиента нужно переводить в проверяемый следующий шаг.",
        "recommended_next_action": "Отправить материалы и согласовать дату следующего контакта.",
        "best_dialogue_fragment": [
            {
                "speaker": "client",
                "text": "Скиньте в WhatsApp, я посмотрю.",
                "timestamp_start": None,
                "timestamp_end": None,
            },
            {
                "speaker": "manager",
                "text": "Хорошо, отправлю информацию.",
                "timestamp_start": None,
                "timestamp_end": None,
            },
        ],
        "report_block_fit": {
            "situation_day": {
                "fit": True,
                "score": 88,
                "reason_code": "manager_gap_with_direct_evidence",
                "evidence_type": "manager_gap",
                "block_role": "coaching_problem",
                "title_mode": "problem",
                "problem_fit": {
                    "score": 88,
                    "problem_signal": "Следующий контакт не закреплен сроком возврата",
                    "explanation": "Менеджер согласился отправить материалы, но не зафиксировал дату следующего контакта.",
                },
                "evidence_target": "Фрагмент доказывает, что менеджер не закрепил срок возврата.",
                "gap_proven": True,
            },
            "call_breakdown": {
                "fit": True,
                "score": 82,
                "reason_code": "coachable_manager_moment",
                "evidence_type": "manager_gap",
                "block_role": "coaching_problem",
                "title_mode": "problem",
                "problem_fit": {
                    "score": 82,
                    "problem_signal": "Следующий контакт не закреплен сроком возврата",
                    "explanation": "Момент показывает действие менеджера, которое нужно усилить.",
                },
                "evidence_target": "Фрагмент показывает действие менеджера и недостающую фиксацию.",
                "gap_proven": True,
            },
            "voice_of_customer": {
                "fit": True,
                "score": 76,
                "reason_code": "direct_customer_signal",
                "evidence_type": "customer_signal",
                "block_role": "customer_signal",
                "title_mode": "neutral",
                "problem_fit": None,
                "evidence_target": "Фрагмент доказывает запрос клиента на материалы.",
                "gap_proven": None,
            },
            "additional_situations": {
                "fit": True,
                "score": 70,
                "reason_code": "missed_opportunity_with_customer_signal",
                "evidence_type": "manager_gap",
                "block_role": "coaching_problem",
                "title_mode": "problem",
                "problem_fit": {
                    "score": 70,
                    "problem_signal": "Клиентский интерес не переведен в срок возврата",
                    "explanation": "Кейс может быть вторичной зоной роста.",
                },
                "evidence_target": "Фрагмент показывает вторичный риск follow-up.",
                "gap_proven": True,
            },
            "call_tomorrow": {
                "fit": True,
                "score": 84,
                "reason_code": "client_requested_next_action",
                "evidence_type": "follow_up",
                "block_role": "follow_up_action",
                "title_mode": "neutral",
                "problem_fit": None,
                "evidence_target": "Фрагмент доказывает действие для следующего контакта.",
                "gap_proven": None,
            },
        },
        "usable_in_report": True,
    }


def _valid_report_evidence_detail_with_semantic_case() -> dict[str, Any]:
    detail = _valid_report_evidence_detail()
    detail["report_evidence"]["semantic_case"] = _valid_semantic_case()
    return detail


def _analyze_prompt_text() -> str:
    for candidate in (
        CORE_ROOT / "core" / "app" / "agents" / "calls" / "prompts" / "analyze.md",
        CORE_ROOT / "app" / "agents" / "calls" / "prompts" / "analyze.md",
    ):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("LLM2 analyze prompt asset was not found")


class ReportEvidenceValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transcript = "Клиент: Скиньте в WhatsApp, я посмотрю. Менеджер: Хорошо, отправлю информацию."

    def _validate(self, detail: dict[str, Any], transcript: str | None = None):
        return validate_report_evidence(detail, self.transcript if transcript is None else transcript)

    def _issue_codes(self, issues: list[Any]) -> set[str]:
        return {issue.code for issue in issues}

    def test_report_evidence_valid_full_package_passes(self):
        result = self._validate(_valid_report_evidence_detail_with_semantic_case())

        self.assertTrue(result.is_valid)
        self.assertEqual(result.version, "v1")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.normalized["report_evidence_version"], "v1")
        self.assertEqual(
            result.normalized["report_evidence"]["business_outcome"]["status"],
            "open",
        )
        self.assertEqual(
            result.normalized["report_evidence"]["call_report_summary"]["hotness"],
            "warm",
        )
        self.assertEqual(
            result.normalized["report_evidence"]["semantic_case"]["case_type"],
            "growth_zone",
        )

    def test_report_evidence_missing_package_is_valid_legacy_state(self):
        result = self._validate({"classification": {"call_type": "sales_primary"}})

        self.assertTrue(result.is_valid)
        self.assertIsNone(result.version)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.normalized, {})

    def test_report_evidence_missing_version_fails_when_package_exists(self):
        detail = _valid_report_evidence_detail()
        detail.pop("report_evidence_version")

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("missing_report_evidence_version", self._issue_codes(result.errors))

    def test_report_evidence_invalid_enum_fails(self):
        detail = _valid_report_evidence_detail()
        detail["report_evidence"]["business_outcome"]["status"] = "maybe"

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("schema_validation_error", self._issue_codes(result.errors))

    def test_report_evidence_invalid_summary_hotness_enum_fails(self):
        detail = _valid_report_evidence_detail()
        detail["report_evidence"]["call_report_summary"]["hotness"] = "rescheduled"

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("schema_validation_error", self._issue_codes(result.errors))

    def test_report_evidence_invalid_client_name_confidence_enum_fails(self):
        detail = _valid_report_evidence_detail()
        detail["report_evidence"]["call_report_summary"]["client_name_confidence"] = "certain"

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("schema_validation_error", self._issue_codes(result.errors))

    def test_report_evidence_too_long_call_report_summary_fields_fail(self):
        detail = _valid_report_evidence_detail()
        detail["report_evidence"]["call_report_summary"]["short_topic"] = "x" * 121
        detail["report_evidence"]["call_report_summary"]["short_context"] = "x" * 281

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("schema_validation_error", self._issue_codes(result.errors))

    def test_report_evidence_suggested_manager_phrase_copying_client_quote_fails(self):
        detail = _valid_report_evidence_detail()
        detail["report_evidence"]["call_report_summary"]["suggested_manager_phrase"] = "Скиньте в WhatsApp, я посмотрю."

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("suggested_manager_phrase_copies_client_quote", self._issue_codes(result.errors))

    def test_report_evidence_non_follow_up_outcome_with_suggested_phrase_warns(self):
        detail = _valid_report_evidence_detail()
        detail["report_evidence"]["business_outcome"]["status"] = "refusal"
        detail["report_evidence"]["follow_up_candidates"] = []

        result = self._validate(detail)

        self.assertTrue(result.is_valid)
        self.assertIn("suggested_manager_phrase_on_non_follow_up_outcome", self._issue_codes(result.warnings))

    def test_report_evidence_without_call_report_summary_remains_valid(self):
        detail = _valid_report_evidence_detail()
        detail["report_evidence"].pop("call_report_summary")

        result = self._validate(detail)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])

    def test_report_evidence_without_semantic_case_remains_valid(self):
        detail = _valid_report_evidence_detail()

        result = self._validate(detail)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])

    def test_report_evidence_invalid_stage_code_fails(self):
        detail = _valid_report_evidence_detail()
        detail["report_evidence"]["situation_candidates"][0]["stage_code"] = "unknown_stage"

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("invalid_stage_code", self._issue_codes(result.errors))

    def test_report_layer_rejects_fit_true_block_candidate_without_stage_code(self):
        candidate = {
            "fit": True,
            "score": 86,
            "role": "coaching_problem",
            "title_mode": "problem",
            "main_thesis": "Менеджер не закрепил срок возврата после отправки материалов.",
            "what_happened": "Клиент попросил материалы, менеджер согласился отправить их.",
            "why_it_matters": "Без срока возврата интерес клиента может потеряться.",
            "what_was_missing": "Не был зафиксирован срок следующего контакта.",
            "better_next_action": "Согласовать конкретную дату следующего контакта.",
            "proof_type": "sequence_inference",
            "proof_explanation": "В звонке есть запрос материалов и согласие менеджера без даты возврата.",
            "supporting_quote": "Хорошо, отправлю информацию.",
            "quote_role": "supports_context",
            "counter_evidence": [],
        }

        normalized, errors, warnings = _validated_report_block_candidates(
            raw_report_evidence={"block_candidates": {"situation_day": candidate}},
            transcript="Клиент: Скиньте материалы. Менеджер: Хорошо, отправлю информацию.",
        )

        self.assertEqual(normalized, {})
        self.assertEqual(warnings, [])
        self.assertIn(
            {
                "block": "situation_day",
                "reason": "stage_code_missing",
                "path": "report_evidence.block_candidates.situation_day",
            },
            errors,
        )

    def test_report_evidence_unsupported_speaker_fails(self):
        detail = _valid_report_evidence_detail()
        detail["report_evidence"]["quote_bank"][0]["speaker"] = "operator"

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("schema_validation_error", self._issue_codes(result.errors))

    def test_report_evidence_quote_not_in_transcript_fails(self):
        detail = _valid_report_evidence_detail()
        detail["report_evidence"]["voice_of_customer"][0]["quote"] = "Этого текста в звонке нет."

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("ungrounded_evidence_text", self._issue_codes(result.errors))

    def test_report_evidence_insufficient_but_usable_fails(self):
        detail = _valid_report_evidence_detail()
        detail["report_evidence"]["additional_situations"][0]["evidence_quality"] = "insufficient"
        detail["report_evidence"]["additional_situations"][0]["usable_in_report"] = True

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("insufficient_evidence_marked_usable", self._issue_codes(result.errors))

    def test_report_evidence_duplicate_situation_fields_warns(self):
        detail = _valid_report_evidence_detail()
        detail["report_evidence"]["situation_candidates"][0]["what_was_missing"] = detail["report_evidence"][
            "situation_candidates"
        ][0]["what_happened"]

        result = self._validate(detail)

        self.assertTrue(result.is_valid)
        self.assertIn("duplicated_situation_fields", self._issue_codes(result.warnings))

    def test_report_evidence_invalid_semantic_case_enum_fails(self):
        detail = _valid_report_evidence_detail_with_semantic_case()
        detail["report_evidence"]["semantic_case"]["case_type"] = "interesting_case"

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("schema_validation_error", self._issue_codes(result.errors))

    def test_report_evidence_invalid_semantic_case_stage_code_fails(self):
        detail = _valid_report_evidence_detail_with_semantic_case()
        detail["report_evidence"]["semantic_case"]["stage_code"] = "unknown_stage"

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("invalid_stage_code", self._issue_codes(result.errors))

    def test_report_evidence_semantic_case_missing_direct_fragment_fails(self):
        detail = _valid_report_evidence_detail_with_semantic_case()
        detail["report_evidence"]["semantic_case"]["best_dialogue_fragment"] = []

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("semantic_case_missing_grounded_fragment", self._issue_codes(result.errors))

    def test_report_evidence_semantic_case_allows_absence_coaching_moment_without_fragment(self):
        detail = _valid_report_evidence_detail_with_semantic_case()
        semantic_case = detail["report_evidence"]["semantic_case"]
        semantic_case["best_dialogue_fragment"] = []
        semantic_case["report_block_fit"]["call_breakdown"]["coaching_moment"] = {
            "summary": "В доступной записи не зафиксировано согласование срока следующего контакта.",
            "missing_action": "Менеджеру стоило согласовать дату возврата к обсуждению.",
            "why_it_matters": "Без срока открытый интерес клиента может не перейти в следующий шаг.",
            "supporting_quote": None,
            "evidence_type": "absence_in_context",
            "confidence": "medium",
        }

        result = self._validate(detail)

        self.assertTrue(result.is_valid)
        moment = result.normalized["report_evidence"]["semantic_case"]["report_block_fit"][
            "call_breakdown"
        ]["coaching_moment"]
        self.assertEqual(moment["supporting_quote"], None)
        self.assertEqual(moment["evidence_type"], "absence_in_context")

    def test_report_evidence_semantic_case_rejects_counter_evidence_quote_for_problem_gap(self):
        detail = _valid_report_evidence_detail_with_semantic_case()
        quote = "А вы, Жанар, может быть, кем являетесь в компании?"
        detail["report_evidence"]["semantic_case"]["report_block_fit"]["situation_day"]["coaching_moment"] = {
            "summary": "Менеджер не выяснил роль клиента в компании.",
            "missing_action": "Нужно было уточнить роль клиента и кто принимает решение.",
            "why_it_matters": "Без роли клиента сложно понять, с кем согласовывать следующий шаг.",
            "supporting_quote": quote,
            "evidence_type": "direct_quote",
            "confidence": "high",
            "gap_claim": "Менеджер не уточнил роль клиента и ЛПР.",
            "proof_type": "direct_gap",
            "proof_explanation": "Цитата ошибочно выбрана как доказательство отсутствия уточнения роли.",
            "quote_role": "proves_gap",
            "counter_evidence": [],
        }

        result = self._validate(detail, transcript=f"{self.transcript} Менеджер: {quote}")

        self.assertFalse(result.is_valid)
        self.assertIn("coaching_moment_proof_conflict", self._issue_codes(result.errors))

    def test_report_evidence_semantic_case_ungrounded_fragment_fails(self):
        detail = _valid_report_evidence_detail_with_semantic_case()
        detail["report_evidence"]["semantic_case"]["best_dialogue_fragment"][0]["text"] = "Этой фразы нет в звонке."

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("ungrounded_evidence_text", self._issue_codes(result.errors))

    def test_report_evidence_semantic_case_insufficient_but_usable_fails(self):
        detail = _valid_report_evidence_detail_with_semantic_case()
        detail["report_evidence"]["semantic_case"]["case_type"] = "insufficient_evidence"
        detail["report_evidence"]["semantic_case"]["evidence_quality"] = "insufficient"
        detail["report_evidence"]["semantic_case"]["usable_in_report"] = True

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("insufficient_evidence_marked_usable", self._issue_codes(result.errors))
        self.assertIn("semantic_case_insufficient_marked_usable", self._issue_codes(result.errors))

    def test_report_evidence_semantic_case_generic_field_fails(self):
        detail = _valid_report_evidence_detail_with_semantic_case()
        detail["report_evidence"]["semantic_case"]["core_meaning"] = "Нужно лучше работать с клиентом."

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("semantic_case_generic_field", self._issue_codes(result.errors))

    def test_report_evidence_invalid_report_block_fit_enum_fails(self):
        detail = _valid_report_evidence_detail_with_semantic_case()
        detail["report_evidence"]["semantic_case"]["report_block_fit"]["situation_day"][
            "reason_code"
        ] = "maybe_good"

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("schema_validation_error", self._issue_codes(result.errors))

    def test_report_evidence_report_block_fit_score_range_fails(self):
        detail = _valid_report_evidence_detail_with_semantic_case()
        detail["report_evidence"]["semantic_case"]["report_block_fit"]["call_breakdown"]["score"] = 120

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("schema_validation_error", self._issue_codes(result.errors))

    def test_report_evidence_invalid_report_block_role_enum_fails(self):
        detail = _valid_report_evidence_detail_with_semantic_case()
        detail["report_evidence"]["semantic_case"]["report_block_fit"]["situation_day"]["block_role"] = "maybe"

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("schema_validation_error", self._issue_codes(result.errors))

    def test_report_evidence_problem_fit_score_range_fails(self):
        detail = _valid_report_evidence_detail_with_semantic_case()
        detail["report_evidence"]["semantic_case"]["report_block_fit"]["situation_day"]["problem_fit"]["score"] = -1

        result = self._validate(detail)

        self.assertFalse(result.is_valid)
        self.assertIn("schema_validation_error", self._issue_codes(result.errors))

    def test_report_evidence_empty_arrays_pass(self):
        detail = {
            "report_evidence_version": "v1",
            "report_evidence": {
                "business_outcome": None,
                "semantic_case": None,
                "situation_candidates": [],
                "manager_coaching_moments": [],
                "voice_of_customer": [],
                "additional_situations": [],
                "follow_up_candidates": [],
                "quote_bank": [],
            },
        }

        result = self._validate(detail)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.normalized["report_evidence"]["situation_candidates"], [])

    def test_llm2_prompt_requires_additive_report_evidence_contract(self):
        prompt = _analyze_prompt_text()

        self.assertIn("REPORT_EVIDENCE_CONTRACT.md", prompt)
        self.assertIn("report_evidence_version", prompt)
        self.assertIn("report_evidence", prompt)
        self.assertIn("call_report_summary", prompt)
        self.assertIn("semantic_case", prompt)
        self.assertIn("report_block_fit", prompt)
        self.assertIn("block_role", prompt)
        self.assertIn("problem_fit", prompt)
        self.assertIn("title_mode", prompt)
        self.assertIn("coaching_moment", prompt)
        self.assertIn("absence_in_context", prompt)
        self.assertIn("supporting_quote` is optional", prompt)
        self.assertIn("в доступной записи/фрагменте не зафиксировано", prompt)
        self.assertIn("customer_signal_without_manager_gap", prompt)
        self.assertIn("positive_diagnosis_not_problem_case", prompt)
        self.assertIn("coherent per-call semantic analysis", prompt)
        self.assertIn("best_dialogue_fragment", prompt)
        self.assertIn("short_topic", prompt)
        self.assertIn("short_context", prompt)
        self.assertIn("manager_visible_summary", prompt)
        self.assertIn("manager_next_action", prompt)
        self.assertIn("suggested_manager_phrase", prompt)
        self.assertIn("Do not add extra top-level fields except", prompt)
        self.assertIn("Every quote and every `dialogue_fragment[].text` must be copied verbatim", prompt)
        self.assertIn("Never use these values in `report_evidence.business_outcome.status`", prompt)
        self.assertIn("Use only `hot`, `warm`, or `low`", prompt)
        self.assertIn("Do not copy a client quote", prompt)
        self.assertIn("Reporting remains final authority for deterministic hotness priority", prompt)
        self.assertIn("postponed / delayed / call later / return later -> `rescheduled`", prompt)
        self.assertIn("declined / rejected / not interested / no need / not relevant -> `refusal`", prompt)
        self.assertIn("For `business_outcome.evidence_quote`, copy an exact transcript substring or set it to `null`", prompt)
        self.assertIn("Do not copy example quotes from this prompt into the output", prompt)
        self.assertIn("Never output the prompt example phrase `Не могу подписать через QR.` unless that exact phrase appears in the transcript", prompt)
        self.assertIn("Do not omit `comment` or `evidence` while adding `report_evidence`", prompt)
        self.assertIn("return at least one `situation_candidate` tied to the strongest missed stage", prompt)
        self.assertIn("Do not leave both `situation_candidates` and `manager_coaching_moments` empty for a sales-like", prompt)
        self.assertIn("If all applicable criteria are at max, return at least one grounded `manager_coaching_moment`", prompt)
        self.assertIn("Sales-like minimum package", prompt)
        self.assertIn("Do not use an empty array to express \"no usable evidence\" for a sales-like outcome", prompt)
        self.assertIn("Every `fit=true` `block_candidates.*` item must include `stage_code` explicitly", prompt)
        self.assertIn("Never use `support`, `service`, or `tech_service` as `stage_code`", prompt)
        self.assertIn("return at least one `manager_coaching_moment`", prompt)
        self.assertIn("semantic signal, not final report authority", prompt)
        self.assertIn("Do not return `follow_up_candidates` for `refusal`, `tech_service`, or `not_suitable`", prompt)


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

    def test_manager_daily_payload_enriches_stage_problem_summaries(self) -> None:
        artifact = _artifact(55.0, "problematic")
        artifact.analysis.scores_detail["score_by_stage"] = [
            {
                "stage_code": "contact_start",
                "stage_name": "Первичный контакт",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "cs_role_scope",
                        "criterion_name": "Уточнение роли и масштаба",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Менеджер не уточнил роль собеседника и масштаб задачи.",
                    }
                ],
            },
            {
                "stage_code": "needs_discovery",
                "stage_name": "Выявление детальных потребностей",
                "stage_score": 1,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "nd_depth",
                        "criterion_name": "Глубина выявления потребности",
                        "score": 1,
                        "max_score": 2,
                    }
                ],
            },
        ]
        artifact.analysis.scores_detail["gaps"] = [
            {
                "criterion_code": "nd_depth",
                "title": "Потребность раскрыта поверхностно",
                "comment": "Потребность клиента раскрыта поверхностно.",
            }
        ]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        stages = {item["stage_code"]: item for item in payload["score_by_stage"]}
        self.assertEqual(
            stages["contact_start"]["problem_summary"],
            "Менеджер не уточнил роль собеседника и масштаб задачи.",
        )
        self.assertEqual(stages["contact_start"]["problem_source"], "criteria_comment")
        self.assertEqual(
            stages["needs_discovery"]["problem_summary"],
            "Потребность клиента раскрыта поверхностно.",
        )
        self.assertEqual(stages["needs_discovery"]["problem_source"], "gap")
        self.assertNotIn("nd_depth", stages["needs_discovery"]["problem_summary"])

    def test_manager_daily_payload_adds_situation_evidence_quote_for_priority_stage(self) -> None:
        artifact = _artifact(50.0, "problematic")
        artifact.analysis.scores_detail["call"]["contact_name"] = "Анжелика"
        artifact.analysis.scores_detail["score_by_stage"] = [
            {
                "stage_code": "contact_start",
                "stage_name": "Первичный контакт",
                "stage_score": 2,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "cs_permission",
                        "criterion_name": "Проверка уместности",
                        "score": 2,
                        "max_score": 2,
                    }
                ],
            },
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "qp_role_scope",
                        "criterion_name": "Роль и масштаб",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Роль собеседника не была уточнена.",
                    }
                ],
            },
        ]
        artifact.analysis.scores_detail["gaps"] = [
            {
                "criterion_code": "qp_role_scope",
                "title": "Роль собеседника не была уточнена",
                "comment": "Роль собеседника не была уточнена.",
            }
        ]
        artifact.analysis.scores_detail["evidence_fragments"] = [
            {
                "criterion_code": "nd_depth",
                "client_text": "У нас несколько филиалов, но пока не понимаю условия.",
                "manager_text": "Расскажу про продукт.",
            },
            {
                "criterion_code": "qp_role_scope",
                "client_text": "Я просто уточняю для руководителя, сама решение не принимаю.",
                "manager_text": "Тогда я вам сейчас расскажу по тарифам.",
            },
        ]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        quote = payload["situation_evidence_quote"]
        self.assertIsNotNone(quote)
        self.assertEqual(quote["source"], "evidence_fragments")
        self.assertEqual(quote["stage_code"], "qualification_primary")
        self.assertEqual(quote["criterion_code"], "qp_role_scope")
        self.assertEqual(quote["client_label"], "Анжелика")
        self.assertIn("сама решение не принимаю", quote["client_text"])
        excerpt = payload["situation_dialogue_excerpt"]
        self.assertIsNotNone(excerpt)
        self.assertEqual(excerpt["source"], "evidence_fragments")
        self.assertTrue(excerpt["is_partial"])
        self.assertEqual(
            excerpt["turns"],
            [
                {"speaker": "manager", "text": "Тогда я вам сейчас расскажу по тарифам."},
                {"speaker": "client", "text": "Я просто уточняю для руководителя, сама решение не принимаю."},
            ],
        )
        deep_dive = payload["focus_stage_deep_dive"]
        self.assertIsNotNone(deep_dive)
        self.assertEqual(deep_dive["stage_code"], "qualification_primary")
        self.assertEqual(deep_dive["stage_name"], "Квалификация и первичная потребность")
        self.assertEqual(deep_dive["what_went_wrong"], "Роль собеседника не была уточнена.")
        self.assertIn("Без понимания роли", deep_dive["why_it_matters"])
        self.assertEqual(
            deep_dive["what_to_fix"],
            "До презентации задать 2–3 уточняющих вопроса и только потом связывать продукт с задачей клиента.",
        )
        self.assertEqual(
            deep_dive["minimum_for_tomorrow"],
            "В каждом подходящем sales-звонке зафиксировать роль собеседника, текущий процесс и следующий шаг.",
        )
        self.assertNotIn("qp_role_scope", " ".join(str(value) for value in deep_dive.values()))
        focus_rec = payload["focus_stage_recommendation"]
        self.assertIsNotNone(focus_rec)
        self.assertEqual(focus_rec["stage_code"], "qualification_primary")
        self.assertEqual(focus_rec["problem"], "Роль собеседника не была уточнена.")
        self.assertEqual(focus_rec["recommendation"], deep_dive["what_to_fix"])
        self.assertEqual(
            focus_rec["checklist"],
            [
                "Уточнить роль собеседника",
                "Понять текущий процесс",
                "Зафиксировать следующий шаг",
            ],
        )
        self.assertEqual(focus_rec["source"], "focus_stage_deep_dive")
        self.assertNotIn("qp_role_scope", " ".join(str(value) for value in focus_rec.values()))
        coaching_view = payload["situation_day_coaching_view"]
        self.assertIsNotNone(coaching_view)
        self.assertEqual(coaching_view["source"], "deterministic_assembly")
        self.assertEqual(coaching_view["stage_code"], "qualification_primary")
        self.assertEqual(coaching_view["stage_label"], "Квалификация и первичная потребность")
        self.assertEqual(coaching_view["stage_score_label"], "0.0/5")
        self.assertEqual(coaching_view["pattern_title"], "Клиент проявил интерес, но квалификация не раскрыта")
        self.assertIn("Клиент сказал", coaching_view["what_happened"])
        self.assertIn("Менеджер не уточнил роль собеседника", coaching_view["what_was_missing"])
        self.assertEqual(coaching_view["meaning"], deep_dive["why_it_matters"])
        self.assertEqual(coaching_view["next_time_action"], deep_dive["what_to_fix"])
        self.assertEqual(
            coaching_view["scripts"],
            [
                "Подскажите, вы сами будете принимать решение по подключению или нужно будет согласовать с руководителем?",
                "Как сейчас у вас проходит работа с документами: бумага, email, WhatsApp или уже есть ЭДО?",
                "Что для вас сейчас важнее: ускорить подписание, навести порядок в документах или снизить риски при проверках?",
            ],
        )
        self.assertNotIn("[конкретная задача клиента]", " ".join(coaching_view["scripts"]))
        self.assertNotIn("qp_role_scope", " ".join(str(value) for value in coaching_view.values()))

    def test_manager_daily_prefers_valid_report_evidence_for_report_blocks(self) -> None:
        artifact = _artifact(64.0, "basic")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["call"]["contact_name"] = "Алия"
        detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "qp_current_process",
                        "criterion_name": "Текущий процесс",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Контекст процесса не уточнён.",
                    }
                ],
            }
        ]
        detail["gaps"] = [{"criterion_code": "qp_current_process", "title": "Legacy gap"}]
        detail.update(_valid_report_evidence_detail())
        detail["report_evidence"]["manager_coaching_moments"][0]["stage_code"] = "qualification_primary"

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        diagnostics = payload["report_evidence_diagnostics"]["summary"]
        self.assertEqual(diagnostics["available_count"], 1)
        self.assertEqual(diagnostics["valid_count"], 1)
        self.assertEqual(diagnostics["semantic_case_available_count"], 0)
        self.assertEqual(diagnostics["semantic_case_valid_count"], 0)
        self.assertEqual(diagnostics["semantic_case_used_count"], 0)
        self.assertEqual(diagnostics["report_evidence_source_counts"]["report_evidence_v1"], 1)
        call_diagnostics = payload["report_evidence_diagnostics"]["calls"][0]
        self.assertFalse(call_diagnostics["semantic_case_available"])
        self.assertFalse(call_diagnostics["semantic_case_valid"])
        self.assertFalse(call_diagnostics["semantic_case_used"])
        self.assertEqual(call_diagnostics["semantic_case_filtered_reason"], "semantic_case_missing")
        self.assertEqual(call_diagnostics["report_evidence_source"], "report_evidence_v1")
        block_diagnostics = payload["report_evidence_diagnostics"]["blocks"]
        self.assertEqual(block_diagnostics["situation_day"]["report_evidence_source"], "report_evidence_v1")
        self.assertEqual(block_diagnostics["call_breakdown"]["report_evidence_source"], "report_evidence_v1")
        self.assertEqual(block_diagnostics["voice_of_customer"]["report_evidence_source"], "report_evidence_v1")
        self.assertIn(
            payload["situation_evidence_quote"]["source"],
            {"report_evidence.situation_candidates", "report_evidence.situation_day_daily_composer.v2"},
        )
        self.assertIn(
            payload["situation_day_coaching_view"]["source"],
            {"report_evidence", "report_evidence.situation_day_daily_composer.v2"},
        )
        self.assertIn(
            payload["situation_day_coaching_view"]["pattern_title"],
            {"Контекст процесса не уточнён", "Не хватило вопроса о текущем документообороте."},
        )
        self.assertIn(
            payload["call_breakdown"]["source_note"],
            {"report_evidence.manager_coaching_moments", "report_evidence.call_breakdown_composer.v2"},
        )
        self.assertTrue(
            "Следующий шаг остался общим" in payload["call_breakdown"]["rows"][0][1]
            or "WhatsApp" in payload["call_breakdown"]["rows"][0][1]
        )
        self.assertIn(
            payload["voice_of_customer"]["source_note"],
            {"report_evidence.voice_of_customer", "report_evidence.voice_of_customer_composer.v2"},
        )
        self.assertEqual(payload["voice_of_customer"]["situations"][0]["quote"], "Скиньте в WhatsApp, я посмотрю.")
        self.assertEqual(payload["additional_situations"]["source_note"], "report_evidence.additional_situations")
        self.assertEqual(payload["call_list"][0]["call_list_topic"], "Клиент попросил материалы в WhatsApp")
        self.assertEqual(
            payload["call_list"][0]["call_list_context"],
            "Клиент готов посмотреть материалы, но срок возврата ещё не зафиксирован.",
        )
        self.assertTrue(payload["voice_of_customer"]["situations"][0]["context"])
        self.assertEqual(payload["call_tomorrow"]["contacts"][0]["source"], "report_evidence.call_report_summary")
        self.assertEqual(
            payload["call_tomorrow"]["contacts"][0]["next_step"],
            "Отправить материалы и согласовать дату следующего контакта.",
        )
        self.assertEqual(
            payload["call_tomorrow"]["contacts"][0]["reason"],
            "Клиент готов посмотреть материалы, но срок возврата ещё не зафиксирован.",
        )
        self.assertIn("call_report_summary_used_count", payload["call_report_summary_diagnostics"]["summary"])

    def test_manager_daily_prefers_semantic_case_for_core_coaching_blocks(self) -> None:
        artifact = _artifact(64.0, "basic")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["call"]["contact_name"] = "Алия"
        detail["score_by_stage"] = [
            {
                "stage_code": "completion_next_step",
                "stage_name": "Завершение и следующий шаг",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "next_step_fixed",
                        "criterion_name": "Фиксация следующего шага",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Менеджер не закрепил срок следующего контакта.",
                    }
                ],
            }
        ]
        detail["gaps"] = [{"criterion_code": "next_step_fixed", "title": "Legacy gap"}]
        detail.update(_valid_report_evidence_detail_with_semantic_case())

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        diagnostics = payload["report_evidence_diagnostics"]
        self.assertEqual(diagnostics["summary"]["semantic_case_available_count"], 1)
        self.assertEqual(diagnostics["summary"]["semantic_case_valid_count"], 1)
        self.assertEqual(diagnostics["summary"]["semantic_case_used_count"], 1)
        self.assertEqual(diagnostics["summary"]["report_evidence_source_counts"]["semantic_case"], 1)
        call_diagnostics = diagnostics["calls"][0]
        self.assertTrue(call_diagnostics["semantic_case_available"])
        self.assertTrue(call_diagnostics["semantic_case_valid"])
        self.assertTrue(call_diagnostics["semantic_case_used"])
        self.assertIsNone(call_diagnostics["semantic_case_filtered_reason"])
        self.assertEqual(call_diagnostics["report_evidence_source"], "semantic_case")
        block_diagnostics = diagnostics["blocks"]
        self.assertTrue(block_diagnostics["situation_day"]["semantic_case_used"])
        self.assertTrue(block_diagnostics["call_breakdown"]["semantic_case_used"])
        self.assertTrue(block_diagnostics["voice_of_customer"]["semantic_case_used"])
        self.assertEqual(block_diagnostics["call_tomorrow"]["report_evidence_source"], "report_evidence_v1")
        self.assertEqual(payload["situation_evidence_quote"]["source"], "report_evidence.semantic_case")
        coaching_view = payload["situation_day_coaching_view"]
        self.assertEqual(coaching_view["source"], "report_evidence.semantic_case")
        self.assertEqual(coaching_view["pattern_title"], "Открытый интерес без срока возврата.")
        self.assertIn("не закрепил дату", coaching_view["meaning"])
        self.assertEqual(payload["call_breakdown"]["source_note"], "report_evidence.semantic_case")
        self.assertEqual(payload["call_breakdown"]["call_breakdown_source"], "report_evidence.semantic_case")
        self.assertTrue(payload["call_breakdown"]["call_breakdown_fragment_present"])
        self.assertIn("не уточнил срок", payload["call_breakdown"]["rows"][0][1])
        self.assertIn("Скиньте в WhatsApp", payload["call_breakdown"]["rows"][0][2])
        self.assertEqual(payload["voice_of_customer"]["source_note"], "report_evidence.semantic_case+voice_of_customer")
        self.assertEqual(payload["voice_of_customer"]["situations"][0]["source"], "report_evidence.semantic_case")
        self.assertIn("Клиент попросил отправить материалы", payload["voice_of_customer"]["situations"][0]["context"])

    def test_manager_daily_prefers_block_candidates_before_semantic_case(self) -> None:
        artifact = _artifact(64.0, "basic")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["call"]["contact_name"] = "Алия"
        detail["score_by_stage"] = [
            {
                "stage_code": "completion_next_step",
                "stage_name": "Завершение и следующий шаг",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "next_step_fixed",
                        "criterion_name": "Фиксация следующего шага",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Менеджер не закрепил срок следующего контакта.",
                    }
                ],
            }
        ]
        detail["gaps"] = [{"criterion_code": "next_step_fixed", "title": "Legacy gap"}]
        evidence_detail = _valid_report_evidence_detail_with_semantic_case()
        evidence_detail["report_evidence"]["block_candidates"] = {
            "situation_day": {
                "fit": True,
                "score": 94,
                "role": "coaching_problem",
                "title_mode": "problem",
                "stage_code": "completion_next_step",
                "main_thesis": "Блок-кандидат: интерес клиента остался без контрольной даты.",
                "what_happened": "Менеджер согласился отправить материалы, но не перевел открытый интерес в срок возврата.",
                "why_it_matters": "Без контрольной даты теплый интерес может зависнуть после отправки материалов.",
                "what_was_missing": "Не было зафиксировано, когда менеджер вернется к обсуждению.",
                "better_next_action": "Сразу согласовать дату следующего касания после отправки материалов.",
                "proof_type": "sequence_inference",
                "proof_explanation": "Вывод основан на последовательности: клиент попросил материалы, менеджер согласился отправить их без даты возврата.",
                "supporting_quote": "Хорошо, отправлю информацию.",
                "quote_role": "supports_context",
                "counter_evidence": [],
            },
            "call_breakdown": {
                "fit": True,
                "score": 91,
                "role": "coaching_problem",
                "title_mode": "problem",
                "stage_code": "completion_next_step",
                "main_thesis": "Разбор глубже: интерес не получил контрольную точку.",
                "what_happened": "Менеджер согласился отправить материалы без даты возврата.",
                "why_it_matters": "Следующий контакт остается на инициативе клиента.",
                "what_was_missing": "Не хватило конкретной даты или времени возврата.",
                "better_next_action": "Предложить конкретный слот для следующего контакта.",
                "proof_type": "sequence_inference",
                "proof_explanation": "В звонке есть запрос материалов и согласие менеджера, но нет фиксации даты следующего касания.",
                "supporting_quote": "Хорошо, отправлю информацию.",
                "quote_role": "supports_context",
                "moments": [
                    {
                        "situation": "Менеджер ответил согласием на отправку материалов.",
                        "essence": "Глубина момента в том, что интерес не получил контрольную точку.",
                        "proof_explanation": "Запрос материалов завершился согласием менеджера без даты возврата.",
                        "better_action": "Сразу предложить дату возврата к обсуждению.",
                        "proof_type": "sequence_inference",
                        "supporting_quote": "Хорошо, отправлю информацию.",
                        "quote_role": "supports_context",
                    }
                ],
            },
        }
        detail.update(evidence_detail)

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        diagnostics = payload["report_evidence_diagnostics"]
        self.assertEqual(diagnostics["summary"]["block_candidates_available_count"], 1)
        self.assertEqual(diagnostics["summary"]["block_candidates_valid_count"], 1)
        self.assertEqual(diagnostics["summary"]["report_evidence_source_counts"]["block_candidates"], 1)
        block_diagnostics = diagnostics["blocks"]
        self.assertEqual(block_diagnostics["situation_day"]["report_evidence_source"], "block_candidates")
        self.assertEqual(block_diagnostics["call_breakdown"]["report_evidence_source"], "block_candidates")
        self.assertFalse(block_diagnostics["situation_day"]["semantic_case_used"])
        self.assertFalse(block_diagnostics["call_breakdown"]["semantic_case_used"])
        coaching_view = payload["situation_day_coaching_view"]
        self.assertEqual(coaching_view["source"], "report_evidence.block_candidates.situation_day")
        self.assertIn("Блок-кандидат", coaching_view["pattern_title"])
        self.assertEqual(coaching_view["proof_type"], "sequence_inference")
        self.assertEqual(
            payload["daily_coaching_focus"]["problem_statement"],
            "Не было зафиксировано, когда менеджер вернется к обсуждению.",
        )
        self.assertEqual(
            payload["daily_coaching_focus"]["problem_statement_source"],
            "situation_day_selected_case",
        )
        breakdown = payload["call_breakdown"]
        self.assertEqual(breakdown["call_breakdown_source"], "report_evidence.block_candidates.call_breakdown")
        self.assertEqual(breakdown["proof_type"], "sequence_inference")
        self.assertIn("контрольную точку", breakdown["rows"][0][2])
        self.assertNotIn("не уточнил срок", breakdown["rows"][0][1])

    def test_manager_daily_situation_day_block_candidate_focus_override_happens_before_deep_dive(self) -> None:
        artifact = _artifact(64.0, "basic")
        artifact.interaction.text = (
            "Клиент: У нас сейчас всё на бумаге. "
            "Менеджер: Может, я вам скину информацию о нашем продукте."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["score_by_stage"] = [
            {
                "stage_code": "completion_next_step",
                "stage_name": "Завершение и договорённости",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "ns_next_step_fixed",
                        "criterion_name": "Фиксация следующего шага",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Следующий шаг не был закреплён достаточно конкретно.",
                    }
                ],
            },
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 1,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "qp_need_or_trigger",
                        "criterion_name": "Потребность клиента",
                        "score": 1,
                        "max_score": 2,
                        "comment": "Часть контекста клиента была раскрыта.",
                    }
                ],
            },
        ]
        detail["gaps"] = [{"criterion_code": "ns_next_step_fixed", "title": "Legacy next step gap"}]
        evidence_detail = _valid_report_evidence_detail()
        evidence_detail["report_evidence"]["follow_up_candidates"][0]["client_label"] = None
        evidence_detail["report_evidence"]["block_candidates"] = {
            "situation_day": {
                "fit": True,
                "score": 92,
                "role": "coaching_problem",
                "title_mode": "problem",
                "stage_code": "qualification_primary",
                "main_thesis": "Менеджер предложил продукт до выяснения задачи клиента.",
                "what_happened": "Менеджер перешёл к отправке материалов до фиксации задачи клиента.",
                "why_it_matters": "Без понимания задачи предложение может не попасть в реальный контекст клиента.",
                "what_was_missing": "Не было зафиксировано, какую задачу клиент хочет решить.",
                "better_next_action": "Сначала уточнить задачу клиента, затем предлагать материал.",
                "proof_type": "sequence_inference",
                "proof_explanation": "Сначала клиент описал бумажный процесс, затем менеджер сразу предложил отправить продукт без уточнения задачи.",
                "supporting_quote": "Может, я вам скину информацию о нашем продукте.",
                "quote_role": "supports_context",
                "counter_evidence": [],
            }
        }
        detail.update(evidence_detail)

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}

        diagnostics = payload["report_evidence_diagnostics"]
        self.assertFalse(diagnostics["calls"][0]["report_evidence_valid"])
        self.assertEqual(diagnostics["blocks"]["situation_day"]["report_evidence_source"], "block_candidates")
        coaching_view = payload["situation_day_coaching_view"]
        self.assertEqual(coaching_view["source"], "report_evidence.block_candidates.situation_day")
        self.assertEqual(coaching_view["stage_code"], "qualification_primary")
        self.assertEqual(
            coaching_view["selection_diagnostics"]["selection_mode"],
            "best_block_candidate_after_focus_mismatch",
        )
        self.assertEqual(payload["daily_coaching_focus"]["stage_code"], "qualification_primary")
        self.assertEqual(
            payload["daily_coaching_focus"]["focus_override_reason"],
            "best_block_candidate_after_focus_mismatch",
        )
        self.assertEqual(payload["focus_stage_deep_dive"]["stage_code"], "qualification_primary")
        self.assertEqual(sections["challenge"]["focus_stage_code"], "qualification_primary")
        self.assertEqual(sections["main_focus_for_tomorrow"]["focus_stage_code"], "qualification_primary")
        self.assertNotIn(
            "situation_stage_mismatch:qualification_primary",
            payload["daily_coaching_focus_validation"]["issues"],
        )

    def test_manager_daily_semantic_coaching_moment_does_not_require_fragment(self) -> None:
        artifact = _artifact(64.0, "basic")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["call"]["contact_name"] = "Алия"
        detail["score_by_stage"] = [
            {
                "stage_code": "completion_next_step",
                "stage_name": "Завершение и следующий шаг",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "next_step_fixed",
                        "criterion_name": "Фиксация следующего шага",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Менеджер не закрепил срок следующего контакта.",
                    }
                ],
            }
        ]
        detail["gaps"] = [{"criterion_code": "next_step_fixed", "title": "Legacy gap"}]
        evidence_detail = _valid_report_evidence_detail_with_semantic_case()
        semantic_case = evidence_detail["report_evidence"]["semantic_case"]
        semantic_case["best_dialogue_fragment"] = []
        coaching_moment = {
            "summary": (
                "Менеджер завершил звонок отправкой материалов, "
                "но не перевёл интерес клиента в дату возврата."
            ),
            "missing_action": (
                "Не хватило конкретного срока следующего контакта "
                "после отправки материалов."
            ),
            "why_it_matters": (
                "Без срока возврата открытый интерес легко зависает "
                "и не превращается в следующий шаг."
            ),
            "supporting_quote": None,
            "evidence_type": "absence_in_context",
            "confidence": "high",
        }
        for block_name in ("situation_day", "call_breakdown", "additional_situations"):
            semantic_case["report_block_fit"][block_name]["coaching_moment"] = dict(coaching_moment)
        detail.update(evidence_detail)

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        coaching_view = payload["situation_day_coaching_view"]
        self.assertEqual(coaching_view["source"], "report_evidence.semantic_case")
        self.assertEqual(coaching_view["moment_summary"], coaching_moment["summary"])
        self.assertEqual(coaching_view["supporting_quote"], None)
        self.assertEqual(coaching_view["evidence_type"], "absence_in_context")
        self.assertEqual(payload["call_breakdown"]["source_note"], "report_evidence.semantic_case")
        self.assertFalse(payload["call_breakdown"]["call_breakdown_fragment_present"])
        self.assertEqual(payload["call_breakdown"]["moment_summary"], coaching_moment["summary"])
        self.assertEqual(payload["call_breakdown"]["rows"][0][2], coaching_moment["summary"])
        self.assertEqual(payload["call_breakdown"]["supporting_quote"], None)
        self.assertEqual(payload["call_breakdown_quality"]["status"], "passed")
        self.assertEqual(
            payload["call_breakdown_quality"]["rendered_rows"][0]["quote_optional"],
            True,
        )
        self.assertIn("additional_situations", payload)
        self.assertEqual(payload["voice_of_customer"]["source_note"], "report_evidence.voice_of_customer")

    def test_manager_daily_situation_day_rejects_problem_signal_mismatch(self) -> None:
        manager = _manager()
        aligned_artifact = _artifact_for_manager(
            manager,
            score_percent=64.0,
            level="basic",
            call_date="2026-03-25 10:00:00",
        )
        aligned_artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию."
        )
        aligned_detail = aligned_artifact.analysis.scores_detail
        aligned_detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        aligned_detail["score_by_stage"] = [
            {
                "stage_code": "completion_next_step",
                "stage_name": "Завершение и следующий шаг",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "next_step_fixed",
                        "criterion_name": "Фиксация следующего шага",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Менеджер не закрепил срок следующего контакта.",
                    }
                ],
            }
        ]
        aligned_detail["gaps"] = [{"criterion_code": "next_step_fixed", "title": "Legacy gap"}]
        aligned_detail.update(_valid_report_evidence_detail_with_semantic_case())

        mismatch_artifact = _artifact_for_manager(
            manager,
            score_percent=63.0,
            level="basic",
            call_date="2026-03-25 11:00:00",
        )
        mismatch_artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию. "
            "Менеджер: Какие задачи хотите решить?"
        )
        mismatch_detail = mismatch_artifact.analysis.scores_detail
        mismatch_detail["classification"] = aligned_detail["classification"]
        mismatch_detail["score_by_stage"] = aligned_detail["score_by_stage"]
        mismatch_detail["gaps"] = [{"criterion_code": "next_step_fixed", "title": "Legacy gap"}]
        mismatch_evidence = json.loads(json.dumps(_valid_report_evidence_detail_with_semantic_case()))
        semantic_case = mismatch_evidence["report_evidence"]["semantic_case"]
        semantic_case.update(
            {
                "case_title": "Потребности клиента не раскрыты перед отправкой материалов",
                "core_meaning": "Менеджеру нужно глубже понять задачи клиента перед отправкой материалов.",
                "why_this_call_matters": "Без понимания задач предложение может остаться слишком общим.",
                "customer_signal": "Клиент готов посмотреть материалы, но не объяснил задачи.",
                "manager_behavior": "Менеджер начал уточнять задачи клиента перед отправкой информации.",
                "coaching_diagnosis": "Не хватило детального выявления потребностей клиента.",
                "recommended_next_action": "Уточнить задачи клиента и текущий процесс перед предложением продукта.",
                "best_dialogue_fragment": [
                    {
                        "speaker": "client",
                        "text": "Скиньте в WhatsApp, я посмотрю.",
                        "timestamp_start": None,
                        "timestamp_end": None,
                    },
                    {
                        "speaker": "manager",
                        "text": "Какие задачи хотите решить?",
                        "timestamp_start": None,
                        "timestamp_end": None,
                    },
                ],
            }
        )
        semantic_case["report_block_fit"]["situation_day"]["problem_fit"] = {
            "score": 90,
            "problem_signal": "Не выявлены потребности и задачи клиента",
            "explanation": "Кейс относится к выявлению потребностей перед предложением продукта.",
        }
        mismatch_detail.update(mismatch_evidence)

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[mismatch_artifact, aligned_artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        self.assertEqual(payload["situation_evidence_quote"]["call_id"], str(aligned_artifact.interaction.id))
        situation_diagnostics = payload["report_evidence_diagnostics"]["blocks"]["situation_day"][
            "selection_diagnostics"
        ]
        rejected_reasons = {
            item["rejection_reason"]
            for item in situation_diagnostics["rejected_candidates"]
        }
        self.assertIn("problem_signal_mismatch", rejected_reasons)

    def test_report_layer_situation_day_rejects_counter_evidence_proof_quote(self) -> None:
        quote = "А вы, Жанар, может быть, кем являетесь в компании?"
        semantic_case = _valid_semantic_case()
        semantic_case.update(
            {
                "case_title": "Роль клиента не уточнена",
                "core_meaning": "Клиент готов смотреть материалы, но роль клиента якобы не выяснена.",
                "manager_behavior": "Менеджер якобы не уточнил роль клиента.",
                "coaching_diagnosis": "Нужно уточнять роль клиента в компании.",
                "best_dialogue_fragment": [
                    {
                        "speaker": "manager",
                        "text": quote,
                        "timestamp_start": None,
                        "timestamp_end": None,
                    }
                ],
            }
        )
        semantic_case["report_block_fit"]["situation_day"]["coaching_moment"] = {
            "summary": "Менеджер не выяснил роль клиента в компании.",
            "missing_action": "Нужно было уточнить роль клиента и кто принимает решение.",
            "why_it_matters": "Без роли клиента сложно понять, с кем согласовывать следующий шаг.",
            "supporting_quote": quote,
            "evidence_type": "direct_quote",
            "confidence": "high",
            "gap_claim": "Менеджер не уточнил роль клиента и ЛПР.",
            "proof_type": "direct_gap",
            "proof_explanation": "Цитата ошибочно выбрана как доказательство отсутствия уточнения роли.",
            "quote_role": "proves_gap",
            "counter_evidence": [],
        }

        reason = _semantic_case_block_rejection_reason(
            semantic_case=semantic_case,
            turns=[{"speaker": "manager", "text": quote}],
            block_name="situation_day",
            focus_stage_code=None,
            daily_focus=None,
        )

        self.assertEqual(reason, "proof_quote_looks_like_counter_evidence")

    def test_manager_daily_situation_day_rejects_counter_evidence_proof_quote(self) -> None:
        manager = _manager()
        fallback_artifact = _artifact_for_manager(
            manager,
            score_percent=64.0,
            level="basic",
            call_date="2026-03-25 10:00:00",
        )
        fallback_artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию."
        )
        fallback_detail = fallback_artifact.analysis.scores_detail
        fallback_detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        fallback_detail["score_by_stage"] = [
            {
                "stage_code": "completion_next_step",
                "stage_name": "Завершение и следующий шаг",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "next_step_fixed",
                        "criterion_name": "Фиксация следующего шага",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Менеджер не закрепил срок следующего контакта.",
                    }
                ],
            }
        ]
        fallback_detail["gaps"] = [{"criterion_code": "next_step_fixed", "title": "Legacy gap"}]
        fallback_detail.update(_valid_report_evidence_detail_with_semantic_case())

        proof_artifact = _artifact_for_manager(
            manager,
            score_percent=63.0,
            level="basic",
            call_date="2026-03-25 11:00:00",
        )
        quote = "А вы, Жанар, может быть, кем являетесь в компании?"
        proof_artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            f"Менеджер: {quote}"
        )
        proof_detail = proof_artifact.analysis.scores_detail
        proof_detail["classification"] = fallback_detail["classification"]
        proof_detail["score_by_stage"] = fallback_detail["score_by_stage"]
        proof_detail["gaps"] = [{"criterion_code": "next_step_fixed", "title": "Legacy gap"}]
        proof_evidence = json.loads(json.dumps(_valid_report_evidence_detail_with_semantic_case()))
        semantic_case = proof_evidence["report_evidence"]["semantic_case"]
        semantic_case.update(
            {
                "case_title": "Роль клиента не уточнена",
                "core_meaning": "Клиент готов смотреть материалы, но роль клиента якобы не выяснена.",
                "why_this_call_matters": "Без роли клиента менеджер не понимает, кто влияет на решение.",
                "customer_signal": "Клиент готов посмотреть материалы.",
                "manager_behavior": "Менеджер якобы не уточнил роль клиента.",
                "coaching_diagnosis": "Нужно уточнять роль клиента в компании.",
                "recommended_next_action": "Уточните роль клиента и кто принимает решение.",
                "best_dialogue_fragment": [
                    {
                        "speaker": "manager",
                        "text": quote,
                        "timestamp_start": None,
                        "timestamp_end": None,
                    }
                ],
            }
        )
        semantic_case["report_block_fit"]["situation_day"]["score"] = 98
        semantic_case["report_block_fit"]["situation_day"]["problem_fit"] = {
            "score": 98,
            "problem_signal": "Роль клиента не уточнена",
            "explanation": "Кейс ошибочно считает, что менеджер не уточнил роль клиента.",
        }
        semantic_case["report_block_fit"]["situation_day"]["coaching_moment"] = {
            "summary": "Менеджер не выяснил роль клиента в компании.",
            "missing_action": "Нужно было уточнить роль клиента и кто принимает решение.",
            "why_it_matters": "Без роли клиента сложно понять, с кем согласовывать следующий шаг.",
            "supporting_quote": quote,
            "evidence_type": "direct_quote",
            "confidence": "high",
            "gap_claim": "Менеджер не уточнил роль клиента и ЛПР.",
            "proof_type": "direct_gap",
            "proof_explanation": "Цитата ошибочно выбрана как доказательство отсутствия уточнения роли.",
            "quote_role": "proves_gap",
            "counter_evidence": [],
        }
        proof_detail.update(proof_evidence)

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[proof_artifact, fallback_artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        self.assertEqual(payload["situation_evidence_quote"]["call_id"], str(fallback_artifact.interaction.id))
        proof_call_diagnostics = next(
            item
            for item in payload["report_evidence_diagnostics"]["calls"]
            if item["interaction_id"] == str(proof_artifact.interaction.id)
        )
        error_codes = {
            item["code"]
            for item in proof_call_diagnostics["report_evidence_errors"]
        }
        self.assertFalse(proof_call_diagnostics["report_evidence_valid"])
        self.assertIn("coaching_moment_proof_conflict", error_codes)

    def test_manager_daily_block_fit_rejects_customer_signal_as_problem_situation(self) -> None:
        manager = _manager()
        good_artifact = _artifact_for_manager(manager, score_percent=64.0, level="basic", call_date="2026-03-25 10:00:00")
        good_artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию."
        )
        good_detail = good_artifact.analysis.scores_detail
        good_detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        good_detail["score_by_stage"] = [
            {
                "stage_code": "completion_next_step",
                "stage_name": "Завершение и следующий шаг",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "next_step_fixed",
                        "criterion_name": "Фиксация следующего шага",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Менеджер не закрепил срок следующего контакта.",
                    }
                ],
            }
        ]
        good_detail["gaps"] = [{"criterion_code": "next_step_fixed", "title": "Legacy gap"}]
        good_detail.update(_valid_report_evidence_detail_with_semantic_case())

        weak_artifact = _artifact_for_manager(manager, score_percent=25.0, level="basic", call_date="2026-03-25 11:00:00")
        weak_artifact.interaction.text = (
            "Клиент: Оба счета скиньте, пожалуйста, Тулеген. "
            "Менеджер: Хорошо, отправлю два счета."
        )
        weak_detail = weak_artifact.analysis.scores_detail
        weak_detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "warm_webinar_or_lead",
            "analysis_eligibility": "eligible",
        }
        weak_detail["score_by_stage"] = [
            {
                "stage_code": "completion_next_step",
                "stage_name": "Завершение и следующий шаг",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "next_step_fixed",
                        "criterion_name": "Фиксация следующего шага",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Подытоживание договорённости отсутствует.",
                    }
                ],
            }
        ]
        weak_detail["gaps"] = [{"criterion_code": "next_step_fixed", "title": "Legacy gap"}]
        weak_detail.update(
            {
                "report_evidence_version": "v1",
                "report_evidence": {
                    "business_outcome": {
                        "status": "open",
                        "confidence": "high",
                        "reason": "Клиент попросил отправить два счета.",
                        "evidence_quote": "Оба счета скиньте, пожалуйста, Тулеген.",
                        "evidence_speaker": "client",
                        "needs_human_review": False,
                    },
                    "call_report_summary": {
                        "short_topic": "Клиент попросил два счета",
                        "short_context": "Клиент запросил два варианта счета для рассмотрения.",
                        "client_display_name": None,
                        "client_name_confidence": None,
                        "hotness": "warm",
                        "hotness_reason": "Есть запрос на счета, но это ещё не управленческий разбор.",
                        "manager_next_action": "Отправить два счета и уточнить срок обратной связи.",
                        "suggested_manager_phrase": "Добрый день. Отправляю два счета, как договорились. Когда удобно сверить следующий шаг?",
                    },
                    "semantic_case": {
                        "case_title": "Клиент попросил отправить два счета",
                        "case_type": "customer_signal",
                        "stage_code": "completion_next_step",
                        "priority": "medium",
                        "evidence_quality": "direct",
                        "core_meaning": "Клиент хочет получить два варианта счета для рассмотрения.",
                        "why_this_call_matters": "Запрос счета показывает коммерческий интерес и требует своевременного follow-up.",
                        "customer_signal": "Клиент прямо попросил отправить два счета.",
                        "manager_behavior": "Менеджер согласился отправить счета.",
                        "coaching_diagnosis": "Менеджер правильно отреагировал на запрос клиента.",
                        "recommended_next_action": "Отправить два счета и уточнить, когда клиент сможет обсудить детали.",
                        "best_dialogue_fragment": [
                            {
                                "speaker": "client",
                                "text": "Оба счета скиньте, пожалуйста, Тулеген.",
                                "timestamp_start": None,
                                "timestamp_end": None,
                            }
                        ],
                        "report_block_fit": {
                            "situation_day": {
                                "fit": False,
                                "score": 20,
                                "reason_code": "customer_signal_without_manager_gap",
                                "evidence_type": "customer_signal",
                            },
                            "call_breakdown": {
                                "fit": False,
                                "score": 35,
                                "reason_code": "positive_diagnosis_not_problem_case",
                                "evidence_type": "customer_signal",
                            },
                            "voice_of_customer": {
                                "fit": True,
                                "score": 90,
                                "reason_code": "direct_customer_signal",
                                "evidence_type": "customer_signal",
                            },
                            "additional_situations": {
                                "fit": False,
                                "score": 40,
                                "reason_code": "not_relevant_for_block",
                                "evidence_type": "customer_signal",
                            },
                            "call_tomorrow": {
                                "fit": True,
                                "score": 80,
                                "reason_code": "client_requested_next_action",
                                "evidence_type": "follow_up",
                            },
                        },
                        "usable_in_report": True,
                    },
                    "situation_candidates": [],
                    "manager_coaching_moments": [],
                    "voice_of_customer": [],
                    "additional_situations": [],
                    "follow_up_candidates": [],
                    "quote_bank": [],
                },
            }
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[good_artifact, weak_artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        self.assertEqual(payload["situation_evidence_quote"]["call_id"], str(good_artifact.interaction.id))
        self.assertEqual(payload["call_breakdown"]["call_id"], str(good_artifact.interaction.id))
        voice_quotes = [item["quote"] for item in payload["voice_of_customer"]["situations"]]
        self.assertIn("Оба счета скиньте, пожалуйста, Тулеген.", voice_quotes)
        situation_diagnostics = payload["report_evidence_diagnostics"]["blocks"]["situation_day"][
            "selection_diagnostics"
        ]
        rejected_reasons = {
            item["rejection_reason"]
            for item in situation_diagnostics["rejected_candidates"]
        }
        self.assertIn("customer_signal_without_manager_gap", rejected_reasons)

    def test_call_breakdown_prefers_report_evidence_moment_with_fragment(self) -> None:
        artifact = _artifact(70.0, "basic")
        artifact.interaction.text = (
            "Менеджер начал с общего вопроса. "
            "Скиньте в WhatsApp, я посмотрю. "
            "Хорошо, отправлю информацию. "
            "Клиент попросил коммерческое предложение в WhatsApp."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["gaps"] = [{"criterion_code": "qp_current_process", "title": "Legacy gap"}]
        evidence_detail = _valid_report_evidence_detail()
        evidence_detail["report_evidence"]["manager_coaching_moments"] = [
            {
                "stage_code": "completion_next_step",
                "moment_type": "missed",
                "priority": "high",
                "evidence_quality": "direct",
                "dialogue_fragment": [],
                "what_happened": "Следующий шаг описан общо.",
                "what_better": "Зафиксировать срок возврата.",
                "usable_in_report": True,
            },
            {
                "stage_code": "qualification_primary",
                "moment_type": "missed",
                "priority": "low",
                "evidence_quality": "direct",
                "dialogue_fragment": [
                    {
                        "speaker": "client",
                        "text": "Клиент попросил коммерческое предложение в WhatsApp.",
                    }
                ],
                "what_happened": "Клиент попросил КП, но срок обсуждения не был закреплён.",
                "what_better": "Отправить КП и сразу согласовать дату возврата к обсуждению.",
                "usable_in_report": True,
            },
        ]
        detail.update(evidence_detail)

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        breakdown = payload["call_breakdown"]
        self.assertIn(
            breakdown["source_note"],
            {"report_evidence.manager_coaching_moments", "report_evidence.call_breakdown_composer.v2"},
        )
        self.assertTrue(breakdown["call_breakdown_fragment_present"])
        self.assertEqual(breakdown["call_breakdown_evidence_strength"], "strong")
        self.assertIn("коммерческое предложение", breakdown["rows"][0][1])
        self.assertIn("коммерческое предложение", breakdown["rows"][0][2])
        self.assertNotEqual(breakdown["rows"][0][2], "—")

    def test_situation_client_reaction_prefers_client_grounded_evidence(self) -> None:
        artifact = _artifact(64.0, "basic")
        client_quote = "Лучше напишите в WhatsApp, я не отвечаю на незнакомые звонки."
        manager_fragment = "Скажите, пожалуйста, насколько актуален вопрос сейчас?"
        evidence = {
            "situation_candidates": [
                {
                    "stage_code": "contact_start",
                    "situation_title": "Не адаптировался к ответу клиента",
                    "priority": "high",
                    "evidence_quality": "direct",
                    "dialogue_fragment": [
                        {
                            "speaker": "manager",
                            "text": manager_fragment,
                            "timestamp_start": None,
                            "timestamp_end": None,
                        }
                    ],
                    "what_happened": "Менеджер не адаптировался к ответу клиента о возможности говорить.",
                    "what_it_means": "Клиентский барьер может сорвать продолжение.",
                    "what_was_missing": "Не хватило фиксации удобного канала связи.",
                    "next_time_action": "Закрепить безопасный канал продолжения.",
                    "usable_in_report": True,
                }
            ],
            "voice_of_customer": [
                {
                    "quote": client_quote,
                    "speaker": "client",
                    "topic": "risk",
                    "meaning": "Клиент обозначил барьер доверия к незнакомому звонку.",
                    "business_signal": "medium",
                    "stage_code": "contact_start",
                    "usable_in_report": True,
                }
            ],
        }

        result = _build_report_evidence_situation(
            artifacts=[artifact],
            report_evidence_index={
                str(artifact.interaction.id): {
                    "report_evidence_available": True,
                    "report_evidence_valid": True,
                    "report_evidence": evidence,
                }
            },
            call_list_by_interaction_id={str(artifact.interaction.id): {"status": "open"}},
            score_by_stage=[
                {
                    "stage_code": "contact_start",
                    "stage_name": "Начало контакта",
                    "score": 4,
                    "is_priority": True,
                }
            ],
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["evidence_quote"]["client_text"], client_quote)
        self.assertEqual(result["evidence_quote"]["source"], "report_evidence.client_grounded_situation")
        self.assertTrue(result["evidence_quote"]["client_grounded"])
        self.assertNotEqual(result["evidence_quote"]["client_text"], manager_fragment)
        self.assertEqual(result["dialogue_excerpt"]["turns"][0]["speaker"], "client")
        self.assertEqual(result["dialogue_excerpt"]["source"], "report_evidence.voice_of_customer")
        self.assertEqual(result["coaching_view"]["source"], "report_evidence.client_grounded_situation")
        self.assertIn("довер", result["coaching_view"]["what_happened"].lower())
        self.assertIn("безопас", result["coaching_view"]["next_time_action"].lower())

    def test_voice_of_customer_manager_action_is_signal_specific(self) -> None:
        cases = [
            (
                "Я посоветуюсь с руководителем и перезвоню.",
                "timing",
                "Client needs an internal discussion before a decision.",
                "Ожидать звонка клиента.",
                "с кем клиент будет обсуждать",
                "Ожидать звонка клиента",
            ),
            (
                "Нам текущей системы достаточно.",
                "process",
                "Client says the current setup covers the need.",
                None,
                "что именно закрывает текущее решение",
                "уточнить задачу клиента",
            ),
            (
                "Напишите в WhatsApp, я не отвечаю на незнакомые звонки.",
                "risk",
                "Client has a trust barrier around unknown calls.",
                None,
                "безопасный канал",
                "уточнить задачу клиента",
            ),
            (
                "Скиньте КП в WhatsApp, я посмотрю.",
                "product_interest",
                "Client asked for proposal materials.",
                "Отправить КП и завтра уточнить, появились ли вопросы.",
                "перед отправкой КП уточнить объем",
                "безопасный канал",
            ),
        ]
        for quote, topic, meaning, summary_action, expected, forbidden in cases:
            with self.subTest(topic=topic):
                artifact = _artifact(64.0, "basic")
                artifact.interaction.text = (
                    "Клиент: Скиньте в WhatsApp, я посмотрю. "
                    f"Клиент: {quote} "
                    "Менеджер: Хорошо, отправлю информацию."
                )
                detail = artifact.analysis.scores_detail
                detail["classification"] = {
                    "call_type": "sales_primary",
                    "scenario_type": "cold_outbound",
                    "analysis_eligibility": "eligible",
                }
                detail.update(_valid_report_evidence_detail())
                detail["report_evidence"]["voice_of_customer"][0].update(
                    {
                        "quote": quote,
                        "topic": topic,
                        "meaning": meaning,
                        "business_signal": "medium",
                    }
                )
                if summary_action is not None:
                    detail["report_evidence"]["call_report_summary"]["manager_next_action"] = summary_action

                payload = build_manager_daily_payload(
                    department_id=str(uuid4()),
                    department_name="Отдел продаж",
                    artifacts=[artifact],
                    period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
                    filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
                    mode="report_from_ready_data_only",
                    model_override=None,
                )
                row = {
                    section["id"]: section
                    for section in build_report_render_model(payload)["sections"]
                }["voice_of_customer"]["rows"][0]

                self.assertIn(quote, row[1])
                self.assertIn("Клиент:", row[1])
                self.assertIn(expected, row[2])
                self.assertNotIn(forbidden, row[2])

    def test_voice_of_customer_legacy_fallback_uses_customer_signal_action(self) -> None:
        artifact = _artifact(64.0, "basic")
        artifact.interaction.text = "Клиент: Нам текущей системы достаточно. Менеджер: Понял."
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail.pop("report_evidence", None)
        detail.pop("report_evidence_version", None)
        detail["product_signals"] = [
            {
                "quote": "Нам текущей системы достаточно.",
                "topic": "process",
            }
        ]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        row = {
            section["id"]: section
            for section in build_report_render_model(payload)["sections"]
        }["voice_of_customer"]["rows"][0]

        self.assertIn("Нам текущей системы достаточно.", row[1])
        self.assertIn("Клиент:", row[1])
        self.assertIn("текущ", row[2].lower())
        self.assertRegex(row[2].lower(), r"ручн|риск|закрывает")
        self.assertNotIn("уточнить задачу клиента", row[2])

    def test_step8ah1_unified_client_call_reference_in_manager_daily_blocks(self) -> None:
        artifact = _artifact(64.0, "basic", call_date="2026-05-04 11:46:00")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию."
        )
        artifact.interaction.metadata_["contact_name"] = "Нур-Султан"
        artifact.interaction.metadata_["contact_phone"] = "+77071523663"
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["call"] = {"contact_name": "Нур-Султан", "contact_phone": "+77071523663"}
        detail.update(_valid_report_evidence_detail())

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        report = build_report_render_model(payload)
        sections = {section["id"]: section for section in report["sections"]}
        expected = "Нур-Султан · +77071523663 · 4 мая 2026, 11:46"

        self.assertEqual(payload["call_list"][0]["client_call_reference"], expected)
        self.assertEqual(payload["call_breakdown"]["client_call_reference"], expected)
        self.assertEqual(payload["voice_of_customer"]["situations"][0]["client_call_reference"], expected)
        self.assertEqual(payload["call_tomorrow"]["contacts"][0]["client_call_reference"], expected)
        self.assertEqual(sections["call_list"]["rows"][0][1], expected)
        self.assertEqual(sections["call_tomorrow"]["rows"][0][1], expected)
        self.assertEqual(sections["call_breakdown"]["summary_line"], expected)
        self.assertIn(expected, sections["voice_of_customer"]["rows"][0][0])
        self.assertNotIn("+77071523663 · +77071523663", expected)

        self.assertEqual(sections["call_breakdown"]["rows"][0][0], "Момент 1")
        self.assertEqual(len(sections["call_breakdown"]["rows"][0]), 4)
        self.assertTrue(sections["call_tomorrow"]["rows"][0][2].startswith(("Повод:", "Срок:", "Контекст:")))
        self.assertIn("Можно начать:", sections["call_tomorrow"]["rows"][0][3])
        self.assertEqual(sections["call_list"]["columns"], ["#", "Клиент", "Тип / суть", "Контекст", "Статус"])

    def test_step8ah1_uses_safe_persisted_transcript_name_when_metadata_name_missing(self) -> None:
        artifact = _artifact(64.0, "basic", call_date="2026-05-04 11:46:00")
        artifact.interaction.text = "Как могу к вам обращаться? Нур-Султан. Нур-Султан, приятно познакомиться."
        artifact.interaction.metadata_.pop("contact_name", None)
        artifact.interaction.metadata_["contact_phone"] = "+77071523663"
        artifact.interaction.metadata_["segments"] = [
            {"speaker": "A", "text": "А как могу к вам обращаться?"},
            {"speaker": "B", "text": "Нур-Султан."},
        ]
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["call"] = {"contact_name": None, "contact_phone": "+77071523663"}
        detail.update(_valid_report_evidence_detail())

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        self.assertEqual(
            payload["call_list"][0]["client_call_reference"],
            "Нур-Султан · +77071523663 · 4 мая 2026, 11:46",
        )

    def test_step8ah8b_rejects_unsafe_client_display_name(self) -> None:
        """Step 8AH-8B: unsafe extracted names fall back to phone/date in unified references."""
        artifact = _artifact(64.0, "basic", call_date="2026-05-04 06:37:00")
        artifact.interaction.text = "Как могу к вам обращаться? Ужас. Менеджер продолжил звонок."
        artifact.interaction.metadata_["contact_name"] = "Ужас"
        artifact.interaction.metadata_["contact_phone"] = "+77774745093"
        artifact.interaction.metadata_["segments"] = [
            {"speaker": "A", "text": "Как могу к вам обращаться?"},
            {"speaker": "B", "text": "Ужас."},
        ]
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["call"] = {"contact_name": "Ужас", "contact_phone": "+77774745093"}
        detail.update(_valid_report_evidence_detail())

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        expected = "+77774745093 · 4 мая 2026, 06:37"
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["call_list"][0]["client_call_reference"], expected)
        self.assertEqual(payload["call_list"][0]["client_name"], None)
        self.assertNotIn("Ужас · +77774745093", rendered)

    def test_step8ah8b_keeps_safe_client_display_names(self) -> None:
        """Step 8AH-8B: valid persisted names continue to render in unified references."""
        safe_names = ["Надежда Анатольевна", "Агирим", "Акмарал", "Екатерина", "Максим", "Нур-Султан"]
        for name in safe_names:
            with self.subTest(name=name):
                artifact = _artifact(64.0, "basic", call_date="2026-05-04 11:46:00")
                artifact.interaction.metadata_["contact_name"] = name
                artifact.interaction.metadata_["contact_phone"] = "+77071523663"
                detail = artifact.analysis.scores_detail
                detail["classification"] = {
                    "call_type": "sales_primary",
                    "scenario_type": "cold_outbound",
                    "analysis_eligibility": "eligible",
                }
                detail["call"] = {"contact_name": name, "contact_phone": "+77071523663"}
                detail["follow_up"] = {"next_step_fixed": True, "next_step_text": "Отправить информацию."}

                payload = build_manager_daily_payload(
                    department_id=str(uuid4()),
                    department_name="Отдел продаж",
                    artifacts=[artifact],
                    period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
                    filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
                    mode="report_from_ready_data_only",
                    model_override=None,
                )

                self.assertEqual(
                    payload["call_list"][0]["client_call_reference"],
                    f"{name} · +77071523663 · 4 мая 2026, 11:46",
                )

    def test_step8ah3_call_tomorrow_uses_hotness_not_final_open_label(self) -> None:
        def contact(name: str, text: str, follow_up: dict[str, Any], call_date: str) -> ReportArtifact:
            artifact = _artifact(70.0, "basic", call_date=call_date)
            artifact.interaction.text = text
            artifact.interaction.metadata_["contact_name"] = name
            detail = artifact.analysis.scores_detail
            detail["call"] = {"contact_name": name, "contact_phone": "+77070000000"}
            detail["classification"] = {
                "call_type": "sales_primary",
                "scenario_type": "cold_outbound",
                "analysis_eligibility": "eligible",
            }
            detail["follow_up"] = follow_up
            return artifact

        agreed = contact(
            "Счет клиент",
            "Клиент согласился: выставляйте счет сегодня.",
            {"next_step_fixed": True, "next_step_text": "Выставить счет клиенту."},
            "2026-05-04 12:00:00",
        )
        rescheduled = contact(
            "Перенос клиент",
            "Клиент попросил вернуться позже после просмотра.",
            {"next_step_fixed": False, "reason_not_fixed": "Клиент попросил позже."},
            "2026-05-04 09:00:00",
        )
        warm = contact(
            "Теплый клиент",
            "Клиент: скиньте информацию на WhatsApp, я посмотрю.",
            {"next_step_fixed": True, "next_step_text": "Отправить информацию на WhatsApp."},
            "2026-05-04 08:00:00",
        )
        low = contact(
            "Низкий клиент",
            "Менеджер рассказал про продукт, клиент конкретный следующий шаг не подтвердил.",
            {"next_step_fixed": True, "next_step_text": "Поддерживать связь на случай будущих потребностей."},
            "2026-05-04 07:00:00",
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[low, warm, rescheduled, agreed],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        contacts = payload["call_tomorrow"]["contacts"]
        self.assertEqual([item["priority_code"] for item in contacts], ["hot", "rescheduled", "warm"])
        self.assertEqual([item["priority_label"] for item in contacts], ["Горячий", "Перенос", "Тёплый"])
        self.assertEqual([item["status"] for item in contacts], ["agreed", "rescheduled", "open"])
        self.assertEqual(
            payload["call_tomorrow"]["selection_diagnostics"]["rejected"][0]["rejection_reason"],
            "weak_open_without_grounded_follow_up_signal",
        )

        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        priority_labels = [row[0] for row in sections["call_tomorrow"]["rows"]]
        self.assertEqual(priority_labels, ["🔴 Горячий", "🟡 Перенос", "🟠 Тёплый"])
        self.assertNotIn("Открытый", " ".join(priority_labels))

    def test_step8ah8e_call_tomorrow_recommendations_are_signal_specific(self) -> None:
        def contact(name: str, text: str, follow_up: dict[str, Any]) -> ReportArtifact:
            artifact = _artifact(70.0, "basic", call_date="2026-05-04 10:00:00")
            artifact.interaction.text = text
            artifact.interaction.metadata_["contact_name"] = name
            detail = artifact.analysis.scores_detail
            detail["call"] = {"contact_name": name, "contact_phone": "+77070000000"}
            detail["classification"] = {
                "call_type": "sales_primary",
                "scenario_type": "cold_outbound",
                "analysis_eligibility": "eligible",
            }
            detail["follow_up"] = follow_up
            return artifact

        cases = [
            (
                "Счёт клиент",
                "Клиент согласился: выставьте счёт, после получения согласуем оплату.",
                {"next_step_fixed": True, "next_step_text": "Выставить счёт клиенту."},
                "срок оплаты",
                "Отправить счёт",
                "Отправляю счёт",
            ),
            (
                "Встреча клиент",
                "Клиент готов на Zoom-демо продукта.",
                {"next_step_fixed": True, "next_step_text": "Согласовать Zoom-демо и участников встречи."},
                "участников и повестку",
                "Подтвердить встречу",
                "Подтверждаю встречу",
            ),
            (
                "Материалы клиент",
                "Клиент: скиньте КП в WhatsApp, я посмотрю.",
                {"next_step_fixed": True, "next_step_text": "Отправить КП в WhatsApp."},
                "материалы или предложение",
                "Отправить материал",
                "отправлю информацию",
            ),
            (
                "Совет клиент",
                "Клиент сказал, что подумает и обсудит предложение с коллегами.",
                {"next_step_fixed": True, "next_step_text": "Клиент обсудит предложение с коллегами."},
                "обсудить решение внутри",
                "с кем клиент будет обсуждать",
                "Удалось обсудить",
            ),
            (
                "Доверие клиент",
                "Клиент не берёт незнакомые звонки и просит сначала написать в WhatsApp.",
                {"next_step_fixed": True, "next_step_text": "Написать клиенту в WhatsApp."},
                "барьер доверия",
                "безопасный канал",
                "проверить контакт",
            ),
        ]
        for name, text, follow_up, expected_context, expected_action, expected_phrase in cases:
            with self.subTest(name=name):
                payload = build_manager_daily_payload(
                    department_id=str(uuid4()),
                    department_name="Отдел продаж",
                    artifacts=[contact(name, text, follow_up)],
                    period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
                    filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
                    mode="report_from_ready_data_only",
                    model_override=None,
                )
                sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
                rendered_context = sections["call_tomorrow"]["rows"][0][2]
                rendered_recommendation = sections["call_tomorrow"]["rows"][0][3]

                self.assertIn(expected_context, rendered_context)
                self.assertIn(expected_action, rendered_recommendation)
                self.assertIn(expected_phrase, rendered_recommendation)
                self.assertNotIn("Понять текущий интерес клиента", rendered_recommendation)

    def test_call_tomorrow_filters_weak_open_without_grounded_signal(self) -> None:
        artifact = _artifact(70.0, "basic", call_date="2026-05-04 10:00:00")
        artifact.interaction.text = "Менеджер рассказал про продукт, клиент конкретный следующий шаг не подтвердил."
        artifact.interaction.metadata_["contact_name"] = "Слабый клиент"
        detail = artifact.analysis.scores_detail
        detail["call"] = {"contact_name": "Слабый клиент", "contact_phone": "+77070000000"}
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["follow_up"] = {
            "next_step_fixed": True,
            "next_step_text": "Поддерживать связь на случай будущих потребностей.",
        }

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}

        self.assertEqual(payload["call_tomorrow"]["contacts"], [])
        self.assertEqual(sections["call_tomorrow"]["rows"], [])
        self.assertEqual(
            payload["call_tomorrow"]["selection_diagnostics"]["rejected"][0]["rejection_reason"],
            "weak_open_without_grounded_follow_up_signal",
        )

    def test_call_tomorrow_rejects_rescheduled_without_customer_reopen_signal(self) -> None:
        self.assertEqual(
            _call_tomorrow_rejection_reason(
                {
                    "status": "rescheduled",
                    "priority_code": "rescheduled",
                    "action_profile": "rescheduled",
                    "reason": "Клиент не проявил интереса к продукту.",
                    "next_step": "Вернуться в согласованный срок.",
                    "opening_script": "Добрый день. Договаривались вернуться к вопросу.",
                    "evidence_signal_text": "клиент не проявил интереса к продукту",
                }
            ),
            "rescheduled_without_customer_reopen_signal",
        )
        self.assertEqual(
            _call_tomorrow_rejection_reason(
                {
                    "status": "rescheduled",
                    "priority_code": "rescheduled",
                    "action_profile": "rescheduled",
                    "reason": "Клиент не проявил интереса к продукту.",
                    "next_step": "Вернуться в согласованный срок.",
                    "opening_script": "Добрый день. Договаривались вернуться к вопросу.",
                    "evidence_signal_text": "статус возврата: 18 июн, связаться позже.",
                }
            ),
            "rescheduled_without_customer_reopen_signal",
        )
        self.assertIsNone(
            _call_tomorrow_rejection_reason(
                {
                    "status": "rescheduled",
                    "priority_code": "rescheduled",
                    "action_profile": "rescheduled",
                    "reason": "Клиент не был готов к разговору и попросил перезвонить позже.",
                    "next_step": "Перезвонить клиенту позже.",
                    "opening_script": "Добрый день. Договаривались вернуться к вопросу.",
                    "evidence_signal_text": "клиент попросил перезвонить позже",
                }
            )
        )

    def test_step8ah8e_call_tomorrow_uses_specific_summary_action_when_aligned(self) -> None:
        artifact = _artifact(70.0, "basic", call_date="2026-05-04 10:00:00")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию. "
            "Клиент попросил выставить счёт. Менеджер договорился отправить счёт и уточнить оплату."
        )
        detail = artifact.analysis.scores_detail
        detail["call"] = {"contact_name": "Счёт клиент", "contact_phone": "+77070000000"}
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["follow_up"] = {"next_step_fixed": True, "next_step_text": "Выставить счёт клиенту."}
        detail.update(_valid_report_evidence_detail())
        detail["report_evidence"]["business_outcome"]["status"] = "agreement"
        detail["report_evidence"]["call_report_summary"]["short_context"] = (
            "Клиент попросил счёт и готов обсудить срок оплаты после получения."
        )
        detail["report_evidence"]["call_report_summary"]["manager_next_action"] = (
            "Отправить счёт и согласовать срок оплаты."
        )
        detail["report_evidence"]["call_report_summary"]["suggested_manager_phrase"] = (
            "Добрый день. Отправляю счёт, как договорились. Когда удобно сверить получение?"
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        contact = payload["call_tomorrow"]["contacts"][0]
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}

        self.assertEqual(contact["action_source"], "call_report_summary.manager_next_action")
        self.assertEqual(contact["context_source"], "call_report_summary.short_context")
        self.assertEqual(contact["next_step"], "Отправить счёт и согласовать срок оплаты.")
        self.assertIn("Отправить счёт и согласовать срок оплаты", sections["call_tomorrow"]["rows"][0][3])
        self.assertIn("Отправляю счёт", sections["call_tomorrow"]["rows"][0][3])

    def test_manager_daily_invalid_report_evidence_uses_step8w_fallback(self) -> None:
        artifact = _artifact(50.0, "problematic")
        artifact.interaction.text = "Клиент: Я просто уточняю для руководителя, сама решение не принимаю."
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "qp_role_scope",
                        "criterion_name": "Роль и масштаб",
                        "score": 0,
                        "max_score": 2,
                    }
                ],
            }
        ]
        detail["gaps"] = [{"criterion_code": "qp_role_scope", "title": "Роль собеседника не была уточнена"}]
        detail["evidence_fragments"] = [
            {
                "criterion_code": "qp_role_scope",
                "client_text": "Я просто уточняю для руководителя, сама решение не принимаю.",
            }
        ]
        invalid_report_evidence = _valid_report_evidence_detail()
        invalid_report_evidence["report_evidence"]["voice_of_customer"][0]["quote"] = "Этой цитаты нет в транскрипте."
        detail.update(invalid_report_evidence)

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        diagnostics = payload["report_evidence_diagnostics"]["summary"]
        self.assertEqual(diagnostics["available_count"], 1)
        self.assertEqual(diagnostics["valid_count"], 0)
        self.assertEqual(diagnostics["invalid_count"], 1)
        self.assertEqual(
            payload["report_evidence_diagnostics"]["calls"][0]["report_evidence_source"],
            "legacy_fallback",
        )
        if payload["situation_evidence_quote"] is not None:
            self.assertEqual(payload["situation_evidence_quote"]["source"], "evidence_fragments")
            self.assertIn("сама решение не принимаю", payload["situation_evidence_quote"]["client_text"])
        self.assertIsNone(payload["call_list"][0]["call_list_topic"])
        self.assertEqual(payload["call_list"][0]["call_list_topic_source"], "deterministic_fallback")

    def test_step8ah7_wires_valid_call_report_summary_with_guardrails(self) -> None:
        artifact = _artifact(64.0, "basic")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail.update(_valid_report_evidence_detail())
        detail["report_evidence"]["call_report_summary"]["short_topic"] = "Клиент попросил отправить КП"
        detail["report_evidence"]["call_report_summary"]["short_context"] = (
            "Клиент попросил КП в WhatsApp и не зафиксировал срок возврата."
        )
        detail["report_evidence"]["call_report_summary"]["manager_next_action"] = (
            "Отправить КП и завтра уточнить, появились ли вопросы."
        )
        detail["report_evidence"]["call_report_summary"]["suggested_manager_phrase"] = (
            "Алия, добрый день. Отправляю КП, как договорились. Завтра уточню, появились ли вопросы."
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}

        self.assertEqual(sections["call_list"]["rows"][0][2], "Клиент попросил отправить КП")
        self.assertEqual(
            sections["call_list"]["rows"][0][3],
            "Клиент попросил КП в WhatsApp и не зафиксировал срок возврата.",
        )
        self.assertEqual(payload["call_tomorrow"]["contacts"][0]["priority_code"], "warm")
        self.assertEqual(
            payload["call_tomorrow"]["contacts"][0]["next_step"],
            "Отправить КП и завтра уточнить, появились ли вопросы.",
        )
        self.assertIn("Отправить КП", sections["call_tomorrow"]["rows"][0][3])
        self.assertIn("Можно начать:", sections["call_tomorrow"]["rows"][0][3])
        self.assertTrue(
            "Что сделать:" in sections["voice_of_customer"]["rows"][0][2]
            or "Отправ" in sections["voice_of_customer"]["rows"][0][2]
        )
        self.assertGreaterEqual(
            payload["call_report_summary_diagnostics"]["summary"]["call_report_summary_used_count"],
            3,
        )

    def test_step8ah7_falls_back_for_broad_topic_and_unsafe_phrase(self) -> None:
        artifact = _artifact(64.0, "basic")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail.update(_valid_report_evidence_detail())
        detail["report_evidence"]["call_report_summary"]["short_topic"] = "Обсуждение ЭДО"
        detail["report_evidence"]["call_report_summary"]["short_context"] = (
            "Клиент попросил материалы без конкретного срока возврата."
        )
        detail["report_evidence"]["call_report_summary"]["suggested_manager_phrase"] = (
            "Добрый день. Возвращаюсь по разговору 12 мая в 14:30."
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}

        self.assertIsNone(payload["call_list"][0]["call_list_topic"])
        self.assertEqual(sections["call_list"]["rows"][0][2], "Продажи · Холодный")
        self.assertEqual(
            sections["call_list"]["rows"][0][3],
            "Клиент попросил материалы без конкретного срока возврата.",
        )
        self.assertNotIn("12 мая", sections["call_tomorrow"]["rows"][0][3])
        self.assertNotIn("14:30", sections["call_tomorrow"]["rows"][0][3])

    def test_ddc9_call_list_uses_llm2_business_outcome_status_for_display(self) -> None:
        artifact = _artifact(64.0, "basic", call_date="2026-05-18 09:40:00")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию. "
            "Клиент: Бюджет не заложен, договор продлевать не будем. "
            "Менеджер: Тогда я отправлю информацию."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["follow_up"] = {
            "next_step_fixed": True,
            "next_step_text": "Отправить информацию клиенту.",
        }
        detail.update(_valid_report_evidence_detail())
        detail["report_evidence"]["business_outcome"] = {
            "status": "refusal",
            "confidence": "high",
            "reason": "Клиент сообщил, что бюджет не заложен и договор не будут продлевать.",
            "evidence_quote": "Бюджет не заложен, договор продлевать не будем.",
            "evidence_speaker": "client",
            "needs_human_review": False,
        }
        detail["report_evidence"]["call_report_summary"]["short_topic"] = "Клиент отказался от продления договора"
        detail["report_evidence"]["call_report_summary"]["short_context"] = (
            "Клиент сообщил, что бюджет не заложен и договор продлевать не будут."
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-18", "date_to": "2026-05-18"},
            filters=ReportRunFilters(date_from="2026-05-18", date_to="2026-05-18"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        row = payload["call_list"][0]

        self.assertEqual(row["status"], "open")
        self.assertEqual(row["call_list_status"], "refusal")
        self.assertEqual(row["call_list_status_source"], "report_evidence.business_outcome")
        self.assertTrue(row["call_list_status_conflict_with_resolver"])
        self.assertEqual(sections["call_list"]["rows"][0][2], "Клиент отказался от продления договора")
        self.assertEqual(
            sections["call_list"]["rows"][0][3],
            "Клиент сообщил, что бюджет не заложен и договор продлевать не будут.",
        )
        self.assertEqual(sections["call_list"]["rows"][0][4], "Отказ")
        self.assertEqual(payload["call_outcomes_summary"]["open_count"], 1)
        self.assertEqual(payload["call_list_status_quality"]["llm2_status_used_count"], 1)
        self.assertEqual(payload["call_list_status_quality"]["conflict_count"], 1)

    def test_ddc9_call_list_falls_back_to_resolver_when_llm2_outcome_invalid(self) -> None:
        artifact = _artifact(64.0, "basic", call_date="2026-05-18 10:00:00")
        artifact.interaction.text = "Клиент: Выставляйте счёт. Менеджер: Отправлю счёт."
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["follow_up"] = {
            "next_step_fixed": True,
            "next_step_text": "Выставить счёт клиенту.",
        }
        detail.update(_valid_report_evidence_detail())
        detail["report_evidence"]["business_outcome"]["status"] = "maybe"

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-18", "date_to": "2026-05-18"},
            filters=ReportRunFilters(date_from="2026-05-18", date_to="2026-05-18"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        row = payload["call_list"][0]

        self.assertEqual(row["call_list_status"], "agreed")
        self.assertEqual(row["call_list_status_source"], "business_outcome_resolver")
        self.assertEqual(row["call_list_status_fallback_reason"], "missing_llm2_business_outcome")
        self.assertEqual(sections["call_list"]["rows"][0][4], "Договорённость")
        self.assertEqual(payload["call_list_status_quality"]["resolver_fallback_count"], 1)
        self.assertEqual(
            payload["report_evidence_diagnostics"]["calls"][0]["report_evidence_source"],
            "legacy_fallback",
        )

    def test_step8ah9_call_list_deadline_context_removes_technical_do_for_periods(self) -> None:
        self.assertEqual(_call_context_label("agreed", "После праздников", None), "после праздников")
        self.assertEqual(_call_context_label("agreed", "На этой неделе", None), "на этой неделе")
        self.assertEqual(_call_context_label("agreed", "12:00", None), "до 12:00")
        self.assertEqual(_call_context_label("agreed", "пятницы", None), "до пятницы")
        self.assertEqual(_call_context_label("agreed", "до На этой неделе", None), "на этой неделе")
        self.assertNotIn("→ до Конец года 2026", _call_context_label("rescheduled", "до Конец года 2026", None))

        artifact = _artifact(64.0, "basic", call_date="2026-05-04 09:14:00")
        artifact.interaction.text = "Клиент: выставляйте счёт. Менеджер: отправлю счёт."
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["follow_up"] = {
            "next_step_fixed": True,
            "next_step_text": "Выставить счёт клиенту.",
            "due_date_text": "На этой неделе",
        }

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        rendered_context = sections["call_list"]["rows"][0][3]

        self.assertIn("счёт", rendered_context)
        self.assertIn("на этой неделе", rendered_context)
        self.assertNotIn("до На", rendered_context)

    def test_step8ah11e_call_list_context_rejects_truncated_summary_context(self) -> None:
        artifact = _artifact(64.0, "basic", call_date="2026-05-04 09:30:00")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию. "
            "Клиент: Не заинтересован в данный момент."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["follow_up"] = {
            "next_step_fixed": False,
            "reason_not_fixed": "Клиент не заинтересован в данный момент",
        }
        detail.update(_valid_report_evidence_detail())
        detail["report_evidence"]["business_outcome"] = {
            "status": "refusal",
            "confidence": "high",
            "reason": "Клиент не заинтересован в данный момент.",
            "evidence_quote": "Не заинтересован в данный момент.",
            "evidence_speaker": "client",
            "needs_human_review": False,
        }
        detail["report_evidence"]["call_report_summary"]["short_topic"] = "Обсуждение ЭДО"
        detail["report_evidence"]["call_report_summary"]["short_context"] = "Клиент не заинтересован в да…"

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        row = payload["call_list"][0]
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        rendered_context = sections["call_list"]["rows"][0][3]

        self.assertEqual(payload["call_list_context_quality"]["status"], "passed")
        self.assertEqual(row["call_list_context_source"], "deterministic_context_quality_gate")
        self.assertIn("Клиент отказался", row["call_list_context"])
        self.assertNotIn("да…", rendered_context)
        self.assertTrue(
            any(item["reason"] == "truncated_context" for item in row["call_list_context_rejected"])
        )

    def test_sfb5_call_list_prefers_manager_visible_summary_over_truncated_short_context(self) -> None:
        artifact = _artifact(64.0, "basic", call_date="2026-05-04 09:30:00")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию. "
            "Клиент: Давайте вернёмся после того, как я покажу коллегам."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["follow_up"] = {
            "next_step_fixed": False,
            "reason_not_fixed": "Клиент попросил материалы и обсуждение с коллегами",
        }
        detail.update(_valid_report_evidence_detail())
        detail["report_evidence"]["business_outcome"] = {
            "status": "open",
            "confidence": "high",
            "reason": "Клиент попросил материалы и не зафиксировал дату возврата.",
            "evidence_quote": "Скиньте в WhatsApp, я посмотрю.",
            "evidence_speaker": "client",
            "needs_human_review": False,
        }
        detail["report_evidence"]["call_report_summary"]["short_context"] = "Клиент попросил материалы и хочет обсудить с кол…"
        detail["report_evidence"]["call_report_summary"]["manager_visible_summary"] = (
            "Клиент попросил отправить материалы в WhatsApp и сказал, что покажет их коллегам. "
            "Дата возврата к обсуждению в звонке не закреплена, поэтому контакт остаётся открытым. "
            "Менеджеру важно отправить материалы и отдельно согласовать, когда вернуться к решению."
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        row = payload["call_list"][0]
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        rendered_context = sections["call_list"]["rows"][0][3]

        self.assertEqual(payload["call_list_context_quality"]["status"], "passed")
        self.assertEqual(row["call_list_context_source"], "report_evidence.call_report_summary.manager_visible_summary")
        self.assertEqual(payload["call_list_context_quality"]["manager_visible_summary_count"], 1)
        self.assertIn("покажет их коллегам", row["call_list_context"])
        self.assertIn("Дата возврата", rendered_context)
        self.assertNotIn("кол…", rendered_context)

    def test_step8ah11e_call_list_context_fallbacks_avoid_bare_dash_for_sales_rows(self) -> None:
        agreed = _artifact(64.0, "basic", call_date="2026-05-04 09:00:00")
        agreed.interaction.text = "Клиент: Выставляйте счёт. Менеджер: Отправлю счёт."
        agreed_detail = agreed.analysis.scores_detail
        agreed_detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        agreed_detail["follow_up"] = {
            "next_step_fixed": True,
            "next_step_text": "Выставить счёт клиенту.",
        }

        rescheduled = _artifact(64.0, "basic", call_date="2026-05-04 10:00:00")
        rescheduled.interaction.text = "Клиент: Вернитесь после праздников. Менеджер: Хорошо."
        rescheduled_detail = rescheduled.analysis.scores_detail
        rescheduled_detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        rescheduled_detail["follow_up"] = {
            "next_step_fixed": False,
            "reason_not_fixed": "Клиент попросил перезвонить после праздников",
            "due_date_text": "После праздников",
        }

        open_call = _artifact(64.0, "basic", call_date="2026-05-04 11:00:00")
        open_call.interaction.text = "Клиент: Скиньте материалы, я посмотрю. Менеджер: Отправлю."
        open_detail = open_call.analysis.scores_detail
        open_detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        open_detail["follow_up"] = {
            "next_step_fixed": False,
            "reason_not_fixed": "",
        }

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[agreed, rescheduled, open_call],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        contexts = [row["call_list_context"] for row in payload["call_list"]]

        self.assertEqual(payload["call_list_context_quality"]["status"], "passed")
        self.assertTrue(all(context and context != "—" for context in contexts))
        self.assertTrue(any("счёт" in context for context in contexts))
        self.assertTrue(any("после праздников" in context for context in contexts))
        self.assertTrue(any("Клиент попросил материалы" in context for context in contexts))

    def test_step8ah11e_call_list_context_handles_year_period_and_service_fallback(self) -> None:
        rescheduled = _artifact(64.0, "basic", call_date="2026-05-04 10:00:00")
        rescheduled.interaction.text = "Клиент: Вернитесь в конце года 2026. Менеджер: Хорошо."
        rescheduled_detail = rescheduled.analysis.scores_detail
        rescheduled_detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        rescheduled_detail["follow_up"] = {
            "next_step_fixed": False,
            "reason_not_fixed": "Клиент попросил вернуться в конце года",
            "due_date_text": "Конец года 2026",
        }

        service = _artifact(64.0, "basic", call_date="2026-05-04 11:00:00")
        service.interaction.text = "Клиент: Помогите с подписанием документа через QR."
        service_detail = service.analysis.scores_detail
        service_detail["classification"] = {
            "call_type": "support",
            "scenario_type": "after_signed_document",
            "analysis_eligibility": "not_eligible",
        }
        service_detail["follow_up"] = {}

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[rescheduled, service],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        rendered_contexts = [row[3] for row in sections["call_list"]["rows"]]
        all_context = " ".join(rendered_contexts)

        self.assertIn("в конце 2026 года", all_context)
        self.assertIn("после подписания документа", all_context.lower())
        self.assertNotIn("→ до Конец года 2026", all_context)
        self.assertNotIn("до Конец года 2026", all_context)
        self.assertEqual(payload["call_list_context_quality"]["status"], "passed")

    def test_step8ah9_empty_additional_situations_hidden_in_manager_daily_render(self) -> None:
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[_artifact()],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        payload["additional_situations"] = {"is_placeholder": True, "situations": []}

        rendered = render_report_email(payload)

        self.assertNotIn("ДОПОЛНИТЕЛЬНЫЕ 3 СИТУАЦИИ", rendered["text"])
        self.assertNotIn("Дополнительные ситуации появятся", rendered["text"])
        self.assertNotIn("Дополнительные ситуации появятся", rendered["html"])
        self.assertNotIn("ЧЕЛЛЕНДЖ НА ЗАВТРА", rendered["text"])

    def test_step8ah11a_expanded_coaching_scope_is_explicit_for_non_report_day_blocks(self) -> None:
        manager = _manager()
        previous_day = _artifact_for_manager(
            manager,
            score_percent=38.0,
            level="problematic",
            call_date="2026-04-30 09:00:00",
        )
        report_day = _artifact_for_manager(
            manager,
            score_percent=82.0,
            level="strong",
            call_date="2026-05-04 10:00:00",
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[previous_day, report_day],
            period={"date_from": "2026-04-30", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=[previous_day, report_day],
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}

        self.assertEqual(len(payload["call_list"]), 1)
        self.assertEqual(payload["call_list"][0]["date_label"], "2026-05-04")
        self.assertEqual(payload["data_scopes"]["situation_day"]["code"], "expanded_coaching_base")
        self.assertEqual(payload["data_scopes"]["call_breakdown"]["code"], "expanded_coaching_base")
        self.assertEqual(payload["data_scopes"]["challenge"]["code"], "rolling_window")

        situation = sections["main_focus_for_tomorrow"]
        self.assertEqual(situation["data_scope"], "expanded_coaching_base")
        self.assertNotEqual(situation["label"], "СИТУАЦИЯ ДНЯ")
        self.assertIn("расширенной", situation["scope_note"].lower())
        self.assertEqual(situation["example_label"], "Пример из расширенной базы")
        self.assertIn("РАСШИРЕННОЙ БАЗЫ", situation["situation_title"])

        breakdown = sections["call_breakdown"]
        self.assertEqual(breakdown["data_scope"], "expanded_coaching_base")
        self.assertIn("РАСШИРЕННОЙ БАЗЫ", breakdown["label"])
        self.assertIn("расширенной", breakdown["scope_note"].lower())

        challenge = sections["challenge"]
        self.assertEqual(challenge["data_scope"], "rolling_window")
        self.assertNotIn("Сегодня", challenge["today_line"])
        self.assertIn("За последние", challenge["today_line"])

    def test_step8ah11a_report_day_scope_keeps_today_wording(self) -> None:
        artifact = _artifact(call_date="2026-05-04 10:00:00")
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=[artifact],
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}

        self.assertEqual(payload["data_scopes"]["situation_day"]["code"], "report_day")
        self.assertEqual(sections["main_focus_for_tomorrow"]["label"], "СИТУАЦИЯ ДНЯ")
        self.assertIsNone(sections["main_focus_for_tomorrow"]["scope_note"])
        self.assertEqual(sections["main_focus_for_tomorrow"]["example_label"], "Пример из сегодня")
        self.assertTrue(sections["challenge"]["today_line"].startswith("Сегодня:"))

    def test_step8ah11b_daily_focus_filters_mismatched_situation_and_breakdown(self) -> None:
        artifact = _artifact(64.0, "basic")
        artifact.interaction.text = "Клиент: Скиньте в WhatsApp, я посмотрю. Менеджер: Хорошо, отправлю информацию."
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["score_by_stage"] = [
            {
                "stage_code": "contact_start",
                "stage_name": "Первичный контакт",
                "stage_score": 2,
                "max_stage_score": 2,
                "criteria_results": [],
            },
            {
                "stage_code": "needs_discovery",
                "stage_name": "Выявление детальных потребностей",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "nd_depth",
                        "criterion_name": "Глубина потребности",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Конкретные сценарии использования не были выявлены.",
                    }
                ],
            },
        ]
        detail["gaps"] = [
            {
                "criterion_code": "cs_relevance",
                "title": "Нерелевантный старт",
                "comment": "Старт звонка был общим.",
            }
        ]
        detail.update(_valid_report_evidence_detail())
        detail["report_evidence"]["situation_candidates"][0]["stage_code"] = "contact_start"
        detail["report_evidence"]["manager_coaching_moments"][0]["stage_code"] = "contact_start"

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}

        self.assertEqual(payload["daily_coaching_focus"]["stage_id"], "Э3")
        self.assertEqual(payload["daily_coaching_focus"]["stage_code"], "needs_discovery")
        self.assertEqual(payload["daily_coaching_focus_validation"]["status"], "passed")
        self.assertEqual(payload["situation_day_coaching_view"]["stage_code"], "needs_discovery")
        self.assertIn("Недостаточно evidence", payload["situation_day_coaching_view"]["what_happened"])
        self.assertEqual(payload["call_breakdown"]["stage_code"], "needs_discovery")
        self.assertEqual(payload["call_breakdown"]["call_breakdown_source"], "focus_evidence_missing")
        self.assertEqual(payload["call_breakdown_quality"]["status"], "insufficient_evidence")
        self.assertEqual(sections["call_breakdown"]["rows"], [])
        self.assertIn("Недостаточно подтверждённых фрагментов", sections["call_breakdown"]["summary_line"])
        self.assertEqual(sections["challenge"]["focus_stage_code"], "needs_discovery")
        self.assertEqual(sections["main_focus_for_tomorrow"]["focus_stage_code"], "needs_discovery")

    def test_step8ah11b_daily_focus_keeps_aligned_report_evidence_blocks(self) -> None:
        artifact = _artifact(64.0, "basic")
        artifact.interaction.text = "Клиент: Скиньте в WhatsApp, я посмотрю. Менеджер: Хорошо, отправлю информацию."
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "qp_current_process",
                        "criterion_name": "Текущий процесс",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Контекст процесса не уточнён.",
                    }
                ],
            }
        ]
        detail["gaps"] = [{"criterion_code": "qp_current_process", "title": "Legacy gap"}]
        detail.update(_valid_report_evidence_detail())
        detail["report_evidence"]["manager_coaching_moments"][0]["stage_code"] = "qualification_primary"

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}

        self.assertEqual(payload["daily_coaching_focus"]["stage_code"], "qualification_primary")
        self.assertEqual(payload["situation_day_coaching_view"]["stage_code"], "qualification_primary")
        self.assertEqual(payload["call_breakdown"]["stage_code"], "qualification_primary")
        self.assertEqual(payload["daily_coaching_focus_validation"]["status"], "passed")
        self.assertEqual(sections["challenge"]["focus_stage_code"], "qualification_primary")

    def test_step8ah11c_problem_normalizer_blocks_positive_problem_wording(self) -> None:
        artifact = _artifact(42.0, "problematic")
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "qp_process_before_pitch",
                        "criterion_name": "Не ушёл в презентацию слишком рано",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Менеджер не ушел в презентацию слишком рано",
                    }
                ],
            }
        ]
        detail["gaps"] = [
            {
                "criterion_code": "qp_role_scope",
                "title": "Роль не уточнена",
                "comment": "Роль собеседника не была уточнена.",
            },
            {
                "criterion_code": "qp_current_process",
                "title": "Не ушёл в презентацию слишком рано",
                "comment": "Квалификация не была завершена до предложения.",
            },
        ]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        rendered_text = " ".join(
            str(value)
            for value in [
                payload["score_by_stage"][0].get("problem_summary"),
                payload["daily_coaching_focus"].get("problem_statement"),
                sections["review_block"]["stage_rows"][0].get("problem_summary"),
                *(item.get("title") for item in sections["additional_situations"].get("situations") or []),
                *(item.get("client_said") for item in sections["additional_situations"].get("situations") or []),
            ]
        )
        rendered_norm = rendered_text.lower().replace("ё", "е")

        self.assertNotIn("менеджер не ушел в презентацию слишком рано", rendered_norm)
        self.assertNotIn("не ушел в презентацию слишком рано", rendered_norm)
        self.assertIn("квалификация не была завершена до предложения", rendered_norm)
        self.assertIn("positive_or_neutral_problem_wording_normalized", payload["score_by_stage"][0]["problem_wording_warnings"])
        self.assertEqual(payload["problem_wording_diagnostics"]["status"], "warning")

    def test_step8ah11c_additional_gap_title_and_body_are_normalized(self) -> None:
        artifact = _artifact(64.0, "basic", call_date="2026-05-04 10:00:00")
        artifact.interaction.text = "Клиент: Скиньте в WhatsApp, я посмотрю. Менеджер: Хорошо, отправлю информацию."
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "qp_current_process",
                        "criterion_name": "Текущий процесс",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Квалификация не была завершена до предложения.",
                    }
                ],
            }
        ]
        detail.update(_valid_report_evidence_detail())
        detail["report_evidence"]["manager_coaching_moments"][0]["stage_code"] = "qualification_primary"
        detail["report_evidence"]["additional_situations"][0].update(
            {
                "type": "growth_zone",
                "title": "Не ушёл в презентацию слишком рано",
                "stage_code": "qualification_primary",
                "what_happened": "Не ушёл в презентацию слишком рано",
                "why_it_matters": "Квалификация не была завершена до предложения.",
            }
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        situation = sections["additional_situations"]["situations"][0]
        combined = f"{situation['title']} {situation['client_said']}".lower().replace("ё", "е")

        self.assertEqual(situation["badge"], "Зона роста")
        self.assertNotIn("не ушел в презентацию слишком рано", combined)
        self.assertIn("квалификация не была завершена до предложения", combined)
        self.assertIn("narrative", situation)
        self.assertIn("В следующий раз", situation["narrative"])
        self.assertTrue(situation.get("evidence_dialogue"))
        self.assertGreaterEqual(payload["problem_wording_diagnostics"]["normalized_count"], 1)

    def test_step8ah11d_additional_quality_gate_hides_contextless_legacy_cards(self) -> None:
        artifact = _artifact(
            48.0,
            "problematic",
            call_date="2026-05-04 10:00:00",
            gaps=[
                {
                    "criterion_code": "qp_role_scope",
                    "title": "Роль не уточнена",
                    "comment": "Роль собеседника не была уточнена.",
                },
                {
                    "criterion_code": "qp_current_process",
                    "title": "Текущий процесс не уточнён",
                    "comment": "Квалификация не была завершена до предложения.",
                },
            ],
            strengths=[],
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        rendered = render_report_email(payload)

        self.assertEqual(payload["additional_situations"]["situations"], [])
        self.assertEqual(payload["additional_situations"].get("hidden_reason"), "quality_gate_no_valid_situations")
        self.assertGreaterEqual(payload["additional_situations_quality"]["filtered_reasons"].get("missing_evidence", 0), 1)
        self.assertNotIn("ДОПОЛНИТЕЛЬНЫЕ 3 СИТУАЦИИ", rendered["text"])
        self.assertNotIn("Дополнительные ситуации появятся", rendered["text"])

    def test_step8ah11d_additional_quality_gate_adapts_generic_wording_by_stage(self) -> None:
        artifact = _artifact(64.0, "basic", call_date="2026-05-04 10:00:00")
        artifact.interaction.text = "Клиент: Скиньте в WhatsApp, я посмотрю. Менеджер: Хорошо, отправлю информацию."
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail.update(_valid_report_evidence_detail())
        generic_why = "Клиент не получил достаточно конкретики или фиксации следующего шага."
        generic_action = "Задать уточняющий вопрос, затем зафиксировать конкретный следующий шаг и дедлайн."
        detail["report_evidence"]["additional_situations"] = [
            {
                "type": "growth_zone",
                "title": "Текущий процесс не уточнён",
                "priority": "medium",
                "evidence_quality": "indirect",
                "what_happened": "Скиньте в WhatsApp, я посмотрю.",
                "why_it_matters": generic_why,
                "recommended_action": generic_action,
                "stage_code": "qualification_primary",
                "usable_in_report": True,
            },
            {
                "type": "growth_zone",
                "title": "Следующий шаг остался общим",
                "priority": "medium",
                "evidence_quality": "indirect",
                "what_happened": "Хорошо, отправлю информацию.",
                "why_it_matters": generic_why,
                "recommended_action": generic_action,
                "stage_code": "completion_next_step",
                "usable_in_report": True,
            },
        ]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-05-04", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        situations = sections["additional_situations"]["situations"]
        rendered_text = " ".join(
            " ".join(str(situation.get(key) or "") for key in ("meant", "how_to", "why"))
            for situation in situations
        ).lower().replace("ё", "е")
        actions = [situation["how_to"] for situation in situations]

        self.assertEqual(payload["additional_situations_quality"]["rendered_count"], 2)
        self.assertEqual(payload["additional_situations_quality"]["filtered_count"], 0)
        self.assertNotIn("клиент не получил достаточно конкретики или фиксации следующего шага", rendered_text)
        self.assertNotIn("задать уточняющий вопрос, затем зафиксировать конкретный следующий шаг", rendered_text)
        self.assertEqual(len(set(actions)), len(actions))
        self.assertTrue(any("роль" in action.lower() or "текущий процесс" in action.lower() for action in actions))
        self.assertTrue(any("канал" in action.lower() or "срок" in action.lower() for action in actions))

    def test_step8ah11f_manager_daily_semantic_regression_checkpoint(self) -> None:
        """Single pre-rebuild checkpoint for Step 8AH-11A..11E semantics."""
        manager = _manager()
        scope_previous_day = _artifact_for_manager(
            manager,
            score_percent=38.0,
            level="problematic",
            call_date="2026-04-30 09:00:00",
        )
        scope_report_day = _artifact_for_manager(
            manager,
            score_percent=82.0,
            level="strong",
            call_date="2026-05-04 10:00:00",
        )
        scope_payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[scope_previous_day, scope_report_day],
            period={"date_from": "2026-04-30", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=[scope_previous_day, scope_report_day],
        )
        scope_sections = {section["id"]: section for section in build_report_render_model(scope_payload)["sections"]}

        previous_day = _artifact_for_manager(
            manager,
            score_percent=38.0,
            level="problematic",
            call_date="2026-04-30 09:00:00",
            gaps=[
                {
                    "criterion_code": "qp_current_process",
                    "title": "Не ушёл в презентацию слишком рано",
                    "comment": "Менеджер не ушел в презентацию слишком рано",
                }
            ],
            strengths=[],
        )
        previous_detail = previous_day.analysis.scores_detail
        previous_detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        previous_detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "qp_process_before_pitch",
                        "criterion_name": "Не ушёл в презентацию слишком рано",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Менеджер не ушел в презентацию слишком рано",
                    }
                ],
            }
        ]

        report_day = _artifact_for_manager(
            manager,
            score_percent=70.0,
            level="basic",
            call_date="2026-05-04 10:00:00",
        )
        report_day.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Хорошо, отправлю информацию. "
            "Клиент: Не заинтересован в данный момент."
        )
        report_detail = report_day.analysis.scores_detail
        report_detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        report_detail["follow_up"] = {
            "next_step_fixed": False,
            "reason_not_fixed": "Клиент не заинтересован в данный момент",
        }
        report_detail.update(_valid_report_evidence_detail())
        report_detail["report_evidence"]["call_report_summary"]["short_topic"] = "Обсуждение ЭДО"
        report_detail["report_evidence"]["call_report_summary"]["short_context"] = "Клиент не заинтересован в да…"
        report_detail["report_evidence"]["additional_situations"] = []

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[previous_day, report_day],
            period={"date_from": "2026-04-30", "date_to": "2026-05-04"},
            filters=ReportRunFilters(date_from="2026-05-04", date_to="2026-05-04"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=[previous_day, report_day],
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        rendered = render_report_email(payload)
        rendered_norm = rendered["text"].lower().replace("ё", "е")
        call_list_context = " ".join(str(row[3]) for row in sections["call_list"]["rows"])

        self.assertEqual([row["date_label"] for row in scope_payload["call_list"]], ["2026-05-04"])
        self.assertIn("data_scopes", scope_payload)
        self.assertEqual(scope_payload["data_scopes"]["situation_day"]["code"], "expanded_coaching_base")
        self.assertEqual(scope_payload["data_scopes"]["call_breakdown"]["code"], "expanded_coaching_base")
        self.assertEqual(scope_payload["data_scopes"]["challenge"]["code"], "rolling_window")
        self.assertNotEqual(scope_sections["main_focus_for_tomorrow"]["label"], "СИТУАЦИЯ ДНЯ")
        self.assertNotIn("Сегодня", scope_sections["challenge"]["today_line"])
        self.assertEqual([row["date_label"] for row in payload["call_list"]], ["2026-05-04"])

        self.assertIn("daily_coaching_focus_validation", payload)
        self.assertEqual(payload["daily_coaching_focus"]["stage_code"], "qualification_primary")
        self.assertEqual(payload["daily_coaching_focus_validation"]["status"], "passed")
        self.assertEqual(sections["main_focus_for_tomorrow"]["focus_stage_code"], "qualification_primary")
        self.assertEqual(payload["call_breakdown"]["stage_code"], "qualification_primary")
        self.assertEqual(sections["challenge"]["focus_stage_code"], "qualification_primary")

        self.assertIn("problem_wording_diagnostics", payload)
        self.assertGreaterEqual(payload["problem_wording_diagnostics"]["normalized_count"], 1)
        self.assertNotIn("менеджер не ушел в презентацию слишком рано", rendered_norm)
        self.assertIn("квалификация не была завершена до предложения", rendered_norm)

        self.assertIn("additional_situations_quality", payload)
        self.assertEqual(payload["additional_situations"]["situations"], [])
        self.assertEqual(payload["additional_situations"].get("hidden_reason"), "quality_gate_no_valid_situations")
        self.assertGreaterEqual(payload["additional_situations_quality"]["filtered_count"], 1)
        self.assertNotIn("ДОПОЛНИТЕЛЬНЫЕ 3 СИТУАЦИИ", rendered["text"])
        self.assertIn("call_breakdown_quality", payload)
        self.assertNotIn("Нет подтверждающего фрагмента в сохранённых данных", rendered["text"])

        self.assertIn("call_list_context_quality", payload)
        self.assertEqual(payload["call_list_context_quality"]["status"], "passed")
        self.assertEqual(payload["call_list_context_quality"]["calls_count"], 1)
        self.assertGreaterEqual(payload["call_list_context_quality"]["fallback_generated_count"], 1)
        self.assertTrue(
            any(
                item["reason"] == "truncated_context"
                for item in payload["call_list_context_quality"]["rejected_contexts"]
            )
        )
        self.assertNotIn("до После", call_list_context)
        self.assertNotIn("до На этой неделе", call_list_context)
        self.assertNotIn("→ до Конец года 2026", call_list_context)
        self.assertNotIn("да…", call_list_context)
        self.assertNotEqual(call_list_context.strip(), "—")

    def test_manager_daily_payload_keeps_situation_evidence_quote_null_without_stage_match(self) -> None:
        artifact = _artifact(50.0, "problematic")
        artifact.analysis.scores_detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "qp_role_scope",
                        "criterion_name": "Роль и масштаб",
                        "score": 0,
                        "max_score": 2,
                    }
                ],
            }
        ]
        artifact.analysis.scores_detail["evidence_fragments"] = [
            {
                "criterion_code": "nd_depth",
                "client_text": "Эта цитата относится к другому этапу.",
            }
        ]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        self.assertIsNone(payload["situation_evidence_quote"])

    def test_manager_daily_payload_dialogue_excerpt_is_partial_with_client_text_only(self) -> None:
        artifact = _artifact(50.0, "problematic")
        artifact.analysis.scores_detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "qp_current_process",
                        "criterion_name": "Текущий процесс",
                        "score": 0,
                        "max_score": 2,
                    }
                ],
            }
        ]
        artifact.analysis.scores_detail["evidence_fragments"] = [
            {
                "criterion_code": "qp_current_process",
                "client_text": "На бумаге или просто по электронной почте.",
            }
        ]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        excerpt = payload["situation_dialogue_excerpt"]
        self.assertIsNotNone(excerpt)
        self.assertTrue(excerpt["is_partial"])
        self.assertEqual(excerpt["turns"], [{"speaker": "client", "text": "На бумаге или просто по электронной почте."}])

    def test_manager_daily_payload_dialogue_excerpt_uses_transcript_segments_when_available(self) -> None:
        artifact = _artifact(50.0, "problematic")
        artifact.interaction.metadata_["segments"] = [
            {"speaker": "A", "text": "обороты устраиваем?"},
            {"speaker": "A", "text": "На бумаге или просто по электронной почте."},
            {"speaker": "A", "text": "смотрите, я у вас базовый пакет покупаю, надо 180 тысяч"},
        ]
        artifact.analysis.scores_detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "qp_current_process",
                        "criterion_name": "Текущий процесс",
                        "score": 0,
                        "max_score": 2,
                    }
                ],
            }
        ]
        artifact.analysis.scores_detail["evidence_fragments"] = [
            {
                "criterion_code": "qp_current_process",
                "client_text": "На бумаге или просто по электронной почте.",
            }
        ]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        excerpt = payload["situation_dialogue_excerpt"]
        self.assertIsNotNone(excerpt)
        self.assertEqual(excerpt["source"], "transcript_turns")
        self.assertTrue(excerpt["is_partial"])
        self.assertEqual(excerpt["partial_reason"], "speaker_roles_unavailable")
        self.assertEqual(
            excerpt["turns"],
            [
                {"speaker": "unknown", "text": "обороты устраиваем?"},
                {"speaker": "client", "text": "На бумаге или просто по электронной почте."},
                {"speaker": "unknown", "text": "смотрите, я у вас базовый пакет покупаю, надо 180 тысяч"},
            ],
        )
        coaching_view = payload["situation_day_coaching_view"]
        self.assertIsNotNone(coaching_view)
        self.assertEqual(
            coaching_view["pattern_title"],
            "Клиент спрашивает про формат работы, но контекст не уточнён",
        )
        self.assertIn("документооборот", coaching_view["what_happened"])
        self.assertTrue(coaching_view["dialogue_is_partial"])

    def test_manager_daily_situation_fallback_skips_ivr_like_transcript_segments(self) -> None:
        artifact = _artifact(35.0, "problematic")
        artifact.interaction.text = (
            "Здравствуйте! Вас приветствует главный эксперт по путешествиям турагентства HTKZ. "
            "Наберите внутренний номер сотрудника или дождитесь ответа менеджера. "
            "Только у нас вы можете забронировать тур не выходя из дома, оплачивая картой виза или мастер-карт. "
            "Я хотел у вас уточнить по поводу электронного документооборота. "
            "Скиньте коммерческое предложение в WhatsApp, я посмотрю."
        )
        artifact.interaction.metadata_["segments"] = [
            {"speaker": "A", "text": "Здравствуйте! Вас приветствует главный эксперт по путешествиям турагентства HTKZ."},
            {"speaker": "A", "text": "Наберите внутренний номер сотрудника или дождитесь ответа менеджера."},
            {
                "speaker": "A",
                "text": "Только у нас вы можете забронировать тур не выходя из дома, оплачивая картой виза или мастер-карт.",
            },
            {"speaker": "A", "text": "Я хотел у вас уточнить по поводу электронного документооборота."},
            {"speaker": "A", "text": "Скиньте коммерческое предложение в WhatsApp, я посмотрю."},
        ]
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["call"]["contact_name"] = "HTKZ клиент"
        detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "qp_current_process",
                        "criterion_name": "Текущий процесс",
                        "score": 0,
                        "max_score": 2,
                        "comment": "Текущий процесс не уточнен.",
                    }
                ],
            }
        ]
        detail["gaps"] = [
            {
                "criterion_code": "qp_current_process",
                "title": "Текущий процесс не уточнен",
                "comment": "Текущий процесс не уточнен.",
            }
        ]
        detail["evidence_fragments"] = []

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        excerpt = payload["situation_dialogue_excerpt"]
        self.assertIsNotNone(excerpt)
        self.assertEqual(excerpt["source"], "call_breakdown_transcript_segments")
        rendered = " ".join(turn["text"] for turn in excerpt["turns"])
        self.assertIn("документооборота", rendered)
        self.assertNotIn("турагентства", rendered)
        self.assertNotIn("Наберите внутренний номер", rendered)
        self.assertEqual(excerpt["evidence_quality"], "indirect")

    def test_manager_daily_call_breakdown_prefers_meaningful_fallback_over_greeting_only(self) -> None:
        weak = _artifact(10.0, "problematic", call_date="2026-03-25 09:00:00")
        weak.interaction.text = "ТЕЛЕФОННЫЙ ЗВОНОК. Алло. Добрый день."
        weak.interaction.metadata_["segments"] = [
            {"speaker": "A", "text": "ТЕЛЕФОННЫЙ ЗВОНОК"},
            {"speaker": "A", "text": "Алло"},
            {"speaker": "A", "text": "Добрый день"},
        ]
        strong = _artifact(80.0, "basic", call_date="2026-03-25 10:00:00")
        strong.interaction.text = (
            "Менеджер уточнил электронный документооборот. "
            "Клиент попросил отправить коммерческое предложение в WhatsApp."
        )
        strong.interaction.metadata_["segments"] = [
            {"speaker": "A", "text": "Менеджер уточнил электронный документооборот."},
            {"speaker": "B", "text": "Клиент попросил отправить коммерческое предложение в WhatsApp."},
        ]

        for artifact, label in ((weak, "Слабый IVR"), (strong, "Содержательный клиент")):
            detail = artifact.analysis.scores_detail
            detail["classification"] = {
                "call_type": "sales_primary",
                "scenario_type": "cold_outbound",
                "analysis_eligibility": "eligible",
            }
            detail["call"]["contact_name"] = label
            detail["score_by_stage"] = [
                {
                    "stage_code": "qualification_primary",
                    "stage_name": "Квалификация и первичная потребность",
                    "stage_score": 0,
                    "max_stage_score": 2,
                    "criteria_results": [
                        {
                            "criterion_code": "qp_current_process",
                            "criterion_name": "Текущий процесс",
                            "score": 0,
                            "max_score": 2,
                            "comment": "Текущий процесс не уточнен.",
                        }
                    ],
                }
            ]
            detail["gaps"] = [
                {
                    "criterion_code": "qp_current_process",
                    "title": "Текущий процесс не уточнен",
                    "comment": "Текущий процесс не уточнен.",
                }
            ]
            detail["evidence_fragments"] = []

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[weak, strong],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        self.assertEqual(payload["call_breakdown"]["client_label"], "Содержательный клиент")
        self.assertEqual(payload["call_breakdown"]["fallback_evidence_quality"], "indirect")
        self.assertGreaterEqual(payload["call_breakdown"]["fallback_evidence_score"], 4)

    def test_manager_daily_call_breakdown_accepts_text_only_gap_items(self) -> None:
        artifact = _artifact(42.0, "problematic")
        artifact.interaction.text = "Клиент попросил коммерческое предложение в WhatsApp, но процесс не был уточнен."
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["call"]["contact_name"] = "Текстовый gap"
        detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [],
            }
        ]
        detail["gaps"] = [{"text": "Менеджер не выяснил, как устроен текущий процесс у клиента."}]
        detail["evidence_fragments"] = []

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        self.assertFalse(payload["call_breakdown"]["is_placeholder"])
        self.assertEqual(payload["call_breakdown"]["client_label"], "Текстовый gap")
        self.assertEqual(
            payload["analysis_improve"][0]["label"],
            "Менеджер не выяснил, как устроен текущий процесс у клиента.",
        )

    def test_call_breakdown_quality_gate_hides_missing_fragment_rows(self) -> None:
        artifact = _artifact(42.0, "problematic")
        artifact.interaction.text = "Текст звонка."
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [],
            }
        ]
        detail["gaps"] = [{"criterion_code": "qp_current_process", "title": "Текущий процесс не уточнён"}]
        detail["recommendations"] = [{"recommendation": "Уточнить текущий процесс клиента."}]
        detail["evidence_fragments"] = []

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        self.assertFalse(payload["call_breakdown"]["call_breakdown_fragment_present"])
        self.assertEqual(payload["call_breakdown"]["call_breakdown_evidence_strength"], "missing")
        self.assertEqual(payload["call_breakdown_quality"]["status"], "insufficient_evidence")
        self.assertGreaterEqual(payload["call_breakdown_quality"]["filtered_rows_count"], 1)
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        self.assertEqual(sections["call_breakdown"]["rows"], [])
        rendered = render_report_email(payload)["text"]
        self.assertIn("Недостаточно подтверждённых фрагментов", rendered)
        self.assertNotIn("Нет подтверждающего фрагмента в сохранённых данных", rendered)
        self.assertNotIn("Фрагмент: —", rendered)

    def test_step8ah11h_call_breakdown_filters_positive_recommendation_for_problem_row(self) -> None:
        artifact = _artifact(42.0, "problematic")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Расскажите, как сейчас подписываете документы. "
            "Клиент: Пока вручную, но процесс не обсуждали подробно."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [],
            }
        ]
        detail["gaps"] = [{"criterion_code": "qp_current_process", "title": "Текущий процесс не уточнён"}]
        detail["recommendations"] = [
            {"recommendation": "Продолжать использовать четкое представление компании."}
        ]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        quality = payload["call_breakdown_quality"]
        self.assertEqual(quality["status"], "insufficient_evidence")
        self.assertEqual(
            quality["filtered_reasons"].get("recommendation_polarity_mismatch"),
            1,
        )
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        breakdown_text = " ".join(
            [sections["call_breakdown"]["summary_line"]]
            + [" | ".join(row) for row in sections["call_breakdown"]["rows"]]
        )
        self.assertIn("Недостаточно подтверждённых фрагментов", breakdown_text)
        self.assertNotIn("Продолжать использовать четкое представление", breakdown_text)

    def test_step8ah11h_call_breakdown_cleans_punctuation_artifacts(self) -> None:
        artifact = _artifact(42.0, "problematic")
        artifact.interaction.text = (
            "Клиент: Скиньте в WhatsApp, я посмотрю. "
            "Менеджер: Вам удобно сейчас говорить? "
            "Клиент: Нет, напишите позже."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["score_by_stage"] = [
            {
                "stage_code": "qualification_primary",
                "stage_name": "Проверить возможность говорить.",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [],
            }
        ]
        detail["gaps"] = [
            {
                "criterion_code": "qp_current_process",
                "title": "Уместность разговора не проверена",
                "comment": "Менеджер не проверил возможность говорить.: Менеджер сразу перешёл к вопросу.",
            }
        ]
        detail["recommendations"] = [
            {
                "recommendation": "Сначала уточнить, удобно ли говорить, затем коротко обозначить цель звонка."
            }
        ]

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        self.assertEqual(payload["call_breakdown_quality"]["status"], "passed")
        sections = {section["id"]: section for section in build_report_render_model(payload)["sections"]}
        breakdown_text = " ".join(
            [sections["call_breakdown"]["summary_line"]]
            + [" | ".join(row) for row in sections["call_breakdown"]["rows"]]
        )
        self.assertNotIn("говорить.: Менеджер", breakdown_text)
        self.assertNotIn(".:", breakdown_text)
        self.assertIn("сначала уточнить", breakdown_text.lower())

    def test_manager_daily_payload_focus_stage_deep_dive_uses_stage_specific_fallbacks(self) -> None:
        artifact = _artifact(50.0, "problematic")
        artifact.analysis.scores_detail["score_by_stage"] = [
            {
                "stage_code": "completion_next_step",
                "stage_name": "Завершение и договорённости",
                "stage_score": 0,
                "max_stage_score": 2,
                "criteria_results": [
                    {
                        "criterion_code": "completion_next_step",
                        "criterion_name": "Фиксация следующего шага",
                        "score": 0,
                        "max_score": 2,
                    }
                ],
            }
        ]
        artifact.analysis.scores_detail["gaps"] = []
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[artifact],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        deep_dive = payload["focus_stage_deep_dive"]
        self.assertIsNotNone(deep_dive)
        self.assertEqual(deep_dive["stage_code"], "completion_next_step")
        self.assertEqual(deep_dive["what_went_wrong"], "Фиксация следующего шага.")
        self.assertEqual(
            deep_dive["minimum_for_tomorrow"],
            "В каждом подходящем sales-звонке зафиксировать конкретный следующий шаг, срок и ответственного.",
        )
        self.assertIn("конкретный следующий шаг", deep_dive["what_to_fix"])
        focus_rec = payload["focus_stage_recommendation"]
        self.assertIsNotNone(focus_rec)
        self.assertEqual(
            focus_rec["checklist"],
            [
                "Назвать конкретный следующий шаг",
                "Зафиксировать срок",
                "Подтвердить ответственного",
            ],
        )
        self.assertEqual(focus_rec["source"], "focus_stage_deep_dive")

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

    def test_classify_meaningful_call_excludes_short_source_only_contact(self) -> None:
        """Meaningful recalibration: CDR-only partial contacts need stronger talk-time evidence."""
        artifact = ReportArtifact(
            interaction=SimpleNamespace(
                id=uuid4(),
                duration_sec=60,
                text="",
                metadata_={
                    "source_status": "answered",
                    "direction": "out",
                },
            ),
            analysis=None,
            manager=_manager(),
            call_started_at=None,
        )

        is_meaningful, reason = _classify_meaningful_call(artifact)

        self.assertFalse(is_meaningful)
        self.assertEqual(reason, "too_short_or_no_speech")

    def test_classify_meaningful_call_keeps_long_source_only_live_contact(self) -> None:
        """Meaningful recalibration: long answered CDR-only calls stay in the manager-facing day list."""
        artifact = ReportArtifact(
            interaction=SimpleNamespace(
                id=uuid4(),
                duration_sec=MEANINGFUL_NO_TRANSCRIPT_MIN_DURATION_SEC,
                text="",
                metadata_={
                    "source_status": "answered",
                    "direction": "in",
                },
            ),
            analysis=None,
            manager=_manager(),
            call_started_at=None,
        )

        is_meaningful, reason = _classify_meaningful_call(artifact)

        self.assertTrue(is_meaningful)
        self.assertIsNone(reason)

    def test_classify_meaningful_call_excludes_non_answered_source_only_call(self) -> None:
        """Meaningful recalibration: missed/local source rows remain raw-only, not meaningful."""
        artifact = ReportArtifact(
            interaction=SimpleNamespace(
                id=uuid4(),
                duration_sec=MEANINGFUL_NO_TRANSCRIPT_MIN_DURATION_SEC + 30,
                text="",
                metadata_={
                    "source_status": "missed",
                    "direction": "out",
                },
            ),
            analysis=None,
            manager=_manager(),
            call_started_at=None,
        )

        is_meaningful, reason = _classify_meaningful_call(artifact)

        self.assertFalse(is_meaningful)
        self.assertEqual(reason, "too_short_or_no_speech")

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

    def test_unclassified_breakdown_counts_report_day_meaningful_calls_only(self) -> None:
        """Step 8C: unclassified diagnostics use report-day meaningful calls, not coaching window."""
        manager = _manager()
        coaching_artifact = _artifact_for_manager(
            manager,
            score_percent=82.0,
            level="strong",
            call_date="2026-03-24 10:00:00",
        )
        report_day_ready = _artifact_for_manager(
            manager,
            score_percent=78.0,
            level="basic",
            call_date="2026-03-25 09:00:00",
        )
        report_day_missing = ReportArtifact(
            interaction=_interaction(
                manager_id=manager.id,
                text="Клиент спрашивает про договор.",
                call_date="2026-03-25 11:00:00",
            ),
            analysis=None,
            manager=manager,
            call_started_at=datetime.fromisoformat("2026-03-25T11:00:00").replace(tzinfo=UTC),
        )
        previous_day_missing = ReportArtifact(
            interaction=_interaction(
                manager_id=manager.id,
                text="Предыдущий день, тоже без анализа.",
                call_date="2026-03-24 12:00:00",
            ),
            analysis=None,
            manager=manager,
            call_started_at=datetime.fromisoformat("2026-03-24T12:00:00").replace(tzinfo=UTC),
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[coaching_artifact, report_day_ready],
            period={"date_from": "2026-03-24", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=[coaching_artifact, report_day_ready, report_day_missing, previous_day_missing],
        )

        self.assertEqual(payload["unclassified_breakdown"]["total"], 1)
        self.assertEqual(payload["unclassified_breakdown"]["by_reason"], {"no_analysis": 1})
        self.assertEqual(payload["call_outcomes_summary"]["unclassified_count"], 1)

    def test_call_list_adds_unclassified_reason_for_no_analysis(self) -> None:
        """Step 8C: unclassified call_list rows explain why status is unavailable."""
        ready = _artifact(82.0, "strong")
        missing_analysis = ReportArtifact(
            interaction=_interaction(
                manager_id=ready.interaction.manager_id,
                text="Есть транскрипт, но нет готового анализа.",
                call_date="2026-03-25 11:00:00",
            ),
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T11:00:00").replace(tzinfo=UTC),
        )

        rows = _build_meaningful_call_list(window_artifacts=[ready, missing_analysis])
        unclassified = [row for row in rows if row["status"] is None]

        self.assertEqual(len(unclassified), 1)
        self.assertEqual(unclassified[0]["unclassified_reason_code"], "no_analysis")
        self.assertEqual(unclassified[0]["unclassified_reason_label"], "Нет готового анализа")

    def test_call_list_adds_cdr_only_reason_for_probable_live_without_audio(self) -> None:
        """Step 8C: CDR-only probable live calls are separated from generic no_analysis."""
        ready = _artifact(82.0, "strong")
        interaction = _interaction(
            manager_id=ready.interaction.manager_id,
            text="",
            call_date="2026-03-25 11:00:00",
        )
        interaction.duration_sec = 180
        interaction.metadata_["source_status"] = "answered"
        interaction.metadata_["direction"] = "out"
        cdr_only = ReportArtifact(
            interaction=interaction,
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T11:00:00").replace(tzinfo=UTC),
        )

        rows = _build_meaningful_call_list(window_artifacts=[ready, cdr_only])
        unclassified = [row for row in rows if row["status"] is None]

        self.assertEqual(unclassified[0]["unclassified_reason_code"], "cdr_only_probable_live")
        self.assertEqual(unclassified[0]["unclassified_reason_label"], "CDR-only: вероятный живой разговор")

    def test_call_list_adds_analysis_not_reusable_reason(self) -> None:
        """Step 8C: rejected persisted analysis is visible as diagnostic reason."""
        ready = _artifact(82.0, "strong")
        rejected = _analysis(0.0, "problematic", strengths=[], gaps=[], recommendations=[])
        rejected.scores_detail = {"classification": {}, "follow_up": {}}
        interaction = _interaction(
            manager_id=ready.interaction.manager_id,
            text="Транскрипт есть, но persisted analysis старого формата.",
            call_date="2026-03-25 12:00:00",
        )
        artifact = ReportArtifact(
            interaction=interaction,
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T12:00:00").replace(tzinfo=UTC),
            original_analysis=rejected,
            analysis_reuse_reason="missing_required_keys:score,score_by_stage",
        )

        rows = _build_meaningful_call_list(window_artifacts=[ready, artifact])
        unclassified = [row for row in rows if row["status"] is None]

        self.assertEqual(unclassified[0]["unclassified_reason_code"], "analysis_not_reusable")
        self.assertEqual(unclassified[0]["unclassified_reason_label"], "Анализ не проходит reuse-проверку")

    def test_unclassified_manager_buckets_are_added_to_call_list(self) -> None:
        """Step 8G: diagnostic reasons get manager-facing status buckets."""
        ready = _artifact(82.0, "strong")
        no_transcript_interaction = _interaction(
            manager_id=ready.interaction.manager_id,
            text="",
            call_date="2026-03-25 11:00:00",
        )
        no_transcript_interaction.raw_ref = "onlinepbx://audio.wav"
        no_transcript = ReportArtifact(
            interaction=no_transcript_interaction,
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T11:00:00").replace(tzinfo=UTC),
        )
        no_analysis = ReportArtifact(
            interaction=_interaction(
                manager_id=ready.interaction.manager_id,
                text="Есть транскрипт, но нет анализа.",
                call_date="2026-03-25 12:00:00",
            ),
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T12:00:00").replace(tzinfo=UTC),
        )
        rejected = _analysis(0.0, "problematic", strengths=[], gaps=[], recommendations=[])
        non_reusable = ReportArtifact(
            interaction=_interaction(
                manager_id=ready.interaction.manager_id,
                text="Транскрипт есть, но звонок не подходит для разбора.",
                call_date="2026-03-25 13:00:00",
            ),
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T13:00:00").replace(tzinfo=UTC),
            original_analysis=rejected,
            analysis_reuse_reason="semantic_empty:not_coachable_or_reportable",
        )
        failed = _analysis(0.0, "problematic", strengths=[], gaps=[], recommendations=[])
        failed.is_failed = True
        failed.fail_reason = "Criterion intro missing required fields: comment"
        analysis_failed = ReportArtifact(
            interaction=_interaction(
                manager_id=ready.interaction.manager_id,
                text="Транскрипт есть, analysis упал.",
                call_date="2026-03-25 14:00:00",
            ),
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T14:00:00").replace(tzinfo=UTC),
            original_analysis=failed,
            analysis_reuse_reason="contract_validation_error",
        )
        provider_failed = _analysis(0.0, "problematic", strengths=[], gaps=[], recommendations=[])
        provider_failed.is_failed = True
        provider_failed.fail_reason = "OpenAI 429 insufficient_quota"
        provider_error = ReportArtifact(
            interaction=_interaction(
                manager_id=ready.interaction.manager_id,
                text="Транскрипт есть, provider вернул ошибку.",
                call_date="2026-03-25 15:00:00",
            ),
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T15:00:00").replace(tzinfo=UTC),
            original_analysis=provider_failed,
            analysis_reuse_reason="provider_error",
        )

        rows = _build_meaningful_call_list(
            window_artifacts=[ready, no_transcript, no_analysis, non_reusable, analysis_failed, provider_error]
        )
        buckets = {
            row["unclassified_reason_code"]: row["unclassified_status_label"]
            for row in rows
            if row["status"] is None
        }

        self.assertEqual(buckets["no_transcript"], "Без транскрипта")
        self.assertEqual(buckets["no_analysis"], "Без анализа")
        self.assertEqual(buckets["semantic_empty"], "Не подходит для разбора")
        self.assertEqual(buckets["analysis_failed_contract"], "Ошибка анализа")
        self.assertEqual(buckets["analysis_failed_provider"], "Ошибка провайдера")

    def test_day_summary_uses_without_breakdown_bucket_and_preserves_total(self) -> None:
        """Step 8G: dashboard keeps arithmetic while replacing НЕ КЛАСС. with a breakdown."""
        ready = _artifact(82.0, "strong")
        missing = ReportArtifact(
            interaction=_interaction(
                manager_id=ready.interaction.manager_id,
                text="Есть транскрипт, но нет анализа.",
                call_date="2026-03-25 11:00:00",
            ),
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T11:00:00").replace(tzinfo=UTC),
        )
        rejected = _analysis(0.0, "problematic", strengths=[], gaps=[], recommendations=[])
        non_reusable = ReportArtifact(
            interaction=_interaction(
                manager_id=ready.interaction.manager_id,
                text="Транскрипт есть, но звонок не подходит для разбора.",
                call_date="2026-03-25 12:00:00",
            ),
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T12:00:00").replace(tzinfo=UTC),
            original_analysis=rejected,
            analysis_reuse_reason="not_coachable_or_reportable",
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[ready],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=[ready, missing, non_reusable],
        )
        report = build_report_render_model(payload)
        day_summary = {section["id"]: section for section in report["sections"]}["day_summary"]
        labels = [item["label"] for item in day_summary["outcome_cols"]]
        values = [int(item["value"]) for item in day_summary["outcome_cols"]]

        self.assertIn("БЕЗ РАЗБОРА", labels)
        self.assertNotIn("НЕ КЛАСС.", labels)
        self.assertIn("1 без анализа", day_summary["breakdown_note"])
        self.assertIn("1 не подходит для разбора", day_summary["breakdown_note"])
        self.assertEqual(sum(values[1:]), payload["selection_model"]["meaningful_calls_total"])

    def test_call_list_render_status_matches_unclassified_bucket(self) -> None:
        """Step 8G: СПИСОК ЗВОНКОВ ДНЯ shows concrete bucket, not generic gray status."""
        ready = _artifact(82.0, "strong")
        missing = ReportArtifact(
            interaction=_interaction(
                manager_id=ready.interaction.manager_id,
                text="Есть транскрипт, но нет анализа.",
                call_date="2026-03-25 11:00:00",
            ),
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T11:00:00").replace(tzinfo=UTC),
        )
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[ready],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=[ready, missing],
        )
        report = build_report_render_model(payload)
        call_list = {section["id"]: section for section in report["sections"]}["call_list"]
        missing_row = [row for row in call_list["rows"] if row[4] == "Без анализа"][0]

        self.assertEqual(missing_row[3], "Нет готового анализа")

    def test_manager_facing_completeness_gate_passes_with_non_coachable_bucket(self) -> None:
        """Step 8I: non-coachable/semantic-empty calls may remain in a manager-facing report."""
        ready = _artifact(82.0, "strong")
        failed = _analysis(0.0, "problematic", strengths=[], gaps=[], recommendations=[])
        failed.is_failed = True
        failed.fail_reason = "not_coachable_or_reportable: semantic_empty"
        non_coachable = ReportArtifact(
            interaction=_interaction(
                manager_id=ready.interaction.manager_id,
                text="Расшифрованный звонок без sales-содержания.",
                call_date="2026-03-25 11:00:00",
            ),
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T11:00:00").replace(tzinfo=UTC),
            original_analysis=failed,
            analysis_reuse_reason="semantic_empty:not_coachable_or_reportable",
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[ready],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=[ready, non_coachable],
        )

        self.assertEqual(payload["manager_facing_completeness"]["status"], "passed")
        self.assertTrue(payload["manager_facing_completeness"]["manager_report_allowed"])
        self.assertEqual(payload["call_outcomes_summary"]["unclassified_by_bucket"]["Не подходит для разбора"], 1)

    def test_manager_facing_completeness_gate_fails_on_incomplete_and_technical_buckets(self) -> None:
        """Step 8I: incomplete/technical buckets block ordinary manager-facing delivery."""
        ready = _artifact(82.0, "strong")
        no_transcript_interaction = _interaction(
            manager_id=ready.interaction.manager_id,
            text="",
            call_date="2026-03-25 11:00:00",
        )
        no_transcript_interaction.raw_ref = "onlinepbx://audio.wav"
        no_transcript = ReportArtifact(
            interaction=no_transcript_interaction,
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T11:00:00").replace(tzinfo=UTC),
        )
        no_analysis = ReportArtifact(
            interaction=_interaction(
                manager_id=ready.interaction.manager_id,
                text="Транскрипт есть, анализа нет.",
                call_date="2026-03-25 12:00:00",
            ),
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T12:00:00").replace(tzinfo=UTC),
        )
        failed = _analysis(0.0, "problematic", strengths=[], gaps=[], recommendations=[])
        failed.is_failed = True
        failed.fail_reason = "Criterion greeting missing required fields: comment"
        contract_error = ReportArtifact(
            interaction=_interaction(
                manager_id=ready.interaction.manager_id,
                text="Транскрипт есть, contract validation упал.",
                call_date="2026-03-25 13:00:00",
            ),
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T13:00:00").replace(tzinfo=UTC),
            original_analysis=failed,
            analysis_reuse_reason="contract_validation_error",
        )

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[ready],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=[ready, no_transcript, no_analysis, contract_error],
        )
        gate = payload["manager_facing_completeness"]

        self.assertEqual(gate["status"], "review_required")
        self.assertFalse(gate["manager_report_allowed"])
        self.assertEqual(gate["reason"], "incomplete_day_call_processing")
        self.assertEqual(gate["blocking_counts"]["no_transcript"], 1)
        self.assertEqual(gate["blocking_counts"]["no_analysis"], 1)
        self.assertEqual(gate["blocking_counts"]["analysis_error"], 1)
        self.assertEqual(gate["affected_calls_count"], 3)

    def test_manager_daily_coaching_core_excludes_support_not_eligible_calls(self) -> None:
        """Selection bugfix: support/not_eligible can be meaningful, but not coaching_core."""
        coaching_artifact = _artifact(82.0, "strong")
        support_interaction = _interaction(
            manager_id=coaching_artifact.interaction.manager_id,
            text="Клиент задаёт технический вопрос по документам.",
        )
        support_analysis = _analysis(50.0, "basic")
        support_detail = dict(support_analysis.scores_detail)
        support_detail["classification"] = {
            "call_type": "support",
            "scenario_type": "hot_incoming_contact",
            "analysis_eligibility": "not_eligible",
        }
        support_analysis = SimpleNamespace(
            id=uuid4(),
            interaction_id=support_interaction.id,
            instruction_version="analysis_v1",
            score_total=50.0,
            scores_detail=support_detail,
            is_failed=False,
            fail_reason=None,
        )
        support_artifact = ReportArtifact(
            interaction=support_interaction,
            analysis=support_analysis,
            manager=coaching_artifact.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T09:00:00").replace(tzinfo=UTC),
        )

        missing, usable = CallsManualReportingOrchestrator._split_usable_artifacts(
            [coaching_artifact, support_artifact],
            require_coaching_core_eligible=True,
        )
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=usable,
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=[coaching_artifact, support_artifact],
        )

        self.assertEqual([item.interaction.id for item in usable], [coaching_artifact.interaction.id])
        self.assertIn(f"coaching_core_not_eligible:{support_artifact.interaction.id}", missing)
        self.assertEqual(len(payload["call_list"]), 2)
        self.assertEqual(payload["selection_model"]["meaningful_calls_total"], 2)
        self.assertEqual(payload["selection_model"]["included_in_report_total"], 1)
        self.assertEqual(payload["selection_model"]["service_calls_total"], 1)

    def test_manager_daily_source_filters_do_not_apply_hardcoded_duration_cutoff(self) -> None:
        """Source scope keeps short calls unless explicit UI duration filters are set."""
        short_record = CDRRecord(
            call_id="short-call",
            call_date="2026-03-25T10:00:00+00:00",
            duration=45,
            talk_duration=23,
            direction="out",
            status="answered",
            extension="322",
            phone="+77070000000",
        )
        missed_record = CDRRecord(
            call_id="missed-call",
            call_date="2026-03-25T11:00:00+00:00",
            duration=15,
            talk_duration=0,
            direction="out",
            status="missed",
            extension="322",
            phone="+77070000001",
        )

        self.assertTrue(
            CallsManualReportingOrchestrator._record_matches_source_scope(
                record=short_record,
                source_extensions={"322"},
            )
        )
        self.assertTrue(
            CallsManualReportingOrchestrator._record_matches_source_filters(
                record=short_record,
                filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            )
        )
        self.assertFalse(
            CallsManualReportingOrchestrator._record_matches_source_filters(
                record=short_record,
                filters=ReportRunFilters(
                    date_from="2026-03-25",
                    date_to="2026-03-25",
                    min_duration_sec=180,
                ),
            )
        )
        self.assertTrue(
            CallsManualReportingOrchestrator._record_matches_source_filters(
                record=missed_record,
                filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            )
        )

    def test_prepare_artifacts_skips_audio_build_for_source_only_calls(self) -> None:
        """Source-only missed/no-recording calls stay in raw scope without STT failure."""
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        interaction = _interaction(text="")
        interaction.raw_ref = None
        interaction.metadata_ = {
            **dict(interaction.metadata_ or {}),
            "source_status": "missed",
            "direction": "out",
        }
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
                preset=resolve_report_preset("manager_daily"),
                mode="build_missing_and_report",
            )

        import asyncio

        artifacts, build_summary, build_errors = asyncio.run(_run())

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(build_summary["missing_transcripts_before_build"], 1)
        self.assertEqual(build_summary["transcripts_built"], 0)
        self.assertEqual(build_summary["transcript_build_failed"], 0)
        self.assertEqual(build_errors, [])

    def test_prepare_artifacts_refreshes_onlinepbx_audio_url_before_stt(self) -> None:
        """Step 8L: selected OnlinePBX calls refresh expired direct URLs before STT."""
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        interaction = _interaction(text="", call_date="2026-03-25 10:00:00")
        interaction.source = "onlinepbx"
        interaction.external_id = "98aa9872-5406-4eef-9c0b-30f44175b3a9"
        interaction.raw_ref = "https://api2.onlinepbx.ru/calls-records/download/expired/rec.mp3"
        interaction.error_message = "Failed to download audio artifact: status=404 KEY_IS_EXPIRED"
        interaction.metadata_ = {
            **dict(interaction.metadata_ or {}),
            "external_call_code": interaction.external_id,
            "source_status": "answered",
            "direction": "out",
        }
        commits: list[bool] = []
        processed: list[str] = []

        class FakeExtractor:
            async def process(self, item):
                processed.append(item.raw_ref)
                item.text = "Расшифрованный звонок"

        setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **kwargs: {})
        setattr(orchestrator, "_load_managers_by_id", lambda **kwargs: {})
        orchestrator.db = SimpleNamespace(commit=lambda: commits.append(True))
        orchestrator.intake = SimpleNamespace(
            get_recording_url=lambda call_id: f"https://fresh.example.test/{call_id}/rec.mp3"
        )
        orchestrator.extractor = FakeExtractor()
        orchestrator.analyzer = SimpleNamespace(analyze_call=lambda *_args, **_kwargs: _analysis(80.0, "strong"))
        orchestrator.call_orchestrator = SimpleNamespace(
            persist_analysis=lambda **kwargs: kwargs["result"]
        )

        async def _run():
            return await CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[interaction],
                preset=resolve_report_preset("manager_daily"),
                mode="build_missing_and_report",
            )

        import asyncio

        _artifacts, build_summary, build_errors = asyncio.run(_run())

        self.assertEqual(processed, [f"https://fresh.example.test/{interaction.external_id}/rec.mp3"])
        self.assertEqual(build_summary["transcripts_built"], 1)
        self.assertEqual(build_summary["analyses_built"], 1)
        self.assertEqual(build_errors, [])
        self.assertGreaterEqual(len(commits), 1)
        self.assertEqual(interaction.metadata_["source_audio_url_refresh"]["status"], "refreshed")
        self.assertIsNone(interaction.error_message)

    def test_prepare_artifacts_records_source_audio_unavailable_when_refresh_fails(self) -> None:
        """Step 8L: refresh failure becomes an operator diagnostic and STT is skipped."""
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        interaction = _interaction(text="", call_date="2026-03-25 10:00:00")
        interaction.source = "onlinepbx"
        interaction.external_id = "98aa9872-5406-4eef-9c0b-30f44175b3a9"
        interaction.raw_ref = None
        interaction.error_message = None
        interaction.metadata_ = {
            **dict(interaction.metadata_ or {}),
            "external_call_code": interaction.external_id,
            "source_status": "answered",
            "direction": "out",
        }

        class FakeExtractor:
            async def process(self, _item):
                raise AssertionError("STT should not run when audio refresh fails")

        def _raise_refresh_error(_call_id):
            raise ASAError("OnlinePBX recording lookup failed: KEY_IS_EXPIRED")

        setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **kwargs: {})
        setattr(orchestrator, "_load_managers_by_id", lambda **kwargs: {})
        orchestrator.db = SimpleNamespace(commit=lambda: None)
        orchestrator.intake = SimpleNamespace(get_recording_url=_raise_refresh_error)
        orchestrator.extractor = FakeExtractor()
        orchestrator.analyzer = SimpleNamespace(analyze_call=lambda *_args, **_kwargs: None)
        orchestrator.call_orchestrator = SimpleNamespace(persist_analysis=lambda *_args, **_kwargs: None)

        async def _run():
            return await CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[interaction],
                preset=resolve_report_preset("manager_daily"),
                mode="build_missing_and_report",
            )

        import asyncio

        _artifacts, build_summary, build_errors = asyncio.run(_run())

        self.assertEqual(build_summary["transcripts_built"], 0)
        self.assertEqual(build_summary["transcript_build_failed"], 1)
        self.assertTrue(any(item.startswith("source_audio_unavailable:") for item in build_errors))
        self.assertEqual(
            interaction.metadata_["source_audio_unavailable"]["reason"],
            "recording_url_refresh_failed",
        )
        self.assertEqual(interaction.error_message, "source_audio_unavailable:recording_url_refresh_failed")

    def test_provider_error_classifier_detects_openai_insufficient_quota(self) -> None:
        error = (
            "Whisper STT failed: Error code: 429 - {'error': {'message': 'You exceeded your current quota', "
            "'type': 'insufficient_quota', 'code': 'insufficient_quota'}}"
        )

        classified = classify_provider_error(error)

        self.assertEqual(classified.error_class, "quota_insufficient")

    def test_provider_error_classifier_separates_non_quota_rate_limit(self) -> None:
        classified = classify_provider_error("Error code: 429 - rate_limit_exceeded")

        self.assertEqual(classified.error_class, "rate_limited")

    def test_prepare_artifacts_stops_stt_after_quota_and_marks_remaining(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        first = _interaction(text="", call_date="2026-03-25 10:00:00")
        second = _interaction(text="", call_date="2026-03-25 10:05:00")
        for item in (first, second):
            item.raw_ref = "https://example.test/audio.mp3"
            item.metadata_ = {
                **dict(item.metadata_ or {}),
                "source_status": "answered",
                "direction": "out",
            }
        calls: list[str] = []

        class FakeExtractor:
            async def process(self, interaction):
                calls.append(str(interaction.id))
                raise ASAError("Whisper STT failed: Error code: 429 - {'error': {'code': 'insufficient_quota'}}")

        setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **kwargs: {})
        setattr(orchestrator, "_load_managers_by_id", lambda **kwargs: {})
        orchestrator.extractor = FakeExtractor()
        orchestrator.analyzer = SimpleNamespace(analyze_call=lambda *_args, **_kwargs: None)
        orchestrator.call_orchestrator = SimpleNamespace(persist_analysis=lambda *_args, **_kwargs: None)

        async def _run():
            return await CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[first, second],
                preset=resolve_report_preset("manager_daily"),
                mode="build_missing_and_report",
            )

        import asyncio

        _artifacts, build_summary, build_errors = asyncio.run(_run())

        self.assertEqual(len(calls), 1)
        self.assertEqual(build_summary["transcript_build_failed"], 1)
        self.assertEqual(build_summary["skipped_due_to_quota"], 1)
        self.assertEqual(build_summary["quota_blocker"]["type"], "quota_blocked")
        self.assertTrue(any(item.startswith("quota_blocked_current_run:") for item in build_errors))
        self.assertEqual(second.metadata_["last_provider_failure"]["error_class"], "quota_insufficient")

    def test_prepare_artifacts_stops_llm_after_quota_and_keeps_transcript(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        first = _interaction(text="Готовый транскрипт", call_date="2026-03-25 10:00:00")
        second = _interaction(text="Второй транскрипт", call_date="2026-03-25 10:05:00")
        calls: list[str] = []

        def _raise_quota(interaction):
            calls.append(str(interaction.id))
            raise ASAError("LLM-1 request failed: Error code: 429 - {'error': {'code': 'insufficient_quota'}}")

        setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **kwargs: {})
        setattr(orchestrator, "_load_managers_by_id", lambda **kwargs: {})
        orchestrator.extractor = SimpleNamespace(process=lambda *_args, **_kwargs: None)
        orchestrator.analyzer = SimpleNamespace(analyze_call=_raise_quota)
        orchestrator.call_orchestrator = SimpleNamespace(persist_analysis=lambda *_args, **_kwargs: None)

        async def _run():
            return await CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[first, second],
                preset=resolve_report_preset("manager_daily"),
                mode="build_missing_and_report",
            )

        import asyncio

        _artifacts, build_summary, build_errors = asyncio.run(_run())

        self.assertEqual(len(calls), 1)
        self.assertEqual(first.text, "Готовый транскрипт")
        self.assertEqual(build_summary["analysis_build_failed"], 1)
        self.assertEqual(build_summary["skipped_due_to_quota"], 1)
        self.assertTrue(any(item.startswith("quota_blocked_current_run:") for item in build_errors))

    def test_prepare_artifacts_persists_contract_validation_failure_as_analysis_error(self) -> None:
        """Step 8N: contract validation failures are persisted and surfaced as Ошибка анализа."""
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        interaction = _interaction(text="Готовый транскрипт", call_date="2026-03-25 10:00:00")
        persisted: list[SimpleNamespace] = []

        def _raise_contract_error(item):
            raise LLMResponseError(
                "Criterion cs_intro_and_company in stage contact_start is missing required fields: comment",
                interaction_id=str(item.id),
                raw_response='{"score_by_stage":[]}',
            )

        def _persist_failed_analysis(**kwargs):
            failed = _analysis(0.0, "problematic", strengths=[], gaps=[], recommendations=[])
            failed.is_failed = True
            failed.fail_reason = kwargs.get("fail_reason") or str(kwargs["error"])
            failed.scores_detail = None
            persisted.append(failed)
            return failed

        setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **kwargs: {})
        setattr(orchestrator, "_load_managers_by_id", lambda **kwargs: {})
        orchestrator.extractor = SimpleNamespace(process=lambda *_args, **_kwargs: None)
        orchestrator.analyzer = SimpleNamespace(analyze_call=_raise_contract_error)
        orchestrator.call_orchestrator = SimpleNamespace(
            persist_analysis=lambda *_args, **_kwargs: None,
            persist_failed_analysis=_persist_failed_analysis,
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
        rows = _build_meaningful_call_list(window_artifacts=artifacts)

        self.assertEqual(build_summary["analysis_build_failed"], 1)
        self.assertEqual(len(persisted), 1)
        self.assertTrue(persisted[0].fail_reason.startswith("analysis_failed_contract:"))
        self.assertTrue(any("analysis_failed_contract:" in item for item in build_errors))
        self.assertEqual(rows[0]["unclassified_reason_code"], "analysis_failed_contract")
        self.assertEqual(rows[0]["unclassified_status_label"], "Ошибка анализа")

    def test_prepare_artifacts_non_quota_error_does_not_trip_circuit_breaker(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        first = _interaction(text="", call_date="2026-03-25 10:00:00")
        second = _interaction(text="", call_date="2026-03-25 10:05:00")
        for item in (first, second):
            item.raw_ref = "https://example.test/audio.mp3"
            item.metadata_ = {
                **dict(item.metadata_ or {}),
                "source_status": "answered",
                "direction": "out",
            }
        calls: list[str] = []

        class FakeExtractor:
            async def process(self, interaction):
                calls.append(str(interaction.id))
                raise ASAError("temporary provider timeout")

        setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **kwargs: {})
        setattr(orchestrator, "_load_managers_by_id", lambda **kwargs: {})
        orchestrator.extractor = FakeExtractor()
        orchestrator.analyzer = SimpleNamespace(analyze_call=lambda *_args, **_kwargs: None)
        orchestrator.call_orchestrator = SimpleNamespace(persist_analysis=lambda *_args, **_kwargs: None)

        async def _run():
            return await CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[first, second],
                preset=resolve_report_preset("manager_daily"),
                mode="build_missing_and_report",
            )

        import asyncio

        _artifacts, build_summary, _build_errors = asyncio.run(_run())

        self.assertEqual(len(calls), 2)
        self.assertEqual(build_summary["transcript_build_failed"], 2)
        self.assertEqual(build_summary["skipped_due_to_quota"], 0)
        self.assertIsNone(build_summary["quota_blocker"])

    def test_prepare_artifacts_skips_previous_quota_failure_without_force(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        interaction = _interaction(text="", call_date="2026-03-25 10:00:00")
        interaction.raw_ref = "https://example.test/audio.mp3"
        interaction.metadata_ = {
            **dict(interaction.metadata_ or {}),
            "source_status": "answered",
            "direction": "out",
            "last_provider_failure": {
                "type": "quota_blocked",
                "stage": "stt",
                "error_class": "quota_insufficient",
            },
        }
        setattr(orchestrator, "_load_latest_analyses_by_interaction", lambda **kwargs: {})
        setattr(orchestrator, "_load_managers_by_id", lambda **kwargs: {})
        orchestrator.extractor = SimpleNamespace(
            process=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("quota-blocked call should not retry"))
        )
        orchestrator.analyzer = SimpleNamespace(analyze_call=lambda *_args, **_kwargs: None)
        orchestrator.call_orchestrator = SimpleNamespace(persist_analysis=lambda *_args, **_kwargs: None)

        async def _run():
            return await CallsManualReportingOrchestrator._prepare_artifacts(
                orchestrator,
                interactions=[interaction],
                preset=resolve_report_preset("manager_daily"),
                mode="build_missing_and_report",
            )

        import asyncio

        _artifacts, build_summary, build_errors = asyncio.run(_run())

        self.assertEqual(build_summary["quota_blocked_previous_run"], 1)
        self.assertEqual(build_summary["skipped_due_to_quota"], 1)
        self.assertTrue(any(item.startswith("quota_blocked_previous_run:") for item in build_errors))

    def test_quota_blocker_response_has_no_secret_value(self) -> None:
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        blocker = CallsManualReportingOrchestrator._build_quota_blocker(
            stage="stt",
            provider_context={
                "provider": "openai",
                "account_alias": "stt_main",
                "model": "whisper-1",
                "api_key_env": "OPENAI_API_KEY_STT_MAIN",
            },
            error_info=classify_provider_error("429 insufficient_quota"),
        )

        text = str(blocker)
        self.assertIn("OPENAI_API_KEY_STT_MAIN", text)
        self.assertNotIn("sk-", text)
        self.assertNotIn("test-key", text)

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

    def test_sm3_call_list_sorted_by_status_order_then_time(self) -> None:
        """Step 8AH-2: call_list rows are grouped by status order, then by time."""
        agreed = _artifact(82.0, "strong", call_date="2026-03-25 11:00:00")
        refusal = _artifact(70.0, "basic", call_date="2026-03-25 09:00:00")
        open_early = _artifact(65.0, "basic", call_date="2026-03-25 08:00:00")
        open_late = _artifact(65.0, "basic", call_date="2026-03-25 15:00:00")
        refusal.interaction.text = "Клиент: сейчас не рассматриваем, нет необходимости."
        refusal.analysis.scores_detail["follow_up"] = {
            "next_step_fixed": False,
            "reason_not_fixed": "Клиент не заинтересован.",
        }
        for item in (open_early, open_late):
            item.interaction.text = "Клиент: скиньте на WhatsApp, я посмотрю."
            item.analysis.scores_detail["follow_up"] = {
                "next_step_fixed": False,
                "next_step_text": "Скиньте на WhatsApp, клиент посмотрит.",
            }

        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[open_late, refusal, agreed, open_early],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )

        self.assertEqual([row["status"] for row in payload["call_list"]], ["agreed", "refusal", "open", "open"])
        self.assertEqual(
            [row["time"] for row in payload["call_list"][2:]],
            sorted(row["time"] for row in payload["call_list"][2:]),
            "rows inside the same status group must stay sorted by time",
        )

    def test_step8ah8a_business_outcome_ignores_synthetic_recommendation_refusal_terms(self) -> None:
        """Step 8AH-8A: synthetic coaching text must not flip an open follow-up to refusal."""
        artifact = _artifact(70.0, "basic", call_date="2026-05-04 12:09:44")
        artifact.interaction.text = (
            "Менеджер: хотел предложить вам посотрудничать по ЭДО. "
            "Клиент: Вы можете отправить предложение, я вам написала почту. "
            "Менеджер: Хорошо, сейчас посмотрю."
        )
        detail = artifact.analysis.scores_detail
        detail["classification"] = {
            "call_type": "sales_primary",
            "scenario_type": "cold_outbound",
            "analysis_eligibility": "eligible",
        }
        detail["summary"] = {
            "outcome_code": "callback_planned",
            "outcome_text": "Клиент согласился на получение предложения по электронной почте.",
            "next_step_text": "Клиенту будет отправлено предложение по электронной почте.",
        }
        detail["follow_up"] = {
            "next_step_fixed": True,
            "next_step_type": "email_follow_up",
            "next_step_text": "Отправить предложение по электронной почте.",
            "due_date_text": "2026-05-05",
            "reason_not_fixed": None,
        }
        detail["recommendations"] = [
            {
                "recommendation": "Сначала уточнить процесс клиента.",
                "why_it_matters": "Это может привести к тому, что предложение будет неактуально для клиента.",
            }
        ]

        outcome = BusinessOutcomeResolver().resolve(artifact)

        self.assertEqual(outcome.final_status, "open")
        self.assertEqual(outcome.reason_code, "business_outcome_open_follow_up")

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

    # --- SM-4 acceptance tests ---

    def test_sm4_full_report_note_uses_selection_model_funnel(self) -> None:
        """SM-4: full_report selection_note uses selection_model counters for honest funnel."""
        coaching = _artifact(82.0, "strong")
        beep = ReportArtifact(
            interaction=SimpleNamespace(id=uuid4(), duration_sec=5, text=""),
            analysis=None,
            manager=coaching.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T07:00:00").replace(tzinfo=UTC),
        )
        all_window = [coaching, beep]
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[coaching],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=all_window,
        )
        payload.setdefault("meta", {})["readiness"] = {
            "readiness_outcome": "full_report",
            "window_days_used": 1,
            "relevant_calls": 2,
            "ready_analyses": 1,
            "total_group_calls": 2,
        }
        report = build_report_render_model(payload)
        sections = {s["id"]: s for s in report["sections"]}
        note = sections["report_header"].get("selection_note") or ""
        self.assertIn("Найдено в телефонии: 2", note)
        self.assertIn("содержательных: 1", note)
        self.assertIn("вошло в разбор: 1", note)
        self.assertNotIn("Сигнальный отчёт", note)
        self.assertNotIn("too_short_or_no_speech", note)
        self.assertNotIn("ivr_or_autoanswer", note)

    def test_sm4_signal_report_note_prefixed_and_uses_funnel(self) -> None:
        """SM-4: signal_report selection_note prefixed with 'Сигнальный отчёт' and shows funnel."""
        coaching = _artifact(82.0, "strong")
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[coaching],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        payload.setdefault("meta", {})["readiness"] = {
            "readiness_outcome": "signal_report",
            "window_days_used": 1,
            "relevant_calls": 1,
            "ready_analyses": 1,
            "total_group_calls": 1,
        }
        report = build_report_render_model(payload)
        sections = {s["id"]: s for s in report["sections"]}
        note = sections["report_header"].get("selection_note") or ""
        self.assertIn("Сигнальный отчёт", note)
        self.assertIn("Найдено в телефонии:", note)
        self.assertIn("вошло в разбор:", note)
        self.assertNotIn("too_short_or_no_speech", note)

    def test_sm4_note_shows_exclusion_reasons_as_manager_labels(self) -> None:
        """SM-4: exclusion reasons in note use manager-facing labels, not raw codes."""
        coaching = _artifact(82.0, "strong")
        no_analysis = ReportArtifact(
            interaction=_interaction(),
            analysis=None,
            manager=coaching.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T08:00:00").replace(tzinfo=UTC),
        )
        all_window = [coaching, no_analysis]
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[coaching],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            window_artifacts=all_window,
        )
        payload.setdefault("meta", {})["readiness"] = {
            "readiness_outcome": "full_report",
            "window_days_used": 1,
            "relevant_calls": 2,
            "ready_analyses": 1,
            "total_group_calls": 2,
        }
        report = build_report_render_model(payload)
        sections = {s["id"]: s for s in report["sections"]}
        note = sections["report_header"].get("selection_note") or ""
        self.assertIn("нет готового анализа", note)
        self.assertNotIn("not_enough_analysis", note)
        self.assertIn("Не вошло:", note)

    def test_sm4_skip_accumulate_has_no_selection_note(self) -> None:
        """SM-4: skip_accumulate does not produce a selection_note (not a deliverable report)."""
        coaching = _artifact(82.0, "strong")
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[coaching],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        payload.setdefault("meta", {})["readiness"] = {
            "readiness_outcome": "skip_accumulate",
            "window_days_used": 1,
            "relevant_calls": 1,
            "ready_analyses": 1,
        }
        report = build_report_render_model(payload)
        sections = {s["id"]: s for s in report["sections"]}
        note = sections["report_header"].get("selection_note")
        self.assertIsNone(note)

    # --- SM-5 acceptance tests ---

    def test_sm5_one_day_window_has_no_extra_window_note(self) -> None:
        """SM-5: one-day full report does not add noisy coaching-window wording."""
        coaching = _artifact(82.0, "strong")
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[coaching],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        payload.setdefault("meta", {})["readiness"] = {
            "readiness_outcome": "full_report",
            "window_days_used": 1,
            "window_start": "2026-03-25",
            "window_end": "2026-03-25",
            "effective_period": {"date_from": "2026-03-25", "date_to": "2026-03-25"},
            "relevant_calls": 1,
            "ready_analyses": 1,
            "total_group_calls": 1,
        }
        report = build_report_render_model(payload)
        sections = {s["id"]: s for s in report["sections"]}
        note = sections["report_header"].get("selection_note") or ""
        self.assertNotIn("Коучинговый разбор собран", note)
        self.assertNotIn("Список звонков ниже", note)

    def test_sm5_expanded_window_note_explains_day_list_and_coaching_base(self) -> None:
        """SM-5: expanded coaching window is visible without technical rolling-window wording."""
        coaching = _artifact(82.0, "strong")
        payload = build_manager_daily_payload(
            department_id=str(uuid4()),
            department_name="Отдел продаж",
            artifacts=[coaching],
            period={"date_from": "2026-03-24", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
        )
        payload.setdefault("meta", {})["readiness"] = {
            "readiness_outcome": "signal_report",
            "window_days_used": 2,
            "window_start": "2026-03-24",
            "window_end": "2026-03-25",
            "effective_period": {"date_from": "2026-03-24", "date_to": "2026-03-25"},
            "relevant_calls": 2,
            "ready_analyses": 1,
            "total_group_calls": 2,
        }
        report = build_report_render_model(payload)
        sections = {s["id"]: s for s in report["sections"]}
        note = sections["report_header"].get("selection_note") or ""
        self.assertIn("Список звонков ниже — только за выбранный день", note)
        self.assertIn("Коучинговый разбор собран по базе за 2 рабочих дня: с 24 мар по 25 мар", note)
        self.assertNotIn("скользящее окно", note.lower())

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

    def test_render_report_email_uses_short_body_and_pdf_attachment(self) -> None:
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

        self.assertIn("Ежедневный отчет по звонкам", rendered["subject"])
        self.assertIn("Ежедневный отчет -", rendered["artifact"]["filename"])
        self.assertTrue(rendered["artifact"]["filename"].endswith(".pdf"))
        self.assertIn("Полный отчет - в PDF-файле во вложении.", rendered["text"])
        self.assertIn("Кратко по дню", rendered["text"])
        self.assertIn("Содержательных звонков", rendered["text"])
        self.assertNotIn("СИТУАЦИЯ ДНЯ", rendered["text"])
        self.assertNotIn("РАЗБОР ЗВОНКА", rendered["text"])
        self.assertNotIn("СПИСОК ВСЕХ ЗВОНКОВ ДНЯ", rendered["text"])
        self.assertIn("<html>", rendered["html"])
        self.assertNotIn("ДЕНЬГИ НА СТОЛЕ", rendered["html"])
        self.assertNotIn("PIPELINE ТЁПЛЫХ ЛИДОВ", rendered["html"])
        self.assertNotIn("ЧЕЛЛЕНДЖ НА ЗАВТРА", rendered["html"])
        self.assertNotIn("СВОДНАЯ ТАБЛИЦА ЗВОНКОВ", rendered["html"])
        self.assertNotIn("УТРЕННЯЯ КАРТОЧКА", rendered["html"])
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
        self.assertIn("СИТУАЦИЯ ДНЯ", rendered["report_text"])
        self.assertIn("ДЕНЬГИ НА СТОЛЕ", rendered["report_html"])
        ordered_labels = [
            "ШАПКА",
            "СВОДНАЯ ТАБЛИЦА ЗВОНКОВ",
            "ДЕНЬГИ НА СТОЛЕ",
            "PIPELINE ТЁПЛЫХ ЛИДОВ",
            "БАЛЛЫ ПО ЭТАПАМ",
            "СИТУАЦИЯ ДНЯ",
            "РАЗБОР ЗВОНКА",
            "ГОЛОС КЛИЕНТА",
            "ПОЗВОНИ ЗАВТРА",
            "СПИСОК ВСЕХ ЗВОНКОВ ДНЯ",
            "УТРЕННЯЯ КАРТОЧКА",
        ]
        positions = [rendered["report_html"].index(f">{label}</div>") for label in ordered_labels]
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
        self.assertIn("0:10", rendered["report_text"])
        self.assertIn("10:30", rendered["report_text"])
        self.assertIn("~180 000 тенге", rendered["report_text"])
        self.assertIn("Что имел в виду", rendered["report_text"])
        self.assertNotIn("Что имел в виду", rendered["text"])

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
            delivery_options=resolve_report_delivery_options(send_telegram_test=True),
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
            delivery_options=resolve_report_delivery_options(send_email=True, send_telegram_test=True),
        )

        self.assertEqual(result["status"], "partial")
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
            delivery_options=resolve_report_delivery_options(send_email=True, send_telegram_test=True),
        )

        self.assertEqual(result["status"], "delivered")
        self.assertEqual(result["delivery"]["targets"][0]["channel"], "telegram")
        self.assertEqual(result["delivery"]["transport"]["email_delivery"]["status"], "delivered")

    def test_single_report_result_blocks_business_email_when_manager_gate_fails(self) -> None:
        """Step 8I: incomplete manager_daily is operator preview and cannot send business email."""
        orchestrator = object.__new__(CallsManualReportingOrchestrator)
        ready = _artifact()
        missing_interaction = _interaction(
            manager_id=ready.interaction.manager_id,
            text="",
            call_date="2026-03-25 11:00:00",
        )
        missing_interaction.raw_ref = "onlinepbx://audio.wav"
        missing = ReportArtifact(
            interaction=missing_interaction,
            analysis=None,
            manager=ready.manager,
            call_started_at=datetime.fromisoformat("2026-03-25T11:00:00").replace(tzinfo=UTC),
        )
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
                window_artifacts=[ready, missing],
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

        def _preview_report_delivery(**kwargs):
            self.assertFalse(kwargs["send_business_email"])
            return {
                "mode": "split_operator_delivery",
                "telegram_test_delivery": {"enabled": True, "status": "planned", "target": "74665909"},
                "email_delivery": {"enabled": False, "status": "skipped"},
                "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
            }

        def _deliver_operator_report(**kwargs):
            self.assertFalse(kwargs["send_business_email"])
            return {
                "targets": [{"channel": "telegram", "target": "74665909", "status": "sent"}],
                "transport": {
                    "mode": "split_operator_delivery",
                    "telegram_test_delivery": {"enabled": True, "status": "delivered", "target": "74665909"},
                    "email_delivery": {"enabled": False, "status": "skipped"},
                    "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
                },
            }

        orchestrator.delivery = SimpleNamespace(
            preview_report_delivery=_preview_report_delivery,
            deliver_operator_report=_deliver_operator_report,
        )

        result = CallsManualReportingOrchestrator._build_single_report_result(
            orchestrator,
            preset=resolve_report_preset("manager_daily"),
            artifacts=[ready],
            period={"date_from": "2026-03-25", "date_to": "2026-03-25"},
            filters=ReportRunFilters(date_from="2026-03-25", date_to="2026-03-25"),
            mode="report_from_ready_data_only",
            model_override=None,
            delivery_options=resolve_report_delivery_options(send_email=True, send_telegram_test=True),
        )

        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["manager_facing_completeness"]["reason"], "incomplete_day_call_processing")
        self.assertIn("OPERATOR PREVIEW / INCOMPLETE", result["payload"]["header"]["report_title"])
        self.assertEqual(result["delivery"]["transport"]["email_delivery"]["status"], "skipped")

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
            delivery_options=resolve_report_delivery_options(send_email=True, send_telegram_test=True),
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
                "telegram_test_delivery": {"enabled": False, "status": "skipped", "target": "74665909"},
                "email_delivery": {"enabled": False, "status": "skipped", "primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
                "resolved_email": {"primary_email": "elmira@example.com", "cc_emails": ["sales@dogovor24.kz"]},
            },
            deliver_operator_report=lambda **kwargs: {
                "targets": [],
                "transport": {
                    "mode": "split_operator_delivery",
                    "telegram_test_delivery": {"enabled": False, "status": "skipped", "target": "74665909"},
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
            delivery_options=resolve_report_delivery_options(),
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["delivery"]["transport"]["telegram_test_delivery"]["status"], "skipped")
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
            delivery_options=resolve_report_delivery_options(send_telegram_test=True),
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
                window_artifacts=kwargs.get("window_artifacts"),
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
            delivery_options=resolve_report_delivery_options(send_telegram_test=True),
            windows=CallsManualReportingOrchestrator._build_manager_daily_windows(anchor_day="2026-03-25"),
        )

        self.assertEqual(result["readiness_outcome"], "signal_report")
        self.assertEqual(result["window_days_used"], 2)
        self.assertEqual(result["window_start"], "2026-03-24")
        self.assertEqual(result["window_end"], "2026-03-25")
        self.assertEqual(result["relevant_calls"], 3)
        self.assertEqual(result["ready_analyses"], 2)
        self.assertIn("signal_report_ready", result["readiness_reason_codes"])
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["manager_facing_completeness"]["reason"], "incomplete_day_call_processing")
        self.assertEqual(result["manager_facing_completeness"]["blocking_counts"]["no_analysis"], 1)
        self.assertEqual(result["delivery"]["transport"]["email_delivery"]["status"], "skipped")
        self.assertIn("Сигнальный отчёт", result["preview"]["text"])
        self.assertIn("Найдено в телефонии: 2", result["preview"]["text"])
        self.assertIn("вошло в разбор: 2", result["preview"]["text"])
        self.assertIn("Список звонков ниже — только за выбранный день", result["preview"]["text"])
        self.assertIn("Коучинговый разбор собран по базе за 2 рабочих дня", result["preview"]["text"])
        call_dates = {
            str(row.get("time") or "")[:10]
            for row in result["payload"]["call_list"]
            if row.get("time")
        }
        self.assertEqual(call_dates, {"2026-03-25"})

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
        self.assertEqual(sections["call_tomorrow"]["rows"][0][0], "🔴 Горячий")
        self.assertEqual(sections["call_tomorrow"]["rows"][0][1], "+77070000000 · 25 марта 2026, 10:00")
        self.assertIn("договорённость", sections["call_tomorrow"]["rows"][0][2])
        self.assertEqual(len(sections["call_tomorrow"]["rows"][0]), 4)
        self.assertIn("Подтвердить договорённость", sections["call_tomorrow"]["rows"][0][3])
        self.assertIn("Можно начать:", sections["call_tomorrow"]["rows"][0][3])
        self.assertIn("Хочу подтвердить", sections["call_tomorrow"]["rows"][0][3])

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
            delivery_options=resolve_report_delivery_options(send_telegram_test=True),
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
            delivery_options=resolve_report_delivery_options(send_telegram_test=True),
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
            delivery_options=resolve_report_delivery_options(send_email=True, send_telegram_test=True),
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
            delivery_options=resolve_report_delivery_options(),
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
            delivery_options=resolve_report_delivery_options(),
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

    def _stable_selection_analysis(
        self,
        *,
        status_hint: str = "open",
        purpose: str | None = None,
        reusable: bool = True,
    ) -> SimpleNamespace:
        follow_up = {
            "next_step_fixed": False,
            "next_step_text": "Отправить предложение на почту",
            "reason_not_fixed": "",
        }
        if status_hint == "refusal":
            follow_up = {
                "next_step_fixed": False,
                "next_step_text": "",
                "reason_not_fixed": "Клиент сказал, что не актуально.",
            }
        detail = {
            "classification": {
                "call_type": "sales_primary",
                "analysis_eligibility": "eligible",
            },
            "call": {"contact_phone": "+77070000000"},
            "summary": {"short_summary": "Синтетический тестовый звонок"},
            "score": {"checklist_score": {"score_percent": 72.0, "level": "basic"}},
            "score_by_stage": [
                {
                    "stage_code": "completion_next_step",
                    "stage_name": "Завершение и следующий шаг",
                    "criteria_results": [],
                }
            ],
            "strengths": [{"title": "Структура", "comment": "Звонок разобран."}],
            "gaps": [],
            "recommendations": [],
            "follow_up": follow_up,
        }
        if not reusable:
            detail["score_by_stage"] = []
            detail["strengths"] = []
            detail["gaps"] = []
            detail["recommendations"] = []
        if purpose:
            detail = mark_scores_detail_analysis_purpose(detail, analysis_purpose=purpose)
        return SimpleNamespace(
            id=uuid4(),
            interaction_id=uuid4(),
            instruction_version="analysis_v_synthetic",
            score_total=72.0,
            is_failed=False,
            scores_detail=detail,
        )

    def test_stable_analysis_selection_excludes_latest_controlled_sample_from_business_outcome(self) -> None:
        older_stable = self._stable_selection_analysis(status_hint="open")
        newer_sample = self._stable_selection_analysis(
            status_hint="refusal",
            purpose=ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
        )

        selected = _select_stable_analysis_for_reporting([newer_sample, older_stable])

        self.assertIs(selected, older_stable)
        interaction = _interaction(text="Клиент попросил отправить предложение на почту.")
        artifact = ReportArtifact(
            interaction=interaction,
            analysis=selected,
            manager=None,
            call_started_at=datetime(2026, 3, 25, 10, 0, tzinfo=UTC),
        )
        outcome = BusinessOutcomeResolver().resolve(artifact)
        self.assertEqual(outcome.final_status, "open")

    def test_stable_analysis_selection_falls_back_past_latest_invalid_row(self) -> None:
        older_stable = self._stable_selection_analysis(status_hint="open")
        newer_invalid = self._stable_selection_analysis(status_hint="refusal", reusable=False)

        selected = _select_stable_analysis_for_reporting([newer_invalid, older_stable])

        self.assertIs(selected, older_stable)

    def test_stable_analysis_selection_opt_in_can_use_controlled_sample(self) -> None:
        older_stable = self._stable_selection_analysis(status_hint="open")
        newer_sample = self._stable_selection_analysis(
            status_hint="refusal",
            purpose=ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
        )

        normal_selected = _select_stable_analysis_for_reporting([newer_sample, older_stable])
        opt_in_selected = _select_stable_analysis_for_reporting(
            [newer_sample, older_stable],
            include_controlled_samples=True,
        )

        self.assertIs(normal_selected, older_stable)
        self.assertIs(opt_in_selected, newer_sample)

    def test_stable_analysis_selection_preserves_latest_unmarked_production_behavior(self) -> None:
        older_stable = self._stable_selection_analysis(status_hint="open")
        newer_production = self._stable_selection_analysis(status_hint="refusal")

        selected = _select_stable_analysis_for_reporting([newer_production, older_stable])

        self.assertIs(selected, newer_production)

    def test_controlled_sample_analysis_purpose_marker_identifies_verification_without_real_call_ids(self) -> None:
        sample_detail = mark_scores_detail_analysis_purpose(
            {"instruction_version": "analysis_v_synthetic"},
            analysis_purpose=ANALYSIS_PURPOSE_CONTROLLED_SAMPLE,
        )
        verification_analysis = SimpleNamespace(
            instruction_version="verification_only_v0",
            scores_detail={"provenance": "manual_verification_fixture"},
        )
        production_analysis = SimpleNamespace(
            instruction_version="analysis_v_synthetic",
            scores_detail={"meta": {"analysis_purpose": ANALYSIS_PURPOSE_PRODUCTION}},
        )

        self.assertEqual(sample_detail["analysis_purpose"], ANALYSIS_PURPOSE_CONTROLLED_SAMPLE)
        self.assertEqual(analysis_purpose_from_analysis(verification_analysis), ANALYSIS_PURPOSE_VERIFICATION)
        self.assertTrue(is_controlled_analysis(verification_analysis))
        self.assertFalse(is_controlled_analysis(production_analysis))

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
    def _deliver_report_with_modes(
        self,
        *,
        send_telegram_test_delivery: bool,
        send_business_email: bool,
    ) -> tuple[dict[str, Any], Any, Any]:
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
                return_value={
                    "channel": "telegram",
                    "target": "74665909",
                    "status": "sent",
                    "message_id": 101,
                    "document_id": "doc-101",
                },
            ) as send_telegram_document, patch.object(
                CallsDelivery,
                "deliver_report_email",
                return_value={
                    "targets": [{"channel": "email", "target": "elmira@example.com", "status": "sent"}],
                    "subject": "Weekly report",
                    "preview": "Body",
                },
            ) as deliver_report_email:
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
                    send_business_email=send_business_email,
                    send_telegram_test_delivery=send_telegram_test_delivery,
                )
        return result, send_telegram_document, deliver_report_email

    def test_operator_report_no_delivery_preview_skips_telegram_and_email(self) -> None:
        result, send_telegram_document, deliver_report_email = self._deliver_report_with_modes(
            send_telegram_test_delivery=False,
            send_business_email=False,
        )

        send_telegram_document.assert_not_called()
        deliver_report_email.assert_not_called()
        self.assertEqual(result["targets"], [])
        self.assertEqual(result["transport"]["telegram_test_delivery"]["status"], "skipped")
        self.assertEqual(result["transport"]["email_delivery"]["status"], "skipped")
        self.assertEqual(result["artifact"]["filename"], "weekly_report_v1.pdf")

    def test_operator_report_telegram_test_only_sends_telegram_and_skips_email(self) -> None:
        result, send_telegram_document, deliver_report_email = self._deliver_report_with_modes(
            send_telegram_test_delivery=True,
            send_business_email=False,
        )

        send_telegram_document.assert_called_once()
        deliver_report_email.assert_not_called()
        self.assertEqual(result["targets"][0]["channel"], "telegram")
        self.assertEqual(result["transport"]["mode"], "split_operator_delivery")
        self.assertEqual(result["transport"]["telegram_test_delivery"]["status"], "delivered")
        self.assertEqual(result["transport"]["telegram_test_delivery"]["message_id"], 101)
        self.assertEqual(result["transport"]["email_delivery"]["status"], "skipped")
        self.assertEqual(result["transport"]["resolved_email"]["primary_email"], "elmira@example.com")
        self.assertEqual(result["artifact"]["filename"], "weekly_report_v1.pdf")

    def test_operator_report_business_email_only_sends_email_and_skips_telegram(self) -> None:
        result, send_telegram_document, deliver_report_email = self._deliver_report_with_modes(
            send_telegram_test_delivery=False,
            send_business_email=True,
        )

        send_telegram_document.assert_not_called()
        deliver_report_email.assert_called_once()
        self.assertEqual(result["targets"][0]["channel"], "email")
        self.assertEqual(result["transport"]["telegram_test_delivery"]["status"], "skipped")
        self.assertEqual(result["transport"]["email_delivery"]["status"], "delivered")

    def test_operator_report_telegram_and_email_sends_both_channels(self) -> None:
        result, send_telegram_document, deliver_report_email = self._deliver_report_with_modes(
            send_telegram_test_delivery=True,
            send_business_email=True,
        )

        send_telegram_document.assert_called_once()
        deliver_report_email.assert_called_once()
        self.assertEqual([target["channel"] for target in result["targets"]], ["telegram", "email"])
        self.assertEqual(result["transport"]["telegram_test_delivery"]["status"], "delivered")
        self.assertEqual(result["transport"]["email_delivery"]["status"], "delivered")


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
        @contextmanager
        def fake_db():
            yield SimpleNamespace()

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
