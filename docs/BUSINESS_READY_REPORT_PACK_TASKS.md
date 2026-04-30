# Business-ready Report Pack — Task Breakdown

## Назначение

Этот документ фиксирует prioritized task breakdown для Вехи 6.5 `Business-ready Report Pack`
на основе сравнения current repo версии `manager_daily` с новой версией отчёта
(`Ежедневный_отчет_v4_ФИНАЛ.pdf`, загружена 2026-04-16).

Документ является source of truth для следующих implementation tasks.
Реализация не начата на момент фиксации документа.

## Веха и шаг

- Веха roadmap: **6.5 Business-ready Report Pack**
- Статус: task breakdown зафиксирован, реализация не начата
- Зафиксировано: 2026-04-16

## Boundary — что разрешено в этой вехе

По `docs/MANUAL_REPORTING_PILOT.md` и `docs/REPORT_BACKLOG_PRIORITIZATION.md`:

**Разрешено:**
- structure / layout polish
- wording / readability
- visual hierarchy
- renderer / template polish
- consistent PDF and short delivery wrapper
- complete and honest list-of-calls presentation

**Запрещено:**
- новая reporting architecture
- redesign analyzer contract
- новые external integrations / CRM data
- revenue / pricing / amount logic
- history / baseline storage
- coaching / pattern engine
- full rich daily mechanism upgrade

## Source of truth — current report layer

| Роль | Файл |
|---|---|
| Renderer / template engine | `core/app/agents/calls/report_templates.py` |
| Active version registry | `core/app/agents/calls/report_template_assets/active_versions.json` |
| Active manager_daily version | `manager_daily_template_v2` |
| Template assets | `core/app/agents/calls/report_template_assets/manager_daily/manager_daily_template_v2/` |
| Short delivery wrapper | `core/app/agents/calls/delivery.py` (строки ~640–720) |
| Reference layout | `docs/report_templates/reference/manager_daily_reference.md` |

## Что главное изменилось в новой версии

Новая версия — coaching-operational report с явным business-action layer.

Ключевые структурные сдвиги:
- Верхний summary: тайлы (% breakdown) → outcome-таблица (ДОГОВОР / ПЕРЕНОС / ОТКАЗ / ОТКРЫТ / ТЕХ/СЕРВИС)
- РАЗБОР (2 колонки) → БАЛЛЫ ПО ЭТАПАМ (таблица с правилом приоритета)
- ГЛАВНЫЙ ФОКУС НА ЗАВТРА (1 абзац) → СИТУАЦИЯ ДНЯ (этап + балл + правило + пример + речёвки)
- СПИСОК ЗВОНКОВ: колонки перегруппированы, добавлена «Тема», убран «Балл»
- Short delivery wrapper: 3-строчный Telegram caption → УТРЕННЯЯ КАРТОЧКА (greeting + итог + 3 приоритета)
- ПАМЯТКА: убрана из новой версии
- Новые блоки, требующие данных которых нет: ДЕНЬГИ НА СТОЛЕ, PIPELINE ТЁПЛЫХ ЛИДОВ, рекорды

## Корзина: Делать сейчас

Критерий: только presentation layer, существующие поля, без новых подключений.

### Task 1 — Top summary: тайлы → outcome-таблица

**Что:** заменить 5 тайлов (звонков / балл / % сильных / % базовых / % проблемных) на
горизонтальную таблицу с абсолютными значениями.

**Колонки:** ЗВОНКОВ | ДОГОВОР | ПЕРЕНОС | ОТКАЗ | ОТКРЫТ | ТЕХ/СЕРВИС

**Данные:** `call_outcomes_summary` (уже в payload) + фильтрация по `classification.call_type`
для выделения ТЕХ/СЕРВИС как отдельной колонки.

**Файлы:**
- `core/app/agents/calls/report_templates.py` — `_build_manager_daily_model()`
- `core/app/agents/calls/report_template_assets/manager_daily/manager_daily_template_v2/`

---

### Task 2 — Short delivery wrapper: УТРЕННЯЯ КАРТОЧКА

