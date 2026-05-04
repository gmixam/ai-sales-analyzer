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
| ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ (enrichment) | Renderer cleanup DONE 2026-05-04 (Step 7). Remaining: call reference + dialogue excerpt + stage linkage per situation — require `call_id` in `additional_situations` items |
| ПОЗВОНИ ЗАВТРА: список + opening scripts | Richer `follow_up` use + bounded LLM |
| СПИСОК ЗВОНКОВ: колонка «Контекст» (ситуация per call) | `follow_up.next_step_text` или bounded LLM |
| БАЛЛЫ ПО ЭТАПАМ: детализация критериев внутри этапа | Richer распаковка `criteria_results` |
| БАЛЛЫ ПО ЭТАПАМ: Основная проблема для non-priority stages | Data exists: `criteria_results[].comment + evidence` per stage in DB; `criterion_code` prefix maps to stage_code (`cs_→contact_start`, `qp_→qualification_primary`, `nd_→needs_discovery`). Requires `_aggregate_stage_scores()` in reporting.py to surface worst criterion comment+evidence per stage. No analyzer change needed. |
| СИТУАЦИЯ ДНЯ: evidence quote linked to priority stage | Data exists: `evidence_fragments[i].client_text` is real verbatim text when non-null, linked by `criterion_code` to stage. Requires new `situation_evidence_quote` field in payload built from evidence_fragments where criterion_code starts with priority stage prefix and client_text is not null. |
| БАЛЛЫ ПО ЭТАПАМ: stage-linked gaps / Основная проблема via criterion_code | `gaps` items in DB have `criterion_code` with stage prefix — stage linkage is possible without analyzer change. Requires `_aggregate_finding_items()` to preserve `criterion_code` and `_aggregate_stage_scores()` to match gaps to stages by prefix. |
| РАЗБОР ЗВОНКА: verbatim evidence от реального клиента | `evidence_fragments.client_text` может быть реальной цитатой (non-null); сейчас `call_breakdown.rows` используют LLM-written `evidence_text`. Requires renderer to prefer non-null `client_text` over `evidence_text` when building РАЗБОР ЗВОНКА rows. |
| СИТУАЦИЯ ДНЯ: stage-linked recommendation / checklist | `focus_stage_deep_dive` + priority stage + deterministic stage checklist. | **IMPLEMENTED 2026-05-04 (Step 5)** — `focus_stage_recommendation` surfaced in payload and rendered as `Что сделать в следующих звонках` | ДА | СДЕЛАНО — bounded assembly, no analyzer/LLM change |

Это bounded second-stage layer. Не блокирует пилот.

---

## Manager_daily Content Enrichment — Feasibility Audit Results

**Дата аудита:** 2026-05-04
**Scope:** БАЛЛЫ ПО ЭТАПАМ + СИТУАЦИЯ ДНЯ content enrichment
**Верифицировано на:** Толеген Жангазиев / 2026-04-27 (67→16→9 case: 67 raw, 16 meaningful, 9 eligible coaching в 2-дневном окне 27.04+24.04)

### Ключевое открытие: criterion_code как stage-linkage mechanism

В DB `evidence_fragments` и `gaps` items имеют поле `criterion_code` с stage-prefix:
- `cs_*` → `contact_start`
- `qp_*` → `qualification_primary`
- `nd_*` → `needs_discovery`
- Аналогично для других этапов

Это de facto stage-linkage механизм, существующий в данных, но **не используемый** текущей агрегацией.
Это означает, что per-stage problem и stage-linked evidence quotes можно получить **без изменения analyzer contract** — только через изменение агрегации в `reporting.py`.

### Payload Feasibility Matrix

