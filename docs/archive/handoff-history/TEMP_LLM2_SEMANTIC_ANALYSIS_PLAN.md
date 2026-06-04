# TEMP — LLM2 Semantic Analysis Upgrade Plan

> Status 2026-05-21: superseded as an active plan. Keep this file as historical
> implementation context only. The current active track is LLM2 v15
> block-ready evidence plus bounded LLM3 narrative report composers, documented
> in `docs/BUSINESS_READY_REPORT_PACK_TASKS.md`,
> `docs/REPORT_EVIDENCE_CONTRACT.md`, `docs/MANAGER_DAILY_SELECTION_MODEL.md`,
> and `docs/PROGRESS.md`.

**Status:** superseded as active plan; latest guarded v13 pilot completed before v15/SFB work  
**Created:** 2026-05-12  
**Target validation date:** 2026-05-08 call set  
**Tracking purpose:** temporary progress file for the LLM2 semantic-analysis upgrade.

## 1. Goal

The goal of LLM2 is high-quality, meaningful analysis of each conversation for the report blocks that the manager-facing daily report needs.

LLM2 must not merely provide fragments, generic candidates, or raw summaries. It must produce a coherent semantic analysis of the call: what happened, what the client signal was, what the manager did or missed, why the moment matters, and what action should follow.

Only after LLM2 produces this per-call semantic analysis should the Report Layer select the best calls, validate quality, and render the final report.

Target responsibility shift:

```text
Before:
LLM2 -> fragments / candidates / summary
Report Layer -> tries to assemble meaning

After:
LLM2 -> meaningful per-call analysis for report needs
Report Layer -> selects best semantic cases, validates quality, renders report
```

## 2. Non-Negotiable Boundaries

- LLM2 owns semantic understanding of one call.
- LLM2 must ground conclusions in transcript evidence.
- LLM2 must produce analysis that can support the report blocks:
  - `СИТУАЦИЯ ДНЯ`
  - `РАЗБОР ЗВОНКА`
  - `ГОЛОС КЛИЕНТА`
  - `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`
  - `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`
  - call list topic/context enrichment
- Report Layer remains deterministic.
- Report Layer owns report-day scope, final statuses, inclusion/exclusion, ranking, quality gates, rendering, and diagnostics.
- `BusinessOutcomeResolver` remains final authority for manager-facing business outcome.
- Existing `report_evidence` fields remain backward-compatible.
- The upgrade must be additive first; old analyses must continue to work.

## 3. Target Design

Add a new semantic layer inside the existing additive `report_evidence` package.

Preferred initial shape:

```json
{
  "report_evidence_version": "v1",
  "report_evidence": {
    "semantic_case": {
      "case_title": "...",
      "case_type": "growth_zone|missed_opportunity|strong_practice|customer_signal|service_issue|insufficient_evidence",
      "core_meaning": "...",
      "why_this_call_matters": "...",
      "customer_signal": "...",
      "manager_behavior": "...",
      "coaching_diagnosis": "...",
      "recommended_next_action": "...",
      "best_dialogue_fragment": [],
      "evidence_quality": "direct|indirect|weak|insufficient",
      "usable_in_report": true
    }
  }
}
```

The exact field names may be adjusted during implementation if the existing codebase suggests a better fit, but the role must remain stable: this object is the main meaningful per-call analysis for report usage.

## 4. Implementation Plan

### Step 1 — Targeted Audit

Status: `[x] completed`

Audit where the current Report Layer assembles meaning from fragments/candidates:

- `СИТУАЦИЯ ДНЯ`
- `РАЗБОР ЗВОНКА`
- `ГОЛОС КЛИЕНТА`
- `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`
- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`
- call list topic/context enrichment
- current weak/generic/contextless quality gates

Deliverable:

- Update this file with audit notes.
- Identify which heuristics remain quality gates.
- Identify which heuristics should stop constructing meaning once `semantic_case` exists.

Audit notes completed on 2026-05-12:

Current reporting flow already prefers valid `report_evidence` over legacy fallback, but the preferred evidence is still split into block-specific fragments. The Report Layer therefore still assembles meaning from scattered fields.

Primary code path:

- `core/app/agents/calls/reporting.py`
- `_build_manager_daily_payload(...)`
- `_build_report_evidence_index(...)`
- `_build_report_evidence_situation(...)`
- `_build_call_breakdown_from_report_evidence(...)`
- `_build_voice_of_customer_from_report_evidence(...)`
- `_build_additional_situations_from_report_evidence(...)`
- `_build_call_tomorrow(...)`
- `_build_daily_call_row(...)`

Block findings:

- `СИТУАЦИЯ ДНЯ`
  - Current source: `report_evidence.situation_candidates`.
  - Report Layer selects by final sales-like status, daily focus stage, priority, evidence quality, score, and call time.
  - Report Layer then constructs `coaching_view` from `situation_title`, `what_happened`, `what_it_means`, `what_was_missing`, `next_time_action`, and `scripts`.
  - It may replace manager-only evidence with a client quote from `voice_of_customer` or `quote_bank` when a client signal is required.
  - Audit conclusion: this is the clearest place where `semantic_case` should become the preferred source, because the block currently recomposes one coherent case from multiple candidate fields.

- `РАЗБОР ЗВОНКА`
  - Current source: `report_evidence.manager_coaching_moments`.
  - Report Layer builds table rows from `what_happened`, dialogue fragment, and `what_better`.
  - It chooses one best call, then renders up to three moments from that call.
  - Quality gate filters missing/low-information fragments, stage mismatch, recommendation polarity mismatch, and duplicate problem/recommendation wording.
  - Audit conclusion: `semantic_case` should supply the main coherent call-breakdown moment; the existing call-breakdown quality gate should remain.

- `ГОЛОС КЛИЕНТА`
  - Current source: `report_evidence.voice_of_customer`, optionally enriched by `call_report_summary.manager_next_action`.
  - Report Layer filters to client/unknown speaker, high/medium business signal, deduplicates quotes, then derives manager action through `_voice_customer_manager_action(...)`.
  - Audit conclusion: `semantic_case.customer_signal` can improve the meaning and action, but the block must remain quote-first and evidence-grounded.

- `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`
  - Current source: `report_evidence.additional_situations`.
  - Report Layer normalizes positive/neutral wording, deduplicates titles/signals, and applies a quality gate for missing evidence, generic wording, duplicate signals, title/body mismatch, and low confidence.
  - Audit conclusion: `semantic_case` should not blindly replace all additional situations. It can seed the strongest additional card or help ranking, but the existing quality gate should remain.

- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`
  - Current selection is deterministic from final call-list statuses: only `agreed`, `rescheduled`, and `open`.
  - `report_evidence.follow_up_candidates` and `call_report_summary` enrich context, action, and phrase.
  - Hotness and inclusion remain deterministic.
  - Audit conclusion: `semantic_case.recommended_next_action`, `customer_signal`, and `why_this_call_matters` may enrich wording, but must not affect inclusion, final status, or hotness priority by themselves.

