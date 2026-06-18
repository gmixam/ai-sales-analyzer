# PILOT-35: защита `manager_daily` от тихого пропуска расписания

Дата: 2026-06-18
Статус: `implemented_first_pass`

Связанные задачи: `PILOT-24`, `PILOT-26`, `PILOT-27`, `PILOT-28`,
`PILOT-33`, `PILOT-34`, `SPLIT-COMPLETE-07E`, `SPLIT-COMPLETE-07F`.

## Контекст

В автоматическом режиме split-pipeline уже разделен:

- `00:00 Asia/Almaty` - call-processing строит STT и LLM1 за предыдущий день;
- `04:00 Asia/Almaty` - analysis/reporting должен собрать LLM2/LLM3,
  manager_daily PDF и отправить письма менеджерам/РОП;
- `09:30/10:00 Asia/Almaty` - SLA-check должен подтвердить, что отчеты
  готовы и доставлены.

Инцидент 2026-06-18 показал опасный сценарий: scheduled analysis task был
обработан, schedule сдвинул `next_run_at`, но `scheduled_report_batches` и
`scheduled_report_drafts` за день не появились. Оператор увидел проблему только
после ручной проверки.

Цель этой задачи - закрыть класс дефектов "расписание прошло, но отчетов нет и
понятного сигнала нет".

## Результат реализации 2026-06-18

Внедрено:

- zero-batch guard для `manager_daily`: если scheduled path прошел selection,
  но до guard не создано ни одного batch record, создается failed diagnostic
  batch с reason `manager_daily_zero_batches_after_candidate_selection`;
- `scheduled_manager_daily_run` summary в `observability` и `diagnostics`;
- отдельные счетчики:
  - `report_batches_created` / `batches_created` для реальных manager-day
    records;
  - `diagnostic_batches_created` для zero-batch guard;
  - `failed_batches_count`;
  - `review_required_batches_count`;
  - `approved_for_delivery_batches_count`;
  - `delivered_batches_count`;
  - `report_ready_batches_count`;
- итоговый `status=ok|partial|failed`, чтобы failed/no-draft batches не
  выглядели успешным запуском;
- immediate short operator alert для случая, когда есть failed batches и нет
  report-ready batches;
- zero-batch alert и failed/no-draft alert используют `operator_summary` без raw
  JSON;
- per-manager selection summary получает concrete blocker fields из `PILOT-34`;
- SLA precheck/hardcheck registration дополнительно покрыт тестами.

Проверено:

```bash
python3 -m py_compile \
  core/app/agents/calls/scheduled_reporting.py \
  core/app/agents/calls/run_alerts.py \
  core/report_scripts/scheduled_reporting_preflight.py \
  scripts/scheduled_reporting_preflight.py \
  core/app/core_shared/workers/celery_app.py \
  core/app/core_shared/workers/tasks.py \
  core/tests/test_scheduled_reporting.py \
  core/tests/test_run_alerts.py \
  core/tests/test_scheduled_reporting_preflight.py

docker compose exec -T analysis_api python -m pytest -q \
  /app/tests/test_scheduled_reporting.py \
  /app/tests/test_run_alerts.py \
  /app/tests/test_scheduled_reporting_preflight.py \
  -k "zero_batch or manager_daily or alert or sla or operator_summary or duplicate or blocker"
# 41 passed, 12 deselected, 2 subtests passed

docker compose exec -T analysis_api python -m pytest -q \
  /app/tests/test_call_processing_runtime_split.py \
  /app/tests/test_scheduled_call_processing_upstream.py \
  -k "sla or celery_queue_routing or celery_beat_schedule"
# 6 passed, 14 deselected

git diff --check
```

До `done`:

- подтвердить первый реальный auto-run `04:00 Asia/Almaty`;
- подтвердить первый реальный SLA window `09:30/10:00 Asia/Almaty`;
- убедиться, что при норме alert не приходит, а при miss приходит короткое
  operator summary.

## Цель

Сделать так, чтобы `manager_daily` schedule не мог завершиться "тихо".

Если scheduled run запустился, но не создал ни одного report batch/draft для
ожидаемых manager-days, система должна:

1. сохранить диагностический failed batch или эквивалентный observability
   record;
2. явно указать, какие менеджеры/даты были выбраны или пропущены;
3. отправить короткое operator alert без raw JSON;
4. не помечать такой запуск как успешный;
5. дать Codex/оператору понятный next action для восстановления.

## Что дорабатываем

### 1. Guard от zero-batch scheduled run

#### Проблема

`calls.scan_scheduled_reviewable_reporting` может вернуть schedule как
processed, но фактически не создать batch/draft. В таком случае `next_run_at`
может сдвинуться, а менеджеры и РОП не получат отчеты.

#### Требование

В scheduled `manager_daily` path добавить final guard:

- если schedule был due и обработан;
- если после selection/build попытки создано `0` batches;
- если при этом есть expected manager scope или candidate manager-days;

то создать диагностический failed batch/record с причиной:

```text
manager_daily_zero_batches_after_candidate_selection
```

Диагностика должна содержать:

- `schedule_id`;
- `planned_for`;
- `report_period_rule`;
- `report_date`;
- список manager scope;
- selection summary по каждому менеджеру;
- причину, почему batch не создан;
- ссылку на related run/task id, если доступно.

#### Acceptance

- zero-batch scheduled run больше не проходит без строки в
  `scheduled_report_batches` или равноценной observability записи;
- schedule не выглядит successful, если не создано ни одного usable batch;
- operator alert отправлен один раз на occurrence;
- тест покрывает сценарий: due schedule -> selected managers -> `0` batches ->
  failed diagnostic record + alert.

### 2. Диагностика selection по каждому менеджеру

#### Проблема

Сейчас часть причин можно восстановить только ручными SQL-запросами:
были ли звонки, был ли STT/LLM1, был ли анализ, был ли recipient, был ли
open-batch blocker.

#### Требование

В `scheduled_candidate_selection` или аналогичном diagnostics payload сохранять
по каждому менеджеру строку:

```json
{
  "manager_id": "...",
  "manager_name": "...",
  "report_date": "YYYY-MM-DD",
  "selection_status": "selected|skipped|blocked|not_applicable",
  "reason": "selected|no_calls|no_stt|analysis_not_ready|missing_recipient|blocked_by_open_batch|not_business_day|not_in_department|already_reported",
  "calls_total": 0,
  "calls_with_audio": 0,
  "stt_ready": 0,
  "llm1_ready": 0,
  "analysis_ready": 0,
  "blocked_by_batch_id": null,
  "blocked_by_draft_id": null
}
```

Допустимо хранить счетчики частично, если все данные уже есть в текущем
selection path. Нельзя ради диагностики запускать STT/LLM/LLM1/LLM2.

#### Acceptance

- по каждому active schedule manager можно понять, почему отчет создан или не
  создан;
- no-calls/no-audio/no-stt/analysis-not-ready/missing-recipient различаются;
- diagnostics не требует UI и читается через Codex/SQL/preflight CLI.

### 3. Диагностика duplicate/open-batch blocker

#### Проблема

Если новый report не создается из-за уже существующего batch/draft, нужно
видеть конкретный blocker, а не общий статус.

#### Требование

Использовать и не ломать логику `PILOT-34`:

- `blocked_by_batch_id`;
- `blocked_by_batch_status`;
- `blocked_by_draft_id`;
- `blocked_by_draft_status`;
- `blocked_by_reason`;
- `manager_id`;
- `report_date`;
- `recovery_hint`.

Если `PILOT-34` уже внедрен, в рамках `PILOT-35` нужно только проверить, что
эти поля попадают также в zero-batch / manager-day selection diagnostics и
operator summary.

#### Acceptance

- при blocked manager-day alert/diagnostics содержит конкретный batch/draft id;
- default diagnostics не шумит по `paused` recovery batches;
- поведение guard не ужесточается: меняется видимость, не фильтры.

### 4. Operator alert без raw JSON

#### Проблема

Оператору не нужен длинный JSON. Ему нужно коротко понять: что произошло, кого
затронуло, на что влияет, что сделать.

#### Требование

Для zero-batch / skipped schedule / SLA miss формировать короткое сообщение:

```text
⚠️ Daily reports: отчеты не созданы за 2026-06-17

Что случилось:
Scheduled analysis обработал расписание, но не создал report batches.

Кого затронуло:
- Тимур: analysis_ready=8, batch не создан
- Толеген: analysis_ready=27, batch не создан

На что влияет:
Менеджеры и РОП не получат ежедневные отчеты автоматически.

Что проверить:
scheduled_candidate_selection, open-batches, analysis_worker logs.

Run: manager_daily:<schedule_id>:2026-06-17
```

Полный payload остается в observability/logs, но не в Telegram/email body.

#### Acceptance

- operator alert помещается примерно в `1200-1500` символов;
- нет raw JSON/list of dict в body;
- первые 3-5 affected managers показаны, остальные свернуты счетчиком;
- alert delivery failure не ломает основной run.

### 5. Автоматический SLA-check как страховка

#### Проблема

Даже если `04:00` run дал сбой, до `10:00` система должна сама сообщить, что
отчеты не готовы или не доставлены.

#### Требование

Проверить и довести до production:

- `09:30 Asia/Almaty` precheck;
- `10:00 Asia/Almaty` hardcheck;
- default date = previous report day по Алматы;
- SLA-check только читает состояние, не запускает STT/LLM/report generation;
- при норме молчит;
- при проблеме отправляет короткий alert через `PILOT-28` format.

Если `PILOT-27` уже внедрен, в рамках `PILOT-35` нужна production verification:
beat entries реально загружены в `analysis_beat`, задачи уходят в правильную
queue, и первый реальный run подтвержден.

#### Acceptance

- `analysis_beat` содержит задачи SLA precheck/hardcheck;
- `analysis_worker` принимает эти задачи;
- ручной smoke `sla-check --date auto --phase precheck/hard --dry-run`
  возвращает expected affected rows;
- первый реальный SLA window проверен без Codex.

