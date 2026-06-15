# SPLIT-COMPLETE-07C — runtime schedule activation for pilot

Дата подготовки: 2026-06-15
Статус: `draft_for_approval`

## Цель

Аккуратно включить split-расписание для ежедневного пилота по ЭДО Продажи после
подготовленных локальных commit:

- `9ecc6be Prepare production schedule activation smoke`;
- `b658862 Add scheduled call-processing upstream task`.

Это runtime-шаг, а не разработка. Нужно перевести автозапуск из состояния
"код и CLI готовы" в состояние "расписание создано, правильные beat-процессы
запущены, legacy scheduler не конкурирует".

## Текущая точка перед стартом

Проверено 2026-06-15:

```text
git: branch feat/call-processing-analysis-split, ahead 4, worktree clean
active report_schedules: 0
legacy beat: running
call_processing_beat: not running
analysis_beat: not running
split call_processing_api/worker: running
split analysis_api/worker: running
```

## Scope

### In scope

- Остановить legacy `beat`, чтобы не было двойного scheduler.
- Создать production `manager_daily` schedule row для 4 менеджеров ЭДО.
- Запустить split `call_processing_beat` и `analysis_beat`.
- Проверить, что schedule создан с безопасными delivery settings.
- Проверить, что beat-процессы running и routed в правильные queues.
- Проверить, что active schedule один и ожидаемый.
- Зафиксировать результат в docs.

### Out of scope

- Ручной full-day pipeline.
- Ручной `scan-due`, если наступил due-time и это может запустить analysis.
- Approve/delivery менеджерам.
- `business_email_enabled=true`.
- Provider-backed STT/LLM прогон без отдельного подтверждения.
- Изменение LLM/STT моделей, prompts, report layer.

## Production scope

Отдел:

```text
[ЭДО] Отдел Продаж
department_id=472cda28-ce71-494c-9068-25d3ffbf7399
```

Менеджеры:

| Менеджер | `manager_id` | Extension | Email |
| --- | --- | --- | --- |
| Алишер Гайнидинов | `5638c619-8732-435c-9664-a7188f13effd` | `317` | `g.alisher@dogovor24.kz` |
| Илья Тарасов | `cfba5067-d356-4c8b-895a-0f5808647978` | `350` | `t.ilya@dogovor24.kz` |
| Тимур Жуматаев | `656abe58-7c23-476a-a9f6-d76305cf42e0` | `311` | `zh.timur@dogovor24.kz` |
| Толеген Жангазиев | `d42e8246-772e-4a04-bbe7-2b88f45db695` | `325` | `zh.tolegen@dogovor24.kz` |

Исключения:

- inactive/уволенные не считаются;
- `Робот Договор24` не входит в schedule scope.

## Runtime model

Ожидаемая модель:

```text
00:00 Asia/Almaty
call_processing_beat -> call_processing.ensure_daily_upstream
-> call_processing queue -> call_processing_worker
-> previous-day OnlinePBX/STT/transcript/segments/LLM1

08:00 Asia/Almaty
analysis_beat -> calls.scan_scheduled_reviewable_reporting
-> analysis queue -> analysis_worker
-> manager_daily reviewable batch/draft
```

Important:

- `call_processing_beat` и `analysis_beat` могут работать одновременно, потому
  что они планируют разные tasks в разные queues.
- Legacy `beat` не должен работать при active split schedules.
- Manager business email не должен уходить при создании schedule/draft.

## Required env

В `.env.call-processing` для реального ночного upstream нужно включить:

```text
CALL_PROCESSING_DAILY_UPSTREAM_ENABLED=true
CALL_PROCESSING_DAILY_UPSTREAM_TIMEZONE=Asia/Almaty
CALL_PROCESSING_DAILY_UPSTREAM_HOUR=0
CALL_PROCESSING_DAILY_UPSTREAM_MINUTE=0
CALL_PROCESSING_DAILY_UPSTREAM_DEPARTMENT_ID=472cda28-ce71-494c-9068-25d3ffbf7399
CALL_PROCESSING_DAILY_UPSTREAM_MANAGER_IDS=5638c619-8732-435c-9664-a7188f13effd,cfba5067-d356-4c8b-895a-0f5808647978,656abe58-7c23-476a-a9f6-d76305cf42e0,d42e8246-772e-4a04-bbe7-2b88f45db695
CALL_PROCESSING_DAILY_UPSTREAM_PROVIDER_CALL_BUDGET=<approved budget>
```

Для безопасного activation без provider-backed upstream можно оставить:

```text
CALL_PROCESSING_DAILY_UPSTREAM_ENABLED=false
CALL_PROCESSING_DAILY_UPSTREAM_PROVIDER_CALL_BUDGET=0
```

Но в таком режиме `call_processing_beat` не будет запускать ночную подготовку
артефактов. Тогда `08:00 analysis` может попытаться добрать missing artifacts
через external call-processing, если schedule mode остается
`build_missing_and_report`.

## Stop conditions

Остановить выполнение и не переходить к следующему шагу, если:

- worktree dirty перед runtime activation;
- active `report_schedules` уже есть и они конфликтуют;
- Bitrix scope не равен 4 утвержденным менеджерам;
- `business_email_enabled` получается `true`;
- legacy `beat` не удалось остановить;
- split `call_processing_beat` или `analysis_beat` не стартует;
- `call_processing_beat` планирует reporting task;
- `analysis_beat` планирует upstream STT/LLM1 task;
- команда пытается запустить approve/email;
- provider budget не утвержден, но включается provider-backed upstream.

## Execution Plan

### Шаг 0. Preflight

