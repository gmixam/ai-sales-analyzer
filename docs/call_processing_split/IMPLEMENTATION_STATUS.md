# Call-processing / analysis split implementation status

Date started: 2026-06-13  
Branch: `feat/call-processing-analysis-split`  
Source task pack: `docs/call_processing_split/IMPLEMENTATION_TASK_PACK_FOR_AGENTS.md`
Latest acceptance audit:
`docs/call_processing_split/RELEASE_ACCEPTANCE_AUDIT_2026-06-13.md`
Completion roadmap:
`docs/call_processing_split/COMPLETION_ROADMAP.md`

## Current Rule

This branch implements the full service split in task-card order. Existing EDO
pilot behavior must stay available until cutover. Production cutover, real
production migrations, secret changes, and destructive operations require
explicit operator approval.

## Task Status

| Task | Status | Notes |
| --- | --- | --- |
| 0. Repo baseline and contract skeleton | `done` | Branch created; task pack copied into repo; contract skeleton added in `app.agents.call_processing`; focused contract tests pass. |
| 1. DB schemas, models, migrations, compatibility | `implemented_local` | Added additive `call_core` models/tables, schema creation, transcript/transcript_segments backfill, `call_public` compatibility views, and optional read-only grant pattern for `asa_analysis_reader`. Live migration smoke remains release-time. |
| 2. Call-processing domain service | `implemented_local_provider_backed` | Added repositories, ensure, source discovery, legacy backfill, STT artifact build, LLM1 first-pass artifact build, retry/stale helpers. Live provider smoke remains release-time. |
| 3. API, CLI, auth, read grants | `implemented_local` | Added header-grant API routes, package CLI, read-only `call_public` grant pattern, and admin/reader gates. Dry-run, artifacts, and retry-failed are covered by focused tests. |
| 4. Extract LLM-1 from analyzer runtime | `implemented_local` | `CALL_PROCESSING_MODE=legacy` keeps runtime LLM-1; `external_service` consumes injected/fetched `llm1_first_pass_v1` before LLM2. |
| 5. CallProcessingClient and analysis refactor | `implemented_local` | Added local/HTTP clients, LLM-1 artifact adapter, async boundary, and reporting integration through Task 6. |
| 6. Reporting and orchestrator refactor | `implemented_local` | `manager_daily` external mode calls `CallProcessingClient`, consumes transcript/LLM1 artifacts, and keeps legacy path intact. `rop_weekly` is explicitly persisted-only in both modes. Manual live pilot is legacy-only in external-service split. |
| 7. Runtime split | `implemented_local_compose` | Added service identity settings, split queue helpers, and Docker profile services without changing default monolith startup. Live split deployment remains release-time. |
| 8. Test matrix and verification pack | `implemented_local` | Added reproducible verification pack, copy-paste smoke commands, and current verification report. |
| 9. Cutover, rollback, runbook | `runbook_ready_cutover_not_executed` | Added cutover/rollback runbook and next-agent handoff. Production cutover not executed. |
| SPLIT-COMPLETE-06 secret partitioning | `implemented_local` | Added split env templates, split service `env_file` partitioning, settings strict boundary, and preflight CLI while preserving monolith `.env` rollback. |

## Completion Roadmap

The implementation tasks are locally complete, but production completion is
tracked separately in
`docs/call_processing_split/COMPLETION_ROADMAP.md`.

Current completion status:

- first real provider-backed split run was executed on 2026-06-14 for report day
  `2026-06-12`;
- the run confirmed the route
  `call_processing_api/worker -> analysis_api` with
  `CALL_PROCESSING_MODE=external_service`;
- the run was `partial`, because the selected day had no Timur calls in scope
  and only two manager reports were produced in operator Telegram;
- scheduled/reviewable flow, ROP weekly external-service smoke, split cost
  normalization, production secret partitioning and production cutover remain
  open completion stages.

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
  - If operator-created role `asa_analysis_reader` exists, grants only
    `USAGE` on `call_public` and `SELECT` on `call_public` views/default
    tables. The migration does not create production roles and does not grant
    write access or direct `call_core` reads.
