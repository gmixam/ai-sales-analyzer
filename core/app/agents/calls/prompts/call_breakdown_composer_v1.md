# CallBreakdownComposer v1 Prompt Contract

Purpose: compose one manager-facing "Разбор звонка" block from one already
selected verified call. This is an LLM3 report-composition contract, not a
primary call-analysis contract.

The composer must go deeper than "Ситуация дня": the Situation Day block names
the main problem, while Call Breakdown explains the manager's concrete mistakes
step by step, with grounded evidence and better wording.

## Input

The model receives a bounded JSON payload:

```json
{
  "contract_version": "call_breakdown_composer_v1",
  "selected_call": {
    "call_id": "string",
    "client_label": "string or null",
    "client_phone": "string or null",
    "date_label": "string or null",
    "time_label": "string or null",
    "client_call_reference": "string or null",
    "stage_code": "string or null",
    "stage_name": "string or null"
  },
  "situation_evidence_packet": {
    "status": "verified",
    "call_id": "same call_id",
    "problem_title": "string",
    "client_context": "string",
    "observed_manager_behavior": "string",
    "missing_action": "string",
    "causal_link": "string",
    "manager_lesson": "string",
    "dialogue_excerpt": {},
    "proof_type": "direct_gap | sequence_inference | business_context_inference",
    "proof_strength": "strong | medium | weak"
  },
  "transcript_scenes": [
    {
      "scene_id": "string",
      "call_id": "same call_id",
      "stage_code": "string or null",
      "purpose": "discovery | qualification | requirements | next_step | verified_situation_day | objection | closing | other",
      "summary": "short grounded summary",
      "turns": [
        {
          "speaker": "client | manager | unknown",
          "text": "exact or cleaned transcript text",
          "start_sec": 0,
          "end_sec": 0
        }
      ],
      "evidence_refs": [
        {
          "ref_id": "string",
          "call_id": "same call_id",
          "scene_id": "string",
          "turn_indexes": [0],
          "quote": "exact grounded fragment or null"
        }
      ]
    }
  ],
  "llm2_facts": {
    "business_outcome": "string or null",
    "call_report_summary": "string or null",
    "score_by_stage": [],
    "report_evidence": {},
    "semantic_case": {},
    "manager_coaching_moments": [],
    "block_candidates": {}
  },
  "composition_rules": {
    "complex_b2b_detected": true,
    "verified_min_moments": 2,
    "verified_target_moments": 3,
    "verified_max_moments": 4,
    "rows_required": true,
    "fragment_context_min_chars": 90,
    "fragment_must_be_mini_scene": true,
    "same_call_only": true
  },
  "non_duplication_guard": {
    "situation_day_problem_title": "string",
    "situation_day_what_happened": "string",
    "situation_day_recommendation": "string"
  }
}
```

## Output

