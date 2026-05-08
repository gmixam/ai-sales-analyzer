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
| СИТУАЦИЯ ДНЯ: evidence quote / transcript fragment | Data exists: `evidence_fragments[i].client_text` is real verbatim text when non-null, linked by `criterion_code` to stage. If stage-linked quote is absent, Step 8W uses selected sales-like `call_breakdown.call_id` and persisted `metadata_.segments` / `interaction.text` as bounded evidence fallback. |
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
4. `[DONE 2026-05-06 / Step 8W]` `build_manager_daily_payload()` — if stage-linked `situation_evidence_quote` is absent, `СИТУАЦИЯ ДНЯ` can use selected sales-like `call_breakdown` call as evidence fallback: first `evidence_fragments.client_text`, then persisted `metadata_.segments`, then persisted `interaction.text`; renderer shows an honest insufficient-evidence state only when none of those persisted sources exists.

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

### Manager_daily Content Enrichment — Step 8W Closure

**Дата:** 2026-05-06

**Scope:** only `СИТУАЦИЯ ДНЯ` evidence / fragment assembly and docx-first render empty-state. No analyzer prompt, STT/LLM, scoring, eligibility, selection model, rolling window, business outcome resolver, delivery semantics, or PDF layout change.

**Реализовано:**
- `call_breakdown` now carries `call_id`, `date_label`, `client_phone`, allowing `СИТУАЦИЯ ДНЯ` to reference the same selected sales-like call when separate stage-linked evidence is missing;
- fallback evidence source order: selected call `evidence_fragments.client_text` → selected call `metadata_.segments` → selected call `interaction.text` → honest insufficient-evidence state;
- transcript fallback uses 1-3 bounded lines and preserves unreliable roles as `speaker=unknown` / renderer `Реплика`;
- when no explicit below-threshold priority stage exists but a meaningful key problem is present, focus deep-dive may use the lowest-scoring available stage so `СИТУАЦИЯ ДНЯ` does not contradict an available `РАЗБОР ЗВОНКА`;
- old placeholder `Фрагмент звонка в текущем payload не передан` is replaced with `Недостаточно подтверждённых фрагментов звонков для доказательного разбора ситуации дня.`

**Verified 2026-05-04 ready-only cases:**
- Эльмира `+77012172463 · 06:28`, Тимур `+77751231100 · 09:26`, Толеген `Нур-Султан · 11:46`;
- all three selected calls had persisted transcript + `metadata_.segments`;
- `evidence_fragments.client_text/manager_text` were empty for all three, so `situation_dialogue_excerpt.source = call_breakdown_transcript_segments`;
- rebuilt PDFs: `/tmp/step8w_Эльмира_2026-05-04.pdf`, `/tmp/step8w_Тимур_2026-05-04.pdf`, `/tmp/step8w_Толеген_2026-05-04.pdf`;
- delivery, `build_missing`, STT and LLM were not run.

### Manager_daily Target Architecture — Step 8Y Design: LLM2 `report_evidence`

**Дата:** 2026-05-06

**Scope:** design/docs only. No code implementation, prompt implementation, STT/LLM rerun, `build_missing`, delivery, report rendering change, or mass rebuild.

**Contract created:** `docs/REPORT_EVIDENCE_CONTRACT.md`

**Target architecture:**

```text
STT -> transcript + segments + speaker labels if available
LLM1 -> light classification / routing / analyze-or-skip decision
LLM2 -> deep call analysis + checklist + report-ready evidence package
Reporting layer -> deterministic selection, aggregation, rendering, delivery
```

**Decision:**
- Step 8W transcript/evidence fallback remains the compatibility path for legacy analyses.
- Target behavior is additive `report_evidence` produced by LLM2 during each call analysis.
- Reporting layer must not become the semantic analyzer; it selects report scope, validates/ranks ready candidates, resolves final outcomes deterministically, and renders.

**Minimum `report_evidence` package:**
- `business_outcome` — LLM2 semantic signal for outcome evidence; final `BusinessOutcomeResolver` still wins.
- `situation_candidates` — ready candidates for `СИТУАЦИЯ ДНЯ`.
- `manager_coaching_moments` — ready moments for `РАЗБОР ЗВОНКА`, stage examples, coaching blocks.
- `voice_of_customer` — grounded client quotes for `ГОЛОС КЛИЕНТА`.
- `additional_situations` — additional report-ready situations.
- `follow_up_candidates` — tomorrow candidates, constrained by final resolver status.
- `quote_bank` — reusable grounded quote pool for daily/weekly/future reports.

**Validation principles:**
- `report_evidence_version` required when package is present.
- All enums valid; `stage_code` matches MVP-1 checklist stage codes.
- Speakers are only `manager`, `client`, or `unknown`; unreliable roles stay `unknown`.
- Quotes and dialogue fragments must be grounded in transcript or marked insufficient.
- Weak/ambiguous items can set `usable_in_report=false`.
- `evidence_quality=insufficient` must not render as strong proof.

**Backward compatibility:**

```text
If report_evidence exists and passes validation:
    use report_evidence for candidate ranking and evidence rendering
else:
    use current Step 8W fallback logic
```

**Rollout:**
- Step 8Y — design contract only.
- Step 8Z — implement schema / validator.
- Step 8AA — update LLM2 prompt.
- Step 8AB — persist `report_evidence` in analysis.
- Step 8AC — controlled LLM2 re-analysis for 3-5 calls from `2026-05-04`.
- Step 8AD — wire `manager_daily` to prefer `report_evidence`.
- Step 8AE — rebuild PDFs and compare with Step 8W.
- Step 8AF — human review.
- Step 8AI — separate STT diarization/speaker investigation.

### Manager_daily Target Architecture — Step 8Z Closure: `report_evidence` Schema / Validator

**Дата:** 2026-05-06

**Scope:** schema/validator and unit tests only. No LLM2 prompt change, STT/LLM, `build_missing`, report rendering, `BusinessOutcomeResolver`, scoring/checklist/selection model, delivery, PDF rebuild, or mass re-analysis.

**Implemented:**
- new standalone module `core/app/agents/calls/report_evidence.py`;
- Pydantic models:
  - `ReportEvidencePackage`;
  - `BusinessOutcomeEvidence`;
  - `SituationCandidate`;
  - `ManagerCoachingMoment`;
  - `VoiceOfCustomerItem`;
  - `AdditionalSituationItem`;
  - `FollowUpCandidate`;
  - `QuoteBankItem`;
  - `DialogueTurn`;
  - `ReportEvidenceValidationResult` / `ReportEvidenceValidationIssue`;
- enums for priority, evidence quality, speaker, business signal, business outcome status, problem type, moment type, voice topic, additional situation type, follow-up status and priority;
- helper `canonical_report_stage_codes()` reads stage codes from analyzer `CHECKLIST_DEFINITION["stages"]`, avoiding a duplicated stale stage list;
- helper `validate_report_evidence(scores_detail, transcript) -> ReportEvidenceValidationResult`.

**Validation implemented:**
- missing `report_evidence` is valid legacy state;
- `report_evidence_version` is required when package exists;
- only `v1` is supported;
- enum/schema errors fail validation;
- invalid `stage_code` fails validation;
- speaker must be `manager`, `client`, or `unknown`;
- quote/dialogue text must be transcript-grounded unless item is explicitly `evidence_quality=insufficient` and `usable_in_report=false`;
- `evidence_quality=insufficient` with `usable_in_report=true` fails validation;
- identical `what_happened` / `what_was_missing` in a Situation Day candidate emits warning;
- empty arrays pass and normalize to empty arrays.

**Tests added:**
- valid full package passes;
- missing package returns valid legacy result;
- missing version fails when package exists;
- invalid enum fails;
- invalid stage code fails;
- unsupported speaker fails;
- quote not in transcript fails;
- insufficient evidence marked usable fails;
- duplicated situation fields warn;
- empty arrays pass.

**Next step:** Step 8AA — update LLM2 prompt to produce the already-validated additive `report_evidence` package.

### Manager_daily Target Architecture — Step 8AA Closure: LLM2 Prompt Produces `report_evidence v1`

**Дата:** 2026-05-06

**Scope:** LLM2 prompt asset / analyzer prompt context / prompt regression tests only. No mass STT/LLM, no `build_missing`, no scoring/checklist change, no `BusinessOutcomeResolver` change, no report rendering, no delivery, no PDF rebuild.

**Implemented:**
- `core/app/agents/calls/prompts/analyze.md` now requires fresh LLM2 output to include additive top-level `report_evidence_version="v1"` and `report_evidence`.
- Existing MVP-1 required fields remain required and unchanged.
- Old prompt rule `Do not add extra top-level fields` now allows only the approved additive `report_evidence_version` / `report_evidence` fields.
- `REPORT_EVIDENCE_CONTRACT.md` is now in LLM2 source priority after the approved MVP-1 call-analysis contract.
- Prompt includes grounded schema/instructions for:
  - `business_outcome`;
  - `situation_candidates`;
  - `manager_coaching_moments`;
  - `voice_of_customer`;
  - `additional_situations`;
  - `follow_up_candidates`;
  - `quote_bank`.
