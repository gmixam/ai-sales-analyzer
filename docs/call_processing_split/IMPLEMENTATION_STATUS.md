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
| 2. Call-processing domain service | `first_pass_done` | Added repositories, planner-style ensure, legacy transcript backfill, retry/stale helpers. Provider calls intentionally not wired yet. |
| 3. API, CLI, auth, read grants | `first_pass_done` | Added header-grant API routes and package CLI; admin/reader gates covered by focused tests. |
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

## Task 2 Call-processing Domain Service

First pass added the domain-service shell without provider calls or current
analyzer/intake rewrites.

Changed:

- `core/app/agents/call_processing/repositories.py`
  - Added `ArtifactRepository` for active artifact read/write/latest lookup.
  - Added `ProcessingRunRepository` for durable run create/update/status.
  - Centralized first artifact version names.
- `core/app/agents/call_processing/service.py`
  - Added `CallProcessingService.ensure(scope, required_artifacts, mode)`.
  - Creates a durable run for every ensure/dry-run request.
  - Reuses existing active ready artifacts.
  - Backfills transcript artifacts from `Interaction.text`.
  - Backfills transcript segment artifacts from
    `Interaction.metadata_.segments`.
  - Supports `dry_run` planning without provider calls or artifact writes.
  - Returns `EnsureResponse` with planned counts and zero provider calls made.
  - Added retry policy helpers and 30-minute stale run detection.
- `core/app/agents/call_processing/__init__.py`
  - Exported service and retry/stale helpers.
- `core/tests/test_call_processing_service.py`
  - Mirrored to `tests/test_call_processing_service.py`.
  - Covers idempotent artifact reuse, dry-run behavior, run persistence,
    scope date filtering, legacy transcript backfill, retry policy, and stale
    detection.

Verification:

- `python3 -m py_compile core/app/agents/call_processing/__init__.py core/app/agents/call_processing/schemas.py core/app/agents/call_processing/repositories.py core/app/agents/call_processing/service.py core/tests/test_call_processing_service.py tests/test_call_processing_service.py`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_service.py`
  -> `8 passed`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_contracts.py /app/tests/test_call_processing_db_contract.py /app/tests/test_call_processing_service.py`
  -> `18 passed`
- `git diff --check`

Residual risk:

- This first pass does not discover missing calls from OnlinePBX, perform STT,
  perform LLM-1, or update analyzer/reporting call sites. Those are intentionally
  deferred to later task cards.

## Task 3 API, CLI, Auth, Read Grants

First pass added a CLI/API surface for the planning-first call-processing
service. It is intentionally header/contract based and does not introduce UI or
production secret changes.

Changed:

- `core/app/core_shared/api/routes/call_processing.py`
  - Added `/call-processing/health`.
  - Added `POST /call-processing/ensure`.
  - Added `GET /call-processing/runs/{run_id}`.
  - Added `GET /call-processing/artifacts`.
  - Added simple `X-Call-Processing-Grant` header parsing based on the
    `AccessGrant` contract.
  - Enforces `admin` for ensure/dry-run style processing and `reader|admin` for
    read endpoints.
- `core/app/core_shared/api/main.py`
  - Mounted the call-processing router.
- `core/app/agents/call_processing/cli.py`
  - Added package-owned CLI implementation for `ensure`, `dry-run`,
    `run-status`, `artifacts`, and admin-gated placeholder `retry-failed`.
- `core/report_scripts/call_processing_cli.py`
  - Added host wrapper around package CLI.
- `core/tests/test_call_processing_api.py`
  - Mirrored to `tests/test_call_processing_api.py`.
  - Covers route mount, admin requirement, requested_by/grant match, and reader
    artifact access.
- `core/tests/test_call_processing_cli.py`
  - Mirrored to `tests/test_call_processing_cli.py`.
  - Covers admin gate, dry-run JSON output, and retry-failed placeholder.

Verification:

- `python3 -m py_compile core/app/core_shared/api/routes/call_processing.py core/app/agents/call_processing/cli.py core/report_scripts/call_processing_cli.py core/tests/test_call_processing_api.py core/tests/test_call_processing_cli.py tests/test_call_processing_api.py tests/test_call_processing_cli.py`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_api.py /app/tests/test_call_processing_cli.py`
  -> `8 passed`
- `git diff --check`

Residual risk:

- Header JSON grant is a first-pass contract/test mechanism, not final
  production auth. Service-account secret validation and persistent grants
  remain for runtime/security hardening.
- `retry-failed` is CLI/API-reserved but not worker-backed yet.