| Желаемое поле | Текущий source | Статус | Можно рендерить сейчас | Нужно менять механизм |
|---|---|---|---|---|
| `stage_problem_summary_by_stage` (non-priority stages) | `criteria_results[].comment + evidence` per stage в DB; `criterion_code` prefix = stage_code | **IMPLEMENTED 2026-05-04 (Step 2)** — `score_by_stage[].problem_summary` + `problem_source` в payload | ДА | СДЕЛАНО — `_aggregate_stage_scores()` в reporting.py (без analyzer change) |
| `focus_stage_deep_dive` (что пошло не так / почему / что исправить / минимум) | priority stage + `score_by_stage[].problem_summary` + `key_problem_of_day` + stage-specific deterministic fallbacks | **IMPLEMENTED 2026-05-04 (Step 4)** — `focus_stage_deep_dive` surfaced in payload and rendered in `СИТУАЦИЯ ДНЯ` | ДА | СДЕЛАНО — bounded assembly, no analyzer/LLM change |
| `situation_day_what_happened` | `situation.body` / `key_problem.description` | **AVAILABLE** (реализовано) | ДА | НЕТ |
| `situation_day_evidence_quote` | `evidence_fragments[].client_text` (non-null = реальная цитата) связан с `criterion_code` | **IMPLEMENTED 2026-05-04 (Step 3)** — `situation_evidence_quote` surfaced в payload только при stage-linked match | ДА | СДЕЛАНО — matching по criterion_code prefix к priority stage; null-safe |
| `manager_error_summary` | `key_problem_of_day.title` | **AVAILABLE** (реализовано) | ДА | НЕТ |
| `next_time_action_advice` | `situation.manager_task` | **AVAILABLE** (реализовано) | ДА | НЕТ |

### Current Mechanism Verdict

**Renderer-only (уже сделано):**
- `situation_day_what_happened` → "Что произошло: {body}"
- `manager_error_summary` → "Ошибка менеджера: {key_problem.title}"
- `next_time_action_advice` → "Что делать в следующий раз: {manager_task}"
- Priority stage "Основная проблема" → `key_problem_of_day.title`
- Non-priority stage fallback → "Недостаточно данных..."
- Focus block negation → `criterionToProblem(weakCriterion)`

**Что требует механизма (reporting.py changes, no analyzer change):**
1. `[DONE 2026-05-04]` `_aggregate_stage_scores()` — добавлен `problem_summary` / `problem_source` per stage из худшего stage-linked issue (`criteria_results.comment`, затем `gaps`, затем `evidence_fragments`)
2. `[DONE 2026-05-04]` `_aggregate_finding_items()` / stage aggregation — `criterion_code` сохраняется в aggregated gaps; stage matching работает по prefix без analyzer change
3. `[DONE 2026-05-04]` `build_manager_daily_payload()` — добавлено nullable `situation_evidence_quote`: real `evidence_fragments.client_text` matching priority stage criterion_code prefix; renderer показывает `Фрагмент диалога` в `СИТУАЦИЯ ДНЯ`

### Manager_daily Content Enrichment — Step 2 Closure

**Дата:** 2026-05-04

**Реализовано:**
- `score_by_stage[].problem_summary`
- `score_by_stage[].problem_source`
- DOCX/PDF renderer column `Основная проблема` prefers `problem_summary`; fallback remains only when stage data is absent.

**Verified Tolegen 2026-04-27 ready-only case:**
- `raw_calls_total = 67`
- `meaningful_calls_total = 16`
- `included_in_report_total / coaching_core = 9`
- stage summaries surfaced for: Э1 `contact_start`, Э2 `qualification_primary`, Э3 `needs_discovery`, Э4 `presentation`, Э6 `completion_next_step`
- technical criterion codes are not rendered in DOCX (`cs_` / `qp_` / `nd_` absent)

### Manager_daily Content Enrichment — Step 3 Closure

**Дата:** 2026-05-04

**Реализовано:**
- `situation_evidence_quote`
- DOCX/PDF renderer block `СИТУАЦИЯ ДНЯ → Фрагмент диалога`
- strict stage-linked matching: only `evidence_fragments` whose `criterion_code` maps to the priority stage; no `voice_of_customer` substitution.

