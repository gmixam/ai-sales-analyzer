# Call-processing / analysis split cutover and rollback runbook

Date: 2026-06-13  
Branch: `feat/call-processing-analysis-split`

## Current Release State

This branch contains the first production-shaped implementation of the split,
but production cutover has not been executed.

Implemented locally:

- call-processing contracts, schemas, API/CLI, local service planner, DB models
  and additive migration;
- provider-backed first pass in the call-processing service for OnlinePBX
  discovery, STT transcript/segments, and LLM1 first-pass artifacts;
- analysis `CALL_PROCESSING_MODE=external_service` path for LLM1 artifact
  injection;
- manager_daily reporting integration through `CallProcessingClient`;
- split Docker profile services and queue helpers;
- verification pack and late artifact marker.

Not yet production-complete:

- live provider-backed split-worker smoke and production scheduling;
- full external-service smoke for ROP weekly and scheduled reviewable reporting;
- production secret partitioning;
- real cutover execution.

## Pre-cutover Checklist

1. Announce a short pause window for scheduled report runs.
2. Confirm current branch/commit and backup point:

```bash
git status --short --branch
git rev-parse --short HEAD
```

3. Export/backup PostgreSQL before migrations:

```bash
docker compose exec -T postgres pg_dump \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  --format=custom \
  --file=/tmp/asa_pre_call_processing_split.dump
```

4. Verify config without starting production split services:

```bash
docker compose config
docker compose --profile split config
```

5. Run verification pack:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_call_processing_contracts.py \
  /app/tests/test_call_processing_db_contract.py \
  /app/tests/test_call_processing_service.py \
  /app/tests/test_call_processing_api.py \
  /app/tests/test_call_processing_cli.py \
  /app/tests/test_call_processing_llm1_external_mode.py \
  /app/tests/test_call_processing_client.py \
  /app/tests/test_call_processing_reporting_integration.py \
  /app/tests/test_call_processing_manual_pilot_boundary.py \
  /app/tests/test_call_processing_manual_reporting_runner.py \
  /app/tests/test_call_processing_runtime_split.py \
  /app/tests/test_llm2_layered_runtime.py
```

6. Confirm environment intent:

```bash
APP_SERVICE=monolith_legacy
CALL_PROCESSING_MODE=legacy
```

The final switch to split mode must be explicit.

## Cutover Steps

1. Stop or pause scheduled reporting if it could run during migration.
2. Apply additive DB migration in the approved deployment process.
3. Optional SQL read-only access for analysis/external readers:

```sql
-- Run only if SQL read access is intentionally enabled.
-- The migration grants read-only call_public access automatically when this
-- role exists before/at migration time; otherwise run these grants manually.
CREATE ROLE asa_analysis_reader NOLOGIN;
GRANT USAGE ON SCHEMA call_public TO asa_analysis_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA call_public TO asa_analysis_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA call_public
  GRANT SELECT ON TABLES TO asa_analysis_reader;
```

Do not grant analysis/external readers write access or direct `call_core`
access. The default service path should still use the call-processing API.

4. Start call-processing service first:

```bash
docker compose --profile split up -d call_processing_api call_processing_worker
```

5. Run call-processing health:

```bash
docker compose exec -T call_processing_api curl -f http://localhost:8000/call-processing/health
```

6. Run dry-run for the pilot scope:

```bash
export CALL_PROCESSING_GRANT_JSON='{"client_id":"edo-analysis-reporting","client_type":"service","role":"admin","allowed_artifact_kinds":["transcript","transcript_segments","llm1_first_pass"],"read_surfaces":["processed_calls_v1","transcripts_v1","llm1_artifacts_v1","processing_runs_v1"],"created_by_admin":"operator","active":true}'
export CALL_PROCESSING_SCOPE_JSON="{\"department_id\":\"$DEPARTMENT_ID\",\"date_from\":\"$REPORT_DATE\",\"date_to\":\"$REPORT_DATE\",\"source\":\"onlinepbx\"}"

docker compose exec -T call_processing_api python -m app.agents.call_processing.cli \
  --grant "$CALL_PROCESSING_GRANT_JSON" \
  dry-run \
  --scope "$CALL_PROCESSING_SCOPE_JSON" \
  --required-artifacts transcript,transcript_segments,llm1_first_pass
