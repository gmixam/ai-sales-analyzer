# Temporary LLM2 Quality Changeset And Test Plan

Date: 2026-05-15
Status: temporary working file, no runtime changes yet
Project: `/root/ai-sales-analyzer`

## Purpose

Prepare a controlled plan for improving LLM2 quality and stability without changing production behavior first.

The current LLM2 prompt already reflects the target architecture, but it is overloaded: one call must produce MVP-1 scoring, report evidence, semantic case, block candidates, follow-up, VOC, and call-list context. The proposed work should make LLM2 more stable by measuring baseline quality first, then narrowing the primary output around a strong per-call semantic understanding.

## Уточнение продуктового критерия качества

Главная проблема качества не просто в том, что отчетам не хватает цитат. Главная проблема в том, что отчеты часто дают вывод без достаточного контекста звонка, и менеджер не понимает, почему этот вывод верный.

Целевое поведение:

- `СИТУАЦИЯ ДНЯ` должна описывать ситуацию полностью: где возникла проблема, что менеджер сделал или упустил, как отреагировал клиент и почему это важно.
- `РАЗБОР ЗВОНКА` должен содержать понятное резюме того, что было не так. Речевка или цитата полезна только тогда, когда усиливает объяснение; она не должна быть обязательной и не должна считаться доказательством сама по себе.
- `ГОЛОС КЛИЕНТА` не должен опираться на обрезанные фразы без контекста. Отчет должен объяснять, что было до и после фразы, и почему рекомендация следует из этого контекста.
- Доказательные фрагменты могут включать несколько реплик или короткий фрагмент диалога, если это нужно для понимания. Не нужно искусственно ограничивать LLM2 одной короткой цитатой, если она не доказывает вывод.
- Менеджер должен суметь прочитать отчет без памяти о звонке и все равно понять проблему, доказательство и точку роста.

## Что должно быть готово до прогона и сравнения

До запуска экспериментального прогона нельзя начинать "исправление вслепую". Сначала нужно зафиксировать целевую модель качества и правила сравнения.

Обязательные подготовительные шаги:

1. **Описать новый стандарт смыслового блока.**
   Для `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА` и `ЧЕЛЛЕНДЖ` блок считается хорошим только тогда, когда менеджер понимает контекст, проблему, доказательство и точку роста без памяти о звонке.

2. **Перепроектировать роль LLM2.**
   LLM2 должен собирать не набор коротких цитат, а полноценный смысловой кейс: что произошло, где возник пробел, как отреагировал клиент, почему это важно, какие фрагменты диалога это доказывают и что делать иначе.

3. **Разобрать перегрузку и дублирование LLM2.**
   Нужно описать, какие поля сейчас повторяют друг друга или могут противоречить друг другу: `semantic_case`, `block_candidates`, `evidence_fragments`, `voice_of_customer`, `recommendations`, `follow_up`. После этого определить один источник истины и производные поля для отчета.

4. **Выбрать способ декомпозиции.**
   Базовый безопасный вариант: сначала сделать v16 как более структурированный один вызов, где `semantic_case` является главным смысловым объектом, а отчетные блоки являются производными. Если этого недостаточно, следующий этап — дробление на несколько последовательных LLM-вызовов.

5. **Обновить критерии ручной проверки.**
   Агенты и мы оцениваем не наличие цитаты, а полноту контекста: достаточно ли объяснено, что произошло, подтверждает ли фрагмент вывод, не обрезана ли цитата, вытекает ли рекомендация из диалога, не спутан ли сигнал клиента с ошибкой менеджера.

