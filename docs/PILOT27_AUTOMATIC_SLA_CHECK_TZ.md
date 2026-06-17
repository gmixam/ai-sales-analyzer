# PILOT-27: автоматический SLA-check в 09:30/10:00 без Codex

Дата: 2026-06-17
Статус: implemented_first_pass
Связанные задачи: `PILOT-26`, `PILOT-28`, `PILOT-33`,
`SPLIT-COMPLETE-07E`

## Контекст

Production `manager_daily` уже запускается автоматически:

- upstream/call-processing готовит STT/LLM1 за предыдущий день;
- analysis/reporting строит LLM2/Report Layer и отправляет manager email + ROP
  bundle;
- `scheduled_reporting_preflight.py` уже имеет CLI-команды:
  - `sla-status --date YYYY-MM-DD`;
  - `sla-check --date YYYY-MM-DD --phase precheck|hard`.

Проблема: `sla-check` пока нужно запускать вручную/Codex. Если pipeline не
собрал отчет или не отправил email, оператор узнает об этом только после ручной
проверки.

## Цель

Добавить автоматический SLA-check, который без Codex каждый рабочий день:

1. В `09:30 Asia/Almaty` проверяет риск нарушения SLA и отправляет warning
   alert только при проблеме.
2. В `10:00 Asia/Almaty` фиксирует hard SLA miss и отправляет critical alert
   только при проблеме.

Если все отчеты доставлены или день объективно не требует отчета
(`no_calls`/`no_audio` по утвержденному правилу), проверка должна завершаться
без шума.

## Что считаем проблемой

Проблемные причины для alert:

- `analysis_not_ready`;
- `scheduled_batch_missing`;
- `scheduled_draft_missing`;
- `pdf_not_ready`;
- `manager_report_not_delivered`;
- `email_failed`;
- `manager_email_failed`;
- `manager_email_blocked`;
- `missing_recipient`;
- `budget` / `quota`;
- `read_timeout` / `ReadTimeout`;
- неожиданный exception в scheduled reporting или delivery.

Не считать проблемой:

- `no_calls_for_report_day`;
- `no_audio_calls_for_report_day`, если по manager-day нет разговоров с аудио и
  нет обязательного manager-facing отчета.

## Целевое расписание

| Время Asia/Almaty | Phase | Поведение |
| --- | --- | --- |
| `09:30` | `precheck` | Если есть pending/blocked риск, отправить warning alert. Если все ок - молчать |
| `10:00` | `hard` | Если есть недоставленные отчеты, зафиксировать SLA miss и отправить critical alert. Если все ок - молчать |

Report date считать автоматически как предыдущий отчетный день по
`Asia/Almaty`, без ручной передачи даты.

## Каналы уведомлений

Использовать существующий alert layer из `PILOT-28`:

- Telegram operator alert, если включен `ALERT_TELEGRAM_*`;
- email admin alert на `admin@dogovor24.kz`, если включен
  `ALERT_EMAIL_ENABLED=true`.

Не отправлять raw JSON. Полные details должны оставаться в logs/observability.

Пример warning:

```text
⚠️ Риск SLA daily reports за 16 июня

Проблема: анализ не готов по 2 менеджерам.
Влияет: отчеты могут не уйти до 10:00.
Что делать: проверить scheduled batches и analysis service.
```

Пример hard alert:

```text
❌ SLA daily reports нарушен за 16 июня

Не доставлено: Тимур — missing_recipient.
Доставлено: Алишер, Толеген.
Не требуется: Илья — нет звонков.
```

## Требования к реализации

### 1. Автоматический расчет даты

Добавить для SLA-check режим без ручной даты:

- либо `--date auto`;
- либо отсутствие `--date` с default `previous_day`;
- timezone: `Asia/Almaty`;
- нельзя использовать UTC date напрямую для определения отчетного дня.

Ожидаемо утром `2026-06-18 Asia/Almaty` checker проверяет report date
`2026-06-17`.

### 2. Beat/scheduler integration