```

7. Run ensure for the same scope only after dry-run looks sane:

```bash
docker compose exec -T call_processing_api python -m app.agents.call_processing.cli \
  --grant "$CALL_PROCESSING_GRANT_JSON" \
  ensure \
  --scope "$CALL_PROCESSING_SCOPE_JSON" \
  --required-artifacts transcript,transcript_segments,llm1_first_pass
```

8. Start analysis service in external mode:

```bash
docker compose --profile split up -d analysis_api analysis_worker analysis_beat
```

9. Run manager_daily preview smoke:

```bash
docker compose exec -T analysis_api env CALL_PROCESSING_MODE=external_service \
  python -m app.agents.calls.manual_reporting_runner \
  --department-id "$DEPARTMENT_ID" \
  --preset manager_daily \
  --mode build_missing_and_report \
  --date-from "$REPORT_DATE" \
  --date-to "$REPORT_DATE" \
  --delivery-mode preview_only
```

10. Review `observability`:
   - source completeness;
   - `call_processing_mode=external_service`;
   - no reporting-local STT/LLM1 execution;
   - no unexpected `llm1_first_pass_missing`;
   - no unexpected `source_artifacts_updated_after_analysis`.

11. Only after preview approval, resume scheduled/report delivery.

## Rollback Steps

Rollback does not require deleting call-processing artifacts.

1. Stop split analysis services:

```bash
docker compose stop analysis_api analysis_worker analysis_beat
```

2. Return runtime to legacy:

```bash
APP_SERVICE=monolith_legacy
CALL_PROCESSING_MODE=legacy
```

3. Start/confirm legacy services:

```bash
docker compose up -d api worker beat
```

4. Run legacy manager_daily preview:

```bash
docker compose exec -T api env CALL_PROCESSING_MODE=legacy \
  python -m app.agents.calls.manual_reporting_runner \
  --department-id "$DEPARTMENT_ID" \
  --preset manager_daily \
  --mode build_missing_and_report \
  --date-from "$REPORT_DATE" \
  --date-to "$REPORT_DATE" \
  --delivery-mode preview_only
```

5. Keep `call_core` artifacts for audit. Do not delete schemas/tables/artifacts
   unless explicitly approved.

## Known Failure Modes

| Symptom | Meaning | Operator action |
| --- | --- | --- |
| `llm1_first_pass_missing` | Call has transcript but upstream LLM1 artifact is not ready | Run/repair call-processing ensure for the scope; do not force analysis to invent LLM1 |
| `llm1_first_pass_invalid` | Upstream LLM1 artifact violates contract | Inspect artifact payload, fix upstream writer, rerun ensure |
| `transcript_missing_external_service` | Analysis saw a call without transcript in external mode | Repair call-processing STT/source artifact; reporting must not run local STT |
| `source_artifacts_updated_after_analysis` | Upstream artifact changed after EDO analysis was created | Admin decides whether to rerun analysis for that scope |
| `call_processing_ensure_failed` | Client/service ensure failed before report build | Check call-processing API/service logs and run dry-run manually |
| quota/provider blocker | Provider quota, per-run provider-call budget, or rate limit stopped upstream work | Resolve provider/account issue or increase grant `rate_limits.provider_calls_per_run`, then force retry through approved admin flow |

## Admin Rerun Rule

Late artifacts never trigger automatic EDO analysis rerun.

When `source_artifacts_updated_after_analysis` appears:

1. Identify affected `interaction_id` values in run errors/build summary.
2. Confirm upstream artifact is correct and newer than analysis.
3. Rerun analysis manually for the selected manager/day or exact interaction
   scope with `--force-rebuild-analyses`, for example:

   ```bash
   docker compose exec -T api python -m app.agents.calls.manual_reporting_runner \
     --department-id <department_uuid> \
     --preset manager_daily \
     --mode build_missing_and_report \
     --date-from <YYYY-MM-DD> \
     --date-to <YYYY-MM-DD> \
     --manager-extension <ext> \
     --force-rebuild-analyses \
     --no-delivery
   ```

4. Confirm the new run supersedes the stale analysis in reporting.

## Handoff For Next Agent

Start here:

1. `docs/call_processing_split/IMPLEMENTATION_STATUS.md`
2. `docs/call_processing_split/VERIFICATION_PACK.md`
3. this runbook
4. `docs/call_processing_split/IMPLEMENTATION_TASK_PACK_FOR_AGENTS.md`

Do not perform production cutover or destructive DB actions without explicit
operator approval.
