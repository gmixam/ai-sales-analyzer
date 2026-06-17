# PILOT-33: manager_daily open-batch guard не должен блокировать новый день

Дата: 2026-06-17
Статус: implemented_first_pass
Связанные задачи: `PILOT-24`, `PILOT-26`, `PILOT-27`, `PILOT-28`

## Контекст

Первый production auto-run после перевода `manager_daily` в расписание
сработал не полностью.

Факт по отчетному дню `2026-06-16`:

- `00:00 Asia/Almaty` split upstream отработал успешно;
- в телефонии найдено `317` записей;
- построено `38` комплектов `transcript`, `transcript_segments`,
  `llm1_first_pass`;
- upstream cost: `0.675425 USDT`;
- LLM2/Report Layer не стартовали;
- manager PDF и ROP email за `2026-06-16` не были отправлены.

Причина: в `scheduled_report_batches` остались старые batches за
`2026-06-15` со статусом `review_required`. Перед запуском любого due schedule
код вызывает общий guard `_has_open_batch(schedule_id)`. Этот guard видит
любой открытый batch по schedule и блокирует весь следующий запуск, даже если
старый batch относится к другому менеджеру/дню.

В итоге в `04:00 Asia/Almaty` schedule был обработан (`processed_count=1`) и
`next_run_at` был перенесен на следующий день, но новые manager-day batches за
`2026-06-16` не были созданы.

## Цель

Сделать так, чтобы старый незавершенный batch не мог блокировать новый рабочий
день для `manager_daily`.

Для `manager_daily` блокировка должна работать на уровне конкретного ключа:

```text
schedule_id + manager_id + report_date
```

а не на уровне всего `schedule_id`.

## Что не делаем

- Не меняем STT/LLM модели.
- Не меняем качество LLM2/LLM3 анализа.
- Не меняем бизнес-правило strict previous-day.
- Не отправляем пустые или сырые отчеты ради SLA.
- Не удаляем исторические batches из базы без явного recovery-шага.
- Не вводим новый UI.

## Текущие затронутые места

Основной код:

- `core/app/agents/calls/scheduled_reporting.py`
  - `scan_due_schedules(...)`;
  - `_run_due_schedule(...)`;
  - `_has_open_batch(...)`;
  - `_run_due_manager_daily_schedule(...)`;
  - `_has_manager_day_duplicate(...)`;
  - `_record_skipped_manager_day_selection(...)`.

Диагностика/CLI:

- `core/report_scripts/scheduled_reporting_preflight.py`
  - `status`;
  - `sla-status`;
  - `sla-check`;
  - возможно отдельная recovery-команда для безопасного закрытия старых
    тестовых batches.

Тесты:

- `core/tests/test_scheduled_reporting.py`;
- `core/tests/test_scheduled_reporting_preflight.py`;
- при необходимости focused reporting tests.

## Проблемная логика

Сейчас в `_run_due_schedule(...)` есть общий guard:

```python
if self._has_open_batch(schedule_id=schedule.id):
    schedule.last_planned_at = schedule.next_run_at
    schedule.next_run_at = self._advance_schedule(...)
    return
```

Это защищает от дублей, но для `manager_daily` стало слишком грубо:

- batch Толегена за 15 июня блокирует Алишера за 16 июня;
- review batch из ручного/тестового режима блокирует production auto-run;
- старый день блокирует новый день;
- оператор не получает понятного alert, что schedule был пропущен.

## Целевая логика

### 1. Для обычных presets

Оставить текущий `_has_open_batch(schedule_id)` guard без изменений, если это
не `manager_daily` candidate-selection flow.

### 2. Для `manager_daily`

Не применять общий `_has_open_batch(schedule_id)` до выбора manager-day
кандидатов.

Вместо этого:

1. Рассчитать candidate report date по schedule.
2. Для каждого `manager_id` отдельно проверить:
   - есть ли звонки за candidate date;
   - есть ли уже batch/draft по этому `manager_id + report_date`;
   - есть ли открытый running/queued batch именно по этому ключу.
3. Запускать отчет для незаблокированных manager-day ключей.
4. Не создавать дубль, если именно этот менеджер/день уже находится в
   `planned`, `queued`, `running`, `review_required`,
   `approved_for_delivery`, `delivered`.
5. Старый batch другого дня/менеджера не должен блокировать новый ключ.

### 3. Review batches

`review_required` остается reported/open статусом для duplicate protection
конкретного manager-day ключа.

Но `review_required` за `2026-06-15` не должен блокировать `2026-06-16`.

### 4. Production vs ручные/test batches

Если batch создан в ручном/test режиме (`business_email_enabled=false` или
`review_required=true`), он не должен блокировать production auto-run другого
дня.

Для того же manager-day ключа он может блокировать duplicate, чтобы не
отправить два отчета за один день.

## Последовательность действий

### Этап 0. Зафиксировать текущий факт

1. Снять статус расписания:

```bash
docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py status
```

2. Снять SLA по отчетному дню `2026-06-16`:

```bash
docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py sla-status --date 2026-06-16
```

3. Зафиксировать в рабочем выводе:
   - upstream ready: `38`;
   - LLM2 analyses: `0`;
   - blocking batches: старые `review_required` за `2026-06-15`;
   - affected managers: Толеген, Алишер.

### Этап 1. Recovery за 2026-06-16

Цель: догнать пропущенный отчетный день без изменения исторических данных о
звонках.

1. Проверить открытые batches по активному schedule:

```sql
select id, status, period, filters, business_email_enabled, review_required
from scheduled_report_batches
where schedule_id = '97e6c120-6aa3-4664-99ae-3982054698d7'
  and status in ('planned','queued','running','review_required','approved_for_delivery','paused')
order by created_at desc;
```

2. Для старых тестовых/review batches за `2026-06-15`, которые уже не должны
   блокировать production, выполнить безопасное закрытие:
   - preferred first pass: перевести в `failed` или `paused` через существующую
     allowed transition;
   - в `errors`/`observability` добавить причину:
     `closed_by_operator_recovery: superseded_test_batch_blocked_production_schedule`;
   - не удалять строки из БД.

3. Запустить catch-up за `2026-06-16` только по недостающей части:
   - LLM2 analysis на готовых `STT + LLM1`;
   - Report Layer;
   - manager email;
   - ROP bundle email.

4. После catch-up проверить:
   - у Толегена и Алишера появились `analyses`;
   - созданы scheduled batches/drafts за `2026-06-16`;
   - PDF построены;
   - manager email delivery status;
   - ROP email status;
   - `sla_status=late` или другой корректный missed/late reason.

### Этап 2. Исправить guard в коде

1. В `_run_due_schedule(...)` изменить порядок:
   - если `_uses_manager_daily_candidate_selection(schedule)` возвращает
     `True`, сразу идти в `_run_due_manager_daily_schedule(...)`;
   - общий `_has_open_batch(schedule_id)` применять только к non-manager_daily
     flow.

2. Проверить, что `_run_due_manager_daily_schedule(...)` уже использует
   `_has_manager_day_duplicate(...)` на уровне manager-day.

3. Если текущая `_has_manager_day_duplicate(...)` недостаточно точна, уточнить:
   - batch period должен совпадать с `report_date`;
   - filters.manager_ids должен содержать текущего менеджера;
   - draft/payload fallback должен совпадать по `manager_id + report_date`;
   - старый batch другого дня не считается дублем.

4. Добавить диагностику, если manager-day пропущен:
   - `selection_reason`;
   - `skipped_already_reported_dates`;
   - `skipped_empty_dates`;
   - `blocked_by_batch_id`, если есть конкретный batch-дубль.

### Этап 3. Добавить alert при пропуске из-за open batch

Если schedule не запускает manager-day из-за найденного дубля/open batch,
должен уходить короткий operator alert:

```text
⚠️ manager_daily за 2026-06-16 не запущен для Толегена

Что случилось:
Найден открытый batch по этому manager-day.

На что влияет:
Отчет менеджеру и РОП не будет отправлен автоматически.

Что проверить:
scheduled_report_batches / scheduled_report_drafts.

Batch: ...
```

Требования:

- без raw JSON;
- полный список деталей оставить в observability;
- использовать правила `PILOT-28`.

### Этап 4. Тесты

Добавить focused tests:

1. `manager_daily` старый `review_required` batch за предыдущий день не
   блокирует новый день.
2. `manager_daily` `review_required` batch по тому же manager/date блокирует
   duplicate.
3. Batch одного менеджера не блокирует другого менеджера.
4. Non-manager_daily presets продолжают использовать общий `_has_open_batch`.
5. `scan_due_schedules` не переносит schedule молча без batch/diagnostics, если
   есть manager-day с calls.
6. Alert summary при blocked duplicate не содержит raw JSON.

Команды:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_scheduled_reporting.py \
  /app/tests/test_scheduled_reporting_preflight.py \
  -k "manager_daily or open_batch or duplicate or sla"
```

Дополнительно:

```bash
python3 -m py_compile \
  core/app/agents/calls/scheduled_reporting.py \
  core/report_scripts/scheduled_reporting_preflight.py \
  scripts/scheduled_reporting_preflight.py

