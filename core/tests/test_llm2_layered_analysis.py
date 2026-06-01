from __future__ import annotations

import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path


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

from app.agents.calls.llm2_layered_analysis import normalize_llm2_layered_analysis  # noqa: E402


TRANSCRIPT = (
    "Client: Please send the materials in WhatsApp. "
    "Manager: Sure, I will send the information."
)


def _layered_artifact() -> dict:
    return {
        "llm2a_artifact": {
            "pass": "LLM-2A",
            "artifact_version": "llm2_pass_2a_v1",
            "call_id": "call-layered-001",
            "analysis_eligibility": "eligible",
            "eligibility_reason": "sales_relevant_exchange",
            "scenes": [
                {
                    "scene_id": "scene_001",
                    "order": 1,
                    "stage_hint": "completion_next_step",
                    "what_happened": "Client asked for materials and manager agreed to send them.",
                    "manager_actions": ["Agreed to send information."],
                    "client_reactions": ["Asked for WhatsApp materials."],
                    "observed_commitments": ["Manager will send information."],
                    "deadlines_or_timing": [],
                    "objections": [],
                    "service_or_refusal_signals": [],
                    "evidence_ids": ["ev_001", "ev_002"],
                }
            ],
            "evidence_ledger": [
                {
                    "evidence_id": "ev_001",
                    "scene_id": "scene_001",
                    "kind": "quote",
                    "speaker": "client",
                    "text": "Please send the materials in WhatsApp.",
                    "is_exact_transcript_quote": True,
                    "source_span": None,
                    "grounding_note": None,
                },
                {
                    "evidence_id": "ev_002",
                    "scene_id": "scene_001",
                    "kind": "quote",
                    "speaker": "manager",
                    "text": "Sure, I will send the information.",
                    "is_exact_transcript_quote": True,
                    "source_span": None,
                    "grounding_note": None,
                },
            ],
            "business_outcome_signal": {
                "status": "open",
                "confidence": "medium",
                "evidence_ids": ["ev_001"],
                "reason": "Client asked to receive materials before deciding.",
            },
        },
        "llm2b_artifact": {
            "pass": "LLM-2B",
            "artifact_version": "llm2_pass_2b_v1",
            "call_id": "call-layered-001",
            "criteria_results": [
                {
                    "criterion_code": "sf_next_step_clarity",
                    "criterion_name": "Следующий шаг понятен обеим сторонам",
                    "stage_code": "completion_next_step",
                    "applicable": True,
                    "score": 1,
                    "max_score": 2,
                    "comment": (
                        "Manager promised materials but did not anchor a concrete next contact."
                    ),
                    "scene_ids": ["scene_001"],
                    "evidence_ids": ["ev_001", "ev_002"],
                    "missing_evidence_reason": None,
                }
            ],
            "strength_claims": [],
            "gap_claims": [
                {
                    "claim_id": "claim_001",
                    "claim_type": "gap",
                    "stage_code": "completion_next_step",
                    "claim": "Manager sent materials but did not anchor the next contact.",
                    "claim_scope": "scene",
                    "scene_ids": ["scene_001"],
                    "evidence_ids": ["ev_001", "ev_002"],
                    "expected_behavior": "Agree a date or condition for the next contact.",
                    "observed_behavior": "Only sending materials was confirmed.",
                    "confidence": "medium",
                }
            ],
        },
        "llm2c_artifact": {
            "pass": "LLM-2C",
            "artifact_version": "llm2_pass_2c_v1",
            "call_id": "call-layered-001",
            "proof_cards": [
                {
                    "proof_id": "proof_001",
                    "claim_id": "claim_001",
                    "call_id": "call-layered-001",
                    "stage_code": "completion_next_step",
                    "claim": "Manager sent materials but did not anchor the next contact.",
                    "claim_scope": "scene",
                    "claim_type": "manager_gap",
                    "scene_id": "scene_001",
                    "supporting_evidence_ids": ["ev_001", "ev_002"],
                    "counter_evidence_ids": [],
                    "evidence_quote": None,
                    "proof_type": "sequence_inference",
                    "proof_status": "proven",
                    "gap_proven": True,
                    "claim_too_broad": False,
                    "needs_softening": False,
                    "softened_claim": None,
                    "proof_explanation": (
                        "The exchange confirms sending materials but no next contact."
                    ),
                    "reject_reason": None,
                }
            ],
        },
        "llm2d_artifact": {
            "pass": "LLM-2D",
            "artifact_version": "llm2_pass_2d_v1",
            "call_id": "call-layered-001",
            "recommendations": [
                {
                    "recommendation_id": "rec_001",
                    "proof_id": "proof_001",
                    "problem": "Next contact was not anchored.",
                    "why_it_matters": (
                        "The client may review materials without a clear continuation."
                    ),
                    "better_phrase": "I will send this now and call you tomorrow at 10.",
                    "next_action": "Add a concrete date or condition to the final step.",
                    "stage_code": "completion_next_step",
                }
            ],
            "universal_evidence_pack": {
                "proof_cards": [],
                "scenes": [],
                "evidence_ledger": [],
                "business_outcome_signal": {},
                "quote_bank": [],
            },
            "final_normalized_analysis": {
                "summary": {"short": "Client asked for materials."},
                "agreements": [],
                "follow_up": {},
            },
        },
    }