**Что:** заменить 3-строчный Telegram caption (subject + template_id + email) на
business-facing morning card.

**Структура карточки:**
- Приветствие: «{Имя}, доброе утро!»
- Итог дня: {N} звонков → {N} Договорились, {N} Открытых
- Top-3 открытых звонка из `call_list` (время + клиент + статус)
- Челлендж-напоминание (только текущий показатель, без рекорда)

**Также:** добавить УТРЕННЯЯ КАРТОЧКА как отдельную секцию в конец PDF.

**Данные:** все из existing `call_list` + `call_outcomes_summary`.

**Файлы:**
- `core/app/agents/calls/delivery.py` — функция `deliver_operator_report()`
- `core/app/agents/calls/report_templates.py` — добавить секцию в `_build_manager_daily_model()`

---

### Task 3 — БАЛЛЫ ПО ЭТАПАМ: таблица + правило приоритета

**Что:** заменить 2-колоночный РАЗБОР (Что сработало / Над чем работать) на
таблицу этапов с visual bars и правилом приоритета.

**Структура таблицы:** Этап | Сегодня | Шкала (visual bar) | Приоритет

**Правило приоритета:** первый этап ниже 4.0 сверху по воронке → отмечается как приоритетный.
Воронка: Э1 → Э2 → Э3 → Э4 → Э5 → Э6 → Сквозной.

**Колонка «Среднее»:** не включать — нет historical data. Добавить только когда будет WP4.

**Данные:** `score_by_stage` (уже в payload).

**Файлы:**
- `core/app/agents/calls/report_templates.py` — `_build_manager_daily_model()`
- Template assets — обновить `semantic.json` под новую секцию

---

### Task 4 — СИТУАЦИЯ ДНЯ: структурный upgrade

**Что:** расширить «ГЛАВНЫЙ ФОКУС НА ЗАВТРА» до блока «СИТУАЦИЯ ДНЯ».

**Структура блока:**
- Заголовок: «СИТУАЦИЯ ДНЯ · {Название этапа} ({балл}) — первый этап ниже 4 по воронке»
- Problem description из `key_problem_of_day.description`
- Deterministic editorial placeholder для речёвок
  (речёвки через LLM — это Task 2-го этапа, здесь только структура + static placeholder)

**Данные:** `score_by_stage` + `key_problem_of_day` (уже в payload).

**Файлы:**
- `core/app/agents/calls/report_templates.py` — секция `main_focus_for_tomorrow` / `key_problem_of_day`

---

### Task 5 — СПИСОК ЗВОНКОВ: перегруппировка колонок

**Что:** изменить состав и порядок колонок call list.

**Было:** Время / Клиент / Длит. / Статус / Балл / Следующий шаг
**Стало:** # / Время / Клиент / Тема / Статус / Следующий шаг

**Изменения:**
- Добавить «#» (нумерация строк)
- Добавить «Тема» из `classification.call_type` / `classification.scenario_type`
- Убрать «Длит.» и «Балл» как отдельные колонки
- «Следующий шаг» оставить

**Данные:** `call_list` (уже в payload), `classification` (уже в scores_detail).

**Файлы:**
- `core/app/agents/calls/report_templates.py` — секция `call_list`
- `core/app/agents/calls/reporting.py` — `_build_call_list_row()`

---

### Task 6 — ПАМЯТКА: сделать опциональной

**Что:** убрать ПАМЯТКА из обязательного состава финального PDF или сделать её опциональной
(добавлять только при явном включении).

**Файлы:**
- `core/app/agents/calls/report_templates.py` — секция `memo_legend`

---

## Корзина: Делать вторым этапом

Критерий: richer assembly из existing fields, без новых подключений.
Выполнять после завершения корзины «Делать сейчас».

