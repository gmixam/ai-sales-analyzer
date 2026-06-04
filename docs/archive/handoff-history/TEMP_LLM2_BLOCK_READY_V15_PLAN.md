# TEMP — LLM2 Block-Ready Report Evidence v15 Plan

> Status 2026-05-21: superseded as an active plan. Keep this file as historical
> implementation context only. Current source of truth for v15 report-quality
> work is `docs/BUSINESS_READY_REPORT_PACK_TASKS.md`,
> `docs/REPORT_EVIDENCE_CONTRACT.md`, `docs/MANAGER_DAILY_SELECTION_MODEL.md`,
> and `docs/PROGRESS.md`.

**Status:** real-call validation completed  
**Created:** 2026-05-14  
**Target validation date:** 2026-05-08 call set  
**Target manager:** Толеген Жангазиев  
**Tracking purpose:** temporary progress file for the v15 upgrade where LLM2 prepares sufficient, block-ready material for manager daily report blocks.

## 1. Goal

The goal of v15 is to make LLM2 responsible for high-quality, meaningful per-call analysis that is sufficient for the report blocks.

LLM2 must not only produce a generic `semantic_case`, fragments, or candidate text. For every analyzed call, LLM2 must decide which report blocks the call can support and must prepare a complete, grounded candidate for each suitable block.

Target responsibility:

```text
LLM2
-> understands one call deeply
-> creates block-ready candidates with fit score, meaning, proof, and action

Report Layer
-> selects the best candidates across calls
-> validates quality and proof
-> renders the report
```

The Report Layer must not invent the core meaning of a report block from scattered fragments. It may normalize, reject, rank, and format, but the semantic payload must come from LLM2.

## 2. Why This Upgrade Is Needed

v14 improved proof validation and reduced weak cases where a quote contradicted the claimed problem. However, the current mechanism can still leave the Report Layer with incomplete material.

Observed issue:

- LLM2 can identify a broad semantic case, but not always provide enough block-specific material.
- A quote may be rendered as if it proves a gap, while the real proof is sequence-based or absence-based.
- `Ситуация дня` and `Разбор звонка` can become repetitive because both blocks consume the same high-level semantic case.
- Some blocks need a problem-oriented coaching moment, while others need a neutral customer signal or follow-up action.

Therefore, the next upgrade must answer the core question:

> Can this exact call be used in this exact report block, and is the material strong enough to render without Report Layer interpretation?

## 3. Target Blocks

LLM2 must evaluate block readiness for these manager daily blocks:

- `situation_day` — `СИТУАЦИЯ ДНЯ`
- `call_breakdown` — `РАЗБОР ЗВОНКА`
- `voice_of_customer` — `ГОЛОС КЛИЕНТА`
- `money_on_table` — `ДЕНЬГИ НА СТОЛЕ`
- `tomorrow_follow_up` — `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`
- `tomorrow_challenge` — `ЧЕЛЛЕНДЖ НА ЗАВТРА`
- `call_list_context` — enrichment for `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ`

## 4. Block-Ready Candidate Contract

Add an optional block-ready layer inside `report_evidence`.

Preferred shape:

```json
{
  "report_evidence": {
    "block_candidates": {
      "situation_day": {
        "fit": true,
        "score": 86,
        "role": "coaching_problem",
        "title_mode": "problem",
        "main_thesis": "Менеджер перешел к предложению продукта до выяснения задачи клиента.",
        "what_happened": "Менеджер предложил отправить информацию о продукте, но в доступной части звонка не зафиксировал вопросы о роли клиента, текущем процессе и задаче.",
        "why_it_matters": "Без квалификации предложение может оказаться не связанным с реальной задачей клиента.",
        "what_was_missing": "Не было зафиксировано, какую задачу клиент хочет решить и кто принимает решение.",
        "better_next_action": "Сначала уточнить задачу, роль клиента и текущий процесс, затем связать продукт с выявленной потребностью.",
        "proof_type": "sequence_inference",
        "proof_explanation": "Вывод основан на последовательности: сначала менеджер предлагает отправить информацию, а предварительные вопросы о задаче клиента в доступном фрагменте отсутствуют.",
        "supporting_quote": "может, я вам скину информацию о нашем продукте",
        "quote_role": "supports_context",
        "counter_evidence": [],
        "insufficiency_reason": null
      }
    }
  }
}
```

The exact field names may be adjusted during implementation if the existing schema suggests a cleaner local pattern. The principle must remain stable: each candidate must be sufficient for its target block.