- Prompt requires quotes and dialogue fragments to be verbatim transcript text, or else `evidence_quality=insufficient` and `usable_in_report=false`.
- Prompt forbids invented quotes, invented roles, invented manager/client dialogue, invented timestamps, names, or facts.
- Prompt allows only `speaker=manager|client|unknown`; unreliable roles must be `unknown`.
- Prompt says `business_outcome` is semantic signal only; deterministic `BusinessOutcomeResolver` remains final authority.
- Prompt says follow-up candidates are only for `agreement`, `rescheduled`, `open`, and must not be returned for `refusal`, `tech_service`, or `not_suitable`.

**Analyzer prompt context:**
- `core/app/agents/calls/analyzer.py` now loads `docs/REPORT_EVIDENCE_CONTRACT.md` into `approved_sources.report_evidence_contract_markdown`.
- Fresh analyzer instruction version bumped to `edo_sales_mvp1_call_analysis_v2_report_evidence`.
- `schema_version` remains `call_analysis.v1`; checklist/scoring remain unchanged.

**Tests added/updated:**
- prompt regression asserts LLM2 prompt contains `REPORT_EVIDENCE_CONTRACT.md`, additive `report_evidence_version` / `report_evidence`, grounding, resolver authority, and follow-up exclusion instructions;
- existing sample `report_evidence` package still passes `validate_report_evidence`.

**Next step:** Step 8AB — persist / observe `report_evidence` from fresh analyses and expose validation diagnostics without connecting report rendering yet.

### Manager_daily Target Architecture — Step 8AB Runtime Verification: Controlled LLM2 Sample

**Дата:** 2026-05-06

**Scope:** controlled runtime verification on 5 exact persisted interactions from report-day `2026-05-04`. No mass re-analysis, source discovery, STT, `build_missing`, report rendering, `BusinessOutcomeResolver` change, delivery, report rebuild, prompt rewrite, or scheduler work.

**Operational path:**
- direct `CallsAnalyzer.analyze_call()` on already persisted transcripts;
- persisted one new analysis row per selected interaction using instruction version `edo_sales_mvp1_call_analysis_v2_report_evidence`;
- the existing analyzer chain executed its normal LLM1 first-pass helper plus LLM2 deep analysis;
- extractor/source discovery/reporting/delivery runners were not invoked.

**Sample:**

| Call | Type | New analysis id | Validator | Key result |
|---|---|---|---|---|
| Эльмира `06:28 / +77012172463` (`03cb37da-abc5-41c9-b5f2-7cdfafac129c`) | sales-like open | `4f4a317b-7786-46eb-872c-3e9b45cec139` | failed | `business_outcome.status=postponed`, but allowed enum is `rescheduled`; no `situation_candidates` / coaching moments |
| Тимур `09:26 / +77751231100` (`4d3f2ddb-b3b5-4c5f-9a37-07256d88cf58`) | sales-like open | `97ebc8f9-f9cd-434b-8a9b-17e26dddef09` | passed | `business_outcome.status=open`; no `situation_candidates`, coaching moments, VOC, or follow-up candidates |
| Толеген `11:46 / Нур-Султан` (`626894e2-732d-4b38-b6c0-9cd9463478b4`) | sales-like open | `cd6f4198-4424-4395-b0c8-868c1c0affc2` | passed | `business_outcome.status=open`; VOC and follow-up present; no `situation_candidates` / coaching moments |
| Тимур `04:47 / Надежда Анатольевна` (`79ebbb9b-4326-41c0-96bd-3dea7de2e453`) | refusal | `a63a6303-fef2-4437-85fc-2e5633f2e60e` | failed | `business_outcome.status=declined`, but allowed enum is `refusal`; no follow-up candidate, as expected |
| Эльмира `06:30 / +77006973346` (`3337ccea-9a3b-477f-a806-9b30580f22d7`) | tech/service | `ed5a17cb-2e49-41ab-a546-96720fa1b543` | failed | `business_outcome.status=tech_service`, but evidence quote was paraphrased / ungrounded; analysis row is semantic-failed after retry |

**Findings:**
- `report_evidence_version="v1"` and `report_evidence` appeared in all 5 fresh outputs.
- Only 2/5 outputs passed `validate_report_evidence`.
- Primary schema issue: LLM2 still uses legacy outcome words (`postponed`, `declined`) instead of contract enums (`rescheduled`, `refusal`).
- Primary grounding issue: tech/service evidence can be a paraphrase rather than transcript quote.
- Primary content-quality issue: `situation_candidates` and `manager_coaching_moments` were empty across the sample, including sales-like open calls.
- Existing MVP-1 required fields remained present in 4/5 successful analyses; one tech/service call remained a failed semantic analysis and is not ready for report use.

**Decision:**
- Do not wire `manager_daily` to prefer `report_evidence` yet.
- Step 8W legacy transcript/evidence fallback remains the reporting-safe path.
- Add a bounded prompt-quality follow-up before Step 8AD.

**Next step:** Step 8AC — tighten LLM2 `report_evidence` prompt examples/constraints and rerun a small sample before report integration.

### Manager_daily Target Architecture — Step 8AC Closure: Prompt Tightening + Controlled Rerun

**Дата:** 2026-05-06

**Scope:** prompt asset / analyzer retry instruction / prompt regression tests plus controlled LLM2 sample on the same 5 exact persisted `2026-05-04` interactions. No mass re-analysis, source discovery, STT, `build_missing`, report rendering, `BusinessOutcomeResolver`, delivery, report rebuild, scheduler, scoring or checklist changes.

**Implemented prompt constraints:**
- strict `report_evidence.business_outcome.status` allowed-only block: `agreement`, `rescheduled`, `refusal`, `open`, `tech_service`, `not_suitable`;
- explicit mapping from drift values: `postponed/delayed -> rescheduled`, `declined/rejected/not interested -> refusal`, `support/service/technical help -> tech_service`, interest without firm step -> `open`;
- `business_outcome.evidence_quote` must be an exact transcript substring or `null`;
- example quotes are schema illustrations only and must not be copied unless the exact phrase appears in transcript;
- `service/support/tech_service` are forbidden as `stage_code`; service issue quotes must use canonical checklist stage codes;
- sales-like outcomes (`agreement`, `rescheduled`, `open`) must return at least one `manager_coaching_moment`, and at least one of `situation_candidates` / `manager_coaching_moments` must be non-empty, with `evidence_quality=insufficient` + `usable_in_report=false` when the transcript is too thin.

**Analyzer retry prompt:**
- semantic-empty retry instruction now preserves additive `report_evidence_version="v1"` / `report_evidence`;
- retry also repeats the sales-like minimum package so LLM2 does not repair only MVP-1 `score_by_stage` while leaving report evidence empty.

**Controlled v7 rerun results:**

| Call | Type | Step 8AB validator | Step 8AC validator | New analysis id | Key result |
|---|---|---|---|---|---|
| Эльмира `06:28 / +77012172463` | sales-like open | failed | passed | `d353c6ea-515e-422d-b54e-e43fd1959d3b` | `rescheduled`; situation `1`, coaching `1`, VOC `1`, follow-up `1` |
| Тимур `09:26 / +77751231100` | sales-like open | passed | passed | `3e11a6ab-d8bb-4aa4-b824-77d62c5ede3e` | `open`; coaching `1`, follow-up `1`; no empty richness regression |
| Толеген `11:46 / Нур-Султан` | sales-like open | passed | passed | `b023f1ae-8313-483e-90fb-6e0873eebe5b` | `open`; situation `1`, coaching `1`, VOC `1`, follow-up `1` |
| Тимур `04:47 / Надежда Анатольевна` | refusal | failed | passed | `88c42d92-3abe-4d06-86c9-3c1d83438d68` | `refusal`; no follow-up candidate |
| Эльмира `06:30 / +77006973346` | tech/service | failed | passed | `02327df1-e68a-4b86-80a7-ad4f5abca5cd` | `tech_service`; `evidence_quote=null`; no follow-up candidate; persisted as expected non-coachable semantic-failed row |

**Decision:**
- pass rate improved from `2/5` to `5/5`;
- invalid enum failures: `0`;
- ungrounded evidence failures: `0`;
- sales-like richness improved from `0/3` to `3/3` calls with situation or coaching evidence;
- Step 8AD can proceed as a bounded reporting integration that prefers valid `report_evidence` when present, while keeping Step 8W fallback and non-coachable safeguards.

**Next step:** Step 8AD — wire `manager_daily` to prefer valid `report_evidence` for candidate ranking/evidence rendering, with fallback to legacy Step 8W behavior when missing/invalid.

### Manager_daily Target Architecture — Step 8AD Closure: Reporting Prefers Valid `report_evidence`

**Дата:** 2026-05-06

**Scope:** `manager_daily` report payload assembly only. No LLM2 prompt changes, validator schema changes, `BusinessOutcomeResolver` final-authority changes, scoring, eligibility, selection model, rolling window, source discovery, STT, `build_missing`, mass LLM, delivery, scheduler, or PDF layout changes.