- Call list topic/context
  - Current source order: valid `call_report_summary.short_context`, then `short_topic`, then deterministic context fallback.
  - Context quality gate rejects weak, generic, technical, or empty wording.
  - Audit conclusion: `semantic_case` can provide a better semantic context source, but the current context quality gate should remain.

Heuristics that should remain as deterministic quality gates:

- report-day scope and `coaching_core` selection;
- final `BusinessOutcomeResolver` status;
- final sales-like outcome filter for coaching blocks;
- daily focus stage alignment;
- `usable_in_report`;
- `evidence_quality`;
- transcript-grounded quote/dialogue requirement;
- low-information fragment rejection;
- generic wording rejection;
- duplicate signal/title rejection;
- recommendation polarity check;
- call-list context quality gate;
- explicit legacy fallback when semantic evidence is absent or invalid.

Heuristics that should stop being primary meaning-builders once valid `semantic_case` exists:

- constructing `СИТУАЦИЯ ДНЯ` meaning from separate `situation_candidates` fields;
- constructing `РАЗБОР ЗВОНКА` as unrelated rows from multiple `manager_coaching_moments` when one coherent case exists;
- deriving manager action mainly from deterministic customer-signal profiles when LLM2 provided a grounded, specific action;
- using generic stage/problem fallbacks as manager-facing semantic explanation when a valid semantic case exists;
- treating `call_report_summary` as the richest semantic source for report blocks when `semantic_case` is available.

Implementation implication:

The next implementation step should not remove existing fields. It should add optional `report_evidence.semantic_case`, validate it, expose diagnostics, and then adjust source preference block by block:

```text
valid report_evidence.semantic_case
-> existing valid report_evidence v1 candidates
-> legacy fallback
```

The initial integration points are:

- `_build_report_evidence_index(...)` for validation/diagnostics;
- `_build_report_evidence_situation(...)` for `СИТУАЦИЯ ДНЯ`;
- `_build_call_breakdown_from_report_evidence(...)` for `РАЗБОР ЗВОНКА`;
- `_build_voice_of_customer_from_report_evidence(...)` for `ГОЛОС КЛИЕНТА`;
- `_build_call_tomorrow(...)` for wording enrichment only;
- `_build_daily_call_row(...)` for call-list context enrichment only;
- existing call-breakdown, additional-situations, and call-list quality gates for final safety.

### Step 2 — Contract Update

Status: `[x] completed`

Update the report evidence contract to define the new semantic-analysis responsibility.

Files expected:

- `docs/REPORT_EVIDENCE_CONTRACT.md`
- `docs/PROMPTS_GUIDE.md`
- possibly `docs/MANAGER_DAILY_SELECTION_MODEL.md`

Acceptance criteria:

- Contract says LLM2 must produce meaningful per-call analysis, not only candidate material.
- `semantic_case` is documented as additive and optional for backward compatibility.
- Reporting authority boundaries remain explicit.

Step 2 notes completed on 2026-05-12:

- Updated `docs/REPORT_EVIDENCE_CONTRACT.md`.
- Updated `docs/PROMPTS_GUIDE.md`.
- Updated `docs/MANAGER_DAILY_SELECTION_MODEL.md`.

Contract decisions:

- `report_evidence.semantic_case` is now documented as the preferred coherent per-call semantic analysis object.
- `semantic_case` remains additive and optional for backward compatibility.
- Fresh business-meaningful LLM2 runs should produce `semantic_case` after the prompt update is implemented.
- Step 3 now makes current runtime validation accept optional production output containing `semantic_case`.
- Existing `report_evidence v1` arrays remain valid fallback/subview material.
- Source preference is documented as:

```text
valid report_evidence.semantic_case
-> existing valid report_evidence v1 candidates
-> Step 8W legacy fallback
```

Authority boundaries remain unchanged:

- `BusinessOutcomeResolver` remains final for manager-facing status.
- Report Layer remains final for report-day scope, call inclusion/exclusion, `coaching_core`, `data_scope`, hotness priority, ranking, quality gates, and rendering.
- LLM2 must not write final report blocks; it analyzes one call.

### Step 3 — Schema And Validator

Status: `[x] completed`

Add schema and validation for `semantic_case`.

Files expected:

- `core/app/agents/calls/report_evidence.py`
- related tests if present or needed

Validation requirements:

- Reject unknown enum values.
- Require non-generic semantic fields when `usable_in_report=true`.
- Require direct or indirect evidence for strong manager-facing conclusions.
- Mark weak/insufficient cases as unusable or warn clearly.
- Add diagnostics for availability, validity, and filtered reasons.

Step 3 notes completed on 2026-05-12:

- Updated `core/app/agents/calls/report_evidence.py`.
- Updated mirrored validation tests:
  - `tests/test_manual_reporting.py`
  - `core/tests/test_manual_reporting.py`
- Updated `docs/REPORT_EVIDENCE_CONTRACT.md` validator notes.

Implemented schema:

- Added `SemanticCaseType`.
- Added optional `ReportEvidence.semantic_case`.
- Added `SemanticCase` model with:
  - `case_title`
  - `case_type`
  - `stage_code`
  - `priority`
  - `evidence_quality`
  - `core_meaning`
  - `why_this_call_matters`
  - `customer_signal`
  - `manager_behavior`
  - `coaching_diagnosis`
  - `recommended_next_action`
  - `best_dialogue_fragment`
  - `usable_in_report`

Implemented validation:

- invalid `semantic_case.case_type` fails schema validation;
- invalid `semantic_case.stage_code` fails with `invalid_stage_code`;
- `evidence_quality=insufficient` with `usable_in_report=true` fails;
- `case_type=insufficient_evidence` with `usable_in_report=true` fails;
- usable direct/indirect semantic cases require `best_dialogue_fragment`;
- `best_dialogue_fragment[].text` must be transcript-grounded;
- usable semantic fields must be non-empty and non-generic;
- duplicated semantic fields emit a warning.

Scope note:

- Step 3 adds validator diagnostics through existing `errors` / `warnings` issue codes.
- Report payload fields such as `semantic_case_available`, `semantic_case_valid`, `semantic_case_used`, and block-level filtered reasons remain Step 6, after prompt and source-preference wiring exist.

Verification:

```text
docker compose exec -T api python -m py_compile app/agents/calls/report_evidence.py
docker compose exec -T api pytest tests/test_manual_reporting.py::ReportEvidenceValidationTests -q
```

Result:

```text
24 passed
```

Full `tests/test_manual_reporting.py` was also checked. It currently has 6 manager_daily expectation failures outside the validator suite; they were not changed in this step. The new semantic-case validation tests pass.

### Step 4 — LLM2 Prompt Update

Status: `[x] completed`

Update the single runtime LLM2 analysis prompt.

File expected:

- `core/app/agents/calls/prompts/analyze.md`

Prompt requirements:

- LLM2 must produce a coherent semantic analysis for each business-meaningful call.
- LLM2 must not write final report blocks.
- LLM2 must not invent quotes, names, facts, or client intent.
- LLM2 must use transcript-grounded evidence.
- LLM2 must set `usable_in_report=false` when evidence is insufficient.
- LLM2 must still preserve the existing MVP-1 call analysis contract.

Step 4 notes completed on 2026-05-12:

Purpose:

- This task was implemented so fresh LLM2 analyses start producing the new high-quality semantic meaning layer.
- The goal is to move LLM2 from fragment/candidate production toward coherent per-call analysis, while the Report Layer remains responsible for selection, validation, ranking, and rendering.

Updated files:

- `core/app/agents/calls/prompts/analyze.md`
- `core/app/agents/calls/analyzer.py`
- `tests/test_manual_reporting.py`
- `core/tests/test_manual_reporting.py`
- `tests/test_ai_provider_routing.py`
- `core/tests/test_ai_provider_routing.py`
- `docs/REPORT_EVIDENCE_CONTRACT.md`
- `docs/PROMPTS_GUIDE.md`

Implemented prompt changes:

- Added `semantic_case` to the additive `report_evidence` JSON shape.
- Added `semantic_case.case_type` enum to shared prompt rules.
- Added grounding rule for `semantic_case.best_dialogue_fragment[].text`.
- Added a dedicated `semantic_case` prompt section.
- Required fresh business-meaningful calls to return one coherent semantic case when enough transcript exists.
- Clarified that LLM2 must not write final report blocks such as `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, or `ГОЛОС КЛИЕНТА`.
- Required weak semantic cases to be explicit: `case_type=insufficient_evidence`, `evidence_quality=insufficient`, `best_dialogue_fragment=[]`, `usable_in_report=false`.
- Updated semantic-empty retry instruction to preserve and repair `report_evidence.semantic_case`.
- Updated `APPROVED_INSTRUCTION_VERSION` to `edo_sales_mvp1_call_analysis_v9_semantic_case`.

Verification:

```text
docker compose exec -T api pytest tests/test_manual_reporting.py::ReportEvidenceValidationTests -q
docker compose exec -T api pytest tests/test_ai_provider_routing.py::AIProviderRoutingTests::test_analyzer_prompt_context_includes_report_evidence_contract tests/test_ai_provider_routing.py::AIProviderRoutingTests::test_semantic_retry_instruction_preserves_report_evidence_minimum -q
docker compose exec -T api python -m py_compile app/agents/calls/analyzer.py
```

Result:

```text
24 passed
2 passed
py_compile passed
```

### Step 5 — Report Layer Preference

Status: `[x] completed`

Update report assembly so semantic analysis becomes the preferred source where appropriate.

Target source order:

```text
valid report_evidence.semantic_case
-> existing valid report_evidence v1 candidates
-> legacy fallback
```

Files expected:

- `core/app/agents/calls/reporting.py`
- report rendering or diagnostics files if needed

Acceptance criteria:

- Report Layer uses `semantic_case` to reduce meaning assembly from scattered fields.
- Report Layer still ranks/selects calls deterministically.
- Report Layer still applies existing quality gates.
- Old analyses without `semantic_case` still render correctly.

Implementation summary:

- Purpose: move Report Layer from meaning construction to meaning selection for the main coaching blocks.
- Goal: let LLM2 provide a coherent per-call semantic case, while Report Layer validates, ranks, aligns to the daily focus, and renders.
- Implemented valid `report_evidence.semantic_case` preference for `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, and `ГОЛОС КЛИЕНТА`.
- Kept legacy `report_evidence v1` candidates as fallback when `semantic_case` is absent, invalid, unusable, ungrounded, or not aligned to the focus stage.
- Preserved deterministic final status, report-day selection, `BusinessOutcomeResolver`, and existing quality gates.
- Added focused payload coverage for semantic-case preference and preserved legacy report-evidence behavior.
- Updated `docs/REPORT_EVIDENCE_CONTRACT.md` and `docs/MANAGER_DAILY_SELECTION_MODEL.md` with the implemented source policy.

Verification:

- `docker compose exec -T api python -m py_compile app/agents/calls/reporting.py app/agents/calls/report_evidence.py app/agents/calls/analyzer.py`
- `docker compose exec -T api pytest tests/test_manual_reporting.py::ReportEvidenceValidationTests -q` — 24 passed
- `docker compose exec -T api pytest tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_prefers_valid_report_evidence_for_report_blocks tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_prefers_semantic_case_for_core_coaching_blocks tests/test_manual_reporting.py::ManualReportingPayloadTests::test_call_breakdown_prefers_report_evidence_moment_with_fragment -q` — 3 passed
- `docker compose exec -T api ruff check app/agents/calls/reporting.py app/agents/calls/report_evidence.py app/agents/calls/analyzer.py` — passed

### Step 6 — Diagnostics

Status: `[x] completed`

Expose semantic-case usage in payload diagnostics.

Required diagnostic fields:

- `semantic_case_available`
- `semantic_case_valid`
- `semantic_case_used`
- `semantic_case_filtered_reason`
- `report_evidence_source`

Target source values:

```text
semantic_case
report_evidence_v1
legacy_fallback
```

Acceptance criteria:

- It is clear why a call/block used or rejected `semantic_case`.
- Old vs new report comparison can be audited without reading code.

Implementation summary:

- Purpose: make semantic-case adoption auditable before running the 2026-05-08 comparison.
- Goal: show whether each call had `semantic_case`, whether it was valid, whether it was used in final report blocks, and which source each block used.
- Added per-call diagnostics in `payload.report_evidence_diagnostics.calls[]`: `semantic_case_available`, `semantic_case_valid`, `semantic_case_used`, `semantic_case_filtered_reason`, and normalized `report_evidence_source`.
- Added block-level diagnostics in `payload.report_evidence_diagnostics.blocks`: `situation_day`, `call_breakdown`, `voice_of_customer`, `additional_situations`, and `call_tomorrow`.
- Added summary counts for semantic availability, validity, usage, filtering, and source distribution.
- Standardized source values to `semantic_case`, `report_evidence_v1`, and `legacy_fallback`.
- Kept old report behavior unchanged; diagnostics are observational except for adding stable call ids to existing rendered source rows.

Verification:

- `docker compose exec -T api python -m py_compile app/agents/calls/reporting.py app/agents/calls/report_evidence.py app/agents/calls/analyzer.py`
- `docker compose exec -T api pytest tests/test_manual_reporting.py::ReportEvidenceValidationTests -q` — 24 passed
- `docker compose exec -T api pytest tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_prefers_valid_report_evidence_for_report_blocks tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_prefers_semantic_case_for_core_coaching_blocks tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_invalid_report_evidence_uses_step8w_fallback -q` — 3 passed
- `docker compose exec -T api pytest tests/test_manual_reporting.py::ManualReportingPayloadTests::test_call_breakdown_prefers_report_evidence_moment_with_fragment -q` — 1 passed
- `docker compose exec -T api ruff check app/agents/calls/reporting.py app/agents/calls/report_evidence.py app/agents/calls/analyzer.py` — passed