## 5. Block-Specific Requirements

### 5.1. `situation_day`

Purpose:

- Pick one strong, teachable situation of the day.
- Usually problem-oriented, but may be a strong-practice case only if no meaningful problem case exists and the block explicitly renders it as positive.

LLM2 must provide:

- specific problem or teachable thesis;
- what happened;
- why it matters;
- what was missing or what worked well;
- better next action;
- proof type and proof explanation;
- block fit score.

Quality rules:

- no generic stage statements;
- no weak quote-only proof if the real proof is absence or sequence;
- no duplicate `what_was_missing` and `better_next_action`;
- must be understandable without Report Layer inventing the meaning.

### 5.2. `call_breakdown`

Purpose:

- Explain one selected call in more detail than `Ситуация дня`.
- Show the manager what exactly happened and how to improve the move.

LLM2 must provide:

- one to three breakdown moments;
- each moment must have situation, essence, proof, and better action;
- if the same call is also used for `situation_day`, the breakdown must go deeper, not repeat the same text.

Quality rules:

- each row must have a clear coaching value;
- no repetition of the Situation Day wording;
- no rendering of a quote as proof when it only supports context.

### 5.3. `voice_of_customer`

Purpose:

- Show a real customer signal.
- This block does not require a manager mistake.

LLM2 must provide:

- customer signal;
- customer need, doubt, objection, motivation, or risk;
- quote or transcript-grounded paraphrase;
- what the manager should do with this signal.

Quality rules:

- must not force a manager gap when the signal is neutral;
- quote should preferably be from the client;
- if no direct quote exists, mark proof as indirect and explain why.

### 5.4. `money_on_table`

Purpose:

- Identify commercial potential that could be converted into revenue, payment, invoice, upsell, cross-sell, or next commercial step.

LLM2 must provide:

- commercial opportunity;
- signal strength;
- what was monetizable;
- what manager did or missed;
- concrete next commercial action.

Quality rules:

- must not invent money potential from generic interest;
- service-only calls should not become money opportunities unless there is a real commercial bridge.

### 5.5. `tomorrow_follow_up`

Purpose:

- Help manager decide whom to take into work tomorrow.

LLM2 must provide:

- client-specific next action;
- reason this client is worth follow-up;
- recommended opening phrase;
- risk if not followed up.

Quality rules:

- inclusion and final status still belong to deterministic Report Layer;
- LLM2 enriches wording only;
- no follow-up if the call is refusal/not suitable unless there is explicit allowed continuation.

### 5.6. `tomorrow_challenge`

Purpose:

- Turn repeated call issues into one skill challenge for tomorrow.

LLM2 must provide:

- which skill this call indicates;
- what the manager should practice;
- concrete behavior standard;
- optional example phrase.

Quality rules:

- Report Layer aggregates across calls and picks the final challenge;
- one call should not define the challenge alone unless it is the strongest available signal.

### 5.7. `call_list_context`

Purpose:

- Improve daily call list readability.

LLM2 must provide:

- short topic;
- short context;
- final action hint if relevant.

Quality rules:

- no generic `Обсуждение с клиентом`;
- no invented client names;
- no technical fragments as business context.

## 6. Proof Model Upgrade

v15 must make proof type strict:

- `direct_gap` — one quote or short fragment directly proves the manager gap.
- `sequence_inference` — the gap is proven by event order.
- `absence_in_context` — the gap is proven by a missing action in available context.
- `context_support` — the quote supports context but does not prove a problem by itself.

Important rule:

If the problem is "manager did not qualify before offering product", then a quote like "I can send product information" is usually not `direct_gap`. It is context. The proof is sequence or absence.

## 7. Report Layer Upgrade

Report Layer should consume LLM2 block-ready candidates in this priority:

```text
valid report_evidence.block_candidates[block]
-> valid semantic_case.report_block_fit[block]
-> existing report_evidence v1 block arrays
-> legacy fallback
```

Report Layer responsibilities:

- validate candidate structure;
- reject weak or contradictory candidates;
- rank candidates across calls;
- keep deterministic authority for report scope and final outcomes;
- render block-specific labels by proof type:
  - `direct_gap` -> `Подтверждение из звонка`
  - `sequence_inference` -> `Суть момента`
  - `absence_in_context` -> `Что не было зафиксировано`
  - `context_support` -> `Контекст из звонка`

