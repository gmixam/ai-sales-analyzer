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
| 4. Extract LLM-1 from analyzer runtime | `first_pass_done` | `CALL_PROCESSING_MODE=legacy` keeps runtime LLM-1; `external_service` consumes injected `llm1_first_pass_v1`. |
| 5. CallProcessingClient and analysis refactor | `first_pass_client_done` | Added local client abstraction and LLM-1 artifact adapter; reporting/orchestrator wiring continues through Task 6. |
| 6. Reporting and orchestrator refactor | `first_pass_manager_daily_done` | `manager_daily` external mode calls `CallProcessingClient`, consumes transcript/LLM1 artifacts, and keeps legacy path intact. ROP/manual pilot wiring remains pending. |
| 7. Runtime split | `first_pass_compose_done` | Added service identity settings, split queue helpers, and Docker profile services without changing default monolith startup. |
| 8. Test matrix and verification pack | `first_pass_done` | Added reproducible verification pack, copy-paste smoke commands, and current verification report. |
| 9. Cutover, rollback, runbook | `first_pass_runbook_done` | Added cutover/rollback runbook and next-agent handoff. Production cutover not executed. |

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

## Task 4 Extract LLM-1 From Analyzer Runtime

First pass added the analysis-side ownership switch without changing LLM-2
business logic.

Changed:

- `core/app/core_shared/config/settings.py`
  - Added `CALL_PROCESSING_MODE=legacy|external_service`, defaulting to
    `legacy`.
- `core/app/agents/calls/analyzer.py`
  - Added optional `analyze_call(..., llm1_first_pass_artifact=None)` input for
    Task 5 client/resolver wiring.
  - In legacy mode, `analyze_call()` still calls `_request_llm1_first_pass()`.
  - In `external_service` mode, `analyze_call()` validates the provided
    `LLM1FirstPassPayload` / dict artifact and maps it back to the existing
    internal LLM-1 dict shape before LLM-2.
  - Missing, invalid, or non-ready artifacts fail with `AnalysisError` before
    LLM-2 and include a `partial-missing` style reason.
- `core/tests/test_call_processing_llm1_external_mode.py`
  - Mirrored to `tests/test_call_processing_llm1_external_mode.py`.
  - Covers legacy LLM-1 invocation, external artifact consumption without
    LLM-1 runtime calls, and missing artifact fail-closed behavior before LLM-2.

Verification:

- `python3 -m py_compile core/app/agents/calls/analyzer.py core/app/core_shared/config/settings.py core/tests/test_call_processing_llm1_external_mode.py tests/test_call_processing_llm1_external_mode.py`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_llm1_external_mode.py`
  -> `3 passed`
- `docker compose exec -T api python -m pytest -q /app/tests/test_llm2_layered_runtime.py`
  -> `11 passed`
- `git diff --check`

Residual risk:

- Task 5 still needs to resolve/persist/fetch the artifact from the
  call-processing service; this first pass only supports the injected artifact
  path and fail-closed analyzer behavior.

## Task 5 CallProcessingClient First Pass

First pass added the analysis-facing client boundary without changing
reporting/orchestrator call sites yet.

Changed:

- `core/app/agents/call_processing/client.py`
  - Added `CallProcessingClient` protocol with
    `ensure_processed_calls`, `get_processed_artifacts`, and
    `get_llm1_first_pass_artifact`.
  - Added `LocalCallProcessingClient` backed by `CallProcessingService`,
    `ArtifactRepository`, and the existing DB session.
  - Added `llm1_first_pass_payload_from_artifact()` adapter from durable
    `call_core.call_artifacts` rows to `LLM1FirstPassPayload`.
  - Adapter requires `llm1_first_pass_v1`, active ready artifact status, object
    payload, valid payload metadata, and ready payload status.
  - `ensure_processed_calls()` delegates to the current planner service, which
    still reports zero provider calls made.
- `core/app/agents/call_processing/__init__.py`
  - Exported the client protocol, local client, adapter, and artifact error.
- `core/tests/test_call_processing_client.py`
  - Mirrored to `tests/test_call_processing_client.py`.
  - Covers ready artifact adaptation, missing artifact as `None`, ensure
    delegation, scoped artifact reads, and invalid artifact fail-closed behavior.

Verification:

- `python3 -m py_compile core/app/agents/call_processing/client.py core/app/agents/call_processing/__init__.py core/tests/test_call_processing_client.py tests/test_call_processing_client.py`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_client.py`
  -> `5 passed`