6. **Зафиксировать тестовую выборку и метрики.**
   Сравнение v15 и v16 должно идти на одних и тех же звонках и отчетах. В первую очередь проверяются слабые текущие блоки: `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `ЧЕЛЛЕНДЖ`.

Допуск к прогону:

- целевая модель качества описана;
- дублирующиеся поля LLM2 перечислены;
- выбран источник истины для смысла звонка;
- критерии ручной оценки утверждены;
- eval-набор зафиксирован;
- понятно, какие артефакты будут сравниваться до и после.

## Non-Negotiable Boundaries

- Do not change production reporting behavior until baseline and A/B results are reviewed.
- Do not run mass STT, source discovery, `build_missing`, delivery, scheduler, or business email.
- Do not overwrite old analyses.
- Any new prompt experiment must use a new `instruction_version`.
- Experimental analyses must be marked controlled/sample if persisted, so normal `manager_daily` does not select them by default.
- MVP-1 scoring contract remains compatible: required fields, checklist stages, criteria, `score_by_stage`, `strengths`, `gaps`, `recommendations`, `follow_up`, and `evidence_fragments` must remain valid.
- Deterministic reporting remains final authority for outcome, report-day scope, call-list inclusion, hotness priority, and rendering.

## Current Runtime Anchors

- LLM2 prompt: `core/app/agents/calls/prompts/analyze.md`
- Analyzer call path: `core/app/agents/calls/analyzer.py`
- Current analyzer instruction version in code: `edo_sales_mvp1_call_analysis_v15_block_ready`
- Report evidence schema/validator: `core/app/agents/calls/report_evidence.py`
- Reporting consumer: `core/app/agents/calls/reporting.py`
- Contract doc: `docs/REPORT_EVIDENCE_CONTRACT.md`
- Existing inventory: `docs/LLM2_MANAGER_DAILY_INSTRUCTIONS_MAP.md`
- Prompt policy: `docs/PROMPTS_GUIDE.md`

## Documentation Actuality Snapshot

The general project documentation is only partially current for this LLM2 quality work.

Likely current / high-trust docs:

- `docs/REPORT_EVIDENCE_CONTRACT.md` — dated 2026-05-14 and includes v15 `block_candidates`.
- `docs/MANAGER_DAILY_SELECTION_MODEL.md` — includes Step 8AH-11 gates, 2026-05-12 semantic-case updates, and 2026-05-14 v14/v15 notes.
- `docs/PROMPTS_GUIDE.md` — use for permanent prompt policy and prompt/task split.

Needs update before implementation:

- `docs/CONTEXT_INDEX.md` — still presents `MANUAL_OUTPUT_VALIDATION_SPEC.md` as the default current-stage doc and does not foreground the v15 LLM2/report-evidence docs, current-week baseline method, or the report-quality workstream.
- `docs/PROGRESS.md` — last top status is v13 on 2026-05-13, while runtime code and current-week analyses are on v15 from 2026-05-14.
- `docs/ROADMAP.md` — broadly useful, but it does not describe the current LLM2 quality stabilization/eval step or the concrete current-week baseline comparison method.
- `docs/ARCHITECTURE.md` — mostly useful for architecture, but it should be checked for stale delivery/storage statements before using it to reason about where Telegram-visible reports and saved scheduled drafts should live.
- `docs/MANUAL_REPORTING_PILOT.md` — useful for operating boundaries, but its delivery wording must be treated carefully because current manual UI Telegram reports may exist without matching `scheduled_report_drafts` for this week.
- `docs/LLM2_MANAGER_DAILY_INSTRUCTIONS_MAP.md` — good inventory through Step 8AH-11H, but audit date is 2026-05-10 and it should be refreshed against v15 runtime facts and current-week baseline observations.

Temporary / historical docs:

- `docs/TEMP_LLM2_BLOCK_READY_V15_PLAN.md` and `docs/TEMP_LLM2_SEMANTIC_ANALYSIS_PLAN.md` may contain latest operational reasoning, but they should not silently become canonical without promotion into the stable docs above.
- `docs/MANUAL_OUTPUT_VALIDATION_SPEC.md` and old manual validation runs are historical for the current LLM2/report-quality task unless a defect explicitly touches single-call Telegram card validation.

Runtime facts to keep visible in docs:

- Fresh LLM2 analyses use `edo_sales_mvp1_call_analysis_v15_block_ready`.
- Current-week persisted calls/analyses exist for 2026-05-12..2026-05-14.
- Current-week scheduled review storage does not contain ready `scheduled_report_batches` / `scheduled_report_drafts` / saved PDFs for 2026-05-11..2026-05-15.
- For this quality work, comparison must be generated from persisted calls and analyses in ready-only/no-delivery mode, not from existing saved PDFs.

## Target Direction

Move from:

```text
LLM2 tries to prepare every report block directly in one large output
```

to:

```text
LLM2 reliably understands one call and returns a strong semantic_case;
Reporting deterministically validates, selects, derives, renders, and falls back locally.
```

## Current Baseline Reality

As of 2026-05-15, the current-week persisted data exists, but ready PDF report artifacts do not exist in the scheduled UI storage for this week.

Observed DB snapshot for calls with `metadata.call_date` from 2026-05-12 through 2026-05-14:

- 121 interactions total;
- 69 interactions with transcripts;
- 69 LLM2 analysis rows;
- 22 successful analysis rows;
- 47 failed/non-reusable analysis rows;
- instruction version: `edo_sales_mvp1_call_analysis_v15_block_ready`;
- no `scheduled_report_batches` / `scheduled_report_drafts` were created during 2026-05-11..2026-05-15;
- all-time scheduled drafts contain only old `manager_daily` rows from 2026-04-22.

Therefore, this LLM2 quality work should not depend on existing saved PDFs. The comparison baseline should be generated from the persisted calls and analyses in ready-only/no-delivery mode.

## Baseline Artifact Run Completed

Date: 2026-05-15

Output directory:

- `review_packages/llm2_quality_baseline_2026-05-12_2026-05-14/`

Generated artifacts:

- `manifest.json`
- `summary.md`
- `quality_report.md`
- per manager/day:
  - `payload.json`
  - `diagnostics.json`
  - `block_summary.json`
  - `preview.json`
  - `report_preview.txt`
  - `report_preview.html`

Safety:

- source discovery was not run;
- STT was not run;
- LLM was not run;
- Telegram/email delivery was not run;
- scheduled draft/batch persistence was not run.

Baseline result:

- 121 current-week interactions in scope;
- 69 with transcript;
- 69 selected v15 analyses;
- 47 failed/non-reusable selected analyses;
- 7 manager/day payloads generated.

Automated first findings:

- several reports are built from a thin coaching base because failed/non-reusable analyses dominate the current-week set;
- valid `block_candidates` are already useful where present, especially for Тимур on 2026-05-12 and 2026-05-13;
- weak areas for manual review are reports that fall back to `deterministic_assembly`, `legacy_fallback`, or `focus_evidence_missing`;
- the weakest generated report is Тимур on 2026-05-14: focus validation warning, no Situation/VOC source, and insufficient Call Breakdown evidence.

## Report-Payload Measurement Principle

The primary quality target is the manager-facing daily report payload/preview assembled from existing persisted analyses, especially the semantic blocks whose quality currently feels unstable:

- `СИТУАЦИЯ ДНЯ`;
- `РАЗБОР ЗВОНКА`;
- `ГОЛОС КЛИЕНТА`;
- `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`;
- `ЧЕЛЛЕНДЖ`;
- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`;
- call-list `Тип / суть` and `Контекст`.