Return exactly one JSON object. The object must be directly compatible with the
Report Layer `call_breakdown` block:

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
  "source_note": "report_evidence.call_breakdown_composer.v1",
  "call_breakdown_source": "report_evidence.call_breakdown_composer.v1",
  "call_breakdown_evidence_strength": "strong | medium | weak | missing",
  "call_breakdown_fragment_present": true,
  "moment_summary": "short synthesis of the main manager behavior",
  "missing_action": "what the manager failed to do",
  "why_it_matters": "business consequence for this client context",
  "supporting_quote": "best grounded evidence fragment or null",
  "proof_type": "direct_gap | sequence_inference | business_context_inference",
  "proof_explanation": "why the evidence proves the moment",
  "moments": [
    {
      "moment": "Момент 1 - short label",
      "call_id": "same selected_call.call_id",
      "what": "what happened in this exact step",
      "moment_summary": "why this step is a coaching issue",
      "supporting_quote": "grounded quote or compact dialogue excerpt",
      "supporting_quote_proof_type": "direct_gap | sequence_inference | context_support",
      "better": "specific phrase/action the manager should use next time",
      "proof_type": "direct_gap | sequence_inference | business_context_inference",
      "quote_role": "proves_gap | supports_context | counter_evidence",
      "proof_explanation": "how the fragment proves this moment",
      "evidence_refs": []
    }
  ],
  "rows": [
    [
      "Момент 1 - short label",
      "Что было не так: concrete behavior and missing step.",
      "Фрагмент: grounded transcript context.",
      "Сказать: concrete suggested phrase."
    ]
  ],
  "selection_diagnostics": {
    "composer_version": "call_breakdown_composer_v1",
    "selected_call_id": "same selected_call.call_id",
    "rejected_moments": [],
    "quality_gate": {}
  }
}
```

## Non-Negotiable Rules

- Use only facts present in `selected_call`, `transcript_scenes`,
  `situation_evidence_packet`, `llm2_facts`, and their `evidence_refs`.
- Treat `transcript_scenes` as the main evidence source. Prefer connected turns
  from `discovery`, `qualification`, `requirements`, and `next_step` scenes
  over isolated quotes from `situation_evidence_packet`.
- Speaker labels may be inferred when diarization is weak. Use them as helpful
  orientation, but do not build a conclusion only on the label; prove it through
  the sequence and text.
- Do not invent client names, volumes, entities, user counts, roles, deadlines,
  products, integrations, legal risks, meetings, demo agreements, or next steps.
- Keep `call_id` equal to `selected_call.call_id` everywhere. Do not switch to
  another call.
- Return 1 to 4 moments for `status="verified"`. For simple calls, one strong
  grounded moment is better than two weak artificial moments. For complex B2B calls with
  several entities, roles, access rights, legal constraints, or implementation
  workflow, prefer 3 grounded moments, but do not invent weak extra moments:
  return at least 2 grounded moments if the input supports only two.
- Follow `composition_rules` exactly. If
  `composition_rules.complex_b2b_detected=true`, `status="verified"` must have
  at least `composition_rules.verified_min_moments` moments and the same number
  of rows. Otherwise the Report Layer will reject the response.
- Each moment must include `evidence_refs`. If a quote is used, it must be
  grounded in the transcript scene. A paraphrase is allowed only as context, not
  as proof.
- Do not make the quote mandatory when the problem is proven by sequence. In
  that case, use a compact dialogue excerpt and explain the sequence in
  `proof_explanation`. The fragment column must show context as a mini-scene:
  2 to 5 connected turns or a compact contextual excerpt. Do not use isolated
  one-line fragments such as "Давайте сейчас уточню" as the whole proof.
- `rows` is mandatory for `status="verified"`. Build every row from the same
  moment and use a mini-scene in the fragment/context cell.
- Recommendations must be concrete phrases or actions the manager can repeat:
  "Сказать: ..." or "Сделать: ...". Avoid abstract advice such as "лучше
  выявлять потребности" without wording.
- Do not duplicate Situation Day. Do not repeat the same title, same summary, or
  same generic recommendation. Break the same call into concrete steps:
  requirements summary, missing clarification, decision/process control, demo or
  next-step fixation, risk handling, or closing.
- If the input contains counter-evidence that the manager already did the
  recommended action, do not present that action as missing.
- If the manager partially clarified users, roles, participants, access, or who
  will use the system, do not write an absolute claim like "manager did not
  clarify who will use it". Phrase the gap as partial: the manager started
  clarifying, but did not fix roles, participants, decision process, or the next
  step.
- Do not use positive-only praise for a problem breakdown unless it is clearly
  marked as a strong practice moment.

## Quality Gate

For `status="verified"` the answer must pass all checks:

1. `call_id` is present and matches `selected_call.call_id`.
2. There are 1 to 4 moments; complex B2B calls normally target 3 moments and
   require at least `composition_rules.verified_min_moments`.
3. Every moment has `what`, `moment_summary`, `better`, `proof_type`,
   `proof_explanation`, and `evidence_refs`.
4. Every row has four cells: moment, what happened, fragment/context,
   recommendation. The fragment/context cell must be understandable without
   remembering the call and must not be a short isolated phrase.
5. At least one row explains what the manager should summarize back to the
   client.
6. At least one row fixes a controlled next step: demo, scheduled call,
   participants, deadline, or exact follow-up objective.
7. The block explains the manager behavior, not only the client's need.

If any check fails, return `status="insufficient"` and explain the failed checks
in `selection_diagnostics.quality_gate`.

## Pilot B2B Pattern

For complex B2B calls, especially when a client describes multiple entities,
roles, access rights, user groups, legal constraints, or implementation
workflow, the breakdown should usually separate:

1. Missing requirements summary: the manager should repeat the client's process
   in business language.
2. Missing qualification: the manager should clarify roles, decision makers,
   users, deadlines, volume, and success criteria.
3. Missing controlled next step: the manager should not end with vague
   "уточню/перезвоню"; the next step should be a demo, scheduled call, or
   concrete follow-up with participants and purpose.

Example recommendation style:

- "Сказать: «Правильно понял: у вас 16 школ, нужен общий кабинет для головного
  офиса и разграничение доступов по школам. Давайте я зафиксирую роли и покажу,
  как это выглядит в кабинете»."
- "Сказать: «Чтобы не просто уточнять, предлагаю короткий демо-созвон на 20
  минут: покажем общий кабинет, роли доступа и сценарий подписания через ЭЦП.
  Кого подключить со стороны головного офиса?»"