| Задача | Что нужно |
|---|---|
| СИТУАЦИЯ ДНЯ: речёвки (3 варианта скриптов) | Bounded report-composer LLM step |
| СИТУАЦИЯ ДНЯ: count паттерна («9 из 41 звонков») | Cross-call pattern detection из `gaps` |
| СИТУАЦИЯ ДНЯ: конкретный пример с именем и временем | Richer payload из `call_list` + `evidence_fragments` |
| РАЗБОР ЗВОНКА (поминутная таблица конкретного звонка) | Richer assembly из `evidence_fragments` |
| ГОЛОС КЛИЕНТА (3 клиентских ситуации) | Bounded report-composer над `evidence_fragments` |
| ДОПОЛНИТЕЛЬНЫЕ 3 СИТУАЦИИ | Bounded report-composer над `gaps` + `evidence_fragments` |
| ПОЗВОНИ ЗАВТРА: список + opening scripts | Richer `follow_up` use + bounded LLM |
| СПИСОК ЗВОНКОВ: колонка «Контекст» (ситуация per call) | `follow_up.next_step_text` или bounded LLM |
| БАЛЛЫ ПО ЭТАПАМ: детализация критериев внутри этапа | Richer распаковка `criteria_results` |

Это bounded second-stage layer. Не блокирует пилот.

---

## Корзина: Делать в последнюю очередь

Критерий: новые подключения, CRM данные, history storage, revenue logic.
Только после пилота.

| Задача | Почему last-priority |
|---|---|
| ДЕНЬГИ НА СТОЛЕ | Revenue/pricing logic, средний чек — новые данные |
| PIPELINE ТЁПЛЫХ ЛИДОВ | Call-type segmentation + historical baseline |
| БАЛЛЫ ПО ЭТАПАМ: колонка «Среднее» | History/baseline storage layer |
| ЧЕЛЛЕНДЖ: рекорд за период | История по менеджеру |
| ПОЗВОНИ ЗАВТРА: приоритизация по теплоте лида | CRM / lead scoring |

---

---

## Selection Model Implementation — Bounded Tasks

Этот раздел фиксирует последовательность bounded implementation tasks для реализации
canonical selection model из `docs/MANAGER_DAILY_SELECTION_MODEL.md`.

**Doc-only фиксация. Код не меняется в этом шаге.**
Реализацию начинать строго по одному bounded task.

### Граница

- Scope IN: реализация трёх слоёв данных, счётчиков, исключений, rolling window transparency, report contract alignment.
- Scope OUT: изменение analyzer contract, readiness thresholds, scheduler, `rop_weekly`, любые LLM-уровневые изменения.

---

### Task SM-1 — Payload / model changes: добавить счётчики и exclusion reasons

**Что:** расширить payload `manager_daily` новыми обязательными полями selection model.

**Поля для добавления:**
- `raw_calls_total`
- `meaningful_calls_total`
- `service_calls_total`
- `coaching_candidate_calls_total`
- `analyzed_calls_total`
- `included_in_report_total`
- `exclusion_reasons` (structured dict: код → количество)

**Файлы:**
- `core/app/agents/calls/reporting.py` — payload assembly
- structured result / observability / diagnostics — добавить эти поля явно

**Acceptance:** все счётчики присутствуют в payload для любого исхода (`full_report`, `signal_report`, `skip_accumulate`, preview-shell); нет магических чисел в service note builder.

---

### Task SM-2 — Meaningful-calls layer: выделить содержательные звонки

**Что:** ввести явную классификацию `meaningful_calls` как промежуточного слоя между `raw_calls` и `coaching_core`.

**Логика:**
- из `raw_calls` исключаются beep / IVR / no-speech / too-short;
- `meaningful_calls` = звонки, прошедшие базовую фильтрацию по длине и наличию speech;
- support/internal звонки с реальным контентом входят в `meaningful_calls` с типом `ТЕХ/СЕРВИС`.

**Файлы:**
- `core/app/agents/calls/reporting.py` — `_build_manager_daily_group_result()` или аналог
- `core/app/agents/calls/intake.py` или source discovery path — если фильтрация там

**Acceptance:** `meaningful_calls_total` реально отличается от `included_in_report_total`; beep/IVR попадают в `too_short_or_no_speech` / `ivr_or_autoanswer`; support попадает в `support_internal` счётчик.

---

