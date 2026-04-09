# AI Sales Analyzer — Claude Entry Rules

## Project
- Project: AI Sales Analyzer
- Primary source of truth: GitHub repo docs
- Default branch: `main`

## Mandatory task entry rule
Before starting any task:
1. Read `docs/CODER_WORKING_RULES.md`.
2. Use repo docs as the primary source of truth.
3. If the user request is not already structured in the project task format, first normalize it into that format using current repo docs.
4. Keep scope bounded to the requested step.
5. Do not rely on memory, prior chat assumptions, or agent-specific hidden context as source of truth.
6. Before сдача результата, complete the close-out checklist from the task prompt.

## Default repo-first policy
- Canonical context lives in `docs/`.
- Current chat is a management delta over repo.
- If repo and chat conflict, follow the current explicit management decision first, then sync it back into repo docs.
- Files in external Sources are reference-only unless explicitly promoted into repo.

## Key defaults
- verification first
- no scope creep
- update `docs/PROGRESS.md` when project status or current working step changed
- update `docs/DECISIONS.md` when a stable architectural or process rule changed
- task is not complete without close-out