# Call-processing / analysis split verification pack

Date: 2026-06-13  
Branch: `feat/call-processing-analysis-split`  
Last verified implementation commit: `fc6ec42`

## Purpose

This pack makes release checks reproducible for the service split:

- `call-processing` owns source/STT/LLM1 artifacts;
- `analysis` consumes those artifacts and owns EDO LLM2/LLM3/reporting;
- legacy monolith rollback remains available through
  `APP_SERVICE=monolith_legacy` and `CALL_PROCESSING_MODE=legacy`.

Do not mark an item green unless the command was actually run.

## Acceptance Matrix

| Area | Required checks | Current coverage |
| --- | --- | --- |
| DB | additive schemas, tables, views, no destructive legacy changes | `test_call_processing_db_contract.py` |
| Processing | ensure idempotency, transcript backfill, dry-run no writes, retry/stale helpers | `test_call_processing_service.py` |
| API/Auth | health, ensure, run status, artifact read, admin/reader grant matrix | `test_call_processing_api.py`, `test_call_processing_cli.py` |
| LLM1 contract | external mode requires ready `llm1_first_pass_v1`, invalid/missing fail closed | `test_call_processing_llm1_external_mode.py`, `test_call_processing_client.py` |
| Analysis integration | reporting external mode does not run local STT/LLM1, partial LLM1 missing is visible, late artifacts are marked | `test_call_processing_reporting_integration.py` |
| Reporting | manager daily legacy branches preserved; ROP weekly remains persisted-only | focused `test_manual_reporting.py` commands below |
| Runtime | service-specific env, queue routing, compose profile validation | `test_call_processing_runtime_split.py`, `docker compose config` |
| Rollback | legacy mode still runs old analyzer path | `test_call_processing_llm1_external_mode.py`, legacy reporting focused checks |

## Copy-paste Verification Commands

Run from repo root.

```bash
python3 -m py_compile \
  core/app/agents/call_processing/*.py \
  core/app/agents/calls/reporting.py \
  core/app/agents/calls/manual_reporting_runner.py \
  core/app/agents/calls/orchestrator.py \
  core/app/agents/calls/analyzer.py \
  core/report_scripts/call_processing_cli.py \
  core/app/core_shared/config/settings.py \
  core/app/core_shared/workers/celery_app.py
```

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

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_manual_reporting.py \
  -k "prepare_artifacts_persists_contract_validation_failure_as_analysis_error or prepare_artifacts_stops_llm_after_quota_and_keeps_transcript or prepare_artifacts_skips_audio_build_for_source_only_calls or prepare_artifacts_refreshes_onlinepbx_audio_url_before_stt or prepare_artifacts_records_source_audio_unavailable_when_refresh_fails"
```

```bash
docker compose config >/tmp/asa_compose_config.out
docker compose --profile split config >/tmp/asa_compose_split_config.out
git diff --check
```

## Local Smoke Commands

Legacy rollback smoke:

```bash
APP_SERVICE=monolith_legacy CALL_PROCESSING_MODE=legacy \
docker compose up -d api worker beat
```

Split compose smoke:

```bash
docker compose --profile split up -d \
  call_processing_api call_processing_worker \
  analysis_api analysis_worker analysis_beat
```

Call-processing contract smoke:

```bash
export CALL_PROCESSING_GRANT_JSON='{"client_id":"edo-analysis-reporting","client_type":"service","role":"admin","allowed_artifact_kinds":["transcript","transcript_segments","llm1_first_pass"],"read_surfaces":["processed_calls_v1","transcripts_v1","llm1_artifacts_v1","processing_runs_v1"],"created_by_admin":"operator","active":true}'
export CALL_PROCESSING_SCOPE_JSON="{\"department_id\":\"$DEPARTMENT_ID\",\"date_from\":\"2026-06-03\",\"date_to\":\"2026-06-03\",\"source\":\"onlinepbx\"}"

docker compose exec -T api python -m app.agents.call_processing.cli \
  --grant "$CALL_PROCESSING_GRANT_JSON" \
  dry-run \
  --scope "$CALL_PROCESSING_SCOPE_JSON" \
  --required-artifacts transcript,transcript_segments,llm1_first_pass
```

Manager daily external-service smoke must be run only after upstream artifacts
exist for the target scope:

```bash
CALL_PROCESSING_MODE=external_service \
docker compose exec -T api python -m app.agents.calls.manual_reporting_runner \
  --department-id "$DEPARTMENT_ID" \
  --preset manager_daily \
  --mode build_missing_and_report \
  --date-from 2026-06-03 \
  --date-to 2026-06-03 \
  --delivery-mode preview_only
```

## Verification Report

Latest checks run during implementation:

| Check | Result |
| --- | --- |
| `test_call_processing_reporting_integration.py` | `6 passed` |
| `test_call_processing_manual_pilot_boundary.py` | `1 passed` |
| `test_call_processing_manual_reporting_runner.py` | `1 passed` |
| `test_call_processing_runtime_split.py` | `4 passed` |
| focused call-processing/analyzer pack after retry-failed recovery pass | `67 passed` |
| focused AI routing/settings pack | `48 passed` |
| legacy prepare-artifacts + scheduled/reviewable focused checks | `28 passed, 217 deselected` |
| `docker compose config` | passed |
| `docker compose --profile split config` | passed |
| `git diff --check` | passed |

Known non-green / not-yet-final items:

- Production cutover was not executed.
- Provider-backed OnlinePBX/STT/LLM1 first pass is implemented in the local
  call-processing service and covered with fake providers; live split-worker
  smoke and production scheduling remain.
- ROP weekly and scheduled reviewable reporting have focused tests green, but
  have not yet had a full external-service live smoke with real artifacts.
- Broad semantic-empty reporting tests depend on current runtime config and are
  not the acceptance gate for this split.
