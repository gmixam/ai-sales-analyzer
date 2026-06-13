# Call-processing / analysis split acceptance audit

Date: 2026-06-13  
Branch: `feat/call-processing-analysis-split`  
Audited commit: `a26d9cd`

## Summary

The split is implemented and locally verified as code/runtime configuration.
Production cutover is not executed. Live provider-backed split smoke and live
DB migration smoke remain explicit release-time actions because they can change
production state or spend provider budget.

## Whole Release DoD

| Requirement | Status | Evidence |
| --- | --- | --- |
| `call-processing` and `analysis` can run as separate services/workers | `locally_verified` | Split Docker profile and service-specific settings; `docker compose --profile split config` passed. |
| Shared PostgreSQL is logically separated by schemas and ownership | `implemented_local` | Migration creates `call_core`, `call_public`, `analysis`, `org`; optional read-only `call_public` grant pattern for `asa_analysis_reader`. |
| `call-processing` persists transcripts, transcript segments and LLM-1 artifacts | `locally_verified` | `CallProcessingService` tests cover STT transcript/segments and `llm1_first_pass_v1` writes with fake providers. |
| `analysis` consumes artifacts via client/API/read views in external mode | `locally_verified` | `CallProcessingClient`, HTTP/local reads, LLM1 adapter, manager daily external-service tests. |
| `analysis` does not call STT/LLM-1 providers in external mode | `locally_verified` | External-mode analyzer/reporting tests fail closed on missing/invalid artifacts and assert no local STT path. |
| Current pilot reporting flows still work | `locally_verified` | Manager daily integration, manual runner boundary, legacy focused reporting checks. |
| Reports can be generated on partial data | `locally_verified` | Missing LLM1/source artifact tests expose partial source status without crashing. |
| Missing/incomplete source artifacts are visible | `locally_verified` | `llm1_first_pass_missing`, `llm1_first_pass_invalid`, `transcript_missing_external_service`, `call_processing_ensure_failed`. |
| Late artifacts mark affected downstream analysis scope | `locally_verified` | `source_artifacts_updated_after_analysis` and force rebuild tests. |
| Admin can manually rerun analysis after late artifacts | `locally_verified` | `manual_reporting_runner --force-rebuild-analyses` tests supersede late marker. |
| Admin-only `ensure`, `dry_run`, `force_retry_failed` are enforced | `locally_verified` | API/CLI admin-reader matrix tests. |
| Reader clients can only read allowed artifacts/surfaces | `locally_verified` | Artifact route filtering and grant tests. |
| Retry policy matches approved defaults | `locally_verified` | Retryable/non-retryable error tests, `MAX_PROVIDER_ATTEMPTS=3`, stale run detection. |
| Quota exhaustion pauses processing and exposes admin action | `locally_verified` | Per-run provider-call budget from `AccessGrant.rate_limits`; quota tests cover OnlinePBX source and STT billable-call blocking. |
| Docker/runtime config supports separate services and legacy rollback | `locally_verified` | `APP_SERVICE`, `CALL_PROCESSING_MODE`, queue routing, compose config, rollback commands. |
| Full test matrix passes | `local_acceptance_passed` | Focused split pack `73 passed`; AI routing/settings `48 passed`; legacy reporting focused `28 passed, 217 deselected`; `git diff --check`; compose config. |
| Cutover and rollback runbooks exist and were smoke-validated | `runbook_ready_local_smoke` | Runbook exists; copy-paste CLI smoke commands validated locally. Production execution not performed. |

## Verification Run

- `python3 -m py_compile ...` for changed call-processing/API/test modules:
  passed.
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_contracts.py /app/tests/test_call_processing_service.py /app/tests/test_call_processing_api.py /app/tests/test_call_processing_cli.py`
  -> `34 passed`.
- Focused split pack:
  `test_call_processing_contracts.py`,
  `test_call_processing_db_contract.py`,
  `test_call_processing_service.py`,
  `test_call_processing_api.py`,
  `test_call_processing_cli.py`,
  `test_call_processing_llm1_external_mode.py`,
  `test_call_processing_client.py`,
  `test_call_processing_reporting_integration.py`,
  `test_call_processing_manual_pilot_boundary.py`,
  `test_call_processing_manual_reporting_runner.py`,
  `test_call_processing_runtime_split.py`,
  `test_llm2_layered_runtime.py`
  -> `73 passed`.
- `test_ai_provider_routing.py -k "settings or routing or compact_llm2 or llm2_compact_profile"`
  -> `48 passed`.
- Legacy reporting focused checks:
  -> `28 passed, 217 deselected`.
- `docker compose config` and `docker compose --profile split config`:
  passed.
- `git diff --check`:
  passed.

## Release-time Actions Not Executed

These are intentionally not executed without operator approval:

- Apply split migration to production and run live migration up/down smoke.
- Create/assign production SQL role(s), including `asa_analysis_reader`, if SQL
  read-only access is approved.
- Start split services against live provider credentials and run a provider-backed
  OnlinePBX/STT/LLM1 smoke.
- Run full `manager_daily` external-service preview with real artifacts.
- Run ROP weekly and scheduled reviewable external-service smoke with real
  artifacts.
- Resume production scheduled delivery.

## Release Recommendation

Use this branch as the release candidate for an operator-controlled cutover
rehearsal. Start with the runbook in
`docs/call_processing_split/CUTOVER_ROLLBACK_RUNBOOK.md`; do not enable
production delivery until the live smoke steps above are green.