### Step 7 — Full Pilot For Tolegen On 2026-05-08

Status: `[x] completed`

Run a representative full-day pilot for one manager: Толеген Жангазиев, 2026-05-08.

Updated scope approved by user:

- select all persisted calls for Толеген Жангазиев on 2026-05-08;
- rerun current LLM analysis for calls with transcripts using `edo_sales_mvp1_call_analysis_v9_semantic_case`;
- keep no-transcript/no-speech calls visible in report-day selection diagnostics;
- build `manager_daily` with the updated semantic-case Report Layer;
- generate a visible review package with semantic-case diagnostics and report artifacts;
- send the generated report to the configured Telegram test chat when delivery configuration allows.

Acceptance criteria:

- All transcript-bearing eligible calls are attempted with the current LLM1/LLM2 analyzer path.
- New prompt outputs validate or failed/skipped calls are listed with concrete reasons.
- `payload.report_evidence_diagnostics` shows semantic-case availability, validity, usage, and block sources.
- Final statuses are not overridden by LLM2 semantics.
- Weak/no-transcript/service/not-suitable calls do not become normal sales coaching material.
- Generated report artifact is sent to Telegram or the delivery blocker is recorded.

Implementation summary:

- Purpose: validate the new semantic-case mechanism on a representative real manager-day before broader rollout.
- Goal: produce a visible business artifact, not only test output, showing whether LLM2 semantic cases survive validator/report selection and improve final report blocks.
- Target manager/day: Толеген Жангазиев, 2026-05-08.
- Found 32 report-day calls; 17 had transcripts and were rerun through current LLM1+LLM2 with `edo_sales_mvp1_call_analysis_v9_semantic_case`; 15 no-transcript/no-speech calls were not sent to LLM2 and stayed visible in selection diagnostics.
- Direct LLM rerun result: 10 successful new analyses, 7 semantic/not-coachable failures, 7 valid semantic cases, 13 valid `report_evidence` packages.
- Final `manager_daily` diagnostics: 17 calls checked, 13 valid report-evidence packages, 6 valid semantic cases in final report diagnostics, 3 final blocks used semantic case.
- Core block sources: `situation_day=semantic_case`, `call_breakdown=semantic_case`, `voice_of_customer=semantic_case`, `additional_situations=legacy_fallback`, `call_tomorrow=report_evidence_v1`.
- Telegram delivery succeeded to configured test chat: `status=delivered`, `message_id=201`.
- Review package created at `review_packages/semantic_case_2026-05-08_tolegen/`.
- Artifact correction after user review: the initial `report_preview.txt` was the Python runtime text preview and did not match the DOCX-first PDF. The review package was corrected so `report_preview.txt` is now extracted from the actual PDF; the previous text preview is preserved as `runtime_text_preview.txt`.

Artifacts:

- `review_packages/semantic_case_2026-05-08_tolegen/smoke_result.md`
- `review_packages/semantic_case_2026-05-08_tolegen/llm2_rerun.json`
- `review_packages/semantic_case_2026-05-08_tolegen/report_run.json`
- `review_packages/semantic_case_2026-05-08_tolegen/semantic_cases.json`
- `review_packages/semantic_case_2026-05-08_tolegen/report_preview.txt` — text extracted from the generated PDF
- `review_packages/semantic_case_2026-05-08_tolegen/pdf_text_extracted.txt` — verification copy of the extracted PDF text
- `review_packages/semantic_case_2026-05-08_tolegen/runtime_text_preview.txt` — previous Python runtime text preview kept for diagnostics
- `review_packages/semantic_case_2026-05-08_tolegen/report_preview.html`
- `review_packages/semantic_case_2026-05-08_tolegen/manager_daily_d42e8246-772e-4a04-bbe7-2b88f45db695_2026-05-08_manager_daily_template_v2.pdf`

Findings:

- The semantic-case path is working end-to-end for the main report blocks.
- The final report was delivered, but the overall run is `partial` because no-transcript calls and not-coachable calls remain visible as missing analysis/non-ready rows.
- Review-package packaging issue fixed: text preview now reflects the delivered PDF renderer, not the alternate runtime text renderer.
- Remaining LLM2 quality risk: some successful outputs still fail report-evidence validation with `semantic_case_generic_field` or `ungrounded_evidence_text`.
- Before all-manager rollout, tighten LLM2 semantic specificity/grounding and rerun comparison.

### Step 7A — Block-Specific Suitability Gates

Status: `[x] completed`

Implemented after user review of the Толеген pilot exposed that a technically valid `customer_signal` semantic case was incorrectly selected as `СИТУАЦИЯ ДНЯ`.

Purpose:

- Prevent valid semantic cases from being reused in blocks where they do not fit.
- Keep LLM2 responsible for per-call meaning, while making Report Layer select only block-suitable cases.
- Make rejected candidates explainable without turning Report Layer into an LLM.

Implemented changes:

- Added optional `semantic_case.report_block_fit` to the report-evidence schema.
- `report_block_fit` covers `situation_day`, `call_breakdown`, `voice_of_customer`, `additional_situations`, and `call_tomorrow`.
- Each block fit item contains `fit`, `score`, `reason_code`, and `evidence_type`.
- Bumped fresh analyzer instruction version to `edo_sales_mvp1_call_analysis_v10_block_fit`.
- Updated the LLM2 prompt to require block-fit suitability for fresh usable semantic cases.
- Added Report Layer block-specific gates:
  - `СИТУАЦИЯ ДНЯ` requires a manager gap / missed opportunity and rejects pure customer-signal or positive-diagnosis cases.
  - `РАЗБОР ЗВОНКА` requires a coachable manager moment or strong manager practice with grounded manager evidence.
  - `ГОЛОС КЛИЕНТА` requires a grounded customer/unknown speaker signal.
- Added diagnostics for selected/rejected semantic candidates inside `payload.report_evidence_diagnostics.blocks[*].selection_diagnostics`.

Verification:

- `docker compose exec -T api python -m py_compile app/agents/calls/report_evidence.py app/agents/calls/reporting.py app/agents/calls/analyzer.py` — passed.
- `docker compose exec -T api pytest tests/test_manual_reporting.py::ReportEvidenceValidationTests tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_prefers_semantic_case_for_core_coaching_blocks tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_block_fit_rejects_customer_signal_as_problem_situation -q` — 28 passed.
- `docker compose exec -T api sh -lc 'PYTHONPATH=/app pytest tests/test_ai_provider_routing.py::AIProviderRoutingTests::test_analyzer_prompt_context_includes_report_evidence_contract tests/test_ai_provider_routing.py::AIProviderRoutingTests::test_semantic_retry_instruction_preserves_report_evidence_minimum -q'` — 2 passed.

### Step 7B — Block-Fit Rerun For Tolegen On 2026-05-08

Status: `[x] completed`

