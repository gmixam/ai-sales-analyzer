# PILOT-24: стабилизация первого автоматического daily schedule

Дата: 2026-06-16

Статус: `implemented_first_pass`.

Итог внедрения:

- `manager_daily` с `report_period_rule=previous_day` выбирает только
  computed previous day;
- duplicate guard учитывает open/report-ready batches для того же
  `schedule_id + manager_id + report_date`;
- technical failed batch без draft не считается успешным отчетом и не блокирует
  retry;
- analysis -> call-processing timeout поднят до `180` секунд, `ReadTimeout`
  сохраняется с явным reason `call_processing_client_read_timeout`;
- runtime `.env.split.common` обновлен до
  `CALL_PROCESSING_CLIENT_TIMEOUT_SEC=180`;
- focused tests: scheduled reporting / call-processing client / split runtime /
  scheduled upstream `34 passed, 1 skipped`;
- контейнерная проверка показала `call_processing_mode=external_service`,
  `call_processing_client_timeout_sec=180`, alert Telegram enabled.

## Контекст

Первый unattended запуск постоянного split-runtime состоялся:

- `2026-06-16 00:00 Asia/Almaty`: `call_processing_beat` запустил
  `call_processing.ensure_daily_upstream` за `2026-06-15`;
- `2026-06-16 08:00 Asia/Almaty`: `analysis_beat` запустил
  `calls.scan_scheduled_reviewable_reporting`.

Ночной upstream отработал частично успешно:

- найдено `91` interactions;
- STT построено `50`;
- LLM1 построено `50`;
- provider calls made `282` при budget `300`;
- upstream cost около `1.127513 USDT`;
- статус `partial`, technical Telegram alert отправлен.

Дневной reporting не сформировал review drafts/PDF:

- `scheduled_report_batches`: `8` failed;
- `scheduled_report_drafts`: `0`;
- ошибки: `ReadTimeout` и `no_candidate_empty_window`;
- `next_run_at` schedule сдвинулся на следующий день, значит schedule был
  обработан, но результат не готов к review.

## Цель

До следующего автоматического запуска сделать scheduled daily flow надежным:

1. `08:00` должен формировать только отчет за previous day, без догонки старых
   дней.
2. Пока один scheduled batch по schedule/manager/date выполняется, новый scan
   не должен создавать дубль.
3. Analysis не должен падать по короткому timeout при обращении к
   call-processing.

## Scope

В scope:

- `core/app/agents/calls/scheduled_reporting.py`;
- `core/app/agents/call_processing/client.py`, если нужен targeted handling
  timeout/status;
- `core/app/core_shared/config/settings.py` и `.env.analysis.example` /
  `.env.example`, если меняется default timeout;
- реальные runtime env `.env.analysis` только как deployment action;
- tests scheduled reporting / split runtime / call-processing client timeout;
- docs: `docs/PILOT_BACKLOG.md`, `docs/PILOT_OPERATIONS.md`,
  `docs/call_processing_split/COMPLETION_ROADMAP.md` при необходимости.

Не в scope:

- изменение LLM2/LLM3 качества;
- пересборка PDF/шаблонов отчета;
- автодоставка менеджерам;
- weekly/monthly ROP reports;
- ручной повторный полный прогон без отдельного approval.

## Задача 1. Strict previous-day для production `manager_daily`

### Проблема

Сейчас `manager_daily` scheduled branch использует lookback-window и выбирает
`selected_oldest_unreported_date_with_calls`. В первом запуске 16 июня он
выбрал `2026-06-09` и `2026-06-10`, хотя production schedule настроен как
`report_period_rule=previous_day`.

Для пилота это сбивает картину: ежедневный отчет должен отражать вчерашний
день, а не догонять старые даты.

### Требование

Для production `manager_daily` с `report_period_rule=previous_day` и явными
`manager_ids`:

- candidate_dates должен содержать только computed previous day;
- `lookback_days` для этого режима должен быть `1`;
- `selection_reason` должен быть новым явным значением, например
  `selected_previous_day_with_calls`;
- если звонков за previous day нет, фиксировать
  `no_candidate_empty_previous_day`;
- не выбирать старые даты из lookback-window.

Важно: исторический catch-up режим можно оставить только если он явно включен
отдельной настройкой/режимом. По умолчанию production daily schedule не
догоняет старые дни.

### Acceptance

- При `planned_for=2026-06-16 03:00:00Z`,
  `timezone=Asia/Almaty`, `report_period_rule=previous_day` selected date
  может быть только `2026-06-15`.
- В `scheduled_candidate_selection.candidate_dates` только `["2026-06-15"]`.
- В batch period только `{"date_from": "2026-06-15", "date_to": "2026-06-15"}`.
- Старые `2026-06-09` / `2026-06-10` не выбираются.

## Задача 2. Защита от дублей и параллельных scan

### Проблема

`analysis_beat` отправляет `calls.scan_scheduled_reviewable_reporting` каждую
минуту. Первый scan выполнялся около `95` секунд. Пока он еще работал, второй
scan успел создать повторные failed batches.

### Требование

Scheduled reporting должен быть идемпотентным при долгом выполнении:

- если уже есть batch со статусом `planned`, `queued`, `running`,
  `review_required`, `paused` для того же `schedule_id + manager_id +
  report_date`, новый scan не должен создавать еще один batch;
- duplicate check должен учитывать batch, который уже создан, но еще не дошел
  до draft;