**Verified Tolegen 2026-04-27 ready-only case:**
- `raw_calls_total = 67`
- `meaningful_calls_total = 16`
- `included_in_report_total / coaching_core = 9`
- quote found: yes
- quote source: `evidence_fragments`, `stage_code=qualification_primary`, `criterion_code=qp_current_process`
- rendered quote: `Клиент: На бумаге или просто по электронной почте.`
- technical criterion codes are not rendered in DOCX (`cs_` / `qp_` / `nd_` absent)

### Manager_daily Content Enrichment — Step 4 Closure

**Дата:** 2026-05-04

**Реализовано:**
- `focus_stage_deep_dive`
- DOCX/PDF renderer block `СИТУАЦИЯ ДНЯ → Разбор фокусного этапа`
- 4 compact rows: `Что пошло не так`, `Почему это проблема`, `Что исправить`, `Минимум на завтра`.

**Verified Tolegen 2026-04-27 ready-only case:**
- `raw_calls_total = 67`
- `meaningful_calls_total = 16`
- `included_in_report_total / coaching_core = 9`
- focus stage: `qualification_primary`
- `what_went_wrong`: `Роль собеседника не была уточнена.`
- `why_it_matters`: `Без понимания роли, процесса и задачи клиента презентация звучит общей и не привязана к реальной потребности.`
- `what_to_fix`: `До презентации задать 2–3 уточняющих вопроса и только потом связывать продукт с задачей клиента.`
- `minimum_for_tomorrow`: `В каждом подходящем sales-звонке зафиксировать роль собеседника, текущий процесс и следующий шаг.`
- technical criterion codes are not rendered in DOCX (`cs_` / `qp_` / `nd_` absent)

### Manager_daily Content Enrichment — Step 5 Closure

**Дата:** 2026-05-04

**Реализовано:**
- `focus_stage_recommendation`
- DOCX/PDF renderer block `СИТУАЦИЯ ДНЯ → Что сделать в следующих звонках`
- deterministic stage checklist with 2–3 manager actions.

**Verified Tolegen 2026-04-27 ready-only case:**
- `raw_calls_total = 67`
- `meaningful_calls_total = 16`
- `included_in_report_total / coaching_core = 9`
- focus stage: `qualification_primary`
- recommendation source: `focus_stage_deep_dive`
- recommendation: `До презентации задать 2–3 уточняющих вопроса и только потом связывать продукт с задачей клиента.`
- checklist: `Уточнить роль собеседника`; `Понять текущий процесс`; `Зафиксировать следующий шаг`
- technical criterion codes are not rendered in DOCX (`cs_` / `qp_` / `nd_` absent)

### Manager_daily Content Enrichment — Step 6A Closure

**Дата:** 2026-05-04

**Scope:** only top blocks through `СИТУАЦИЯ ДНЯ` inclusive.

**Реализовано:**
- removed old `БАЛЛЫ ПО ЭТАПАМ → Фокус на завтра: ...` weak-criteria sub-block;
- introduced unified call reference in situation evidence rendering: `Звонок: {дата}, {время} · {имя} · {телефон}`;
- rewrote `Что произошло` from concrete quote + focus-stage problem instead of meta signal text;
- simplified `СИТУАЦИЯ ДНЯ` table to `Ошибка менеджера` and `Что это значит`;
- removed non-stage-specific scripts/placeholders from this top section;
- removed `Средний чек` column from `ДЕНЬГИ НА СТОЛЕ`; explanatory text now uses `80 000 тенге`.

**Verified Tolegen 2026-04-27 ready-only case:**
- `raw_calls_total = 67`
- `meaningful_calls_total = 16`
- `included_in_report_total / coaching_core = 9`
- old focus sub-block absent;
- call reference rendered as `Звонок: 27 апреля 2026, 11:17 · Азамат · +77082934767`;
- `Что произошло` no longer contains `Главный сигнал дня`, `Приоритетный этап`, or `Паттерн повторился`;
- `Фрагмент диалога` includes call metadata before real `client_text`;
- `Ошибка менеджера`: `Роль собеседника не была уточнена.`;
- `Средний чек` column absent; `80 000 тенге` wording present;
- technical criterion codes are not rendered in DOCX (`cs_` / `qp_` / `nd_` absent).