Run the corrected v10 block-fit mechanism on the same representative manager/day after user review found that the invoice request call was a weak `СИТУАЦИЯ ДНЯ` case.

Purpose:

- Verify that `semantic_case.report_block_fit` prevents customer-signal-only calls from being selected as problem/coaching cases.
- Confirm that Report Layer still keeps the same call in blocks where it belongs, for example `ГОЛОС КЛИЕНТА`.
- Generate a visible manager daily report and package where the PDF text preview matches the actual PDF.

Implementation summary:

- Target manager/day: Толеген Жангазиев, 2026-05-08.
- Instruction version: `edo_sales_mvp1_call_analysis_v10_block_fit`.
- Found 32 report-day calls; 17 had transcripts and were attempted; 15 were skipped as no-transcript/no-speech.
- LLM2 rerun: 10 successful analyses, 7 failed/not-coachable, 7 valid `report_evidence` packages, 6 valid semantic cases, 6 with `report_block_fit`.
- Final report diagnostics: 17 calls checked, 14 valid report-evidence packages, 3 invalid packages, 7 valid semantic cases available in persisted report diagnostics, 3 semantic cases used by final blocks.
- Core block sources: `situation_day=semantic_case`, `call_breakdown=semantic_case`, `voice_of_customer=semantic_case`, `additional_situations=legacy_fallback`, `call_tomorrow=report_evidence_v1`.
- Telegram delivery succeeded to configured test chat: `status=delivered`, `message_id=202`.

Key result:

- Before the block-fit fix, the report selected `+77787774860 · 8 мая 2026, 11:17` with the invoice quote `Оба счета скиньте...` as `СИТУАЦИЯ ДНЯ`.
- After the fix, `СИТУАЦИЯ ДНЯ` selects `+77051859385 · 8 мая 2026, 09:26`, case `Запланирована демонстрация системы`, with `fit=true`, `reason_code=manager_gap_with_direct_evidence`, `evidence_type=manager_gap`.
- The invoice request call is explicitly rejected for `СИТУАЦИЯ ДНЯ` with `rejection_reason=customer_signal_without_manager_gap`.
- The same invoice request remains in `ГОЛОС КЛИЕНТА`, where it is the right type of evidence.
- `РАЗБОР ЗВОНКА` also selects `+77051859385 · 8 мая 2026, 09:26`; the invoice request call is rejected there with `manager_fragment_missing`.

Artifacts:

- `review_packages/block_fit_2026-05-08_tolegen/smoke_result.md`
- `review_packages/block_fit_2026-05-08_tolegen/llm2_rerun.json`
- `review_packages/block_fit_2026-05-08_tolegen/report_run_clean.json`
- `review_packages/block_fit_2026-05-08_tolegen/semantic_cases.json`
- `review_packages/block_fit_2026-05-08_tolegen/report_preview.txt` — text extracted from the generated PDF
- `review_packages/block_fit_2026-05-08_tolegen/report_preview_runtime.txt` — runtime text preview kept for diagnostics only
- `review_packages/block_fit_2026-05-08_tolegen/report_preview.html`
- `review_packages/block_fit_2026-05-08_tolegen/manager_daily_d42e8246-772e-4a04-bbe7-2b88f45db695_2026-05-08_manager_daily_template_v2.pdf`

Findings:

- The original weak case is now blocked from `СИТУАЦИЯ ДНЯ` by the new block-fit mechanism.
- PDF verification passed: `report_preview.txt` is extracted from the generated PDF and shows the corrected selected case.
- Remaining LLM2 quality risk: three v10 outputs were invalid because of `semantic_case_generic_field` or `ungrounded_evidence_text`.
- Remaining block coverage gap: `additional_situations` and `call_tomorrow` still rely mainly on legacy/report_evidence_v1 sources; block-fit exists but is not yet fully used for those blocks.

### Step 7C — Role And Problem-Fit Gates Across Blocks

Status: `[x] completed`

Implemented after analysis of the corrected `СИТУАЦИЯ ДНЯ` showed that block fit alone was too broad: the selected call fit the stage and block, but the problem wording drifted from the daily focus.

Purpose:

- Make problem-oriented blocks prove what went wrong, not just show an interesting call.
- Let neutral/action blocks show the situation as-is without inventing a manager problem.
- Prevent the same failure mode from appearing in `РАЗБОР ЗВОНКА`, `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`, `ГОЛОС КЛИЕНТА`, and `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`.

Implemented changes:

- Added optional fields to every `report_block_fit` item:
  - `block_role`: `coaching_problem`, `customer_signal`, `follow_up_action`, `neutral_summary`, `strong_practice`;
  - `title_mode`: `problem`, `neutral`, `positive`;
  - `problem_fit`: `score`, `problem_signal`, `explanation`;
  - `evidence_target`;
  - `gap_proven`.
- Bumped fresh analyzer instruction version to `edo_sales_mvp1_call_analysis_v11_role_problem_fit`.
- Updated LLM2 prompt rules:
  - problem blocks require a problem title and proved manager gap;
  - customer/follow-up blocks do not require a manager gap;
  - `problem_fit` describes the per-call problem so Report Layer can compare it to the daily focus.
- Added Report Layer gates:
  - `СИТУАЦИЯ ДНЯ` rejects non-problem roles, neutral/positive titles, unproven gaps, weak problem fit, and problem-signal mismatch with the daily focus;
  - main `РАЗБОР ЗВОНКА` applies the same role/problem alignment for problem breakdowns;
  - `ГОЛОС КЛИЕНТА` accepts customer-signal role without forcing a manager gap;
  - `additional_situations` and `call_tomorrow` now have explicit role checks for future semantic usage.
- Added a problem-fragment evidence gate: problem-oriented blocks reject manager fragments with too little information, so a phrase like `Это же Татьяна, да?` cannot prove a manager gap.
- Diagnostics now expose `block_role`, `title_mode`, `problem_fit_score`, `problem_fit_signal`, `evidence_target`, and `gap_proven` for selected/rejected candidates.

Verification:

- `docker compose exec -T api python -m py_compile app/agents/calls/report_evidence.py app/agents/calls/reporting.py app/agents/calls/analyzer.py` — passed.
- `docker compose exec -T api pytest tests/test_manual_reporting.py::ReportEvidenceValidationTests tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_prefers_semantic_case_for_core_coaching_blocks tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_situation_day_rejects_problem_signal_mismatch tests/test_manual_reporting.py::ManualReportingPayloadTests::test_manager_daily_block_fit_rejects_customer_signal_as_problem_situation -q` — 31 passed.
- `docker compose exec -T api sh -lc 'PYTHONPATH=/app pytest tests/test_ai_provider_routing.py::AIProviderRoutingTests::test_analyzer_prompt_context_includes_report_evidence_contract tests/test_ai_provider_routing.py::AIProviderRoutingTests::test_semantic_retry_instruction_preserves_report_evidence_minimum -q'` — 2 passed.
- `docker compose exec -T api ruff check app/agents/calls/report_evidence.py app/agents/calls/reporting.py app/agents/calls/analyzer.py` — passed.

