# PROMPTS_GUIDE

## Purpose
This document defines how prompt assets should be organized and how prompt instructions must be split between permanent project policies and task-specific requests.

Prompt files are product assets and versioned contracts, not disposable text snippets and not content that should be re-explained in every task prompt.

## 1. Permanent Prompt Policies

These rules are stable by default and should live in prompt assets, source documents, or standing docs.

### 1.1 Prompt asset ownership
- Keep prompts in dedicated markdown files under the relevant agent.
- Treat prompt files as source assets, not inline code literals.
- Do not hardcode production prompt text in runtime code.

### 1.2 Contract and schema stability
- Preserve the output JSON contract even when wording changes.
- Prompt revisions must not change downstream schema unless there is an explicitly planned breaking migration.
- Schema constraints belong in prompt assets and source-of-truth docs, not in repeated task prompts.

### 1.3 Versioning
- Every production prompt change must be traceable to a version label or release note.
- Track prompt changes together with `instruction_version` in persisted analysis records.
- If prompt experiments are introduced later, each analysis row must retain the exact `instruction_version` used.

### 1.4 Stable behavior rules
- Language expectations should live in prompt assets or policy docs when they are stable for a stage or artifact class.
- Output behavior rules should live in prompt assets or policy docs when they are stable for a stage or artifact class.
- Restrictions against hallucinated fields, free-form drift, or schema-breaking output should live in prompt assets or source docs when they are persistent requirements.
- Examples must stay concise and aligned with the active schema.

## 2. What Must Not Be Repeated In Every Task Prompt

The following belong in source prompt assets and/or project docs unless the current task is explicitly changing them:
- language expectations for stable artifact classes;
- business-output localization rules;
- output formatting behavior that is already approved;
- JSON schema and field constraints;
- prompt versioning expectations;
- general anti-hallucination and structured-output guardrails;
- default stage policies that already live in a stage spec.

## 3. What Task Prompts Should Still Contain

Task prompts should contain only the variable part of the current step:
- current stage, if it matters for the task;
- current step and objective;
- exact artifact or case under work;
- concrete scope boundaries for this task;
- expected output for this task;
- explicit local restrictions or temporary exceptions.

If a task prompt starts re-listing stable language, output, and schema rules that already exist in source assets or docs, it is probably too long.

## 4. Authoring Checklist For Prompt Changes

Use this checklist when editing prompt assets:
- Define the task clearly.
- Define required output fields explicitly if the prompt owns them.
- Reference stable language/output policies instead of duplicating them.
- Keep examples short and contract-aligned.
- Preserve backward-compatible behavior unless a planned change says otherwise.
- Update related docs when the change affects standing project understanding.

## 5. Operational Notes
- Prompt files in `core/app/agents/calls/prompts/` are source assets.
- Long-term prompt metadata should also be persisted in the `prompts` table.
- Task prompts are for step-specific intent, not for re-documenting the entire prompt contract.
- If a stable prompt rule changes, update the source prompt asset first and then sync the relevant project docs if needed.

## 6. Manual Reporting Pilot Prompt Boundary

For `Manual Reporting Pilot`, prompt changes must stay explicitly bounded:
- do not treat report-composer prompts as analyzer-contract prompts by default;
- keep daily/weekly reporting synthesis prompts separate from the approved core call-analysis contract;
- preserve reuse-first behavior: changing a reporting prompt must not imply a full pipeline rerun unless that reporting step actually depends on the changed prompt output;
- model experiments for reporting should target only the model-dependent reporting step when possible;
- prompt assets for `manager_daily` and `rop_weekly` should be organized around `report_preset + period + filters`, not around implicit scheduler assumptions.

## 7. LLM2 Report Evidence Prompt Policy

Starting with Step 8AA, the LLM2 deep call-analysis prompt owns an additive `report_evidence_version="v1"` / `report_evidence` package.

