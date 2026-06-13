# Task 1 DB acceptance checks

Date: 2026-06-13  
Applies to: Task 1 from `IMPLEMENTATION_TASK_PACK_FOR_AGENTS.md`

## Required Shape

The first DB pass must be additive and non-destructive:

- create schemas `call_core`, `call_public`, `analysis`, `org`;
- keep legacy `public.*` tables intact for pilot compatibility;
- add `call_core.call_processing_runs`;
- add `call_core.call_artifacts`;
- add `call_public.processed_calls_v1`;
- add `call_public.transcripts_v1`;
- add `call_public.llm1_artifacts_v1`;
- add `call_public.processing_runs_v1`;
- backfill transcript and transcript_segments artifacts from legacy
  `public.interactions` when data exists;
- do not fabricate old LLM1 artifacts;
- provide downgrade that drops new views/tables/schemas without touching legacy
  tables.

## ORM Checks

- New ORM models must be schema-qualified, not replacements for legacy models.
- Legacy `Interaction`, `Analysis`, report schedule models must remain import
  compatible.
- New `CallProcessingRun` and `CallArtifact` model names should be explicit.
- `CallArtifact` must support artifact kind/version/status/provider/model/error
  metadata.
- `CallProcessingRun` must support requested_by, scope, scope_hash, required
  artifacts, mode, status, counts, errors, timestamps and heartbeat/progress.

## Migration Checks

- Alembic revision must follow current head `6b8d0c5e2f31`.
- `upgrade()` must not drop or rename legacy tables.
- `downgrade()` must not drop legacy tables.
- Views must expose stable contract names.
- SQL must tolerate empty legacy tables.
- Backfill must be idempotent enough for migration execution and must not
  fabricate LLM1 data.

## Test Checks

Focused tests should verify:

- ORM metadata contains schema-qualified new tables;
- model constraints/index names cover artifact idempotency and run status;
- migration file contains required schemas/views/backfill statements;
- public view names are present;
- legacy models still point to default schema.

Runtime DB migration smoke can be added later if local PostgreSQL test harness is
prepared. For this first pass, static SQL/model tests are acceptable, but the
residual risk must be documented.