Do not fix PDF/report persistence in this changeset. Build comparison artifacts explicitly in no-delivery mode:

```text
existing persisted calls + current analyses
-> ready-only manager_daily payload / rendered text preview
-> baseline quality review

same calls + experimental LLM2 analyses
-> ready-only experimental manager_daily payload / rendered text preview
-> after quality review
```

The raw LLM2 output is measured because it explains report quality, but promotion decisions should be made from the report payload/preview:

- Выбранный доказательный фрагмент действительно поддерживает вывод?
- Достаточно ли окружающего контекста, чтобы понять вывод без переслушивания звонка?
- Блок объясняет, что произошло, где возникла проблема и чему менеджер должен научиться?
- Сигнал клиента ошибочно не превращается в проблему менеджера?
- Контрдоказательства не игнорируются?
- `СИТУАЦИЯ`, `РАЗБОР` и `ЧЕЛЛЕНДЖ` согласованы вокруг одной реальной проблемы или этапа?
- Рекомендация связана с наблюдаемым диалогом?
- Слабые или шумные фрагменты транскрипта отфильтрованы?
- Цитаты используются как усиление смысла, а не как обязательное украшение?
- Контекст в списке звонков конкретный, а не общий?
- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` отражает реальную дальнейшую работу и правила финального исхода?

Expected comparison artifacts should be written under a temporary/review directory, for example:

- `review_packages/llm2_quality_baseline_2026-05-12_2026-05-14/`
- `review_packages/llm2_quality_v16_2026-05-12_2026-05-14/`

These artifacts are for review only and must not imply Telegram delivery or scheduled draft persistence.

## Workstream 0: Documentation Audit And Refresh

### Agent Task 0.1: Build Documentation Status Matrix

Goal: classify the project docs before any LLM2/runtime changes.

Inspect at least:
- `docs/CONTEXT_INDEX.md`;
- `docs/PROGRESS.md`;
- `docs/ROADMAP.md`;
- `docs/ARCHITECTURE.md`;
- `docs/MANUAL_REPORTING_PILOT.md`;
- `docs/MANAGER_DAILY_SELECTION_MODEL.md`;
- `docs/REPORT_EVIDENCE_CONTRACT.md`;
- `docs/LLM2_MANAGER_DAILY_INSTRUCTIONS_MAP.md`;
- temporary LLM2 docs from 2026-05-14.

For each document, mark:
- `current`;
- `mostly_current_needs_note`;
- `stale_needs_update`;
- `historical_do_not_use_as_current_source`.

Expected artifact:
- `review_packages/llm2_quality_docs_audit_2026-05-15.md`

Acceptance:
- Every stale claim includes the file path and exact topic.
- The matrix identifies which docs are canonical for LLM2 quality work.
- The audit distinguishes stable docs from temporary notes.

### Agent Task 0.2: Update Documentation Entry Points

Goal: prevent future agents from entering the project through stale context.

Candidate updates after review:
- update `docs/CONTEXT_INDEX.md` reading order so LLM2/report-quality work starts from `MANAGER_DAILY_SELECTION_MODEL.md`, `REPORT_EVIDENCE_CONTRACT.md`, `PROMPTS_GUIDE.md`, and `LLM2_MANAGER_DAILY_INSTRUCTIONS_MAP.md`;
- mark `MANUAL_OUTPUT_VALIDATION_SPEC.md` as historical/default-only for old single-call validation, not the current LLM2 report-quality stage;
- update `docs/PROGRESS.md` top status from v13 to the actual v15/current-week quality-stabilization state;
- add a short note that current-week report comparison is generated in ready-only/no-delivery mode because scheduled draft/PDF storage has no current-week artifacts.

Acceptance:
- No code or runtime behavior changes.
- Docs reflect the actual current analyzer version and current-week baseline reality.
- A new agent can understand that this changeset is about LLM2 semantic/report quality, not report persistence repair.

### Our Task 0.3: Approve Documentation Source Of Truth

We should agree which docs are authoritative before implementation:
- canonical LLM2/report contract docs;
- historical docs that should not drive new work;
- temporary docs that should either be promoted, summarized, or discarded.

Decision:
- approve documentation update scope;
- decide whether to update stable docs now or only attach the audit to this temporary task file first.

## Workstream A: Baseline And Eval Set

### Agent Task A1: Build Current-Week Eval Case Inventory

Goal: create a fixed list of calls for prompt comparison.

Inputs:
- persisted interactions with `metadata.call_date` from 2026-05-12 through 2026-05-14;
- existing v15 analyses for the same interactions;
- selected managers/days from the current-week dataset.

User-priority baseline case:

- Толеген Жангазиев, звонки за 2026-05-14.
- Этот менеджер/день должен быть включен в eval-набор обязательно.
- Для него нужно сравнить не только отдельные звонки, но и итоговый дневной отчет: `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `ЧЕЛЛЕНДЖ`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, а также список звонков.

