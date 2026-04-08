Codex Handoff — MVP-1 Sources for CallsAnalyzer
Date: 2026-03-17
This package contains the approved business sources that were previously missing from the scaffold implementation.
Files in this package
`MVP1_CHECKLIST_DEFINITION_v1.md`
source of truth for evaluation logic
stages
criteria
applicability rules
scoring rules
critical errors
`MVP1_MANAGER_CARD_FORMAT_v1.md`
source of truth for human-readable manager card output
summary sections
stage summary
call table layout
comment style
`MVP1_CALL_ANALYSIS_CONTRACT_v1.md`
source of truth for structured call-level output
required and optional fields
business meaning of each block
`MVP1_CALL_ANALYSIS_EXAMPLE_TIMUR_v1.json`
concrete example of one call analysis in final contract form
Required implementation behavior
Read all four files before editing analyzer prompts or schemas.
Treat the checklist as business logic source of truth.
Treat the contract file as output source of truth.
Treat the manager card format as rendering / reporting source of truth.
Keep everything outside MVP-1 optional.
Do not collapse criterion-level detail.
Do not replace `criteria_results` with free text.
Do not silently change field names or data types.
Non-negotiable constraints
Do not change the immutable AnalysisResult contract without an explicit ADR and approval.
Do not do LLM calls outside `CallsAnalyzer`.
Do not hardcode prompt text in code.
Do not modify `docker-compose.yml` or `pyproject.toml`.
Do not create unrelated files.
What should happen next
Remove business placeholders from the scaffold where these files now provide final logic.
Wire prompt assets to use the approved checklist and contract.
Keep optional future fields optional.
Update `docs/PROGRESS.md` honestly.
Add ADR only if a truly new technical decision is required.
Delivery expectation from Codex
Final Codex response should include:
what was implemented,
changed files,
what to verify manually,
what remains optional,
risks / limitations.