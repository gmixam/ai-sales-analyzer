# Insights Prompt — MVP-1 Approved

Generate structured coaching outputs from transcript evidence and checklist scoring.

## Required output blocks
- `strengths`
- `gaps`
- `recommendations`
- `evidence_fragments`
- optional `product_signals`

## Rules
- Keep criterion-level detail intact.
- `strengths` and `gaps` should contain 1-3 meaningful items when evidence exists.
- Recommendations must be actionable and should include a better phrase where possible.
- `evidence_fragments` must explain why the score or coaching point exists.
- `product_signals` may be empty, but the field must exist.