Report Layer must not fill missing semantic meaning with generic stage text when a block-ready candidate is invalid. It should reject and move to the next candidate.

## 8. Implementation Tasks

### Task 1 — Contract And Prompt Design

Status: `[x] completed`

Owner:

- Hooke agent prepares documentation, prompt, and instruction-version changes.

Completed on 2026-05-14:

- Updated the LLM2 prompt to require optional block-ready material for `situation_day`, `call_breakdown`, `voice_of_customer`, `money_on_table`, `tomorrow_follow_up`, `tomorrow_challenge`, and `call_list_context`.
- Bumped `APPROVED_INSTRUCTION_VERSION` to `edo_sales_mvp1_call_analysis_v15_block_ready`.
- Runtime note: the first v15 label was too long for the `analyses.instruction_version` DB column (`VARCHAR(50)`), so the production-safe persisted label is the 44-character value above.
- Documented strict proof rules: `direct_gap` is only for a quote/fragment that directly proves the manager gap; product-offer quotes for missing-qualification cases should normally be `sequence_inference` or `absence_in_context` with `quote_role=supports_context`.
- Updated contract/selection docs to state that LLM2 prepares sufficient block-specific meaning while the Report Layer keeps deterministic authority.

Why this task was implemented:

- To move semantic responsibility into LLM2: the model must produce enough material for each report block, instead of leaving the Report Layer to infer the meaning from fragments.

Purpose:

- Make LLM2 responsible for sufficient material per report block.

Planned changes:

- update `docs/REPORT_EVIDENCE_CONTRACT.md`;
- update `docs/PROMPTS_GUIDE.md`;
- update `docs/MANAGER_DAILY_SELECTION_MODEL.md`;
- update `core/app/agents/calls/prompts/analyze.md`;
- bump approved instruction version to v15.

Acceptance criteria:

- prompt explicitly tells LLM2 to evaluate block readiness;
- each block has clear requirements;
- proof-type rules are explicit;
- block-ready contract remains additive.

### Task 2 — Schema And Validator

Status: `[x] completed`

Owner:

- Poincare agent prepares schema/validator and validation-test changes.

Completed on 2026-05-14:

- Added optional `report_evidence.block_candidates` schema for all v15 target blocks.
- Added block-specific required-field, role/title-mode, proof-type, quote-role, grounded quote, direct-gap overclaim, and duplicate missing/action validation.
- Added prompt-field compatibility for common LLM2 field names such as `better_action`, `proof_explanation`, `what_it_means`, `manager_action`, `client_next_action`, `skill_signal`, `practice_focus`, and `final_action_hint`.
- Added focused validation tests for sequence/absence proof, direct-gap overclaim, quote-role mismatch, duplicate missing/action, and call-breakdown moments.

Why this task was implemented:

- To make v15 enforceable: LLM2 can now send block-ready candidates, but weak or contradictory material is rejected before it can appear in the manager report.

Purpose:

- Prevent weak, incomplete, or contradictory block candidates from reaching the report.

Planned changes:

- add optional `block_candidates` schema;
- validate fit score, role, title mode, proof type, quote role, and required block fields;
- reject direct-gap overclaims;
- reject duplicate `what_was_missing` / `better_next_action`;
- add reason codes for invalid block candidates.

Acceptance criteria:

- invalid block candidates are rejected with diagnostics;
- valid sequence/absence-based candidates are accepted;
- old `report_evidence` remains backward-compatible.

### Task 3 — Report Layer Selection

Status: `[x] completed`

Owner:

- Epicurus agent prepares Report Layer selection/rendering changes.

Completed on 2026-05-14:

- Report Layer now detects valid `report_evidence.block_candidates`.
- `Ситуация дня` and `Разбор звонка` now prefer valid block candidates before `semantic_case.report_block_fit` and legacy v1 arrays.
- Diagnostics now expose block-candidate availability, valid blocks, source counts, selected/rejected candidates, and rejection reasons.
- Dedupe between `Ситуация дня` and `Разбор звонка` is scoped to new `block_candidates` output so v14 semantic fallback behavior remains stable.

Why this task was implemented:

- To change Report Layer from a meaning-builder into a selector: it chooses the best LLM2-prepared block material and keeps deterministic quality control.

Purpose:

- Make Report Layer select block-ready material instead of constructing meaning.

Planned changes:

- index block candidates by call and block;
- prefer valid block candidates for target blocks;
- preserve deterministic status, scope, and hotness authority;
- expose diagnostics showing selected source and rejection reasons.