**Implemented:**
- `build_manager_daily_payload()` now creates a report-day `report_evidence` validation index over operational `meaningful_calls`;
- validation uses `validate_report_evidence(scores_detail, transcript)` once per call and records `report_evidence_available`, `report_evidence_valid`, errors, warnings, version, and `report_evidence_source`;
- valid `report_evidence` is preferred for `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`, and follow-up enrichment in `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`;
- missing or invalid `report_evidence` uses existing Step 8W fallback logic;
- final outcome remains deterministic: `BusinessOutcomeResolver` / final `payload.call_list[]` still decide call-list status, money counters, and tomorrow inclusion/exclusion.

**Source policy now in payload diagnostics:**

```
valid report_evidence -> prefer for report evidence candidates
missing/invalid report_evidence -> legacy_fallback
report_evidence.business_outcome -> semantic signal only
BusinessOutcomeResolver -> final manager-facing outcome authority
```

**Read-only verification on `2026-05-04`:**

No `run_report`, source discovery, STT, LLM, `build_missing`, report rebuild, or delivery was invoked. The verification built persisted payloads and render models directly and saved `/tmp/step8ad_summary_2026-05-04.json`.

| Manager | call_list_dates | gate | totals unchanged | valid report_evidence | report_evidence used | fallback used |
|---|---|---|---|---:|---:|---:|
| Эльмира | `["2026-05-04"]` | passed | yes | 2/12 | 2 | 6 |
| Тимур | `["2026-05-04"]` | passed | yes | 2/15 | 1 | 8 |
| Толеген | `["2026-05-04"]` | passed | yes | 1/6 | 4 | 3 |

Step 8R/8V outcome totals remained unchanged:

| Manager | Meaningful | Договорённость | Перенос | Отказ | Открыт | Тех/сервис | Не подходит |
|---|---:|---:|---:|---:|---:|---:|---:|
| Эльмира | 12 | 1 | 1 | 2 | 2 | 6 | 0 |
| Тимур | 15 | 3 | 1 | 2 | 6 | 2 | 1 |
| Толеген | 6 | 0 | 0 | 1 | 3 | 2 | 0 |

**Next step:** Step 8AE — rebuild/compare PDFs after report_evidence wiring when human-review artifacts are needed; keep Step 8W fallback for all legacy analyses.

### Manager_daily Target Architecture — Step 8AE Closure: PDF Rebuild and Step 8W Comparison

**Дата:** 2026-05-06

**Scope:** ready-only artifact rebuild and quality comparison only. No source discovery, STT, `build_missing`, new LLM analyses, prompt changes, validator changes, `BusinessOutcomeResolver` changes, delivery, or PDF layout changes.

**Artifacts:**
- `/tmp/step8ae_Эльмира_2026-05-04.pdf`
- `/tmp/step8ae_Тимур_2026-05-04.pdf`
- `/tmp/step8ae_Толеген_2026-05-04.pdf`
- `/tmp/step8ae_summary_2026-05-04.json`

**Safety verification:**
- `call_list_dates=["2026-05-04"]` for all three managers;
- rolling-window calls absent from call list;
- `manager_facing_completeness.status=passed`;
- no `OPERATOR PREVIEW / INCOMPLETE`;
- no old `Фрагмент звонка в текущем payload не передан`;
- outcome totals unchanged from Step 8R/8V.

| Manager | evidence available | evidence valid | situation source | breakdown source | VOC source | additional source |
|---|---:|---:|---|---|---|---|
| Эльмира | 2 | 2 | deterministic fallback | `report_evidence.manager_coaching_moments` | `report_evidence.voice_of_customer` | legacy fallback |
| Тимур | 2 | 2 | deterministic fallback | legacy fallback | legacy fallback | legacy fallback |
| Толеген | 1 | 1 | `report_evidence` | `report_evidence.manager_coaching_moments` | `report_evidence.voice_of_customer` | legacy fallback |

**Comparison with Step 8W:**
- Эльмира is partially better: `РАЗБОР ЗВОНКА` and `ГОЛОС КЛИЕНТА` now use valid report evidence, but `СИТУАЦИЯ ДНЯ` remains fallback because the LLM2 situation candidate is `evidence_quality=insufficient` / `usable_in_report=false`.
- Толеген is better: `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, and one tomorrow follow-up use valid report evidence.
- Тимур is still not human-review ready: normal sales-like report evidence only enriches one follow-up; usable Situation/VOC evidence is absent, usable coaching is insufficient, and legacy fallback selects an IVR-like fragment for `СИТУАЦИЯ ДНЯ` / `РАЗБОР ЗВОНКА`.

**Decision:** do not proceed to Step 8AF human review with these PDFs as final artifacts. Add a bounded quality follow-up before human review: either improve Timур sales-like `report_evidence` richness for open calls, or tighten legacy fallback ranking so IVR-like fragments are not selected when report evidence is missing/unusable.

### Manager_daily Target Architecture — Step 8AF Closure: Тимур Evidence Quality Follow-up

**Дата:** 2026-05-06

**Scope:** bounded quality fix before human review. No STT, source discovery, `build_missing`, mass LLM, delivery, final `BusinessOutcomeResolver` changes, money-rule changes, prompt rewrite, or report runner invocation.

**Diagnosis:**
- Step 8AE selected Тимур `12:09 / +77470957591` (`ba0fbc39-33f3-4f27-b978-dc2ef9ab75d0`) for `СИТУАЦИЯ ДНЯ` / `РАЗБОР ЗВОНКА` through legacy fallback.
- The old fragment was IVR-like / greeting-only (`Вас приветствует...`, `Наберите внутренний номер...`) and was not acceptable as manager-facing proof while richer sales-like report-day calls existed.

**Implemented:**
- legacy fallback evidence utility in `reporting.py`: `is_greeting_only_fragment`, `is_low_information_fragment`, `fragment_information_score`;
- Situation Day transcript fallback now skips greetings, name confirmation, connection/noise, and IVR-like boilerplate; low-information fragments are last-resort only and marked weak;
- legacy `РАЗБОР ЗВОНКА` ranking now prefers candidates with meaningful business evidence before lowest-score tie-breaking;
- fresh LLM2 gap items with `text` but no `title` are accepted by report aggregation / call-breakdown fallback;
- docx renderer shows an explicit weak-fragment note for `partial_reason=low_information_fragment_only`.

**Controlled LLM2 sample:**

Direct `CallsAnalyzer.analyze_call()` only, on persisted transcripts for 3 exact Тимур `2026-05-04` interactions:

| interaction_id | time | new analysis | validator | useful package |
|---|---:|---|---|---|
| `3d7f0ba0-2c88-482f-89b7-283b67a76fad` | 09:14 | `c2281d67-89d5-4f29-86dd-5bf6d0eeaeb6` | passed | `agreement`, follow-up `1` |
| `489676d0-0fc8-4457-819d-9167de42425b` | 09:22 | `fb93126a-fcbd-4d23-89bd-709728a2af71` | passed | `open`, VOC `1`, follow-up `1`, weak situation/coaching marked unusable |
| `ba0fbc39-33f3-4f27-b978-dc2ef9ab75d0` | 12:09 | `2ae15a76-cf82-46c6-8472-d908a9cc3861` | passed | `open`, usable situation `1` |

**Ready-only verification:**

Artifact copied to host:
- `/tmp/step8af_Тимур_2026-05-04.pdf`
- `/tmp/step8af_timur_summary_2026-05-04.json`

| Manager | call_list_dates | gate | outcome totals | report_evidence valid | Situation source | Breakdown source | VOC source |
|---|---|---|---|---:|---|---|---|
| Тимур | `["2026-05-04"]` | passed | `15 / 3 / 1 / 2 / 6 / 2 / 1` | 5/15 | `report_evidence.situation_candidates` | legacy fallback, meaningful `07:48`, score `20` | `report_evidence.voice_of_customer` |

**Decision:** Тимур no longer uses IVR/greeting-only evidence for `СИТУАЦИЯ ДНЯ` or `РАЗБОР ЗВОНКА` when a better candidate exists. Proceed to bounded human-review handoff with Step 8AF artifact set; remaining richness gaps are normal prompt/report_evidence iteration, not a blocker for this artifact handoff.

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

**Architecture gap (documented, fixed in Step 8B):**
`call_outcomes_summary` previously used coaching_core window (multi-day), while `call_list` used report-day meaningful calls only. Fixed in Step 8B — see closure section below.

---

### Manager_daily Content Enrichment — Step 8B Closure

**Дата:** 2026-05-05

**Scope:** only `reporting.py` and `report_templates.py`. No changes to `scripts/generate_docx_report.js`, analyzer, prompts, LLM/STT, scoring, eligibility, rolling window, coaching_core selection logic, delivery, `rop_weekly`, or scheduler.

**Root cause:**
`_build_call_outcomes_summary()` received `artifacts` (coaching_core, rolling multi-day window), while `call_list` was built from `operational_day_artifacts` (report-day meaningful only). The mismatch caused ИТОГ ДНЯ to show totals from a different population than the list below it.

**Реализовано:**

`reporting.py` — `_build_call_outcomes_summary()`:
- Now explicitly counts `artifact.analysis is None` as `unclassified += 1` instead of routing through `_derive_call_status_and_deadline({})` which returned `"open"`;
- Added `unclassified_count` to the return dict.

`reporting.py` — `build_manager_daily_payload()`:
- `call_outcomes_summary` computation moved to after `operational_day_artifacts` is built;
- New `operational_meaningful_artifacts = [a for a in operational_day_artifacts if _classify_meaningful_call(a)[0]]` — same source as `call_list`;
- `call_outcomes_summary = _build_call_outcomes_summary(artifacts=operational_meaningful_artifacts)`.

`report_templates.py` — `_build_manager_daily_model()`:
- `total_calls` now reads `selection_model.meaningful_calls_total` (falls back to `kpi.calls_count` for older payloads);
- `outcome_cols` appends `{"label": "НЕ КЛАСС.", "value": unclassified_count, "tone": "neutral"}` when `unclassified_count > 0`.

**Coaching blocks unchanged:** `artifacts` (coaching_core) still used for `kpi_overview.calls_count`, `level_counts`, `average_score`, and all coaching-layer blocks.

**Verified (live ready-only rebuilds 2026-05-04):**
- Толеген: meaningful=6, outcomes sum=6 (1 agreed + 5 unclass), coaching_core=8 (3-day window) ✓
- Тимур: meaningful=15, outcomes sum=15 (15 unclass), coaching_core=2 (3-day window) ✓
- Эльмира: meaningful=12, outcomes sum=12 (12 unclass), coaching_core=4 (3-day window) ✓

All: `categories_sum == meaningful_calls_total: True`; coaching blocks confirmed separate.

**Tests:** `pytest tests/test_manual_reporting.py tests/test_ai_provider_routing.py` — 106 passed.
One test updated: `call_outcomes_summary["agreed_count"]` changed from `2` to `1` in `test_build_manager_daily_payload_enriches_outcomes_focus_and_dynamics` — correct, only report-day calls count (1 call on 2026-03-25, not 2 calls from 2-day window).

---

### Manager_daily Content Enrichment — Step 8C Closure

**Дата:** 2026-05-05

**Scope:** only `core/app/agents/calls/orchestrator.py` and `core/tests/test_manual_reporting.py`. No changes to analyzer, prompts, LLM/STT, scoring, eligibility, selection model, Step 8B outcome logic, coaching blocks, report templates, `rop_weekly`, or scheduler.

**Root cause:**
`_replace_insights()` in `orchestrator.py` passed `item.get("evidence")` / `item.get("quote")` directly as `Insight.quote` (mapped to `TEXT` column). The LLM contract returns `evidence` as `list[dict]` transcript segments (`[{start_ms, end_ms, text}]`). psycopg2 cannot serialize `list` or `dict` to `TEXT` → `ProgrammingError: can't adapt type 'dict'`. Error was silent for calls with `evidence=[]` (no INSERT rows), but crashed on the first call with non-empty segments (Тимур Жуматаев, segments=6, stages=3). Two UI-run attempts (05:31 and 07:37 UTC, 2026-05-05) both returned HTTP 500.