**Что требует нового LLM step:**
- Ничего из перечисленного выше. Все данные уже в DB.
- Для более глубоких coaching scripts, pattern detection across many calls — нужен bounded LLM step (задокументировано в "Делать после пилота" basket)

### Manager_daily Content Enrichment — Step 6B Closure

**Дата:** 2026-05-04

**Scope:** only `СИТУАЦИЯ ДНЯ`.

**Реализовано:**
- added nullable `payload.situation_dialogue_excerpt`;
- `situation_dialogue_excerpt` is built only from persisted transcript segments or existing `evidence_fragments.manager_text/client_text`;
- exact normalized quote matching is used to locate `situation_evidence_quote.client_text` in persisted transcript segments;
- no `voice_of_customer` substitution, no generated quotes, no STT/LLM rerun;
- `СИТУАЦИЯ ДНЯ` renderer is now a single compact flow: call reference, `Что произошло`, line-by-line dialogue fragment, unified `Разбор ситуации` table;
- removed old standalone renderer pieces inside this block: `Разбор фокусного этапа`, standalone `Что сделать в следующих звонках`, and the lower `Ошибка менеджера / Что это значит` table.

**Feasibility result:**
- surrounding transcript segments are available in persisted `interaction.metadata_.segments`;
- reliable speaker roles are not available for the verified case: segments carry generic `speaker=A`, so manager/client attribution cannot be inferred safely;
- for now, surrounding transcript context is rendered as partial dialogue with `speaker=unknown` (`Реплика`) around the matched real client quote;
- if only `evidence_fragments.client_text` is available, the excerpt stays `is_partial=true` and contains only the client line.

**Verified Tolegen 2026-04-27 ready-only case:**
- `raw_calls_total = 67`
- `meaningful_calls_total = 16`
- `included_in_report_total / coaching_core = 9`
- `situation_dialogue_excerpt.source = transcript_turns`
- `is_partial = true`, `partial_reason = speaker_roles_unavailable`
- rendered call reference: `Звонок: 27 апреля 2026, 11:17 · Азамат · +77082934767`
- rendered dialogue: `Реплика: обороты устраиваем?`; `Клиент: На бумаге или просто по электронной почте.`; `Реплика: смотрите, я у вас базовый пакет покупаю, надо 180 тысяч`
- unified table `Разбор ситуации` is present;
- old standalone headings are absent;
- `Что это значит`, placeholders and technical criterion codes are not rendered in DOCX.

**Future gap for full non-partial dialogue excerpt:**
- persist reliable transcript turns with `turn_id`, `speaker`, `text`, `timestamp`, `call_id`;
- once speaker roles are reliable, `situation_dialogue_excerpt` can switch from partial `unknown` surrounding turns to full manager/client turns without changing analyzer prompts.

### Manager_daily Content Enrichment — Step 6C Closure

**Дата:** 2026-05-04

**Scope:** only `СИТУАЦИЯ ДНЯ`.

**Реализовано:**
- added nullable `payload.situation_day_coaching_view`;
- `situation_day_coaching_view` is deterministic assembly from existing `focus_stage_deep_dive`, `focus_stage_recommendation`, `situation_evidence_quote`, `situation_dialogue_excerpt`, and `score_by_stage`;
- renderer title changed from technical stage/score title to business-facing pattern title;
- focus stage and score moved to a separate meta line;
- `Фрагмент диалога` renamed to `Фрагмент звонка`;
- `Ошибка менеджера` replaced by coaching label `Что не хватило в разговоре`;
- Situation Day review table now uses reference-style rows: `Что это значит`, `Что не хватило в разговоре`, `Что делать в следующий раз`, `Варианты речёвок`;
- deterministic stage-specific scripts are included for `qualification_primary`, `needs_discovery`, `completion_next_step`, and safe fallbacks for other known stages.