Acceptance criteria:

- `Ситуация дня` can be selected from `block_candidates.situation_day`;
- `Разбор звонка` can be selected from `block_candidates.call_breakdown`;
- diagnostics explain why candidates were used or rejected.

### Task 4 — PDF Rendering Rules

Status: `[x] completed`

Owner:

- Epicurus agent prepares proof-aware PDF rendering changes together with Task 3.

Completed on 2026-05-14:

- PDF/DOCX rendering now uses proof-aware labels:
  - `direct_gap` -> `Подтверждение из звонка`
  - `sequence_inference` -> `Суть момента`
  - `absence_in_context` -> `Что не было зафиксировано`
  - `context_support` -> `Контекст из звонка`
- `Разбор звонка` can show essence/proof text without pretending a context quote is direct proof.

Why this task was implemented:

- To stop making "Фрагмент" look mandatory or stronger than it is. The report now renders the type of proof honestly.

Purpose:

- Render proof correctly and avoid misleading "fragment proves everything" behavior.

Planned changes:

- replace mandatory `Фрагмент` logic with proof-aware labels;
- use `Суть момента`, `Что не было зафиксировано`, `Контекст из звонка`, or `Подтверждение из звонка`;
- prevent duplicated text between `Ситуация дня` and `Разбор звонка`.

Acceptance criteria:

- sequence/absence cases no longer look like quote-only proof;
- report is easier to read;
- same call can appear in multiple blocks without repeating identical paragraphs.

### Task 5 — Tests

Status: `[x] completed`

Purpose:

- Lock the new behavior so future prompt/report changes do not regress.

Planned tests:

- direct-gap overclaim is rejected;
- sequence inference with context quote is accepted;
- duplicate missing/action pair is rejected or normalized;
- block candidate source is preferred over legacy arrays;
- invalid candidate falls back to next valid source;
- rendering label changes by proof type.

Acceptance criteria:

- focused pytest suite passes;
- JS report generator syntax check passes;
- `git diff --check` passes.

Current verification on 2026-05-14:

- Passed: `python3 -m py_compile core/app/agents/calls/report_evidence.py core/app/agents/calls/reporting.py core/app/agents/calls/analyzer.py ...`
- Passed: `node --check scripts/generate_docx_report.js`
- Passed: `git diff --check`
- Passed in Docker: `pytest tests/test_ai_provider_routing.py::AIProviderRoutingTests::test_analyzer_prompt_context_includes_report_evidence_contract tests/test_ai_provider_routing.py::AIProviderRoutingTests::test_semantic_retry_instruction_preserves_report_evidence_minimum tests/test_report_evidence_coaching_moment_normalization.py tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_prefers_block_candidates_before_semantic_case -q`
- Passed in Docker after real-report defect fix: `pytest tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_situation_day_block_candidate_focus_override_happens_before_deep_dive tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_prefers_block_candidates_before_semantic_case tests/test_manual_reporting.py::ManualReportingPayloadTests::test_step8ah11b_daily_focus_filters_mismatched_situation_and_breakdown tests/test_manual_reporting.py::ManualReportingPayloadTests::test_step8ah11b_daily_focus_keeps_aligned_report_evidence_blocks -q`
- Passed in Docker earlier: focused v15/reporting suite, `13 passed`.
- Broader legacy run `pytest tests/test_report_evidence_coaching_moment_normalization.py tests/test_manual_reporting.py tests/test_ai_provider_routing.py -q` currently has 220 passed and 6 failures in older manager_daily fixture/verification cases. These failures are not in the new block-candidate path and need separate triage before using the broad suite as a release gate.

Additional fixes after the real Tolegen run:

- Valid `block_candidates` are now allowed to survive even when legacy `semantic_case` or other v1 report_evidence fields fail validation.
- `daily_coaching_focus` is aligned early from the selected Situation Day case when the best valid case is outside the aggregate score focus.
- Same-stage selected Situation Day cases now align the focus problem wording, so deep dive/challenge wording does not stay generic.
- Next-step problem matching was narrowed so generic words such as "зафиксировано" or "договор" do not incorrectly force qualification problems into `completion_next_step`.
- DOCX/PDF Situation Day label now avoids duplicate `Суть момента`; the context fragment is rendered as `Контекст из звонка`.
- Text preview now reads from `situation_day_coaching_view`, so package preview and PDF no longer describe different Situation Day cases.