### Task SM-3 — СПИСОК ЗВОНКОВ ДНЯ: переключить на meaningful_calls

**Что:** СПИСОК ЗВОНКОВ ДНЯ строить из `meaningful_calls`, а не из `coaching_core`.

**Изменения:**
- вызов для сборки call list читает из `meaningful_calls`, не только из отобранных для report calls;
- звонки без coaching-анализа (support, short, non-eligible) показываются в списке с типом и без coaching-оценки;
- coaching-блоки (СИТУАЦИЯ ДНЯ и др.) по-прежнему только из `coaching_core`.

**Файлы:**
- `core/app/agents/calls/reporting.py` — `_build_daily_call_list()` или аналог
- `core/app/agents/calls/report_templates.py` — СПИСОК ЗВОНКОВ секция

**Acceptance:** менеджер с 15 звонками за день (8 coaching + 7 service/short) видит в СПИСОК ЗВОНКОВ все 15; coaching-блоки используют только 8.

---

### Task SM-4 — Service note и воронка счётчиков

**Что:** перестроить service note / шапку отчёта по canonical воронке из selection model.

**Новый формат:**
```
Найдено в телефонии: {raw_calls_total}
Содержательных разговоров: {meaningful_calls_total}
С готовым разбором: {coaching_candidate_calls_total}
Вошло в отчёт: {included_in_report_total}
[причины исключения, если есть: too_short_or_no_speech: N · support_internal: N · ...]
```

**Файлы:**
- `core/app/agents/calls/reporting.py` — `_build_manager_daily_selection_note()`
- `core/app/agents/calls/report_templates.py` — service note render

**Acceptance:** service note читается как понятная воронка; нет дублирования одного числа; причины исключения показаны явно.

---

### Task SM-5 — Rolling window transparency

**Что:** если rolling window применён (окно > 1 дня), явно показывать это в отчёте.

**Изменения:**
- в service note: «Данные за N рабочих дн. (с {window_start} по {window_end})»;
- в structured result: `window_days_used`, `window_start`, `window_end` — явные поля;
- СПИСОК ЗВОНКОВ ДНЯ при rolling window **не расширяется** — только за выбранный день.

**Файлы:**
- `core/app/agents/calls/reporting.py` — readiness/window path
- `core/app/agents/calls/report_templates.py` — service note render
- structured result schema

**Acceptance:** при окне 1 день — нет упоминания rolling window в отчёте; при окне 2–3 дня — явное указание в service note и structured result; СПИСОК ЗВОНКОВ всегда только за один день.

---

### Task SM-6 — Acceptance checks на известных кейсах

**Что:** верификация нового selection model на зафиксированных known cases.

**Known cases для проверки:**
1. День с > 10 звонками, из них 3–4 coaching-eligible → meaningful > coaching_core, список полный.
2. День с beep/IVR + sales звонками → beep не попадает в список, sales попадает.
3. День с support + sales → support в списке с типом ТЕХ/СЕРВИС, не в coaching-блоках.
4. Короткий follow-up (< 2 мин., live разговор) → в meaningful, в coaching_core если есть анализ.
5. Rolling window: день с 2 eligible → signal_report, window=1; затем добираем ещё 3 из вчера → проверяем window=2.

**Файлы:**
- `tests/test_manual_reporting.py` — добавить acceptance cases
- при необходимости — controlled fixtures

**Acceptance:** все 5 кейсов проходят без регрессий на существующих тестах.

---

## Out of scope для этой вехи

- Изменение analyzer contract
- Изменение scoring baseline
- Redesign `rop_weekly`
- Full rich daily mechanism upgrade (WP1–WP7 из `RICH_DAILY_AND_PILOT_CHANGESET_PLAN.md`)
- Любые новые внешние подключения
- Автоматическая отправка без operator approve

---

## Порядок реализации

Строго по корзинам:

1. Task 1–6 из корзины «Делать сейчас» (в любом порядке внутри корзины)
2. После завершения и live verification — задачи «Делать вторым этапом»
3. «Делать в последнюю очередь» — после пилота

Начинать со второй корзины нельзя, пока первая не закрыта.