**Реализовано:**

`orchestrator.py`:
- New module-level function `_normalize_insight_quote(value: Any) -> str | None` added before `PilotTargetConfig`;
- Rules: `None → None`; `str → stripped or None`; `list[dict] → join item["text"]`; `list[str] → join non-empty`; `empty list → None`; `dict → dict["text"] or json.dumps`; `unknown → str() or None`;
- All three quote assignment sites in `_replace_insights()` updated: strengths/gaps `evidence` (lines 406, 417) and product_signals `quote` (line 428).

`test_manual_reporting.py`:
- New test class `InsightQuoteNormalizerTests` — 14 tests covering: None, empty string, whitespace, plain string, list[dict] single/multi, empty list, list with empty text, list[str], dict with text, dict without text, any-type-returns-str-or-none, crash reproducer.

**Live verification:**
- `build_missing_and_report` run on `date_from=2026-05-04` triggered after fix;
- Interaction `fc630809` (segments=118, stages=3) — the type that previously triggered the crash — completed LLM + persist without `ProgrammingError`;
- Run continued processing further interactions without error (confirmed in API logs at 08:28–08:29 UTC);
- No `ProgrammingError` appeared in logs after fix was applied.

**Tests:** `pytest tests/test_manual_reporting.py` — 98 passed (14 new + 84 existing).

---

### Manager_daily Content Enrichment — Step 8C Diagnostics Addendum: Unclassified Reason Breakdown

**Дата:** 2026-05-05

**Scope:** only manager_daily payload diagnostics and tests. No changes to analyzer prompts, LLM/STT logic, scoring, eligibility, selection rules, rolling window, coaching_core, Situation Day, Additional Situations, Challenge, Who to work tomorrow, `rop_weekly`, scheduler, or PDF labels.

**Root cause summary:**

The high `НЕ КЛАСС.` count is not a visual renderer bug and not a Step 8B reconciliation bug. It is a coverage gap between the wider report-day `meaningful_calls` layer and ready reusable analysis:
- report-day meaningful includes no-transcript source-side probable live conversations (`answered`, `in/out`, duration >= 90s);
- many of those calls have no reusable transcript and therefore no reusable analysis;
- fresh `build_missing_and_report` tried to fill the gap but STT/LLM-1 calls hit the external `429 insufficient_quota` blocker;
- therefore the list correctly shows meaningful calls, but many of them still have no ready breakdown.

**Payload changes:**
- Added nullable/backward-compatible `payload.unclassified_breakdown`.
- Added `unclassified_reason_code` / `unclassified_reason_label` to `payload.call_list[]` rows where `status is None`.
- Added forensic fields to `ReportArtifact`: `original_analysis` and `analysis_reuse_reason`, so diagnostics can distinguish missing, failed, and non-reusable analyses after `_prepare_artifacts` clears non-ready `analysis`.

Example:

```json
"unclassified_breakdown": {
  "total": 14,
  "by_reason": {
    "no_analysis": 1,
    "no_transcript": 13
  },
  "sample_calls": [
    {
      "time": "04:47",
      "client": "+77476836968",
      "reason_code": "no_analysis",
      "reason_label": "Нет готового анализа"
    }
  ]
}
```

**Reason codes supported:**
`no_transcript`, `no_analysis`, `analysis_failed`, `analysis_not_reusable`, `not_eligible`, `not_coachable_or_reportable`, `no_follow_up_outcome`, `cdr_only_probable_live`, `missing_classification`, `support_or_internal`, `unknown`.

**Fresh verification on 2026-05-04 after build_missing_and_report:**

| Manager | raw | meaningful | analyzed | unclassified | no_transcript | no_analysis | analysis_failed | not_eligible | no_outcome | cdr_only | unknown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| manager 304 pattern (`ext=203`; no local manager row for `304`) | 24 | 6 | 0 | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 |
| Толеген (`ext=325`) | 54 | 6 | 1 | 5 | 5 | 0 | 0 | 0 | 0 | 0 | 0 |
| Тимур (`ext=311`) | 57 | 15 | 1 | 14 | 13 | 1 | 0 | 0 | 0 | 0 | 0 |
| Эльмира (`ext=322`) | 41 | 12 | 0 | 12 | 12 | 0 | 0 | 0 | 0 | 0 | 0 |

Runtime note: extension `304` itself had `raw=0` on 2026-05-04 in the local DB after source discovery. The acceptance pattern `6 meaningful / 6 unclassified` matches extension `203`, which has no mirrored manager row; this mapping should be clarified operationally before naming it manager-facing.

**build_missing verification:**
- `ext=203`: `transcripts_built=0`, `analyses_built=0`, `transcript_build_failed=17`, `analysis_build_failed=1`.
- Толеген: `transcripts_built=0`, `analyses_built=0`, `transcript_build_failed=23`, `analysis_build_failed=4`.
- Тимур: `transcripts_built=0`, `analyses_built=0`, `transcript_build_failed=30`, `analysis_build_failed=6`.
- Эльмира: `transcripts_built=0`, `analyses_built=0`, `transcript_build_failed=25`, `analysis_build_failed=4`.

All four runs returned `partial` because billable STT/LLM-1 attempts failed with `429 insufficient_quota`. No new successful analyses were created in this verification pass. This points to expected low analysis coverage under the current external quota blocker, not to a build_missing logic bug.

**Future task: terminology**

If business review confirms the current words are misleading, rename manager-facing wording in a later step:
- `meaningful_calls` → live conversations / звонки в списке дня;
- `Не классифицировано` → Без разбора / Нет готового разбора.

**Tests:**
- `pytest -q tests/test_manual_reporting.py -k 'unclassified or call_outcomes or call_list or meaningful or selection_model'` — 18 passed.
- `pytest -q tests/test_manual_reporting.py tests/test_ai_provider_routing.py` — 120 passed.
- `node --check scripts/generate_docx_report.js` — passed.

---

### Manager_daily Content Enrichment — Step 8E Closure: Provider Quota Circuit Breaker

