# LLM2 Manager Daily Instructions Map

## Executive summary

Audit date: 2026-05-10
Roadmap: 6.5 Business-ready Report Pack
Scope: Step 8AH / pre-8AH-9 inventory before the next `manager_daily` run

This document maps the effective LLM2 instruction set and downstream report usage for
`manager_daily`. It is an inventory only: no prompt, code, validator, renderer, delivery, STT,
source discovery, `build_missing`, LLM run, or report rebuild behavior was changed in this step.

Key findings:

- There is one runtime LLM2 prompt for per-call analysis: `core/app/agents/calls/prompts/analyze.md`.
- There are no separate LLM2 prompts for `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, or the call list. Those blocks consume fields produced by the per-call LLM2 analysis plus deterministic reporting rules.
- The effective LLM2 instruction is the `analyze.md` system prompt plus a dynamic user JSON object from `CallsAnalyzer.build_prompt_context(...)`.
- LLM2 output is persisted in `Analysis.scores_detail`; `report_evidence` is additive inside that JSON.
- Normal `manager_daily` selection uses stable analysis selection from Step 8-STABLE: newest reusable stable/production analysis, excluding controlled sample / verification analyses by default.
- Valid `report_evidence v1` is preferred for report-ready evidence, but the reporting layer falls back to deterministic / legacy Step 8W paths when the package is missing or invalid.
- `call_report_summary` is used only through a valid `report_evidence` package and guarded by report-layer generic-topic, phrase-safety, and final-authority rules.
- Final outcome totals, inclusion/exclusion, call-list date boundaries, and tomorrow priority are reporting-layer responsibilities; LLM2 signals do not override them.
- Since Step 8AH-11A, coaching-block `data_scope` is also a reporting-layer responsibility. LLM2 does not emit it; the renderer uses deterministic scope metadata so expanded/rolling coaching evidence is labeled explicitly and not shown as plain report-day content.
- Since Step 8AH-11B, `daily_coaching_focus` is the deterministic reporting-layer object that aligns stage focus across stage scores, Situation, Call Breakdown, Challenge, and focus recommendations. LLM2 provides candidate evidence, but it does not choose the final cross-block focus independently.
- Since Step 8AH-11C, positive/neutral problem wording from LLM2 or legacy fallback is normalized downstream before rendering. LLM2 may still emit criterion titles/comments such as “не ушёл в презентацию слишком рано”, but `manager_daily` rewrites manager-facing problem text into actionable missing behavior and exposes `problem_wording_diagnostics`.
- Since Step 8AH-11D, `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` candidates are gated downstream. LLM2 may provide `additional_situations`, but reporting renders only candidates with evidence or concrete call context, non-generic stage-specific wording, aligned title/body, and acceptable confidence.

## LLM2 prompt inventory

| Prompt / instruction role | File path | Calling code | When called | Input data | Expected output | Persistence | Manager_daily usage | Risks / gaps |
|---|---|---|---|---|---|---|---|---|
| LLM2 approved per-call analysis / checklist v5.0 style output | `core/app/agents/calls/prompts/analyze.md` | `CallsAnalyzer.analyze_call()` in `core/app/agents/calls/analyzer.py` | When an analysis is built for an interaction; not during ready-only report rendering | System prompt from `analyze.md`; user JSON from `build_prompt_context(...)`; routed through `_request_analysis_content(... layer="llm2", request_kind="approved_contract_generation", temperature=0.2)` | One JSON object in the approved MVP-1 call analysis contract, plus additive `report_evidence_version` and `report_evidence` | `CallOrchestrator.persist_analysis()` stores the normalized result in `Analysis.scores_detail` | All manager_daily blocks consume some part of this persisted JSON, either directly or through deterministic transforms | Single prompt carries both scoring and report-evidence duties; invalid `report_evidence` can be persisted but ignored by report rendering |
| LLM2 strict retry instruction | Generated in `CallsAnalyzer._build_analysis_retry_instruction(...)` | `CallsAnalyzer.analyze_call()` after `_load_and_validate_contract(...)` raises `LLMResponseError` | Only when the first LLM2 response fails strict contract / semantic validation | Previous invalid JSON, validation error text, same approved schema expectations | One corrected JSON object only | Persisted only if retry output validates; failed attempts may be persisted via `persist_failed_analysis(...)` | Same as approved analysis if successful; failed analyses are non-reusable for reporting | Retry adds report-evidence minimum-package instructions for semantic-empty cases, but it is still reactive and cannot fix all weak evidence |
| Dynamic user prompt context | Built in `CallsAnalyzer.build_prompt_context(...)` | Passed as user message to LLM2 | Every LLM2 analysis call | Interaction id/manager/source/duration/transcript/metadata, checklist definition, contract template, approved source markdown, prompt assets, source priority, optional LLM1 first pass | Context only; LLM2 must return the final JSON contract | Not persisted directly except via resulting analysis and AI routing metadata | Determines what facts and schemas LLM2 can use | `prompt_assets.agreements` and `prompt_assets.insights` are injected as context but are not separate runtime LLM2 prompts |
| `REPORT_EVIDENCE_CONTRACT.md` as injected contract | `docs/REPORT_EVIDENCE_CONTRACT.md` | Loaded by `build_prompt_context(...)` under `approved_sources.report_evidence_contract_markdown` | Every LLM2 analysis call when the doc is available | Contract text for additive `report_evidence v1` | Shapes LLM2 report-evidence output | Not persisted separately | Controls future evidence fields for situation, coaching, VOC, follow-up, summaries | Prompt and Pydantic schema must remain aligned; this audit found no code change needed |
| LLM1 first pass as LLM2 context, not LLM2 prompt | `core/app/agents/calls/prompts/classify.md` | `_request_llm1_first_pass(...)`, then injected as `llm1_first_pass` | Before every LLM2 analysis call | Transcript, metadata, lightweight classification context | Preliminary classification/focus JSON | Stored only as part of runtime metadata/LLM2 context; final LLM2 contract is authoritative | May influence LLM2 focus and eligibility | It is upstream context. It should not be counted as a separate manager_daily report prompt |
| Prompt assets injected for reference | `core/app/agents/calls/prompts/agreements.md`, `core/app/agents/calls/prompts/insights.md` | Loaded by `get_prompt_assets()` and placed in `prompt_assets` | Every LLM2 analysis context | Static prompt asset text | Reference only | Not persisted except indirectly | No direct manager_daily renderer dependency | Since `analyze.md` does not explicitly delegate to these assets, stale or ambiguous asset text can still be visible to LLM2 as context |

## Effective instruction text per prompt

### LLM2 approved analysis prompt

Source: `core/app/agents/calls/prompts/analyze.md`.

Effective system instruction:

- Return exactly one JSON object in the approved MVP-1 call analysis contract.
- Use sources of truth in this order:
  1. `MVP1_CODEX_HANDOFF.md`
  2. `MVP1_CHECKLIST_DEFINITION_v1.md`
  3. `MVP1_CALL_ANALYSIS_CONTRACT_v1.md`
  4. `REPORT_EVIDENCE_CONTRACT.md`
  5. `MVP1_CALL_ANALYSIS_EXAMPLE_TIMUR_v1.json`
  6. `MVP1_MANAGER_CARD_FORMAT_v1.md`
- Non-negotiable rules:
  - Return JSON only.
  - Do not rename fields.
  - Do not add extra top-level fields except approved additive `report_evidence_version` and `report_evidence`.
  - Do not collapse `criteria_results` into generic stage summaries.
  - Preserve criterion-level evidence and comments.
  - Keep optional fields schema-safe with empty arrays or nulls when needed.
  - Do not remove or omit existing required MVP-1 fields when adding `report_evidence`.
  - Never satisfy `report_evidence` by weakening the approved MVP-1 contract.
- Evaluation rules:
  - Checklist definition controls stage applicability, scoring, and critical errors.
  - Contract markdown controls field meaning and shape.
  - `REPORT_EVIDENCE_CONTRACT.md` controls additive `report_evidence v1`.
  - Approved example JSON is a formatting reference, not a copy template.
- Behavioral rules:
  - Be evidence-based.
  - Do not invent transcript facts.
  - Do not mark stages applicable if transcript does not support them.
  - Keep recommendations actionable and concrete.
  - Extract agreements only when there is a real commitment in the call.
  - Eligible sales-relevant calls must not return coaching-empty analyses.
  - If supported, return meaningful `gaps`, `strengths`, `recommendations`, and `evidence_fragments`.
  - Support-only, internal, technical/operational non-sales, too poor-quality, or otherwise non-coachable calls must be marked `not_eligible` with empty detailed coaching arrays.
  - Every criterion result must include `criterion_code`, `criterion_name`, `score`, `max_score`, `comment`, and `evidence`; current criterion `max_score` is `2`.

Additive `report_evidence v1` instruction:

```json
{
  "report_evidence_version": "v1",
  "report_evidence": {
    "business_outcome": null,
    "call_report_summary": null,
    "situation_candidates": [],
    "manager_coaching_moments": [],
    "voice_of_customer": [],
    "additional_situations": [],
    "follow_up_candidates": [],
    "quote_bank": []
  }
}
```

Grounding and quote rules:

- Use only transcript and provided segments/metadata.
- Every quote and every `dialogue_fragment[].text` must be copied verbatim from the transcript.
- `business_outcome.evidence_quote` must be an exact transcript substring or `null`.
- Do not paraphrase quotes; interpretation belongs in fields such as `meaning`, `what_happened`, `what_it_means`, `what_was_missing`, or `what_better`.
- Do not invent quotes, client phrases, manager phrases, timestamps, names, or facts.
- If no exact transcript quote/fragment is safely available, use `evidence_quality=insufficient`, empty `dialogue_fragment`, and `usable_in_report=false`.
- Do not copy example quotes from the prompt unless the exact same phrase appears in the transcript.

Speaker rules:

- Allowed speakers: `manager`, `client`, `unknown`.
- Use `manager` or `client` only when role attribution is reliable.
- If unclear, use `unknown`.
- Never manufacture manager/client dialogue from unlabeled text.

Shared enums:

- `priority`: `high | medium | low`
- `evidence_quality`: `direct | indirect | weak | insufficient`
- `speaker`: `manager | client | unknown`
- `business_signal`: `high | medium | low`
- `call_report_summary.client_name_confidence`: `high | medium | low`
- `call_report_summary.hotness`: `hot | warm | low`
- `business_outcome.status`: `agreement | rescheduled | refusal | open | tech_service | not_suitable`
- `stage_code`: checklist stage code from `contact_start`, `qualification_primary`, `needs_discovery`, `presentation`, `objection_handling`, `completion_next_step`, `sale_processing`, `sale_final`, `cross_stage_transition`

Strict `business_outcome.status` rules:

- Allowed only: `agreement`, `rescheduled`, `refusal`, `open`, `tech_service`, `not_suitable`.
- Forbidden inside `report_evidence.business_outcome.status`: `postponed`, `delayed`, `declined`, `rejected`, `service`, `support`, `interested`, `not_interested`.
- Mapping guidance:
  - postponed/delayed/call later/return later -> `rescheduled`
  - declined/rejected/not interested/no need/not relevant -> `refusal`
  - support/service/technical help/signing help/QR/NCALayer -> `tech_service`
  - interested but no firm commercial step -> `open`
- `business_outcome` is a semantic signal only. Reporting-layer `BusinessOutcomeResolver` is final authority.

### `call_report_summary` instruction

LLM2 is instructed to return a compact report summary for every call when enough transcript or metadata exists, and `null` only when the transcript is too thin.

Expected shape:

```json
{
  "short_topic": "...",
  "short_context": "...",
  "client_display_name": null,
  "client_name_confidence": null,
  "hotness": "hot|warm|low",
  "hotness_reason": "...",
  "manager_next_action": "...",
  "suggested_manager_phrase": null
}
```

Field instructions:

- `short_topic`: short essence, max 120 chars; avoid generic labels such as `Продажи`, `Холодный звонок`, `Разговор с клиентом`.
- `short_context`: short context, max 280 chars.
- `client_display_name`: only explicit name/FIO/name fragment from transcript or metadata; do not invent; do not use company/generic words; if uncertain use `null`; do not include phone/date/time.
- `client_name_confidence`: `high|medium|low` only when name is not null; otherwise null.
- `hotness`: semantic signal only: `hot|warm|low`; never `rescheduled`, `open`, `agreed`, or `cold`.
- `hotness_reason`: explain the semantic hotness.
- `manager_next_action`: concrete manager action.
- `suggested_manager_phrase`: manager-voiced phrase; do not copy client quote; do not start with client words; null if no follow-up; usually null for `refusal`, `tech_service`, `not_suitable` unless explicit service follow-up.
- Reporting remains final authority for final outcome, call-list inclusion/exclusion, phone/date/time display, and manager-facing hotness priority.

### Report block evidence sections inside LLM2 prompt

`situation_candidates`:

- Purpose: candidate material for `СИТУАЦИЯ ДНЯ`.
- Fields: `stage_code`, `problem_type`, `situation_title`, `priority`, `evidence_quality`, `dialogue_fragment`, `what_happened`, `what_it_means`, `what_was_missing`, `next_time_action`, `scripts`, `usable_in_report`.
- `what_happened` and `what_was_missing` must not be identical.
- For sales-like calls and final semantic `agreement|rescheduled|open`, return at least one candidate when there is a missed stage, gap, weak next step, or usable manager behavior.
- If there is no safe exact fragment, return an insufficient/unusable candidate rather than silently leaving evidence empty.

`manager_coaching_moments`:

- Purpose: candidate material for `РАЗБОР ЗВОНКА`.
- Fields: `stage_code`, `moment_type=worked|missed|risk`, `priority`, `evidence_quality`, `dialogue_fragment`, `what_happened`, `what_better`, `usable_in_report`.
- For sales-like final `agreement|rescheduled|open`, LLM2 must provide at least one moment when transcript content exists.
- Weak or missing evidence must be explicit with `weak` or `insufficient`; no ordinary sales coaching moments for final `tech_service`, `refusal`, or `not_suitable` unless specifically grounded.

`voice_of_customer`:

- Purpose: client quotes for `ГОЛОС КЛИЕНТА`.
- Topics: `need`, `objection`, `risk`, `price`, `process`, `timing`, `product_interest`, `service_issue`, `refusal`.
- Fields: `quote`, `speaker`, `topic`, `meaning`, `business_signal`, `stage_code`, `usable_in_report`.
- Prefer `speaker=client`; use `unknown` when useful but role attribution is not reliable.
- `service_issue` still uses canonical checklist `stage_code`, never `support`, `service`, or `tech_service`.

`additional_situations`:

- Purpose: extra report-ready situations.
- Types: `strength`, `growth_zone`, `risk`, `missed_opportunity`, `service_issue`, `customer_signal`.
- Fields: `title`, `priority`, `evidence_quality`, `what_happened`, `why_it_matters`, `recommended_action`, `stage_code`, `usable_in_report`.

`follow_up_candidates`:

- Purpose: semantic follow-up candidate for `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`.
- Fields: `status=agreement|rescheduled|open`, `client_label`, `next_step`, `deadline`, `priority=hot|rescheduled|open`, `first_phrase`, `why_follow_up`, `usable_in_report`.
- Do not return follow-up candidates for `refusal`, `tech_service`, or `not_suitable`.
- Note: this legacy follow-up priority enum is not the same as Step 8AH-3 deterministic manager-facing priority labels.

`quote_bank`:

- Purpose: reusable grounded quotes.
- Fields: `quote`, `speaker`, `topic`, `stage_code`, `evidence_quality`, `usable_in_report`.

Language and wording:

- Preserve direct evidence quotes in original source language.
- Business-facing explanation fields must be in Russian.
- System values, codes, enums, ids, JSON keys, and technical identifiers remain unchanged.
- Manager card may inform compact wording but does not override JSON contract.

### LLM2 retry instruction

Source: generated by `CallsAnalyzer._build_analysis_retry_instruction(...)`.

Base retry instruction:

```text
The JSON above failed strict approved-contract validation with this error:
{error}

