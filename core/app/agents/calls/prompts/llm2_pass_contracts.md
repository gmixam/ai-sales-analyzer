# LLM2 Pass Contracts 2A/2B/2C/2D

Status: handoff-ready contract asset.

This file defines the target split for future LLM-2 implementation. It is not
wired into runtime by itself. The current production prompt remains
`analyze.md` until the analyzer runner is explicitly changed.

## Global Rules

- Return JSON only for every pass.
- Use only transcript, segments, metadata, checklist text, approved contracts,
  and previous pass artifacts.
- Do not invent transcript facts, names, timestamps, commitments, quotes, or
  speaker roles.
- Direct quotes must be exact transcript substrings.
- Use `unknown` when speaker attribution is not reliable.
- No report block selection in any pass.
- `semantic_case`, `block_candidates`, `report_block_fit`, and legacy report
  arrays are compatibility views, not source of truth.
- Source of truth order is:
  `transcript -> scenes -> evidence -> claim -> proof_card -> recommendation`.
- Fail closed: weak or missing evidence becomes `insufficient`, `rejected`, or
  `needs_softening`; it must not become a confident coaching claim.
- Admission boundary: the analyze / do_not_analyze decision is made before
  LLM-2. LLM-2A/2B/2C/2D must not add whole-call stop conditions for an
  admitted commercial call. They may mark specific facts, criteria, claims, or
  recommendations as insufficient, not applicable, softened, or rejected.
- Duration, short-call status, refusal-like flow, or limited sales development
  may affect which stages are applicable, but must not by itself stop LLM-2
  processing after the call has entered LLM-2.

Common enums:

```json
{
  "speaker": ["manager", "client", "unknown"],
  "evidence_kind": ["quote", "dialogue_sequence", "observed_action", "absence_marker", "metadata"],
  "claim_scope": ["scene", "call", "day"],
  "claim_type": ["manager_gap", "customer_signal", "follow_up", "business_outcome", "strong_practice"],
  "proof_type": ["direct_quote", "sequence_inference", "absence_based"],
  "proof_status": ["proven", "softened", "rejected", "insufficient"],
  "reject_reason": [
    "no_scene",
    "no_evidence",
    "quote_not_exact",
    "counter_evidence_stronger",
    "claim_too_broad",
    "unsupported_absence",
    "not_sales_coaching",
    "contradicts_transcript"
  ]
}
```

ID stability:

- `scene_id`: `scene_001`, `scene_002`, ...
- `evidence_id`: `ev_001`, `ev_002`, ...
- `claim_id`: `claim_001`, `claim_002`, ...
- `proof_id`: `proof_001`, `proof_002`, ...
- `recommendation_id`: `rec_001`, `rec_002`, ...

## LLM-2A: Facts / Scenes / Evidence Ledger

Purpose: describe what happened before any checklist scoring or coaching
diagnosis.

Input:

```json
{
  "call_id": "string",
  "metadata": {},
  "transcript": "string",
  "segments": [],
  "llm1_first_pass": {},
  "checklist_observation_frame": {}
}
```

Required output:

```json
{
  "pass": "LLM-2A",
  "artifact_version": "llm2_pass_2a_v1",
  "call_id": "string",
  "analysis_eligibility": "eligible|not_eligible|insufficient",
  "eligibility_reason": "string|null",
  "scenes": [
    {
      "scene_id": "scene_001",
      "order": 1,
      "stage_hint": "stage_code|null",
      "what_happened": "string",
      "manager_actions": ["string"],
      "client_reactions": ["string"],
      "observed_commitments": ["string"],
      "deadlines_or_timing": ["string"],
      "objections": ["string"],
      "service_or_refusal_signals": ["string"],
      "evidence_ids": ["ev_001"]
    }
  ],
  "evidence_ledger": [
    {
      "evidence_id": "ev_001",
      "scene_id": "scene_001",
      "kind": "quote|dialogue_sequence|observed_action|absence_marker|metadata",
      "speaker": "manager|client|unknown",
      "text": "exact quote or bounded factual observation",
      "is_exact_transcript_quote": true,
      "source_span": "timestamp/segment/null",
      "grounding_note": "string|null"
    }
  ],
  "business_outcome_signal": {
    "status": "agreement|rescheduled|refusal|open|tech_service|not_suitable|insufficient",
    "confidence": "high|medium|low",
    "evidence_ids": ["ev_001"],
    "reason": "string"
  },
  "fail_closed": {
    "insufficient_transcript": false,
    "speaker_roles_uncertain": false,
    "reject_reasons": []
  }
}
```

