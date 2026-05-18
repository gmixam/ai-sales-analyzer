# LLM2 v16 Context Evidence Overlay

This overlay is experimental. Use it only when `instruction_version` is
`edo_sales_mvp1_call_analysis_v16_context_evidence`.

Keep the approved MVP-1 contract and `report_evidence_version="v1"` shape.
Do not add new top-level fields. Do not remove required MVP-1 fields.

## Primary Goal

The manager-facing report must explain the call context well enough that a
manager who does not remember the call can understand:

- what happened;
- where the problem or growth point occurred;
- what the manager did or missed;
- how the customer reacted;
- why the moment matters;
- what dialogue evidence supports the conclusion;
- why the recommended action follows from the dialogue.

Do not treat the presence of a short quote as proof. A quote is useful only
when it helps explain the situation. If one quote is too short, use a broader
grounded dialogue fragment through existing fields such as
`semantic_case.best_dialogue_fragment`, `block_candidates.*.dialogue_fragment`,
`supporting_quote`, `proof_explanation`, and `quote_bank`.

## Source Of Truth

Build one coherent meaning first:

1. `report_evidence.semantic_case` is the primary meaning object.
2. Evidence fragments are the shared proof layer.
3. `report_evidence.block_candidates` are derived report views from the same
   semantic case, not a separate interpretation.
4. Legacy arrays such as `situation_candidates`, `manager_coaching_moments`,
   `voice_of_customer`, `additional_situations`, and `follow_up_candidates`
   should stay compatible, but must not contradict `semantic_case`.

If two fields describe the same moment, keep the same stage, problem,
customer signal, evidence, and recommendation. Do not create competing
versions of the truth.

## Context Requirements By Report Block

### Situation Day

For `situation_day`, explain the full situation:

- the call or moment that represents the pattern;
- the stage where the issue happened;
- what the manager did or did not clarify;
- what the customer was trying to understand or decide;
- why the missing action matters for the sale;
- what should be done differently next time.

If the evidence is based on sequence or absence, do not pretend there is a
direct quote. Use `proof_type=sequence_inference` or
`proof_type=absence_in_context`, set `quote_role=supports_context` or
`not_applicable`, and explain the proof in `proof_explanation`.

Never produce a confident `fit=true` problem block if the only available
content would render as `Нет данных` or generic wording.

### Call Breakdown

For `call_breakdown`, the required item is not a script line. The required item
is a clear explanation of what was wrong in the call.

Use a script, quote, or dialogue fragment only when it strengthens the proof.
If a single phrase does not prove the issue, include a short grounded dialogue
sequence or explain the sequence/absence that proves the issue.

Do not put a paraphrase into a field that is rendered as a quote or fragment.
If you are explaining, use explanatory fields such as `what_happened`,
`proof_explanation`, `what_was_missing`, `what_better`, or
`better_next_action`.

### Voice Of Customer

For `voice_of_customer`, do not show clipped phrases without context.

A customer phrase such as "Ладно, хорошо, я перезвоню" is not enough by itself.
Explain what came before it, what the customer was reacting to, what interest,
doubt, objection, or risk it shows, and why the recommended manager action
follows from that context.

Customer signal is not automatically a manager gap. Use customer-signal roles
for neutral customer signals unless the manager gap is separately proven.

### Tomorrow Follow-Up

For `tomorrow_follow_up`, the recommendation must match the real call outcome
and shown context.

Do not use a generic meeting-confirmation phrase when the customer only asked
to call back later. If the next step is weak, say that the manager should
clarify whether the topic is still актуален and then agree on a concrete next
step.

### Tomorrow Challenge

For `tomorrow_challenge`, base the challenge on applicable sales/coaching
calls, not every call in the report day. Service, technical, not suitable, and
too-thin calls should not inflate the challenge target.

## Evidence Quality Rules

- `supporting_quote` must be an exact transcript substring when present.
- A short quote can support context, but it does not prove a manager gap unless
  the gap is directly visible in that quote.
- For problem blocks, distinguish `proves_gap`, `supports_context`,
  `counter_evidence`, and `not_applicable`.
- If the proof is not direct, use `sequence_inference` or
  `absence_in_context` and explain why the conclusion follows.
- If the conclusion cannot be explained from transcript evidence, set the
  relevant candidate `fit=false` or mark evidence insufficient.
- Recommendations must be supported by the same context shown to the manager.

## Compatibility Rules

Keep the existing schema compatible:

- preserve `classification`, `summary`, `score_by_stage`, `strengths`,
  `gaps`, `recommendations`, `agreements`, `follow_up`,
  `evidence_fragments`, `report_evidence_version`, and `report_evidence`;
- keep `report_evidence.business_outcome` as a semantic signal only;
- keep deterministic reporting as final authority for final outcome, report
  scope, hotness, and delivery;
- use existing enum values only.