```bash
git status --short --branch
git log --oneline -4
docker compose ps
docker compose exec -T postgres psql -U asa_app -d ai_sales_analyzer -P pager=off -c \
  "select count(*) as active_schedules from report_schedules where deleted_at is null;"
```

Acceptance:

- worktree clean;
- видны commits `9ecc6be` и `b658862`;
- active schedules = `0`;
- legacy `beat` running, split beats not running.

### Шаг 1. Bitrix scope check

```bash
docker compose exec -T analysis_api python /app/report_scripts/bitrix_manager_sync_preflight.py \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --json
```

Acceptance:

- `schedule_scope_candidates=4`;
- candidates: Алишер, Илья, Тимур, Толеген;
- `Робот Договор24` not in candidates.

### Шаг 2. Schedule dry-run

```bash
docker compose exec -T analysis_api python /app/report_scripts/scheduled_reporting_preflight.py \
  --json \
  create-production-manager-daily \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --first-report-date 2026-06-15 \
  --manager-id 5638c619-8732-435c-9664-a7188f13effd \
  --manager-id cfba5067-d356-4c8b-895a-0f5808647978 \
  --manager-id 656abe58-7c23-476a-a9f6-d76305cf42e0 \
  --manager-id d42e8246-772e-4a04-bbe7-2b88f45db695 \
  --dry-run
```

Acceptance:

- `conflicts=[]`;
- `business_email_enabled=false`;
- `review_required=true`;
- `billable_pipeline_started=false`;
- active schedules still `0`.

### Шаг 3. Stop legacy scheduler

```bash
docker compose stop beat
docker compose ps
```

Acceptance:

- service `beat` stopped/exited;
- no schedule row created yet.

Rollback:

```bash
docker compose up -d beat
```

### Шаг 4. Create production schedule row

```bash
docker compose exec -T analysis_api python /app/report_scripts/scheduled_reporting_preflight.py \
  --json \
  create-production-manager-daily \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --first-report-date 2026-06-15 \
  --manager-id 5638c619-8732-435c-9664-a7188f13effd \
  --manager-id cfba5067-d356-4c8b-895a-0f5808647978 \
  --manager-id 656abe58-7c23-476a-a9f6-d76305cf42e0 \
  --manager-id d42e8246-772e-4a04-bbe7-2b88f45db695
```

Acceptance:

- command returns `status=ok`;
- created schedule id recorded;
- `business_email_enabled=false`;
- `review_required=true`;
- `next_run_at=2026-06-16T03:00:00+00:00` or equivalent UTC for
  `2026-06-16 08:00 Asia/Almaty`;
- no STT/LLM/pipeline/email run at creation time.

Rollback:

Use existing schedule delete/disable API/CLI if available, or pause schedule
before restarting legacy `beat`.

### Шаг 5. Start split beats

If upstream provider-backed run is not approved yet, keep upstream env disabled
and start only `analysis_beat`:

```bash
docker compose --env-file .env.split.common --profile split up -d analysis_beat
```

If upstream provider-backed run is approved, first set `.env.call-processing`
with approved upstream env and then start both:

```bash
docker compose --env-file .env.split.common --profile split up -d \
  call_processing_beat analysis_beat
```

Acceptance:

- `analysis_beat` running;
- `call_processing_beat` running only if upstream is approved/configured;
- legacy `beat` remains stopped.

### Шаг 6. Verify runtime state

```bash
docker compose ps

docker compose exec -T analysis_api python /app/report_scripts/scheduled_reporting_preflight.py \
  --json status

docker compose exec -T postgres psql -U asa_app -d ai_sales_analyzer -P pager=off -c \
  "select id,preset,enabled,start_date,start_time,timezone,report_period_rule,mode,business_email_enabled,review_required,next_run_at,manager_ids from report_schedules where deleted_at is null order by created_at desc;"
```

Acceptance:

- exactly one active `manager_daily` schedule for EDO Sales;
- 4 approved manager ids;
- `business_email_enabled=false`;
- `review_required=true`;
- split beat state matches selected mode.

### Шаг 7. Do not force due-scan unless explicitly approved

Do not run:

```bash
scheduled_reporting_preflight.py scan-due
approve
manual_reporting_runner
call-processing ensure
```

unless operator explicitly approves the next smoke/run.

## Success Criteria

Задача считается выполненной, если:

- legacy `beat` stopped;
- split schedule row exists and is safe;
- `analysis_beat` running;
- `call_processing_beat` decision documented and state matches decision;
- manager business email still disabled;
- no STT/LLM/report/email was manually triggered during activation;
- docs updated with schedule id, next_run_at and beat state.

## Result Log

```text
activation_started_at: 2026-06-15T15:42:00Z
git_commit_before_activation: 4aabb2f Document split runtime schedule activation
bitrix_sync_status: ok; 4 schedule_scope_candidates; Robot Dogovor24 excluded
schedule_id: 97e6c120-6aa3-4664-99ae-3982054698d7
next_run_at: 2026-06-16T03:00:00+00:00 (2026-06-16 08:00 Asia/Almaty)
legacy_beat_state: stopped/exited
call_processing_beat_state: not running; provider-backed upstream not approved
analysis_beat_state: running
business_email_enabled: false
review_required: true
provider_upstream_enabled: false
provider_budget: 0 / not approved for this activation step
smoke_status: schedule activation smoke passed; first due scan processed 0 schedules because next_run_at is future
blockers: none for scheduled reporting activation; open decision remains 00:00 call-processing upstream budget/enablement
next_step: decide whether to enable provider-backed call_processing_beat for 2026-06-16 00:00 Asia/Almaty or let 08:00 analysis request missing artifacts via external call-processing
```