Suggested sample size:
- 20-30 calls total, sampled from the 69 analyzed current-week calls;
- include `agreement`, `rescheduled`, `open`, `refusal`, `tech_service`, `not_suitable`;
- include edge cases:
  - customer signal without manager gap;
  - manager did the allegedly missing action;
  - thin transcript;
  - tech/service call that looks sales-like;
  - refusal with no follow-up;
  - open interest with weak next step;
  - unreliable speaker roles.

Expected artifact:
- `review_packages/llm2_quality_eval_cases_2026-05-12_2026-05-14.json`

Each case should contain:
- `interaction_id`;
- manager/date labels if known;
- transcript availability flag;
- current selected analysis id and instruction version if any;
- expected human baseline:
  - business outcome;
  - whether manager gap exists;
  - whether suitable for `situation_day`;
  - whether suitable for `call_breakdown`;
  - whether VOC exists;
  - whether tomorrow follow-up should exist;
  - notes about risky interpretation.

Acceptance:
- The case list is deterministic and can be reused.
- The sample includes both easy and adversarial cases.
- No new LLM/STT run is needed to create the list.

### Agent Task A1B: Export Current Baseline Reports

Goal: generate current report baseline from persisted v15 analyses without delivery and without rebuilding missing artifacts.

Input:
- current-week dates: 2026-05-12, 2026-05-13, 2026-05-14;
- managers with analyzed calls: Алишер, Тимур, Толеген;
- mode: `report_from_ready_data_only`;
- delivery mode: no delivery / preview only;
- include only stable/production analyses by default.

Expected artifact directory:
- `review_packages/llm2_quality_baseline_2026-05-12_2026-05-14/`

