# SPLIT-COMPLETE-07A — production schedule activation smoke

Дата подготовки: 2026-06-15
Статус: `draft_for_approval`

## Цель

Подготовить и проверить production-расписание для ежедневного `manager_daily`
в split-контуре без ручного запуска полного pipeline и без незаметной
автодоставки менеджерам.

Этап должен подтвердить, что:

- локальный справочник менеджеров обновлен из Bitrix перед расписанием;
- в schedule scope попадают только актуальные рабочие менеджеры отдела ЭДО
  Продажи;
- в БД есть активные `report_schedules` для daily manager reports;
- `analysis_beat` видит расписание и создает reviewable batch/draft в
  split-mode;
- `analysis` не запускает локальные STT/LLM1;
- бизнес-доставка менеджерам остается за review/approve gate;
- блокеры и ошибки уходят техническим alert на `admin@dogovor24.kz`.

Это не является billable full-day run, production cutover decision или
разрешением на автоматическую business delivery.

## Текущее состояние на 2026-06-15

Уже сделано:

- live Bitrix sync по `[ЭДО] Отдел Продаж` выполнен;
- production pilot scope утвержден на 4 менеджера: Алишер, Илья, Тимур,
  Толеген;
- `Робот Договор24` исключен из schedule scope, inactive/уволенные не
  считаются;
- `bitrix_manager_sync_preflight.py` выводит `schedule_scope_candidates`;
- `scheduled_reporting_preflight.py` получил безопасную команду
  `create-production-manager-daily`;
- runtime-mounted copies доступны в `/app/report_scripts`;
- dry-run создания schedule на 4 менеджеров выполнен успешно без записи в БД:
  `start_date=2026-06-16`, `start_time=08:00`, `timezone=Asia/Almaty`,
  `business_email_enabled=false`, `review_required=true`,
  `billable_pipeline_started=false`, `conflicts=[]`;
- focused checks прошли: `py_compile`, `git diff --check`, контейнерный тест
  `/app/tests/test_scheduled_reporting_preflight.py` -> `3 passed`.

Еще не сделано:

- текущие изменения не закоммичены;
- реальная запись `report_schedules` еще не создана;
- `scan-due` / automatic due-scan smoke не запускался;
- split `analysis_beat` не запущен;
- legacy `beat` сейчас running и должен быть остановлен или изолирован до
  включения enabled schedule;
- отдельный scheduled call-processing entrypoint на `00:00 Asia/Almaty` еще не
  найден/не реализован; это gap для полной автоматизации upstream STT/LLM1.

## Оставшиеся решения

### 1. Commit перед изменением runtime state

Перед созданием enabled schedule нужно закоммитить текущие изменения, чтобы
activation smoke имел восстановимую точку.

Минимально в commit должны войти:

- `core/report_scripts/bitrix_manager_sync_preflight.py`;
- `core/report_scripts/scheduled_reporting_preflight.py`;
- `scripts/bitrix_manager_sync_preflight.py`;
- `scripts/scheduled_reporting_preflight.py`;
- `core/tests/test_scheduled_reporting_preflight.py`;
- это ТЗ и связанные docs/roadmap/progress изменения.

Acceptance:

- `git status --short --branch` понятен;
- есть commit hash перед runtime activation.

### 2. Scheduler mode

Перед созданием enabled schedule и запуском split scheduler нужно выбрать один
активный scheduled path.

Текущее наблюдение:

- legacy `beat` сейчас running;
- split `analysis_beat` сейчас не running;
- active `report_schedules` пока `0`, поэтому вреда нет;
- после создания schedule одновременная работа legacy `beat` и
  `analysis_beat` может создать дубль или отправить task не в тот runtime.

Решение по умолчанию для activation smoke:

```bash
docker compose stop beat
docker compose --env-file .env.split.common --profile split up -d analysis_beat
```

Acceptance:

- работает только один scheduler для scheduled reporting;
- task `calls.scan_scheduled_reviewable_reporting` маршрутизируется в split
  analysis path;
- rollback path через legacy остается понятным, но legacy `beat` не конкурирует
  в момент smoke.

