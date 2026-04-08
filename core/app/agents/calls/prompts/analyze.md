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