Return one corrected JSON object only. Preserve the approved schema, include all required stage and criterion fields, and do not add explanations.
```

For semantic-empty eligible analyses, the retry additionally instructs:

- If transcript is sales-relevant and eligible, do not return an empty coaching shell.
- Include applicable `score_by_stage` with criterion-level evidence plus at least one `strengths`, `gaps`, `recommendations`, and usable `evidence_fragments` when supported.
- If truly support-only/internal/non-coachable, set `classification.analysis_eligibility=not_eligible` with clear `eligibility_reason`.
- Preserve `report_evidence_version="v1"` and `report_evidence`.
- When enough transcript or metadata exists, include `report_evidence.call_report_summary` with `short_topic`, `short_context`, `hotness` limited to `hot|warm|low`, `manager_next_action`, and a manager-voiced `suggested_manager_phrase` that does not copy client quotes.
- For semantic `agreement|rescheduled|open`, `manager_coaching_moments` must contain at least one item and at least one of `situation_candidates` or `manager_coaching_moments` must be non-empty.
- If transcript is too thin, return explicit insufficient/unusable evidence instead of empty arrays.
- Do not return `follow_up_candidates` for `refusal`, `tech_service`, or `not_suitable`.

## Dynamic placeholders and injected variables

LLM2 receives the system prompt plus one user message containing JSON from `build_prompt_context(...)`:

| User-context key | Source | Notes |
|---|---|---|
| `interaction.id` | `Interaction.id` | Persisted interaction id |
| `interaction.department_id` | `Interaction.department_id` | Used for tenant/report context |
| `interaction.manager_id` | `Interaction.manager_id` | Manager identity; manager name may also be metadata |
| `interaction.source` | `Interaction.source` | Usually telephony/source system |
| `interaction.duration_sec` | `Interaction.duration_sec` | Supports eligibility and context |
| `interaction.text` | Persisted transcript | Primary evidence source for quotes/fragments |
| `interaction.metadata` | `Interaction.metadata_` | Contains call date/phone/contact metadata when available |
| `checklist_definition` | Embedded approved checklist | Stage/criterion source of truth |
| `analysis_result_contract_template` | `build_contract_template(...)` | Schema-safe default result with required top-level fields |
| `approved_sources.handoff` | MVP-1 source doc or runtime fallback | Business/product rules |
| `approved_sources.checklist_definition_markdown` | MVP-1 checklist markdown or embedded JSON | Stage applicability/scoring |
| `approved_sources.contract_markdown` | MVP-1 contract markdown or template JSON | Field shape/meaning |
| `approved_sources.report_evidence_contract_markdown` | `docs/REPORT_EVIDENCE_CONTRACT.md` | Additive report evidence contract |
| `approved_sources.manager_card_markdown` | MVP-1 manager card source | Human-report wording reference |
| `approved_sources.approved_example_contract` | Approved example JSON | Formatting/filling reference only |
| `prompt_assets.classify` | `prompts/classify.md` | LLM1 prompt text injected as reference |
| `prompt_assets.analyze` | `prompts/analyze.md` | Current system prompt also duplicated in context |
| `prompt_assets.agreements` | `prompts/agreements.md` | Reference asset, not separate runtime LLM2 call |
| `prompt_assets.insights` | `prompts/insights.md` | Reference asset, not separate runtime LLM2 call |
| `source_of_truth_priority` | Static list | Mirrors prompt source priority |
| `llm1_first_pass` | `_request_llm1_first_pass(...)` | Optional preliminary classification/focus context |

## JSON output contracts

### MVP-1 analysis contract

Required top-level fields after normalization:

| Field | Required | Validator / normalizer | Manager_daily usage |
|---|---:|---|---|
| `schema_version` | yes | Forced to approved `call_analysis.v1` | Diagnostics/versioning |
| `instruction_version` | yes | Forced to current approved instruction version | Stable analysis selection and diagnostics |
| `checklist_version` | yes | Forced to approved checklist version | Diagnostics |
| `analysis_timestamp` | yes | Template default | Diagnostics |
| `call` | yes | Merged with template | Client/call reference metadata, call date/time |
| `classification` | yes | Eligibility guardrails | Meaningfulness, call type, resolver context |
| `summary` | yes | Merged with template | Outcome clues, call goal/topic fallback |
| `score` | yes | Checklist score populated | Overall score, reusable-analysis check |
| `score_by_stage` | yes | Stage and criterion fields checked | Stage scores, focus stage, challenge, coaching |
| `strengths` | yes | Normalized items | Worked cards, fallback additional situations |
| `gaps` | yes | Normalized items | Key problem, call breakdown fallback, focus |
| `recommendations` | yes | Normalized items | Recommendation cards, call breakdown fallback |
| `agreements` | yes | Normalized empty/list | Derived agreement persistence |
| `follow_up` | yes | Dict shape required | Resolver context, tomorrow block |
| `product_signals` | yes | Normalized empty/list | VOC fallback and business context |
| `evidence_fragments` | yes | Normalized empty/list | Situation/VOC/call breakdown fallback |
| `analytics_tags` | yes | Normalized empty/list | Analysis metadata |
| `data_quality` | yes | Merged with template | Completeness and manual-review diagnostics |

The analyzer rejects unknown stage codes, missing required stage fields, invalid stage names, non-list `criteria_results`, unknown criterion codes, missing criterion fields, and semantic-empty eligible analyses.

### `report_evidence v1` contract

Pydantic models live in `core/app/agents/calls/report_evidence.py`.

| Object | Required fields | Optional/default fields | Main consumers |
|---|---|---|---|
| `business_outcome` | `status`, `confidence`, `reason` | `evidence_quote`, `evidence_speaker`, `needs_human_review` | Diagnostics/semantic evidence; final resolver remains authority |
| `call_report_summary` | none individually; object optional | `short_topic`, `short_context`, `client_display_name`, `client_name_confidence`, `hotness`, `hotness_reason`, `manager_next_action`, `suggested_manager_phrase` | Call list, tomorrow, VOC, diagnostics |
| `situation_candidates[]` | `stage_code`, `problem_type`, `situation_title`, `priority`, `evidence_quality`, `what_happened`, `what_it_means`, `what_was_missing`, `next_time_action` | `dialogue_fragment`, `scripts`, `usable_in_report` | `СИТУАЦИЯ ДНЯ` |
| `manager_coaching_moments[]` | `stage_code`, `moment_type`, `priority`, `evidence_quality`, `what_happened`, `what_better` | `dialogue_fragment`, `usable_in_report` | `РАЗБОР ЗВОНКА` |
| `voice_of_customer[]` | `quote`, `speaker`, `topic`, `meaning`, `business_signal`, `stage_code` | `usable_in_report` | `ГОЛОС КЛИЕНТА`, Situation Day client-grounding |
| `additional_situations[]` | `type`, `title`, `priority`, `evidence_quality`, `what_happened`, `why_it_matters`, `recommended_action`, `stage_code` | `usable_in_report` | `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` |
| `follow_up_candidates[]` | `status`, `client_label`, `next_step`, `priority`, `first_phrase`, `why_follow_up` | `deadline`, `usable_in_report` | `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` as fallback/enrichment only |
| `quote_bank[]` | `quote`, `speaker`, `topic`, `stage_code`, `evidence_quality` | `usable_in_report` | Situation Day client-grounding and future quote fallback |

## Validators and fallback behavior

| Layer | File / function | What is validated | Invalid behavior | Downstream fallback |
|---|---|---|---|---|
| LLM2 JSON parse | `CallsAnalyzer._load_and_validate_contract(...)` | JSON object parse | Raises `LLMResponseError`; may trigger retry | No persisted successful analysis unless corrected |
| MVP-1 contract shape | `CallsAnalyzer._validate_and_normalize_contract(...)` | Required top-level fields, stage/criterion codes, required fields, score shape, semantic completeness | Raises `LLMResponseError` or semantic error; can persist failed analysis for forensics | Failed/non-reusable analyses are skipped by stable report selection |
| Retry instruction | `CallsAnalyzer._build_analysis_retry_instruction(...)` | Not a validator; corrective instruction | If retry fails, analysis remains failed/non-reusable | Older reusable stable analysis may be selected |
| Persistence | `CallOrchestrator.persist_analysis(...)` | Stores normalized contract; can mark `analysis_purpose` | Controlled samples can be marked without DB migration | Normal manager_daily excludes controlled/verification rows |
| Stable selection | `_select_stable_analysis_for_reporting(...)` / `_is_analysis_reusable_for_reporting(...)` | Newest reusable stable row, required analysis keys, score, follow_up shape, non-empty useful analysis | Latest invalid/non-reusable row does not hide older reusable stable row | If no reusable row exists, newest allowed row is returned for rejection diagnostics |
| `report_evidence` schema | `validate_report_evidence(...)` | Version, Pydantic shape, enums, max lengths, extra fields forbidden | Returns `is_valid=false`; analysis itself can still be reusable | Report blocks ignore invalid package and use deterministic/legacy fallback |
| `report_evidence` grounding | `_validate_package_semantics(...)` and helpers | Stage codes, grounded quotes/fragments, insufficient evidence semantics | Errors for ungrounded report-ready text; warnings for weak/duplicated fields | Invalid whole package is not used by reporting |
| `call_report_summary` safety | `_validate_call_report_summary(...)` and reporting guards | Max lengths, enum values, no copied client quote, warnings for phrases on non-follow-up outcomes | Validator error/warning; reporting also rejects generic/unsafe values | Call list/tomorrow/VOC use deterministic fallback |
| Client display name safety | `_safe_client_display_name(...)` and `_build_client_call_reference(...)` | Unsafe words, phone-like labels, too short/noisy/generic names | Unsafe label omitted | Reference falls back to phone + date/time |
| Suggested phrase safety | `_safe_manager_phrase_from_summary(...)` | Copied quote, phone/date/time, client-style opening | Phrase not rendered | Deterministic safe phrase or no phrase |

Important fallback rules:

- Missing `report_evidence` with no version is valid legacy state.
- `report_evidence_version` without `report_evidence` gives a warning, not a blocking error.
- Invalid `report_evidence` does not invalidate the whole analysis for scoring/reuse; it only prevents report-evidence consumption.
- Valid `call_report_summary` is consumed only when the containing `report_evidence` package validates.
- The whole package validity gate means one invalid enum or ungrounded quote can suppress otherwise useful `call_report_summary` fields.

## PDF block usage map

| PDF block | LLM2 outputs used | Rule-based fields used | Fallback fields / paths | Current human-review risks |
|---|---|---|---|---|
| `ИТОГ ДНЯ` | Indirectly uses persisted analysis fields through final resolver | Report-day `meaningful_calls`, `BusinessOutcomeResolver`, deterministic category counters | Technical/unclassified buckets when no reusable analysis | Outcome drift if future controlled samples are not marked; mitigated for future by Step 8-STABLE |
| `ДЕНЬГИ НА СТОЛЕ` | Outcome/follow-up/money clues from analysis as interpreted by deterministic reporting | Report-day only, final outcome categories and money rules | Empty/zero when no qualifying outcome | LLM wording cannot override money rules; verify totals after next run |
| `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ` | `call_report_summary.short_topic` -> `Тип / суть`; `short_context` -> `Контекст`, only if valid and non-generic | Unified client reference, report-day boundary, final status order, call time | Summary/generic fallback from call type/outcome/context; `—` for empty context | Technical fallback context can remain weak; broad summary topics are guarded but may fall back to less useful text |
| `БАЛЛЫ ПО ЭТАПАМ` | `score_by_stage[].score/max_score/criteria_results` | Stage aggregation and display thresholds; `daily_coaching_focus.stage_code` is derived from the priority stage; problem wording normalizer rewrites positive/neutral problem summaries | Empty/low-information stage handling | Stage scores can be valid while evidence is weak; `daily_coaching_focus_validation` / `problem_wording_diagnostics` should flag downstream mismatches or rewrites |
| `СИТУАЦИЯ ДНЯ` | Preferred `report_evidence.situation_candidates`; client-grounding can use `voice_of_customer` / `quote_bank` from same valid package | `daily_coaching_focus.stage_code`, sales-like final statuses, client-reaction classifier, evidence ranking, dialogue formatting, selected-call `data_scope`, problem wording normalizer | Step 8W legacy evidence fragments, call breakdown excerpt, transcript/dialogue fallback, explicit insufficient-evidence text | Must not silently use another stage; if selected from expanded base, renderer must keep explicit scope label/note; positive wording must be normalized before render |
| `РАЗБОР ЗВОНКА` | Preferred `report_evidence.manager_coaching_moments` | `daily_coaching_focus.stage_code`, evidence-strength ranking, low-information fragment guard, final sales-like filters, selected-call `data_scope`, problem wording normalizer | Legacy gaps/recommendations/evidence fragments/transcript sentence fallback; explicit missing/insufficient-evidence note | Weak evidence is labeled; stage mismatch must not be hidden as main focus; `Что было` must describe a gap, not a positive criterion |
| `ГОЛОС КЛИЕНТА` | Preferred `report_evidence.voice_of_customer`; optional `call_report_summary.manager_next_action` when specific/aligned | Signal-specific deterministic action mapping, quote preservation, source ranking | `evidence_fragments.client_text`, `product_signals.quote`, generic fallback only when no clear signal | If valid report_evidence is missing/invalid, VOC can become sparse; manager action can still be generic for unclear quotes |
| `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` | Preferred `report_evidence.additional_situations` | Dedup against top situation, priority/quality filter, aggregate coaching `data_scope`, gap title/body problem wording normalizer, Step 8AH-11D quality gate | Secondary gaps/strengths only if evidence/context-backed; otherwise hidden empty section | Empty section is hidden after Step 8AH-9; if rendered from expanded/rolling data, scope note must remain visible; cards must not be generic, contextless, duplicated, or title/body contradictory |
| `ЧЕЛЛЕНДЖ` | Indirectly uses `score_by_stage`, gaps/recommendations/key problem | `daily_coaching_focus.stage_code`, deterministic challenge from focus stage/key problem, aggregate coaching `data_scope` | Generic stage challenge fallback | Rolling/expanded counts must not say `Сегодня`; challenge stage must match `daily_coaching_focus` |
| `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` | `call_report_summary.short_context`, `hotness_reason`, `manager_next_action`, safe `suggested_manager_phrase`; `follow_up_candidates` as bounded enrichment | Final status inclusion (`agreed/rescheduled/open` only), deterministic hotness, signal profile, deadline/time sorting | Deterministic profile text, legacy `follow_up`, final call list row context | `call_report_summary.hotness` does not override priority; good. But generic LLM manager actions may be rejected and fallback must stay useful |
| Unified client/call references | LLM2 `call.contact_name/contact_phone` template fields if present; `call_report_summary.client_display_name` is documented but not currently a primary runtime display source | Interaction metadata, safe persisted transcript name fallback, safe-name guard, date/time formatting | Phone + date/time; date/time only if phone absent | Summary names are not currently consumed by `_artifact_call_metadata`; future wiring must respect `client_name_confidence` and safe-name rules |

## Current report-block source notes

### Report-day vs rolling-window semantics

Report-day only:

- `ИТОГ ДНЯ`
- `ДЕНЬГИ НА СТОЛЕ`
- `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ`

Rolling/coaching context allowed:

- `БАЛЛЫ ПО ЭТАПАМ`
- `СИТУАЦИЯ ДНЯ`
- `РАЗБОР ЗВОНКА`
- `ГОЛОС КЛИЕНТА`
- `ЧЕЛЛЕНДЖ`

Since Step 8AH-11A, coaching blocks expose deterministic `data_scope`:

- `report_day` — selected call/metric is report-day only; `Ситуация дня` / `Сегодня` wording is allowed.
- `expanded_coaching_base` — selected coaching call is outside the report-day call list but inside the expanded coaching base; renderer must label it as expanded-base evidence.
- `rolling_window` — metric/pattern is aggregated from the rolling-window coaching base; renderer must use `За последние N рабочих дней` / rolling-window wording and must not say `Сегодня`.

Normal safety expectation: rolling-window calls must not enter the call list. After the next report-day run, verify `call_list_dates`, explicit rolling-window absence in the call list, and scope-aware labels/notes in coaching blocks.

### Focus stage alignment

Current sources can diverge:

- `daily_coaching_focus` is derived from `score_by_stage` and problem text by the reporting layer.
- Situation Day filters valid `report_evidence.situation_candidates` to `daily_coaching_focus.stage_code`, then uses client-grounding / legacy fallback only for the same focus stage.
- Call Breakdown filters valid `manager_coaching_moments` to `daily_coaching_focus.stage_code`, then uses focus-stage legacy fallback or explicit insufficient-evidence text.
- Challenge is deterministic from `daily_coaching_focus`.

If a block cannot find evidence for the focus stage, it must say so explicitly. It must not silently replace the main focus with another stage.

### Problem wording normalization

Since Step 8AH-11C, `manager_daily` treats LLM2 wording as candidate wording, not final manager-facing problem phrasing. The reporting layer normalizes problem statements in:

- `score_by_stage` priority problem summaries;
- `daily_coaching_focus.problem_statement`;
- Situation Day / Call Breakdown problem text;
- `report_evidence.additional_situations` and legacy additional-situation gap title/body text;
- DOCX fallback stage/additional-situation render data.

Examples of downstream rewrites:

| LLM2 / fallback wording | Manager-facing normalized problem |
|---|---|
| `Менеджер не ушел в презентацию слишком рано` | `Квалификация не была завершена до предложения.` |
| `Не ушёл в презентацию слишком рано` | `Квалификация не была завершена до предложения.` |
| `Сохранил нейтральный, вежливый и понятный тон` | `Тон был вежливым, но не помог продвинуть разговор.` |
| `Представился и обозначил компанию` | `Повод звонка был объяснён недостаточно ясно.` |
| `Понятно обозначил причину звонка` | `Причина звонка не была связана с задачей клиента.` |

The payload exposes `problem_wording_diagnostics`; warnings indicate that wording was normalized or still looks unsafe. This does not change LLM2 prompts, `report_evidence`, scoring, final outcomes, call-list semantics, data-scope rules, or the selected daily coaching focus stage.

### Additional Situations quality gate

Since Step 8AH-11D, `report_evidence.additional_situations` and legacy secondary gap/strength candidates are candidate inputs, not guaranteed rendered cards.

The downstream quality gate renders a candidate only when it has:

- `title`;
- `stage_id` / `stage_code` and `problem_signal`;
- `data_scope`;
- evidence or concrete call context (`evidence_quote`, `evidence_call_id`, or call-specific `what_happened`);
- `what_happened`;
- `why_it_matters`;
- `next_action`;
- `why_this_works`;
- `confidence=high|medium` after deterministic confidence assignment.

Filtered reasons are exposed in `additional_situations_quality.filtered_reasons`:

- `missing_evidence`;
- `generic_wording`;
- `title_body_mismatch`;
- `duplicate_signal`;
- `low_confidence`.

When LLM2 or legacy fallback supplies generic wording, the reporting layer may replace it with stage-specific guidance. If it cannot make the card evidence/context-backed and specific, the candidate is excluded. If no candidate passes, the PDF/DOCX/HTML section is hidden.

### Report evidence vs legacy Step 8W fallback

Current policy: valid `report_evidence` is preferred; missing/invalid report evidence falls back to Step 8W-style persisted evidence/transcript/deterministic assembly. This is correct for safety, but it can hide useful summary/evidence fields if one field invalidates the whole package.

## Known gaps before the next report-day run

| Gap / risk | Where | Why it matters | Recommended verification after next run |
|---|---|---|---|
| Whole-package validity gate can suppress useful summary fields | `validate_report_evidence(...)` -> `_build_report_evidence_index(...)` | One invalid enum or ungrounded quote can prevent `short_topic`, `short_context`, and manager action usage | Count valid/invalid `report_evidence`; sample invalid packages and check if failure is localized |
| `call_report_summary.client_display_name` is documented but not currently a primary display-name source | Unified reference path in `reporting.py` | Fresh LLM2 names may not appear even when safe; future wiring could also introduce unsafe names if not gated | Verify whether next-run client labels come from metadata or summary; decide if a bounded wiring task is needed |
| Focus/Situation/Breakdown/Challenge can use different source calls/stages | `daily_coaching_focus_validation` | A report can feel inconsistent even when every block is individually valid | Verify `daily_coaching_focus.stage_code`, Situation stage, Breakdown stage, and Challenge stage match or have explicit insufficient-evidence handling |
| Coaching block data scope can be misread as report-day | `data_scope` assignment/rendering for Situation, Breakdown, Challenge, Additional Situations | A non-report-day example or rolling metric can look like it happened "today" | Verify scope labels/notes: no non-report-day selected call under plain `СИТУАЦИЯ ДНЯ`, no rolling/expanded metric with `Сегодня` wording |
| Positive or neutral text can appear as a problem | Key problem / situation wording fallbacks | Step 8AH-11C normalizes known positive/neutral patterns, but new wording variants can appear | Inspect `problem_wording_diagnostics`, key problem, Situation Day `what_happened`, Additional Situations title/body, and stage challenge language |
| Technical fallback context in call list | Call-list context fallback | If summary context is missing/invalid, technical/unclassified context can stay weak or empty | Verify `Тип / суть` / `Контекст` for technical/service rows and summary usage counts |
| Empty or generic Additional Situations | `additional_situations` report_evidence/fallback and Step 8AH-11D quality gate | The section should not look filled with repeated generic advice or contextless cards | Check `additional_situations_quality`; rendered cards need evidence/context and stage-specific `why_it_matters` / `next_action`; if none pass, section should be hidden |
| Bare `Фрагмент: —` should not return | Call Breakdown rendering | Step 8AH-8F added explicit weak-evidence note; future render path must preserve it | Search PDF text for `Фрагмент: —` and check `call_breakdown_fragment_present` diagnostics |
| Unsafe / weird client names | Safe-name display helper | Bad names are high-visibility PDF defects | Search PDF text for known unsafe labels and review low-confidence names |
| Legacy follow-up candidate priority enum differs from manager-facing hotness | LLM2 `follow_up_candidates.priority` vs Step 8AH-3 priority | LLM2 can emit `open`, but manager-facing labels are deterministic `Горячий/Перенос/Тёплый/Низкий` | Verify tomorrow priority labels and ensure LLM2 priority never overrides deterministic priority |
| Controlled samples can affect reports only if unmarked historical rows remain latest | Stable selection / old DB state | Step 8-STABLE is future-safe, but historical sample rows were not mass-updated | Verify selected `analysis_purpose` and instruction versions in next report summary |
| `report_evidence.business_outcome` is not final authority | Resolver vs semantic signal | Human review can see semantic evidence that differs from final counters if resolver rules differ | Compare resolver status, `business_outcome.status`, and summary/follow_up for mismatches |

## Recommendation: what must be verified after the next run

After the next `manager_daily` report-day run, verify:

1. **No unintended runtime steps**
   - `transcripts_built=0` unless the task explicitly allowed STT.
   - `analyses_built=0` for ready-only runs; if fresh analysis was intended, count and list exact interactions.
   - No source discovery, `build_missing`, delivery, or business email unless explicitly requested.

2. **Analysis selection**
   - Normal report uses stable/production analyses by default.
   - Controlled sample / verification analyses are excluded unless `include_controlled_samples=true`.
   - Latest invalid/non-reusable rows do not hide older reusable stable rows.

3. **Contract validity**
   - Count analyses with `report_evidence_version="v1"`.
   - Count valid vs invalid `report_evidence`.
   - For invalid packages, list validator errors and whether summary fields were suppressed.

4. **Call summary usage**
   - `call_report_summary_available` and `call_report_summary_used` by manager.
   - Call-list `Тип / суть` uses non-generic `short_topic` when valid.
   - Call-list `Контекст` uses useful `short_context` when valid.
   - Broad topics such as `Обсуждение...`, `Разговор...`, `Звонок...`, `Продажи`, `Холодный звонок` are not rendered as final topic.

5. **Block quality**
   - `daily_coaching_focus.stage_code` exists when stage data exists.
   - `СИТУАЦИЯ`, `РАЗБОР ЗВОНКА`, and `ЧЕЛЛЕНДЖ` match `daily_coaching_focus.stage_code` or show explicit insufficient-evidence handling.
   - `СИТУАЦИЯ ДНЯ` client-reaction conclusions include client-grounded evidence when available.
   - Non-report-day coaching examples carry explicit `data_scope` wording and are not rendered as plain `СИТУАЦИЯ ДНЯ`.
   - `РАЗБОР ЗВОНКА` has no bare `Фрагмент: —`; weak/missing evidence is explicit.
   - `ГОЛОС КЛИЕНТА` preserves client quotes and uses signal-specific manager actions.
   - `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` uses deterministic priority, excludes final refusal/tech/not-suitable, and avoids generic or copied phrases.
   - `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` is either populated with quality-gated evidence/context-backed cards or hidden.
   - `additional_situations_quality.filtered_reasons` does not reveal unexpected mass filtering of otherwise useful `report_evidence` candidates.
   - `ЧЕЛЛЕНДЖ` does not say `Сегодня` when the displayed metric comes from an expanded/rolling coaching base.

6. **Boundaries and counters**
   - `call_list_dates` contains only the report day.
   - Rolling-window calls are absent from the call list.
   - Outcome totals match the expected baseline or any explicit re-baseline decision.
   - `manager_facing_completeness.status=passed`.

7. **Display safety**
   - No unsafe / weird client names.
   - Unified references include phone and date/time.
   - Suggested manager phrases do not contain phone/date/time and do not copy client quotes.

## Source files reviewed

- `core/app/agents/calls/prompts/analyze.md`
- `core/app/agents/calls/prompts/classify.md`
- `core/app/agents/calls/prompts/agreements.md`
- `core/app/agents/calls/prompts/insights.md`
- `core/app/agents/calls/analyzer.py`
- `core/app/agents/calls/orchestrator.py`
- `core/app/agents/calls/report_evidence.py`
- `core/app/agents/calls/reporting.py`
- `core/app/agents/calls/report_templates.py`
- `scripts/generate_docx_report.js`
- `docs/CONTEXT_INDEX.md`
- `docs/CODER_WORKING_RULES.md`
- `docs/ROADMAP.md`
- `docs/PROGRESS.md`
- `docs/BUSINESS_READY_REPORT_PACK_TASKS.md`
- `docs/MANAGER_DAILY_SELECTION_MODEL.md`
- `docs/REPORT_EVIDENCE_CONTRACT.md`
- `docs/MANUAL_REPORTING_PILOT.md`
- `docs/DECISIONS.md`
