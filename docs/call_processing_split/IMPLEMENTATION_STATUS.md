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
| 1. DB schemas, models, migrations, compatibility | `first_pass_done` | Added additive `call_core` models/tables, schema creation, transcript/transcript_segments backfill, and `call_public` compatibility views. |
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

- Task 1 verification/iteration, then Task 2 call-processing domain service.

## Task 1 DB Schemas, Models, Migration, Compatibility

First pass added only additive DB surface; legacy public tables are not moved,
dropped, or rewritten.

Changed:

- `core/app/core_shared/db/models.py`
  - Added schema-qualified `call_core.call_processing_runs` ORM model.
  - Added schema-qualified `call_core.call_artifacts` ORM model.
  - Added partial unique active artifact index metadata for one active artifact
    per `interaction_id + artifact_kind + artifact_version`.
- `core/app/core_shared/db/migrations/versions/2f4c9d8e7a61_add_call_processing_split_schemas.py`
  - Creates schemas `call_core`, `call_public`, `analysis`, and `org`.
  - Creates `call_core.call_processing_runs`.
  - Creates `call_core.call_artifacts`.
  - Creates indexes, including unique active artifact index where PostgreSQL
    supports a partial index.
  - Backfills transcript artifacts from `public.interactions.text` when the
    legacy text column exists and has non-empty text.
  - Backfills transcript_segments artifacts from
    `public.interactions.metadata.segments` when the legacy metadata column
    contains a non-empty segments array.
  - Does not fabricate LLM-1 artifacts.
  - Creates compatibility views:
    `call_public.processed_calls_v1`,
    `call_public.transcripts_v1`,
    `call_public.llm1_artifacts_v1`,
    `call_public.processing_runs_v1`.
- `core/tests/test_call_processing_db_contract.py`
  - Mirrored to `tests/test_call_processing_db_contract.py`.
  - Validates schema-qualified model metadata.
  - Validates partial unique active artifact index SQL shape.
  - Validates migration SQL/view/backfill contract without requiring a
    production DB.

Rollback note:

- Alembic downgrade for revision `2f4c9d8e7a61` drops the new public views,
  additive `call_core` tables, and empty split schemas. Do not run production
  downgrade/destructive DB operations without operator approval and backup.

Verification:

- `python3 -m py_compile core/app/core_shared/db/models.py core/app/core_shared/db/migrations/versions/2f4c9d8e7a61_add_call_processing_split_schemas.py core/tests/test_call_processing_db_contract.py tests/test_call_processing_db_contract.py`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_contracts.py /app/tests/test_call_processing_db_contract.py`
  -> `10 passed`
- `git diff --check`

Residual risk:

- Migration was not applied to a live database in this pass. Live up/down smoke
  remains part of Task 8/cutover verification.
