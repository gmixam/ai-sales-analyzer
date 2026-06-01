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


def _proof_card(
    *,
    quote: str,
    claim: str = "Verified claim",
    claim_type: str = "manager_gap",
    speaker: str = "manager",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "proof_id": f"proof-{abs(hash((quote, claim, claim_type))) % 100000}",
        "claim": claim,
        "claim_type": claim_type,
        "proof_type": "direct_quote" if claim_type == "customer_signal" else "sequence_inference",
        "status": "proven",
        "scene_id": f"scene-{abs(hash(quote)) % 100000}",
        "evidence_ids": ["ev-1"],
        "evidence_quote": quote,
        "supporting_evidence": [{"speaker": speaker, "quote": quote}],
    }
    if claim_type == "manager_gap":
        payload["gap_proven"] = True
    return payload


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
                        "proof_card": _proof_card(
                            quote="Хорошо, отправлю вам информацию.",
                            claim="Менеджер не закрепил срок следующего контакта.",
                        ),
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

    def test_daily_focus_is_carried_to_llm3_input_package(self) -> None:
        result = build_situation_day_daily_input(
            [
                {
                    "call_id": "call-gap-1",
                    "report_evidence": {
                        "manager_coaching_moments": [
                            {
                                "stage_code": "objection_handling",
                                "dialogue_fragment": [
                                    {"speaker": "client", "text": "Дорого для нас."},
                                    {"speaker": "manager", "text": "Понимаю, подумаете."},
                                ],
                                "what_happened": "Менеджер не раскрыл ценовое возражение.",
                                "proof_card": _proof_card(
                                    quote="Понимаю, подумаете.",
                                    claim="Менеджер не раскрыл ценовое возражение.",
                                ),
                                "usable_in_report": True,
                            }
                        ]
                    },
                }
            ],
            daily_focus={
                "stage_code": "objection_handling",
                "stage_name": "Работа с возражениями",
                "problem_statement": "Менеджер не раскрыл, что именно смущает клиента в цене.",
                "challenge_metric_source": "score_by_stage.priority",
            },
        )

        self.assertEqual(result["daily_focus"]["stage_code"], "objection_handling")
        self.assertEqual(result["daily_focus"]["stage_name"], "Работа с возражениями")
        self.assertTrue(result["daily_focus"]["proof_pool"]["has_matching_stage_proof"])
        self.assertEqual(result["daily_focus"]["proof_pool"]["matching_scenes_count"], 1)
        self.assertEqual(result["diagnostics"]["focus_stage_code"], "objection_handling")
        self.assertEqual(result["diagnostics"]["focus_matching_verified_scenes_count"], 1)

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
                        "proof_card": _proof_card(
                            quote="У нас сейчас дорого, сравниваем с другим поставщиком.",
                            claim="Клиент сравнивает цену с альтернативой.",
                            claim_type="customer_signal",
                            speaker="client",
                        ),
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
        lower_ranked_signal = {
            "call_id": "call-signal",
            "report_evidence": {
                "voice_of_customer": [
                    {
                        "quote": "Пришлите материалы, мы посмотрим.",
                        "speaker": "client",
                        "topic": "materials",
                        "meaning": "Клиент попросил материалы.",
                        "business_signal": "medium",
                        "proof_card": _proof_card(
                            quote="Пришлите материалы, мы посмотрим.",
                            claim="Клиент попросил материалы.",
                            claim_type="customer_signal",
                            speaker="client",
                        ),
                    }
                ]
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
                        "proof_card": _proof_card(
                            quote="Я пришлю информацию.",
                            claim="Менеджер не уточнил дедлайн клиента.",
                        ),
                        "usable_in_report": True,
                    }
                ]
            },
        }

        result = build_situation_day_daily_input([lower_ranked_signal, gap], max_calls=1)

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
                            "proof_card": _proof_card(
                                quote="Отправлю.",
                                claim="Нет проверяемого следующего шага.",
                            ),
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
                            "proof_card": _proof_card(
                                quote="Нам нужно согласовать бюджет.",
                                claim="Клиент говорит о бюджетном согласовании.",
                                claim_type="customer_signal",
                                speaker="client",
                            ),
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

    def test_report_evidence_index_is_scoped_to_report_artifacts(self) -> None:
        artifacts = [{"call_id": "call-a"}]
        report_evidence_index = {
            "call-a": {
                "report_evidence": {
                    "voice_of_customer": [
                        {
                            "quote": "We need legal approval before signing.",
                            "speaker": "client",
                            "topic": "approval",
                            "meaning": "Client needs internal legal approval.",
                            "proof_card": _proof_card(
                                quote="We need legal approval before signing.",
                                claim="Client needs internal legal approval.",
                                claim_type="customer_signal",
                                speaker="client",
                            ),
                        }
                    ]
                }
            },
            "call-b": {
                "report_evidence": {
                    "voice_of_customer": [
                        {
                            "quote": "External call should not be considered.",
                            "speaker": "client",
                            "topic": "external",
                            "meaning": "External call leaked from the report index.",
                        }
                    ]
                }
            },
        }

        result = build_situation_day_daily_input(
            artifacts,
            report_evidence_index=report_evidence_index,
            max_calls=10,
        )
        diagnostics = result["diagnostics"]
        call_ids = [call["call_id"] for call in result["calls"]]

        self.assertEqual(diagnostics["input_calls_count"], 1)
        self.assertEqual(diagnostics["included_calls_count"], 1)
        self.assertEqual(call_ids, ["call-a"])
        self.assertNotIn("call-b", call_ids)
        self.assertEqual(
            result["calls"][0]["customer_signals"],
            ["Client needs internal legal approval."],
        )
        self.assertNotIn("External call leaked from the report index.", str(result))

    def test_legacy_manager_gap_without_proof_card_is_excluded_from_daily_selection_input(self) -> None:
        result = build_situation_day_daily_input(
            [
                {
                    "call_id": "legacy-gap",
                    "report_evidence": {
                        "situation_candidates": [
                            {
                                "stage_code": "qualification_primary",
                                "situation_title": "Legacy hint",
                                "evidence_quality": "direct",
                                "dialogue_fragment": [
                                    {"speaker": "client", "text": "Расскажите подробнее."},
                                    {"speaker": "manager", "text": "Я отправлю презентацию."},
                                ],
                                "what_was_missing": "Менеджер не уточнил критерии решения.",
                                "usable_in_report": True,
                            }
                        ]
                    },
                }
            ],
        )

        self.assertEqual(result["calls"], [])
        self.assertEqual(
            result["diagnostics"]["excluded_count_by_reason"]["missing_verified_proof"],
            1,
        )

    def test_softened_manager_gap_enters_daily_input_with_softened_status(self) -> None:
        artifact = {
            "call_id": "call-softened-gap",
            "report_evidence": {
                "manager_coaching_moments": [
                    {
                        "stage_code": "completion_next_step",
                        "evidence_quality": "indirect",
                        "dialogue_fragment": [
                            {"speaker": "client", "text": "Пришлите счет, где его увидеть?"},
                            {"speaker": "manager", "text": "Я вам отправлю счет на оплату."},
                        ],
                        "what_happened": "Похоже, следующий шаг был закреплен не до конца конкретно.",
                        "proof_card": {
                            **_proof_card(
                                quote="Я вам отправлю счет на оплату.",
                                claim="Похоже, следующий шаг был закреплен не до конца конкретно.",
                            ),
                            "status": "softened",
                        },
                        "usable_in_report": True,
                    }
                ]
            },
        }

        result = build_situation_day_daily_input([artifact])

        self.assertEqual(result["diagnostics"]["included_calls_count"], 1)
        scene = result["calls"][0]["evidence_scenes"][0]
        self.assertEqual(scene["proof_status"], "softened_proof_card")
        self.assertEqual(scene["proof_strength"], "medium")
        self.assertIn("Похоже", scene["summary"])


if __name__ == "__main__":
    unittest.main()