**Дата:** 2026-05-05

**Scope:** `build_missing_and_report` provider error handling and operator response only. No changes to analyzer prompts, STT/LLM execution logic, scoring, eligibility, selection model, meaningful/coaching_core rules, Situation Day, Additional Situations, Challenge, Who to work tomorrow, `rop_weekly`, or scheduler.

**Root cause in code:**

`_prepare_artifacts()` in `core/app/agents/calls/reporting.py` caught STT and analysis `ASAError` as ordinary per-item failures and continued the interaction loop. As a result, OpenAI `429 insufficient_quota` became `transcript_build_failed:*` / `analysis_build_failed:*`, while the run still attempted billable provider calls for the remaining missing items.

**Implemented:**

- Added deterministic provider error classifier: `quota_insufficient`, `rate_limited`, `auth_error`, `provider_timeout`, `provider_5xx`, `unknown_provider_error`.
- OpenAI `429 insufficient_quota` maps to `quota_insufficient`.
- Added run-level quota blocker. After the first `quota_insufficient`, the current run stops further billable STT/LLM calls and marks remaining eligible items as `quota_blocked_current_run`.
- Added structured response fields:

```json
{
  "blocker": {
    "type": "quota_blocked",
    "stage": "stt",
    "provider": "openai",
    "account_alias": "stt_main",
    "model": "whisper-1",
    "api_key_env": "OPENAI_API_KEY_STT_MAIN",
    "error_class": "quota_insufficient",
    "message": "Provider returned insufficient_quota. Further billable calls were stopped."
  },
  "processed": {
    "transcripts_built": 0,
    "analyses_built": 0,
    "skipped_due_to_quota": 23,
    "quota_blocked_previous_run": 0
  }
}
```

- Added retry/idempotency guard: `metadata_.last_provider_failure` and bounded `metadata_.provider_failure_history` are saved on quota-blocked interactions.
- A later `build_missing_and_report` skips previously quota-blocked calls as `quota_blocked_previous_run` unless the operator explicitly passes `force_retry_quota_blocked=true`.
- CLI operator override added: `--force-retry-quota-blocked`.
- API request override added: `force_retry_quota_blocked`.

**Provider/account visibility:**

- STT visibility: `stage=stt`, `provider=openai`, `account_alias=stt_main`, `api_key_env=OPENAI_API_KEY_STT_MAIN`, `model=whisper-1`.
- LLM-1 visibility: `stage=llm1`, `provider=openai`, `account_alias=llm1_main`, `api_key_env=OPENAI_API_KEY_LLM1_MAIN`, configured model from AI routing.
- Secret values/API keys are not included in the blocker, observability, or tests.

**Runtime behavior:**

- STT quota: first `quota_insufficient` records blocker and stops further STT/LLM billing in the run.
- LLM quota: transcript remains saved/reused; first `quota_insufficient` records blocker and stops further analysis billing in the run.
- Non-quota transient errors do not trip the quota circuit breaker and keep existing retry/failure behavior.
- Run status remains non-success when build errors/blocker exist (`partial` when a report artifact is still produced, otherwise `blocked`).

**Tests:**

- `pytest -q tests/test_manual_reporting.py -k 'quota or unclassified or call_outcomes or call_list or meaningful or selection_model'` — 18 passed.
- `pytest -q tests/test_manual_reporting.py tests/test_ai_provider_routing.py` — 120 passed.
- `node --check scripts/generate_docx_report.js` — passed.

**Recommendation after fix:**

Do not restart a mass `build_missing_and_report` immediately. After quota is replenished, run a controlled smoke on one manager and one or two calls first. Use normal mode to confirm the guard no longer repeats previously blocked calls automatically; use `force_retry_quota_blocked=true` only for explicitly selected calls once the operator confirms quota is available.

---

### Manager_daily Content Enrichment — Step 8G Closure: Split Unclassified Manager-Facing Statuses

**Дата:** 2026-05-05

**Scope:** manager_daily payload/render taxonomy only. No analyzer prompts, STT/LLM, scoring, eligibility, selection model, rolling window, coaching_core, Situation Day, Additional Situations, Challenge, Who to work tomorrow, `rop_weekly`, or scheduler changes.

**What changed:**
- Internal `status` taxonomy remains unchanged: calls without ready outcome still keep `status=None`.
- `call_list[]` rows with `status=None` now carry manager-facing bucket fields:
  - `unclassified_status_label`
  - `unclassified_context_label`
- `call_outcomes_summary` now includes `unclassified_by_bucket` while preserving `unclassified_count`.
- PDF/render model replaces the old `НЕ КЛАСС.` column label with `БЕЗ РАЗБОРА` and adds a compact breakdown note under the day summary, for example: `Без разбора: 5 без транскрипта, 2 не подходят для разбора, 1 без анализа.`
- `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ` shows concrete statuses such as `Без транскрипта`, `Без анализа`, `Не подходит для разбора`, `Ошибка анализа`, `Нет итога`, `Нет классификации`, instead of one generic `Не классифицировано`.

**Manager-facing mapping:**

| Internal reason | Manager-facing status |
|---|---|
| `no_transcript` | `Без транскрипта` |
| `cdr_only_probable_live` | `Без транскрипта` |
| `no_analysis` | `Без анализа` |
| `analysis_failed` | `Ошибка анализа` |
| `analysis_not_reusable` | `Не подходит для разбора` |
| `not_coachable_or_reportable` | `Не подходит для разбора` |
| `not_eligible` | `Не подходит для разбора` |
| `no_follow_up_outcome` | `Нет итога` |
| `missing_classification` | `Нет классификации` |
| `unknown` | `Без разбора` |

**Money block:** `ДЕНЬГИ НА СТОЛЕ` remains limited to actionable outcomes (`Договорённость`, `Открыт`, `Перенос`). Non-actionable buckets (`Без транскрипта`, `Без анализа`, `Не подходит для разбора`, `Ошибка анализа`) are excluded from potential-money calculations.

**Ready-only verification on controlled 2026-05-04 cases:**

| Manager | meaningful | normal outcomes | без транскрипта | без анализа | не подходит для разбора | ошибка анализа | other | sum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Толеген | 6 | 4 | 1 | 1 | 0 | 0 | 0 | 6 |
| Тимур | 15 | 5 | 6 | 0 | 0 | 4 | 0 | 15 |
| Эльмира | 12 | 3 | 5 | 0 | 0 | 4 | 0 | 12 |

Artifacts generated locally without delivery:
- `/tmp/step8g_Толеген_2026-05-04.pdf`
- `/tmp/step8g_Тимур_2026-05-04.pdf`
- `/tmp/step8g_Эльмира_2026-05-04.pdf`

**Tests:**
- `docker compose exec -T api pytest -q tests/test_manual_reporting.py -k 'unclassified or call_outcomes or call_list or meaningful or selection_model or money'` — 18 passed.
- `docker compose exec -T api pytest -q tests/test_manual_reporting.py tests/test_ai_provider_routing.py` — 120 passed.
- `node --check scripts/generate_docx_report.js` — passed.

---

### Manager_daily Content Enrichment — Step 8I Closure: Manager-Facing Completeness Gate

**Дата:** 2026-05-05

**Scope:** manager_daily payload/delivery readiness gate and failed-analysis bucket classification only. No analyzer prompts, STT/LLM, scoring, eligibility, selection model, rolling window, coaching_core, Situation Day, Additional Situations, Challenge, Who to work tomorrow, `rop_weekly`, or scheduler changes.

**What changed:**
- Added nullable/backward-compatible `payload.manager_facing_completeness`.
- Ordinary manager-facing delivery is allowed only when report-day `call_list[]` has no blocking buckets:
  - `Без транскрипта`
  - `Без анализа`
  - technical `Ошибка анализа`
  - `Ошибка провайдера`
- If the gate fails, report result status becomes `review_required`, reason `incomplete_day_call_processing`, business email is disabled, and the payload contains counts plus affected calls with required operator action.
- Operator/test Telegram delivery may still be used as preview, but the payload header is marked `OPERATOR PREVIEW / INCOMPLETE`.

**Updated bucket classifier:**

| Persisted/internal signal | Bucket |
|---|---|
| `semantic_empty`, `not_coachable_or_reportable`, `not_coachable`, `not_reportable` | `Не подходит для разбора` |
| contract / parser / schema / validation / `Criterion ... missing required fields` | `Ошибка анализа` |
| provider / quota / 429 / rate-limit / timeout / auth / 5xx | `Ошибка провайдера` |
| failed analysis with unknown technical cause | `Ошибка анализа` |

**Ready-only verification on current controlled 2026-05-04 state:**

| Manager | meaningful | normal outcomes | без транскрипта | без анализа | не подходит для разбора | ошибка анализа | ошибка провайдера | Gate result |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Эльмира | 12 | 3 | 4 | 0 | 5 | 0 | 0 | `review_required` |
| Тимур | 15 | 6 | 5 | 0 | 4 | 0 | 0 | `review_required` |
| Толеген | 6 | 4 | 0 | 1 | 1 | 0 | 0 | `review_required` |

