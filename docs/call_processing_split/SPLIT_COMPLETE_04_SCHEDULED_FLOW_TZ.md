# SPLIT-COMPLETE-04 — scheduled flow в split-контуре

Дата подготовки: 2026-06-15
Статус: `implemented_local`

## Цель

Подготовить техническую автоматизацию двух разделенных сервисов без участия
Codex и без UI:

1. `call-processing` каждый день запускается в 00:00 по Алматы и готовит
   upstream artifacts: звонки из OnlinePBX, audio, STT, segments и LLM1.
2. `analysis/reporting` каждый день запускается в 08:00 по Алматы, берет
   готовые upstream artifacts, выполняет LLM2/LLM3/report layer и создает
   reviewable daily drafts/reports.

Главный принцип: не вести отдельный календарь выходных и праздников. Система
сама определяет, есть ли отчетный день по фактическим звонкам и готовым
артефактам.

Полный production запуск расписания в рамках этого ТЗ не нужен. Нужно
технически подготовить и покрыть тестами scheduled/reviewable flow в split-mode.

Итог реализации 2026-06-15:

- добавлен split-aware scheduled branch для `manager_daily` schedules с явными
  `manager_ids`;
- analysis scan выбирает самый старый неотчитанный день со звонками внутри
  `SCHEDULED_ANALYSIS_LOOKBACK_DAYS`;
- пустые дни фиксируются как skip/no-draft без manager-facing отчета;
- observability содержит candidate selection diagnostics;
- duplicate protection усилен по manager-day ключу;
- scan/draft остается review-only и вызывает `run_report(..., send_email=False)`;
- approve остается единственным business delivery gate.

## Почему это нужно

Мы двигаемся к режиму, где ежедневный процесс работает автоматически. Codex
должен быть нужен только для контроля, аудита и ручных запросов, а не для
ежедневного запуска.

Без этого этапа автоматизация может:

- случайно вызвать legacy STT/LLM1 внутри `analysis`;
- отправить business email менеджеру до review/approve;
- не заметить пустой выходной/праздничный день;
- создать дубли отчетов за один и тот же день;
- потерять blocker, alert или cost summary;
- зависнуть без уведомления admin, если закончился бюджет или внешний сервис
  вернул ошибку.

## Утвержденная модель расписания

### 1. STT/upstream service

Сервис: `call_processing_api/worker`

Расписание:

```text
00:00 Asia/Almaty daily
```

Поведение:

- обрабатывает предыдущий календарный день;
- подтягивает звонки из OnlinePBX;
- строит/переиспользует audio, STT, transcript segments и LLM1;
- сохраняет `CallProcessingRun`, artifact readiness и upstream cost summary;
- не формирует manager daily report;
- не отправляет manager business email;
- при ошибках или budget/blocker отправляет технический alert на
  `admin@dogovor24.kz`.

Если звонков за день нет:

- manager-facing отчет не создается;
- run завершается как no-op/skip с понятной причиной;
- состояние фиксируется в observability/logs, чтобы оператор видел, что запуск
  был и почему не было отчета.

### 2. Analysis/reporting service

Сервис: `analysis_api/worker`

Расписание:

```text
08:00 Asia/Almaty daily
```

Поведение:

- работает только через `CALL_PROCESSING_MODE=external_service`;
- не запускает локальные STT/LLM1 внутри `analysis`;
- для каждого пилотного менеджера ищет неотчитанный день с фактическими
  звонками/артефактами в lookback-window;
- выполняет LLM2, LLM3 и report layer;
- создает `scheduled_report_batches` и `scheduled_report_drafts`;
- сохраняет observability, blockers, alerts и merged cost summary;
- не отправляет business email менеджерам до explicit approve.

## Правило выходных и праздников

Отдельный календарь выходных/праздников не ведем.

Analysis service каждый день в 08:00 делает data-driven scan:

1. Берет окно последних `SCHEDULED_ANALYSIS_LOOKBACK_DAYS` дней.
2. Для каждого менеджера ищет дни, где есть фактические звонки или готовые
   upstream artifacts.
3. Исключает дни, по которым уже есть terminal batch/draft/report.
4. Пустые дни без звонков пропускает без manager-facing отчета.
5. Если после выходных или праздников есть последний рабочий день со звонками,
   система берет его автоматически.

Рекомендуемое поведение по backlog:

- по умолчанию формировать не более одного manager-day report на менеджера за
  один scheduled scan;