Standing rules:
- `report_evidence` is additive and must not remove or rename existing MVP-1 call-analysis fields.
- The analyzer prompt must keep `REPORT_EVIDENCE_CONTRACT.md` as the source of truth for `report_evidence` field shape, enums, grounding, speaker, and validation rules.
- Starting with instruction version `edo_sales_mvp1_call_analysis_v15_block_ready`, fresh business-meaningful LLM2 analyses should produce `report_evidence.semantic_case` as the primary coherent per-call meaning source for report usage and optional `report_evidence.block_candidates` as block-ready material.
- `semantic_case` must explain what happened, the customer signal, manager behavior, coaching diagnosis, why the call matters, and the recommended next action. It is not a final rendered report block.
- Fresh usable `semantic_case` output should include `report_block_fit` for `situation_day`, `call_breakdown`, `voice_of_customer`, `additional_situations`, and `call_tomorrow`.
- `report_block_fit` is a machine-readable suitability signal. LLM2 marks where one call can be used; the deterministic Report Layer still selects the best calls across the day.
- Fresh block-fit items should include `block_role`, `title_mode`, `problem_fit`, `evidence_target`, `gap_proven`, and optional `coaching_moment`, so problem blocks can be separated from customer-signal and follow-up blocks.
- Fresh v15 block candidates should evaluate `situation_day`, `call_breakdown`, `voice_of_customer`, `money_on_table`, `tomorrow_follow_up`, `tomorrow_challenge`, and `call_list_context`. For each suitable block, LLM2 must provide enough material for the Report Layer to render without inventing meaning: fit score, role, title mode, thesis or signal, what happened, why it matters, proof type, proof explanation, quote role, counter-evidence, and a concrete next/report action.
- Every fresh `fit=true` block candidate must include an explicit canonical `stage_code`; the analyzer repair retry and Report Layer validation reject usable block-ready material when the stage is missing or unknown.
- `situation_day` candidates require a teachable problem or explicitly positive practice, `call_breakdown` candidates require one to three deeper moments, `voice_of_customer` candidates require a real customer signal, `money_on_table` candidates require a concrete commercial bridge, `tomorrow_follow_up` candidates require client-specific next action and opening phrase, `tomorrow_challenge` candidates require a skill-standard signal, and `call_list_context` candidates require short non-generic topic/context/action text.
- `coaching_moment` carries the meaning of the report block: summary, optional missing action, optional why-it-matters, optional supporting quote, evidence type, and confidence. Its `evidence_type` must be only `direct_quote`, `absence_in_context`, or `inferred_from_dialogue`; never `none` or `insufficient`.
- `coaching_moment.evidence_type=direct_quote` requires `supporting_quote` to be a non-empty exact transcript substring. If no exact quote can be copied, use `supporting_quote=null` with absence/inferred evidence, or `coaching_moment=null` for an irrelevant `fit=false` block. Absence-based moments should be worded as `в доступной записи/фрагменте не зафиксировано...`.
- For problem-oriented `СИТУАЦИЯ ДНЯ` and `РАЗБОР ЗВОНКА`, `coaching_moment` must also explain the proof: `gap_claim`, `proof_type`, `proof_explanation`, `quote_role`, and `counter_evidence`.
- A quote is not proof just because it mentions the same topic. If the quote shows the manager asked the missing role/convenience/next-step/process question, it is counter-evidence and the problem block must not be marked `fit=true`.
- Proof type rules are strict: `direct_gap` means the quote directly proves the manager gap; `sequence_inference` means event order proves it; `absence_in_context` means the available record lacks the expected action; `context_support` means the quote is only context and is not enough for a `fit=true` manager-gap problem block.
- A manager product-offer quote is usually not `direct_gap` for a missing-qualification claim. If the problem is "offered product before qualifying", use `sequence_inference` or `absence_in_context`; the product-offer quote should normally be `quote_role=supports_context`.
- For `СИТУАЦИЯ ДНЯ`, the prompt must require a problem title, manager gap or missed opportunity, `block_role=coaching_problem`, and `gap_proven=true`. Pure customer signals without manager gap should be `situation_day.fit=false` with `reason_code=customer_signal_without_manager_gap`.
- For `ГОЛОС КЛИЕНТА` and `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, the prompt must not invent a manager problem when the block only needs a customer signal or next action.
- `semantic_case` is preferred downstream only after validation; deterministic reporting remains final authority for report scope, final outcome, call inclusion/exclusion, hotness priority, and rendering.
- Direct quotes and dialogue fragments must be transcript-grounded. If grounding is not available and the moment is not a careful absence/inferred `coaching_moment`, the prompt must require `evidence_quality=insufficient` and `usable_in_report=false`.
- `business_outcome.evidence_quote` must be an exact transcript substring or `null`; prompt examples are never reusable evidence unless the exact phrase appears in transcript.
- `report_evidence.business_outcome.status` must use only the contract enum values: `agreement`, `rescheduled`, `refusal`, `open`, `tech_service`, `not_suitable`.
- Starting with Step 8AH-5 and SFB-5, fresh LLM2 analyses must also fill optional `report_evidence.call_report_summary` when enough transcript/non-name metadata exists. It should provide `short_topic`, `short_context`, optional richer `manager_visible_summary`, explicit `client_display_name` only when the name is spoken in STT transcript/segments and safe, semantic `hotness=hot|warm|low`, `hotness_reason`, `manager_next_action`, and `suggested_manager_phrase`.
- `manager_visible_summary` may be up to 640 chars and is meant for compact manager-facing call-list context when `short_context` would flatten meaning. It must stay factual, grounded, Russian, and must not become a full call breakdown.
- `call_report_summary.hotness` is only a semantic signal; deterministic reporting remains final authority for final outcome, call-list inclusion/exclusion, and manager-facing hotness priority.
- `suggested_manager_phrase` must be written from the manager's voice and must not copy a client quote. If no follow-up exists, it should be `null`; for refusal/tech/not_suitable it is usually `null` unless there is an explicit service follow-up.
- For sales-like outcomes (`agreement`, `rescheduled`, `open`), the prompt and retry instruction must require at least one `manager_coaching_moment`, and at least one of `situation_candidates` / `manager_coaching_moments` must be non-empty. Thin evidence should become explicit `insufficient` / `usable_in_report=false`, not silent empty arrays.
- Speaker roles must stay `unknown` when transcript/segments do not make the role reliable.
- `report_evidence.business_outcome` is only a semantic signal. Final manager-facing outcome remains owned by deterministic reporting-layer resolver rules.
- Prompt changes that alter `report_evidence` expectations must remain traceable through `instruction_version`.

## 8. LLM3 Narrative Composer Prompt Policy

Starting with SFB-1..SFB-5, selected `manager_daily` blocks may use LLM3
composer prompts after deterministic selection/evidence preparation.

Standing rules:
- LLM3 composers are report writers for bounded selected material, not new call
  analyzers.
- LLM3 must not add/remove selected calls or contacts, change final
  status/outcome, change report-day scope, invent facts, deadlines, meetings,
  products, amounts, client names, or quotes.
- Use narrative freedom for meaning, not for facts. Prompts should constrain the
  composer by intent and evidence, not by rigid report micro-fields that flatten
  the story.
- `Ситуация дня` should be one coherent narrative `Что произошло` block with
  grounded support. Structured action/example material can live below it; do not
  create repeated visible subblocks that duplicate the same meaning.
- `Разбор звонка` should explain the selected call's story and concrete turning
  points. It must not duplicate `Ситуацию дня` with extra summary blocks.
- `Голос клиента` should explain what the client really means and how to work
  with that signal. It is not a manager-gap diagnosis block.
- `Кого взять в работу завтра` wording composers may rewrite only visible
  reason/action/example phrase for already accepted deterministic contacts.
- Dialogue in prompt output must be line-separated and speaker-labelled.
  Reliable roles may use `Менеджер` / `Клиент`; uncertain roles must use
  `Сторона 1` / `Сторона 2`.
- Composer output should be manager-facing Russian. Non-Russian or
  contract-breaking output must fail closed to fallback.
