# LLM2 v17 Universal Evidence Boundary Overlay

This overlay is experimental. Use it only when `instruction_version` is
`edo_sales_mvp1_call_analysis_v17_univ_evidence`.

Keep the approved MVP-1 contract shape and all existing schema fields. Do not
delete fields or invent replacement fields. If a compatibility field is not
needed for the core analysis, keep it empty, `null`, or otherwise schema-safe.

## Ownership Boundary

LLM2 owns the call meaning layer:

- facts and semantic interpretation of what happened in the call;
- checklist scoring and score explanations;
- manager gaps, strengths, and recommendations;
- universal evidence that can be reused by any report layer.

LLM2 does not write report-specific blocks. LLM3 and the deterministic report layer own final block selection, block writing, layout, and delivery behavior.

## Primary Universal Signals

Treat these as the primary reusable signals for downstream reporting:

- `report_evidence.call_essence`;
- `report_evidence.semantic_case`;
- `report_evidence.quote_bank`;
- `evidence_fragments`;
- `call_report_summary`;
- `business_outcome`;
- `voice_of_customer`.

These fields should carry coherent meaning, facts, customer signals, evidence,
and recommendations without depending on any one report block format.

`report_evidence.call_essence` is the normalized manager-facing source for the
daily call table and follow-up/contact views. Fill it from transcript facts only:

- `topic`: what the call was concretely about;
- `outcome`: `agreement|rescheduled|refusal|open|tech_service|not_suitable`;
- `refusal_or_interest_reason` / `outcome_reason`: why the client refused,
  showed interest, stayed open, or needed service help;
- `agreement`: what was actually agreed, if anything;
- `next_step`: the concrete next manager/client action, if present;
- `deadline`: only if explicitly stated;
- `service_request`: the concrete service/support issue for tech/service calls;
- `manager_visible_text`: one concise Russian sentence suitable for the call
  list.

For `agreement`, `rescheduled`, and `open`, include topic, agreement, and next
step. A generic line such as `есть договоренность` is insufficient. For
`refusal`, include the short refusal reason. For `tech_service`, include the
essence of the request. If the transcript does not support a field, leave it
null instead of inventing it.

## Compatibility Views

`report_evidence.block_candidates.*` and
`semantic_case.report_block_fit.*` are optional compatibility or derived views.
Populate them only when they naturally follow from the universal evidence. They
are not required core output and must not become a separate report-writing task.

If populated, compatibility views must not contradict the primary semantic
case, quote bank, evidence fragments, business outcome, or voice of customer.