class LLM2LayeredAnalysisTests(unittest.TestCase):
    def _issue_codes(self, result) -> set[str]:
        validation = result.report_evidence_validation
        self.assertIsNotNone(validation)
        return {issue.code for issue in validation.errors}

    def test_normalizes_layered_artifact_to_scores_detail_and_validates_proof_cards(self) -> None:
        result = normalize_llm2_layered_analysis(_layered_artifact(), transcript=TRANSCRIPT)

        self.assertTrue(result.is_valid)
        detail = result.scores_detail
        self.assertEqual(detail["call"]["call_id"], "call-layered-001")
        self.assertEqual(detail["report_evidence_version"], "v1")
        self.assertEqual(detail["score"]["checklist_score"]["total_points"], 1)
        self.assertEqual(detail["score"]["checklist_score"]["max_points"], 2)
        self.assertEqual(detail["score_by_stage"][0]["stage_code"], "completion_next_step")
        self.assertEqual(detail["gaps"][0]["proof_id"], "proof_001")
        self.assertEqual(detail["recommendations"][0]["proof_id"], "proof_001")
        proof_card = detail["report_evidence"]["proof_cards"][0]
        self.assertEqual(proof_card["proof_id"], "proof_001")
        self.assertEqual(proof_card["status"], "proven")
        self.assertEqual(proof_card["recommendation_id"], "rec_001")
        call_essence = detail["report_evidence"]["call_essence"]
        self.assertEqual(call_essence["topic"], "Client asked for materials.")
        self.assertEqual(call_essence["outcome"], "open")
        self.assertIn("Client asked to receive materials", call_essence["outcome_reason"])
        self.assertIn("Manager will send information", call_essence["agreement"])
        self.assertIn("Add a concrete date", call_essence["next_step"])
        self.assertNotIn("_claim_id", proof_card)
        layered_metadata = detail["layered_analysis"]
        self.assertEqual(
            layered_metadata["adapter_instruction_version"],
            "llm2_layered_analysis_adapter_v1",
        )
        self.assertTrue(layered_metadata["pass_artifacts"]["llm2a"]["present"])
        self.assertTrue(layered_metadata["pass_artifacts"]["llm2a"]["valid_shape"])
        self.assertEqual(layered_metadata["proof_card_counts"]["proven"], 1)
        self.assertEqual(layered_metadata["proof_card_counts"]["accepted"], 1)

    def test_rejected_proof_card_stays_in_audit_but_not_manager_facing_guidance(self) -> None:
        artifact = _layered_artifact()
        proof_card = artifact["llm2c_artifact"]["proof_cards"][0]
        proof_card.update(
            {
                "proof_status": "rejected",
                "gap_proven": False,
                "reject_reason": "no_evidence",
                "proof_explanation": "The claim lacks enough evidence.",
            }
        )

        result = normalize_llm2_layered_analysis(artifact, transcript=TRANSCRIPT)

        self.assertTrue(result.is_valid)
        self.assertEqual(result.scores_detail["gaps"], [])
        self.assertEqual(result.scores_detail["recommendations"], [])
        proof_card = result.scores_detail["report_evidence"]["proof_cards"][0]
        self.assertEqual(proof_card["status"], "reject")
        self.assertEqual(proof_card["reject_reason"], "missing_evidence")

    def test_ungrounded_layered_quote_fails_existing_report_evidence_gate(self) -> None:
        artifact = deepcopy(_layered_artifact())
        artifact["llm2a_artifact"]["evidence_ledger"][1]["text"] = "This quote is absent."

        result = normalize_llm2_layered_analysis(artifact, transcript=TRANSCRIPT)

        self.assertFalse(result.is_valid)
        self.assertIn("ungrounded_evidence_text", self._issue_codes(result))
        proof_card = result.scores_detail["report_evidence"]["proof_cards"][0]
        self.assertEqual(proof_card["proof_id"], "proof_001")

    def test_missing_or_invalid_proof_pass_does_not_emit_manager_facing_guidance(self) -> None:
        cases = []

        missing_proof_pass = deepcopy(_layered_artifact())
        del missing_proof_pass["llm2c_artifact"]
        cases.append((missing_proof_pass, None))

        missing_supporting_evidence = deepcopy(_layered_artifact())
        missing_supporting_evidence["llm2c_artifact"]["proof_cards"][0][
            "supporting_evidence_ids"
        ] = ["ev_missing_001", "ev_missing_002"]
        cases.append((missing_supporting_evidence, "retry"))

        for artifact, expected_status in cases:
            with self.subTest(expected_status=expected_status):
                result = normalize_llm2_layered_analysis(artifact, transcript=TRANSCRIPT)

                self.assertTrue(result.is_valid)
                self.assertEqual(result.scores_detail["gaps"], [])
                self.assertEqual(result.scores_detail["recommendations"], [])
                proof_cards = result.scores_detail["report_evidence"]["proof_cards"]
                if expected_status is None:
                    self.assertEqual(proof_cards, [])
                    self.assertFalse(
                        result.scores_detail["layered_analysis"]["pass_artifacts"]["llm2c"][
                            "present"
                        ]
                    )
                else:
                    self.assertEqual(proof_cards[0]["status"], expected_status)
                    self.assertEqual(
                        result.scores_detail["layered_analysis"]["proof_card_counts"][
                            expected_status
                        ],
                        1,
                    )

    def test_counter_evidence_and_unsupported_sequence_remain_non_verified(self) -> None:
        counter_evidence_artifact = deepcopy(_layered_artifact())
        counter_evidence_artifact["llm2a_artifact"]["evidence_ledger"].append(
            {
                "evidence_id": "ev_counter_001",
                "scene_id": "scene_001",
                "kind": "quote",
                "speaker": "manager",
                "text": "We can talk tomorrow at 10.",
                "is_exact_transcript_quote": True,
            }
        )
        counter_evidence_artifact["llm2c_artifact"]["proof_cards"][0][
            "counter_evidence_ids"
        ] = ["ev_counter_001"]

        counter_result = normalize_llm2_layered_analysis(
            counter_evidence_artifact,
            transcript=f"{TRANSCRIPT} Manager: We can talk tomorrow at 10.",
        )

        self.assertTrue(counter_result.is_valid)
        counter_card = counter_result.scores_detail["report_evidence"]["proof_cards"][0]
        self.assertEqual(counter_card["status"], "soften")
        self.assertNotIn(counter_card["status"], {"verified", "proven"})
        self.assertEqual(
            counter_result.scores_detail["layered_analysis"]["proof_card_counts"][
                "soften"
            ],
            1,
        )

        thin_sequence_artifact = deepcopy(_layered_artifact())
        thin_sequence_artifact["llm2c_artifact"]["proof_cards"][0][
            "supporting_evidence_ids"
        ] = ["ev_001"]

        thin_result = normalize_llm2_layered_analysis(
            thin_sequence_artifact,
            transcript=TRANSCRIPT,
        )

        self.assertTrue(thin_result.is_valid)
        thin_card = thin_result.scores_detail["report_evidence"]["proof_cards"][0]
        self.assertEqual(thin_card["status"], "retry")
        self.assertEqual(thin_result.scores_detail["gaps"], [])
        self.assertEqual(thin_result.scores_detail["recommendations"], [])

    def test_stage_aliases_normalize_across_layered_outputs(self) -> None:
        artifact = deepcopy(_layered_artifact())
        artifact["llm2b_artifact"]["criteria_results"][0][
            "stage_code"
        ] = "qualification_pain"
        artifact["llm2b_artifact"]["gap_claims"][0]["stage_code"] = "next_step"
        artifact["llm2c_artifact"]["proof_cards"][0]["stage_code"] = "closing"
        artifact["llm2d_artifact"]["recommendations"][0]["stage_code"] = "sale"

        result = normalize_llm2_layered_analysis(artifact, transcript=TRANSCRIPT)

        self.assertTrue(result.is_valid)
        detail = result.scores_detail
        self.assertEqual(
            detail["criteria_results"][0]["stage_code"],
            "qualification_primary",
        )
        self.assertEqual(detail["score_by_stage"][0]["stage_code"], "qualification_primary")
        self.assertEqual(detail["gaps"][0]["stage_code"], "completion_next_step")
        self.assertEqual(
            detail["report_evidence"]["proof_cards"][0]["stage_code"],
            "completion_next_step",
        )
        self.assertEqual(detail["recommendations"][0]["stage_code"], "sale_final")

    def test_preserves_runtime_diagnostics_alongside_layered_metadata(self) -> None:
        artifact = deepcopy(_layered_artifact())
        artifact["llm2d_artifact"]["final_normalized_analysis"]["diagnostics"] = {
            "runtime_agent": {
                "execution_status": "subagent_executed",
                "output_artifact": "/tmp/llm2d_output.json",
            }
        }

        result = normalize_llm2_layered_analysis(artifact, transcript=TRANSCRIPT)

        self.assertTrue(result.is_valid)
        self.assertEqual(
            result.scores_detail["diagnostics"]["runtime_agent"]["execution_status"],
            "subagent_executed",
        )
        self.assertEqual(
            result.scores_detail["layered_analysis"]["pass_artifacts"]["llm2d"][
                "artifact_version"
            ],
            "llm2_pass_2d_v1",
        )

    def test_root_admission_gate_overrides_downstream_not_eligible(self) -> None:
        artifact = deepcopy(_layered_artifact())
        artifact["llm2_admission_gate"] = {
            "admitted": True,
            "reason_code": "llm2_admission_accepted",
            "duration_is_not_stop_condition": True,
        }
        artifact["llm2a_artifact"]["analysis_eligibility"] = "not_eligible"
        artifact["llm2a_artifact"]["eligibility_reason"] = "duration_below_threshold"
        artifact["llm2d_artifact"]["final_normalized_analysis"]["classification"] = {
            "call_type": "sales_primary",
            "analysis_eligibility": "not_eligible",
            "eligibility_reason": "duration_below_threshold",
        }

        result = normalize_llm2_layered_analysis(artifact, transcript=TRANSCRIPT)

        self.assertTrue(result.is_valid)
        classification = result.scores_detail["classification"]
        self.assertEqual(classification["analysis_eligibility"], "eligible")
        self.assertEqual(classification["eligibility_reason"], "llm2_admission_gate_accepted")
        self.assertEqual(
            classification["eligibility_reason_before_admission_gate"],
            "duration_below_threshold",
        )
        self.assertTrue(classification["eligibility_overridden_by_admission_gate"])
        self.assertEqual(
            result.scores_detail["diagnostics"]["llm2_admission_gate"]["reason_code"],
            "llm2_admission_accepted",
        )
        self.assertEqual(
            result.scores_detail["score_by_stage"][0]["stage_code"],
            "completion_next_step",
        )


if __name__ == "__main__":
    unittest.main()
