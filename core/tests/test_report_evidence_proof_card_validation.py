from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Any


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

from app.agents.calls.report_evidence import validate_report_evidence  # noqa: E402


TRANSCRIPT = (
    "Client: Please send the materials in WhatsApp. "
    "Manager: Sure, I will send the information. "
    "Manager: We can talk tomorrow at 10."
)


def _detail_with_card(card: dict[str, Any], *, transcript: str = TRANSCRIPT):
    detail = {
        "report_evidence_version": "v1",
        "report_evidence": {
            "proof_cards": [card],
            "situation_candidates": [],
            "manager_coaching_moments": [],
            "voice_of_customer": [],
            "additional_situations": [],
            "follow_up_candidates": [],
            "quote_bank": [],
        },
    }
    return validate_report_evidence(detail, transcript)


def _verified_sequence_card() -> dict[str, Any]:
    return {
        "proof_id": "proof_next_step_001",
        "claim": "Manager sent materials but did not anchor the next contact.",
        "claim_scope": "scene",
        "claim_type": "manager_gap",
        "proof_type": "sequence_inference",
        "status": "verified",
        "stage_code": "completion_next_step",
        "scene_id": "scene_001",
        "evidence_id": "ev_001",
        "recommendation_id": "rec_001",
        "supporting_evidence": [
            {
                "evidence_id": "ev_001",
                "quote": "Please send the materials in WhatsApp.",
                "speaker": "client",
            },
            {
                "evidence_id": "ev_002",
                "quote": "Sure, I will send the information.",
                "speaker": "manager",
            },
        ],
        "counter_evidence": [],
        "outcome_reason": None,
    }


class ReportEvidenceProofCardValidationTests(unittest.TestCase):
    def _issue_codes(self, issues: list[Any]) -> set[str]:
        return {issue.code for issue in issues}

    def test_verified_sequence_proof_card_passes(self) -> None:
        result = _detail_with_card(_verified_sequence_card())

        self.assertTrue(result.is_valid)
        card = result.normalized["report_evidence"]["proof_cards"][0]
        self.assertEqual(card["status"], "verified")
        self.assertEqual(card["recommendation_id"], "rec_001")

    def test_call_essence_contract_warnings_are_non_blocking(self) -> None:
        detail = {
            "report_evidence_version": "v1",
            "report_evidence": {
                "call_essence": {
                    "topic": "есть договоренность",
                    "outcome": "agreement",
                    "agreement": "есть договоренность",
                    "manager_visible_text": "есть договоренность",
                },
                "proof_cards": [],
                "situation_candidates": [],
                "manager_coaching_moments": [],
                "voice_of_customer": [],
                "additional_situations": [],
                "follow_up_candidates": [],
                "quote_bank": [],
            },
        }

        result = validate_report_evidence(detail, TRANSCRIPT)

        self.assertTrue(result.is_valid)
        self.assertFalse(result.errors)
        self.assertIn("call_essence_incomplete_follow_up_contract", self._issue_codes(result.warnings))
        self.assertIn("call_essence_generic_field", self._issue_codes(result.warnings))

    def test_verified_manager_gap_requires_recommendation_link(self) -> None:
        card = _verified_sequence_card()
        card["recommendation_id"] = None

        result = _detail_with_card(card)

        self.assertFalse(result.is_valid)
        self.assertIn(
            "proof_card_missing_recommendation_link",
            self._issue_codes(result.errors),
        )

    def test_quote_not_in_transcript_rejects_proof_card(self) -> None:
        card = _verified_sequence_card()
        card["supporting_evidence"][0]["quote"] = "This quote is not in the call."

        result = _detail_with_card(card)

        self.assertFalse(result.is_valid)
        self.assertIn("ungrounded_evidence_text", self._issue_codes(result.errors))

    def test_verified_card_with_counter_evidence_rejects_admission(self) -> None:
        card = _verified_sequence_card()
        card["counter_evidence"] = [
            {
                "evidence_id": "ev_counter_001",
                "quote": "We can talk tomorrow at 10.",
                "speaker": "manager",
            }
        ]

        result = _detail_with_card(card)

        self.assertFalse(result.is_valid)
        self.assertIn(
            "proof_card_counter_evidence_conflict",
            self._issue_codes(result.errors),
        )

    def test_verified_sequence_requires_two_supporting_points(self) -> None:
        card = _verified_sequence_card()
        card["supporting_evidence"] = card["supporting_evidence"][:1]
        card["evidence_ids"] = ["ev_001"]

        result = _detail_with_card(card)

        self.assertFalse(result.is_valid)
        self.assertIn(
            "proof_card_sequence_inference_too_thin",
            self._issue_codes(result.errors),
        )

    def test_softened_card_allows_counter_evidence_with_reason(self) -> None:
        card = _verified_sequence_card()
        card["status"] = "soften"
        card["counter_evidence"] = [
            {
                "evidence_id": "ev_counter_001",
                "quote": "We can talk tomorrow at 10.",
                "speaker": "manager",
            }
        ]
        card["outcome_reason"] = "Counter-evidence shows a specific next contact."

        result = _detail_with_card(card)

        self.assertTrue(result.is_valid)
        normalized = result.normalized["report_evidence"]["proof_cards"][0]
        self.assertEqual(normalized["status"], "soften")

    def test_verified_absence_based_card_requires_expected_element(self) -> None:
        card = _verified_sequence_card()
        card.update(
            {
                "proof_type": "absence_based",
                "supporting_evidence": [],
                "expected_absent_element": None,
            }
        )

        result = _detail_with_card(card)

        self.assertFalse(result.is_valid)
        self.assertIn(
            "proof_card_absence_without_expected_element",
            self._issue_codes(result.errors),
        )

    def test_verified_direct_quote_cannot_overclaim_context_quote(self) -> None:
        card = {
            "proof_id": "proof_next_step_002",
            "claim": "Менеджер не согласовал срок следующего контакта.",
            "claim_scope": "scene",
            "claim_type": "manager_gap",
            "proof_type": "direct_quote",
            "status": "verified",
            "stage_code": "completion_next_step",
            "scene_id": "scene_002",
            "evidence_id": "ev_003",
            "recommendation_id": "rec_002",
            "supporting_evidence": [
                {
                    "evidence_id": "ev_003",
                    "quote": "Хорошо, отправлю информацию.",
                    "speaker": "manager",
                }
            ],
            "counter_evidence": [],
        }

        result = _detail_with_card(
            card,
            transcript="Клиент: Скиньте материалы. Менеджер: Хорошо, отправлю информацию.",
        )

        self.assertFalse(result.is_valid)
        self.assertIn(
            "proof_card_claim_evidence_mismatch",
            self._issue_codes(result.errors),
        )


if __name__ == "__main__":
    unittest.main()