- выбирать самый старый неотчитанный день внутри lookback-window, чтобы после
  длинных выходных не перескакивать через старые дни;
- при необходимости разрешить operator override для обработки всего backlog.

## Runtime config

Минимальные параметры:

```text
SCHEDULED_TIMEZONE=Asia/Almaty
SCHEDULED_STT_ENABLED=true
SCHEDULED_STT_RUN_TIME=00:00
SCHEDULED_STT_TARGET_DAY=previous_calendar_day

SCHEDULED_ANALYSIS_ENABLED=true
SCHEDULED_ANALYSIS_RUN_TIME=08:00
SCHEDULED_ANALYSIS_LOOKBACK_DAYS=7
SCHEDULED_ANALYSIS_MAX_REPORT_DAYS_PER_MANAGER=1
SCHEDULED_EMPTY_DAY_POLICY=skip_without_report

CALL_PROCESSING_MODE=external_service
AI_LLM2_INPUT_PROFILE=compact
ALERT_EMAIL_ENABLED=true
ALERT_EMAIL_TO=admin@dogovor24.kz
```

Если в проекте уже есть близкие env-названия, новые имена можно не плодить:
допустимо использовать существующие, но в документации нужно явно связать их с
этими правилами.

## Требования

### 1. Scheduled STT должен быть idempotent

Повторный запуск за тот же `report_date` не должен заново оплачивать уже
готовые artifacts.

Нужно фиксировать:

- `provider`;
- `model`;
- `duration_sec`;
- `billable_minutes`;
- `request_id`, если есть;
- built/reused/error counts;
- upstream cost summary.

### 2. Scheduled analysis должен быть split-aware

При `CALL_PROCESSING_MODE=external_service` scheduled manager_daily flow должен:

- вызвать `CallsManualReportingOrchestrator.run_report()`;
- внутри orchestrator использовать `call_processing_client.ensure_processed_calls`;
- получить `EnsureResponse.run_id/status/planned/quota/costs`;
- сохранить это в `scheduled_report_batches.observability`;
- использовать только external LLM1 artifacts.

Недопустимо:

- запускать STT/LLM1 из legacy/manual path внутри `analysis`;
- молча терять `call-processing` blocker;
- падать из-за отсутствия upstream costs в старых тестовых responses.

### 3. Candidate selection должен быть понятным

В observability scheduled batch нужно сохранять:

- `scheduled_timezone`;
- `scan_started_at`;
- `lookback_days`;
- `manager_id`;
- `candidate_dates`;
- `selected_report_date`;
- `skipped_empty_dates`;
- `skipped_already_reported_dates`;
- `skipped_not_ready_dates`;
- `selection_reason`.

Это нужно, чтобы без Codex было понятно, почему система взяла именно этот день
или почему ничего не сформировала.

### 4. Draft creation must be review-only

После scheduled scan:

- batch status должен быть `review_required`, если есть draft/report payload;
- draft status должен быть `review_required`;
- `business_email_enabled` может быть сохранен в batch, но email менеджеру не
  должен уходить на этапе scan/draft;
- delivery metadata может содержать preview/test status, но не manager business
  delivery without approve.

### 5. Approve remains the delivery gate

Business delivery разрешена только после:

- batch status `review_required`;
- explicit `approve_batch()`;
- `business_email_enabled=true`;
- resolved primary recipient.

Если `business_email_enabled=false`, approve не должен отправлять manager email.

### 6. Duplicate protection

Ключ защиты от дублей:

```text
preset + manager_id + report_date + report_type
```

Scheduled scan не должен создавать новый manager daily draft/report, если по
этому ключу уже есть:

- delivered report;
- approved batch;
- review_required draft;
- running/open batch;
- terminal blocked/review record, который оператор еще не разобрал.

### 7. Alerts

Технический alert на `admin@dogovor24.kz` нужен для:

- provider/budget/quota error;
- repeated blocker;
- partial run;
- no_data, если ожидались звонки;
- not_ready, если есть звонки, но нет нужных artifacts;
- unexpected exception;
- delivery gate failure.

Alert не должен ломать сам run, если SMTP недоступен. Попытка отправки должна
сохраняться в `observability.alerts`.

### 8. Cost summary

Scheduled analysis должен сохранять merged cost summary:

- upstream: STT + LLM1 из `call-processing`;
- downstream: LLM2 + LLM3/report layer из `analysis`;
- total current run cost;
- reuse не добавляет новую стоимость текущего прогона;
- missing price должен давать `price_missing`, а не ноль.

