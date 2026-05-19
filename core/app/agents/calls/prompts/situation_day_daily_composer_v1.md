# SituationDayDailyComposer v1 Prompt Contract

Purpose: compose one grounded manager-facing `Ситуация дня` block from a
prepared daily input package. This is report composition only.

## Input

You receive a bounded JSON payload with up to 8 candidates. The payload does not
contain full transcripts or full call analysis.

Each candidate contains only:

- `candidate_id`
- `call_id`
- `evidence_type`
- `score`
- `source`
- `situation_title`
- `moment_summary`
- `what_happened`
- `manager_error`
- `evidence_scene`
- `dialogue_turns`
- `supporting_quote`
- `why_it_matters`
- `next_time_action`
- `scripts`
- `source_fact_ids`
- `proof_strength`

## Output

Return exactly one JSON object:

```json
{
  "status": "verified | insufficient",
  "selected_call_id": "string or null",
  "situation_title": "string or null",
  "moment_summary": "string or null",
  "what_happened": "string or null",
  "manager_error": "string or null",
  "evidence_scene": "string or null",
  "dialogue_turns": [{"speaker": "client | manager | unknown", "text": "string"}],
  "supporting_quote": "string or null",
  "why_it_matters": "string or null",
  "next_time_action": "string or null",
  "scripts": ["at least two grounded manager phrases"],
  "rejected_candidates": [],
  "selection_reason": "string",
  "source_fact_ids": [],
  "diagnostics": {}
}
```

## Non-Negotiable Rules

- Select only a `manager_gap`, `manager_coaching_moment`, or `stage_gap`
  candidate.
- Never select `customer_signal`, `service_issue`, `tech_service`, or
  `support_issue` as `manager_error`.
- Do not recalculate scores.
- Do not perform full call analysis.
- Do not invent quotes, scenes, call ids, facts, names, volumes, products,
  deadlines, integrations, decision makers, or legal risks.
- `selected_call_id` must be copied from one of the provided candidates.
- `evidence_scene` and `supporting_quote` must be grounded in the selected
  candidate. Use exact provided text or a shorter substring from provided text.
- Do not use call ids that are absent from the payload.
- Return at least two `scripts`. Scripts must follow the selected
  `manager_error` and `next_time_action`.
- If no manager-gap candidate has a concrete scene and manager error, return
  `status="insufficient"`.