Привязать два автоматических запуска к существующему runtime scheduler/beat:

- `manager_daily_sla_precheck` в `09:30 Asia/Almaty`;
- `manager_daily_sla_hardcheck` в `10:00 Asia/Almaty`.

Технически можно реализовать как:

- отдельные beat tasks, вызывающие Python-функцию `sla_check`;
- или отдельный small runner/CLI entrypoint, запускаемый beat worker.

Важно: не запускать общий `scan_due`, не создавать новые report batches и не
перезапускать LLM/STT. SLA-check только читает состояние, шлет alert и в hard
phase фиксирует SLA miss в observability, как уже делает текущий CLI.

### 3. Idempotency

Повторный запуск за тот же report date/phase не должен плодить бесконечные
alerts.

Минимальный acceptable вариант:

- `run_id = manager_daily_sla:{report_date}:{phase}`;
- alert layer использует существующую дедупликацию, если она есть;
- если дедупликации нет, добавить observability marker или bounded suppression
  по run id.

### 4. No-noise policy

Checker молчит, если:

- все manager-facing отчеты доставлены;
- ROP bundle доставлен/отправлен для доставленных manager reports;
- менеджер не требует отчета по причине `no_calls_for_report_day`;
- менеджер имеет только `no_audio_calls_for_report_day` и нет аудио для
  анализа.

Checker шлет alert, если:

- есть хотя бы один менеджер с pending/blocked status;
- missing batch/draft/pdf;
- email не доставлен;
- provider/timeout/quota/budget blocker.

### 5. Human-readable summary

Alert должен содержать:

- report date;
- phase: precheck/hard;
- список affected managers с короткой причиной;
- влияние: отчет может не уйти / SLA нарушен;
- что проверить: scheduled batches, analysis service, delivery config,
  provider quota.

Полные affected rows оставить в `observability`, не в тексте alert.

## Что не делаем

- Не меняем STT/LLM модели.
- Не меняем scheduled report generation time `04:00`.
- Не запускаем повторный pipeline из SLA-check.
- Не отправляем пустые/сырые отчеты ради SLA.
- Не строим отдельный UI.
- Не вводим отдельный календарь праздников.

## Проверки

### Unit/focused tests

Добавить focused tests на:

1. Auto-date считается по `Asia/Almaty`, а не UTC.
2. `precheck` в `09:30` отправляет warning при `analysis_not_ready`.
3. `hard` в `10:00` фиксирует SLA miss и отправляет critical при
   недоставленном отчете.
4. `no_calls_for_report_day` не создает alert.
5. `no_audio_calls_for_report_day` не создает alert, если нет аудио для
   анализа.
6. Повторный запуск same `report_date + phase` не плодит шумные дубли, если
   есть дедупликация.
7. Beat registration содержит два schedule: `09:30` и `10:00` `Asia/Almaty`.

Команды:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_scheduled_reporting_preflight.py \
  /app/tests/test_run_alerts.py \
  -k "sla or manager_daily"

python3 -m py_compile \
  core/report_scripts/scheduled_reporting_preflight.py \
  scripts/scheduled_reporting_preflight.py

git diff --check
```

### Manual smoke

Dry run / controlled check:

```bash
docker compose exec -T analysis_api python \
  /app/report_scripts/scheduled_reporting_preflight.py sla-check \
  --date auto \
  --phase precheck

docker compose exec -T analysis_api python \
  /app/report_scripts/scheduled_reporting_preflight.py sla-check \
  --date auto \
  --phase hard
