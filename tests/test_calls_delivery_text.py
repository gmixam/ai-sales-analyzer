"""Regression tests for compact delivery text rendering."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = PROJECT_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.agents.calls.analyzer import CallsAnalyzer
from app.agents.calls.delivery import CallsDelivery
from app.core_shared.db.models import Interaction


def _build_interaction() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        department_id=uuid4(),
        manager_id=None,
        metadata_={},
        text=(
            "Сейчас я в бухгалтерию отправила, ее посадят, автоматический доступ откроется. "
            "Давайте пока презентацию вам проведу. "
            "А в рамках вашей подписки будут доступны документы. "
            "Я вас передам в отдел сервиса. "
            "Она с вами познакомится, она вам позвонит."
        ),
    )


def _build_legacy_shaped_analysis() -> dict:
    return {
        "call": {
            "external_call_code": "384e3a87-3d38-4a84-9656-0feec40be59a",
            "manager_name": "Pilot Manager 212",
            "contact_phone": "+77072221464",
            "call_started_at": "2026-03-18T05:27:59+00:00",
            "duration_sec": 757,
        },
        "classification": {
            "call_type": "sales_primary",
            "scenario_type": "repeat_contact",
            "analysis_eligibility": "eligible",
            "eligibility_reason": "duration_ge_180_sec_and_sales_relevant",
        },
        "summary": {
            "short_summary": (
                "The call involved a detailed walkthrough of the client's subscription features "
                "and document access process."
            ),
            "outcome_text": "The client was guided through accessing documents and features.",
            "next_step_text": "The client will be contacted by the service department for further assistance.",
        },
        "score": {
            "legacy_card_score": None,
            "legacy_card_level": None,
            "checklist_score": {
                "total_points": 15,
                "max_points": 24,
                "score_percent": 62.5,
                "level": "basic",
            },
            "critical_failure": False,
        },
        "score_by_stage": [
            {
                "stage_name": "Первичный контакт",
                "stage_score": 6,
                "max_stage_score": 8,
                "criteria_results": [
                    {
                        "criterion_code": "cs_reason_for_call",
                        "criterion_name": "Понятно обозначил причину звонка",
                        "score": 2,
                        "max_score": 2,
                        "comment": "Clear reason provided.",
                        "evidence": "The manager clearly stated the purpose of the call.",
                    }
                ],
            },
            {
                "stage_name": "Квалификация и первичная потребность",
                "stage_score": 3,
                "max_stage_score": 8,
                "criteria_results": [
                    {
                        "criterion_code": "qp_current_process",
                        "criterion_name": "Выяснил, как сейчас устроен процесс / документооборот",
                        "score": 0,
                        "max_score": 2,
                        "comment": "No inquiry into current processes.",
                        "evidence": "The manager did not ask about the current process.",
                    }
                ],
            },
            {
                "stage_name": "Формирование предложения (презентация/КП)",
                "stage_score": 6,
                "max_stage_score": 8,
                "criteria_results": [
                    {
                        "criterion_code": "pr_clarity_and_examples",
                        "criterion_name": "Объяснил решение ясно, без путаницы",
                        "score": 1,
                        "max_score": 2,
                        "comment": "Explanation was clear but could be crisper.",
                        "evidence": "The explanation was understandable but not crisp.",
                    }
                ],
            },
        ],
        "strengths": [
            {
                "criterion_code": "cs_reason_for_call",
                "comment": "Clear reason provided.",
                "evidence": "The manager clearly stated the purpose of the call.",
            }
        ],
        "gaps": [
            {
                "criterion_code": "qp_current_process",
                "comment": "No inquiry into current processes.",
                "evidence": "The manager did not ask about the current process.",
            }
        ],
        "recommendations": [
            {
                "criterion_code": "qp_current_process",
                "recommendation": (
                    "Ask about the client's current processes to better tailor the presentation."
                ),
            }
        ],
        "agreements": [],
        "follow_up": {
            "next_step_fixed": True,
            "next_step_text": "The client will be contacted by the service department for further assistance.",
            "reason_not_fixed": None,
        },
    }


class CallsDeliveryRenderTests(unittest.TestCase):
    def test_build_notification_text_handles_legacy_shape_and_renders_russian(self) -> None:
        delivery = CallsDelivery(department_id=str(uuid4()), db=None)
        interaction = _build_interaction()
        text = delivery.build_notification_text(
            interaction=interaction,
            analysis_result=_build_legacy_shaped_analysis(),
        )

        self.assertNotIn("None: None", text)
        self.assertNotIn("None / None", text)
        self.assertNotIn("[medium] None -> None", text)
        self.assertNotIn("The call involved", text)
        self.assertNotIn("The client was guided", text)
        self.assertNotIn("The client will be contacted", text)
        self.assertNotIn("Eligibility:", text)
        self.assertNotIn("Follow-up:", text)
        self.assertNotIn("manual pilot", text)
        self.assertIn("Краткое резюме: Менеджер подробно провёл клиента", text)
        self.assertIn("Итог: Клиенту помогли с доступом", text)
        self.assertIn("Следующий шаг: С клиентом свяжется отдел сервиса", text)
        self.assertIn("Сильные стороны:", text)
        self.assertIn("Зоны роста:", text)
        self.assertIn("Рекомендации:", text)
        self.assertIn("Статус анализа: eligible / duration_ge_180_sec_and_sales_relevant", text)
        self.assertIn("Дальнейшие действия:", text)
        self.assertIn("Понятно обозначил причину звонка", text)
        self.assertIn("Выяснил, как сейчас устроен процесс / документооборот", text)
        self.assertIn("[средний]", text)
        self.assertIn("Критический сбой: нет", text)
        self.assertIn("Скоринг по чек-листу: 15/24 (62.5%, Базовый)", text)

    def test_build_notification_text_renders_explicit_manager_fallback_label(self) -> None:
        delivery = CallsDelivery(department_id=str(uuid4()), db=None)
        interaction = _build_interaction()
        interaction.metadata_ = {
            "mapping_source": "manual_fallback",
            "extension": "322",
        }
        analysis = _build_legacy_shaped_analysis()
        analysis["call"]["manager_name"] = "322"

        text = delivery.build_notification_text(
            interaction=interaction,
            analysis_result=analysis,
        )

        self.assertIn("Менеджер: не сопоставлен (внутренний номер 322)", text)
        self.assertNotIn("Менеджер: 322\n", text)

    def test_delivery_render_does_not_translate_transcript_source_text(self) -> None:
        delivery = CallsDelivery(department_id=str(uuid4()), db=None)
        interaction = _build_interaction()
        original_text = interaction.text

        delivery.build_notification_text(
            interaction=interaction,
            analysis_result=_build_legacy_shaped_analysis(),
        )

        self.assertEqual(interaction.text, original_text)
        self.assertIn("автоматический доступ откроется", interaction.text)


class CallsAnalyzerNormalizationTests(unittest.TestCase):
    def test_analyzer_normalizes_legacy_finding_shapes_to_contract_shape(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = Interaction(
            department_id=uuid4(),
            manager_id=None,
            type="call",
            source="onlinepbx",
            external_id="case-1",
            duration_sec=300,
            metadata_={
                "external_call_code": "case-1",
                "manager_name": "Тестовый менеджер",
                "call_date": "2026-03-18 10:00:00",
                "direction": "out",
                "phone": "+77070000000",
            },
        )

        normalized = analyzer._validate_and_normalize_contract(
            raw_contract={
                "classification": {
                    "call_type": "sales_primary",
                    "scenario_type": "repeat_contact",
                },
                "summary": {
                    "short_summary": "Кратко",
                    "outcome_text": "Итог",
                    "next_step_text": "Следующий шаг",
                },
                "score_by_stage": [
                    {
                        "stage_code": "qualification_primary",
                        "stage_name": "Квалификация и первичная потребность",
                        "criteria_results": [
                            {
                                "criterion_code": "qp_current_process",
                                "criterion_name": "Выяснил, как сейчас устроен процесс / документооборот",
                                "score": 0,
                                "max_score": 2,
                                "comment": "Не уточнил текущий процесс",
                                "evidence": "Менеджер не спросил, как сейчас устроен процесс.",
                            }
                        ],
                    }
                ],
                "strengths": [
                    {
                        "criterion_code": "qp_current_process",
                        "comment": "Комментарий",
                        "evidence": "Подтверждение",
                    }
                ],
                "gaps": [
                    {
                        "criterion_code": "qp_current_process",
                        "comment": "Комментарий зоны роста",
                        "evidence": "Подтверждение зоны роста",
                    }
                ],
                "recommendations": [
                    {
                        "criterion_code": "qp_current_process",
                        "recommendation": "Сначала выяснять текущий процесс.",
                    }
                ],
                "follow_up": {
                    "next_step_fixed": False,
                    "next_step_text": None,
                    "reason_not_fixed": "Не договорились",
                },
            },
            interaction=interaction,
            instruction_version="edo_sales_mvp1_call_analysis_v1",
        )

        self.assertEqual(
            normalized["strengths"][0]["title"],
            "Выяснил, как сейчас устроен процесс / документооборот",
        )
        self.assertEqual(normalized["strengths"][0]["impact"], "Комментарий")
        self.assertEqual(
            normalized["recommendations"][0]["problem"],
            "Выяснил, как сейчас устроен процесс / документооборот",
        )
        self.assertEqual(
            normalized["recommendations"][0]["better_phrase"],
            "Сначала выяснять текущий процесс.",
        )


if __name__ == "__main__":
    unittest.main()
