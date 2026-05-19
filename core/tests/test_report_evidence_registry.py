from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

MODULE_PATH = CORE_ROOT / "app" / "agents" / "calls" / "report_evidence_registry.py"
SPEC = importlib.util.spec_from_file_location("report_evidence_registry", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
report_evidence_registry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = report_evidence_registry
SPEC.loader.exec_module(report_evidence_registry)

ReportEvidenceItem = report_evidence_registry.ReportEvidenceItem
build_report_evidence_registry = report_evidence_registry.build_report_evidence_registry
report_evidence_registry_as_dicts = report_evidence_registry.report_evidence_registry_as_dicts


class ReportEvidenceRegistryTests(unittest.TestCase):
    def test_alisher_weak_next_step_coaching_moment_becomes_manager_gap(self) -> None:
        artifact = {
            "call_id": "alisher-call-1",
            "report_evidence": {
                "manager_coaching_moments": [
                    {
                        "stage_code": "completion_next_step",
                        "moment_type": "missed",
                        "priority": "medium",
                        "evidence_quality": "weak",
                        "dialogue_fragment": [
                            {
                                "speaker": "client",
                                "text": "Алишер, скиньте условия, я посмотрю.",
                            },
                            {
                                "speaker": "manager",
                                "text": "Хорошо, я отправлю вам информацию.",
                            },
                        ],
                        "what_happened": "Менеджер слабо зафиксировал следующий шаг после запроса клиента.",
                        "what_better": "Закрепить конкретный срок возврата к обсуждению.",
                        "usable_in_report": True,
                    }
                ]
            },
        }

        registry = build_report_evidence_registry([artifact])

        self.assertEqual(len(registry), 1)
        item = registry[0]
        self.assertIsInstance(item, ReportEvidenceItem)
        self.assertEqual(item.call_id, "alisher-call-1")
        self.assertEqual(item.source, "report_evidence.manager_coaching_moments")
        self.assertEqual(item.evidence_type, "manager_gap")
        self.assertEqual(item.proof_strength, "weak")
        self.assertEqual(item.proof_type, "sequence_inference")
        self.assertIn("слабо зафиксировал следующий шаг", item.manager_gap or "")
        self.assertEqual(item.dialogue_scene[1]["speaker"], "manager")
        self.assertEqual(item.supporting_quote, "Хорошо, я отправлю вам информацию.")
        self.assertIn("weak_evidence_quality", item.rejection_reasons)

        suitability = item.block_suitability["call_breakdown"]
        self.assertTrue(suitability["eligible"])
        self.assertEqual(suitability["strength"], "weak")

    def test_customer_signal_does_not_become_manager_gap(self) -> None:
        artifact = {
            "call_id": "customer-signal-1",
            "report_evidence": {
                "voice_of_customer": [
                    {
                        "quote": "Скиньте тарифы, я сравню с текущим поставщиком.",
                        "speaker": "client",
                        "topic": "price",
                        "meaning": "Клиент сравнивает цену и проявляет коммерческий интерес.",
                        "business_signal": "medium",
                        "stage_code": "needs_discovery",
                        "usable_in_report": True,
                    }
                ]
            },
        }

        registry = build_report_evidence_registry([artifact])

        self.assertEqual(len(registry), 1)
        item = registry[0]
        self.assertEqual(item.evidence_type, "customer_signal")
        self.assertEqual(item.proof_type, "customer_signal")
        self.assertIsNone(item.manager_gap)
        self.assertFalse(item.block_suitability["call_breakdown"]["eligible"])
        self.assertIn(
            "customer_signal_not_manager_gap",
            item.block_suitability["call_breakdown"]["reasons"],
        )

    def test_block_candidates_are_kept_even_when_weak_or_not_fit(self) -> None:
        artifact = {
            "call_id": "block-candidate-1",
            "report_evidence": {
                "block_candidates": {
                    "situation_day": {
                        "fit": False,
                        "score": 28,
                        "role": "coaching_problem",
                        "title_mode": "problem",
                        "stage_code": "qualification_primary",
                        "main_thesis": "Кандидат слабый, но должен попасть в registry.",
                        "what_was_missing": "Не хватило уточнения процесса.",
                        "evidence_quality": "insufficient",
                        "insufficiency_reason": "Нет точной цитаты менеджера.",
                    },
                    "call_breakdown": {
                        "fit": True,
                        "score": 48,
                        "role": "coaching_problem",
                        "title_mode": "problem",
                        "stage_code": "completion_next_step",
                        "main_thesis": "Следующий шаг сформулирован слишком общо.",
                        "what_was_missing": "Нет даты повторного контакта.",
                        "evidence_quality": "weak",
                        "supporting_quote": "Отправлю информацию.",
                    },
                }
            },
        }

        registry = build_report_evidence_registry([artifact])
        by_source = {item.source: item for item in registry}

        situation = by_source["report_evidence.block_candidates.situation_day"]
        self.assertEqual(situation.evidence_type, "manager_gap")
        self.assertEqual(situation.proof_strength, "insufficient")
        self.assertIn("fit_false", situation.rejection_reasons)
        self.assertIn("insufficient_evidence", situation.rejection_reasons)
        self.assertFalse(situation.block_suitability["situation_day"]["eligible"])

        breakdown = by_source["report_evidence.block_candidates.call_breakdown"]
        self.assertEqual(breakdown.proof_strength, "weak")
        self.assertTrue(breakdown.block_suitability["call_breakdown"]["eligible"])
        self.assertIn("weak_evidence_quality", breakdown.rejection_reasons)

    def test_situation_candidates_are_normalized_as_manager_gap_evidence(self) -> None:
        artifact = {
            "call_id": "situation-candidate-1",
            "report_evidence": {
                "situation_candidates": [
                    {
                        "stage_code": "qualification_primary",
                        "problem_type": "missing_process",
                        "situation_title": "Процесс клиента не уточнен",
                        "priority": "high",
                        "evidence_quality": "indirect",
                        "dialogue_fragment": [
                            {
                                "speaker": "client",
                                "text": "У нас часть договоров пока идет на бумаге.",
                            },
                            {
                                "speaker": "manager",
                                "text": "Тогда я отправлю вам коммерческое предложение.",
                            },
                        ],
                        "what_happened": "Менеджер перешел к КП без уточнения процесса.",
                        "what_it_means": "Потребность клиента осталась описана слишком общо.",
                        "what_was_missing": "Не хватило вопросов о текущем документообороте.",
                        "next_time_action": "Уточнить текущий процесс до отправки КП.",
                        "usable_in_report": True,
                    }
                ]
            },
        }

        registry = build_report_evidence_registry([artifact])

        self.assertEqual(len(registry), 1)
        item = registry[0]
        self.assertEqual(item.source, "report_evidence.situation_candidates")
        self.assertEqual(item.evidence_type, "manager_gap")
        self.assertEqual(item.proof_strength, "medium")
        self.assertTrue(item.block_suitability["situation_day"]["eligible"])
        self.assertIn("Не хватило вопросов", item.manager_gap or "")

    def test_accepts_report_artifact_like_object_and_nested_scores_detail(self) -> None:
        artifact = SimpleNamespace(
            interaction=SimpleNamespace(id="object-call-1"),
            analysis=SimpleNamespace(
                scores_detail={
                    "report_evidence_version": "v1",
                    "report_evidence": {
                        "semantic_case": {
                            "case_title": "Открытый интерес без срока возврата",
                            "case_type": "growth_zone",
                            "stage_code": "completion_next_step",
                            "priority": "high",
                            "evidence_quality": "direct",
                            "core_meaning": "Клиент готов посмотреть материалы.",
                            "why_this_call_matters": "Интерес нужно перевести в действие.",
                            "customer_signal": "Клиент попросил материалы.",
                            "manager_behavior": "Менеджер не закрепил срок возврата.",
                            "coaching_diagnosis": "Следующий контакт должен быть проверяемым.",
                            "recommended_next_action": "Согласовать дату следующего контакта.",
                            "best_dialogue_fragment": [
                                {
                                    "speaker": "client",
                                    "text": "Скиньте в WhatsApp, я посмотрю.",
                                },
                                {
                                    "speaker": "manager",
                                    "text": "Хорошо, отправлю.",
                                },
                            ],
                        },
                        "call_report_summary": {
                            "short_topic": "Клиент попросил материалы",
                            "short_context": "Есть открытый интерес.",
                            "manager_next_action": "Отправить материалы и договориться о сроке.",
                        },
                    },
                }
            ),
        )

        registry = build_report_evidence_registry(artifact)
        dicts = report_evidence_registry_as_dicts(registry)

        self.assertEqual([item.call_id for item in registry], ["object-call-1", "object-call-1"])
        self.assertEqual(registry[0].source, "report_evidence.semantic_case")
        self.assertEqual(registry[0].evidence_type, "manager_gap")
        self.assertEqual(dicts[0]["source"], "report_evidence.semantic_case")
        self.assertEqual(registry[1].evidence_type, "follow_up_opportunity")


if __name__ == "__main__":
    unittest.main()