### 6. Итог scheduled run фиксируется как run summary

#### Проблема

После автоматического запуска нужно видеть итог не только в логах: сколько
менеджеров ожидалось, сколько batch/draft/report/email создано, кто пропущен и
почему.

#### Требование

В observability scheduled run сохранять summary:

```json
{
  "scheduled_manager_daily_run": {
    "schedule_id": "...",
    "planned_for": "...",
    "report_date": "YYYY-MM-DD",
    "expected_managers": 4,
    "selected_manager_days": 2,
    "batches_created": 2,
    "drafts_created": 2,
    "reports_rendered": 2,
    "manager_emails_sent": 2,
    "rop_bundle_sent": true,
    "skipped": [
      {"manager_id": "...", "reason": "no_calls"}
    ],
    "status": "ok|partial|failed",
    "failure_reason": null
  }
}
```

#### Acceptance

- Codex может по одному scheduled run быстро ответить: "что произошло";
- summary попадает в batch observability или отдельный run diagnostics record;
- manual recovery run не смешивается с scheduled run summary.

## Что не делаем

- Не меняем время расписания `00:00`, `04:00`, `09:30`, `10:00`.
- Не меняем качество LLM2/LLM3 и структуру manager report.
- Не запускаем повторный pipeline из SLA-check.
- Не отправляем пустой/сырой отчет ради SLA.
- Не добавляем UI.
- Не делаем автоматическое recovery без явной команды или отдельного ТЗ.

## Файлы-кандидаты

- `core/app/agents/calls/scheduled_reporting.py`;
- `core/app/agents/calls/reporting.py`;
- `core/app/agents/calls/run_alerts.py`;
- `core/report_scripts/scheduled_reporting_preflight.py`;
- `scripts/scheduled_reporting_preflight.py`;
- `core/app/tasks/calls.py` или текущий файл Celery tasks для analysis runtime;
- `core/app/core_shared/config/settings.py`, если нужны env flags;
- `core/tests/test_scheduled_reporting.py`;
- `core/tests/test_scheduled_reporting_preflight.py`;
- `core/tests/test_run_alerts.py`;
- `docs/PILOT_BACKLOG.md`;
- `docs/call_processing_split/COMPLETION_ROADMAP.md`.

## Проверки

Focused tests:

```bash
docker compose exec -T analysis_api python -m pytest -q \
  /app/tests/test_scheduled_reporting.py \
  /app/tests/test_scheduled_reporting_preflight.py \
  /app/tests/test_run_alerts.py \
  -k "zero_batch or manager_daily or sla or alert or duplicate or blocker"
```

Static checks:

```bash
python3 -m py_compile \
  core/app/agents/calls/scheduled_reporting.py \
  core/app/agents/calls/reporting.py \
  core/app/agents/calls/run_alerts.py \
  core/report_scripts/scheduled_reporting_preflight.py \
  scripts/scheduled_reporting_preflight.py \
  core/tests/test_scheduled_reporting.py \
  core/tests/test_scheduled_reporting_preflight.py \
  core/tests/test_run_alerts.py

git diff --check
```

Runtime smoke:

```bash
docker compose exec -T analysis_api python \
  /app/report_scripts/scheduled_reporting_preflight.py --json status

docker compose exec -T analysis_api python \
  /app/report_scripts/scheduled_reporting_preflight.py --json open-batches \
  --preset manager_daily

docker compose exec -T analysis_api python \
  /app/report_scripts/scheduled_reporting_preflight.py sla-status \
  --date auto --json
```

## Agent split

### Agent A - zero-batch guard и run summary

Scope:

- `scheduled_reporting.py`;
- `test_scheduled_reporting.py`.

Задачи:

- добавить final guard для `manager_daily` zero-batch;
- создать failed diagnostic batch/record;
- сохранить `scheduled_manager_daily_run` summary;
- покрыть тестом.

### Agent B - selection diagnostics

Scope:

- `scheduled_reporting.py`;
- `scheduled_reporting_preflight.py`;
- tests.

Задачи:

- добавить per-manager selection diagnostics;
- связать с existing duplicate/open-batch diagnostics;
- убедиться, что `open-batches` / status CLI помогает расследовать blocker.

### Agent C - alerts/SLA verification

Scope:

- `run_alerts.py`;
- `reporting.py`;
- `scheduled_reporting_preflight.py`;
- Celery/beat task registration;
- tests.

Задачи:

- проверить, что zero-batch/SLA alerts используют короткий operator summary;
- подтвердить SLA tasks в `analysis_beat`;
- добавить/обновить tests для короткого alert.

## Definition of Done

Задача считается закрытой, когда:

1. zero-batch scheduled run создает failed diagnostic record и alert;
2. по каждому менеджеру видно, почему отчет создан/не создан;
3. duplicate/open-batch blocker показывает concrete ids;
4. SLA precheck/hardcheck реально привязан к `analysis_beat`;
5. alert human-readable, без raw JSON;
6. focused tests проходят в контейнере;
7. первый следующий auto-run проверен: либо отчеты созданы/доставлены, либо
   система сама прислала понятную проблему.