- duplicate check должен срабатывать внутри manager-day candidate branch,
  а не только для non-manager branch;
- schedule не должен продвигаться/создавать repeated attempts таким образом,
  чтобы один planned occurrence порождал несколько failed batches за разные
  минуты.

Рекомендуемый путь:

- расширить `_has_manager_day_duplicate(...)`, чтобы он считал open batches;
- использовать `scheduled_candidate_selection.manager_id` и
  `selected_report_date` из `observability`/`diagnostics`, плюс `period`;
- добавить guard на уровне `scan_due_schedules` или `_run_due_schedule`, если
  schedule уже обрабатывается в текущем occurrence.

### Acceptance

- Две параллельные/последовательные попытки `scan_due_schedules()` для одного
  due schedule не создают два batch для одного manager/date.
- При уже существующем `running` batch повторный scan возвращает
  `processed_count=0` или фиксирует skip без создания новой строки.
- В тесте с long-running/open batch количество batches остается `1`.

## Задача 3. Timeout analysis -> call-processing

### Проблема

Утренний reporting получил `ReadTimeout` при обращении analysis к
call-processing. Текущий default:

```text
CALL_PROCESSING_CLIENT_TIMEOUT_SEC=30
```

Для scheduled build_missing/report этого мало, особенно если analysis просит
call-processing добрать artifacts или читает тяжелый ответ.

### Требование

- Увеличить timeout для analysis runtime до безопасного значения:
  рекомендовано `180` секунд.
- В `.env.analysis` runtime поставить:

```text
CALL_PROCESSING_CLIENT_TIMEOUT_SEC=180
```

- В templates/examples отразить production recommendation.
- Если код сейчас hard-fails без подробного reason, добавить observability-safe
  reason: `call_processing_client_read_timeout`.

Дополнительно проверить, можно ли в scheduled reporting после ночного upstream
использовать режим, который не запускает тяжелый ensure повторно, если artifacts
уже готовы. Это вторичный пункт; основной фикс - timeout + strict previous day.

### Acceptance

- Analysis settings внутри контейнера показывает
  `call_processing_client_timeout_sec=180`.
- При timeout ошибка сохраняется как понятный blocker/reason, а не пустой
  `ReadTimeout: `.
- Scheduled reporting не падает на 30-second timeout при нормальном ответе
  call-processing.

## Задача 4. Очистка/политика failed batches первого запуска

### Проблема

Первый автоматический запуск создал failed batches:

- даты `2026-06-09`, `2026-06-10`, `2026-06-15`;
- часть с `ReadTimeout`;
- часть с `no_candidate_empty_window`;
- drafts не созданы.

### Требование

Перед следующей проверкой определить политику:

- failed batches первого запуска не должны считаться успешными отчетами;
- strict previous-day logic не должна считать эти failed rows причиной
  `skipped_already_reported_dates`, если отчета/draft/delivery не было;
- если duplicate guard использует failed rows, он должен отличать terminal
  failure from successful/report-ready states.

Не удалять данные без отдельного operator approval. Для теста можно оставить
failed rows как audit evidence.

### Acceptance

- После фикса failed batches первого запуска не мешают сформировать новый
  review draft за `2026-06-15`.
- `skipped_already_reported_dates` появляется только для реально созданных
  review/delivered reports или intentional terminal states, но не для
  technical failed attempts без draft.

## Тест-план

### Unit/focused tests

Добавить/обновить тесты:

- `previous_day` scheduled manager_daily выбирает только previous day;
- lookback/catch-up не применяется к production previous_day schedule;
- duplicate guard не создает второй batch при open/running batch;
- failed technical batch без draft не блокирует повторный build previous day;
- call-processing client timeout берется из settings/env.

Ориентировочные тестовые файлы:

- `core/tests/test_scheduled_reporting.py`;
- `core/tests/test_scheduled_call_processing_upstream.py`;
- `core/tests/test_call_processing_runtime_split.py`;
- при необходимости `core/tests/test_manual_reporting.py`.

### Runtime preflight после внедрения

Без запуска ручного STT/LLM/report:

```bash
docker compose ps
docker compose exec -T analysis_api python - <<'PY'
from app.core_shared.config.settings import settings
print(settings.call_processing_mode)
print(settings.call_processing_client_timeout_sec)
PY
docker compose exec -T postgres psql -U asa_app -d ai_sales_analyzer -P pager=off -c \
"select id,preset,enabled,start_time,timezone,report_period_rule,mode,business_email_enabled,review_required,next_run_at from report_schedules where deleted_at is null order by created_at desc;"
```

### Controlled verification после внедрения

Только после approval:

- либо безопасный `scan-due` preview для schedule;
- либо дождаться следующего автоматического `08:00`.

Проверить:

- batch только за `2026-06-15` / current previous day;
- no duplicate batches;
- drafts появились;
- business email все еще skipped/gated;
- `observability` содержит clear selection, costs, alerts.

## Stop conditions

Остановить и не запускать повторно auto/report flow, если:

- duplicate batches продолжают создаваться;
- schedule снова выбирает старые даты;
- business email включается автоматически;
- analysis начинает выполнять STT/LLM1 локально вместо external-service;
- call-processing provider budget/quota exhausted.

## Definition of Done

- Три основные правки внедрены: strict previous-day, duplicate/open-batch guard,
  timeout `180`.
- Focused tests passed.
- Runtime settings проверены в контейнерах.
- RoadMap/backlog updated.
- До следующего автоокна нет ручного STT/LLM/report без approval.
