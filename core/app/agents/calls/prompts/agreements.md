# Agreements Prompt — MVP-1 Approved

Extract only actual commitments and next-step facts from the transcript.

## Required output blocks
- `agreements`
- `follow_up`

## Rules
- Include an agreement only when the call contains a real commitment.
- If there is no real commitment, return `agreements: []`.
- `follow_up` must still exist even when `agreements` is empty.
- Do not invent dates, owners, or next steps.
- Keep `due_date_iso` null when the transcript does not allow a real ISO date.