- `core/tests/test_call_processing_db_contract.py`
  - Mirrored to `tests/test_call_processing_db_contract.py`.
  - Validates schema-qualified model metadata.
  - Validates partial unique active artifact index SQL shape.
  - Validates migration SQL/view/backfill contract without requiring a
    production DB.
  - Validates the optional `call_public` read-only grant pattern and guards
    against write grants.

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

First pass added the domain-service shell. The current pass adds provider-backed
source discovery, STT artifact build, and LLM1 first-pass artifact build while
preserving `dry_run` as no-provider/no-write planning.

Changed:

- `core/app/agents/call_processing/repositories.py`
  - Added `ArtifactRepository` for active artifact read/write/latest lookup.
  - Added `ProcessingRunRepository` for durable run create/update/status.
  - Centralized first artifact version names.
- `core/app/agents/call_processing/service.py`
  - Added `CallProcessingService.ensure(scope, required_artifacts, mode)` and
    async `ensure_async(...)` for API/FastAPI usage.
  - Creates a durable run for every ensure/dry-run request.
  - In `ensure` mode, discovers OnlinePBX source calls for the scope and
    persists missing interactions through `OnlinePBXIntake`.
  - Counts OnlinePBX CDR/recording-url requests in both
    `source_provider_calls_made` and total `provider_calls_made`.
  - Reuses existing active ready artifacts.
  - Backfills transcript artifacts from `Interaction.text`.
  - Backfills transcript segment artifacts from
    `Interaction.metadata_.segments`.
  - Builds missing `transcript` and `transcript_segments` artifacts through
    `CallsExtractor.process()` when a source interaction has audio.
  - Builds missing `llm1_first_pass_v1` artifacts through
    `CallsAnalyzer._request_llm1_first_pass()` only; call-processing does not
    call LLM2 `analyze_call()`.
  - Ordinary `ensure` does not retry active failed artifacts marked
    non-retryable; retryable failed artifacts can be rebuilt, and admin
    `force_retry_failed` can explicitly retry failed artifacts.
  - Dependency-aware artifact order is now
    `transcript -> transcript_segments -> llm1_first_pass`.
  - Supports `dry_run` planning without provider calls or artifact writes.
  - Returns `EnsureResponse` with planned counts, provider call counts, and
    quota status.
  - Enforces optional per-run provider-call budget from admin grant
    `rate_limits`; quota exhaustion stops further billable provider calls and
    exposes `quota_insufficient` plus required admin action in the response.
  - Added retry policy helpers and 30-minute stale run detection.
- `core/app/agents/call_processing/__init__.py`
  - Exported service and retry/stale helpers.
- `core/tests/test_call_processing_service.py`
  - Mirrored to `tests/test_call_processing_service.py`.
  - Covers idempotent artifact reuse, dry-run behavior, run persistence,
    scope date filtering, legacy transcript backfill, source discovery,
    STT transcript/segments artifact build, LLM1 first-pass artifact build
    without LLM2, quota blocking, failed-artifact retry policy, and stale
    detection.

Verification:

- `python3 -m py_compile core/app/agents/call_processing/client.py core/app/agents/call_processing/service.py core/app/agents/calls/reporting.py core/app/core_shared/api/routes/call_processing.py core/tests/test_call_processing_client.py core/tests/test_call_processing_service.py`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_client.py /app/tests/test_call_processing_service.py /app/tests/test_call_processing_api.py`
  -> `27 passed`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_contracts.py /app/tests/test_call_processing_db_contract.py /app/tests/test_call_processing_service.py /app/tests/test_call_processing_api.py /app/tests/test_call_processing_cli.py /app/tests/test_call_processing_llm1_external_mode.py /app/tests/test_call_processing_client.py /app/tests/test_call_processing_reporting_integration.py /app/tests/test_call_processing_runtime_split.py /app/tests/test_llm2_layered_runtime.py`
  -> `73 passed`
- `git diff --check`

Residual risk:

- Real provider execution still requires live environment smoke; unit coverage
  uses fake intake/extractor/analyzer to avoid billable calls.

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
    `run-status`, `artifacts`, and admin-gated `retry-failed`.
  - `retry-failed --run-id` loads the original run scope/required artifacts and
    starts a new ensure run with `force_retry_failed=True`.
  - Passes optional provider-call budget from `AccessGrant.rate_limits` to the
    service for `ensure`, `dry-run`, and `retry-failed`.