Целевое место: `observability.ai_costs`.

## Предлагаемые изменения по коду

### Файлы-кандидаты

- `core/app/agents/calls/scheduled_reporting.py`
- `core/app/agents/calls/reporting.py`
- `core/app/agents/calls/run_alerts.py`
- `core/tests/test_scheduled_reporting.py`
- `core/tests/test_manual_reporting.py`
- `core/tests/test_call_processing_reporting_integration.py`
- `services/call_processing/*`, если понадобится отдельный scheduler entrypoint;
- docs:
  - `docs/call_processing_split/COMPLETION_ROADMAP.md`;
  - `docs/ACTIVE_WORK_STATE.md`;
  - `docs/PROGRESS.md` после реализации.

### Возможные кодовые правки

1. Добавить/уточнить scheduled entrypoint для STT daily run.
2. Добавить data-driven candidate selection для analysis daily run.
3. Явно запретить business delivery на scan/draft.
4. Сохранить candidate-selection diagnostics в batch observability.
5. Укрепить duplicate protection по `preset + manager_id + report_date +
   report_type`.
6. Пробросить upstream costs в scheduled observability.
7. Подключить admin alerts для blocked/partial/no_data/not_ready states.

## Acceptance Criteria

1. STT scheduled run в 00:00 Asia/Almaty готовит upstream artifacts за
   предыдущий день и не создает manager report.
2. Analysis scheduled run в 08:00 Asia/Almaty выбирает неотчитанный день по
   факту звонков, без отдельного календаря выходных/праздников.
3. Пустой день без звонков пропускается без manager-facing отчета.
4. После выходных analysis scan выбирает рабочий день со звонками внутри
   lookback-window.
5. Scheduled manager_daily scan в `CALL_PROCESSING_MODE=external_service`
   использует external call-processing path и не запускает local STT/LLM1.
6. Scan/draft не отправляет manager business email.
7. `approve_batch()` остается единственным business delivery gate.
8. Duplicate protection не дает создать второй report/draft за тот же
   `manager_id + report_date + report_type`.
9. Batch observability содержит candidate selection, blockers, alerts и
   `ai_costs.schema_version=split_ai_costs_v1`, если есть upstream costs.
10. Admin alert attempts сохраняются в `observability.alerts`.

## Test Plan

Минимальный набор:

```bash
python3 -m py_compile \
  core/app/agents/calls/scheduled_reporting.py \
  core/app/agents/calls/reporting.py \
  core/app/agents/calls/run_alerts.py

docker compose exec -T api python -m pytest -q \
  /app/tests/test_manual_reporting.py \
  /app/tests/test_call_processing_reporting_integration.py \
  -k "scheduled or schedule or reviewable or external_service"

git diff --check
```

Новые/обновленные тест-кейсы:

- STT schedule: previous day, idempotent reuse, no manager delivery.
- Analysis schedule: Friday with calls + weekend empty days -> Friday selected.
- Empty day: no calls -> no manager draft/report, clear skip reason.
- Not ready: calls exist, artifacts missing -> review/blocker + admin alert.
- Duplicate: existing draft/report -> no duplicate.
- Split boundary: analysis scheduled path does not call local STT/LLM1.
- Delivery gate: scan/draft does not send manager email; approve does.
- Cost summary: upstream + downstream merged into `observability.ai_costs`.

## Разделение по агентам

### Agent A — scheduler/candidate-selection tests

- Найти текущие scheduled/reviewable tests.
- Добавить тесты:
  - daily 08:00 scan выбирает неотчитанный день по факту звонков;
  - weekend/holiday empty days are skipped;
  - duplicate protection работает;
  - business delivery не вызывается на scan/draft.

### Agent B — split-boundary/cost/alerts tests

- Добавить тесты:
  - external-service scheduled analysis не вызывает local STT/LLM1;
  - upstream costs попадают в scheduled batch observability;
  - blockers/no_data/not_ready сохраняют alert attempts.

### Agent C — implementation hardening

- Внести минимальные кодовые правки по результатам тестов.
- Не менять manager-facing PDF/report content.
- Не включать business delivery на scan/draft.

### Main agent — integration

- Проверить, что тесты не делают реальных provider/email calls.
- Прогнать focused tests.
- Обновить roadmap/status docs.
- Не запускать реальный schedule/pipeline без отдельного approval.
