from __future__ import annotations

import importlib.util
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

MODULE_PATH = CORE_ROOT / "app" / "agents" / "calls" / "report_block_router.py"
SPEC = importlib.util.spec_from_file_location("report_block_router", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
report_block_router = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = report_block_router
SPEC.loader.exec_module(report_block_router)

is_usable_for_block = report_block_router.is_usable_for_block
route_evidence_items = report_block_router.route_evidence_items


@dataclass(frozen=True)
class EvidenceRow:
    item_id: str
    call_id: str
    evidence_type: str
    proof_strength: str
    score: int
    source: str
    what_happened: str
    usable_in_report: bool = True


class ReportBlockRouterTests(unittest.TestCase):
    def test_customer_signal_does_not_route_to_situation_day(self) -> None:
        item = {
            "item_id": "voc-1",
            "call_id": "call-1",
            "evidence_type": "customer_signal",
            "proof_strength": "strong",
            "score": 91,
            "quote": "Скиньте в WhatsApp, я посмотрю.",
            "source": "report_evidence.voice_of_customer[0]",
            "proof_card": {
                "proof_id": "proof-voc-1",
                "scene_id": "scene-voc-1",
                "evidence_ids": ["ev-voc-1"],
                "evidence_quote": "Скиньте в WhatsApp, я посмотрю.",
                "reject_reason": None,
            },
        }

        result = route_evidence_items([item])

        self.assertEqual(result["situation_day"], [])
        self.assertEqual(result["voice_of_customer"][0]["item_id"], "voc-1")
        reasons = {
            entry["reason"]
            for entry in result["diagnostics"]["rejected"]
            if entry["item_id"] == "voc-1" and entry["block"] == "situation_day"
        }
        self.assertEqual(reasons, {"customer_signal_routed_elsewhere"})
        usable, reason = is_usable_for_block(item, "situation_day")
        self.assertFalse(usable)
        self.assertEqual(reason, "customer_signal_routed_elsewhere")

    def test_service_issue_does_not_route_to_sales_coaching_blocks(self) -> None:
        item = {
            "item_id": "svc-1",
            "call_id": "call-2",
            "case_type": "service_issue",
            "target_block": "situation_day",
            "proof_strength": "strong",
            "score": 85,
            "quote": "Документ не открывается в личном кабинете.",
            "source": "report_evidence.semantic_case",
            "proof_card": {
                "proof_id": "proof-service-1",
                "scene_id": "scene-service-1",
                "evidence_ids": ["ev-service-1"],
                "evidence_quote": "Документ не открывается в личном кабинете.",
                "reject_reason": None,
            },
        }

        result = route_evidence_items([item])

        for block in ("situation_day", "call_breakdown", "challenge", "additional_situations"):
            self.assertEqual(result[block], [])
            reasons = {
                entry["reason"]
                for entry in result["diagnostics"]["rejected"]
                if entry["item_id"] == "svc-1" and entry["block"] == block
            }
            self.assertEqual(reasons, {"service_issue_forbidden"})

    def test_manager_coaching_moment_medium_proof_can_be_call_breakdown_fallback(self) -> None:
        customer_signal = {
            "item_id": "voc-1",
            "call_id": "call-1",
            "evidence_type": "customer_signal",
            "proof_strength": "strong",
            "score": 96,
            "quote": "Скиньте КП в WhatsApp.",
        }
        medium_moment = EvidenceRow(
            item_id="moment-1",
            call_id="call-2",
            evidence_type="manager_coaching_moment",
            proof_strength="medium",
            score=82,
            source="report_evidence.manager_coaching_moments[0]",
            what_happened=(
                "Менеджер согласился отправить материалы, но не закрепил дату "
                "возврата к обсуждению."
            ),
        )
        medium_moment = {
            **medium_moment.__dict__,
            "proof_card": {
                "proof_id": "proof-moment-1",
                "scene_id": "scene-moment-1",
                "evidence_ids": ["ev-moment-1"],
                "evidence_quote": "Хорошо, отправлю материалы.",
                "gap_proven": True,
                "reject_reason": None,
            },
        }

        result = route_evidence_items([customer_signal, medium_moment])

        self.assertEqual([item["item_id"] for item in result["call_breakdown"]], ["moment-1"])
        routed = {
            entry["reason"]
            for entry in result["diagnostics"]["routed"]
            if entry["item_id"] == "moment-1" and entry["block"] == "call_breakdown"
        }
        self.assertEqual(routed, {"fallback_best_manager_moment"})
        usable, reason = is_usable_for_block(medium_moment, "call_breakdown")
        self.assertTrue(usable)
        self.assertEqual(reason, "eligible_manager_gap")

    def test_verified_situation_day_limits_call_breakdown_to_same_call_manager_gap(self) -> None:
        same_call = {
            "item_id": "gap-same",
            "call_id": "call-selected",
            "evidence_type": "manager_gap",
            "proof_strength": "strong",
            "score": 90,
            "evidence_scene": "Клиент попросил материалы, менеджер не закрепил срок возврата.",
            "proof_card": {
                "proof_id": "proof-same",
                "status": "proven",
                "evidence_quote": "Клиент попросил материалы, менеджер не закрепил срок возврата.",
                "gap_proven": True,
                "reject_reason": None,
            },
        }
        other_call = {
            "item_id": "gap-other",
            "call_id": "call-other",
            "evidence_type": "manager_gap",
            "proof_strength": "strong",
            "score": 95,
            "evidence_scene": "Другой звонок с похожей ошибкой.",
            "proof_card": {
                "proof_id": "proof-other",
                "status": "proven",
                "evidence_quote": "Другой звонок с похожей ошибкой.",
                "gap_proven": True,
                "reject_reason": None,
            },
        }

        result = route_evidence_items(
            [other_call, same_call],
            selected_situation_call_id="call-selected",
        )

        self.assertEqual([item["item_id"] for item in result["call_breakdown"]], ["gap-same"])
        reasons = {
            entry["reason"]
            for entry in result["diagnostics"]["rejected"]
            if entry["item_id"] == "gap-other" and entry["block"] == "call_breakdown"
        }
        self.assertEqual(reasons, {"wrong_call"})

    def test_legacy_rows_without_proof_card_are_not_eligible(self) -> None:
        item = {
            "item_id": "legacy-no-proof-1",
            "call_id": "call-3",
            "evidence_type": "manager_gap",
            "proof_strength": "strong",
            "score": 88,
            "source": "report_evidence.situation_candidates[0]",
            "what_happened": "Нужно лучше выявлять потребности.",
            "usable_in_report": True,
        }

        result = route_evidence_items([item])

        self.assertEqual(result["situation_day"], [])
        self.assertEqual(result["call_breakdown"], [])
        rejected = {
            entry["block"]: entry["reason"]
            for entry in result["diagnostics"]["rejected"]
            if entry["item_id"] == "legacy-no-proof-1"
            and entry["block"] in {"situation_day", "call_breakdown"}
        }
        self.assertEqual(
            rejected,
            {
                "situation_day": "missing_proof_card",
                "call_breakdown": "missing_proof_card",
            },
        )

    def test_diagnostics_only_mode_routes_usable_legacy_rows_without_proof_card(self) -> None:
        item = {
            "item_id": "legacy-usable-1",
            "call_id": "call-3",
            "evidence_type": "manager_gap",
            "proof_strength": "strong",
            "score": 88,
            "source": "report_evidence.situation_candidates[0]",
            "evidence_scene": "Клиент просит материалы, менеджер не закрепляет следующий контакт.",
            "what_happened": "Менеджер отправляет материалы без даты следующего шага.",
            "usable_in_report": True,
        }

        result = route_evidence_items([item], require_verified_proof=False)

        self.assertEqual(result["diagnostics"]["proof_gate_mode"], "diagnostics_only")
        self.assertEqual(result["situation_day"][0]["item_id"], "legacy-usable-1")
        self.assertEqual(result["call_breakdown"][0]["item_id"], "legacy-usable-1")
        routed_reasons = {
            entry["block"]: entry["reason"]
            for entry in result["diagnostics"]["routed"]
            if entry["item_id"] == "legacy-usable-1"
            and entry["block"] in {"situation_day", "call_breakdown"}
        }
        self.assertEqual(
            routed_reasons,
            {
                "situation_day": "manager_gap_verified_for_situation_day",
                "call_breakdown": "fallback_best_manager_moment",
            },
        )
        usable, reason = is_usable_for_block(
            item,
            "situation_day",
            require_verified_proof=False,
        )
        self.assertTrue(usable)
        self.assertEqual(reason, "manager_gap_verified_for_situation_day")

    def test_softened_proof_card_routes_with_softened_status(self) -> None:
        item = {
            "item_id": "softened-gap-1",
            "call_id": "call-softened",
            "evidence_type": "manager_gap",
            "proof_strength": "medium",
            "score": 81,
            "source": "report_evidence.proof_cards",
            "what_happened": "Похоже, менеджер не до конца закрепил дату следующего контакта.",
            "proof_card": {
                "proof_id": "proof-softened-gap-1",
                "status": "soften",
                "scene_id": "scene-softened-gap-1",
                "evidence_ids": ["ev-softened-gap-1"],
                "evidence_quote": "Я отправлю информацию, посмотрите.",
                "gap_proven": True,
                "reject_reason": None,
            },
        }

        result = route_evidence_items([item])

        self.assertEqual(result["situation_day"][0]["item_id"], "softened-gap-1")
        self.assertEqual(result["call_breakdown"][0]["item_id"], "softened-gap-1")
        statuses = {
            entry["proof_status"]
            for entry in result["diagnostics"]["routed"]
            if entry["item_id"] == "softened-gap-1"
        }
        self.assertEqual(statuses, {"softened_proof_card"})

    def test_block_suitability_fit_false_blocks_routing(self) -> None:
        item = {
            "item_id": "semantic-voc-1",
            "call_id": "call-4",
            "source": "report_evidence.semantic_case",
            "evidence_type": "manager_gap",
            "proof_strength": "strong",
            "dialogue_scene": [{"speaker": "manager", "text": "Свяжусь через месяц."}],
            "block_suitability": {
                "situation_day": {
                    "eligible": False,
                    "fit": False,
                    "reasons": ["customer_signal_not_manager_gap"],
                },
                "call_breakdown": {
                    "eligible": False,
                    "fit": False,
                    "reasons": ["fit_false"],
                },
                "voice_of_customer": {"eligible": True, "fit": True},
            },
        }

        result = route_evidence_items([item])

        self.assertEqual(result["situation_day"], [])
        self.assertEqual(result["call_breakdown"], [])
        reasons = {
            entry["block"]: entry["reason"]
            for entry in result["diagnostics"]["rejected"]
            if entry["item_id"] == "semantic-voc-1"
            and entry["block"] in {"situation_day", "call_breakdown"}
        }
        self.assertEqual(
            reasons,
            {
                "situation_day": "customer_signal_not_manager_gap",
                "call_breakdown": "fit_false",
            },
        )

    def test_call_essence_consistency_diagnostics_for_call_list_and_follow_up(self) -> None:
        item = {
            "item_id": "essence-1",
            "call_id": "call-essence",
            "source": "report_evidence.call_essence",
            "evidence_type": "call_essence",
            "proof_strength": "medium",
            "score": 90,
            "call_essence": {
                "topic": "Презентация по ЭДО",
                "outcome": "agreement",
                "agreement": "Договорились созвониться на презентацию по ЭДО.",
                "next_step": "Отправить приглашение на презентацию.",
                "manager_visible_text": "Клиент заинтересован в презентации по ЭДО.",
            },
        }

        result = route_evidence_items([item])

        self.assertEqual(result["call_list"][0]["item_id"], "essence-1")
        self.assertEqual(result["follow_up"][0]["item_id"], "essence-1")
        self.assertEqual(
            result["diagnostics"]["source_consistency"],
            [
                {
                    "call_id": "call-essence",
                    "consistent": True,
                    "reason": "same_source",
                    "call_list_source": "report_evidence.call_essence",
                    "follow_up_source": "report_evidence.call_essence",
                    "preferred_source": "report_evidence.call_essence",
                }
            ],
        )

    def test_generic_call_essence_still_routes_call_list_but_not_follow_up(self) -> None:
        item = {
            "item_id": "essence-generic",
            "call_id": "call-generic",
            "source": "report_evidence.call_essence",
            "evidence_type": "call_essence",
            "proof_strength": "weak",
            "score": 80,
            "call_essence": {
                "topic": "есть договоренность",
                "outcome": "agreement",
                "agreement": "есть договоренность",
            },
        }

        result = route_evidence_items([item])

        self.assertEqual(result["call_list"][0]["item_id"], "essence-generic")
        self.assertEqual(result["follow_up"], [])
        rejected = {
            entry["reason"]
            for entry in result["diagnostics"]["rejected"]
            if entry["item_id"] == "essence-generic" and entry["block"] == "follow_up"
        }
        self.assertEqual(rejected, {"missing_next_step"})


if __name__ == "__main__":
    unittest.main()