Expected files:
- per-manager/per-day payload JSON;
- rendered text preview when available;
- block-source diagnostics;
- summary markdown listing selected source per semantic block.

Acceptance:
- `transcripts_built=0`;
- `analyses_built=0`;
- no Telegram/email delivery;
- no scheduled draft persistence required;
- output is reproducible from current persisted analyses.

### Agent Task A2: Build Baseline Quality Report From Report Payloads

Goal: measure current LLM2/report evidence quality as it appears in manager_daily payload/preview before any prompt change.

Metrics:
- total cases;
- cases with current reusable analysis;
- `report_evidence_version="v1"` count;
- whole-package `validate_report_evidence` pass/fail;
- `semantic_case` available/valid/used;
- `block_candidates` available/valid blocks;
- invalid enum errors;
- ungrounded quote errors;
- generic wording warnings/errors;
- `business_outcome.status` mismatch with deterministic resolver;
- fallback usage by report block;
- `call_report_summary` available/used/rejected;
- customer signal incorrectly treated as manager gap;
- counter-evidence ignored.
- selected evidence fragment does not prove the rendered conclusion;
- Situation/Breakdown/Challenge stage mismatch;
- generic report block wording;
- call-list context generic/empty/technical;
- tomorrow follow-up inclusion/exclusion mismatch.

Expected artifact:
- `review_packages/llm2_quality_baseline_2026-05-12_2026-05-14/quality_report.json`
- `review_packages/llm2_quality_baseline_2026-05-12_2026-05-14/quality_report.md`

Acceptance:
- Report can be regenerated from the same eval list.
- Each failure includes `interaction_id`, failing path, and reason.
- Report distinguishes contract failure from semantic quality failure.

## Workstream B: Prompt Simplification Experiment

### Agent Task B1: Draft v16 Prompt Strategy

Goal: propose a narrower LLM2 primary output without implementing it yet.

Proposed instruction version:

```text
edo_sales_mvp1_call_analysis_v16_semantic_primary
```

Primary outputs:
- existing MVP-1 contract;
- `report_evidence.business_outcome`;
- `report_evidence.call_report_summary`;
- `report_evidence.semantic_case`;
- legacy arrays for backward compatibility when easy to fill.

Secondary/experimental outputs:
- `report_evidence.block_candidates` should be optional, not the main quality dependency.

Prompt should emphasize:
- one coherent per-call meaning;
- grounded evidence;
- exact transcript quotes only;
- customer signal vs manager gap separation;
- counter-evidence;
- absence-in-context wording;
- deterministic reporting authority.

Prompt should reduce:
- duplicated block-specific instructions;
- large repeated examples;
- forcing all seven block candidates on every meaningful call;
- parallel ways of saying the same thing.

Expected artifact:
- a draft plan or patch proposal, not automatically applied to production.

Acceptance:
- The draft explains what is removed, what remains, and why.
- The MVP-1 contract is not weakened.
- The new role of `semantic_case` is explicit.

### Agent Task B2: Prompt Regression Checklist

Goal: define tests that must pass if/when v16 prompt is implemented.

Required checks:
- prompt contains `REPORT_EVIDENCE_CONTRACT.md`;
- prompt preserves required MVP-1 fields;
- prompt requires JSON only;
- prompt requires grounded quotes;
- prompt forbids invented speakers/facts/timestamps/names;
- prompt keeps allowed `business_outcome.status` enum;
- prompt says deterministic resolver/reporting remains final authority;
- prompt requires non-generic `semantic_case` for business-meaningful calls;
- prompt prevents customer-signal-only calls from becoming `situation_day` manager-gap cases.

Acceptance:
- Tests can be added without running external LLM.
- Tests fail if the prompt drops core safety rules.

## Workstream C: Partial Validation And Local Fallback

### Agent Task C1: Design Section-Level Validation

Goal: prevent one bad field from suppressing all useful `report_evidence`.

Current risk:
- one invalid enum or ungrounded quote can make the whole package invalid;
- useful `call_report_summary` or `semantic_case` can be ignored because another section failed.

Proposed section statuses:
- `business_outcome`;
- `call_report_summary`;
- `semantic_case`;
- `block_candidates.situation_day`;
- `block_candidates.call_breakdown`;
- `block_candidates.voice_of_customer`;
- `block_candidates.money_on_table`;
- `block_candidates.tomorrow_follow_up`;
- `block_candidates.tomorrow_challenge`;
- `block_candidates.call_list_context`;
- legacy `situation_candidates`;
- legacy `manager_coaching_moments`;
- legacy `voice_of_customer`;
- legacy `follow_up_candidates`;
- `quote_bank`.