**Tests:**
- `docker compose exec -T api pytest -q tests/test_manual_reporting.py -k 'unclassified or call_outcomes or call_list or meaningful or selection_model or completeness or delivery'` — 22 passed.

---

### Manager_daily Content Enrichment — Step 8J Closure: Controlled Completeness Build

**Дата:** 2026-05-05

**Scope:** runtime controlled build/verification only. No code, prompt, STT/LLM, scoring, eligibility, selection model, rolling window, renderer, `rop_weekly`, scheduler, or delivery semantics changes.

**Execution mode:**
- Used an internal CLI verification path in the `api` container.
- Called `_prepare_artifacts(..., mode="build_missing_and_report")` only for exact selected `interaction_id` batches.
- Did not invoke report runner delivery; business email and Telegram delivery were not sent.

**Result:**

| Manager | Before gate | Batch selected | Built transcripts | Built analyses | After gate | Main blocker |
|---|---|---:|---:|---:|---|---|
| Эльмира | `review_required` (`Без транскрипта=4`) | 4 | 0 | 0 | `review_required` | OnlinePBX audio download 404 |
| Тимур | `review_required` (`Без транскрипта=5`) | 5 | 0 | 0 | `review_required` | OnlinePBX audio download 404 |
| Толеген | `review_required` (`Без анализа=1`) | 1 | 0 reused | 1 | `passed` | closed |

**Findings:**
- Quota remained stable: no `429`, no `quota_blocked`, no `skipped_due_to_quota`.
- Эльмира/Тимур no-transcript calls had `raw_ref`, but all selected audio downloads failed before STT with `404` from OnlinePBX recording download URLs.
- Толеген's remaining `Без анализа` call built reusable analysis and moved to `tech_service`, so manager-facing completeness gate passed for Толеген.
- `call_list_dates=["2026-05-04"]` for all verified managers; rolling-window calls did not enter the report-day call list.

**Follow-up task:**
- Add a bounded source-audio availability/retention recovery decision before expecting remaining `Без транскрипта` calls to close:
  - refresh/re-resolve expired OnlinePBX recording URLs if possible;
  - or persist a technical source-audio-unavailable marker;
  - or define an operator-facing unrecoverable bucket that still blocks business-ready delivery until reviewed.

---

### Manager_daily Content Enrichment — Step 8K Closure: Source Audio 404 Recovery Audit

**Дата:** 2026-05-05

**Scope:** forensic/read-only source-audio audit and one audio-only probe. No Step 8I gate changes, no analyzer/STT/LLM/scoring/eligibility/selection/rolling/renderer/delivery/`rop_weekly`/scheduler changes.

**Root cause classification:** `expired URL`.

Evidence:
- The 9 remaining Эльмира/Тимур `Без транскрипта` calls have persisted `raw_ref`, but `raw_ref` is a direct OnlinePBX `api2.onlinepbx.ru/calls-records/download/.../rec.mp3` URL.
- Old URL probes returned HTTP `404` with body `KEY_IS_EXPIRED`.
- Each row still has canonical OnlinePBX uuid in `interactions.external_id` and `metadata.external_call_code`.
- `get_cdr_list("2026-05-04")` still finds all 9 calls by uuid.
- Current CDR records do not include `record_url`, but `get_recording_url(uuid)` successfully returns a fresh download URL for all 9 calls.
- One-call audio-only probe on `98aa9872-5406-4eef-9c0b-30f44175b3a9` downloaded a fresh `audio/mpeg` MP3 (`368208` bytes), then deleted the temp file; no STT/LLM or DB mutation was performed.

**Code-path finding:**
- Persisted `raw_ref` is an expiring direct URL.
- Canonical OnlinePBX uuid is preserved separately.
- `_prepare_artifacts()` uses `interaction.raw_ref` as-is and does not refresh expired URLs before `CallsExtractor.download_and_extract()`.
- Full source-aware report-run can re-resolve recording URLs during source discovery for targeted records, but exact-ID controlled build bypassed that prelude.

**Next bounded implementation task:**
- Add `source_audio_url_refresh` before transcript build for OnlinePBX calls:
  - when `raw_ref` is missing or known-expired, use `interaction.external_id` / `metadata.external_call_code` with `OnlinePBXIntake.get_recording_url(uuid)`;
  - update only selected interactions in bounded mode;
  - after refresh, run a 1-call controlled build first;
  - if lookup fails, return/persist operator-facing `source_audio_unavailable` diagnostic and keep manager-facing completeness gate blocking until operator review.

---

### Manager_daily Content Enrichment — Step 8L Closure: Bounded Source Audio URL Refresh

**Дата:** 2026-05-05

**Scope:** implementation inside controlled `manager_daily` build_missing path. No Step 8I gate changes, no analyzer prompt/STT/LLM provider/scoring/eligibility/selection/rolling/renderer/delivery/`rop_weekly`/scheduler changes.

**Implemented:**
- `_prepare_artifacts()` refreshes a selected OnlinePBX audio URL before billable STT when the interaction has no transcript and is source-build-eligible.
- Canonical OnlinePBX uuid resolution order: `interaction.external_id`, then `interaction.metadata_.external_call_code`.
- Successful refresh persists fresh `interaction.raw_ref`, writes `metadata.source_audio_url_refresh`, and clears stale source-audio download errors.
- Failed refresh writes operator-facing `metadata.source_audio_unavailable` / `last_audio_source_failure`, returns `source_audio_unavailable:<interaction_id>:<reason>`, skips STT, and leaves the existing completeness gate blocking through `Без транскрипта`.
- `_is_interaction_source_build_eligible()` now allows recoverable OnlinePBX rows with canonical uuid even when direct `raw_ref` is missing.

**1-call verification:**
- Target: Эльмира, ext `322`, `2026-05-04T05:09`, interaction `fba9e2df-5e69-4da5-ae2b-e3f17362c6e0`, OnlinePBX uuid `98aa9872-5406-4eef-9c0b-30f44175b3a9`, duration `156`.
- Execution: internal `_prepare_artifacts()` on the exact interaction only; no report rendering, no business email, no Telegram delivery.
- Result: refresh succeeded, audio downloaded, transcript built (`transcripts_built=1`), analysis attempt persisted `not_coachable_or_reportable` failed analysis (`7273f82e-c392-4d13-b524-6eaa34d05e0a`), final bucket changed from `Без транскрипта` to `Не подходит для разбора`.
- Gate impact: Эльмира remains `review_required`, but `Без транскрипта` improved `4 -> 3`.

**Next controlled task:**
- Process the remaining 8 recoverable source-audio calls in small exact-ID/duration batches (Эльмира 3, Тимур 5).
- Do not run a mass `build_missing_and_report`; keep delivery path isolated until Telegram/no-delivery semantics are fixed separately.

---

### Manager_daily Content Enrichment — Step 8M Closure: Controlled Source-Audio Recovery Build

**Дата:** 2026-05-05

**Scope:** operational exact-ID build for the remaining recoverable source-audio calls. No code changes; no full report runner, rendering, business email, or Telegram delivery.

**Result:**
- All 8 remaining source-audio calls refreshed successfully through Step 8L and built transcripts.
- `source_audio_unavailable=0`, `quota_blocker=null`, `skipped_due_to_quota=0`.
- Эльмира: 3/3 calls moved from `Без транскрипта` to `Не подходит для разбора`; final gate `passed`.
- Тимур: 5/5 calls moved out of `Без транскрипта`; 3 calls moved to `Не подходит для разбора`, 2 calls remain blocking `Без анализа` after LLM contract validation errors did not persist a failed analysis row.

**Final 2026-05-04 manager-facing completeness snapshot:**
- Эльмира: normal `3`, `Не подходит для разбора=9`, blocking buckets all `0`, gate `passed`.
- Тимур: normal `6`, `Не подходит для разбора=7`, `Без анализа=2`, `Без транскрипта=0`, gate `review_required`.
- `call_list_dates=["2026-05-04"]` for both managers; rolling-window calls did not enter the report-day call list.

**Follow-up:**
- No new source-audio recovery follow-up is needed for these 8 calls.
- Step 8N follow-up opened for analysis contract-validation failures: ensure contract/parser validation errors either persist a technical failed analysis (`analysis_failed_contract` / `Ошибка анализа`) or provide an explicit operator retry path, so they do not remain an unexplained `Без анализа`.
- Delivery semantics (`--no-delivery` vs Telegram test delivery) remains a separate known follow-up.

---

### Manager_daily Content Enrichment — Step 8N Closure: Persist / Surface Analysis Contract-Validation Failures

**Дата:** 2026-05-05

**Scope:** bounded technical failure persistence in the existing analysis build path. No Step 8I gate changes, no Step 8L source-audio changes, no analyzer prompt/STT/LLM provider/scoring/eligibility/selection/rolling/renderer/`rop_weekly`/scheduler/delivery changes.