### 3. Реальное создание schedule row

После commit и scheduler-mode решения выполнить уже проверенную команду без
`--dry-run`:

```bash
docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py \
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

- создан schedule id;
- `business_email_enabled=false`;
- `review_required=true`;
- `next_run_at` соответствует `2026-06-16 08:00 Asia/Almaty`
  (`2026-06-16 03:00 UTC`);
- manager ids ровно 4 утвержденных;
- conflicts отсутствуют.

### 4. Gap по `00:00 call-processing`

Для полной автоматизации нужен upstream scheduled entrypoint:

```text
00:00 Asia/Almaty daily -> call-processing prepares previous day STT/LLM1
```

На 2026-06-15 найдено:

- есть API/CLI `call-processing ensure/dry-run`;
- отдельного celery/beat/cron entrypoint на `00:00 Asia/Almaty` в коде/compose
  пока не найдено.

Варианты:

- временно признать, что `08:00 analysis` в режиме `build_missing_and_report`
  будет добирать missing artifacts через external call-processing;
- или перед production cutover реализовать отдельную scheduled upstream задачу
  для `call-processing`.

Рекомендация:

- для `SPLIT-COMPLETE-07A` можно создать schedule/draft smoke с
  `business_email_enabled=false`;
- для полного автоматического контура завести отдельную следующую задачу:
  `SPLIT-COMPLETE-07B — scheduled call-processing upstream at 00:00`.

## Утвержденный scope

Отдел:

```text
[ЭДО] Отдел Продаж
department_id=472cda28-ce71-494c-9068-25d3ffbf7399
```

Правило scope:

- сначала выполнить Bitrix manager sync;
- брать только `schedule_scope_candidates`;
- `active=true`;
- заполнены `email` и `extension`;
- inactive/уволенные сотрудники не считаются;
- технический пользователь `Робот Договор24` исключается.

Production pilot scope с 2026-06-15:

| Менеджер | `manager_id` | Extension | Email |
| --- | --- | --- | --- |
| Алишер Гайнидинов | `5638c619-8732-435c-9664-a7188f13effd` | `317` | `g.alisher@dogovor24.kz` |
| Илья Тарасов | `cfba5067-d356-4c8b-895a-0f5808647978` | `350` | `t.ilya@dogovor24.kz` |
| Тимур Жуматаев | `656abe58-7c23-476a-a9f6-d76305cf42e0` | `311` | `zh.timur@dogovor24.kz` |
| Толеген Жангазиев | `d42e8246-772e-4a04-bbe7-2b88f45db695` | `325` | `zh.tolegen@dogovor24.kz` |

Schedule `manager_ids`:

```json
[
  "5638c619-8732-435c-9664-a7188f13effd",
  "cfba5067-d356-4c8b-895a-0f5808647978",
  "656abe58-7c23-476a-a9f6-d76305cf42e0",
  "d42e8246-772e-4a04-bbe7-2b88f45db695"
]
```

Валидный отчетный день для smoke: `2026-06-15`.

Ожидаемый автоматический цикл по Алматы:

- `2026-06-16 00:00 Asia/Almaty` — call-processing готовит upstream artifacts
  за `2026-06-15`;
- `2026-06-16 08:00 Asia/Almaty` — analysis/reporting создает reviewable
  daily batch/draft за `2026-06-15`.

## Scope

### In scope

- Bitrix manager sync preflight.
- Проверка, что `schedule_scope_candidates` совпадают с утвержденными 4
  менеджерами.
- Проверка env/secret partitioning для split-сервисов.
- Проверка, что running containers подхватили актуальный код/scripts.
- Создание активных `report_schedules` для `manager_daily`.
- Проверка schedule fields:
  - `preset=manager_daily`;
  - `timezone=Asia/Almaty`;
  - `report_period_rule=previous_day`;
  - `manager_ids` = 4 утвержденных менеджера;
  - `mode` соответствует production daily flow;
  - delivery не обходит review/approve gate.
- Запуск/проверка `analysis_beat` в split-profile.
- Один automatic due-scan smoke без ручного запуска full pipeline.
- Проверка created batch/draft, observability, alerts, costs.
- Фиксация результата в roadmap/progress.

### Out of scope

- Ручной provider-backed full-day pipeline вместо scheduler.
- Автоматическая отправка business email менеджерам без отдельного approval.
- ROP weekly/monthly report.
- Изменение моделей STT/LLM.
- Изменение логики report content.
- Production GO/NO-GO cutover decision (`SPLIT-COMPLETE-08`).

## Stop conditions

Остановить задачу и не включать schedule/delivery дальше, если:

- Bitrix sync failed;
- `schedule_scope_candidates` не совпали с утвержденными 4 менеджерами;
- в scope попал `Робот Договор24` или inactive manager;
- split secret preflight failed;
- running service не видит актуальный код/scripts;
- активные legacy `beat` и split `analysis_beat` могут одновременно создать
  дубли или отправить scheduled task не в тот runtime path;
- в `report_schedules` уже есть конфликтующие active rows;
- dry/smoke due scan пытается отправить manager business email до approve;
- observability показывает local STT/LLM1 execution внутри `analysis`;
- repeated quota/auth/provider blocker не дает создать batch/draft;
- alert email на `admin@dogovor24.kz` не настроен.

При stop condition:

- зафиксировать команду, вывод, schedule id/batch id/run id;
- не запускать billable ensure/report delivery;
- обновить `COMPLETION_ROADMAP` и `PROGRESS`;
- отправить/проверить technical alert, если blocker production-facing.

## План работ

### Шаг 1. Git/runtime sanity

Проверить состояние:

```bash
git status --short --branch
git rev-parse --short HEAD
```

Acceptance:

- понятно, какие изменения локальные;
- нет неожиданных dirty runtime edits перед activation.

### Шаг 2. Bitrix manager sync

Запустить live sync:

```bash
docker compose exec -T api python /app/report_scripts/bitrix_manager_sync_preflight.py \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --json
```

Если runtime container не видит скрипт, пересоздать сервисы или выполнить
эквивалентный sync через `BitrixManagerMapper`, затем отдельно исправить
mount/rebuild перед production activation.

Acceptance:

- `status=ok`;
- `schedule_scope_candidates=4`;
- кандидаты: Алишер, Илья, Тимур, Толеген;
- `Робот Договор24` не в candidates;
- inactive/уволенные не в candidates.

### Шаг 3. Split env and service preflight

Проверить compose и secret partitioning:

```bash
docker compose --env-file .env.split.common --profile split \
  config --no-env-resolution --quiet

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

