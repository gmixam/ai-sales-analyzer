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
- No day-level educational case selection in any pass. LLM-2 may prepare
  per-call evidence/candidates for `situation_day` and `call_breakdown`, but
  only LLM-3 chooses the day's case from the score-derived focus.
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
  "case_status_candidate": ["strong", "workable", "weak_blocked"],
  "coaching_decision": ["improve", "maintain", "no_comment"],
  "sales_scoring_scope": ["full", "partial", "none", "unclear"],
  "scope_reason": [
    "edo_sales",
    "edo_service",
    "legal_direction",
    "tech_support",
    "internal_or_wrong_call",
    "mixed",
    "insufficient_data",
    "other"
  ],
  "expected_manager_action": [
    "sell",
    "transfer",
    "support",
    "clarify",
    "close_service_issue",
    "keep_relationship",
    "no_action",
    "other"
  ],
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
  "edo_scope": {
    "sales_scoring_scope": "full|partial|none|unclear",
    "scope_reason": "edo_sales|edo_service|legal_direction|tech_support|internal_or_wrong_call|mixed|insufficient_data|other",
    "applicable_part": "string|null",
    "expected_manager_action": "sell|transfer|support|clarify|close_service_issue|keep_relationship|no_action|other",
    "evidence_ids": ["ev_001"]
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
- `edo_scope` is a compact applicability contract for EDO sales scoring. It
  must not duplicate `business_outcome_signal`, future `business_outcome`,
  `status_details`, `analysis_eligibility`, full quotes, or the full
  `evidence_ledger`.
- LLM-2A must not assume every call is sales-applicable by default. Use
  `full`, `partial`, `none`, or `unclear` based on transcript evidence and
  LLM-1 only as a prior hint. For mixed or unusual scenarios, preserve nuance
  with `partial`, `other`, `unclear`, `applicable_part`, and
  `expected_manager_action` instead of forcing one narrow label.

## LLM-2B: Scoring / Gaps

Purpose: evaluate only the scenes from LLM-2A against the checklist.

Input:

```json
{
  "call_id": "string",
  "llm2a_artifact": {},
  "edo_scope": {},
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
      "applicable": true,
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

- redefining, overriding, or narrowing LLM-2A `edo_scope`;
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
- Use LLM-2A `edo_scope` to decide EDO sales applicability. If
  `sales_scoring_scope=none`, mark sales criteria/stages non-applicable and do
  not create sales penalties. If `sales_scoring_scope=unclear`, avoid hard
  sales scoring without evidence and record cautious applicability notes. If
  `sales_scoring_scope=partial`, score only the sales part described in
  `applicable_part` and mark the rest non-applicable.
- For `tech_support`, `legal_direction`, `edo_service`,
  `internal_or_wrong_call`, insufficient-data, or out-of-scope `other`, record
  service/transfer/support context as non-coachable where appropriate rather
  than turning it into an EDO sales gap.
- Do not duplicate `business_outcome`, `status_details`, or the full
  `evidence_ledger` in scoring output. Reference ids and keep the scenario's
  full meaning; use `partial`, `other`, and `unclear` when needed.
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
- `absence_based` / compatibility `absence_in_context` is allowed only when the
  proof card points to a bounded grounded scene where the missing action would
  have appeared, and no stronger counter-evidence shows the manager did it.
  Use cautious language: `в доступной сцене не видно...`, not an absolute claim
  about the whole call.

## LLM-2D: Recommendations / Universal Evidence Pack

Purpose: produce final normalized analysis using only proven or softened proof
cards, and choose one compact coaching decision for the call.

Input:

```json
{
  "call_id": "string",
  "llm2a_artifact": {},
  "llm2b_artifact": {},
  "llm2c_artifact": {},
  "edo_scope": {},
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
  "coaching_decision": {
    "decision": "improve|maintain|no_comment",
    "title": "Улучшить|Поддерживать|Корректно|null",
    "text": "string|null",
    "reason": "string",
    "based_on": {
      "stage_code": "string|null",
      "criterion_codes": ["string"],
      "proof_ids": ["proof_001"],
      "evidence_ids": ["ev_001"]
    }
  },
  "universal_evidence_pack": {
    "proof_cards": [],
    "scenes": [],
    "evidence_ledger": [],
    "business_outcome_signal": {},
    "quote_bank": [],
    "report_case_candidates": [
      {
        "candidate_id": "case_001",
        "call_id": "string",
        "stage_code": "string",
        "block_targets": ["situation_day", "call_breakdown"],
        "claim_type": "manager_gap|strong_practice",
        "case_status_candidate": "strong|workable|weak_blocked",
        "evidence_level": "strong|workable|weak",
        "wording_mode": "confident|cautious|blocked",
        "proof_ids": ["proof_001"],
        "scene_ids": ["scene_001"],
        "evidence_ids": ["ev_001"],
        "selection_notes_for_llm3": "string",
        "rejection_reasons": []
      }
    ]
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
    "status_details": {
      "status": "agreement|rescheduled|refusal|open|service",
      "agreement": null,
      "rescheduled": null,
      "refusal": null,
      "open": null,
      "service": null
    },
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

Use LLM-2A `edo_scope` when producing recommendations and compatibility
analysis. Do not redefine scope. Do not apply sales-push recommendations to
`tech_support`, `legal_direction`, `edo_service`, internal/wrong-call,
out-of-scope `other`, or unclear calls. For `partial`, address only the sales
portion named in `applicable_part` and preserve the non-sales context. For
`none` or `unclear`, recommendations should focus on transfer, support,
clarification, service closure, relationship maintenance, or cautious review as
appropriate.

Recommendations and compatibility fields must not duplicate
`business_outcome`, `status_details`, or the full `evidence_ledger`; use proof
ids and `edo_scope.evidence_ids`. Do not narrow the call meaning: keep mixed,
other, and uncertain cases explicit instead of forcing them into a simple sales
failure.

`coaching_decision` is the manager-facing coaching source of truth:

- `decision=improve` is allowed only when an important manager gap is proven or
  safely softened, is applicable to the manager's role and the call scope, and
  could plausibly affect the call result. Use `title="Улучшить"` and link the
  decision to concrete `proof_ids`/`evidence_ids`.
- `decision=maintain` is used when no important applicable gap is proven, but a
  proven or safely softened `strong_practice` or useful manager action is worth
  reinforcing. Use `title="Поддерживать"` for commercial best practice or
  `title="Корректно"` for confirmed service, transfer, support,
  clarification, relationship, or service-closure behavior.
- `decision=no_comment` is used when there is neither a proven important gap nor
  a specific strong action worth reinforcing. Set `title=null`, `text=null`,
  and explain the reason briefly.

Decision logic:

```text
Proven important gap? -> improve
No gap, useful action? -> maintain
Neither gap nor strong action? -> no_comment
```

Scores, low stage values, weak-stage counts, gap candidates, report columns,
open status, `status_details`, proof cards, and `edo_scope` are input signals;
they never automatically create a recommendation. Do not force
`Улучшить`/`decision=improve` because a score is low or a report field expects a
recommendation. If the relevant proof card is `rejected` or `insufficient`, the
gap cannot become `Улучшить`.

For `edo_scope.sales_scoring_scope=none|unclear`, do not create a sales-push
decision or compatibility recommendation. A `maintain`/`Корректно` decision is
allowed only when supported by confirmed service, transfer, support,
clarification, relationship, or service-closure evidence.

Legacy `recommendations` are the compatibility view for
`coaching_decision.decision=improve`. When the decision is `maintain` or
`no_comment`, do not invent a legacy improvement recommendation.

`final_normalized_analysis.status_details` must describe the factual details
of the final status for the report "Итог" line. Use the LLM-2A
`business_outcome_signal.status` as source of truth, map `tech_service` to
`service`, fill only the matching status structure, and keep all other status
structures `null`. Unknown facts stay `null`.

Status structures:

- `agreement`: `type`, `what_agreed`, `manager_commitment`,
  `client_commitment`, `owner`, `deadline`, `evidence`
- `rescheduled`: `reason`, `return_when`, `return_owner`,
  `preparation_needed`, `evidence`
- `refusal`: `type`, `reason`, `finality`, `return_condition`,
  `recommended_next_action`, `evidence`
- `open`: `why_open`, `missing_to_close`, `next_action`, `owner`, `deadline`,
  `evidence`
- `service`: `type`, `request`, `action_taken`, `follow_up_needed`,
  `follow_up_action`, `owner`, `sales_scoring_applicability`, `evidence`
  Use `edo_scope.sales_scoring_scope` for `sales_scoring_applicability`; do not
  infer a different value from `status_details`.

Forbidden:

- creating new gaps or claims;
- using rejected or insufficient proof cards for confident recommendations;
- creating `Улучшить` only because a score is low, a gap candidate exists, a
  call ended open, or a report column needs text;
- converting service, legal-direction, technical-support, internal/wrong-call,
  out-of-scope, or unclear calls into "did not sell" recommendations;
- choosing report sections such as `situation_day`, `call_breakdown`,
  `voice_of_customer`, or `tomorrow_follow_up`;
- strengthening a softened claim back into a hard claim.

Fail-closed behavior:

- No proven or softened manager-gap proof card means no confident improvement
  recommendation. Use `maintain` only for confirmed strong practice; otherwise
  use `no_comment`.
- Rejected and insufficient proof cards may remain in audit output, but must not
  appear as verified manager-facing guidance.

Downstream boundary:

- Report Layer must display only the prepared `coaching_decision`; it must not
  build a fallback recommendation from scores, gaps, statuses, or templates.
- LLM-2D may expose `report_case_candidates` and compatibility
  `semantic_case`/`block_candidates`/`report_block_fit` evidence for downstream
  report composition. These are per-call candidates, not final daily blocks.
- LLM-3 may group, shorten, deduplicate, or select existing LLM-2D
  `improve`/`maintain` decisions and report-case candidates for day-level
  reporting.
- LLM-3 owns the semantic choice of the educational case of the day:
  it receives the score-derived `daily_focus.stage_code`, tries a `strong`
  same-stage case first, may choose a `workable` same-stage case with cautious
  wording, and returns `weak_blocked` when no readable same-stage case exists.
- LLM-3 must not invent `Улучшить` when LLM-2D returned `maintain` or
  `no_comment`, upgrade `maintain` into a criticism, create a recommendation
  when LLM-2D gave none, or add sales-push advice for service/out-of-scope
  scenarios.
- LLM-3 must not use a candidate from another stage as the ordinary
  `СИТУАЦИЯ ДНЯ` / `РАЗБОР ЗВОНКА`. A stage mismatch becomes
  `blocked_mismatch`, not a visible fallback.

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
- `analyze_recommendations`: generate `coaching_decision`, recommendations,
  and compatibility output only from accepted proof cards and grounded
  evidence.

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
- `LLM-2D.coaching_decision` -> source of truth for manager-facing coaching
  display (`Улучшить`, `Поддерживать`/`Корректно`, or no comment).
- `LLM-2D.recommendations` -> current legacy improvement `recommendations`,
  each linked to a `proof_id` and consistent with
  `coaching_decision.decision=improve`.
- `LLM-2D.universal_evidence_pack.proof_cards` -> future normalized proof
  pool for validators, registry, router, and report layer.
- `LLM-2D.universal_evidence_pack.report_case_candidates` plus compatibility
  `report_evidence.semantic_case`, `report_block_fit`, `block_candidates`, and
  `manager_coaching_moments` -> LLM-3 input for `focus_case_selection`.
  Candidate-level `case_status_candidate` may guide LLM-3, but LLM-3 returns
  the final `case_status`.

Compatibility views may be generated from proof cards, but they must never be
treated as stronger than their source proof.

LLM-3 may consume compatibility views for aggregation, but must not treat them
as permission to create new coaching advice beyond the LLM-2D
`coaching_decision`.
