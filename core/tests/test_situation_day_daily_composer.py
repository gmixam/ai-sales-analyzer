from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

MODULE_PATH = CORE_ROOT / "app" / "agents" / "calls" / "situation_day_daily_composer.py"
SPEC = importlib.util.spec_from_file_location("situation_day_daily_composer", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
situation_day_daily_composer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = situation_day_daily_composer
SPEC.loader.exec_module(situation_day_daily_composer)

compose_daily_situation_day = situation_day_daily_composer.compose_daily_situation_day
build_daily_situation_llm3_payload = (
    situation_day_daily_composer.build_daily_situation_llm3_payload
)


def _manager_gap(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "item_id": "gap-1",
        "call_id": "call-gap",
        "evidence_type": "manager_gap",
        "proof_strength": "strong",
        "score": 84,
        "source": "report_evidence.manager_gap[0]",
        "situation_title": "Следующий шаг остался без управления",
        "moment_summary": "Клиент попросил КП, менеджер согласился отправить без уточнений.",
        "what_happened": "Клиент попросил КП, менеджер сразу согласился отправить материалы.",
        "manager_error": "Менеджер не уточнил критерии, срок и участников решения.",
        "evidence_scene": "Клиент: Отправьте КП. Менеджер: Да, отправлю в WhatsApp.",
        "supporting_quote": "Да, отправлю в WhatsApp.",
        "why_it_matters": "Сделка остается без понятного следующего шага.",
        "next_time_action": "Сначала уточнить задачу и закрепить дату возврата.",
        "scripts": ["Давайте уточню задачу и срок, чтобы КП было предметным."],
        "source_fact_ids": ["fact-gap-1"],
    }
    item.update(overrides)
    return item


def _customer_signal(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "item_id": "signal-1",
        "call_id": "call-signal",
        "evidence_type": "customer_signal",
        "proof_strength": "strong",
        "score": 99,
        "source": "report_evidence.voice_of_customer[0]",
        "situation_title": "Клиент проявил интерес",
        "moment_summary": "Клиент попросил отправить материалы.",
        "what_happened": "Клиент попросил КП и сказал, что посмотрит.",
        "manager_error": "Клиентский сигнал, не ошибка менеджера.",
        "evidence_scene": "Клиент: Скиньте КП, я посмотрю.",
        "supporting_quote": "Скиньте КП, я посмотрю.",
        "why_it_matters": "Есть интерес клиента.",
        "next_time_action": "Отправить материалы.",
        "scripts": ["Отправлю материалы."],
        "source_fact_ids": ["fact-signal-1"],
    }
    item.update(overrides)
    return item


class SituationDayDailyComposerTests(unittest.TestCase):
    def test_picks_manager_gap_over_stronger_customer_signal(self) -> None:
        result = compose_daily_situation_day(
            {"evidence_items": [_customer_signal(score=100), _manager_gap(score=70)]},
            llm3_enabled=False,
        )

        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["selected_call_id"], "call-gap")
        self.assertEqual(result["manager_error"], "Менеджер не уточнил критерии, срок и участников решения.")
        self.assertEqual(result["selection_reason"], "best_manager_gap_scene_by_score")

    def test_returns_insufficient_when_only_customer_signals(self) -> None:
        result = compose_daily_situation_day(
            {"evidence_items": [_customer_signal()]},
            llm3_enabled=False,
        )

        self.assertEqual(result["status"], "insufficient")
        self.assertIsNone(result["selected_call_id"])
        self.assertEqual(result["selection_reason"], "no_manager_gap_scene")
        self.assertEqual(result["rejected_candidates"][0]["reason"], "customer_signal_forbidden")

    def test_deterministic_result_has_required_fields_and_scripts(self) -> None:
        result = compose_daily_situation_day(
            {"routing": {"situation_day": [_manager_gap(scripts=[])]}},
            llm3_enabled=False,
        )

        required = {
            "status",
            "selected_call_id",
            "situation_title",
            "moment_summary",
            "what_happened",
            "manager_error",
            "evidence_scene",
            "supporting_quote",
            "why_it_matters",
            "next_time_action",
            "scripts",
            "rejected_candidates",
            "selection_reason",
            "source_fact_ids",
            "diagnostics",
        }
        self.assertTrue(required.issubset(result.keys()))
        self.assertEqual(result["status"], "verified")
        self.assertGreaterEqual(len(result["scripts"]), 2)
        self.assertEqual(result["source_fact_ids"], ["fact-gap-1"])

    def test_llm3_payload_includes_no_full_transcript_and_forbids_recalculation(self) -> None:
        payload = build_daily_situation_llm3_payload(
            {
                "evidence_items": [_manager_gap()],
                "transcript": "Клиент: полный текст не должен попасть в payload",
                "analysis": {"full_call_analysis": "не должен попасть"},
            }
        )

        candidates_text = str(payload["candidates"]).lower()
        self.assertNotIn("полный текст", candidates_text)
        self.assertNotIn("не должен попасть", candidates_text)
        forbidden = " ".join(payload["forbidden"]).lower()
        self.assertIn("do not recalculate scores", forbidden)
        self.assertIn("do not perform full call analysis", forbidden)
        self.assertIn("do not invent facts", forbidden)
        self.assertIn("do not invent facts, quotes", forbidden)

    def test_reads_day_level_calls_package_from_input_builder(self) -> None:
        result = compose_daily_situation_day(
            {
                "calls": [
                    {
                        "call_id": "call-from-builder",
                        "score": 42,
                        "manager_gaps": ["Менеджер не закрепил дату следующего контакта."],
                        "evidence_scenes": [
                            {
                                "source": "report_evidence.manager_coaching_moments",
                                "evidence_type": "manager_gap",
                                "proof_type": "sequence_inference",
                                "proof_strength": "strong",
                                "stage_code": "completion_next_step",
                                "quote": "Хорошо, отправлю вам информацию.",
                                "turns": [
                                    {"speaker": "client", "text": "Скиньте условия, я посмотрю."},
                                    {"speaker": "manager", "text": "Хорошо, отправлю вам информацию."},
                                ],
                                "next_time_action": "Согласовать дату возврата к вопросу.",
                            }
                        ],
                        "source_fact_ids": ["fact-from-builder"],
                    }
                ]
            },
            llm3_enabled=False,
        )

        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["selected_call_id"], "call-from-builder")
        self.assertEqual(result["stage_code"], "completion_next_step")
        self.assertEqual(result["proof_type"], "sequence_inference")
        self.assertIn("Клиент:", result["evidence_scene"])
        self.assertEqual(result["source_fact_ids"], ["fact-from-builder"])


if __name__ == "__main__":
    unittest.main()