**Verified Tolegen 2026-04-27 ready-only case:**
- `raw_calls_total = 67`
- `meaningful_calls_total = 16`
- `included_in_report_total / coaching_core = 9`
- rendered title: `СИТУАЦИЯ ДНЯ · Клиент спрашивает про формат работы, но контекст не уточнён`
- rendered focus meta: `Фокусный этап: Квалификация и первичная потребность — 1.9/5`
- call reference is a separate line;
- `Что произошло` starts from the concrete document-flow question and then gives the coaching conclusion;
- partial call fragment is explicit: `Фрагмент звонка передан частично: роли участников определены не полностью.`;
- `Ошибка менеджера` is absent in the Situation Day slice;
- `Что не хватило в разговоре` and 3 qualification scripts are present;
- placeholders and technical criterion codes are not rendered in Situation Day.

### Manager_daily Content Enrichment — Step 7 Closure

**Дата:** 2026-05-04

**Scope:** only `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` block renderer in `scripts/generate_docx_report.js`. No changes to `report_templates.py`, `reporting.py`, analyzer, LLM, scoring, eligibility, or selection model.

**Реализовано:**
- `dataFromBundle()` additional_situations filter: `signal > 0` AND non-empty title AND title ≠ `Без названия` AND title does not start with `cs_/qp_/nd_/ep_/cl_`; `.slice(0, 3)` enforces max 3; no more wrapping missing title in `«Ситуация»`;
- `buildDopSituatsii()` rewritten: empty-state if no valid situations after filter; dynamic heading: 1 situation → `ДОПОЛНИТЕЛЬНАЯ СИТУАЦИЯ`, 2–3 → `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`; heading not emitted before validity check;
- row labels renamed: `Ситуация / сигнал` → `Что произошло`; `Что хотел сказать клиент` → `Что это значит`; `Как лучше ответить / что делать` → `Что делать в следующий раз`; `Почему это важно` → `Почему это сработает`;
- type label: removed emoji prefixes `✅`/`🔶`, now plain `Сильная сторона` / `Зона роста`;
- signal suffix: `{N} зв.` rendered only when `signal > 0`; `0 зв.` never shown.

**Verified Эльмира 2026-04-06 case:**
- 3 valid situations pass filter: signal=5,3,6; titles: `Не фиксирует конкретный следующий шаг`, `Не проверяет, удобно ли говорить`, `Чётко представляется и называет компанию`;
- heading: `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`;
- type labels: `Зона роста`, `Зона роста`, `Сильная сторона`;
- signal suffix shown: `5 зв.`, `3 зв.`, `6 зв.`; no `0 зв.`;
- row labels renamed as specified above.

**Verified Толеген 2026-04-27 case (signal report):**
- `additional_situations` empty after filter → empty-state renders without error.

**Future tasks for deeper additional situations enrichment:**
- call reference per situation (specific call_id, date, time, contact name) — requires `additional_situations` items to carry `call_id` linkage; currently not in payload;
- compact dialogue excerpt per situation — requires same call_id + evidence_fragment linkage;
- stage linkage per situation — `criterion_code` prefix in `gaps` / `improve_items` could enable this without analyzer change, similar to Steps 2–3 mechanism.

### Manager_daily Content Enrichment — Step 8 Closure

**Дата:** 2026-05-04

**Scope:** only `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ` status taxonomy in `scripts/generate_docx_report.js`, plus supporting Python functions in `report_templates.py` and `reporting.py`. No changes to analyzer, prompts, LLM/STT, scoring, eligibility, selection model, rolling window logic, readiness, delivery, `rop_weekly`, or other report blocks.

**Реализовано:**