Expected artifact:
- design note with proposed diagnostic shape;
- compatibility plan for existing `report_evidence_valid`.

Acceptance:
- Existing whole-package status remains available for compatibility.
- Reporting can see which sections are individually usable.
- Invalid section falls back locally, not globally.

### Agent Task C2: Reporting Source Policy Update Plan

Goal: define how manager_daily consumes partial valid sections.

Desired policy:
- call list can use valid `call_report_summary` even if VOC is invalid;
- VOC can use valid VOC or semantic customer signal even if `quote_bank` is invalid;
- Situation/Breakdown can use valid `semantic_case`;
- block-specific invalid data falls back only for that block;
- final outcome and inclusion remain deterministic.

Expected artifact:
- source priority table per block;
- list of diagnostics that should prove the policy is working.

Acceptance:
- No block silently switches stage or scope.
- Diagnostics expose source per block.
- Fallback count can be compared before/after.

## Workstream D: A/B Execution

### Agent Task D1: Controlled A/B Runner

Goal: run current LLM2 and experimental LLM2 on the same eval cases.

Modes:
- baseline: existing stable/current `instruction_version`;
- experiment: proposed new `instruction_version`.

Safety:
- no mass runs;
- no production selection;
- controlled/sample purpose if results are persisted;
- no delivery.

Expected artifact:
- `review_packages/llm2_quality_v16_2026-05-12_2026-05-14/llm2_rerun.json`
- `review_packages/llm2_quality_v16_2026-05-12_2026-05-14/ab_results.json`
- optional `review_packages/llm2_quality_v16_2026-05-12_2026-05-14/ab_summary.md`

Comparison fields:
- old/new analysis id;
- old/new instruction version;
- contract success;
- report evidence whole-package validity;
- section-level validity if implemented;
- semantic-case quality;
- fallback source changes;
- human-baseline match/mismatch;
- notes for manual review.

Acceptance:
- A/B can be rerun on the same case list.
- Results are traceable by `instruction_version`.
- Normal reports continue selecting stable/production analyses by default.

### Agent Task D2: Experimental Ready-Only Report Export

Goal: build after-change manager_daily payload/preview from the same current-week calls using experimental LLM2 analyses, without Telegram delivery and without changing saved PDF persistence.

Input:
- same managers/dates as baseline;
- same eval case set or full current-week analyzed call set;
- experimental analysis purpose / include-controlled flag or equivalent explicit selection;
- mode: `report_from_ready_data_only`;
- delivery mode: no delivery / preview only.

Expected artifact directory:
- `review_packages/llm2_quality_v16_2026-05-12_2026-05-14/`

Expected files:
- per-manager/per-day experimental payload JSON;
- rendered text preview when available;
- block-source diagnostics;
- before/after diff against baseline by block.

Acceptance:
- `transcripts_built=0`;
- no STT;
- no Telegram/email delivery;
- no production report selection changes;
- baseline and experimental outputs are comparable by manager/date/block.

## Workstream E: Human Review

### Our Task E1: Review Eval Case Baseline

We should review and approve:
- whether the eval cases cover the real instability;
- whether expected outcomes make business sense;
- whether edge cases are represented enough.
- which existing manager reports are the baseline for business-facing comparison.
- user-priority baseline: Толеген Жангазиев, 2026-05-14.

Decision:
- approve eval set;
- add/remove cases;
- split by manager/report day if needed.
- mark specific current reports as baseline artifacts.
- treat Толеген Жангазиев, 2026-05-14 as mandatory "было / стало" comparison case unless the underlying data is missing.

### Our Task E2: Review Baseline Quality

We should inspect:
- current PDF/text report output first;
- top invalid reasons;
- examples of generic wording;
- examples where customer signal became manager gap;
- examples where counter-evidence was ignored;
- where reporting fell back and why.

Decision:
- whether instability is mostly prompt-side, validator-side, or reporting-side.

### Our Task E3: Review v16 Prompt Strategy

We should decide:
- whether `semantic_case` becomes the primary LLM2 meaning object;
- whether `block_candidates` becomes optional/secondary;
- whether legacy arrays stay required, optional, or compatibility-only;
- whether partial validation should come before or after prompt simplification.

### Our Task E4: Approve A/B Promotion Criteria