Rerun summary:

- Target manager/day: Толеген Жангазиев, 2026-05-08.
- Instruction version: `edo_sales_mvp1_call_analysis_v11_role_problem_fit`.
- Found 32 report-day calls; 17 had transcripts and were attempted; 15 were skipped as no-transcript/no-speech.
- LLM2 rerun: 10 successful analyses, 7 failed/not-coachable, 8 valid `report_evidence` packages, 7 valid semantic cases, 9 with `report_block_fit`.
- Telegram delivery succeeded to configured test chat: `status=delivered`, final `message_id=204`.
- v10 selected `+77051859385 · 09:26` for `СИТУАЦИЯ ДНЯ`; v11 rejected it with `problem_fragment_low_information` because the selected manager fragment was too weak.
- v11 selected `+77471109896 · 05:55` for both `СИТУАЦИЯ ДНЯ` and `РАЗБОР ЗВОНКА`: `Не уточнены детали текущего процесса и роль собеседника`.
- The invoice request remains outside `СИТУАЦИЯ ДНЯ` and appears in `ГОЛОС КЛИЕНТА`.
- A final no-delivery rebuild refreshed `report_run_clean.json` so diagnostics use source policy `valid_semantic_case_with_role_problem_fit_else_report_evidence_v1_else_step8w_fallback`.

Artifacts:

- `review_packages/role_problem_fit_2026-05-08_tolegen/smoke_result.md`
- `review_packages/role_problem_fit_2026-05-08_tolegen/llm2_rerun.json`
- `review_packages/role_problem_fit_2026-05-08_tolegen/report_run_clean.json`
- `review_packages/role_problem_fit_2026-05-08_tolegen/semantic_cases.json`
- `review_packages/role_problem_fit_2026-05-08_tolegen/report_preview.txt` — text extracted from the generated PDF
- `review_packages/role_problem_fit_2026-05-08_tolegen/report_preview_runtime.txt` — runtime text preview kept for diagnostics only
- `review_packages/role_problem_fit_2026-05-08_tolegen/report_preview.html`
- `review_packages/role_problem_fit_2026-05-08_tolegen/manager_daily_d42e8246-772e-4a04-bbe7-2b88f45db695_2026-05-08_manager_daily_template_v2.pdf`

### Step 8 — Full LLM2 Reanalysis For 2026-05-08

Status: `[ ] not started`

Note: the approved immediate scope was narrowed to Толеген on 2026-05-08 and completed in Step 7B. This all-manager/full-day comparison remains a separate rollout decision.

Run new LLM2 analysis for all calls on 2026-05-08 as a separate version/run.

Requirements:

- Do not overwrite existing production analyses.
- Use a new `instruction_version`.
- Use a distinct run label.
- Keep ability to generate old and new reports for comparison.

Acceptance criteria:

- All eligible 2026-05-08 calls have new LLM2 analyses.
- Failed/skipped calls are listed with reasons.
- The run is reproducible.

### Step 7E — Fresh v12 LLM2 Reanalysis For Tolegen On 2026-05-08

Status: `[x] completed`

Purpose:

- Run fresh LLM2 on the representative manager/day after the coaching-moment contract was introduced.
- Check whether LLM2 now returns report-facing semantic meaning for each usable call, not only fragments/quotes.
- Capture validation failures separately from successful contract generation, so Report Layer issues can be diagnosed before rebuilding the PDF.

Run summary:

- Target manager/day: Толеген Жангазиев, 2026-05-08.
- Instruction version: `edo_sales_mvp1_call_analysis_v12_coaching_moment`.
- Found 32 report-day calls.
- 17 calls had transcripts and were attempted.
- 15 calls were skipped as `skipped_without_transcript`.
- 9 calls produced successful LLM2 analyses.
- 8 calls were marked `not_coachable_or_reportable`.
- 0 contract/provider/unknown failures.
- 9 successful analyses produced `semantic_case`.
- 9 semantic cases produced explicit `report_block_fit.*.coaching_moment`.
- 32 block-level coaching moments were returned; 28 had an allowed `coaching_moment.evidence_type`.
- 5 successful analyses passed full `report_evidence` validation.
- 4 successful analyses had validation errors.

Important findings:

- The core LLM2 behavior improved: fresh v12 does produce semantic, report-facing coaching moments per block.
- The remaining weakness is strict validation/normalization:
  - LLM2 sometimes used unsupported `coaching_moment.evidence_type` values such as `none` or `insufficient`;
  - in several cases LLM2 returned supporting quotes that did not exactly match the transcript substring;
  - those invalid packages fall back to older/legacy report evidence in the deterministic report path.
- A standard report rebuild has not yet been sent for this v12 rerun. If run without an instruction-version guard, the existing Report Layer selection policy will use the newest reusable analysis; for calls where v12 is failed/not-coachable and an older successful analysis exists, it may select the older analysis. For a clean v12-only comparison, the report runner should either receive an instruction-version filter or the comparison package should explicitly isolate v12 analyses.

Artifacts:

- `review_packages/coaching_moment_v12_full_rerun_tolegen_2026-05-08/llm2_rerun.json`
- `review_packages/coaching_moment_v12_full_rerun_tolegen_2026-05-08/block_fit_diagnostics.json`
- `review_packages/coaching_moment_v12_full_rerun_tolegen_2026-05-08/semantic_cases.json`

### Step 7F — Systemic Coaching-Moment Evidence Guard And v13 Rerun

Status: `[x] completed`

Purpose:

- Turn the previous "fragment-first" report block input into a systemic `coaching_moment` mechanism for all coaching blocks.
- Make LLM2 explicitly rate whether each call can be used in each report block and return the essence of the moment, with quote evidence only when it is available and useful.
- Prevent weak or unsupported moment evidence from either breaking validation or leaking into the report as a forced fragment.
- Ensure the comparison report can be built strictly from the new LLM2 instruction version, without accidentally falling back to older analyses.

Systemic changes implemented:

- LLM2 prompt/contract now require block-specific `report_block_fit.*.coaching_moment` with `moment_summary`, `what_to_improve`, `evidence_type`, and optional `supporting_quote`.
- `APPROVED_INSTRUCTION_VERSION` was bumped to `edo_sales_mvp1_call_analysis_v13_cm_evidence`.
- Important implementation note: the first v13 label was too long for the DB `instruction_version` column (`VARCHAR(50)`), so it was shortened to the 44-character production-safe version above.
- `report_evidence` validation now normalizes block-level `coaching_moment`:
  - drops moments when `fit=false`;
  - converts unsupported non-direct evidence markers such as `none`/`insufficient` into report-safe non-quote evidence types when the semantic moment is still useful;
  - removes ungrounded `supporting_quote` for non-direct evidence;
  - keeps strict grounding for `direct_quote`.
- Manual reporting runner now supports `--analysis-instruction-version`, and the reuse policy rejects older analyses when this guard is set.