`reporting.py` — `_build_daily_call_row()`:
- `artifact.analysis is None` → `status=None, deadline=None` (previously defaulted to `"open"` via `_derive_call_status_and_deadline({})`);
- `call_type in {support, internal}` → `status="tech_service", deadline=None`;
- `_derive_call_status_and_deadline()` called only for analyzed non-support/internal calls.

`report_templates.py`:
- `_call_status_label()` rewritten as clean mapping dict: `None/unknown → "Не классифицировано"`, `"rescheduled" → "Перенос"` (was `"Перенесли"`), `"tech_service" → "Тех/сервис"` added;
- `_call_context_label()`: `status=None → "Нет готового разбора"`;
- `_manager_status_class()` fallback changed from `"open"` to `"neutral"`;
- `_manager_status_fill()`: added `"neutral": (240, 240, 240)`, fallback changed from `mapping[...]` to `mapping.get(..., (240, 240, 240))`.

`scripts/generate_docx_report.js`:
- `allCalls` mapping in `dataFromBundle()` reads `payload.call_list[i]` by row number, checks `call_type in {support, internal} → "Тех/сервис"`, else `statusLabelMap[st] || "Не классифицировано"`; fallback to `row[5]` if no payload entry;
- context fallback: status `"Не классифицировано"` + raw context `"—"` → `"Нет готового разбора"`;
- `buildCoachingWindowNote()` for rolling window (`window_days > 1`) appends `"В список ниже включены только звонки отчётного дня."`.

**Verified Толеген 2026-04-27 bundle:**
- Row 1 (call_type=support, status=open) → rendered `"Тех/сервис"` ✓
- Row 2 (call_type=sales_primary, status=agreed) → `"Договорённость"` ✓
- Row 3 (call_type=support, status=open) → rendered `"Тех/сервис"` ✓
- Row 4 (call_type=sales_primary, status=open) → `"Открыт"` ✓
- Row 5 (call_type=sales_primary, status=agreed) → `"Договорённость"` ✓

**Live DB verification (Толеген 2026-04-27):**
- `type=None, status=None: 12` (was `open: 12`) ✓
- `type=support, status=tech_service: 1` (was `open: 1`) ✓
- `type=sales_primary, status=agreed: 2` ✓
- `type=sales_primary, status=open: 1` ✓

**Tests:** 84 passed (`tests/test_manual_reporting.py`); `node --check scripts/generate_docx_report.js` passed.

**Architecture gap (documented, not fixed, out of scope):**
`call_outcomes_summary` uses coaching_core window (multi-day, 9 calls for Tolegen 27-Apr) while `call_list` uses report-day meaningful calls only (5 for Tolegen bundle, 16 live). This means dashboard НЕ КЛАСС. count ≠ call list НЕ КЛАСС. count after fix. Not a bug introduced here — pre-existing structural split. Fix would require aligning `_build_call_outcomes_summary()` or `call_list` source period; out of scope per task boundary.

**Future task — call_outcomes_summary report-day alignment:**
Align `call_outcomes_summary` to use report-day meaningful calls (not coaching_core window) so that status counts in the day-summary table match the counts in the call list below. Change scope: `reporting.py` `_build_call_outcomes_summary()` — pass report-day artifacts only, not rolling window core. Requires test update for the 9→5/16 count change in outcome summary.

---

### Verified Tolegen 2026-04-27 (67→16→9) State

- `raw_calls = 67` (interactions table, 2026-04-27) ✅
- `meaningful_calls = 16` (из PROGRESS.md; runtime rule: transcript OR CDR answered/in-out/≥90s) ✅
- `coaching_core = 9` (3 eligible на 27.04 + 6 eligible на 24.04, 2-дневный rolling window) ✅
- Структура data в DB: `criterion_code` (stage-prefix), `client_text` (real quotes в 7 из 16 fragments), `evidence_text` (LLM-written), `criteria_results` per stage (все stages, не только priority)
- Реальные клиентские цитаты найдены: "Я вот хотел поинтересоваться...", "На бумаге или просто по электронной почте.", "Просто мы оказываем услуги, с государственными организациями работаем..."

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