Do not promote the new prompt unless:
- MVP-1 contract success does not regress;
- whole-package or section-level usable evidence improves;
- ungrounded quote errors decrease or stay zero;
- context completeness improves for `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, and `ГОЛОС КЛИЕНТА`;
- short quotes are no longer treated as proof when they do not explain the problem;
- recommendations are supported by the shown dialogue context;
- generic wording decreases;
- fallback usage decreases or becomes more local;
- outcome mismatch with deterministic resolver does not increase;
- customer-signal-only cases are not rendered as manager-gap problems;
- tech/refusal cases do not produce sales follow-up.

## Workstream F: Контроль исполнения и финальный результат

Этот блок фиксирует мою роль как контролирующего исполнителя задачи.

### My Task F1: Управлять последовательностью работ

Я запускаю и принимаю задачи последовательно, чтобы не перейти к прогону раньше, чем готова модель качества.

Порядок контроля:

1. проверить актуальность документации и точку входа для агентов;
2. зафиксировать текущую baseline-картину по отчетам;
3. принять новую доказательную модель блоков;
4. разобрать перегрузку и дублирование LLM2;
5. подготовить v16-стратегию или план декомпозиции;
6. только после этого запускать controlled A/B;
7. сравнить результаты по одним и тем же звонкам и отчетам;
8. подготовить финальный вывод для пользователя.

### My Task F2: Контролировать качество результатов агентов

Я не принимаю результат агента, если он:

- оценивает только наличие цитат, а не полноту контекста;
- не связывает вывод с конкретным местом звонка;
- не проверяет, вытекает ли рекомендация из диалога;
- игнорирует дублирование между `semantic_case`, `block_candidates`, `evidence_fragments`, `voice_of_customer`, `recommendations`, `follow_up`;
- предлагает промпт без правил проверки на менеджерскую понятность;
- предлагает запуск A/B без фиксированной baseline-выборки.

### My Task F3: Подготовить финальный пакет для пользователя

Финальный результат должен включать:

- что было изменено в подходе к LLM2;
- какие дубли и перегрузки найдены;
- какая доказательная модель выбрана;
- какие отчеты и звонки использовались для сравнения;
- таблицу v15 против v16 по ключевым блокам;
- примеры "было / стало" по слабым ситуациям;
- вывод, стало ли менеджеру понятнее, где проблема и что делать иначе;
- список оставшихся рисков и следующий рекомендуемый шаг.

Критерий успеха:

Новый отчет не просто звучит лучше, а лучше показывает проблемную ситуацию: менеджер видит контекст звонка, понимает свою недоработку, видит подтверждение и получает рекомендацию, которая логически следует из диалога.

## Test Plan

### Documentation Gate

Before prompt/runtime implementation:
- run the documentation status matrix from Workstream 0;
- verify `APPROVED_INSTRUCTION_VERSION` in code against docs;
- verify `REPORT_EVIDENCE_CONTRACT.md` and `MANAGER_DAILY_SELECTION_MODEL.md` mention v15 behavior;
- verify `CONTEXT_INDEX.md` and `PROGRESS.md` no longer route agents into stale v13/current-stage assumptions after they are updated;
- verify docs explicitly state that current-week comparison uses ready-only/no-delivery generated artifacts, not saved scheduled PDFs.

Acceptance:
- documentation does not contradict the runtime facts used for the eval;
- stale docs are either updated or marked historical;
- no agent task can reasonably infer that fixing PDF persistence is part of this LLM2 prompt-quality changeset.

### 0. Current Report Payload Baseline Review

Input:
- generated ready-only/no-delivery report payloads;
- rendered text previews where available;
- report diagnostics and source selections;
- human notes from reviewing the semantic blocks.

Mandatory first review:

- Толеген Жангазиев, 2026-05-14.
- Reason: user selected this as the primary candidate where the report quality should visibly improve.

Review each manager/day report by block:
- `СИТУАЦИЯ ДНЯ`;
- `РАЗБОР ЗВОНКА`;
- `ГОЛОС КЛИЕНТА`;
- `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`;
- `ЧЕЛЛЕНДЖ`;
- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`;
- call-list `Тип / суть`;
- call-list `Контекст`.

For each block, label:
- `good`;
- `acceptable_but_weak`;
- `wrong_meaning`;
- `generic`;
- `ungrounded`;
- `wrong_stage`;
- `wrong_call`;
- `evidence_does_not_support_claim`;
- `context_missing`;
- `quote_too_short_or_misleading`;
- `recommendation_not_supported`;
- `counter_evidence_ignored`;
- `should_be_empty`;
- `missing_useful_signal`.

