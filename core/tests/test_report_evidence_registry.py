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

ROUTER_PATH = CORE_ROOT / "app" / "agents" / "calls" / "report_block_router.py"
ROUTER_SPEC = importlib.util.spec_from_file_location("report_block_router", ROUTER_PATH)
assert ROUTER_SPEC is not None and ROUTER_SPEC.loader is not None
report_block_router = importlib.util.module_from_spec(ROUTER_SPEC)
sys.modules[ROUTER_SPEC.name] = report_block_router
ROUTER_SPEC.loader.exec_module(report_block_router)

ReportEvidenceItem = report_evidence_registry.ReportEvidenceItem
build_report_evidence_registry = report_evidence_registry.build_report_evidence_registry
report_evidence_registry_as_dicts = report_evidence_registry.report_evidence_registry_as_dicts
route_evidence_items = report_block_router.route_evidence_items


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

    def test_v17_pack_sources_route_without_block_candidates(self) -> None:
        artifact = {
            "call_id": "v17-call-1",
            "report_evidence": {
                "semantic_case": {
                    "case_title": "Следующий шаг без срока",
                    "case_type": "growth_zone",
                    "stage_code": "completion_next_step",
                    "priority": "high",
                    "evidence_quality": "direct",
                    "core_meaning": "Клиент готов посмотреть материалы.",
                    "customer_signal": "Клиент попросил отправить материалы.",
                    "manager_behavior": "Менеджер не закрепил срок возврата.",
                    "best_dialogue_fragment": [
                        {"speaker": "client", "text": "Скиньте в WhatsApp, я посмотрю."},
                        {"speaker": "manager", "text": "Хорошо, отправлю информацию."},
                    ],
                    "proof_card": {
                        "proof_id": "proof-semantic-1",
                        "call_id": "v17-call-1",
                        "stage_code": "completion_next_step",
                        "claim": "Менеджер не закрепил срок возврата.",
                        "claim_scope": "scene",
                        "scene_id": "scene-semantic-1",
                        "evidence_ids": ["ev-semantic-1"],
                        "evidence_quote": "Хорошо, отправлю информацию.",
                        "proof_type": "sequence_inference",
                        "gap_proven": True,
                        "counter_evidence": [],
                        "needs_softening": False,
                        "reject_reason": None,
                    },
                    "report_block_fit": {
                        "situation_day": {
                            "fit": True,
                            "score": 88,
                            "evidence_type": "manager_gap",
                            "block_role": "coaching_problem",
                        }
                    },
                    "usable_in_report": True,
                },
                "additional_situations": [
                    {
                        "type": "growth_zone",
                        "title": "Роль клиента не уточнена",
                        "priority": "medium",
                        "evidence_quality": "direct",
                        "stage_code": "qualification_primary",
                        "what_happened": "Клиент сказал, что уточняет для руководителя.",
                        "recommended_action": "Уточнить роль и критерии решения.",
                        "quote": "Я просто уточняю для руководителя.",
                        "speaker": "client",
                        "proof_card": {
                            "proof_id": "proof-additional-1",
                            "call_id": "v17-call-1",
                            "stage_code": "qualification_primary",
                            "claim": "Менеджер не уточнил роль клиента.",
                            "claim_scope": "scene",
                            "scene_id": "scene-additional-1",
                            "evidence_ids": ["ev-additional-1"],
                            "evidence_quote": "Я просто уточняю для руководителя.",
                            "proof_type": "sequence_inference",
                            "gap_proven": True,
                            "counter_evidence": [],
                            "needs_softening": False,
                            "reject_reason": None,
                        },
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
                        "first_phrase": "Алия, добрый день. Отправляю материалы.",
                        "why_follow_up": "Клиент попросил материалы.",
                        "proof_card": {
                            "proof_id": "proof-follow-up-1",
                            "call_id": "v17-call-1",
                            "stage_code": "completion_next_step",
                            "claim": "Есть открытый следующий шаг.",
                            "claim_scope": "call",
                            "scene_id": "scene-follow-up-1",
                            "evidence_ids": ["ev-follow-up-1"],
                            "evidence_quote": "Скиньте в WhatsApp, я посмотрю.",
                            "proof_type": "sequence_inference",
                            "counter_evidence": [],
                            "needs_softening": False,
                            "reject_reason": None,
                        },
                        "usable_in_report": True,
                    }
                ],
                "quote_bank": [
                    {
                        "quote": "Скиньте в WhatsApp, я посмотрю.",
                        "speaker": "client",
                        "topic": "product_interest",
                        "business_signal": "high",
                        "stage_code": "completion_next_step",
                        "proof_card": {
                            "proof_id": "proof-quote-1",
                            "call_id": "v17-call-1",
                            "stage_code": "completion_next_step",
                            "claim": "Клиент проявил интерес к материалам.",
                            "claim_scope": "scene",
                            "scene_id": "scene-quote-1",
                            "evidence_ids": ["ev-quote-1"],
                            "evidence_quote": "Скиньте в WhatsApp, я посмотрю.",
                            "proof_type": "direct_quote",
                            "counter_evidence": [],
                            "needs_softening": False,
                            "reject_reason": None,
                        },
                        "usable_in_report": True,
                    }
                ],
                "evidence_fragments": [
                    {
                        "evidence_type": "customer_signal",
                        "client_text": "Я посмотрю материалы и дам обратную связь.",
                        "criterion_code": "completion_next_step",
                        "evidence_quality": "direct",
                    }
                ],
            },
        }

        registry = build_report_evidence_registry([artifact])
        by_source = {}
        for item in registry:
            by_source.setdefault(item.source, []).append(item)

        self.assertNotIn("report_evidence.block_candidates.situation_day", by_source)
        semantic = by_source["report_evidence.semantic_case"][0]
        self.assertEqual(semantic.evidence_type, "manager_gap")
        self.assertTrue(semantic.block_suitability["situation_day"]["eligible"])

        additional = by_source["report_evidence.additional_situations"][0]
        self.assertEqual(additional.evidence_type, "manager_gap")
        self.assertTrue(additional.block_suitability["additional_situations"]["eligible"])

        follow_up = by_source["report_evidence.follow_up_candidates"][0]
        self.assertEqual(follow_up.evidence_type, "follow_up_opportunity")
        self.assertTrue(follow_up.block_suitability["follow_up"]["eligible"])
        self.assertTrue(follow_up.block_suitability["call_tomorrow"]["eligible"])

        quote = by_source["report_evidence.quote_bank"][0]
        self.assertEqual(quote.evidence_type, "customer_signal")
        self.assertEqual(quote.proof_strength, "strong")
        self.assertTrue(quote.block_suitability["voice_of_customer"]["eligible"])

        fragment = by_source["evidence_fragments"][0]
        self.assertEqual(fragment.evidence_type, "customer_signal")
        self.assertTrue(fragment.block_suitability["voice_of_customer"]["eligible"])

        routed = route_evidence_items(registry)
        summary = routed["diagnostics"]["summary"]["routed_count_by_block"]
        self.assertGreaterEqual(summary["situation_day"], 1)
        self.assertGreaterEqual(summary["follow_up"], 1)
        self.assertGreaterEqual(summary["additional_situations"], 1)
        self.assertGreaterEqual(summary["voice_of_customer"], 2)

    def test_voice_of_customer_business_signal_drives_router_proof_strength(self) -> None:
        artifact = {
            "call_id": "voc-business-signal-1",
            "report_evidence": {
                "voice_of_customer": [
                    {
                        "quote": "Скиньте тарифы, я сравню с текущим поставщиком.",
                        "speaker": "client",
                        "topic": "price",
                        "meaning": "Клиент сравнивает цену и проявляет коммерческий интерес.",
                        "business_signal": "medium",
                        "stage_code": "needs_discovery",
                        "proof_card": {
                            "proof_id": "proof-voc-1",
                            "call_id": "voc-business-signal-1",
                            "stage_code": "needs_discovery",
                            "claim": "Клиент сравнивает цену.",
                            "claim_scope": "scene",
                            "scene_id": "scene-voc-1",
                            "evidence_ids": ["ev-voc-1"],
                            "evidence_quote": "Скиньте тарифы, я сравню с текущим поставщиком.",
                            "proof_type": "direct_quote",
                            "counter_evidence": [],
                            "needs_softening": False,
                            "reject_reason": None,
                        },
                        "usable_in_report": True,
                    }
                ]
            },
        }

        registry = build_report_evidence_registry([artifact])

        self.assertEqual(len(registry), 1)
        item = registry[0]
        self.assertEqual(item.source, "report_evidence.voice_of_customer")
        self.assertEqual(item.evidence_type, "customer_signal")
        self.assertEqual(item.proof_strength, "medium")
        self.assertEqual(item.diagnostics["proof_status"], "verified_proof_card")
        self.assertTrue(item.block_suitability["voice_of_customer"]["eligible"])

        routed = route_evidence_items(registry)
        self.assertEqual(len(routed["voice_of_customer"]), 1)
        self.assertEqual(
            routed["voice_of_customer"][0]["source"],
            "report_evidence.voice_of_customer",
        )

    def test_call_essence_routes_same_source_to_call_list_and_follow_up(self) -> None:
        artifact = {
            "call_id": "essence-call-1",
            "report_evidence": {
                "call_essence": {
                    "topic": "Презентация по ЭДО",
                    "outcome": "agreement",
                    "refusal_or_interest_reason": "Клиент хочет увидеть, как работает ЭДО.",
                    "agreement": "Договорились созвониться на презентацию по ЭДО.",
                    "next_step": "Назначить презентацию и отправить приглашение.",
                    "deadline": "завтра",
                    "manager_visible_text": (
                        "Клиент заинтересовался ЭДО. Договорились созвониться "
                        "на презентацию, дальше нужно отправить приглашение."
                    ),
                    "source": "llm2_layered_analysis.derived_call_essence",
                }
            },
        }

        registry = build_report_evidence_registry([artifact])

        self.assertEqual(len(registry), 1)
        item = registry[0]
        self.assertEqual(item.source, "report_evidence.call_essence")
        self.assertEqual(item.evidence_type, "call_essence")
        self.assertEqual(item.proof_strength, "medium")
        self.assertTrue(item.block_suitability["call_list"]["eligible"])
        self.assertTrue(item.block_suitability["follow_up"]["eligible"])
        self.assertEqual(item.call_essence["topic"], "Презентация по ЭДО")

        routed = route_evidence_items(registry)
        self.assertEqual(routed["call_list"][0]["source"], "report_evidence.call_essence")
        self.assertEqual(routed["follow_up"][0]["source"], "report_evidence.call_essence")
        self.assertEqual(
            routed["diagnostics"]["source_consistency"][0]["reason"],
            "same_source",
        )

    def test_legacy_candidate_without_proof_card_is_hint_only_for_router(self) -> None:
        artifact = {
            "call_id": "legacy-no-proof-1",
            "report_evidence": {
                "situation_candidates": [
                    {
                        "stage_code": "qualification_primary",
                        "situation_title": "Процесс клиента не уточнен",
                        "evidence_quality": "direct",
                        "dialogue_fragment": [
                            {"speaker": "client", "text": "У нас часть договоров на бумаге."},
                            {"speaker": "manager", "text": "Тогда я отправлю КП."},
                        ],
                        "what_was_missing": "Не хватило вопросов о документообороте.",
                        "usable_in_report": True,
                    }
                ]
            },
        }

        registry = build_report_evidence_registry([artifact])

        self.assertEqual(len(registry), 1)
        item = registry[0]
        self.assertIn("missing_proof_card", item.rejection_reasons)
        self.assertEqual(item.diagnostics["proof_status"], "legacy_hint_only")
        self.assertFalse(item.diagnostics["verified_source"])

        routed = route_evidence_items(registry)
        self.assertEqual(routed["situation_day"], [])
        reasons = {
            entry["reason"]
            for entry in routed["diagnostics"]["rejected"]
            if entry["item_id"] == item.evidence_id and entry["block"] == "situation_day"
        }
        self.assertEqual(reasons, {"missing_proof_card"})

    def test_top_level_proof_cards_build_verified_pool_items(self) -> None:
        artifact = {
            "call_id": "proof-pool-1",
            "report_evidence": {
                "proof_cards": [
                    {
                        "proof_id": "proof-top-1",
                        "claim": "Менеджер не закрепил срок следующего контакта.",
                        "claim_scope": "scene",
                        "claim_type": "manager_gap",
                        "proof_type": "sequence_inference",
                        "status": "proven",
                        "stage_code": "completion_next_step",
                        "scene_id": "scene-1",
                        "evidence_ids": ["ev-1", "ev-2"],
                        "gap_proven": True,
                        "recommendation_id": "rec-1",
                        "supporting_evidence": [
                            {"evidence_id": "ev-1", "quote": "Я вам отправлю информацию.", "speaker": "manager"},
                            {"evidence_id": "ev-2", "quote": "Хорошо, я посмотрю.", "speaker": "client"},
                        ],
                    }
                ]
            },
        }

        registry = build_report_evidence_registry([artifact])

        self.assertEqual(len(registry), 1)
        item = registry[0]
        self.assertEqual(item.source, "report_evidence.proof_cards")
        self.assertEqual(item.evidence_type, "manager_gap")
        self.assertEqual(item.diagnostics["proof_status"], "verified_proof_card")
        self.assertTrue(item.block_suitability["situation_day"]["eligible"])
        self.assertTrue(item.block_suitability["call_breakdown"]["eligible"])

        routed = route_evidence_items(registry)
        self.assertEqual(len(routed["situation_day"]), 1)
        self.assertEqual(len(routed["call_breakdown"]), 1)

    def test_persisted_scores_detail_proof_cards_feed_verified_router_pool(self) -> None:
        artifact = {
            "call_id": "persisted-proof-1",
            "scores_detail": {
                "report_evidence": {
                    "proof_cards": [
                        {
                            "proof_id": "proof-persisted-1",
                            "claim": "Менеджер не зафиксировал дату следующего контакта.",
                            "claim_type": "manager_gap",
                            "proof_type": "sequence_inference",
                            "status": "proven",
                            "stage_code": "completion_next_step",
                            "scene_id": "scene-persisted-1",
                            "evidence_ids": ["ev-persisted-1"],
                            "gap_proven": True,
                            "supporting_evidence": [
                                {
                                    "evidence_id": "ev-persisted-1",
                                    "speaker": "manager",
                                    "quote": "Я отправлю информацию, посмотрите.",
                                }
                            ],
                        }
                    ]
                }
            },
        }

        registry = build_report_evidence_registry([artifact])

        self.assertEqual(len(registry), 1)
        item = registry[0]
        self.assertEqual(item.source, "report_evidence.proof_cards")
        self.assertEqual(item.call_id, "persisted-proof-1")
        self.assertEqual(item.diagnostics["proof_status"], "verified_proof_card")

        routed = route_evidence_items(registry)
        self.assertEqual(routed["situation_day"][0]["evidence_id"], item.evidence_id)
        self.assertEqual(routed["call_breakdown"][0]["evidence_id"], item.evidence_id)

    def test_softened_proof_card_is_admitted_but_not_marked_verified(self) -> None:
        artifact = {
            "call_id": "softened-proof-1",
            "scores_detail": {
                "report_evidence": {
                    "proof_cards": [
                        {
                            "proof_id": "proof-softened-1",
                            "claim": "Похоже, менеджер не до конца закрепил дату следующего контакта.",
                            "claim_type": "manager_gap",
                            "proof_type": "sequence_inference",
                            "status": "softened",
                            "stage_code": "completion_next_step",
                            "scene_id": "scene-softened-1",
                            "evidence_ids": ["ev-softened-1"],
                            "gap_proven": True,
                            "supporting_evidence": [
                                {
                                    "evidence_id": "ev-softened-1",
                                    "speaker": "manager",
                                    "quote": "Я отправлю информацию, посмотрите.",
                                }
                            ],
                        }
                    ]
                }
            },
        }

        registry = build_report_evidence_registry([artifact])

        self.assertEqual(len(registry), 1)
        item = registry[0]
        self.assertEqual(item.proof_strength, "medium")
        self.assertEqual(item.diagnostics["proof_status"], "softened_proof_card")
        self.assertFalse(item.diagnostics["verified_source"])

        routed = route_evidence_items(registry)
        self.assertEqual(routed["situation_day"][0]["evidence_id"], item.evidence_id)
        self.assertEqual(routed["call_breakdown"][0]["evidence_id"], item.evidence_id)
        routed_statuses = {
            entry["proof_status"]
            for entry in routed["diagnostics"]["routed"]
            if entry["item_id"] == item.evidence_id
        }
        self.assertEqual(routed_statuses, {"softened_proof_card"})


if __name__ == "__main__":
    unittest.main()