Verification:

- Focused tests passed:

```text
41 passed in 0.94s
```

- Covered:
  - coaching-moment normalization;
  - instruction-version guarded report reuse;
  - analyzer prompt/version routing;
  - existing manual-reporting semantic-case and block-fit behavior.

Fresh v13 LLM2 rerun summary:

- Target manager/day: Толеген Жангазиев, 2026-05-08.
- Instruction version: `edo_sales_mvp1_call_analysis_v13_cm_evidence`.
- Found 32 report-day calls.
- 17 calls had transcripts and were attempted.
- 15 calls were skipped as `skipped_without_transcript`.
- 11 calls produced successful LLM2 analyses.
- 6 calls were marked `not_coachable_or_reportable`.
- 0 contract/provider/unknown failures.
- 11 successful analyses passed full `report_evidence` validation.
- 0 successful analyses had validation errors.
- 11 successful analyses produced `semantic_case`.
- 11 semantic cases produced explicit `report_block_fit.*.coaching_moment`.
- 24 block-level coaching moments were returned and all 24 were usable after validation/normalization.

Guarded report rebuild:

- Report runner used `--analysis-instruction-version edo_sales_mvp1_call_analysis_v13_cm_evidence`.
- `prepared_artifacts.analyses_reused`: 11.
- `prepared_artifacts.analyses_rejected_for_reuse`: 27.
- `prepared_artifacts.analyses_rejected_for_instruction_version`: 21.
- Final report payload source artifacts: 10 interactions / 10 analyses, instruction version only `edo_sales_mvp1_call_analysis_v13_cm_evidence`.
- Report status is `ready`; runner status is `partial` because source discovery had a non-blocking OnlinePBX/auth timeout and older analyses were intentionally rejected by the version guard.
- The report was delivered to Telegram target `74665909`, message `213`, filename `tolegen_2026-05-08_v13_cm_evidence_guarded.pdf`.

Artifacts:

- `review_packages/coaching_moment_v13_guarded_tolegen_2026-05-08/llm2_rerun.json`
- `review_packages/coaching_moment_v13_guarded_tolegen_2026-05-08/report_run_clean.json`
- `review_packages/coaching_moment_v13_guarded_tolegen_2026-05-08/report_preview.txt`
- `review_packages/coaching_moment_v13_guarded_tolegen_2026-05-08/report_preview.html`
- `review_packages/coaching_moment_v13_guarded_tolegen_2026-05-08/semantic_cases.json`
- `review_packages/coaching_moment_v13_guarded_tolegen_2026-05-08/block_fit_diagnostics.json`
- `review_packages/coaching_moment_v13_guarded_tolegen_2026-05-08/telegram_delivery.json`
- `review_packages/coaching_moment_v13_guarded_tolegen_2026-05-08/manager_daily_d42e8246-772e-4a04-bbe7-2b88f45db695_2026-05-08_manager_daily_template_v2.pdf`

Open quality note:

- The mechanical contract is now much cleaner than v12: 11/11 successful v13 analyses have valid `report_evidence`, and the guarded report does not mix in older instruction versions.
- The next review should be semantic: check whether selected cases in `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, and `ГОЛОС КЛИЕНТА` are strong enough for a manager-facing report.
- In the current preview, `СИТУАЦИЯ ДНЯ` uses the call `+77787774860 · 2026-05-08 12:16` with the moment "Менеджер не проверил уместность разговора"; this is a better fit than the previous weak invoice fragment mechanically, but still needs user review for business strength.

### Step 7G — v14 Proof Layer And Guarded Толеген Report

Status: `[x] completed`

Purpose:

- Prevent a problem block from using a quote that actually proves the opposite of the claimed manager gap.
- Make LLM2 state the exact proof basis for problem-oriented `coaching_moment` items.
- Keep Report Layer deterministic: it selects the best proven semantic case and renders the report, while invalid/counter-evidence material is ignored.

Systemic changes implemented:

- `APPROVED_INSTRUCTION_VERSION` was bumped to `edo_sales_mvp1_call_analysis_v14_proof_layer`.
- LLM2 prompt now requires `gap_claim`, `proof_type`, `proof_explanation`, `quote_role`, and `counter_evidence` for problem-oriented `situation_day` / `call_breakdown` moments.
- `report_evidence` validation rejects `situation_day` / problem `call_breakdown` when:
  - `counter_evidence` is present;
  - the selected quote is marked as counter-evidence;
  - `proof_type=context_support` is used as a proved manager gap;
  - the quote appears to show the allegedly missing role/convenience/next-step/process action.
- Report Layer applies the same proof guard before selecting semantic cases.
- Report Layer now has a safe semantic fallback: it first prefers the daily focus stage, but if no valid semantic case matches that focus, it selects the best proven semantic case instead of falling back to a generic deterministic block.
- When that semantic fallback is used, downstream `daily_coaching_focus`, `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, and `ЧЕЛЛЕНДЖ` are aligned to the selected semantic case.
- Renderer hides duplicated situation text and filters instruction-like recommendations out of manager phrase examples.

Verification:

- Focused regression suite passed: `44 passed in 0.89s`.
- `python -m py_compile` passed for analyzer/reporting/report-evidence/runner.
- `node --check scripts/generate_docx_report.js` passed.
- `git diff --check` passed.

Fresh v14 LLM2 rerun summary:

- Target manager/day: Толеген Жангазиев, 2026-05-08.
- Instruction version: `edo_sales_mvp1_call_analysis_v14_proof_layer`.
- Found 32 report-day calls.
- 17 calls had transcripts and were attempted.
- 15 calls were skipped as `skipped_without_transcript`.
- 10 calls produced successful LLM2 analyses.
- 7 calls were marked `not_coachable_or_reportable`.
- 0 contract/provider/unknown failures.
- 8 successful analyses passed full `report_evidence` validation.
- 2 successful analyses had invalid `report_evidence` and were excluded from preferred report-evidence usage:
  - one generic `semantic_case.coaching_diagnosis`;
  - one ungrounded `business_outcome.evidence_quote` / `call_tomorrow.coaching_moment.supporting_quote`.
- 9 analyses produced `semantic_case`.
- 20 block-level coaching moments were returned.

Guarded report rebuild:

- Report runner used `--analysis-instruction-version edo_sales_mvp1_call_analysis_v14_proof_layer`.
- `prepared_artifacts.analyses_reused`: 10.
- `prepared_artifacts.analyses_rejected_for_reuse`: 28.
- `prepared_artifacts.analyses_rejected_for_instruction_version`: 21.
- Final report status is `ready`; runner status is `partial` because older/missing analyses were intentionally excluded by the version guard.
- `manager_facing_completeness.status`: `passed`.
- `report_evidence_diagnostics.summary`: 17 checked, 15 valid, 2 invalid, 7 valid semantic cases, 4 semantic cases used in final blocks.
- `СИТУАЦИЯ ДНЯ` and `РАЗБОР ЗВОНКА` now use semantic case `Жанна · +77771896548 · 8 мая 2026, 05:46`, stage `Квалификация и первичная потребность`, case `Не зафиксирована конкретная задача клиента перед предложением`.
- `ЧЕЛЛЕНДЖ` is aligned to the same selected semantic focus.
- Report delivered to Telegram target `74665909`, message `215`, filename `tolegen_2026-05-08_v14_proof_layer.pdf`.