Optional fields:

- `language_notes`
- `metadata_observations`
- `transcript_quality_notes`

Forbidden:

- checklist scores;
- strengths, gaps, coaching claims, or recommendations;
- report block fit, report block names, or report routing.

Fail-closed behavior:

- If the transcript is technically empty or unusable, return
  `analysis_eligibility=insufficient`, keep `scenes` and `evidence_ledger`
  empty or minimal, and explain why.
- If the transcript is short but contains a bounded commercial interaction,
  return `analysis_eligibility=eligible` and extract the available scenes and
  evidence. LLM-2A must not close downstream scoring only because the call is
  short, refusal-like, rescheduled, or commercially limited.
- `analysis_eligibility=not_eligible` is compatibility-only for clearly
  misrouted non-call/non-analysis input. It is not a scoring stop signal for an
  admitted commercial call.
- If a quote is not exact, set `is_exact_transcript_quote=false` and do not use
  it later as direct proof.

## LLM-2B: Scoring / Gaps

Purpose: evaluate only the scenes from LLM-2A against the checklist.

Input:

```json
{
  "call_id": "string",
  "llm2a_artifact": {},
  "checklist_definition": {},
  "mvp1_contract_shape": {}
}
```

Required output:

```json
{
  "pass": "LLM-2B",
  "artifact_version": "llm2_pass_2b_v1",
  "call_id": "string",
  "criteria_results": [
    {
      "criterion_code": "string",
      "criterion_name": "string",
      "stage_code": "string",
      "applicable": true,
      "score": 0,
      "max_score": 2,
      "comment": "string",
      "scene_ids": ["scene_001"],
      "evidence_ids": ["ev_001"],
      "missing_evidence_reason": "string|null"
    }
  ],
  "stage_scores": [
    {
      "stage_code": "string",
      "score": 0,
      "max_score": 2,
      "criterion_codes": ["string"],
      "comment": "string",
      "scene_ids": ["scene_001"],
      "evidence_ids": ["ev_001"]
    }
  ],
  "strength_claims": [
    {
      "claim_id": "claim_001",
      "claim_type": "strength",
      "stage_code": "string",
      "claim": "string",
      "scene_ids": ["scene_001"],
      "evidence_ids": ["ev_001"],
      "confidence": "high|medium|low"
    }
  ],
  "gap_claims": [
    {
      "claim_id": "claim_002",
      "claim_type": "gap",
      "stage_code": "string",
      "claim": "string",
      "claim_scope": "scene|call|day",
      "scene_ids": ["scene_001"],
      "evidence_ids": ["ev_001"],
      "expected_behavior": "string",
      "observed_behavior": "string",
      "confidence": "high|medium|low"
    }
  ],
  "fail_closed": {
    "claims_without_scene_rejected": 0,
    "claims_without_evidence_rejected": 0,
    "reject_reasons": []
  }
}
```

Optional fields:

- `applicability_notes`
- `non_coachable_reasons`

Forbidden:

- creating a gap without `scene_ids` and `evidence_ids`;
- recommendations;
- proof status beyond preliminary confidence;
- report block fit or report routing.

Fail-closed behavior:

- LLM-2B must not add a second whole-call eligibility gate. Do not return empty
  `criteria_results`, `stage_scores`, or claims only because
  `llm2a_artifact.analysis_eligibility` is `not_eligible`, `insufficient`,
  duration-below-threshold, short-call, weak-commercial, or refusal-like.
- If LLM-2A contains usable scenes/evidence, score every checklist
  criterion/stage that is applicable to those scenes. For non-observed stages,
  mark criteria not applicable or explain missing evidence; do not invent a
  gap and do not force a zero.
- Empty `stage_scores` is allowed only when the input is technically unusable:
  no scenes, no usable evidence, or an artifact shape that prevents scoring. In
  that case, add a diagnostic retry reason to `fail_closed.reject_reasons`.
- If a checklist issue has no concrete scene, do not emit a `gap_claim`.
- If evidence is weak, lower confidence and let LLM-2C decide proof status.

## LLM-2C: Claim Proof Check

Purpose: prove, soften, or reject every preliminary claim from LLM-2B.

Input:

```json
{
  "call_id": "string",
  "llm2a_artifact": {},
  "llm2b_artifact": {}
}
```

Required output:

```json
{
  "pass": "LLM-2C",
  "artifact_version": "llm2_pass_2c_v1",
  "call_id": "string",
  "proof_cards": [
    {
      "proof_id": "proof_001",
      "claim_id": "claim_002",
      "call_id": "string",
      "stage_code": "string",
      "claim": "string",
      "claim_scope": "scene|call|day",
      "claim_type": "manager_gap|customer_signal|follow_up|business_outcome|strong_practice",
      "scene_id": "scene_001",
      "supporting_evidence_ids": ["ev_001"],
      "counter_evidence_ids": [],
      "evidence_quote": "string|null",
      "proof_type": "direct_quote|sequence_inference|absence_based",
      "proof_status": "proven|softened|rejected|insufficient",
      "gap_proven": true,
      "claim_too_broad": false,
      "needs_softening": false,
      "softened_claim": "string|null",
      "proof_explanation": "string",
      "reject_reason": null
    }
  ],
  "claim_audit": {
    "input_claim_count": 0,
    "proven_count": 0,
    "softened_count": 0,
    "rejected_count": 0,
    "insufficient_count": 0
  },
  "fail_closed": {
    "unmatched_claim_ids": [],
    "reject_reasons": []
  }
}
```

Optional fields:

- `counter_evidence_notes`
- `quote_grounding_notes`
- `absence_proof_notes`

Forbidden:

- new claims not present in LLM-2B;
- recommendations;
- report block fit or report routing;
- upgrading weak/context evidence into direct proof.

Fail-closed behavior:

- If `evidence_quote` is used for direct proof, it must be exact.
- If counter-evidence weakens the claim, use `softened` or `rejected`.
- If absence is not visible from the available dialogue sequence, use
  `proof_status=insufficient` and `reject_reason=unsupported_absence`.

## LLM-2D: Recommendations / Universal Evidence Pack

Purpose: produce final normalized analysis using only proven or softened proof
cards.

Input:

```json
{
  "call_id": "string",
  "llm2a_artifact": {},
  "llm2b_artifact": {},
  "llm2c_artifact": {},
  "mvp1_contract_shape": {},
  "report_evidence_contract_v1": {}
}
```

Required output:

```json
{
  "pass": "LLM-2D",
  "artifact_version": "llm2_pass_2d_v1",
  "call_id": "string",
  "recommendations": [
    {
      "recommendation_id": "rec_001",
      "proof_id": "proof_001",
      "problem": "string",
      "why_it_matters": "string",
      "better_phrase": "string|null",
      "next_action": "string",
      "stage_code": "string"
    }
  ],
  "universal_evidence_pack": {
    "proof_cards": [],
    "scenes": [],
    "evidence_ledger": [],
    "business_outcome_signal": {},
    "quote_bank": []
  },
  "final_normalized_analysis": {
    "classification": {},
    "summary": {},
    "score_by_stage": [],
    "criteria_results": [],
    "strengths": [],
    "gaps": [],
    "recommendations": [],
    "agreements": [],
    "follow_up": {},
    "evidence_fragments": [],
    "report_evidence_version": "v1",
    "report_evidence": {}
  },
  "compatibility_notes": {
    "mvp1_scores_detail_compatible": true,
    "legacy_report_fields_are_derived": true,
    "report_block_selection_excluded": true
  },
  "fail_closed": {
    "recommendations_without_proof_rejected": 0,
    "proof_cards_not_used": [],
    "reject_reasons": []
  }
}
```

Optional fields:

- `softened_recommendation_notes`
- `downstream_validation_hints`
- `legacy_field_mapping`

Forbidden:

- creating new gaps or claims;
- using rejected or insufficient proof cards for confident recommendations;
- choosing report sections such as `situation_day`, `call_breakdown`,
  `voice_of_customer`, or `tomorrow_follow_up`;
- strengthening a softened claim back into a hard claim.

Fail-closed behavior:

- No proven or softened proof card means no confident coaching
  recommendation.
- Rejected and insufficient proof cards may remain in audit output, but must not
  appear as verified manager-facing guidance.

## Prompt Split

Prompt files map one-to-one to the pass names:

```text
analyze_facts_scenes.md          -> LLM-2A
analyze_scoring_gaps.md          -> LLM-2B
analyze_claim_proof.md           -> LLM-2C
analyze_recommendations.md       -> LLM-2D
```

Until runtime wiring exists, these prompt files are handoff assets only. Do not
infer that adding these prompt files alone changes analyzer behavior.

Instruction boundaries:

- `analyze_facts_scenes`: observe, quote, segment, and classify basic call
  facts only.
- `analyze_scoring_gaps`: score observed scenes by checklist and create only
  preliminary claims.
- `analyze_claim_proof`: evaluate preliminary claims against supporting and
  counter evidence.
- `analyze_recommendations`: generate recommendations and compatibility output
  only from accepted proof cards.

## Final Assembly Mapping

The final persisted artifact must remain compatible with current
`Analysis.scores_detail` until a migration is approved.

Mapping:

- `LLM-2A.scenes` -> source for `evidence_fragments`,
  `report_evidence.quote_bank`, and future normalized scenes.
- `LLM-2A.business_outcome_signal` -> source for
  `report_evidence.business_outcome`, still subordinate to deterministic
  reporting-layer final outcome.
- `LLM-2A.business_outcome_signal` + `LLM-2A.scenes` + accepted
  `LLM-2D.recommendations` -> source for `report_evidence.call_essence`.
  This is the normalized manager-facing source for both daily call-list context
  and follow-up/contact context. It must expose `topic`, `outcome`,
  `refusal_or_interest_reason`/`outcome_reason`, `agreement`, `next_step`,
  optional `deadline`, optional `service_request`, and `manager_visible_text`.
  For `agreement|rescheduled|open`, preserve topic + agreement + next step.
  For `refusal`, preserve the short refusal reason. For `tech_service`, preserve
  the service/support request. Do not output generic essence such as
  `есть договоренность`; leave unsupported fields null.
- `LLM-2B.criteria_results` -> current MVP-1 `criteria_results` and
  `score_by_stage`.
- `LLM-2B.strength_claims` -> current `strengths`, after proof/grounding
  consistency check.
- `LLM-2B.gap_claims` + `LLM-2C.proof_cards` -> current `gaps` only when
  proof is `proven` or safely `softened`.
- `LLM-2D.recommendations` -> current `recommendations`, each linked to a
  `proof_id`.
- `LLM-2D.universal_evidence_pack.proof_cards` -> future normalized proof
  pool for validators, registry, router, and report layer.

Compatibility views may be generated from proof cards, but they must never be
treated as stronger than their source proof.
