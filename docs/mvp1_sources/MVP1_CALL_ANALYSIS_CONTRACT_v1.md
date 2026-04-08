# MVP-1 Call Analysis Contract — AI Анализ звонков

**Document code:** `edo_sales_call_analysis_contract`  
**Version:** `v1`  
**Status:** Approved for implementation  
**Date:** 2026-03-17

## 1. Purpose

This file defines the **structured result contract** for one analyzed call.

Important:

- **Checklist** = evaluation rules.
- **Contract** = structured result for one specific call.
- The contract must preserve detailed results by stage and by criterion.
- Anything outside MVP-1 must remain optional.

## 2. Contract principles

1. The contract is JSON.
2. Field names and field types are stable.
3. Empty arrays are preferred over missing fields.
4. Optional fields may be present as empty arrays / null.
5. The contract must keep evidence-based detail.
6. The contract must not collapse criterion-level results into one generic summary.

## 3. Required top-level fields

Required top-level fields:

- `schema_version`
- `instruction_version`
- `checklist_version`
- `analysis_timestamp`
- `call`
- `classification`
- `summary`
- `score`
- `score_by_stage`
- `strengths`
- `gaps`
- `recommendations`
- `agreements`
- `follow_up`
- `product_signals`
- `evidence_fragments`
- `analytics_tags`
- `data_quality`

## 4. Top-level structure

```json
{
  "schema_version": "call_analysis.v1",
  "instruction_version": "string",
  "checklist_version": "string",
  "analysis_timestamp": "ISO-8601 datetime",

  "call": { "...": "..." },
  "classification": { "...": "..." },
  "summary": { "...": "..." },
  "score": { "...": "..." },
  "score_by_stage": [{ "...": "..." }],
  "strengths": [{ "...": "..." }],
  "gaps": [{ "...": "..." }],
  "recommendations": [{ "...": "..." }],
  "agreements": [{ "...": "..." }],
  "follow_up": { "...": "..." },
  "product_signals": [{ "...": "..." }],
  "evidence_fragments": [{ "...": "..." }],
  "analytics_tags": ["..."],
  "data_quality": { "...": "..." }
}
```

## 5. Field specification

## 5.1 `call`
Required fields:

- `call_id` — internal unique call id
- `external_call_code` — external or human-readable call code if available
- `source_system` — e.g. `onlinepbx`
- `department_id`
- `manager_id` — may be null if unresolved
- `manager_name`
- `call_started_at` — ISO-8601 datetime
- `duration_sec`
- `direction`
- `contact_name` — may be null
- `contact_phone` — may be null
- `contact_company` — may be null
- `language` — e.g. `ru`

## 5.2 `classification`
Required fields:

- `call_type`
- `scenario_type`
- `channel_context`
- `analysis_eligibility` — `eligible` or `not_eligible`
- `eligibility_reason`
- `analysis_confidence`

Allowed `call_type` and `scenario_type` values are defined in the checklist file.

## 5.3 `summary`
Required fields:

- `short_summary`
- `context`
- `call_goal`
- `outcome_code`
- `outcome_text`
- `next_step_text`

## 5.4 `score`
Required fields:

- `legacy_card_score` — numeric compatibility field for current human-readable cards
- `legacy_card_level` — current card level
- `checklist_score`

Inside `checklist_score`:
- `total_points`
- `max_points`
- `score_percent`
- `level`

Also required:
- `critical_failure`
- `critical_errors`

`critical_errors` must be an array of structured items, not only strings.

Recommended item shape:
- `error_code`
- `title`
- `evidence`
- `impact`

## 5.5 `score_by_stage`
This is mandatory for deeply analyzed calls.

Each item must contain:

- `stage_code`
- `stage_name`
- `stage_score`
- `max_stage_score`
- `criteria_results`

### `criteria_results`
Each criterion item must contain:

- `criterion_code`
- `criterion_name`
- `score`
- `max_score`
- `comment`
- `evidence`

Criterion-level detail is mandatory. Do not replace it with one stage comment.

## 5.6 `strengths`
Array of 1–3 items for meaningful calls.

Each item:
- `title`
- `evidence`
- `impact`

## 5.7 `gaps`
Array of 1–3 items.

Each item:
- `title`
- `evidence`
- `impact`

## 5.8 `recommendations`
Array of actionable coaching recommendations.

Each item:
- `priority` — `high`, `medium`, or `low`
- `problem`
- `why_it_matters`
- `better_phrase`

## 5.9 `agreements`
Array of actual extracted commitments only.

Each item:
- `agreement_text`
- `owner`
- `due_date_text`
- `due_date_iso`
- `next_step`
- `status_initial`

Use empty array when no agreement exists.

## 5.10 `follow_up`
Required even when there is no agreement.

Fields:
- `next_step_fixed` — boolean
- `next_step_type`
- `next_step_text`
- `owner`
- `due_date_text`
- `due_date_iso`
- `reason_not_fixed`

## 5.11 `product_signals`
Optional for MVP-1, but field must exist.

Each item:
- `signal_type` — e.g. `pain`, `objection`, `usage_context`, `request`
- `topic`
- `quote`
- `importance`

Use empty array when absent.

## 5.12 `evidence_fragments`
Mandatory for meaningful deeply analyzed calls.

Each item:
- `fragment_type` — e.g. `good_example`, `missed_opportunity`, `tone_risk`
- `client_text`
- `manager_text`
- `why`
- `better_variant`

## 5.13 `analytics_tags`
Array of compact tags for downstream filtering.

## 5.14 `data_quality`
Required fields:
- `transcript_quality`
- `classification_quality`
- `analysis_quality`
- `needs_manual_review`
- `manual_review_reason`

## 6. Eligibility behavior

### Deeply analyzed call
All required fields above must be filled meaningfully.

### Not eligible for deep analysis
The contract must still contain:

- `call`
- `classification`
- `summary` (minimal allowed)
- `score` with zero / null-safe structure if needed
- empty arrays for detailed coaching sections
- clear `eligibility_reason`

Implementation must stay schema-safe.

## 7. MVP boundary

Required in MVP-1:
- classification,
- summary,
- score,
- score_by_stage,
- criterion-level results,
- strengths,
- gaps,
- recommendations,
- agreements,
- follow_up,
- evidence_fragments.

Optional in MVP-1:
- non-essential product analytics expansion,
- broad trend-enrichment fields,
- advanced automation metadata.

## 8. Non-negotiable implementation rules

- Do not rename fields without a deliberate version change.
- Do not remove criterion-level structure.
- Do not make optional future fields mandatory.
- Do not hardcode prompt content in code.
- Do not treat placeholder business logic as final if sources are updated later.
