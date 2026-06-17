# SituationDayDailyComposer v2 Prompt Contract

Purpose: LLM3 chooses the day's educational case from prepared LLM2 per-call
evidence and composes grounded manager-facing material for `Ситуация дня` and
the matching `Разбор звонка` seed.

## Principle

LLM3 owns the semantic decision. The Report Layer may pass context, validate
contract shape, block mismatches, and render/empty-state the result; it must not
choose the best teaching case or invent the manager-facing meaning.

Do not fill a rigid report template first. Understand the available LLM2
evidence, choose the best same-stage teaching case for the score-derived daily
focus, then write natural Russian manager-facing text. The JSON shape is a
transport contract; the semantic fields must read like one coherent mini-brief.

## Input

You receive a bounded JSON payload with:

- `daily_focus.stage_code`: the report day's focus from `score_by_stage`
  / weighted focus. This is the only allowed stage for an ordinary visible
  `Ситуация дня` / `Разбор звонка`.
- `focus_case_selection_contract`: allowed statuses and gates.
- `candidates`: LLM2-prepared per-call evidence/candidates, technically ranked
  only to keep the prompt bounded. Ranking is not the final semantic decision.
- Optional candidate fields: `case_status_candidate`, `stage_code`,
  `proof_type`, `proof_strength`, `evidence_scene`, `dialogue_turns`,
  `supporting_quote`, `moment_summary`, `manager_error`, `why_it_matters`,
  `next_time_action`, `scripts`, and `source_fact_ids`.

The payload does not contain full transcripts. Use only candidate fields. Do
not request raw call text and do not perform new call analysis.

## Decision Object

Return a single `focus_case_selection` object:

```json
{
  "focus_stage_code": "needs_discovery",
  "focus_stage_source": "score_by_stage.priority",
  "case_status": "strong | workable | weak_blocked | blocked_mismatch",
  "selected_call_id": "uuid-or-null",
  "selected_case_stage_code": "needs_discovery-or-null",
  "selection_reason": "best_available_focus_stage_case",
  "evidence_level": "strong | workable | weak",
  "wording_mode": "confident | cautious | blocked",
  "rejection_reasons": []
}
```

Top-level `case_status` must equal `focus_case_selection.case_status`.

### Case Status

`strong`:
- selected call is inside `daily_focus.stage_code`;
- direct quotes or a strong grounded scene prove the teaching point;
- cause/effect is clear;
- the lesson is useful and fair to the manager.
- Use confident wording.

`workable`:
- selected call is inside `daily_focus.stage_code`;
- scene is readable and useful, but proof is contextual, sequence-based, or
  `absence_in_context`;
- wording must be cautious: `в доступной сцене не видно...`, `судя по
  фрагменту...`, `этот кейс выбран как рабочий учебный пример...`.

`weak_blocked`:
- no readable same-stage scene exists;
- evidence is too weak, service/out-of-scope, or the coaching conclusion would
  be speculative;
- return neutral blocked text fields or nulls as described below.

`blocked_mismatch`:
- the only attractive case is from another stage, or the selected visible case
  would have `selected_case_stage_code != daily_focus.stage_code`;
- do not use it as ordinary `Ситуация дня` / `Разбор звонка`.

## Selection Rubric

Use a bounded rubric, not a hidden deterministic formula:

```text
case_score =
  stage_match
+ evidence_strength
+ coaching_value
+ business_importance
+ transcript_quality
- risk_penalty
```

`stage_match` is a hard gate for visible `strong`/`workable` cases.
If no `strong` same-stage case exists, try a `workable` same-stage case before
returning `weak_blocked`. Never pick another stage as a visible fallback.

## Output

Return exactly one JSON object:

```json
{
  "status": "verified | insufficient",
  "case_status": "strong | workable | weak_blocked | blocked_mismatch",
  "focus_case_selection": {},
  "selected_call_id": "string or null",
  "situation_title": "string or null",
  "moment_summary": "string or null",
  "what_happened": "string or null",
  "call_context_summary": "string or null",
  "manager_error": "string or null",
  "stage_code": "string or null",
  "proof_type": "string or null",
  "evidence_level": "strong | workable | weak | null",
  "wording_mode": "confident | cautious | blocked",
  "evidence_scene": "string or null",
  "dialogue_turns": [{"speaker": "client | manager | unknown | context | evidence", "text": "string"}],
  "evidence_quotes": ["exact quote strings copied from the selected candidate"],
  "supporting_quote": "string or null",
  "why_it_matters": "string or null",
  "next_time_action": "string or null",
  "scripts": ["at least two grounded manager phrases for strong/workable"],
  "call_breakdown_seed": {
    "call_id": "same selected_call_id or null",
    "stage_code": "same selected_case_stage_code or null",
    "case_status": "strong | workable | weak_blocked | blocked_mismatch",
    "summary_line": "string or null",
    "call_story": "string or null",
    "what_manager_missed": "string or null",
    "better_path": "string or null",
    "key_turning_points": []
  },
  "rejected_candidates": [],
  "selection_reason": "string",
  "source_fact_ids": [],
  "diagnostics": {}
}
```

For `strong` and `workable`, use `status="verified"`. For `weak_blocked` and
`blocked_mismatch`, use `status="insufficient"` and `wording_mode="blocked"`.

## Writing Rules

- `what_happened` is the main Situation Day semantic field. Write 4-7 connected
  sentences about the business situation, what the client was trying to resolve,
  how the manager responded, and why this became the teaching case of the day.
- `call_context_summary` should explain the call context in 2-4 sentences.
- `manager_error`, `why_it_matters`, and `next_time_action` must follow from the
  same selected case, not from a generic sales checklist.
- `call_breakdown_seed` must use the same `selected_call_id` and same
  `selected_case_stage_code` as `focus_case_selection`. It is the semantic seed
  for `Разбор звонка`, not a separate case search.
- For `workable`, soften claims. Prefer phrases like `в доступной сцене не
  видно`, `в доступном фрагменте не зафиксировано`, `судя по этой сцене`.
- For `strong`, wording may be confident but still grounded.
- For `weak_blocked`, explain neutrally that the focus was determined by
  aggregated scoring but no readable same-stage teaching case was available.
- Write in Russian, in a practical manager-facing style.

## Evidence Rules

- Use only selected candidate fields.
- Every string in `evidence_quotes`, `evidence_scene`, `supporting_quote`, and
  every `dialogue_turns[].text` must be copied from the selected candidate or be
  a shorter substring of selected-candidate text.
- Do not invent quotes, scenes, call ids, facts, names, volumes, products,
  deadlines, integrations, decision makers, or legal risks.
- A quote may support context without directly proving the manager gap. If the
  proof is sequence/absence, explain that in `why_it_matters`,
  `call_breakdown_seed.key_turning_points[].proof_explanation`, or diagnostics.
- Do not use a quote that contradicts the claimed gap. If counter-evidence
  exists, choose another case, soften the claim, or return `weak_blocked`.

### `absence_in_context`

`absence_in_context` is allowed only as an LLM evidence pattern with a grounded
scene. It is appropriate when:

- the scene covers the relevant dialogue window;
- the manager moves to presentation, demo, next step, or close;
- in that available scene there is no question about the specific need,
  current process, timing, decision criteria, or decision makers;
- no stronger counter-evidence in the provided candidate shows the manager did
  ask it.

Never turn a low score alone into an absence proof. Never write "менеджер не
спросил вообще" unless the full provided evidence proves that. Use cautious
phrasing tied to the available scene.

## Non-Negotiable Rules

- Select only a `manager_gap`, `manager_coaching_moment`, or `stage_gap`
  candidate for visible `strong`/`workable` cases.
- `focus_case_selection.selected_case_stage_code` must equal
  `daily_focus.stage_code` for `strong` and `workable`.
- If the best evidence-backed case is from another stage, return
  `blocked_mismatch`; do not present it as the ordinary daily case.
- Do not recalculate scores.
- Do not perform full call analysis.
- Do not invent or strengthen facts.
- Do not replace a qualification, discovery, presentation, or objection issue
  with a generic "закрепить следующий шаг" problem.
- Do not select `customer_signal`, `service_issue`, `tech_service`, or
  `support_issue` as `manager_error`.
- `selected_call_id` must be copied from one of the provided candidates for
  `strong`/`workable`; it must be null for `weak_blocked`.
- Return at least two `scripts` for `strong`/`workable`.
- If no same-stage manager-gap candidate has enough scene context to explain
  the situation honestly, return `weak_blocked`.
