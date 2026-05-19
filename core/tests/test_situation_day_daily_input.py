from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

REGISTRY_PATH = CORE_ROOT / "app" / "agents" / "calls" / "report_evidence_registry.py"
REGISTRY_SPEC = importlib.util.spec_from_file_location("report_evidence_registry", REGISTRY_PATH)
assert REGISTRY_SPEC is not None and REGISTRY_SPEC.loader is not None
report_evidence_registry = importlib.util.module_from_spec(REGISTRY_SPEC)
sys.modules[REGISTRY_SPEC.name] = report_evidence_registry
REGISTRY_SPEC.loader.exec_module(report_evidence_registry)

MODULE_PATH = CORE_ROOT / "app" / "agents" / "calls" / "situation_day_daily_input.py"
SPEC = importlib.util.spec_from_file_location("situation_day_daily_input", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
situation_day_daily_input = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = situation_day_daily_input
SPEC.loader.exec_module(situation_day_daily_input)

build_situation_day_daily_input = situation_day_daily_input.build_situation_day_daily_input


class SituationDayDailyInputTests(unittest.TestCase):
    def test_manager_coaching_moments_become_gaps_and_evidence_scenes(self) -> None:
        artifact = {
            "call_id": "call-gap-1",
            "metadata": {
                "contact_name": "ООО Ромашка",
                "started_at": "2026-05-18T09:15:00+00:00",
            },
            "analysis": {"score": 71},
            "report_evidence": {
                "manager_coaching_moments": [
                    {
                        "stage_code": "completion_next_step",
                        "moment_type": "missed",
                        "evidence_quality": "direct",
                        "dialogue_fragment": [
                            {
                                "speaker": "client",
                                "text": "Скиньте условия, я посмотрю.",
                            },
                            {
                                "speaker": "manager",
                                "text": "Хорошо, отправлю вам информацию.",
                            },
                        ],
                        "what_happened": "Менеджер не закрепил срок следующего контакта.",
                        "what_better": "Договориться о дате возврата к обсуждению.",
                        "usable_in_report": True,
                    }
                ]
            },
        }

        result = build_situation_day_daily_input([artifact])

        self.assertEqual(result["contract_version"], "situation_day_daily_input_v1")
        self.assertEqual(result["diagnostics"]["included_calls_count"], 1)
        call = result["calls"][0]
        self.assertEqual(call["call_id"], "call-gap-1")
        self.assertEqual(call["client_label"], "ООО Ромашка")
        self.assertEqual(call["date_label"], "2026-05-18")
        self.assertEqual(call["time_label"], "09:15")
        self.assertEqual(call["score"], 71)
        self.assertEqual(
            call["manager_gaps"],
            ["Менеджер не закрепил срок следующего контакта."],
        )
        self.assertEqual(len(call["evidence_scenes"]), 1)
        scene = call["evidence_scenes"][0]
        self.assertEqual(scene["source"], "report_evidence.manager_coaching_moments")
        self.assertEqual(scene["evidence_type"], "manager_gap")
        self.assertEqual(scene["stage_code"], "completion_next_step")
        self.assertEqual(scene["quote"], "Хорошо, отправлю вам информацию.")
        self.assertEqual(scene["turns"][0]["speaker"], "client")
        self.assertIn("call-gap-1:report_evidence.manager_coaching_moments:0", call["source_fact_ids"])

    def test_voice_of_customer_is_customer_signal_not_manager_gap(self) -> None:
        artifact = {
            "call_id": "call-voc-1",
            "report_evidence": {
                "voice_of_customer": [
                    {
                        "quote": "У нас сейчас дорого, сравниваем с другим поставщиком.",
                        "speaker": "client",
                        "topic": "price",
                        "meaning": "Клиент сравнивает цену с альтернативой.",
                        "business_signal": "medium",
                        "stage_code": "needs_discovery",
                    }
                ]
            },
        }

        result = build_situation_day_daily_input([artifact])
        call = result["calls"][0]

        self.assertEqual(call["manager_gaps"], [])
        self.assertEqual(call["customer_signals"], ["Клиент сравнивает цену с альтернативой."])
        self.assertEqual(call["evidence_scenes"][0]["evidence_type"], "customer_signal")
        self.assertIn("customer_signal_not_manager_gap", call["quality_flags"])

    def test_max_calls_keeps_manager_gap_calls_above_neutral(self) -> None:
        neutral = {
            "call_id": "call-neutral",
            "report_evidence": {
                "call_report_summary": {
                    "short_topic": "Короткий нейтральный звонок",
                    "short_context": "Клиент попросил перезвонить позже.",
                }
            },
        }
        gap = {
            "call_id": "call-gap",
            "report_evidence": {
                "manager_coaching_moments": [
                    {
                        "dialogue_fragment": [
                            {"speaker": "client", "text": "Мне важно понять сроки."},
                            {"speaker": "manager", "text": "Я пришлю информацию."},
                        ],
                        "what_happened": "Менеджер не уточнил дедлайн клиента.",
                        "usable_in_report": True,
                    }
                ]
            },
        }

        result = build_situation_day_daily_input([neutral, gap], max_calls=1)

        self.assertEqual([call["call_id"] for call in result["calls"]], ["call-gap"])
        self.assertEqual(result["diagnostics"]["excluded_count_by_reason"]["max_calls"], 1)

    def test_diagnostics_counts_sources_fragments_and_exclusions(self) -> None:
        artifacts = [
            {
                "call_id": "call-gap",
                "report_evidence": {
                    "manager_coaching_moments": [
                        {
                            "dialogue_fragment": [
                                {"speaker": "client", "text": "Посмотрю КП."},
                                {"speaker": "manager", "text": "Отправлю."},
                            ],
                            "what_happened": "Нет проверяемого следующего шага.",
                            "usable_in_report": True,
                        }
                    ]
                },
            },
            {
                "call_id": "call-index",
                "report_evidence": {
                    "call_report_summary": {
                        "short_topic": "Индексный звонок",
                        "short_context": "Контекст есть только в summary.",
                    }
                },
            },
            {"metadata": {"contact_name": "Без id"}},
        ]
        report_evidence_index = {
            "call-index": {
                "report_evidence": {
                    "voice_of_customer": [
                        {
                            "quote": "Нам нужно согласовать бюджет.",
                            "speaker": "client",
                            "topic": "budget",
                            "meaning": "Клиент говорит о бюджетном согласовании.",
                        }
                    ]
                }
            }
        }

        result = build_situation_day_daily_input(
            artifacts,
            report_evidence_index=report_evidence_index,
            max_calls=10,
        )
        diagnostics = result["diagnostics"]

        self.assertEqual(diagnostics["input_calls_count"], 2)
        self.assertEqual(diagnostics["included_calls_count"], 2)
        self.assertEqual(diagnostics["fragments_count"], 2)
        self.assertEqual(
            diagnostics["sources"],
            {
                "report_evidence.call_report_summary": 1,
                "report_evidence.manager_coaching_moments": 1,
                "report_evidence.voice_of_customer": 1,
            },
        )
        self.assertEqual(diagnostics["excluded_count_by_reason"]["missing_call_id"], 1)
        by_call_id = {call["call_id"]: call for call in result["calls"]}
        self.assertEqual(
            by_call_id["call-index"]["customer_signals"],
            ["Клиент говорит о бюджетном согласовании."],
        )


if __name__ == "__main__":
    unittest.main()