- `git diff --check`

Verification note:

- Host `python3 -m pytest ...` could not run because host Python does not have
  `pytest` installed; focused pytest passed in the running API container.

Residual risk:

- Reporting/orchestrator are intentionally untouched in this first pass per
  current write scope. Task 5 still needs the integration pass that builds
  report scopes, calls the client from analysis/reporting flows, persists
  partial/missing source status, and marks late artifacts.

## Task 6 Reporting/Orchestrator First Pass

First pass wired `manager_daily` reporting to the call-processing boundary while
preserving the legacy pilot path.

Changed:

- `core/app/agents/calls/reporting.py`
  - `CallsManualReportingOrchestrator` now owns a `CallProcessingClient`
    instance backed by `LocalCallProcessingClient`.
  - In `CALL_PROCESSING_MODE=external_service`,
    `manager_daily/build_missing_and_report` calls
    `ensure_processed_calls()` for `transcript`, `transcript_segments`, and
    `llm1_first_pass` instead of doing reporting-local source discovery.
  - Reporting hydrates missing `interaction.text` from ready upstream
    transcript artifacts before analysis.
  - Reporting runs EDO analysis only when a ready `llm1_first_pass_v1` artifact
    is available and passes that artifact into `CallsAnalyzer.analyze_call()`.
  - Missing/invalid upstream LLM1 artifacts stay visible as partial source
    status (`llm1_first_pass_missing` / `llm1_first_pass_invalid`) and do not
    make the call disappear from report artifacts.
  - Late ready upstream artifacts with `source_updated_at` later than reused
    EDO analysis `created_at` mark the affected call as
    `source_artifacts_updated_after_analysis` without automatic rerun.
  - Legacy mode keeps the previous direct STT and runtime LLM1 path; the new
    `llm1_first_pass_artifact` keyword is not passed in legacy mode.
  - Observability now separates external upstream LLM1 reuse/missing counters
    from EDO LLM2 analysis builds.
- `core/tests/test_call_processing_reporting_integration.py`
  - Mirrored to `tests/test_call_processing_reporting_integration.py`.
  - Covers ready LLM1 artifact injection without reporting-local STT and
    missing LLM1 artifact as partial/no-analysis rather than a crash or hidden
    provider call.

Verification:

- `python3 -m py_compile core/app/agents/calls/reporting.py core/tests/test_call_processing_reporting_integration.py tests/test_call_processing_reporting_integration.py`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_reporting_integration.py`
  -> `2 passed`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_contracts.py /app/tests/test_call_processing_db_contract.py /app/tests/test_call_processing_service.py /app/tests/test_call_processing_api.py /app/tests/test_call_processing_cli.py /app/tests/test_call_processing_llm1_external_mode.py /app/tests/test_call_processing_client.py /app/tests/test_call_processing_reporting_integration.py /app/tests/test_llm2_layered_runtime.py`
  -> `47 passed`
- Legacy focused reporting checks for contract/quota/source-audio branches:
  `5 passed, 287 deselected`
- `git diff --check`

Verification note:

- Broad semantic-empty reporting tests still depend on runtime semantic
  validation config in the current container; they were not used as acceptance
  for this integration pass.

Residual risk:

- Current local `CallProcessingService.ensure()` is still planner/backfill-only
  and does not yet perform OnlinePBX discovery or real STT/LLM1 provider work.
  In `external_service` mode reporting therefore does not hide missing upstream
  source ingestion; it reports partial/no-data until upstream artifacts exist.
- ROP weekly, manual pilot orchestration, manual rerun marker clearing, and
  full scheduled flow checks remain for the next Task 6/8 passes.

## Task 7 Runtime Split First Pass

First pass added service identity and queue separation without changing the
default local monolith startup.

Changed:

