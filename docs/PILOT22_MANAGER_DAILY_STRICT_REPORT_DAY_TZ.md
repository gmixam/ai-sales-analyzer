# PILOT-22: строгий отчетный день в manager_daily

Дата: 2026-06-12  
Статус: implemented_first_pass / needs controlled rerender verification  
Связанный backlog: `docs/PILOT_BACKLOG.md`, задача `PILOT-22`

## Контекст

Во время полного прогона за `2026-06-11` по Алишеру, Тимуру и Толегену все
отчеты были доставлены на почту, но runner завершился со статусом `partial`.
Особенно заметная проблема появилась по Тимуру:

- за `2026-06-11` у Тимура было `4` звонка;
- содержательный звонок был `1`;
- готовых разборов по содержательным звонкам дня было `0`;
- механизм расширил окно и собрал `signal_report` за `2026-06-10 - 2026-06-11`;
- письмо показало смешанную математику: `Из 1 содержательных ... в
  коучинговый разбор вошло — 18`.

Пользователь утвердил новое правило: менеджерский ежедневный отчет должен
отражать ситуацию выбранного дня как есть. Прошлые дни нельзя подмешивать,
даже если в текущем дне мало данных для полноценного анализа.

## Цель

Сделать `manager_daily` честным однодневным отчетом:

- PDF и email всегда строго за выбранный report day;
- воронка, статусы, список звонков, coaching blocks, readiness и письмо
  считаются из одного и того же дня;
- при низком покрытии анализа отчет показывает честное состояние дня, а не
  добирает кейсы из прошлых дней;
- rolling-window остается допустимым только для РОП / weekly / monthly /
  внутренних сравнений, но не для manager-facing daily.

## Бизнес-правило

Для `preset=manager_daily`:

1. `window_days_used` для manager-facing PDF/email должен быть `1`.
2. `window_start == date_from`, `window_end == date_to`.
3. `group_key` должен использовать выбранный report day, а не предыдущий день.
4. Email subject/body не должен показывать диапазон дат, если оператор запросил
   один день.
5. Если данных мало, отчет не становится "богаче" за счет прошлых дней.
6. Если за день нет готовых разборов, это надо явно показать:
   - найдено в телефонии;
   - содержательных;
   - исключено из списка дня;
   - не вошло в коучинговый разбор из-за отсутствия готового разбора;
   - в коучинговый разбор вошло `0`.
7. Если текущий механизм не может сформировать полезный manager-facing отчет,
   допустимые исходы:
   - `signal_report` строго по текущему дню;
   - `review_required` / operator-only preview;
   - `skip_accumulate`;
   но не расширенный отчет с прошлыми звонками.

## Что изменить

### 1. Readiness / group selection

Найти код, который для `manager_daily` расширяет окно назад при слабом покрытии
текущего дня.

Ожидаемые зоны поиска:

- `core/app/agents/calls/reporting.py`
- функции вокруг:
  - `_build_manager_daily_reports_with_readiness`
  - `_evaluate_manager_daily_readiness`
  - manager daily group/result builders
  - selection/readiness helpers

Нужно разделить два понятия:

- `source_period` / ingest window: может смотреть несколько дней назад для
  технического reuse/source discovery, если это нужно runner.
- `manager_report_period`: всегда только выбранный день для PDF/email/payload.

Если технический source window остается шире, он не должен попадать в
manager-facing report groups, metrics, call list, email subject/body и
coaching-core blocks.

### 2. Report payload scope

Для `manager_daily` все visible sections должны строиться только из звонков
`report_day`:

- header / period;
- верхняя воронка;
- `Из N содержательных...`;
- `БАЛЛЫ ПО ЭТАПАМ`;
- `СИТУАЦИЯ ДНЯ`;
- `РАЗБОР ЗВОНКА`;
- `ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ`;
- `КОНТАКТЫ В РАБОТУ`;
- статусные счетчики;
- `call_breakdown_composer`;
- `situation_day_daily_composer`;
- email preview/body.

Нельзя использовать historical ready analyses как manager-facing content для
текущего daily.

### 3. Low-data day behavior

Если за выбранный день мало готовых анализов:

- не менять период;
- не подмешивать прошлые звонки;
- не показывать "вошло в разбор" больше, чем количество содержательных звонков
  дня;
- не считать `ready_analyses` по расширенному окну;
- добавить/сохранить понятную причину:
  - `low_report_day_analysis_coverage`;
  - `no_ready_report_day_analysis`;
  - `signal_report_ready_report_day_only`;
  - или аналогичный существующий reason code.

Важно: мы не ужесточаем смысловой анализ LLM2. Эта задача только про границы
данных manager-facing daily.

### 4. Delivery gate

Перед business email delivery для `manager_daily` добавить safety check:

- если requested period один день, но artifact/email subject/body содержит
  диапазон дат, delivery должен быть заблокирован или переведен в
  operator-only preview;
- если `coaching_core_total` / `ready_analyses` больше `meaningful_calls_total`
  выбранного дня, delivery должен быть заблокирован или помечен
  `review_required`;
- если `window_days_used > 1` для manager-facing daily, business email delivery
  не допускается.

Telegram/operator preview может оставаться доступным для диагностики, но
менеджеру такой отчет отправлять нельзя.

### 5. Документация

Обновить:

- `docs/MANAGER_DAILY_SELECTION_MODEL.md`
  - заменить/уточнить старое правило rolling-window;
  - явно зафиксировать, что manager-facing daily не расширяет отчетный день.