Expected artifact:
- `review_packages/llm2_quality_baseline_2026-05-12_2026-05-14/human_review.md` or JSON equivalent.

Acceptance:
- Human report-payload review identifies the real defects to fix.
- Each defect links back to source diagnostics where possible.
- The same review checklist can be used after A/B.

### 1. Static / Unit Tests

Run prompt and validator related tests:

```bash
docker compose exec -T api pytest -q tests/test_manual_reporting.py -k 'report_evidence or semantic_case or block_candidates'
docker compose exec -T api pytest -q tests/test_ai_provider_routing.py -k 'prompt or report_evidence or semantic'
```

Run semantic checkpoint:

```bash
docker compose exec -T api pytest -q tests/test_manual_reporting.py -k 'step8ah11'
```

Expected:
- prompt regression checks pass;
- validator catches invalid enums, ungrounded quotes, invalid stage codes;
- semantic gates still reject generic/problem-mismatched content.

### 2. Offline Baseline Quality Report

Input:
- fixed eval case list;
- existing persisted analyses.

Expected:
- no STT;
- no LLM unless explicitly running A/B;
- report shows current failure/fallback profile.

Key questions:
- Is current instability caused by invalid JSON/schema, weak semantic evidence, or reporting gates?
- Which sections most often cause fallback?
- Are failures concentrated in certain call types?

### 3. Controlled LLM A/B

Input:
- same eval cases;
- current prompt/instruction version;
- experimental prompt/instruction version.

Expected:
- both runs produce traceable artifacts;
- no production overwrite;
- controlled/sample analyses excluded from normal reporting.

Compare:
- valid analysis count;
- valid report evidence count;
- valid semantic case count;
- section-level usability if available;
- fallback by block;
- mismatch with human baseline.
- manager-facing report block labels from baseline review vs experimental review.

### 4. Ready-Only Report Payload Check

Use already persisted analyses to build manager_daily payload without building missing transcripts/analyses.

Check:
- `transcripts_built=0`;
- `analyses_built=0` unless A/B explicitly allowed;
- call-list dates remain report-day only;
- rolling/expanded examples are labeled by `data_scope`;
- `daily_coaching_focus.stage_code` aligns with Situation, Breakdown, Challenge or shows explicit insufficient-evidence fallback;
- no broad/generic call-list topics;
- no bare `—` for sales/open/follow-up rows when deterministic fallback can explain context;
- no sales follow-up for refusal/tech/not-suitable.

### 5. Manual Spot Review

For each experimental improvement, inspect at least:
- 3 open/rescheduled calls;
- 2 agreement calls;
- 2 refusal calls;
- 2 tech/service calls;
- 3 adversarial manager-gap/counter-evidence cases.

Manual review questions:
- Does `semantic_case.core_meaning` match the actual call?
- Is the manager behavior described fairly?
- Is any quoted text exact?
- Is a customer signal incorrectly framed as a manager problem?
- Is absence phrased cautiously as `в доступной записи не зафиксировано...`?
- Is the next action specific and not generic?

## Suggested Order

1. Create eval case list.
2. Generate baseline quality report from current persisted analyses.
3. Review baseline with human notes.
4. Draft v16 prompt strategy, but do not apply yet.
5. Decide whether partial validation should be implemented before prompt simplification.
6. Implement the smallest safe experiment.
7. Run static tests.
8. Run controlled A/B on eval cases.
9. Compare reports.
10. Decide whether to promote, revise, or abandon the experiment.

## Promotion Criteria

The change can move from experiment to implementation only if:
- no MVP-1 scoring contract regression;
- no increase in semantic-empty failures for eligible sales calls;
- no increase in ungrounded quote failures;
- lower generic wording count;
- lower or more localized fallback usage;
- better `semantic_case` human-review match;
- no report-day scope regressions;
- no deterministic outcome authority regression.

## Open Decisions

- Should `block_candidates` remain generated by LLM2 or become derived/secondary?
- Should partial validation be implemented before prompt simplification?
- How many eval cases are enough for first promotion: 20, 30, or manager-specific samples?
- Should A/B analyses be persisted in DB or stored as external JSON artifacts first?
- Should `call_report_summary.client_display_name` ever become a primary display source, or remain guarded/fallback-only?