Artifacts:

- `review_packages/coaching_moment_v14_proof_tolegen_2026-05-08/llm2_rerun.json`
- `review_packages/coaching_moment_v14_proof_tolegen_2026-05-08/report_run_clean.json`
- `review_packages/coaching_moment_v14_proof_tolegen_2026-05-08/report_preview.txt`
- `review_packages/coaching_moment_v14_proof_tolegen_2026-05-08/report_preview.html`
- `review_packages/coaching_moment_v14_proof_tolegen_2026-05-08/semantic_cases.json`
- `review_packages/coaching_moment_v14_proof_tolegen_2026-05-08/block_fit_diagnostics.json`
- `review_packages/coaching_moment_v14_proof_tolegen_2026-05-08/telegram_delivery.json`
- `review_packages/coaching_moment_v14_proof_tolegen_2026-05-08/manager_daily_d42e8246-772e-4a04-bbe7-2b88f45db695_2026-05-08_manager_daily_template_v2.pdf`

### Step 9 — Old Vs New Report Generation

Status: `[ ] not started`

Generate comparison outputs for each manager for 2026-05-08.

Outputs:

- old report using current analysis/path
- new report using semantic-case analysis/path
- text extraction of key blocks
- JSON payload diagnostics

Acceptance criteria:

- Differences can be reviewed block by block.
- Report statuses and call inclusion can be checked.
- Diagnostics identify source selection.

### Step 10 — Quality Comparison Package

Status: `[ ] not started`

Create a review package for the experiment.

Target path:

```text
review_packages/semantic_case_2026-05-08/
```

Expected contents:

```text
audit_notes.md
contract_diff.md
smoke_run_notes.md
old_reports/
new_reports/
comparison_matrix.md
summary_2026-05-08.json
```

Comparison criteria:

- Is the selected call more meaningful?
- Is `СИТУАЦИЯ ДНЯ` more specific and less generic?
- Does `РАЗБОР ЗВОНКА` explain the actual manager/client moment?
- Is `ГОЛОС КЛИЕНТА` tied to a real customer signal?
- Are recommendations more actionable?
- Is transcript evidence present and relevant?
- Did final statuses remain correct?
- Did weak/not-suitable calls stay out of coaching?
- Is the reason for selecting each call transparent?

## 5. Rollout Decision

After the 2026-05-08 comparison, choose one:

- `[ ]` Enable `semantic_case` as preferred source in normal reports.
- `[ ]` Keep experimental and improve prompt/validator.
- `[ ]` Reject the approach and keep current `report_evidence v1` path.

## 6. Progress Log

- 2026-05-12 — Initial tracking plan created.
- 2026-05-12 — Step 1 targeted audit completed. Report Layer meaning-assembly points and preserved quality gates documented.
- 2026-05-12 — Step 2 contract update completed. `semantic_case` target and LLM2/Report Layer responsibility boundary documented.
- 2026-05-12 — Step 3 schema and validator completed. Optional `semantic_case` schema, semantic validation rules, and focused tests added.
- 2026-05-12 — Step 4 LLM2 prompt update completed. Runtime prompt now requests coherent `report_evidence.semantic_case`; instruction version bumped to v9.
- 2026-05-12 — Step 5 Report Layer preference completed. Core coaching blocks now prefer valid `semantic_case`; legacy report-evidence candidates remain fallback.
- 2026-05-12 — Step 6 diagnostics completed. Payload now exposes per-call semantic-case availability/validity/usage/filter reasons and block-level source selection.
- 2026-05-12 — Step 7 full Толеген pilot completed. LLM2 rerun, manager_daily rebuild, Telegram delivery, and review package were produced for 2026-05-08.
- 2026-05-12 — Step 7 review-package artifact corrected. `report_preview.txt` now matches text extracted from the generated PDF; the older runtime text preview is preserved separately.
- 2026-05-12 — Step 7A block-specific suitability gates completed. LLM2 now has `report_block_fit`; Report Layer rejects valid semantic cases that do not fit the target block.
- 2026-05-12 — Step 7B block-fit Толеген rerun completed. v10 LLM2 rerun, manager_daily rebuild, Telegram delivery, PDF-matched preview, semantic-cases export, and smoke comparison package were produced.
- 2026-05-12 — Step 7C role/problem-fit gates completed. v11 LLM2 rerun, manager_daily rebuild, Telegram delivery, PDF-matched preview, semantic-cases export, and smoke comparison package were produced.
- 2026-05-12 — Step 7C no-delivery refresh completed. `report_run_clean.json` was rebuilt with the final role/problem-fit source policy after Telegram delivery, without sending a second Telegram message.
- 2026-05-13 — Step 7D coaching-moment upgrade completed. `report_block_fit.*.coaching_moment` was added to the LLM2 contract/prompt, Report Layer now treats `moment_summary` as primary and quote as optional evidence, and the DOCX/PDF renderer now shows `Суть момента` plus optional `Подтверждение из звонка`.
- 2026-05-13 — Step 7D Толеген report smoke completed. Report was rebuilt for Толеген on 2026-05-08 with ready analyses and the updated Report Layer/renderer, delivered to Telegram message `211`, then resent with cache-safe filename in message `212`. Review package: `review_packages/coaching_moment_tolegen_2026-05-08/`.
- 2026-05-13 — Step 7D verification note: the smoke run did not perform a full fresh LLM2 v12 rerun of all calls; v12 is implemented for future LLM2 builds, while this report validates the new deterministic selection/rendering path on existing analyses.
- 2026-05-13 — Step 7E fresh v12 LLM2 rerun completed for Толеген on 2026-05-08. 32 calls found, 17 attempted with transcripts, 9 successful semantic analyses, 8 not-coachable, 15 skipped without transcript, 0 contract/provider failures. v12 produced `coaching_moment` in 9 semantic cases; remaining issue is validation/normalization for unsupported moment evidence types and ungrounded supporting quotes. Review package: `review_packages/coaching_moment_v12_full_rerun_tolegen_2026-05-08/`.
- 2026-05-13 — Step 7F systemic coaching-moment evidence guard completed through delegated implementation. v13 LLM2 prompt/contract, `report_evidence` normalization, and instruction-version guarded report reuse were implemented and tested. Fresh v13 rerun for Толеген on 2026-05-08 produced 11 successful analyses, 0 invalid `report_evidence`, 24 usable block-level coaching moments, and a guarded v13-only report delivered to Telegram message `213`. Review package: `review_packages/coaching_moment_v13_guarded_tolegen_2026-05-08/`.