- `core/app/core_shared/config/settings.py`
  - Added `APP_SERVICE=monolith_legacy|call_processing|analysis`.
  - Kept `CALL_PROCESSING_MODE=legacy|external_service` validation.
  - `APP_SERVICE=analysis` requires `CALL_PROCESSING_MODE=external_service`.
  - `APP_SERVICE=analysis` can start without OnlinePBX/STT provider secrets.
  - `APP_SERVICE=call_processing` requires OnlinePBX and active STT provider
    secrets, but does not require SMTP/Telegram/LLM2/LLM3 delivery secrets.
  - Avoided importing `app.agents.call_processing` from settings to keep config
    below DB/runtime layers.
- `core/app/core_shared/workers/celery_app.py`
  - Added queue constants and helpers:
    `call_processing`, `analysis`, `calls`, `default`.
  - Scheduled EDO reporting routes to `analysis` in split mode and `default` in
    monolith mode.
- `docker-compose.yml`
  - Existing `api`, `worker`, `beat` remain the default monolith startup.
  - Added profile `split` services:
    `call_processing_api`, `analysis_api`,
    `call_processing_worker`, `analysis_worker`, `analysis_beat`.
  - Split workers listen to isolated queues:
    `call_processing_worker -> call_processing`,
    `analysis_worker -> analysis,default`.
  - Added service-specific healthchecks:
    call-processing API uses `/call-processing/health`; analysis API uses
    `/health`.
- `.env.example`
  - Added `APP_SERVICE=monolith_legacy` and `CALL_PROCESSING_MODE=legacy`.
- `core/tests/test_call_processing_runtime_split.py`
  - Mirrored to `tests/test_call_processing_runtime_split.py`.
  - Covers service secret boundaries and queue routing helpers.

Verification:

- `python3 -m py_compile core/app/core_shared/config/settings.py core/app/core_shared/workers/celery_app.py core/tests/test_call_processing_runtime_split.py tests/test_call_processing_runtime_split.py`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_runtime_split.py`
  -> `4 passed`
- `docker compose config`
- `git diff --check`

Smoke commands for QA/release agent:

```bash
docker compose config
docker compose up -d api worker beat
docker compose --profile split up -d call_processing_api call_processing_worker analysis_api analysis_worker analysis_beat
docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_runtime_split.py
```

Residual risk:

- Split services are compose-profile definitions only; production deployment,
  real secret partitioning, real call-processing workers, and source/STT/LLM1
  task implementation still require later Task 7/8 passes.
- Existing unprofiled monolith services still start unless the operator targets
  split services explicitly. This preserves pilot rollback but is not yet a
  production deployment topology.

## Task 8 Verification Pack First Pass

First pass added a reproducible release-check document:

- `docs/call_processing_split/VERIFICATION_PACK.md`
  - Acceptance matrix for DB, processing, API/auth, LLM1 contract, analysis
    integration, reporting, runtime, and rollback.
  - Copy-paste pytest, `py_compile`, compose config, and diff-check commands.
  - Local legacy rollback smoke and split compose smoke commands.
  - Call-processing dry-run CLI smoke command.
  - Manager-daily external-service preview smoke command using the real
    `app.agents.calls.manual_reporting_runner` module.
  - Current verification report with run results and non-green/not-yet-final
    items.

Verification:

- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_reporting_integration.py`
  -> `3 passed`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_runtime_split.py`
  -> `4 passed`
- Focused call-processing/analyzer pack after runtime split:
  `51 passed`
- Focused AI routing/settings pack:
  `7 passed, 41 deselected`
- `docker compose config`
- `docker compose --profile split config`
- `git diff --check`

Residual risk:

- This is a local verification pack. Production cutover, real provider-backed
  split workers, full ROP weekly external smoke, and scheduled reviewable
  external smoke remain for Task 9/release execution.

## Task 9 Cutover/Rollback Runbook First Pass

First pass added:

- `docs/call_processing_split/CUTOVER_ROLLBACK_RUNBOOK.md`
  - current release state;
  - pre-cutover backup/config/test checklist;
  - cutover sequence;
  - rollback sequence;
  - known failure modes and operator actions;
  - admin rerun rule for `source_artifacts_updated_after_analysis`;
  - next-agent handoff route.

Important status:

- Production cutover was not executed.
- Destructive DB actions were not executed.
- The runbook preserves rollback through `APP_SERVICE=monolith_legacy` and
  `CALL_PROCESSING_MODE=legacy`.

Residual risk:

- Real provider-backed split workers and full external-service live smoke are
  still required before production cutover can be called complete.
