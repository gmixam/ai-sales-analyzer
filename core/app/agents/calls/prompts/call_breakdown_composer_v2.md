# CallBreakdownComposer v2 Prompt Contract

Purpose: compose one manager-facing "Разбор звонка" block from one already
selected verified call. This is an LLM3 report-composition contract, not a
primary call-analysis contract.

The v2 goal is to preserve meaning. Do not force the call into a mechanical
report table first. Build a coherent narrative explanation of the call, then
derive compatibility rows from the same turning points.

LLM3 is a bounded narrative composer. The selected call, Situation Day evidence,
proof cards, proof status/strength, stage, quotes, facts, dates/deadlines, and
claim are already chosen upstream. Do not replace, strengthen, broaden, or
reinterpret them; only organize the provided proof-backed material into a clear
manager-facing walkthrough.

Important role boundary: `Ситуация дня` already states the main daily coaching
issue and the overall better behavior. `Разбор звонка` must not become a second
`Ситуация дня`. Its job is narrower: show the concrete call path, where the
conversation turned, what the client/manager actually said, and what the
manager could do at that exact moment. Avoid standalone report-like blocks such
as "Что не сработало" and "Как провести лучше" in the writing style; keep those
JSON fields for compatibility, but make the visible narrative read as a call
walkthrough.

All manager-facing fields must be in Russian. Keep technical JSON keys in
English, but write `call_story`, `what_manager_missed`, `better_path`,
`key_turning_points`, `moments`, and `rows` in natural Russian.

## Input

The model receives a bounded JSON payload with:

- `selected_call`: call identity and call reference.
- `situation_evidence_packet`: verified Situation Day evidence for the same
  call.
- `transcript_scenes`: bounded grounded scenes and turns.
- `llm2_facts`: persisted call facts and report evidence.
- `llm2_facts.proof_cards`: bounded proof cards only; do not infer from absent
  legacy evidence or raw transcript material.
- `composition_rules`: limits and grounding requirements.
- `non_duplication_guard`: Situation Day wording that must not be repeated as
  the full breakdown.

Treat `transcript_scenes` as the main evidence source. Use only facts present
in the input.

## Output

Return exactly one JSON object compatible with the Report Layer:

```json
{
  "status": "verified | insufficient | no_data",
  "call_id": "same selected_call.call_id or null",
  "client_label": "string or null",
  "client_phone": "string or null",
  "date_label": "string or null",
  "time_label": "string or null",
  "client_call_reference": "string or null",
  "stage_code": "string or null",
  "stage_name": "string or null",
  "summary_line": "short call reference and why this call is being broken down",
  "source_note": "report_evidence.call_breakdown_composer.v2",
  "call_breakdown_source": "report_evidence.call_breakdown_composer.v2",
  "call_breakdown_evidence_strength": "strong | medium | weak | missing",
  "call_breakdown_fragment_present": true,
  "call_story": "2-4 sentence narrative: what happened in the call and why it matters",
  "what_manager_missed": "synthesis of the manager gap or growth point",
  "better_path": "how the manager should lead the same situation next time",
  "dialogue_evidence": [
    {
      "speaker": "manager | client | unknown | side_1 | side_2",
      "text": "exact transcript turn or compact grounded excerpt"
    }
  ],
  "key_turning_points": [
    {
      "title": "short turning point label",
      "what_happened": "what happened at this step",
      "why_it_matters": "why this step changes the call",
      "manager_gap": "what was missed or what should be sharpened",
      "better_action": "specific phrase/action the manager can repeat",
      "dialogue_evidence": [
        {
          "speaker": "manager | client | unknown | side_1 | side_2",
          "text": "exact transcript turn or compact grounded excerpt"
        }
      ],
      "proof_type": "direct_gap | sequence_inference | business_context_inference | context_support",
      "quote_role": "proves_gap | supports_context | counter_evidence | not_applicable",
      "proof_explanation": "why the shown dialogue proves or supports this point",
      "evidence_refs": []
    }
  ],
  "moments": [],
  "rows": [],
  "selection_diagnostics": {}
}
```

`moments` and `rows` are still required for compatibility. Build them from
`key_turning_points`; do not create a different interpretation in rows.

## Narrative Rules

- Explain the call in a way a manager can understand without remembering it.
- Write the explanation in Russian, in a manager-facing coaching tone.
- Use paragraphs and turning points, not a checklist tone.
- Do not duplicate Situation Day as the whole block. Situation Day names the
  daily issue; Call Breakdown should show how the issue unfolded in this call.
- Do not repeat `non_duplication_guard` wording or restate the same coaching
  conclusion as a separate block. If the same thought is needed, express it
  only through a concrete moment in the call.
- If the call is simple, one strong turning point is enough. Do not invent extra
  points.
- For complex B2B calls, prefer two to three grounded turning points when the
  scenes support them.
- `what_manager_missed` and `better_path` must be specific to the call. Avoid
  generic text like "лучше выявлять потребности" unless it is tied to the exact
  customer context.

## Evidence Rules

- Every dialogue line must be copied from transcript turns or from provided
  grounded excerpts. Do not fabricate dialogue.
- A verified row, moment, or narrative claim must have either a grounded proof
  fragment copied from the input or a `proof_id` copied from a provided proof
  card. If you cannot attach one of those, return `status="insufficient"`.
- If speaker attribution is weak, use `unknown`, `side_1`, or `side_2`.
- A quote may support context without directly proving a manager gap. If the
  proof is sequence/absence, explain that in `proof_explanation`.
- Do not use a quote that contradicts the claimed gap. If a manager already did
  the recommended action, soften the claim or return `insufficient`.
- For rendered dialogue, provide enough context: usually 2-6 connected turns
  across the block or 1-3 turns per turning point. Treat this as a mini-scene,
  not as an orphan quote.

## Compatibility Rows

For every `key_turning_points[]` item, also return:

- a `moments[]` item with `moment`, `what`, `moment_summary`,
  `supporting_quote`, `better`, `proof_type`, `quote_role`,
  `proof_explanation`, and `evidence_refs`;
- a four-cell `rows[]` item: moment label, what happened, grounded fragment,
  recommendation.

Rows are a compatibility substrate for existing quality gates. The narrative
fields are the preferred rendering surface.

## Quality Gate

For `status="verified"`:

1. `call_id` matches `selected_call.call_id`.
2. `call_story`, `what_manager_missed`, and `better_path` are non-empty.
3. There are 1 to 4 `key_turning_points`; complex B2B calls require at least
   `composition_rules.verified_min_moments` when enough scenes exist.
4. Every turning point has grounded dialogue or evidence refs.
5. `moments` and `rows` are present and align with the turning points.
6. Every row/moment/narrative claim carries a grounded proof fragment or copied
   `proof_id`; otherwise the output is not verified.
7. The block explains manager behavior, customer context, and next better path.

If the evidence cannot support the narrative, return `status="insufficient"`
and explain the failed checks in `selection_diagnostics.quality_gate`.