- `core/report_scripts/call_processing_cli.py`
  - Added host wrapper around package CLI.
- `core/tests/test_call_processing_api.py`
  - Mirrored to `tests/test_call_processing_api.py`.
  - Covers route mount, admin requirement, requested_by/grant match, and reader
    artifact access.
- `core/tests/test_call_processing_cli.py`
  - Mirrored to `tests/test_call_processing_cli.py`.
  - Covers admin gate, dry-run JSON output, retry-failed admin-only behavior,
    retry-failed force replay of the original run scope, and rate-limit budget
    forwarding.

Verification:

- `python3 -m py_compile core/app/core_shared/api/routes/call_processing.py core/app/agents/call_processing/cli.py core/report_scripts/call_processing_cli.py core/tests/test_call_processing_api.py core/tests/test_call_processing_cli.py tests/test_call_processing_api.py tests/test_call_processing_cli.py`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_api.py /app/tests/test_call_processing_cli.py`
  -> `11 passed`
- `git diff --check`

Residual risk:

- Header JSON grant is a first-pass contract/test mechanism, not final
  production auth. Service-account secret validation and persistent grants
  remain for runtime/security hardening.
- `retry-failed` is implemented as synchronous admin replay of the original
  run scope; queue-backed retry workers remain a later operational hardening
  option, not a blocker for local/admin recovery.

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

- This analyzer pass only introduced the fail-closed external-artifact input.
  The later Task 5/6 passes now fetch and inject artifacts through
  `CallProcessingClient`; live external-service smoke with real artifacts
  remains release-time evidence.

## Task 5 CallProcessingClient Implementation

Changed:

- `core/app/agents/call_processing/client.py`
  - Added `CallProcessingClient` protocol with
    `ensure_processed_calls`, `get_processed_artifacts`, and
    `get_llm1_first_pass_artifact`.
  - Added `LocalCallProcessingClient` backed by `CallProcessingService`,
    `ArtifactRepository`, and the existing DB session.
  - Added `HttpCallProcessingClient` for split analysis deployments; it calls
    `/call-processing/ensure`, `/call-processing/artifacts`, and
    `/call-processing/artifacts/{interaction_id}/llm1_first_pass`.
  - Added async `ensure_processed_calls_async()` for local and HTTP clients so
    async report runs can request upstream artifacts without falling back to a
    sync call inside the active event loop.
  - Added `build_call_processing_client()` factory: monolith/default uses the
    local client, while `APP_SERVICE=analysis` +
    `CALL_PROCESSING_MODE=external_service` uses the HTTP client.
  - Added `llm1_first_pass_payload_from_artifact()` adapter from durable
    `call_core.call_artifacts` rows to `LLM1FirstPassPayload`.
  - Adapter requires `llm1_first_pass_v1`, active ready artifact status, object
    payload, valid payload metadata, and ready payload status.
  - `ensure_processed_calls()` delegates to the local/HTTP call-processing
    service boundary; the provider-backed first pass is implemented by the
    service in `ensure` mode, while `dry_run` remains no-provider/no-write.
- `core/app/agents/call_processing/__init__.py`
  - Exported the client protocol, local/HTTP clients, factory, adapter, and
    artifact error.
- `core/app/core_shared/api/routes/call_processing.py`
  - Added single-artifact read endpoint for HTTP client LLM1 lookup.
- `core/tests/test_call_processing_client.py`
  - Mirrored to `tests/test_call_processing_client.py`.
  - Covers ready artifact adaptation, missing artifact as `None`, sync/async
    ensure delegation, scoped artifact reads, HTTP client ensure/read calls, and
    invalid artifact fail-closed behavior.

Verification:

- `python3 -m py_compile core/app/agents/call_processing/client.py core/app/agents/call_processing/__init__.py core/tests/test_call_processing_client.py tests/test_call_processing_client.py`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_client.py`
  -> `5 passed`
- `git diff --check`

Verification note:

- Host `python3 -m pytest ...` could not run because host Python does not have
  `pytest` installed; focused pytest passed in the running API container.

Residual risk:

- The local and HTTP client boundaries are covered with fake/local tests. Full
  external-service smoke through separate running services with real artifacts
  remains release-time evidence.

## Task 6 Reporting/Orchestrator Implementation

First pass wired `manager_daily` reporting to the call-processing boundary while
preserving the legacy pilot path.

