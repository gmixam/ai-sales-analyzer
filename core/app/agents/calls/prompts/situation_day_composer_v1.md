# SituationDayComposer v1 Prompt Contract

Purpose: compose one manager-facing "Ситуация дня" block from already prepared
day-level artifacts. This is an LLM3 report-composition contract, not a call
analysis contract.

## Input

The model receives a bounded JSON payload:

```json
{
  "contract_version": "situation_day_composer_v1",
  "candidates": [
    {
      "candidate_id": "call-id:source:pattern",
      "call_id": "string",
      "pattern_code": "proposal_without_microqualification | complex_b2b_without_controlled_next_step | interest_without_decision | sequence_gap | ...",
      "source": "report_evidence... | transcript.pattern_inference",
      "score": 0,
      "problem_title": "string",
      "client_context": "string",
      "evidence_scene": "string",
      "manager_gap": "string",
      "why_it_matters": "string",
      "next_time_action": "string",
      "suggested_phrase": "string",
      "proof_type": "direct_gap | sequence_inference | business_context_inference",
      "proof_strength": "strong | medium | weak",
      "evidence_refs": []
    }
  ]
}
```

## Output

Return exactly one JSON object:

```json
{
  "status": "verified | insufficient | no_data",
  "selected_candidate_id": "string or null",
  "selected_call_id": "string or null",
  "problem_title": "string or null",
  "client_context": "string or null",
  "evidence_scene": "string or null",
  "manager_gap": "string or null",
  "why_it_matters": "string or null",
  "next_time_action": "string or null",
  "suggested_phrase": "string or null",
  "proof_type": "direct_gap | sequence_inference | business_context_inference | null",
  "proof_strength": "strong | medium | weak | null",
  "rejected_candidates": [],
  "quality_diagnostics": {}
}
```

## Non-Negotiable Rules

- Use only facts present in candidate fields and `evidence_refs`.
- Do not invent client names, volumes, roles, deadlines, products, integrations,
  decision makers, meetings, or legal risks.
- A single short quote is not enough. The block must explain the sequence:
  client context, what happened, what the manager missed, why it matters, and
  the next action.
- If the best candidate lacks client context, evidence scene, manager gap, or a
  concrete action, return `status="insufficient"`.
- If there are no candidates or no transcript/analysis facts, return
  `status="no_data"`.
- Preserve `selected_call_id` from the chosen candidate.
- Preserve `selected_candidate_id` from the chosen candidate.
- Keep `proof_type` and `proof_strength` consistent with the input. Do not
  upgrade weak proof to strong.

## Supported Pilot Patterns

1. `proposal_without_microqualification`: the client asks for a commercial
   proposal, and the manager agrees before clarifying volume, users, role,
   decision process, criteria, or timeline.
2. `complex_b2b_without_controlled_next_step`: the client describes roles,
   entities, users, volume, integrations, legal risk, or access rules, but the
   manager ends with vague "уточню/перезвоню" instead of a demo, participants,
   date, or requirements summary.
3. `interest_without_decision`: the client shows explicit interest, but the
   manager does not fix the next step, participants, deadline, and purpose.
4. `sequence_gap`: the problem is proven by the order of the conversation, not
   by one quote.
