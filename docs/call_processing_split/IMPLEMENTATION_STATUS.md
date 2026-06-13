# Call-processing / analysis split implementation status

Date started: 2026-06-13  
Branch: `feat/call-processing-analysis-split`  
Source task pack: `docs/call_processing_split/IMPLEMENTATION_TASK_PACK_FOR_AGENTS.md`

## Current Rule

This branch implements the full service split in task-card order. Existing EDO
pilot behavior must stay available until cutover. Production cutover, real
production migrations, secret changes, and destructive operations require
explicit operator approval.

## Task Status

| Task | Status | Notes |
| --- | --- | --- |
| 0. Repo baseline and contract skeleton | `done` | Branch created; task pack copied into repo; contract skeleton added in `app.agents.call_processing`; focused contract tests pass. |
| 1. DB schemas, models, migrations, compatibility | `pending` | Must start after Task 0 contract freeze. |
| 2. Call-processing domain service | `pending` | Depends on Task 1. |
| 3. API, CLI, auth, read grants | `pending` | Depends on Tasks 1-2. |
| 4. Extract LLM-1 from analyzer runtime | `pending` | Depends on Task 2. |
| 5. CallProcessingClient and analysis refactor | `pending` | Depends on Tasks 3-4. |
| 6. Reporting and orchestrator refactor | `pending` | Depends on Task 5. |
| 7. Runtime split | `pending` | Depends on Tasks 2-5. |
| 8. Test matrix and verification pack | `pending` | Starts early, final pass after Tasks 1-7. |
| 9. Cutover, rollback, runbook | `pending` | Depends on Tasks 1-8. |

## Task 0 Contract Skeleton

Added initial contract module:

- `core/app/agents/call_processing/__init__.py`
- `core/app/agents/call_processing/schemas.py`

The skeleton defines:

- artifact kinds and statuses;
- processing run statuses;
- structured error classes;
- retryable and non-retryable error class sets;
- client type and role values;
- `APP_SERVICE` and `CALL_PROCESSING_MODE` values;
- `llm1_first_pass_v1` payload model;
- processing scope and stable scope hash;
- ensure request/response model;
- access grant model with admin/reader processing gate.

No runtime behavior, migrations, provider calls, or settings validation changed
in this task.

Verification:

- `python3 -m py_compile core/app/agents/call_processing/__init__.py core/app/agents/call_processing/schemas.py tests/test_call_processing_contracts.py core/tests/test_call_processing_contracts.py`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_contracts.py`
  -> `6 passed`
- `git diff --check`

Next task:

- Task 1 DB schemas, models, migrations and compatibility views.