git diff --check
```

### Этап 5. Контрольный прогон

После реализации:

1. Создать тестовый old `review_required` batch за день N.
2. Поставить active manager_daily schedule на день N+1.
3. Запустить безопасный `scan-due`/controlled due scan.
4. Проверить, что:
   - день N+1 создает новые manager-day batches;
   - старый день N не блокирует;
   - дубль по тому же manager/date не создается;
   - schedule корректно переносится на следующий день;
   - в observability есть selection diagnostics.

## Acceptance criteria

1. Старый `review_required` batch за другой день не блокирует новый
   `manager_daily` production auto-run.
2. Дубль по тому же `manager_id + report_date` по-прежнему не создается.
3. Один менеджер не блокирует другого менеджера.
4. Non-manager_daily schedules не теряют защиту от общего open batch.
5. При пропуске manager-day есть понятный reason/diagnostics.
6. Оператор получает короткий alert, если запуск заблокирован конкретным
   batch-дублем.
7. Catch-up за `2026-06-16` можно выполнить без повторного STT/LLM1, используя
   готовые artifacts.
8. После исправления следующий production auto-run не пропускается из-за
   старых review batches.

## Definition of Done

- Recovery за `2026-06-16` выполнен или явно зафиксирован как отдельный ручной
  шаг перед следующим auto-run.
- Кодовый guard исправлен.
- Тесты из Test Plan прошли.
- `docs/PILOT_BACKLOG.md` обновлен.
- После controlled verification статус задачи можно перевести в
  `implemented_first_pass`, после реального auto-run без пропуска - в `done`.

## Implementation status 2026-06-17

Выполнено:

- `manager_daily` flow теперь уходит в candidate selection до общего
  `_has_open_batch(schedule_id)`;
- общий `_has_open_batch(schedule_id)` сохранен для non-manager_daily presets;
- duplicate protection для `manager_daily` уточнена на ключ
  `schedule_id + manager_id + report_date`;
- старый batch другого дня или другого менеджера не блокирует новый manager-day;
- добавлена CLI-диагностика `scheduled_reporting_preflight.py open-batches`;
- добавлена dry-run-first recovery-команда
  `scheduled_reporting_preflight.py recover-open-batches`;
- runtime-mounted `scripts/scheduled_reporting_preflight.py` синхронизирован с
  `core/report_scripts/scheduled_reporting_preflight.py`.

Проверки:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_scheduled_reporting.py \
  -k "manager_daily or open_batch or duplicate"
# 8 passed, 8 deselected

docker compose exec -T api python -m pytest -q \
  /app/tests/test_scheduled_reporting_preflight.py \
  -k "open_batch or blocker or recovery or sla"
# 9 passed, 3 deselected

python3 -m py_compile \
  core/app/agents/calls/scheduled_reporting.py \
  core/report_scripts/scheduled_reporting_preflight.py \
  scripts/scheduled_reporting_preflight.py \
  core/tests/test_scheduled_reporting.py \
  core/tests/test_scheduled_reporting_preflight.py

git diff --check
```

Live dry-run на `2026-06-17`:

- `open-batches` нашел `3` потенциальных блокера за `2026-06-15`;
- `recover-open-batches --before-date 2026-06-16` предложил `3` перехода
  `review_required -> paused`;
- запись в БД не выполнялась, потому что команда была запущена без `--apply`.

Recovery/catch-up 2026-06-17:

- recovery применен к `3` старым batches за `2026-06-15`:
  `review_required -> paused`;
- catch-up за `2026-06-16` выполнен точечно через active production schedule
  `97e6c120-6aa3-4664-99ae-3982054698d7`;
- режим анализа: `CALL_PROCESSING_MODE=external_service`,
  `AI_LLM2_INPUT_PROFILE=compact`;
- STT/LLM1 повторно не строились, LLM1 брался из external artifacts;
- Алишер: `2/2` analyses ready, manager email `delivered`, ROP email `sent`,
  SLA status `late`;
- Толеген: `36` calls with audio, `24` analyses ready, `12` failed as
  `Analyzer did not admit call into layered LLM-2`, manager email `delivered`,
  ROP email `sent`, SLA status `late`;
- Тимур: `4` no-audio calls, draft/PDF создан, manager email `skipped`,
  batch `review_required` с reason `missing_recipient`;
- Илья: no calls, batch `failed/not_applicable` с reason
  `no_candidate_empty_previous_day`;
- schedule после catch-up вернулся на `2026-06-17T23:00:00+00:00`.

Осталось:

1. Наблюдать следующий auto-run и после успешного production дня перевести
   задачу в `done`.
2. Доработать operator visibility:
   - `open-batches` не должен называть paused recovery batches активными
     блокерами - выполнено 2026-06-17;
   - duplicate diagnostics желательно дополнить конкретным `blocked_by_batch_id`
     / `blocked_by_draft_id`;
   - immediate alert при duplicate/open-batch skip остается отдельным хвостом
     после functional fix.

Visibility fix 2026-06-17:

- `paused` убран из default `OPEN_BATCH_STATUSES`, поэтому recovery batches не
  отображаются как active open blockers;
- добавлен `RECOVERABLE_BATCH_STATUSES`, чтобы explicit recovery по
  `--status paused` оставался доступен;
- focused preflight tests: `12 passed, 3 deselected`;
- live `open-batches` после фикса показывает только актуальный open batch
  Тимура за `2026-06-16` (`review_required/missing_recipient`), а старые paused
  batches за `2026-06-15` больше не шумят.