**Implemented:**
- `_prepare_artifacts(..., mode="build_missing_and_report")` now handles analyzer `LLMResponseError` separately from provider/runtime `ASAError`.
- Contract/parser/schema validation failures are persisted through `persist_failed_analysis(..., fail_reason="analysis_failed_contract:<error>")`.
- Persisted contract failures remain non-reusable for coaching and are classified by the existing Step 8I bucket logic as `Ошибка анализа`, not `Не подходит для разбора` and not unexplained `Без анализа`.
- The manual live persistence helper now accepts `LLMResponseError` failed attempts as well as `SemanticAnalysisError`.

**Controlled rebuild result for Тимур blockers:**
- Selected exact IDs only:
  - `ec9cfc47-4a0e-4a4d-95f9-781286f0f2b7` (`09:19`, `+77072801616`)
  - `489676d0-0fc8-4457-819d-9167de42425b` (`09:22`, `+77768305005`)
- Full report runner/render/delivery was not called; business email and Telegram were not sent.
- Both calls reused existing transcripts and refreshed audio; `transcripts_built=0`, `transcripts_reused=2`.
- Both calls attempted analysis and persisted failed analyses after retry as `not_coachable_or_reportable`; `analysis_build_failed=2`, `analyses_built=0`, `quota_blocker=null`, `skipped_due_to_quota=0`.
- This followed the acceptable Step 8N outcome: the calls no longer remain unexplained `Без анализа`; they resolved to allowed `Не подходит для разбора`.

**Final Тимур 2026-05-04 ready-only snapshot:**
- normal/non-blocking `6`
- `Не подходит для разбора=9`
- `Без транскрипта=0`
- `Без анализа=0`
- `Ошибка анализа=0`
- `Ошибка провайдера=0`
- gate `passed`
- `call_list_dates=["2026-05-04"]`

**Follow-up:**
- Step 8M contract-validation persistence follow-up is closed.
- No new analysis-contract follow-up is needed from this controlled rebuild.
- Delivery semantics (`--no-delivery` vs Telegram test delivery) remains a separate known follow-up.

---

### Manager_daily Content Enrichment — Step 8P Closure: Safe Delivery Semantics + Telegram Test Send

**Дата:** 2026-05-05

**Scope:** bounded delivery-semantics hardening for ordinary `manager_daily` report path plus test Telegram delivery of the already verified Step 8O PDFs. No analyzer prompt/STT/LLM/build/scoring/eligibility/selection/rolling-window/report-content/`rop_weekly`/scheduler changes.

**Implemented delivery matrix:**
- `preview_only` / `--no-delivery`: no Telegram, no business email, artifact/render allowed.
- `telegram_test_only`: Telegram test delivery only.
- `business_email_only`: business email only.
- `telegram_and_email`: both explicitly enabled channels.

**Safety rules:**
- `send_email=false` no longer enables Telegram by side effect.
- Telegram test delivery requires explicit flag/mode.
- Business email requires explicit flag/mode.
- Incomplete / `review_required` `manager_daily` keeps business email forced off; Telegram operator preview is allowed only when explicitly enabled.

**Result:**
- Delivery semantics follow-up from Step 8M/8N/8O is closed.
- Step 8O PDFs for Эльмира, Тимур, and Толеген (`2026-05-04`) were sent to the configured test/operator Telegram chat.
- Business email was not sent; `build_missing`, STT, and LLM were not run.

---

### Manager_daily Content Enrichment — Step 8Q/8R Closure: Report-Day Business Outcome Resolver

**Дата:** 2026-05-06

**Scope:** bounded audit and implementation for `manager_daily` report-day call-list outcomes only. Acceptance/verification used only `payload.call_list[]` / `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ` with `call_list_dates=["2026-05-04"]` for Эльмира, Тимур, and Толеген. Rolling-window calls, coaching_core calls outside report-day call list, historical calls, weekly data, and `rop_weekly` were not used for outcome acceptance.

**Step 8Q audit result:**

| Manager | Report-day calls checked | Current `Не подходит для разбора` | Confirmed correct | Questionable | Likely refusal | Likely tech/service | Likely open/follow-up |
|---|---:|---:|---:|---:|---:|---:|---:|
| Эльмира | 12 | 9 | 1 | 0 | 1 | 4 | 3 |
| Тимур | 15 | 9 | 1 | 1 | 1 | 1 | 5 |
| Толеген | 6 | 1 | 0 | 0 | 0 | 0 | 1 |

**Implemented:**
- `core/app/agents/calls/reporting.py` now has `BusinessOutcomeResolver`.
- `_build_daily_call_row()` uses the resolver to populate final `status`, unclassified bucket, and diagnostic evidence fields.
- `_build_call_outcomes_summary()` now derives from `BusinessOutcomeResolver` output.

**Standing priority order:**
1. technical blockers: no transcript, no analysis, contract/parser/schema analysis error, provider error;
2. `Тех/сервис`;
3. explicit `Отказ`;
4. true commercial `Договорённость`;
5. `Перенос`;
6. `Открыт`;
7. `Не подходит для разбора` only for truly semantic-empty / no business signal.

**Behavior change:**
- `not_coachable_or_reportable` no longer maps directly to `Не подходит для разбора`.
- Resolver first checks persisted transcript/analysis/follow-up/fail reason for business outcome.
- If business outcome exists, manager-facing category becomes `Тех/сервис`, `Отказ`, `Договорённость`, `Перенос`, or `Открыт`.
- If no business signal exists, the call remains `Не подходит для разбора`.
- `duration_below_threshold` / coaching non-eligibility does not automatically beat business outcome in `payload.call_list[]`.

**Ready-only verification for `2026-05-04`:**

| Manager | Meaningful | Договорённость | Перенос | Отказ | Открыт | Тех/сервис | Не подходит для разбора | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Эльмира | 12 | 1 | 1 | 2 | 2 | 6 | 0 | passed |
| Тимур | 15 | 3 | 1 | 2 | 6 | 2 | 1 | passed |
| Толеген | 6 | 0 | 0 | 1 | 3 | 2 | 0 | passed |

**Suspicious-call regression after Step 8R:**
- Эльмира: `3337ccea-9a3b-477f-a806-9b30580f22d7 -> Тех/сервис`; `84d678b1-2af2-45e9-928a-a9e5fbd6b075 -> Открыт`; `a7db44c0-ffe1-4e35-b354-e14dc5cabe10 -> Отказ`; `fbe3a0e8-1749-4cab-9d7b-07b1edc34231 -> Отказ`; `577222e5-c8aa-4704-bdb4-c5be21335d4e -> Тех/сервис`; `efd7037a-95c4-4fe4-a667-7e55992807e0 -> Перенос`; `85427168-a321-441e-ac03-f501149057b4 -> Договорённость`.
- Тимур: `697e2efc-f4b7-4108-85f8-b3359f2fe050 -> Не подходит для разбора`; `79ebbb9b-4326-41c0-96bd-3dea7de2e453 -> Отказ`; `e4022d06-5e4b-4b08-8912-5b2abac7957d -> Отказ`; `41822044-3a3b-4df3-ace2-eabd33138c07 -> Открыт`; `4147eac0-6ae9-4248-9dcd-434a8d5b2a82 -> Тех/сервис`; `3d7f0ba0-2c88-482f-89b7-283b67a76fad -> Договорённость`; `489676d0-0fc8-4457-819d-9167de42425b -> Открыт`.
- Толеген: `cc115847-cc05-4666-a03d-4e67d8db22c3 -> Открыт`; `9d83c5e3-ea90-436a-9e47-c20a2ae0fb34 -> Отказ`.

**Explicit non-actions:** no `build_missing`, no STT, no LLM, no delivery, no analyzer prompt/scoring/eligibility/selection/rolling-window/Step 8I/Step 8L/Step 8N/Step 8P/PDF-layout changes.

**Checks:** `python3 -m py_compile core/app/agents/calls/reporting.py`; `docker compose exec -T api pytest -q tests/test_manual_reporting.py -k 'outcome or refusal or unclassified or call_outcomes or call_list or meaningful or completeness'` (`13 passed`); `docker compose exec -T api pytest -q tests/test_manual_reporting.py tests/test_ai_provider_routing.py` (`132 passed`); `node --check scripts/generate_docx_report.js`; `git diff --check`.

---

### Manager_daily Content Enrichment — Step 8T Audit Closure + Step 8U Follow-up

**Дата:** 2026-05-06

**Scope:** audit-only consistency check after Step 8R resolver and Step 8S PDF regeneration. Inputs were only Step 8S PDFs and report-day `2026-05-04` payload/code inspection. No `build_missing`, STT, LLM, delivery, prompt, scoring, eligibility, selection, rolling-window, renderer, or resolver implementation changes.

**Consistency summary:**

| Manager | Итог дня ok | Деньги на столе ok | Кого взять завтра ok | Call list ok | Issues |
|---|---|---|---|---|---:|
| Эльмира | yes | yes | no | yes | 3 |
| Тимур | yes | yes | no | yes | 3 |
| Толеген | yes | yes | no | yes | 5 |

