# Calls Analyze Prompt — MVP-1 Approved

Return exactly one JSON object in the approved MVP-1 call analysis contract.

Use sources of truth in this exact priority order:
1. `MVP1_CODEX_HANDOFF.md`
2. `MVP1_CHECKLIST_DEFINITION_v1.md`
3. `MVP1_CALL_ANALYSIS_CONTRACT_v1.md`
4. `REPORT_EVIDENCE_CONTRACT.md`
5. `MVP1_CALL_ANALYSIS_EXAMPLE_TIMUR_v1.json`
6. `MVP1_MANAGER_CARD_FORMAT_v1.md`

## Non-negotiable rules
- Return JSON only.
- Do not rename fields.
- Do not add extra top-level fields except the approved additive `report_evidence_version` and `report_evidence` fields.
- Do not collapse `criteria_results` into generic stage summaries.
- Preserve criterion-level evidence and comments.
- Keep optional fields schema-safe with empty arrays or nulls when needed.
- Do not remove or omit existing required MVP-1 contract fields when adding `report_evidence`.

## Evaluation rules
- Checklist definition is the source of truth for stage applicability.
- Checklist definition is the source of truth for scoring and critical errors.
- Use the contract markdown as the source of truth for field meaning and field shape.
- Use `REPORT_EVIDENCE_CONTRACT.md` as the source of truth for additive `report_evidence v1`.
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

## Additive `report_evidence v1`

In addition to all existing required MVP-1 fields, return these top-level fields:

```json
{
  "report_evidence_version": "v1",
  "report_evidence": {
    "business_outcome": null,
    "situation_candidates": [],
    "manager_coaching_moments": [],
    "voice_of_customer": [],
    "additional_situations": [],
    "follow_up_candidates": [],
    "quote_bank": []
  }
}
```

This package is additive. It must not change checklist scoring, stage applicability, required MVP-1 fields, or the existing `follow_up` contract.

### Grounding rules
- Use only the transcript and provided segments/metadata.
- Every quote and every `dialogue_fragment[].text` must be copied verbatim from the transcript.
- If a useful candidate exists but there is no transcript-grounded quote/fragment, set `evidence_quality` to `insufficient` and `usable_in_report=false`.
- Do not invent quotes, client phrases, manager phrases, timestamps, names, or facts.
- Do not paraphrase as a quote. Put interpretation in `meaning`, `what_happened`, `what_it_means`, `what_was_missing`, `what_better`, or similar explanatory fields.

### Speaker rules
- Allowed speakers: `manager`, `client`, `unknown`.
- Use `manager` or `client` only when transcript/segments make the role reliable.
- If the speaker role is unclear, generic, missing, or inferred only by guesswork, use `unknown`.
- Never manufacture manager/client dialogue from unlabeled transcript text.

### Shared enums
- `priority`: `high | medium | low`
- `evidence_quality`: `direct | indirect | weak | insufficient`
- `speaker`: `manager | client | unknown`
- `business_signal`: `high | medium | low`
- `stage_code`: one of the checklist stage codes:
  `contact_start`, `qualification_primary`, `needs_discovery`, `presentation`,
  `objection_handling`, `completion_next_step`, `sale_processing`, `sale_final`,
  `cross_stage_transition`

### `business_outcome`
Return a semantic signal for the business outcome:

```json
{
  "status": "agreement|rescheduled|refusal|open|tech_service|not_suitable",
  "confidence": "high|medium|low",
  "reason": "...",
  "evidence_quote": "...",
  "evidence_speaker": "client|manager|unknown",
  "needs_human_review": false
}
```

`business_outcome` is a semantic signal, not final report authority. The deterministic reporting-layer `BusinessOutcomeResolver` wins over this signal, and technical blockers / deterministic refusal / service rules win when they conflict.

### `situation_candidates`
Return 0..N candidates for `СИТУАЦИЯ ДНЯ`:

```json
{
  "stage_code": "...",
  "problem_type": "missing_role|missing_process|missing_need|early_presentation|weak_next_step|weak_contact_start|other",
  "situation_title": "...",
  "priority": "high|medium|low",
  "evidence_quality": "direct|indirect|weak|insufficient",
  "dialogue_fragment": [
    {
      "speaker": "manager|client|unknown",
      "text": "...",
      "timestamp_start": null,
      "timestamp_end": null
    }
  ],
  "what_happened": "...",
  "what_it_means": "...",
  "what_was_missing": "...",
  "next_time_action": "...",
  "scripts": ["...", "...", "..."],
  "usable_in_report": true
}
```

`what_happened` and `what_was_missing` must not be identical. Do not make a strong manager-facing conclusion when evidence is weak or insufficient.

### `manager_coaching_moments`
Return worked / missed / risk moments for `РАЗБОР ЗВОНКА`:

```json
{
  "stage_code": "...",
  "moment_type": "worked|missed|risk",
  "priority": "high|medium|low",
  "evidence_quality": "direct|indirect|weak|insufficient",
  "dialogue_fragment": [],
  "what_happened": "...",
  "what_better": "...",
  "usable_in_report": true
}
```

### `voice_of_customer`
Return client quotes for topics `need`, `objection`, `risk`, `price`, `process`, `timing`, `product_interest`, `service_issue`, or `refusal`:

```json
{
  "quote": "...",
  "speaker": "client|unknown",
  "topic": "need|objection|risk|price|process|timing|product_interest|service_issue|refusal",
  "meaning": "...",
  "business_signal": "high|medium|low",
  "stage_code": "...",
  "usable_in_report": true
}
```

Prefer `speaker=client`; use `unknown` if the quote is useful but role attribution is not reliable.

### `additional_situations`
Return additional report-ready situations:

```json
{
  "type": "strength|growth_zone|risk|missed_opportunity|service_issue|customer_signal",
  "title": "...",
  "priority": "high|medium|low",
  "evidence_quality": "direct|indirect|weak|insufficient",
  "what_happened": "...",
  "why_it_matters": "...",
  "recommended_action": "...",
  "stage_code": "...",
  "usable_in_report": true
}
```

### `follow_up_candidates`
Return follow-up candidates only when the call contains a real business follow-up:

```json
{
  "status": "agreement|rescheduled|open",
  "client_label": "...",
  "next_step": "...",
  "deadline": "...",
  "priority": "hot|rescheduled|open",
  "first_phrase": "...",
  "why_follow_up": "...",
  "usable_in_report": true
}
```

Do not return `follow_up_candidates` for `refusal`, `tech_service`, or `not_suitable` calls.

### `quote_bank`
Return reusable transcript-grounded quotes:

```json
{
  "quote": "...",
  "speaker": "client|manager|unknown",
  "topic": "...",
  "stage_code": "...",
  "evidence_quality": "direct|indirect|weak",
  "usable_in_report": true
}
```

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
