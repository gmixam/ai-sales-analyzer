# AI Sales Analyzer — Agent Entry Rules

Use GitHub repo docs as the primary source of truth.

Primary canonical rules live in:
- docs/CODER_WORKING_RULES.md
- docs/TASK_PROMPT_TEMPLATE.md

Before starting any task:
1. Read `docs/CODER_WORKING_RULES.md`.
2. If the user request is not already in project task format, normalize it first.
3. Use repo docs as the primary source of truth.
4. Keep scope bounded.
5. Do not rely on memory or agent-specific hidden context as source of truth.
6. Before сдача результата, complete the close-out checklist.

Critical defaults:
- repo-first
- verification first
- no scope creep
- update `docs/PROGRESS.md` when project status changed
- update `docs/DECISIONS.md` when a stable decision changed
- task is not complete without close-out