- call-processing strict preflight passed;
- analysis strict preflight passed;
- `analysis` не имеет upstream OnlinePBX/STT/LLM1 secrets;
- `call-processing` не имеет downstream LLM2/LLM3 secrets.

### Шаг 4. Проверить существующие schedules

Проверить active rows:

```bash
docker compose exec -T postgres psql -U asa_app -d ai_sales_analyzer \
  -P pager=off \
  -c "select id,preset,enabled,start_time,timezone,mode,business_email_enabled,review_required,next_run_at,manager_ids from report_schedules where deleted_at is null order by created_at desc;"
```

Acceptance:

- нет конфликтующих active schedules;
- если есть старые active rows, они явно остановлены/удалены/объяснены до
  создания production row.

### Шаг 5. Создать production manager_daily schedule

Создать schedule через существующий service/API/CLI путь, не прямым SQL, если
такой путь доступен. Базовые значения:

```text
department_id=472cda28-ce71-494c-9068-25d3ffbf7399
preset=manager_daily
manager_ids=[4 approved ids]
enabled=true
timezone=Asia/Almaty
start_time=08:00
recurrence_type=daily
report_period_rule=previous_day
mode=build_missing_and_report
business_email_enabled=false for smoke unless separately approved
review_required=true
```

Предпочтительный CLI путь:

```bash
docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py \
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

После успешного dry-run и проверки `conflicts=[]` убрать `--dry-run`.
Команда сама:

- выводит payload без записи в БД при `--dry-run`;
- выводит `billable_pipeline_started=false`;
- выводит `business_email_enabled=false` по умолчанию;
- блокирует создание при overlapping active schedules, если оператор явно не
  передал `--allow-conflicts`.

Если для production принято сразу включать email после approve, schedule может
хранить `business_email_enabled=true`, но scan/draft все равно не должен
отправлять email без explicit approve.

Acceptance:

- создана активная schedule row;
- schedule id зафиксирован;
- `manager_ids` точно 4 утвержденных id;
- `next_run_at` соответствует ожидаемому времени в UTC для
  `08:00 Asia/Almaty`;
- review gate включен.

### Шаг 6. Запустить split `analysis_beat`

Перед запуском убедиться, что legacy/monolith beat не создаст дубль. Для
production smoke должен работать один scheduled path.

Если `docker compose ps` показывает running `beat`, остановить legacy beat до
старта split `analysis_beat` или явно подтвердить другой безопасный runtime
план.

Команда:

```bash
docker compose --env-file .env.split.common --profile split up -d analysis_beat
```

Acceptance:

- `analysis_beat` running;
- scheduled task route идет в `analysis` queue;
- нет одновременной конфликтующей legacy schedule execution.

### Шаг 7. Automatic due-scan smoke

Проверить первый due scan через scheduled mechanism, а не ручной full pipeline.
Если нужно ускорить smoke, допустимо временно выставить `next_run_at` на
контролируемое ближайшее время только для test schedule, затем вернуть/создать
production schedule с настоящим временем.

Acceptance:

- `scan_due_schedules` обработал schedule;
- создан `scheduled_report_batches` / `scheduled_report_drafts` или понятный
  `no_data/blocker`;
- batch/draft status не отправил manager business email автоматически;
- observability содержит:
  - selected report date;
  - manager id;
  - `CALL_PROCESSING_MODE=external_service`;
  - call-processing ensure summary;
  - `observability.ai_costs`;
  - `observability.alerts`;
  - absence of local STT/LLM1 in analysis.

### Шаг 8. Зафиксировать результат

Обновить:

- `docs/call_processing_split/COMPLETION_ROADMAP.md`;
- `docs/PROGRESS.md`;
- при необходимости `docs/ACTIVE_WORK_STATE.md`.

Зафиксировать:

- Bitrix sync summary;
- production scope;
- schedule id;
- `next_run_at`;
- first batch/draft id или blocker;
- delivery status;
- alerts status;
- recommendation: continue to `SPLIT-COMPLETE-08` или fix blocker.

## Проверка результата

Задача считается выполненной, если:

- актуальный Bitrix scope подтвержден;
- создано production-ready расписание для 4 менеджеров;
- split `analysis_beat` может обработать due schedule;
- первый smoke не нарушил review gate и split boundary;
- менеджерам ничего не отправлено без approve;
- все blockers/alerts/costs видны оператору;
- новый агент может по docs понять, что именно создано и что делать дальше.

## Команды для ручной сверки

Проверить утвержденных active managers:

```sql
select id,name,extension,email,active,bitrix_id
from managers
where department_id='472cda28-ce71-494c-9068-25d3ffbf7399'
order by active desc, name;
```

Проверить schedules:

```sql
select id,preset,enabled,start_time,timezone,mode,business_email_enabled,
       review_required,next_run_at,manager_ids
from report_schedules
where deleted_at is null
order by created_at desc;
```

Проверить recent batches:

```sql
select id,schedule_id,department_id,preset,status,period_start,period_end,
       created_at,updated_at
from scheduled_report_batches
order by created_at desc
limit 10;
```

## Notes

- Валюта cost summary остается USDT.
- UI не обязателен; Codex/оператор может читать DB/artifacts и отвечать в чате.
- Если `business_email_enabled=false`, manager emails не уйдут даже после
  draft creation. Это безопасный smoke.
- Если будет принято включить business email после approve, ROP daily copy
  должна уйти на `edo.rop@dogovor24.kz` только после успешной доставки
  manager reports.
