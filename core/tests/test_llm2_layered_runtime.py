from __future__ import annotations

import json
import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
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


CORE_ROOT = Path(__file__).resolve().parents[1]
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from app.agents.calls.analyzer import APPROVED_INSTRUCTION_VERSION, CallsAnalyzer  # noqa: E402
from app.core_shared.exceptions import LLMResponseError, SemanticAnalysisError  # noqa: E402


TRANSCRIPT = (
    "Client: Please send the materials in WhatsApp. "
    "Manager: Sure, I will send the information."
)


def _interaction() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        external_id="layered-runtime-call",
        department_id=uuid4(),
        manager_id=None,
        source="onlinepbx",
        duration_sec=360,
        text=TRANSCRIPT,
        metadata_={"external_call_code": "layered-runtime-call"},
    )


def _pass_artifacts(*, proof_status: str = "proven") -> dict[str, dict]:
    rejected = proof_status in {"rejected", "insufficient"}
    llm2a = {
        "pass": "LLM-2A",
        "artifact_version": "llm2_pass_2a_v1",
        "call_id": "call-layered-runtime",
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
                "text": "Client: Please send the materials in WhatsApp.",
                "is_exact_transcript_quote": True,
                "source_span": None,
                "grounding_note": None,
            },
            {
                "evidence_id": "ev_002",
                "scene_id": "scene_001",
                "kind": "quote",
                "speaker": "manager",
                "text": "Manager: Sure, I will send the information.",
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
    }
    llm2b = {
        "pass": "LLM-2B",
        "artifact_version": "llm2_pass_2b_v1",
        "call_id": "call-layered-runtime",
        "criteria_results": [
            {
                "criterion_code": "cn_owner_and_deadline",
                "criterion_name": "Определил кто делает и когда",
                "stage_code": "completion_next_step",
                "applicable": True,
                "score": 0,
                "max_score": 2,
                "comment": "Manager did not anchor a concrete next contact.",
                "scene_ids": ["scene_001"],
                "evidence_ids": ["ev_001", "ev_002"],
                "missing_evidence_reason": None,
            }
        ],
        "strength_claims": [],
        "gap_claims": [
            {
                "claim_id": "claim_001",
                "claim_type": "manager_gap",
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
    }
    llm2c = {
        "pass": "LLM-2C",
        "artifact_version": "llm2_pass_2c_v1",
        "call_id": "call-layered-runtime",
        "proof_cards": [
            {
                "proof_id": "proof_001",
                "claim_id": "claim_001",
                "call_id": "call-layered-runtime",
                "stage_code": "completion_next_step",
                "claim": "Manager sent materials but did not anchor the next contact.",
                "claim_scope": "scene",
                "claim_type": "manager_gap",
                "scene_id": "scene_001",
                "supporting_evidence_ids": ["ev_001", "ev_002"],
                "counter_evidence_ids": [],
                "evidence_quote": None,
                "proof_type": "sequence_inference",
                "proof_status": proof_status,
                "gap_proven": not rejected,
                "claim_too_broad": False,
                "needs_softening": False,
                "softened_claim": None,
                "proof_explanation": "The exchange confirms sending materials but no next contact.",
                "reject_reason": "no_evidence" if rejected else None,
            }
        ],
    }
    llm2d = {
        "pass": "LLM-2D",
        "artifact_version": "llm2_pass_2d_v1",
        "call_id": "call-layered-runtime",
        "recommendations": []
        if rejected
        else [
            {
                "recommendation_id": "rec_001",
                "proof_id": "proof_001",
                "problem": "Next contact was not anchored.",
                "why_it_matters": "The client may review materials without a clear continuation.",
                "better_phrase": "I will send this now and call you tomorrow at 10.",
                "next_action": "Add a concrete date or condition to the final step.",
                "stage_code": "completion_next_step",
            }
        ],
        "universal_evidence_pack": {"proof_cards": [], "scenes": [], "evidence_ledger": []},
        "final_normalized_analysis": {
            "classification": {
                "call_type": "sales_primary",
                "scenario_type": "repeat_contact",
                "channel_context": "phone_call",
                "analysis_eligibility": "eligible",
                "eligibility_reason": "sales_relevant_exchange",
                "analysis_confidence": "medium",
            },
            "summary": {"short_summary": "Client asked for materials."},
            "agreements": [],
            "follow_up": {},
        },
    }
    return {
        "llm2a_facts_scenes": llm2a,
        "llm2b_scoring_gaps": llm2b,
        "llm2c_claim_proof": llm2c,
        "llm2d_recommendations": llm2d,
    }


class LLM2LayeredRuntimeTests(unittest.TestCase):
    def test_layered_llm2_is_default_and_runs_all_passes(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = _interaction()
        responses = _pass_artifacts()

        def fake_request(**kwargs):
            return json.dumps(deepcopy(responses[kwargs["request_kind"]]), ensure_ascii=False)

        with patch.dict(os.environ, {"AI_LLM2_ANALYSIS_MODE": ""}, clear=False), patch.object(
            analyzer,
            "_request_llm1_first_pass",
            return_value={"analysis_focus": []},
        ), patch.object(analyzer, "_request_llm_content", side_effect=fake_request) as llm_request:
            result = analyzer.analyze_call(
                interaction=interaction,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
            )

        request_kinds = [call.kwargs["request_kind"] for call in llm_request.call_args_list]
        self.assertEqual(
            request_kinds,
            [
                "llm2a_facts_scenes",
                "llm2b_scoring_gaps",
                "llm2c_claim_proof",
                "llm2d_recommendations",
            ],
        )
        self.assertEqual(result["llm2_layered_runtime"]["pass_artifact_keys"], ["llm2a", "llm2b", "llm2c", "llm2d"])

    def test_explicit_monolithic_llm2_mode_remains_available(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = _interaction()

        with patch.dict(os.environ, {"AI_LLM2_ANALYSIS_MODE": "monolithic"}, clear=False), patch.object(
            analyzer,
            "_request_llm1_first_pass",
            return_value={"analysis_focus": []},
        ), patch.object(analyzer, "_request_analysis_content", return_value="{}") as monolithic, patch.object(
            analyzer,
            "_load_and_validate_contract",
            return_value={"score_by_stage": []},
        ), patch.object(
            analyzer,
            "_analyze_call_with_layered_llm2",
            side_effect=AssertionError("layered path must not run in explicit monolithic mode"),
        ):
            result = analyzer.analyze_call(
                interaction=interaction,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
            )

        self.assertEqual(result, {"score_by_stage": []})
        monolithic.assert_called_once()

    def test_layered_llm2_runs_all_passes_and_stores_artifacts_and_metadata(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = _interaction()
        responses = _pass_artifacts()

        def fake_request(**kwargs):
            request_kind = kwargs["request_kind"]
            CallsAnalyzer._store_ai_routing_metadata(
                interaction=kwargs["interaction"],
                layer_metadata={
                    "layer": "llm2",
                    "request_kind": request_kind,
                    "selected_account_alias": f"{request_kind}_route",
                    "execution_status": "test_executed",
                },
            )
            return json.dumps(deepcopy(responses[request_kind]), ensure_ascii=False)

        with patch.dict(os.environ, {"AI_LLM2_ANALYSIS_MODE": "layered"}, clear=False), patch.object(
            analyzer,
            "_request_llm1_first_pass",
            return_value={"analysis_focus": []},
        ), patch.object(analyzer, "_request_llm_content", side_effect=fake_request):
            result = analyzer.analyze_call(
                interaction=interaction,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
            )

        runtime = result["llm2_layered_runtime"]
        self.assertTrue(runtime["enabled"])
        self.assertEqual(runtime["pass_artifact_keys"], ["llm2a", "llm2b", "llm2c", "llm2d"])
        self.assertEqual(
            runtime["pass_metadata"]["llm2c"]["request_kind"],
            "llm2c_claim_proof",
        )
        self.assertFalse(runtime["report_evidence_validation_enabled"])
        self.assertFalse(runtime["semantic_validation_enabled"])
        self.assertEqual(result["llm2_layered_artifacts"]["llm2a"]["pass"], "LLM-2A")
        self.assertEqual(result["gaps"][0]["proof_id"], "proof_001")
        self.assertEqual(result["recommendations"][0]["proof_id"], "proof_001")

    def test_rejected_layered_proof_is_not_resurrected_by_contract_enrichment(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = _interaction()
        responses = _pass_artifacts(proof_status="rejected")

        def fake_request(**kwargs):
            return json.dumps(deepcopy(responses[kwargs["request_kind"]]), ensure_ascii=False)

        with patch.dict(os.environ, {"AI_LLM2_ANALYSIS_MODE": "layered"}, clear=False), patch.object(
            analyzer,
            "_request_llm1_first_pass",
            return_value={"analysis_focus": []},
        ), patch.object(analyzer, "_request_llm_content", side_effect=fake_request):
            result = analyzer.analyze_call(
                interaction=interaction,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
            )

        self.assertEqual(result["gaps"], [])
        self.assertEqual(result["recommendations"], [])
        proof_card = result["report_evidence"]["proof_cards"][0]
        self.assertEqual(proof_card["status"], "reject")
        self.assertEqual(proof_card["reject_reason"], "missing_evidence")

    def test_layered_llm2_does_not_run_when_pre_admission_rejects_call(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = _interaction()

        with patch.dict(os.environ, {"AI_LLM2_ANALYSIS_MODE": "layered"}, clear=False), patch.object(
            analyzer,
            "_request_llm1_first_pass",
            return_value={
                "classification": {
                    "call_type": "support",
                    "analysis_eligibility": "not_eligible",
                    "eligibility_reason": "support_only_interaction",
                }
            },
        ), patch.object(analyzer, "_request_llm_content") as llm_request:
            with self.assertRaises(SemanticAnalysisError):
                analyzer.analyze_call(
                    interaction=interaction,
                    instruction_version=APPROVED_INSTRUCTION_VERSION,
                )

        llm_request.assert_not_called()

    def test_admitted_short_commercial_call_overrides_llm2a_not_eligible(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = _interaction()
        interaction.duration_sec = 75
        responses = _pass_artifacts()
        responses["llm2a_facts_scenes"]["analysis_eligibility"] = "not_eligible"
        responses["llm2a_facts_scenes"]["eligibility_reason"] = "duration_below_threshold"
        responses["llm2d_recommendations"]["final_normalized_analysis"]["classification"][
            "analysis_eligibility"
        ] = "not_eligible"
        responses["llm2d_recommendations"]["final_normalized_analysis"]["classification"][
            "eligibility_reason"
        ] = "duration_below_threshold"

        def fake_request(**kwargs):
            return json.dumps(deepcopy(responses[kwargs["request_kind"]]), ensure_ascii=False)

        with patch.dict(os.environ, {"AI_LLM2_ANALYSIS_MODE": "layered"}, clear=False), patch.object(
            analyzer,
            "_request_llm1_first_pass",
            return_value={
                "classification": {
                    "call_type": "sales_primary",
                    "analysis_eligibility": "not_eligible",
                    "eligibility_reason": "duration_below_threshold",
                }
            },
        ), patch.object(analyzer, "_request_llm_content", side_effect=fake_request):
            result = analyzer.analyze_call(
                interaction=interaction,
                instruction_version=APPROVED_INSTRUCTION_VERSION,
            )

        self.assertEqual(result["classification"]["analysis_eligibility"], "eligible")
        self.assertEqual(
            result["classification"]["eligibility_reason"],
            "llm2_admission_gate_accepted",
        )
        self.assertEqual(result["score_by_stage"][0]["stage_code"], "completion_next_step")
        self.assertTrue(
            result["llm2_layered_artifacts"]["llm2a"]["admission_gate_overrides"]
        )

    def test_admitted_commercial_call_fails_when_llm2b_returns_no_scores(self) -> None:
        analyzer = CallsAnalyzer(department_id=str(uuid4()), db=None)
        interaction = _interaction()
        interaction.duration_sec = 75
        responses = _pass_artifacts()
        responses["llm2a_facts_scenes"]["analysis_eligibility"] = "not_eligible"
        responses["llm2a_facts_scenes"]["eligibility_reason"] = "duration_below_threshold"
        responses["llm2b_scoring_gaps"]["criteria_results"] = []
        responses["llm2b_scoring_gaps"]["stage_scores"] = []
        responses["llm2b_scoring_gaps"]["gap_claims"] = []

        def fake_request(**kwargs):
            return json.dumps(deepcopy(responses[kwargs["request_kind"]]), ensure_ascii=False)

        with patch.dict(os.environ, {"AI_LLM2_ANALYSIS_MODE": "layered"}, clear=False), patch.object(
            analyzer,
            "_request_llm1_first_pass",
            return_value={
                "classification": {
                    "call_type": "sales_primary",
                    "analysis_eligibility": "not_eligible",
                    "eligibility_reason": "duration_below_threshold",
                }
            },
        ), patch.object(analyzer, "_request_llm_content", side_effect=fake_request):
            with self.assertRaises(LLMResponseError) as ctx:
                analyzer.analyze_call(
                    interaction=interaction,
                    instruction_version=APPROVED_INSTRUCTION_VERSION,
                )

        self.assertEqual(
            ctx.exception.reason_code,
            "llm2b_missing_scores_for_admitted_commercial_call",
        )


if __name__ == "__main__":
    unittest.main()
