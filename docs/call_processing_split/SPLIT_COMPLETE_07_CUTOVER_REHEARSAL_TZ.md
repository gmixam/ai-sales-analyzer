# SPLIT-COMPLETE-07 — production cutover rehearsal

Дата подготовки: 2026-06-15
Статус: `draft_for_approval`

## Цель

Провести техническую репетицию production cutover в split-контуре без включения
автоматической бизнес-доставки менеджерам.

Репетиция должна подтвердить, что:

- реальные split env files заполнены и проходят preflight;
- `call-processing` отдельно поднимается и готовит OnlinePBX/STT/LLM1 artifacts;
- `analysis/reporting` отдельно поднимается в
  `CALL_PROCESSING_MODE=external_service`;
- `analysis` строит manager_daily preview только по готовым upstream artifacts и
  не запускает локальные STT/LLM1;
- observability/costs/alerts сохраняются;
- rollback path через monolith/legacy остается рабочим.

Это еще не production cutover и не включение автодоставки. Это controlled
rehearsal с операторским решением `GO/NO-GO` в конце.

## Что обязательно перед стартом

### 1. Git state

- Рабочее дерево должно быть чистым.
- Все изменения SPLIT-COMPLETE-06 должны быть закоммичены.
- Желательно запушить ветку перед rehearsal, чтобы состояние было восстановимо.

Проверки:

```bash
git status --short --branch
git rev-parse --short HEAD
```

### 2. Реальные split env files

Создать реальные файлы из templates:

```bash
cp .env.split.common.example .env.split.common
cp .env.call-processing.example .env.call-processing
cp .env.analysis.example .env.analysis
```

Заполнить вручную вне git:

- `.env.split.common`: DB/Redis/shared runtime values;
- `.env.call-processing`: OnlinePBX, STT, LLM1;
- `.env.analysis`: call-processing API grant, LLM2, LLM3, SMTP/Telegram/alerts.

Запрещено:

- копировать OnlinePBX/STT/LLM1 secrets в `.env.analysis`;
- копировать LLM2/LLM3/business delivery secrets в `.env.call-processing`;
- коммитить реальные `.env.split.common`, `.env.call-processing`,
  `.env.analysis`.

### 3. Target day/scope

Перед rehearsal нужно выбрать контрольный день и менеджеров.

Минимальные требования к дню:

- есть звонки хотя бы у одного пилотного менеджера;
- желательно есть звонки у всех трех: Толеген, Тимур, Алишер;
- дата не должна пересекаться с активной production-доставкой;
- бизнес-доставка менеджерам выключена.

Если нет подтвержденного дня для всех трех менеджеров, rehearsal можно делать на
одном менеджере с понятной фиксацией ограничения.

Переменные:

```bash
export DEPARTMENT_ID=<department_uuid>
export REPORT_DATE=<YYYY-MM-DD>
export MANAGER_IDS=<comma-separated-manager-uuid-list>
```

## Scope

### In scope

- Проверка split env/profile/preflight.
- DB backup before rehearsal.
- Compose config validation.
- Подъем `call_processing_api` / `call_processing_worker`.
- Health check call-processing.
- Call-processing dry-run.
- Call-processing ensure после dry-run approval.
- Подъем `analysis_api` / `analysis_worker`.
- Manager_daily preview/report-only run в external mode.
- Проверка observability:
  - `call_processing_mode=external_service`;
  - external LLM1 artifacts reused;
  - local STT/LLM1 in analysis not executed;
  - `observability.ai_costs`;
  - `observability.alerts`;
  - blocker reasons.
- Rollback smoke или rollback readiness check.

### Out of scope

- Включение business email manager delivery.
- Включение production schedule на автозапуск.
- Ротация секретов.
- Изменение моделей LLM/STT.
- ROP weekly smoke.
- Production GO cutover decision. Это отдельный SPLIT-COMPLETE-08.

## Stop conditions

Остановить rehearsal и не переходить к следующему шагу, если:

- git state dirty до старта;
- split env preflight failed;
- compose split config failed;
- DB backup failed;
- call-processing health failed;
- dry-run показывает неожиданный scope или слишком много provider calls;
- ensure получил repeated provider/quota/auth errors;
- analysis preflight видит upstream secrets;
- analysis logs/observability показывают local STT/LLM1 execution;
- manager_daily preview пытается отправить business email;
- нет понятного rollback path.

При stop condition:

- сохранить команду, вывод и artifact/run id;
- не продолжать ensure/report delivery;
- обновить `COMPLETION_ROADMAP` / `PROGRESS` с blocker;
- при необходимости выполнить rollback steps.

## План работ

### Шаг 1. Preflight env and compose

```bash
docker compose config --no-env-resolution --quiet

docker compose --env-file .env.split.common --profile split \
  config --no-env-resolution --quiet \
  postgres redis \
  call_processing_api call_processing_worker \
  analysis_api analysis_worker analysis_beat
```

Preflight CLI:

```bash
docker compose --env-file .env.split.common --profile split run --rm \
  call_processing_api \
  python report_scripts/split_secret_partitioning_preflight.py \
    --service call-processing --strict

docker compose --env-file .env.split.common --profile split run --rm \
  analysis_api \
  python report_scripts/split_secret_partitioning_preflight.py \
    --service analysis --strict
```

Acceptance:

- both preflights `status=passed`;
- no forbidden env present;
- no missing required config.

### Шаг 2. DB backup

```bash
docker compose exec -T postgres pg_dump \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  --format=custom \
  --file=/tmp/asa_pre_split_rehearsal.dump
```

Acceptance:

- backup command exits `0`;
- file exists inside postgres container;
- backup timestamp and commit hash are recorded.

### Шаг 3. Run focused verification pack

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
  /app/tests/test_service_secret_partitioning.py \
  /app/tests/test_scheduled_reporting.py \
  /app/tests/test_llm2_layered_runtime.py
```

Acceptance:

- tests pass or any failure is explicitly classified as unrelated to split
  cutover.

### Шаг 4. Start call-processing service

```bash
docker compose --env-file .env.split.common --profile split up -d \
  call_processing_api call_processing_worker
```

Health:

```bash
docker compose exec -T call_processing_api \
  curl -f http://localhost:8000/call-processing/health
```

Acceptance:

- containers healthy/running;
- health endpoint OK;
- logs do not show missing OnlinePBX/STT/LLM1 config.

### Шаг 5. Call-processing dry-run

Grant:

```bash
export CALL_PROCESSING_GRANT_JSON='{"client_id":"edo-analysis-reporting","client_type":"service","role":"admin","allowed_artifact_kinds":["transcript","transcript_segments","llm1_first_pass"],"read_surfaces":["processed_calls_v1","transcripts_v1","llm1_artifacts_v1","processing_runs_v1"],"rate_limits":{"provider_calls_per_run":200},"created_by_admin":"operator","active":true}'
```

Scope:

```bash
export CALL_PROCESSING_SCOPE_JSON="{\"department_id\":\"$DEPARTMENT_ID\",\"manager_ids\":[...],\"date_from\":\"$REPORT_DATE\",\"date_to\":\"$REPORT_DATE\",\"source\":\"onlinepbx\"}"
```

Dry-run:

```bash
docker compose exec -T call_processing_api python -m app.agents.call_processing.cli \
  --grant "$CALL_PROCESSING_GRANT_JSON" \
  dry-run \
  --scope "$CALL_PROCESSING_SCOPE_JSON" \
  --required-artifacts transcript,transcript_segments,llm1_first_pass
```

Acceptance:

- scope manager/date is correct;
- planned interactions look sane;
- dry-run makes no provider calls;
- expected missing/reused artifacts are understandable.

### Шаг 6. Call-processing ensure

Run only after dry-run approval.

```bash
docker compose exec -T call_processing_api python -m app.agents.call_processing.cli \
  --grant "$CALL_PROCESSING_GRANT_JSON" \
  ensure \
  --scope "$CALL_PROCESSING_SCOPE_JSON" \
  --required-artifacts transcript,transcript_segments,llm1_first_pass
