# ТЗ: полное разделение call-processing и EDO analysis services

Дата: 2026-06-05

## Назначение документа

Этот документ задает техническое задание на один полный релиз, после которого:

- `call-processing service` работает как боевой upstream-сервис исходников звонков;
- `EDO analysis service` работает как боевой downstream-клиент этих исходников;
- другие команды могут получать доступ к STT/LLM-1 артефактам без доступа к внутренним таблицам и без влияния на пилот ЭДО;
- текущий пилот ЭДО продолжает работать через новую архитектуру без потери звонков, дублей и ручного восстановления.

Это не план поэтапного MVP. Частичная приемка не допускается: релиз считается завершенным только когда оба сервиса готовы к боевой эксплуатации и текущий EDO pilot flow проходит через новый сервисный контракт.

## Текущее состояние, от которого отталкиваемся

Кодовый репозиторий: `gmixam/ai-sales-analyzer`.

Актуальные связки в текущем коде:

- `core/app/agents/calls/extractor.py`
  - `CallsExtractor` владеет audio download, STT и сохранением transcript в `interactions.text`;
- `core/app/agents/calls/analyzer.py`
  - `CallsAnalyzer.analyze_call()` сначала запускает `LLM-1`, затем `LLM-2`;
  - `LLM-1` сейчас transient step внутри analyzer runtime;
- `core/app/agents/calls/reporting.py`
  - `CallsManualReportingOrchestrator` создает `OnlinePBXIntake`, `CallsExtractor`, `CallsAnalyzer`, `CallsDelivery`, `CallsManualPilotOrchestrator`;
  - `manager_daily/build_missing_and_report` может выполнить полный upstream+downstream chain:
    `source discovery -> ingest -> audio -> STT -> LLM-1 -> LLM-2 -> persistence -> report -> delivery`;
- `docker-compose.yml`
  - сейчас один `api`, один `worker`, один `beat`, общий `postgres`, общий `redis`.

Проблема: reporting/analysis layer остается владельцем source/audio/STT/LLM-1, поэтому другие команды не могут использовать единый сервис исходников, а падение одного контура затрудняет добор missing artifacts.

## Целевое состояние

### Сервис 1: `call-processing`

Боевой upstream-сервис, который владеет:

- discovery звонков из OnlinePBX и будущих источников;
- фильтрацией source-level звонков;
- маппингом звонка на department/manager/extension;
- idempotent persistence source calls;
- refresh/download audio;
- STT;
- transcript segments;
- LLM-1 first pass;
- retry/reconciliation по incomplete artifacts;
- read-only выдачей готовых STT/LLM-1 артефактов клиентам;
- audit/observability по source/STT/LLM-1.

Не владеет:

- EDO-specific checklist scoring;
- LLM-2 approved analyzer contract;
- daily/weekly report assembly;
- PDF rendering;
- Telegram/email delivery отчетов;
- правками business-facing report text.

### Сервис 2: `edo-analysis`

Боевой downstream-сервис, который владеет:

- EDO-specific LLM-2 / approved analyzer contract;
- EDO daily/weekly reporting;
- readiness/reuse для EDO analysis artifacts;
- PDF/report template rendering;
- scheduled reviewable reporting для EDO;
- Telegram/email delivery для EDO;
- CLI/API entrypoints for EDO report runs and admin operations.

Не владеет:

- OnlinePBX discovery;
- audio URL refresh/download;
- STT credentials;
- LLM-1 credentials;
- core transcript persistence;
- source-call idempotency.

### Другие команды

Другие команды считаются такими же downstream-клиентами, как `edo-analysis`.

Они могут:

- запрашивать добор source/STT/LLM-1 артефактов по своему scope;
- читать готовые `transcript` и `llm1` артефакты;
- строить свои downstream analyses.

Они не могут:

- писать в core call-processing tables;
- менять transcript/segments/LLM-1 payload;
- запускать source/STT/LLM-1 напрямую в обход `call-processing`;
- получать данные чужих departments без явного grant.

## Архитектурный принцип релиза

Физически допускается один PostgreSQL и один Redis, но ownership должен быть сервисным.

Рекомендуемый production baseline:

```text
PostgreSQL
├─ call_core        -- owned by call-processing service
├─ call_public      -- read-only stable views/API-facing read models
├─ analysis         -- owned by analysis services, including EDO analysis
└─ org              -- shared org/manager mapping with controlled writes
```