```

После внедрения проверить в runtime:

- beat содержит/запускает `manager_daily_sla_precheck`;
- beat содержит/запускает `manager_daily_sla_hardcheck`;
- при нормальном состоянии нет лишних alerts;
- при искусственно смоделированном pending/blocked состоянии приходит короткий
  alert без JSON.

## Acceptance criteria

1. В `09:30 Asia/Almaty` SLA precheck запускается автоматически без Codex.
2. В `10:00 Asia/Almaty` hard SLA check запускается автоматически без Codex.
3. Дата отчета определяется автоматически как previous report day по Алматы.
4. Если проблема есть, оператор получает короткий warning/critical alert.
5. Если проблемы нет, checker молчит.
6. `no_calls` и `no_audio` дни не создают ложный шум.
7. SLA miss фиксируется в observability/status, а не только в Telegram/email.
8. Existing manual CLI `sla-status/sla-check` продолжает работать.

## Разделение по агентам

### Agent A — scheduler/beat integration

Файлы-кандидаты:

- runtime scheduler/beat config;
- celery/beat task modules, если используются;
- docker/runtime config, если расписание задается там.

Задача:

- найти текущий механизм расписания;
- добавить два scheduled task;
- не менять генерацию отчетов;
- обеспечить timezone `Asia/Almaty`.

### Agent B — SLA CLI auto-date + idempotency

Файлы-кандидаты:

- `core/report_scripts/scheduled_reporting_preflight.py`;
- `scripts/scheduled_reporting_preflight.py`;
- tests для preflight.

Задача:

- добавить `--date auto` или optional date;
- вычислять previous day по Алматы;
- проверить/усилить idempotency по `run_id`;
- сохранить backward compatibility.

### Agent C — alert text and tests

Файлы-кандидаты:

- `core/app/agents/calls/run_alerts.py`;
- `core/tests/test_run_alerts.py`;
- `core/tests/test_scheduled_reporting_preflight.py`.

Задача:

- убедиться, что SLA alert short summary не содержит raw JSON;
- покрыть warning/critical/no-noise scenarios;
- проверить affected managers summary.

## Статус после реализации

First pass реализован 2026-06-17. После первого реального рабочего утра, где
checker сам отработает без Codex, перевести в `done`.

## Результат реализации 2026-06-17

Внедрено:

- Celery task routes:
  - `calls.manager_daily_sla_precheck`;
  - `calls.manager_daily_sla_hardcheck`;
- beat entries для analysis runtime:
  - `manager_daily_sla_precheck` каждый будний день в `09:30 Asia/Almaty`;
  - `manager_daily_sla_hardcheck` каждый будний день в `10:00 Asia/Almaty`;
- обе задачи идут в `analysis` queue и не запускают STT/LLM/report pipeline;
- task wrappers вызывают существующий
  `scheduled_reporting_preflight.sla_check`;
- `sla-status` и `sla-check` получили optional `--date`; default/`auto`
  означает previous report day по `Asia/Almaty`;
- runtime-mounted `scripts/scheduled_reporting_preflight.py` синхронизирован с
  `core/report_scripts/scheduled_reporting_preflight.py`;
- no-noise политика остается в `sla_check`: rows без аудио для анализа не
  попадают в affected managers, а при отсутствии affected alert не отправляется.

Проверено:

```bash
docker compose exec -T analysis_api python -m pytest -q \
  /app/tests/test_call_processing_runtime_split.py \
  /app/tests/test_scheduled_call_processing_upstream.py \
  -k "sla or celery_queue_routing or celery_beat_schedule"
# 6 passed, 14 deselected

docker compose exec -T api python -m pytest -q \
  /app/tests/test_scheduled_reporting_preflight.py -k "sla"
# 10 passed, 8 deselected

python3 -m py_compile \
  core/app/core_shared/workers/celery_app.py \
  core/app/core_shared/workers/tasks.py \
  core/report_scripts/scheduled_reporting_preflight.py \
  scripts/scheduled_reporting_preflight.py \
  core/tests/test_call_processing_runtime_split.py \
  core/tests/test_scheduled_call_processing_upstream.py \
  core/tests/test_scheduled_reporting_preflight.py
```

Осталось до `done`:

- дождаться/проверить первый реальный scheduled run `09:30/10:00`;
- убедиться, что при норме alert не приходит;
- если есть проблема, проверить короткий текст alert и запись hard SLA miss в
  observability.