### Task 6 — Re-run Tolegen Calls

Status: `[x] completed`

Purpose:

- Validate v15 on the real 2026-05-08 Tolegen call set.

Planned changes:

- re-run LLM2 for all available Tolegen transcripts on 2026-05-08;
- rebuild manager daily report;
- export diagnostics, preview text, PDF, and review package;
- send updated PDF to Telegram.

Acceptance criteria:

- new review package exists;
- `report_preview.txt` matches the PDF text;
- Telegram delivery succeeds;
- diagnostics show block-ready candidate usage and rejection reasons.

Completed on 2026-05-14:

- Re-ran LLM2 for Tolegen using `edo_sales_mvp1_call_analysis_v15_block_ready`.
- Built analyses: 38 total persisted for the rolling source window:
  - 2026-05-06: 6 successful, 14 `not_coachable_or_reportable`, 1 `semantically_empty_analysis`;
  - 2026-05-08: 10 successful, 7 `not_coachable_or_reportable`.
- Final report status: `ready`; run status: `partial` because some discovered calls are short/empty or have failed semantic analysis.
- Report-day readiness: 32 relevant calls found, 17 meaningful calls, 10 calls in coaching core, coverage 31.2%.
- Telegram delivery succeeded:
  - target: operator test chat `74665909`;
  - message id: `216`;
  - artifact: `manager_daily_d42e8246-772e-4a04-bbe7-2b88f45db695_2026-05-08_manager_daily_template_v2.pdf`.
- Review package:
  - `/root/ai-sales-analyzer/review_packages/coaching_moment_v15_block_ready_tolegen_2026-05-08/`
  - `report_preview.txt` was extracted from the final PDF, not from stale JSON preview.
- Diagnostics:
  - `block_candidates_available_count`: 17;
  - `block_candidates_valid_count`: 11;
  - source counts: `block_candidates=11`, `report_evidence_v1=6`, `legacy_fallback=0`.

### Task 7 — Quality Review

Status: `[x] completed`

Purpose:

- Compare v15 output with v14 and decide whether the new mechanism is good enough to keep.

Review questions:

- Did `Ситуация дня` become stronger and more honest about proof?
- Did `Разбор звонка` add depth instead of repeating the same case?
- Did `Голос клиента` remain customer-signal based rather than forced into manager-error logic?
- Did `Кого взять в работу завтра` and `Челлендж` use LLM2 material without losing deterministic control?
- Did the report become easier to read?

Acceptance criteria:

- written comparison summary;
- list of remaining defects, if any;
- decision: keep v15, adjust v15, or rollback.

Completed on 2026-05-14:

- `Ситуация дня` now uses LLM2 block-ready material instead of deterministic legacy fallback.
- Final selected case:
  - call: `Татьяна · +77051859385 · 8 мая 2026, 09:26`;
  - source: `report_evidence.block_candidates.situation_day`;
  - stage: `Завершение и договорённости`;
  - thesis: `Менеджер не подытожил договорённость и не убедился в понимании.`
- `Разбор звонка` uses `report_evidence.block_candidates.call_breakdown` for the same call and adds a deeper breakdown moment instead of the old positive sale case.
- `Голос клиента` remains customer-signal based and is not forced into a manager-error frame.
- Task 2 completed: LLM2 `stage_code` hardening for `block_candidates`.
  - Prompt now explicitly requires `stage_code` on every `fit=true` block candidate.
  - Analyzer now rejects fresh `fit=true` `report_evidence.block_candidates.*` without canonical `stage_code`, triggering the normal LLM2 repair retry.
  - Report Layer now treats missing/invalid `stage_code` as a candidate-level rejection reason for block-ready material.
- Remaining quality risk:
  - Some sequence-inference context is still short because transcript speaker roles are not always available.
- Decision: keep v15 path and continue tightening prompt/stage completeness; do not rollback.

## 9. Progress Protocol

After each task:

- update this file;
- write a short user-facing summary;
- explain why the task was implemented and what goal it served;
- wait for confirmation before moving to the next task, unless the user explicitly says to continue automatically.

## 10. Expected Final Artifacts

- updated prompt and instruction version;
- updated report evidence contract;
- updated validator and diagnostics;
- updated Report Layer selection;
- updated PDF rendering behavior;
- test results;
- Tolegen v15 review package;
- Tolegen v15 PDF delivered to Telegram;
- comparison notes against v14.
