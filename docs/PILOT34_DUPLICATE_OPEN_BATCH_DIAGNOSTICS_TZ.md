# PILOT-34: улучшить диагностику duplicate/open-batch

Дата: 2026-06-17
Статус: implemented_first_pass
Связанные задачи: `PILOT-24`, `PILOT-26`, `PILOT-33`,
`SPLIT-COMPLETE-07F`

## Контекст

После `PILOT-33` функциональная блокировка нового дня старым
`manager_daily` batch снята:

- общий open-batch guard больше не блокирует `manager_daily` до выбора
  конкретного manager-day;
- duplicate protection уточнена до ключа
  `schedule_id + manager_id + report_date`;
- старые `paused` recovery batches больше не шумят в default
  `open-batches` diagnostics.

Оставшийся эксплуатационный хвост: когда candidate day пропускается как уже
обработанный или когда diagnostics показывает открытый batch, оператор видит
только общий факт, но не всегда видит конкретный источник:

- какой batch стал причиной duplicate;
- какой draft стал причиной duplicate;
- по какому `manager_id` и `report_date` найдено совпадение;
- почему batch/draft считается blocker/protector.

Это не мешает автоматическому прогону, но усложняет расследование инцидентов.

## Цель

Добавить конкретные диагностические ссылки в duplicate/open-batch слой, чтобы
Codex/оператор мог быстро ответить:

1. какой именно batch/draft уже защищает manager-day от дубля;
2. почему candidate date был пропущен;
3. какой открытый batch потенциально мешает ручному/автоматическому recovery;
4. что нужно закрыть/проверить, если прогон не двигается.

Важно: задача не должна возвращать старую широкую блокировку. Поведение
создания batch остается таким же, меняется только observability/diagnostics.

## Требования к данным диагностики

### 1. Duplicate guard должен отдавать не только bool

Текущее место:

- `core/app/agents/calls/scheduled_reporting.py`;
- метод `_has_manager_day_duplicate(...)`;
- сейчас возвращает `bool`.

Нужно добавить диагностический результат, например:

```python
{
  "has_duplicate": true,
  "blocked_by_batch_id": "...",
  "blocked_by_batch_status": "review_required|delivered|...",
  "blocked_by_draft_id": "...|null",
  "blocked_by_draft_status": "delivered|...",
  "blocked_by_reason": "matching_open_batch|matching_reported_batch|matching_reported_draft",
  "manager_id": "...",
  "report_date": "YYYY-MM-DD",
  "schedule_id": "...",
  "match_source": "batch_key|draft_group_key|draft_payload_meta"
}
```

Допустимый вариант реализации:

- оставить `_has_manager_day_duplicate(...) -> bool` для backward
  compatibility;
- добавить рядом `_manager_day_duplicate_diagnostics(...) -> dict`;
- `_has_manager_day_duplicate` вызывает новый метод и возвращает
  `has_duplicate`.

### 2. Selection observability должен сохранять причины skip

Когда `_select_manager_day(...)` добавляет дату в
`skipped_already_reported_dates`, рядом должна сохраняться структура:

```json
{
  "skipped_already_reported_details": [
    {
      "report_date": "2026-06-16",
      "manager_id": "...",
      "blocked_by_batch_id": "...",
      "blocked_by_draft_id": null,
      "blocked_by_reason": "matching_open_batch"
    }
  ]
}
```

Где хранить:

- в `ScheduledManagerDaySelection.to_dict()`;
- далее в существующем
  `observability.scheduled_candidate_selection`.

### 3. `open-batches` CLI должен показывать concrete blocker ids

Текущее место:

- `core/report_scripts/scheduled_reporting_preflight.py`;
- `scripts/scheduled_reporting_preflight.py`;
- `_open_batch_row(...)`;
- `_format_open_batch_diagnostics(...)`.

Добавить в JSON-row:

- `blocked_by_batch_id`;
- `blocked_by_batch_status`;
- `blocked_by_draft_ids`;
- `blocked_by_draft_statuses`;
- `manager_ids`;
- `report_date` или `period.date_from/date_to`;
- `blocker_scope`: `same_manager_day`, `open_batch_visibility`,
  `non_manager_daily_global_guard`, если применимо;
- `recovery_hint`: короткая машинно-читаемая подсказка, например
  `recover-open-batches --batch-id <id> --target-status paused --apply`.

В human output добавить одну строку:

```text
blocked_by: batch=<id> status=<status> drafts=<draft ids or ->
```

### 4. Alert/observability без raw JSON

Если duplicate/open-batch blocker всплывает в alert или operator summary,
показывать коротко:

```text
Блокирует старый batch: <id>, status=<status>, period=<date>.
```

Полные details оставить в observability/logs.

## Что не делаем

- Не меняем расписание `04:00`, `09:30`, `10:00`.
- Не меняем STT/LLM/report generation.
- Не возвращаем старую широкую блокировку `manager_daily` по любому open batch.
- Не делаем автоматическое recovery без явной команды.
- Не считаем `paused` batch blocker в default diagnostics.

## Файлы-кандидаты

- `core/app/agents/calls/scheduled_reporting.py`;
- `core/report_scripts/scheduled_reporting_preflight.py`;
- `scripts/scheduled_reporting_preflight.py`;
- `core/tests/test_scheduled_reporting.py`;
- `core/tests/test_scheduled_reporting_preflight.py`;
- при необходимости `docs/call_processing_split/COMPLETION_ROADMAP.md`;
- при необходимости `docs/PILOT_BACKLOG.md`.

## Проверки

Focused tests:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_scheduled_reporting.py \
  /app/tests/test_scheduled_reporting_preflight.py \
  -k "duplicate or open_batch or recovery or blocker"
```

Static checks:

```bash
python3 -m py_compile \
  core/app/agents/calls/scheduled_reporting.py \
  core/report_scripts/scheduled_reporting_preflight.py \
  scripts/scheduled_reporting_preflight.py \
  core/tests/test_scheduled_reporting.py \
  core/tests/test_scheduled_reporting_preflight.py

git diff --check
```

Manual smoke:

```bash
docker compose exec -T api python \
  /app/report_scripts/scheduled_reporting_preflight.py open-batches \
  --preset manager_daily \
  --date YYYY-MM-DD
```

Ожидаемый результат:

- JSON содержит `blocked_by_batch_id` / `blocked_by_draft_ids`, где применимо;
- human output показывает конкретный `batch=<id>`;
- `paused` batch не появляется в default blockers;
- duplicate manager-day skip содержит concrete blocker details в
  `scheduled_candidate_selection`;
- создание нового `manager_daily` за другой manager-day не блокируется старым
  batch.

## Acceptance criteria

1. При duplicate manager-day skip в observability видно, какой batch/draft стал
   причиной.
2. `open-batches` CLI показывает concrete blocker ids и recovery hint.
3. Поведение duplicate guard не ужесточено: меняется диагностика, не фильтры.
4. Default diagnostics не шумит по `paused` recovery batches.
5. Focused tests и `py_compile` проходят.

## Результат реализации 2026-06-17

Внедрено:

- добавлен `ScheduledManagerDaySelection.to_dict()`;
- добавлено поле `skipped_already_reported_details`;
- добавлен `_manager_day_duplicate_diagnostics(...)`;
- `_has_manager_day_duplicate(...) -> bool` сохранен как совместимый wrapper;
- duplicate diagnostics теперь возвращает concrete поля:
  `blocked_by_batch_id`, `blocked_by_batch_status`,
  `blocked_by_draft_id`, `blocked_by_draft_status`,
  `blocked_by_reason`, `manager_id`, `report_date`, `schedule_id`,
  `match_source`;
- `scheduled_candidate_selection` получает details по skipped duplicate dates;
- `open-batches` JSON получил `blocked_by_batch_id`,
  `blocked_by_batch_status`, `blocked_by_draft_ids`,
  `blocked_by_draft_statuses`, `blocker_scope`, `recovery_hint`;
- human output `open-batches` показывает строку `blocked_by: ...` и
  `recovery_hint`;
- runtime copy `scripts/scheduled_reporting_preflight.py` синхронизирован.

Проверено:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_scheduled_reporting.py \
  /app/tests/test_scheduled_reporting_preflight.py \
  -k "duplicate or open_batch or recovery or blocker"
# 14 passed, 24 deselected, 2 subtests passed

docker compose exec -T api python -m pytest -q /app/tests/test_scheduled_reporting.py
# 19 passed, 2 subtests passed

docker compose exec -T api python -m pytest -q \
  /app/tests/test_scheduled_reporting_preflight.py \
  -k "open_batch or recovery or blocker"
# 6 passed, 13 deselected
```