Changed:

- `core/app/agents/calls/reporting.py`
  - `CallsManualReportingOrchestrator` now owns a `CallProcessingClient`
    instance built by `build_call_processing_client()`: local in monolith mode,
    HTTP in split `APP_SERVICE=analysis` mode.
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
  - Explicit admin/manual rerun can pass `force_rebuild_analyses` (CLI:
    `--force-rebuild-analyses`) to rebuild analyses for late upstream
    artifacts and supersede the marker without enabling automatic reruns.
  - Legacy mode keeps the previous direct STT and runtime LLM1 path; the new
    `llm1_first_pass_artifact` keyword is not passed in legacy mode.
  - Observability now separates external upstream LLM1 reuse/missing counters
    from EDO LLM2 analysis builds.
  - `rop_weekly` remains persisted-only in both legacy and `external_service`
    modes: weekly reporting does not call call-processing `ensure`, does not
    source-discover, and does not build new STT/LLM1/LLM2 artifacts.
- `core/app/agents/calls/orchestrator.py`
  - Manual live pilot runs are explicitly blocked in
    `CALL_PROCESSING_MODE=external_service`, because that path owns
    OnlinePBX/STT/LLM1. Operators should use call-processing `ensure` for
    upstream artifacts and `manual_reporting_runner` for report delivery in
    split mode. Delivery replay remains persisted-artifact based.
- `core/tests/test_call_processing_reporting_integration.py`
  - Mirrored to `tests/test_call_processing_reporting_integration.py`.
  - Covers ready LLM1 artifact injection without reporting-local STT and
    missing LLM1 artifact as partial/no-analysis rather than a crash or hidden
    provider call.
  - Covers manager_daily async `ensure` source summary mapping and
    `rop_weekly` external mode persisted-only behavior without call-processing
    `ensure`.
  - Covers force rebuild after late upstream artifacts: without the flag the
    marker is emitted; with the flag a new analysis is built and the marker is
    superseded.
- `core/tests/test_call_processing_manual_pilot_boundary.py`
  - Covers that manual live pilot fails before any upstream provider work in
    `external_service` mode.
- `core/tests/test_call_processing_manual_reporting_runner.py`
  - Covers CLI acceptance of `--force-rebuild-analyses`.

Verification:

- `python3 -m py_compile core/app/agents/calls/reporting.py core/app/agents/calls/manual_reporting_runner.py core/app/agents/calls/orchestrator.py core/tests/test_call_processing_reporting_integration.py core/tests/test_call_processing_manual_pilot_boundary.py core/tests/test_call_processing_manual_reporting_runner.py`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_reporting_integration.py`
  -> `6 passed`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_manual_pilot_boundary.py`
  -> `1 passed`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_manual_reporting_runner.py`
  -> `1 passed`
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_contracts.py /app/tests/test_call_processing_db_contract.py /app/tests/test_call_processing_service.py /app/tests/test_call_processing_api.py /app/tests/test_call_processing_cli.py /app/tests/test_call_processing_llm1_external_mode.py /app/tests/test_call_processing_client.py /app/tests/test_call_processing_reporting_integration.py /app/tests/test_call_processing_manual_pilot_boundary.py /app/tests/test_call_processing_manual_reporting_runner.py /app/tests/test_call_processing_runtime_split.py /app/tests/test_llm2_layered_runtime.py`
  -> `73 passed`
- Legacy focused reporting checks for contract/quota/source-audio branches:
  `5 passed, 287 deselected`
- `git diff --check`

Verification note:

- Broad semantic-empty reporting tests still depend on runtime semantic
  validation config in the current container; they were not used as acceptance
  for this integration pass.

Residual risk:

- `CallProcessingService.ensure()` now has provider-backed OnlinePBX
  discovery/STT/LLM1 first-pass behavior in `ensure` mode, but this pass used
  fake intake/extractor/analyzer unit coverage. Live provider smoke and
  production worker scheduling remain before cutover.
- In `external_service` mode reporting still does not hide missing upstream
  source ingestion; it reports partial/no-data until upstream artifacts exist.
- Scheduled/reviewable focused checks are green; full external-service live
  smoke with real artifacts remains for release execution.

## Task 7 Runtime Split First Pass

First pass added service identity and queue separation without changing the
default local monolith startup.