Запрещено:

- давать downstream-командам write-доступ в `call_core`;
- делать `edo-analysis` owner-ом STT/LLM-1 таблиц;
- держать `LLM-1` только transient context внутри `CallsAnalyzer`;
- оставлять `reporting.py` прямым владельцем `OnlinePBXIntake` / `CallsExtractor` / source build.

## Сервисные контракты

### Control API: ensure/reconciliation

`call-processing` должен принимать запрос на гарантированный добор артефактов:

```http
POST /call-processing/ensure
```

Request:

```json
{
  "requested_by": "edo-analysis",
  "scope": {
    "department_code": "EDO",
    "department_id": "uuid",
    "date_from": "2026-06-01",
    "date_to": "2026-06-05",
    "manager_ids": ["uuid"],
    "extensions": ["322"],
    "min_duration_sec": 60,
    "max_duration_sec": null
  },
  "required_artifacts": ["transcript", "llm1"],
  "mode": "ensure_missing",
  "force_retry_failed": false,
  "include_failed_statuses": true
}
```

Response:

```json
{
  "run_id": "uuid",
  "status": "queued|running|ready|partial|blocked|failed",
  "scope_hash": "stable-hash",
  "requested_by": "edo-analysis",
  "accepted_at": "ISO-8601",
  "summary": {
    "source_calls_found": 0,
    "interactions_created": 0,
    "interactions_reused": 0,
    "transcripts_ready": 0,
    "llm1_ready": 0,
    "failed": 0
  }
}
```

### Run status API

```http
GET /call-processing/runs/{run_id}
```

Response must include:

- current status;
- per-stage counts;
- errors grouped by reason;
- artifacts ready count;
- failed/stale count;
- whether downstream can proceed with partial artifacts.

### Artifact read API

```http
GET /call-processing/artifacts
```

Query parameters:

- `department_id` or `department_code`;
- `date_from`;
- `date_to`;
- optional `manager_ids`;
- optional `extensions`;
- `required_artifacts=transcript,llm1`;
- `include_failed=true|false`.

Response:

```json
{
  "items": [
    {
      "interaction_id": "uuid",
      "source": "onlinepbx",
      "external_id": "source-call-id",
      "department_id": "uuid",
      "manager_id": "uuid|null",
      "extension": "322",
      "call_date": "ISO-8601",
      "duration_sec": 120,
      "source_status": "answered",
      "processing_status": "llm1_ready",
      "transcript": {
        "status": "ready",
        "version": "stt_contract_v1",
        "text": "...",
        "segments": [],
        "provider": "openai",
        "model": "whisper-1"
      },
      "llm1": {
        "status": "ready",
        "version": "llm1_first_pass_v1",
        "payload": {
          "classification": {},
          "summary": {},
          "follow_up": {},
          "data_quality": {},
          "analysis_focus": []
        },
        "provider": "openai",
        "model": "..."
      },
      "audit": {
        "ai_routing": {},
        "processed_at": "ISO-8601",
        "errors": []
      }
    }
  ],
  "summary": {
    "source_calls_found": 0,
    "transcripts_ready": 0,
    "llm1_ready": 0,
    "partial": 0,
    "failed": 0
  }
}
```

### Internal client contract for `edo-analysis`

`edo-analysis` must use a client abstraction instead of importing upstream internals:

```python
class CallProcessingClient:
    def ensure_processed_calls(scope, required_artifacts) -> ProcessingRunResult: ...
    def get_processed_artifacts(scope, required_artifacts) -> list[ProcessedCallArtifact]: ...
```

`edo-analysis` must not import:

- `OnlinePBXIntake`;
- `CallsExtractor`;
- STT provider adapters;
- `_request_llm1_first_pass`;
- source audio URL refresh helpers.

## Database requirements

### `call_core.interactions`

Existing `interactions` can remain the base table, but must be treated as owned by call-processing.

Required invariants:

- unique key: `(source, external_id)`;
- every row has `department_id`;
- `metadata` must preserve source metadata and audit;
- source call ingest is idempotent;
- updating `raw_ref`, source metadata, transcript and processing status is call-processing responsibility only.

### `call_core.call_processing_runs`

New table.

Fields:

- `id`;
- `requested_by`;
- `scope_json`;
- `scope_hash`;
- `required_artifacts`;
- `mode`;
- `status`;
- `started_at`;
- `finished_at`;
- `counts_json`;
- `errors_json`;
- `created_at`;
- `updated_at`.

Purpose:

- durable recovery after service crash;
- operator/client observability;
- deduplication of identical in-flight ensure requests when needed.

### `call_core.call_artifacts`

New table for transcript/LLM-1 artifacts.

Fields:

- `id`;
- `department_id`;
- `interaction_id`;
- `artifact_kind`: `transcript|transcript_segments|llm1_first_pass`;
- `artifact_version`;
- `status`: `ready|missing|processing|failed|skipped|stale`;
- `payload_json`;
- `text_value` for transcript text when useful;
- `provider`;
- `model`;
- `account_alias`;
- `api_key_env`;
- `raw_response_ref` or bounded raw response field if safe;
- `error_reason`;
- `created_at`;
- `updated_at`.

Required:

- one active artifact per `interaction_id + artifact_kind + artifact_version`;
- old versions may remain for audit but read API must expose active/effective version.

### `call_public` read models

Create stable read-only views:

- `call_public.processed_calls_v1`;
- `call_public.transcripts_v1`;
- `call_public.llm1_artifacts_v1`;
- `call_public.processing_runs_v1`.

Rules:

- downstream teams receive read-only access only to `call_public`;
- row-level security or scoped views must restrict departments;
- no team writes through these views;
- view contracts are versioned and must not change silently.

### `analysis`

Existing `analyses`, reports, scheduled draft tables may stay in current schema initially, but ownership must be explicit:

- EDO service writes EDO `analyses`;
- EDO service writes report runs/artifacts;
- EDO service reads `call_public` or `call-processing` API;
- EDO service does not mutate `call_core.call_artifacts`.
- The logical analysis schema is named `analysis`, so future non-EDO analysis clients can use the same namespace pattern without a schema rename.

## Recovery and failure behavior

The release must support service failure without manual data repair.

Required behavior:

- repeated `ensure` for the same scope rescans source period;
- source calls are upserted by `(source, external_id)`;
- missing transcript is built;
- missing LLM-1 is built;
- failed artifacts are retried only when retry policy allows or an admin explicitly runs `force_retry_failed=true`;
- stale/incomplete in-flight jobs are reclaimed by lease/timeout;
- provider quota failures are persisted with provider/account/model metadata, pause further billable call-processing work, and notify admin;
- downstream reports can proceed with the artifacts that are ready, using the existing analysis/reporting rules;
- run status must show whether not all calls in the selected scope were transcribed or enriched with LLM-1, so admin can run a later retry and downstream analysis/reporting can be rerun after new artifacts appear.

Approved recovery defaults:

- stale job means no heartbeat/progress for 30 minutes;
- `STT` max attempts: initial attempt + 2 retry attempts;
- `LLM-1` max attempts: initial attempt + 2 retry attempts;
- retry applies only to transient provider/network classes: `provider_timeout`, `rate_limited`, `provider_5xx`;
- `quota_insufficient` gets 0 automatic retries, pauses further billable processing, and notifies admin;
- `auth_error` gets 0 automatic retries, pauses the affected provider/account, and notifies admin;
- `source_audio_expired` / `source_audio_missing` gets 0 automatic retries until source refresh or admin action;
- `force_retry_failed=true` is admin-only.

Late artifact rule:

- if new transcript or LLM-1 artifacts become ready after a downstream analysis/report was already produced for the same scope, mark the affected downstream scope as `source_artifacts_updated_after_analysis`;
- no automatic report rebuild is required;
- admin manually decides whether to rerun analysis/reporting.

Recommended state machine:

```text
source_found
interaction_persisted
audio_ready
transcript_processing
transcript_ready
llm1_processing
llm1_ready
failed
stale
```

No state transition may require deleting and recreating an interaction.

## EDO analysis/reporting requirements

`edo-analysis` must keep the existing business behavior:

- `manager_daily`;
- `rop_weekly`;
- `scheduled_reviewable_reporting`;
- active templates:
  - `manager_daily_template_v2`;
  - `rop_weekly_template_v1`;
- explicit Telegram test delivery;
- optional business email delivery;
- review-required scheduled drafts.

Required changes:

- `manager_daily/build_missing_and_report` calls `CallProcessingClient.ensure_processed_calls(...)`;
- `report_from_ready_data_only` may call source ensure with `required_artifacts=[]` or read-only mode only if existing behavior requires source discovery; it must not trigger new STT/LLM-1;
- EDO LLM-2 analysis reads `llm1_first_pass` from `call-processing` artifact, not from a new internal LLM-1 request;
- EDO readiness uses:
  - transcript readiness from call-processing;
  - LLM-1 readiness from call-processing;
  - EDO analysis readiness from `analysis`;
- `rop_weekly` remains persisted-only for EDO analysis/reporting and must not trigger upstream build unless explicitly required by a new business rule.

## Service packaging and deployment requirements

Docker Compose must include separate runtime services:

```text
call_processing_api
call_processing_worker
analysis_api
analysis_worker
beat
postgres
redis
flower
nginx
```

Acceptable simplification:

- both services may share the same code image initially if commands/env/queues are separated;
- both services may share PostgreSQL and Redis;
- both services must have separate service accounts and env scopes.

Required queue separation:

- `call_processing` queue for source/audio/STT/LLM-1;
- `analysis` queue for LLM-2/report/render/delivery;
- `default` only for shared low-risk tasks.

Required env separation:

`call-processing` gets:

- OnlinePBX credentials;
- STT provider credentials;
- LLM-1 provider credentials;
- DB user with write access to `call_core` and read access to `org`;
- no EDO LLM-2/report delivery credentials.

`edo-analysis` gets:

- EDO LLM-2 provider credentials;
- report renderer/delivery credentials;
- DB user with write access to `analysis`, read access to `call_public` and `org`;
- no OnlinePBX/STT/LLM-1 credentials.

## Access model for other teams

Other teams may access STT/LLM-1 source artifacts in two supported ways:

1. API access:
   - `POST /call-processing/ensure`;
   - `GET /call-processing/artifacts`;
   - scoped by service account or employee account.

2. SQL read-only access:
   - only `call_public.*`;
   - service/employee-specific grants or views;
   - no direct access to `call_core`.

Every external client must have:

- `client_id`;
- client type: `service` or `employee`;
- role: `admin` or `reader`;
- allowed artifact kinds and read surfaces;
- rate limits;
- audit logging for ensure/read requests.

Access rule:

- admin can configure access and run billable/processing actions such as `ensure`, `dry_run`, and `force_retry_failed`;
- non-admin service/employee accounts are read-only;
- access is not scoped by department by default.

## API/security requirements

Required:

- service-to-service auth for `edo-analysis -> call-processing`;
- API token or internal auth header for other clients;
- server-side validation by service/employee grant and role;
- no secrets in response payloads;
- no raw provider API keys in metadata;
- PII exposure controlled by service/employee access grants;
- audit log for each external artifact read.

## Observability requirements

`call-processing` must expose:

- health endpoint;
- queue depth for call-processing tasks;
- per-run status;
- stage counts:
  - source scanned;
  - interactions created/reused;
  - audio ready/failed;
  - transcripts ready/failed;
  - LLM-1 ready/failed;
- provider/account/model selected per artifact;
- quota/rate/auth/provider errors as structured reason codes;
- stale job detection.

`edo-analysis` must expose:

- report run status;
- call-processing run reference;
- EDO analysis counts;
- rendered artifact status;
- Telegram/email delivery status;
- scheduled draft status.

No new UI is required for this release. Operational interaction with the split services is CLI-first; API endpoints may exist for service operation and smoke checks, but the acceptance criteria do not require a new operator screen.

## Cost and quota requirements

Admin owns STT/LLM-1 cost and quota control.

Required:

- only admin can launch billable `ensure` runs that build STT/LLM-1 artifacts;
- only admin can run `dry_run` / estimate before a billable processing run;
- only admin can run `force_retry_failed=true`;
- reader service/employee accounts cannot start billable processing;
- when quota is exhausted, call-processing must:
  - persist structured quota status;
  - pause further billable processing;
  - notify admin;
  - leave downstream analysis/reporting to use whatever artifacts are already ready.

## Retention and PII requirements

Current approved policy: store call-processing artifacts indefinitely until a future explicit retention/compliance decision changes this.

Required:

- keep transcripts, transcript segments, LLM-1 artifacts, processing metadata, and analysis artifacts without automatic deletion;
- do not add masking/redaction requirements in this release;
- do not expose secrets or raw provider API keys in public views/API responses;
- access to artifacts is controlled by service/employee grants and role.

## RAG/vector extensibility

RAG/vector DB is not part of the release acceptance criteria.

Required extensibility:

- keep stable `interaction_id`;
- keep transcript/segment artifacts versioned;
- keep LLM-1 artifacts versioned;
- do not make retrieval the source of truth for scoring or reporting;
- leave room for future embeddings tables, preferably `pgvector` in PostgreSQL if/when semantic search or knowledge-base grounding becomes a proven requirement.

## Code changes required

All items below are in scope for the single full release.

### New modules

- `core/app/agents/call_processing/`
  - `service.py`
  - `client.py`
  - `api.py`
  - `tasks.py`
  - `schemas.py`
  - `artifacts.py`
  - `reconciliation.py`
  - `permissions.py`

### Refactored modules

- `core/app/agents/calls/extractor.py`
  - move STT execution under call-processing service ownership;
  - preserve existing provider routing behavior;
  - write transcript artifacts to `call_core.call_artifacts`.

- `core/app/agents/calls/analyzer.py`
  - split LLM-1 first-pass execution from EDO LLM-2 analysis;
  - expose LLM-1 through call-processing service;
  - make EDO LLM-2 accept persisted `llm1_first_pass`.

- `core/app/agents/calls/reporting.py`
  - remove direct source/audio/STT/LLM-1 ownership;
  - call `CallProcessingClient`;
  - keep EDO report payload/render/delivery behavior stable.

- `core/app/core_shared/api/routes/pipeline.py`
  - route EDO reporting through new client;
  - add or mount call-processing routes separately.

- `core/app/core_shared/workers/tasks.py`
  - register separate call-processing and EDO queues/tasks.

- `docker-compose.yml`
  - add separated api/worker services and queues.

### Migrations

Add Alembic migrations for:

- `call_processing_runs`;
- `call_artifacts`;
- `call_public` views;
- required indexes;
- service-account grants if managed in SQL;
- optional schema creation for `call_core`, `call_public`, `analysis`.

Required indexes:

- `(source, external_id)` unique;
- `(department_id, call_date)` for source-period reads;
- `(interaction_id, artifact_kind, artifact_version)`;
- `(scope_hash, status)` for run dedupe/observability;
- `(department_id, manager_id, call_date)` for client artifact reads.

## Compatibility requirements

Existing EDO pilot behavior must remain available after the release:

- current `manager_daily` and `rop_weekly` API/CLI contracts must not break;
- no new operator UI is required for the split; admin/operator interaction for the split is CLI-first;
- existing report templates remain active;
- existing scheduled reviewable reporting remains review-required and does not auto-send business delivery;
- existing persisted interactions/analyses must be readable after migration;
- existing transcripts in `interactions.text` must be backfilled or exposed as transcript artifacts.

Backfill requirement:

- create `transcript` artifact rows for interactions that already have `interactions.text`;
- create `transcript_segments` artifacts from `interactions.metadata.segments` when present;
- do not fabricate LLM-1 artifacts for old analyses unless existing metadata contains a valid LLM-1 payload;
- old interactions without LLM-1 remain `llm1_missing` and can be rebuilt by `ensure`.

## Pilot cutover requirements

The pilot should not lose data or require manual DB repair. A short planned operational window without launching new reports is allowed for cutover, migration, smoke checks, and rollback validation.

Before cutover:

- run data migration/backfill;
- verify call-processing `ensure` on EDO department and pilot manager scope;
- verify EDO report run uses `CallProcessingClient`;
- verify no duplicate interactions after repeated ensure;
- verify no direct STT/LLM-1 call from `edo-analysis`;
- verify scheduled reviewable reporting still produces review-required draft.

Cutover rule:

- EDO pilot traffic must use the new `call-processing` contract.
- Legacy direct source/STT/LLM-1 path may remain only as rollback code path behind a disabled feature flag.
- Rollback must not require DB rollback; it may reuse call-processing-produced artifacts.
- Feature flag: `CALL_PROCESSING_MODE=legacy|external_service`.
- During the planned cutover window, new report launches may be paused; existing persisted artifacts and reports must remain readable.

## Testing requirements

### Unit tests

Required coverage:

- scope normalization and `scope_hash`;
- idempotent source upsert by `(source, external_id)`;
- artifact version selection;
- transcript artifact write/read;
- LLM-1 artifact write/read;
- failed/stale artifact retry policy;
- `CallProcessingClient` contract;
- EDO analysis receives persisted LLM-1 and does not call `_request_llm1_first_pass`;
- read-only view serialization;
- service/employee grant and admin/reader role permission checks.

### Integration tests

Required scenarios:

- `ensure` creates missing interactions and artifacts;
- repeated `ensure` creates no duplicates;
- STT failure is persisted and surfaced as structured blocker;
- LLM-1 failure is persisted and surfaced as structured blocker;
- partial ready artifacts are returned correctly;
- `manager_daily/build_missing_and_report` uses call-processing and then runs EDO LLM-2/report;
- `report_from_ready_data_only` does not trigger STT/LLM-1;
- `rop_weekly` remains persisted-only;
- scheduled reviewable reporting still stops at `review_required`.

### Runtime smoke tests

Required before accepting release:

1. EDO `manager_daily/build_missing_and_report` for known pilot scope:
   - source discovery;
   - missing ingest;
   - transcript/LLM-1 via call-processing;
   - EDO LLM-2;
   - PDF render;
   - Telegram test delivery if explicitly enabled.

2. EDO `manager_daily/report_from_ready_data_only`:
   - no STT;
   - no LLM-1;
   - report from ready artifacts only.

3. EDO `rop_weekly`:
   - no source discovery;
   - no STT/LLM-1;
   - persisted-only report.

4. Other-team read simulation:
   - read `call_public` or API for allowed department;
   - denied for unauthorized department;
   - no write access to `call_core`.

## Production readiness checklist

Release is not complete until all checks pass:

- separated services are present in compose/runtime;
- separated queues are used;
- service accounts have correct DB permissions;
- `call-processing` can recover from failed/interrupted runs;
- `edo-analysis` can run without OnlinePBX/STT/LLM-1 credentials;
- other teams can read only allowed STT/LLM-1 artifacts;
- EDO pilot report flow succeeds through new contract;
- no duplicate interactions after repeated ensure;
- all expected tests pass;
- docs updated in repo and local planning workspace;
- rollback instructions documented.

## Acceptance criteria

The implementation is accepted only when:

1. `call-processing` can independently ensure source calls, transcript, and LLM-1 for all departments.
2. `edo-analysis` uses `call-processing` as a client and no longer runs source/audio/STT/LLM-1 directly.
3. Existing EDO pilot `manager_daily` and `rop_weekly` flows still work.
4. Repeated ensure/read requests are idempotent and do not create duplicates.
5. Service failure can be recovered by rerunning ensure for the same scope.
6. Other teams can get STT/LLM-1 artifacts through API/read-only views with service/employee-level access control and admin-only write/processing actions.
7. Both services have separate runtime commands/queues/env scopes.
8. All migrations, tests, docs, and smoke checks are included in the same release.

## Explicit non-goals

Not part of this release:

- changing the approved EDO analyzer scoring contract;
- redesigning report templates beyond compatibility changes;
- building a generic enterprise data platform;
- giving teams write access to call-processing core tables;
- splitting PostgreSQL into separate physical databases unless needed by deployment constraints;
- changing business email/Telegram delivery semantics outside required compatibility.

## Implementation prompt for the next coding agent

Use this when starting implementation in `gmixam/ai-sales-analyzer`:

> Implement the full call-processing / EDO-analysis service split as one production-ready release. Create a `call-processing` service boundary that owns OnlinePBX source discovery, interaction upsert, audio/STT, transcript artifacts, LLM-1 first-pass artifacts, recovery/reconciliation, read APIs/views, and call-processing queues. Refactor EDO reporting/analysis so it consumes processed call artifacts through a `CallProcessingClient` and no longer imports or directly runs source/audio/STT/LLM-1. Keep existing EDO `manager_daily`, `rop_weekly`, scheduled reviewable reporting, templates, readiness, rendering, and delivery behavior compatible. Add DB migrations, API contracts, read-only views/permissions, Docker/queue separation, tests, runtime smoke checks, and docs. The release is accepted only when both services are production-ready and the current EDO pilot flow runs through the new contract without duplicate calls or missing artifact recovery gaps.