**Confirmed source alignment:**
- `ИТОГ ДНЯ` uses `payload.call_outcomes_summary`, now derived from `BusinessOutcomeResolver`.
- `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ` uses `_build_daily_call_row()` and final resolver status.
- `ДЕНЬГИ НА СТОЛЕ` uses the same `call_outcomes_summary`; it excludes `Отказ`, `Тех/сервис`, and `Не подходит`.
- Current money rule intentionally counts `Договорённость + Открыт + Перенос`. If business wants `Перенос` excluded or separated, that is a business-rule change, not a Step 8T consistency bug.

**Inconsistencies found:**

| Manager | call/time/client | call list status | other block | conflict | recommended fix |
|---|---|---|---|---|---|
| Эльмира | `06:28` / `+77012172463` | `Открыт` | `КОГО ВЗЯТЬ` | shown as hot `Договорённость` | build tomorrow list from final call-list status; show as `Открытый` |
| Эльмира | `12:05` / `Акмарал` | `Тех/сервис` | `КОГО ВЗЯТЬ` | shown as hot `Договорённость` | exclude `Тех/сервис` from tomorrow actions |
| Эльмира | `10:14` / `Агирим` | `Отказ` | `КОГО ВЗЯТЬ` | shown as open follow-up | exclude `Отказ` from tomorrow actions |
| Тимур | `12:09` / `+77470957591` | `Открыт` | `КОГО ВЗЯТЬ` | shown as hot `Договорённость` | show as `Открытый`, not hot agreement |
| Тимур | `09:26` / `+77751231100` | `Открыт` | `КОГО ВЗЯТЬ` | shown as hot `Договорённость` | show as `Открытый`, not hot agreement |
| Тимур | `04:47` / `Надежда Анатольевна` | `Отказ` | `КОГО ВЗЯТЬ` | shown as open follow-up | exclude `Отказ` from tomorrow actions |
| Толеген | `11:52` / `+77020472248` | `Тех/сервис` | `КОГО ВЗЯТЬ` | shown as hot `Договорённость` | exclude `Тех/сервис` from tomorrow actions |
| Толеген | `06:37` / `+77774745093` | `Открыт` | `КОГО ВЗЯТЬ` | shown as hot `Договорённость` | show as `Открытый`, not hot agreement |
| Толеген | `11:46` / `Нур-Султан` | `Открыт` | `КОГО ВЗЯТЬ` | shown as hot `Договорённость` | show as `Открытый`, not hot agreement |
| Толеген | `11:36` / `Флора` | `Отказ` | `КОГО ВЗЯТЬ` | shown as hot `Договорённость` | exclude `Отказ` from tomorrow actions |
| Толеген | `11:52` / `+77020472248` | `Тех/сервис` | `РАЗБОР ЗВОНКА` | coaching example selected from service outcome | filter coaching examples by final business outcome or mark service examples separately |

**Root cause:**
- `_build_call_tomorrow()` still runs on `coaching_core` artifacts and calls legacy `_derive_call_status_and_deadline(follow_up)`.
- It does not read final `BusinessOutcomeResolver` status from `payload.call_list[]`.
- Coaching blocks still use `coaching_core` and do not know final business outcome; a reusable/eligible analysis can still become a final `Тех/сервис` or `Отказ` after Step 8R.

**Step 8U follow-up:**
- Align `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` with final business outcome source:
  - build from `payload.call_list[]` / resolver status, not raw follow-up status;
  - include only final `Перенос`, `Договорённость`, `Открыт`;
  - exclude final `Отказ`, `Тех/сервис`, and unclassified rows;
  - preserve `deadline`, `next_step`, and `reason`, but derive priority label from final status.
- Add deterministic tests for the Step 8T cases above.
- Decide whether coaching examples should exclude report-day final `Тех/сервис` / `Отказ`, or explicitly label them as non-sales coaching examples. Recommended default: exclude them from `РАЗБОР ЗВОНКА`, `СИТУАЦИЯ ДНЯ`, and `ЧЕЛЛЕНДЖ` candidate examples when enough final sales-like calls remain.
- Keep `ДЕНЬГИ НА СТОЛЕ` unchanged unless business explicitly changes the rule for `Перенос`.

---

### Manager_daily Content Enrichment — Step 8U Closure: Post-Summary Blocks Use Final Business Outcome

**Дата:** 2026-05-06

**Scope:** bounded implementation for report payload assembly / post-summary `manager_daily` blocks only. No `build_missing`, STT, LLM, analyzer prompt, scoring, eligibility, selection model, rolling window, Step 8I/8L/8N/8P/8R, delivery semantics, or money-rule changes.

**Implemented:**
- `payload.call_list[]` rows now carry `interaction_id` so post-summary blocks can join against final report-day outcomes.
- `_build_call_tomorrow()` now builds from final `payload.call_list[]` / `BusinessOutcomeResolver` status, not legacy raw `follow_up` over `coaching_core`.
- Tomorrow actions include only final `agreed`, `rescheduled`, `open`.
- Tomorrow actions exclude final `refusal`, `tech_service`, `Не подходит для разбора`, `Без транскрипта`, `Без анализа`, `Ошибка анализа`, `Ошибка провайдера`.
- Priority labels are derived from final status:
  - `agreed -> Горячий`;
  - `rescheduled -> Перенос`;
  - `open -> Открытый`.
- Empty state is explicit and non-fabricating: `Нет коммерческих звонков для работы завтра по итогам отчётного дня.`
- Normal coaching candidate pool for `РАЗБОР ЗВОНКА` / `СИТУАЦИЯ ДНЯ` / `ЧЕЛЛЕНДЖ` excludes report-day final `refusal`, `tech_service`, and unclassified technical buckets when at least one report-day sales-like candidate exists. If no sales-like candidates exist, previous sparse fallback behavior is preserved.

**Ready-only verification for `2026-05-04`:**

| Manager | Tomorrow items | Excluded refusals | Excluded tech/service | Open shown as open | Conflicts remaining |
|---|---:|---:|---:|---|---:|
| Эльмира | 4 | 2/2 | 6/6 | yes | 0 |
| Тимур | 5 | 2/2 | 2/2 | yes | 0 |
| Толеген | 3 | 1/1 | 2/2 | yes | 0 |

**Step 8T conflict closure:**
- Эльмира `06:28 +77012172463` is rendered as `🔵 Открытый`, not hot agreement.
- Эльмира `12:05 Акмарал` final `Тех/сервис` is excluded from tomorrow.
- Эльмира `10:14 Агирим` final `Отказ` is excluded from tomorrow.
- Тимур `12:09 +77470957591` and `09:26 +77751231100` are no longer rendered as hot agreements.
- Тимур `04:47 Надежда Анатольевна` final `Отказ` is excluded from tomorrow.
- Толеген `11:52 +77020472248` final `Тех/сервис` is excluded from tomorrow and is not selected as normal `РАЗБОР ЗВОНКА` while sales-like candidates exist.
- Толеген `06:37 +77774745093` and `11:46 Нур-Султан` are rendered as `🔵 Открытый`.
- Толеген `11:36 Флора` final `Отказ` is excluded from tomorrow.

**Verification facts:**
- `call_list_dates=["2026-05-04"]` for all three managers.
- Rolling-window calls did not enter the report-day call list.
- `manager_facing_completeness.status=passed`.
- Delivery was not run.
- `build_missing`, STT and LLM were not run.

**Checks:** `python3 -m py_compile core/app/agents/calls/reporting.py`; `docker compose exec -T api pytest -q tests/test_manual_reporting.py -k 'step8u or tomorrow or outcome or refusal or call_list or call_outcomes or meaningful or completeness'` (`15 passed`); full checks were run as part of Step 8U close-out.

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

## Step 8AH-1 — Unified client/call references

**Status:** DONE 2026-05-08.

**Scope:** reporting payload / render display layer only for `manager_daily`. No STT, source discovery, `build_missing`, LLM/re-analysis, prompt changes, `report_evidence` contract changes, `BusinessOutcomeResolver` changes, delivery semantics changes, or radical call-list layout redesign.

**Implemented display contract:**

```text
имя / ФИО / persisted label · телефон · дата, время
```

Fallbacks:
- no name/label: `телефон · дата, время`;
- no phone: `имя · дата, время`;
- same phone in label and phone is rendered once;
- no invented names.

**Applied to blocks:**
- `СИТУАЦИЯ ДНЯ`;
- `РАЗБОР ЗВОНКА`;
- `ГОЛОС КЛИЕНТА`;
- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`;
- `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ` client column.

**Ready-only verification:** `/tmp/step8ah1_Эльмира_2026-05-04.pdf`, `/tmp/step8ah1_Тимур_2026-05-04.pdf`, `/tmp/step8ah1_Толеген_2026-05-04.pdf`, summary `/tmp/step8ah1_summary_2026-05-04.json`. All three kept `call_list_dates=["2026-05-04"]`, rolling-window calls absent from call list, `manager_facing_completeness.status=passed`, delivery skipped/disabled, and Step 8AG outcome totals unchanged.

**Follow-up for Step 8AH-2:** call-list structure/width can be polished separately, including potential regrouping of `Время` + `Клиент` if human review finds the unified label too wide in dense PDFs. Step 8AH-1 intentionally did not redesign table columns.

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
