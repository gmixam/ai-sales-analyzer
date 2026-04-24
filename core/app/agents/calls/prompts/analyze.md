# Calls Analyze Prompt — MVP-1 Approved

Return exactly one JSON object in the approved MVP-1 call analysis contract.

Use sources of truth in this exact priority order:
1. `MVP1_CODEX_HANDOFF.md`
2. `MVP1_CHECKLIST_DEFINITION_v1.md`
3. `MVP1_CALL_ANALYSIS_CONTRACT_v1.md`
4. `MVP1_CALL_ANALYSIS_EXAMPLE_TIMUR_v1.json`
5. `MVP1_MANAGER_CARD_FORMAT_v1.md`

## Non-negotiable rules
- Return JSON only.
- Do not rename fields.
- Do not add extra top-level fields.
- Do not collapse `criteria_results` into generic stage summaries.
- Preserve criterion-level evidence and comments.
- Keep optional fields schema-safe with empty arrays or nulls when needed.

## Evaluation rules
- Checklist definition is the source of truth for stage applicability.
- Checklist definition is the source of truth for scoring and critical errors.
- Use the contract markdown as the source of truth for field meaning and field shape.
- Use the approved example JSON as a formatting and filling reference, not as a copy template.

## Behavioral rules
- Be evidence-based.
- Do not invent transcript facts.
- Do not mark stages applicable if the transcript does not support them.
- Keep recommendations actionable and concrete.
- Extract agreements only when there is a real commitment in the call.
- For an `eligible` sales-relevant call, do not return a coaching-empty analysis.
- If the transcript supports any growth issue, return at least one meaningful `gaps` item.
- If the transcript supports any positive signal, return at least one meaningful `strengths` item.
- For every eligible sales-relevant call with any `gaps` item, return at least one usable `recommendations` item with `problem`, `why_it_matters`, and `better_phrase`.
- Populate `evidence_fragments` with usable source-backed moments when the transcript supports them. Prefer real customer phrases in `client_text`; leave `client_text` null rather than inventing a quote.
- If the call is support-only, internal, technical/operational non-sales, too poor-quality, or otherwise not coachable/reportable, set `classification.analysis_eligibility` to `not_eligible`, set a clear `eligibility_reason`, and keep detailed coaching arrays empty instead of pretending it is a sales analysis.
- Every criterion result must include `max_score`; for the current checklist each criterion has `max_score: 2`.

## Language rules
- Preserve transcript meaning and any direct evidence quotes in the original source language.
- Do not translate transcript text, raw source fragments, or intentionally cited source quotes.
- All business-facing fields in the returned contract must be in Russian:
  - `summary`
  - `strengths`
  - `gaps`
  - `recommendations`
  - `follow_up`
  - human-readable agreement text when present
- Do not switch business-facing explanation fields to English.
- System values may remain unchanged:
  - codes
  - enums
  - ids
  - JSON keys
  - technical identifiers

## Manager card relationship
- Manager card format is for human-readable reporting.
- It may inform wording compactness, but it does not override the JSON contract.
