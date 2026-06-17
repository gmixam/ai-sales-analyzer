# PILOT-28: Короткие операторские уведомления без JSON

Дата: 2026-06-16
Статус: implemented_first_pass
Связанные задачи: `PILOT-26`, `PILOT-27`, `SPLIT-COMPLETE-07E`

## Контекст

Production/unattended режим уже использует технические уведомления для ошибок,
SLA и blocked/partial состояний. Сейчас в Telegram/почту оператору могут уходить
слишком большие сообщения с JSON-подобными структурами: `scope`, `counts`,
`errors`, `details`, списки managers/blockers и другие внутренние payload.

Для оператора это неудобно: нужно не видеть сырой JSON, а быстро понять:

- что случилось;
- на кого или на какой день влияет;
- на что это влияет в бизнес-процессе;
- что проверить или перезапустить;
- где искать технические детали.

Полные технические данные удалять нельзя: они должны оставаться в
`observability`, БД и логах для последующего разбора Codex/инженером.

## Цель

Сделать production alert человекочитаемым и коротким:

- без сырого JSON в Telegram/body уведомления;
- с коротким резюме причины и влияния;
- с ограничением размера сообщения;
- с сохранением полных технических деталей в observability/logs.

## Что не меняем

- Не меняем сам механизм прогонов, доставки отчетов и SLA.
- Не скрываем ошибки из observability.
- Не удаляем `details`, `errors`, `scope`, `counts` из внутренних артефактов.
- Не вводим новый UI.
- Не делаем LLM-суммаризацию ошибок: alert summary должен строиться
  детерминированным кодом.

## Текущее место проблемы

Основные точки:

- `core/app/agents/calls/run_alerts.py`
  - `build_run_alert_email(...)`;
  - `_format_errors(...)`;
  - `_format_json(...)`;
  - `_format_telegram_alert(...)`.
- `core/app/agents/calls/reporting.py`
  - `_build_run_monitor_alert_specs(...)`;
  - туда попадают `blockers`, `reason_codes`, report statuses.
- `core/report_scripts/scheduled_reporting_preflight.py`
  - `_send_sla_alert(...)`;
  - сейчас формирует `errors` как list of dict и дублирует это в
    `details={"managers": errors}`.
- `scripts/scheduled_reporting_preflight.py`
  - runtime-mounted copy, должен быть синхронизирован с core script.

## Требуемый формат уведомления

Операторское уведомление должно быть примерно таким:

```text
⚠️ Отчеты за 2026-06-15: проблема с доставкой

Что случилось:
Не доставлены отчеты 2 менеджерам до SLA 10:00.

Кого затронуло:
- Тимур: email failed
- Алишер: нет готового отчета

На что влияет:
Менеджеры не получили ежедневный отчет вовремя.

Что проверить:
scheduled reporting batch, draft delivery, email delivery result.

Run: manager_daily_sla:2026-06-15:hard
```

Если затронуто много строк, показывать первые 3-5 и добавлять строку:

```text
Еще 4 см. в observability/logs.
```

## Правила содержания

1. В Telegram и email body не выводить raw JSON для:
   - `scope`;
   - `counts`;
   - `details`;
   - list/dict внутри `errors`;
   - `blockers`.
2. Допускаются короткие строки вида:
   - `affected_managers: 2`;
   - `failed_reports: 1`;
   - `partial_reports: 3`.
3. Причины должны быть переведены в короткие человекочитаемые формулировки.
4. В уведомлении обязательно должны быть блоки:
   - `Что случилось`;
   - `Кого/что затронуло`;
   - `На что влияет`;
   - `Что проверить`;
   - `Run`.
5. Если событие не связано с конкретными менеджерами, блок назвать
   `Что затронуто`.
6. Максимальная длина Telegram-сообщения: целевой лимит `1200-1500` символов.
   Жесткий лимит можно оставить ниже Telegram API limit, чтобы сообщение не
   дробилось на несколько частей.

## Рекомендуемая реализация

### 1. Добавить operator summary contract

В `run_alerts.py` добавить внутреннюю структуру или helper, например:

```python
@dataclass(frozen=True, slots=True)
class RunAlertSummary:
    title: str
    what_happened: str
    affected: list[str]
    impact: str
    action: str
    run_id: str
```

Либо без публичного dataclass, но с отдельным pure helper:

```python
def build_operator_alert_summary(...) -> str:
    ...
```

Важно: функция должна быть deterministic и тестируемой без SMTP/Telegram.

### 2. Поддержать готовый human summary от caller

Добавить в `send_run_alert(...)` и `build_run_alert_email(...)` опциональный
аргумент, например:

```python
operator_summary: str | None = None
```

Если caller передал `operator_summary`, то:

- Telegram отправляет именно его;
- email body начинается с него;
- технический `scope/counts/errors/details` не добавляется в user-facing body
  или добавляется только как короткая строка `Technical details: see
  observability/logs`.

Если `operator_summary` не передан, `run_alerts.py` должен сам построить
bounded fallback summary из `event/status/run_id/counts/errors`.

### 3. Переписать SLA alert summary

В `scheduled_reporting_preflight.py`:

- оставить полный список affected rows в результате `sla-check` и
  observability;
- в `send_run_alert(...)` передавать короткий `operator_summary`;
- `errors` для alert можно передавать как короткие строки, а не dict;
- `details` не должен попадать в текст уведомления.

Для SLA:

- `precheck` -> warning: "к 09:30 есть отчеты не в delivered-состоянии";
- `hard` -> critical/error: "к 10:00 отчеты не доставлены".

### 4. Переписать manager_daily run monitor summary

В `reporting.py`:

- `_build_run_monitor_alert_specs(...)` должен формировать короткий
  `operator_summary`;
- в summary включить:
  - период;
  - общий статус;
  - количество отчетов по статусам;
  - top reason codes;
  - влияние: "часть менеджеров может не получить отчет" или "отчет требует
    review";
  - действие: "проверить scheduled_report_batches / drafts / observability".

### 5. Ограничить размер и списки

Добавить helper:

```python
def _bounded_lines(lines: list[str], *, max_items: int, omitted_label: str) -> list[str]:
    ...
```

Для managers/errors/blockers показывать не больше 3-5 строк.

### 6. Сохранить технические детали

В observability результат alert attempt должен по-прежнему сохранять:

- channel;
- event;
- level;
- subject;
- status;
- delivery;
- error/error_class при failed alert delivery.

Если нужен полный `details`, он должен храниться в вызывающем result/observability,
но не в body уведомления.

## Категории причин

Добавить небольшой mapping для часто встречающихся причин:

| Технический код | Человеческая формулировка |
| --- | --- |
| `sla_missed` | отчет не доставлен до SLA |
| `missing_artifacts` | не хватило готовых данных для отчета |
| `email_failed` | ошибка отправки email |
| `manager_email_failed` | письмо менеджеру не отправлено |
| `no_calls` | за день нет звонков в scope |
| `no_audio` | звонки есть, но аудио недоступно |
| `stt_error` | ошибка транскрибации |
| `llm_error` | ошибка анализа |
| `llm2_admission_non_commercial_or_unusable` | звонок не принят в коммерческий разбор |
| `quota` / `budget` | ограничение бюджета или лимита |
| `read_timeout` / `ReadTimeout` | таймаут при ожидании сервиса |

Если код неизвестен, показывать его как короткую строку, но не весь JSON.

## Acceptance criteria

1. Telegram alert по SLA содержит короткий текст, а не JSON/list of dict.
2. Email alert body также начинается с короткого operator summary.
3. В уведомлении есть понятное влияние: что не получит менеджер/РОП или какой
   этап остановлен.
4. Полные технические данные доступны в observability/logs.
5. Длинные списки affected managers/errors обрезаются и показывают счетчик
   пропущенных.
6. Alert delivery failure не ломает основной прогон.
7. Runtime-mounted `scripts/scheduled_reporting_preflight.py` синхронизирован с
   `core/report_scripts/scheduled_reporting_preflight.py`.

## Тесты

Добавить/обновить focused tests:

- `core/tests/test_run_alerts.py`
  - `test_telegram_alert_uses_operator_summary_without_json`;
  - `test_email_alert_uses_operator_summary_without_json`;
  - `test_fallback_summary_bounds_structured_errors`;
  - `test_long_affected_list_is_truncated`.
- `core/tests/test_scheduled_reporting_preflight.py`
  - SLA `precheck` alert sends concise warning;
  - SLA `hard` alert sends concise critical/error;
  - full affected rows remain in command result/observability.
- `core/tests/test_manual_reporting.py` или existing alert tests:
  - manager_daily monitor alert passes `operator_summary`;
  - raw blockers/details do not appear in user-facing text.

Smoke:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_run_alerts.py \
  /app/tests/test_scheduled_reporting_preflight.py \
  /app/tests/test_manual_reporting.py -k "run_alert or admin_alert"

git diff --check
```

## Разделение по агентам

### Agent A — Alert formatter

- Изменить `run_alerts.py`;
- добавить `operator_summary` support;
- добавить bounded fallback formatting;
- покрыть `test_run_alerts.py`.

### Agent B — SLA alert caller

- Изменить `core/report_scripts/scheduled_reporting_preflight.py`;
- синхронизировать `scripts/scheduled_reporting_preflight.py`;
- сделать SLA summary для `precheck/hard`;
- покрыть `test_scheduled_reporting_preflight.py`.

### Agent C — Manager daily monitor alert

- Изменить `_build_run_monitor_alert_specs(...)` / `_send_run_monitor_alerts(...)`;
- передавать summary в `send_run_alert`;
- не выводить JSON blockers/details в human text;
- покрыть focused reporting tests.

### Controller

- Проверить, что все alert attempts остаются fail-safe;
- прогнать focused tests;
- проверить текст примерного уведомления вручную;
- обновить `PILOT_BACKLOG.md` статус после реализации.

## Риски

- Можно случайно потерять важную диагностическую информацию из уведомления.
  Защита: сохранять run_id/batch_id и ссылку "details in observability/logs".
- Можно сломать существующие tests, которые ожидают старый body с JSON.
  Такие tests нужно обновить под новое требование: user-facing alert без JSON,
  technical observability сохраняется.
- Telegram и email могут использовать один body; нужно убедиться, что оба
  канала не получают сырой JSON.

## Definition of Done

- `PILOT-28` переведен минимум в `implemented_first_pass`.
- Focused tests passed.
- Пример SLA/manager_daily alert читается как короткое резюме.
- Нет raw JSON/list of dict в Telegram/email body.
- Полные details остались в observability/logs.

## Implementation status

First pass реализован 2026-06-16:

- `run_alerts.py` поддерживает `operator_summary` и deterministic fallback
  summary без raw JSON в user-facing body;
- Telegram alert отправляет короткий summary, email body начинается с summary и
  содержит только ссылку на `observability/logs` для деталей;
- SLA `precheck/hard` передает короткий operator summary, а полный affected
  payload остается в result/observability;
- `manager_daily` run monitor передает короткий operator summary с показателями,
  основными причинами, влиянием и действием оператора;
- runtime-mounted `scripts/scheduled_reporting_preflight.py` синхронизирован с
  `core/report_scripts/scheduled_reporting_preflight.py`.

Проверки:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_run_alerts.py \
  /app/tests/test_scheduled_reporting_preflight.py

docker compose exec -T api python -m pytest -q \
  /app/tests/test_manual_reporting.py \
  -k "manager_daily_run_monitor or terminal_run_skip_accumulate_blocks_manager_email_and_sends_admin_alert or terminal_run_partial_records_failed_admin_alert"

docker compose exec -T api python -m pytest -q \
  /app/tests/test_run_alerts.py \
  /app/tests/test_scheduled_reporting_preflight.py \
  /app/tests/test_manual_reporting.py \
  -k "run_alert or admin_alert"

python3 -m py_compile \
  core/app/agents/calls/run_alerts.py \
  core/app/agents/calls/reporting.py \
  core/report_scripts/scheduled_reporting_preflight.py \
  scripts/scheduled_reporting_preflight.py

git diff --check
```