Changed:

- `core/app/core_shared/config/settings.py`
  - Added `APP_SERVICE=monolith_legacy|call_processing|analysis`.
  - Kept `CALL_PROCESSING_MODE=legacy|external_service` validation.
  - `APP_SERVICE=analysis` requires `CALL_PROCESSING_MODE=external_service`.
  - `APP_SERVICE=analysis` requires `CALL_PROCESSING_API_BASE_URL` and
    `CALL_PROCESSING_ACCESS_GRANT_JSON`, so split analysis uses the
    call-processing API instead of a local DB-backed client.
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

## SPLIT-COMPLETE-06 Secret Partitioning Pass

Changed:

- Added `.env.split.common.example` for DB/Redis/shared runtime defaults and
  Compose interpolation values.
- Added `.env.call-processing.example` for OnlinePBX, STT, and LLM1 upstream
  provider routing only.
- Added `.env.analysis.example` for call-processing API access, LLM2/LLM3,
  Bitrix/read-only reporting config, SMTP, Telegram, and alert delivery.
- Updated `.gitignore` so real `.env.split.common`, `.env.call-processing`, and
  `.env.analysis` remain ignored while the examples are tracked.
- Updated `docker-compose.yml` so split services read
  `.env.split.common + role-specific env_file`; default monolith services keep
  `.env` for rollback/local development.
- Removed inline analysis defaults for `CALL_PROCESSING_API_BASE_URL` and
  `CALL_PROCESSING_ACCESS_GRANT_JSON` so `.env.analysis` owns those values.
- Updated the cutover runbook with the split env file map and safe
  `docker compose ... config --no-env-resolution --quiet` checks.
- Added `STRICT_SERVICE_SECRET_PARTITIONING` to settings.
- `APP_SERVICE=analysis` in strict mode fails when upstream OnlinePBX/STT/LLM1
  secrets or enabled provider configs are present.
- `APP_SERVICE=call_processing` in strict mode fails when downstream LLM2/LLM3
  provider secrets or configs are present; delivery secrets remain
  warning-visible because technical alerts may still be needed.
- Added `split_secret_partitioning_preflight.py` with JSON summary and exit
  codes. It is available in both `core/report_scripts` and runtime-mounted
  `scripts` so `python report_scripts/split_secret_partitioning_preflight.py`
  works inside current Compose containers.

Verification:

- `docker compose config --no-env-resolution --quiet` -> passed.
- `docker compose --env-file .env.split.common.example --profile split config --no-env-resolution --quiet` -> passed.
- `docker compose --env-file .env.split.common.example --profile split config --no-env-resolution --quiet postgres redis call_processing_api call_processing_worker analysis_api analysis_worker analysis_beat` -> passed.
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_runtime_split.py /app/tests/test_service_secret_partitioning.py` -> `16 passed`.
- `docker compose exec -T api python -m ruff check /app/app/core_shared/config/settings.py /app/tests/test_call_processing_runtime_split.py /app/tests/test_service_secret_partitioning.py /app/report_scripts/split_secret_partitioning_preflight.py` -> passed.
- `python3 -m py_compile` for changed settings/preflight/tests -> passed.
- Container preflight smoke for clean `analysis --strict` -> passed.
- Container preflight smoke for clean `call-processing --strict` -> passed.
- Strict `analysis` with injected upstream `ONLINEPBX_API_KEY` -> failed as expected.
- `git diff --check` -> passed.

Residual risk:

- Real secret files were not created or validated in git, by design.
- Current running monolith `api` container still reads common `.env` and fails
  `analysis --strict` preflight as expected; split services must be recreated
  with service-specific env files for production smoke.

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
- Focused call-processing/analyzer pack after quota gate pass:
  `73 passed`
- Focused AI routing/settings pack:
  `48 passed`
- Legacy prepare-artifacts + scheduled/reviewable focused checks:
  `28 passed, 217 deselected`
- `docker compose config`
- `docker compose --profile split config`
- `git diff --check`

Residual risk:

- This is a local verification pack. Production cutover, live provider-backed
  split-worker smoke, full ROP weekly external smoke, and scheduled reviewable
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

- Live provider-backed split-worker smoke, production scheduling, and full
  external-service smoke are still required before production cutover can be
  called complete.