```

Acceptance:

- run reaches terminal status `completed` or understandable `partial`;
- `counts_json.costs` saved;
- quota/provider blockers are explicit;
- no stale `queued/running` runs left.

### Шаг 7. Start analysis service

```bash
docker compose --env-file .env.split.common --profile split up -d \
  analysis_api analysis_worker
```

Preflight after start:

```bash
docker compose exec -T analysis_api \
  python report_scripts/split_secret_partitioning_preflight.py \
    --service analysis --strict
```

Acceptance:

- preflight `status=passed`;
- `CALL_PROCESSING_MODE=external_service`;
- no upstream secrets present.

### Шаг 8. Manager_daily preview in external mode

Run preview only:

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

If running per manager is safer, add `--manager-id <uuid>` or available
equivalent runner filter.

Acceptance:

- report preview/draft is created;
- no business email sent;
- `observability.source.call_processing_mode=external_service`;
- `build_summary.transcripts_built=0` on analysis side;
- `llm1_first_pass_reused_for_analysis > 0` when artifacts exist;
- no unexpected `transcript_missing_external_service`;
- `observability.ai_costs.schema_version=split_ai_costs_v1` when upstream costs
  exist.

### Шаг 9. Rollback readiness check

Do not execute destructive rollback unless needed.

Check that rollback steps are still valid:

```bash
docker compose stop analysis_api analysis_worker analysis_beat
docker compose up -d api worker beat
```

Optional legacy preview only if rehearsal had blockers:

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

Acceptance:

- legacy path remains available;
- split artifacts are not deleted.

## Required output after rehearsal

После выполнения rehearsal нужно обновить:

- `docs/call_processing_split/COMPLETION_ROADMAP.md`;
- `docs/call_processing_split/IMPLEMENTATION_STATUS.md`;
- `docs/PROGRESS.md`;
- при необходимости отдельный audit файл:
  `docs/call_processing_split/SPLIT_COMPLETE_07_REHEARSAL_RESULT_<date>.md`.

Отчет должен содержать:

- commit hash;
- report date/scope/managers;
- env preflight results;
- DB backup result;
- dry-run summary;
- ensure run id/status/counts/costs;
- manager_daily preview result;
- delivery status;
- split-boundary evidence;
- blockers;
- rollback readiness;
- recommendation: `GO_TO_SPLIT_COMPLETE_08` или `NO_GO_FIX_BLOCKERS`.

## Acceptance Criteria

SPLIT-COMPLETE-07 можно считать выполненным, если:

1. Split env preflight passed для `call-processing` и `analysis`.
2. DB backup сделан.
3. Focused verification pack passed.
4. `call-processing` dry-run and ensure completed or partial with explicit,
   acceptable blockers.
5. `analysis` manager_daily preview построен в external mode.
6. Analysis-side local STT/LLM1 не запускались.
7. Business delivery не была включена.
8. Observability/costs/alerts сохранены.
9. Rollback path подтвержден.
10. Operator получил понятный `GO/NO-GO` recommendation.

## Разделение по агентам

### Agent A — preflight and env rehearsal

- Проверить git state, env files, compose config.
- Запустить strict preflight for both services.
- Подготовить summary of env readiness.

### Agent B — call-processing rehearsal

- Проверить health.
- Выполнить dry-run.
- После approval внутри процесса выполнить ensure.
- Сохранить run id/status/counts/costs/blockers.

### Agent C — analysis preview rehearsal

- Запустить/проверить analysis service.
- Выполнить manager_daily preview only.
- Проверить split-boundary evidence and delivery gate.

### Main agent — control and reporting

- Контролировать stop conditions.
- Не включать business delivery.
- Обновить docs/result.
- Дать operator summary and GO/NO-GO recommendation.