- `docs/DECISIONS.md`
  - добавить ADR: manager-facing `manager_daily` is strict report-day.
- `docs/PILOT_OPERATIONS.md`
  - post-run audit должен проверять, что period в email/PDF не расширился.
- `docs/PILOT_BACKLOG.md`
  - после реализации обновить статус `PILOT-22`.

## Не делать в этой задаче

- Не менять критерии LLM2 admission.
- Не чинить `llm2_admission_non_commercial_or_unusable`.
- Не менять бизнес-смысл `signal_report` в целом.
- Не добавлять новые LLM-вызовы.
- Не менять weekly/monthly/ROP логику, кроме явного сохранения права этих
  отчетов работать с периодом больше одного дня.
- Не отправлять отчеты менеджерам до контрольной проверки.

## Acceptance Criteria

1. Прогон/ready-only rerender Тимура за `2026-06-11`:
   - subject: только `11 июня 2026`;
   - PDF filename: только `11 июня 2026`;
   - email body: только `11 июня 2026`;
   - нет диапазона `10 июня 2026 - 11 июня 2026`.

2. Математика Тимура за `2026-06-11`:
   - найдено в телефонии: `4`;
   - содержательных: `1`;
   - в коучинговый разбор вошло: `0`;
   - не вошло в коучинговый разбор: `1`;
   - не должно быть `вошло — 18`.

3. Для Алишера и Толегена за `2026-06-11`:
   - report period остается одним днем;
   - `ready_analyses <= meaningful_calls_total`;
   - call list содержит только звонки выбранного дня.

4. Если coverage низкий:
   - отчет остается честным `signal_report` / `review_required` /
     `skip_accumulate` по текущему дню;
   - прошлые звонки не используются как visible content.

5. Business email safety:
   - менеджеру нельзя отправить daily email, если visible report window
     расширился.

## Test Plan

Минимальные focused tests:

- unit/regression на readiness:
  - single-day manager_daily never returns `window_days_used > 1`;
  - no historical calls in manager-facing group when current day has low
    coverage.
- unit/regression на email body:
  - for Timur-like fixture: `meaningful=1`, `ready=0`, historical ready analyses
    exist, email body says `вошло — 0`, not historical count.
- regression на delivery gate:
  - business email blocked if `window_days_used > 1` for manager_daily.
- existing focused tests:
  - `tests/test_manual_reporting.py` manager daily readiness / selection model;
  - `tests/test_calls_delivery_text.py`;
  - `tests/test_situation_day_daily_composer.py` if payload scope changes.

Контрольный ручной прогон после реализации:

```bash
docker compose exec -T api python -m app.agents.calls.manual_reporting_runner \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --preset manager_daily \
  --mode report_from_ready_data_only \
  --date-from 2026-06-11 \
  --date-to 2026-06-11 \
  --manager-id 656abe58-7c23-476a-a9f6-d76305cf42e0 \
  --delivery-mode preview_only
```

После preview-only проверки можно делать rerender/delivery только после явного
подтверждения оператора.

## Ожидаемый результат для пилота

Менеджер получает отчет, который может быть коротким или неполным, но не
обманывает периодом и не смешивает день с прошлыми звонками. Это важнее, чем
искусственно делать отчет "богатым" за счет старых данных.

## Implementation Update 2026-06-12

First pass внедрен:

- `CallsManualReportingOrchestrator._build_manager_daily_windows()` теперь
  возвращает только одно окно: `anchor_day -> anchor_day`,
  `window_days_used=1`.
- `skip_accumulate` / empty-state path получает только artifacts выбранного
  report day, а не весь исходный набор группы.
- Перед business email delivery добавлен `strict_report_day_gate` для
  `manager_daily`. Он блокирует manager email и переводит результат в
  `review_required`, если:
  - payload period не один день;
  - readiness window больше одного дня;
  - window/effective period не совпадает с report day;
  - `included_in_report_total > meaningful_calls_total`.
- Telegram/operator preview остается доступен для диагностики.
- Во время controlled rerender Тимура найден и исправлен смежный bug в
  empty-state email/preview shell: отсутствие `selection_model` и `or` fallback
  превращали `included_in_report_total=0` в `kpi.calls_count`. Теперь
  empty-state payload содержит честный `selection_model`, а email/coverage note
  сохраняют нулевые значения.

Проверено:

```bash
python3 -m py_compile core/app/agents/calls/reporting.py
docker compose exec -T api python -m pytest -q /app/tests/test_manual_reporting.py \
  -k "manager_daily_group_result_does_not_expand_to_previous_workday or expanded_window_payload_is_not_manager_email_safe or manager_daily_group_result_returns_full_report_when_day_is_ready"
```

Результат focused pytest: `4 passed, 240 deselected`.

Следующий шаг: controlled rerender Тимура за `2026-06-11` в `preview_only` /
operator Telegram, затем только после проверки решать вопрос business email.

Controlled rerender Тимура `2026-06-11` в `preview_only` после правки:

- period/source_period: `2026-06-11 -> 2026-06-11`;
- readiness: `skip_accumulate`;
- `window_days_used=1`;
- найдено в телефонии: `4`;
- содержательных: `1`;
- исключено из списка дня: `3` (`too_short_or_no_speech`);
- не вошло в коучинговый разбор: `1` (`нет готового разбора`);
- вошло в коучинговый разбор: `0`;
- Telegram/email delivery: `skipped`.
