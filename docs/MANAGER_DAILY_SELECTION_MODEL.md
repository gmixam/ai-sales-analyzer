# Manager Daily — Selection Model & Report Contract

## Назначение

Этот документ фиксирует canonical selection model и report contract для `manager_daily`.
Он является source of truth для bounded implementation tasks по этой теме.

**Первичная фиксация:** 2026-04-30.
**Implementation update:** 2026-05-08 — Step 8R добавил reporting-layer `BusinessOutcomeResolver` для финальных outcome-категорий report-day `meaningful_calls`; Step 8U выровнял post-summary blocks (`КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, normal coaching examples) с финальным outcome source; Step 8W сделал `СИТУАЦИЯ ДНЯ` evidence-based через persisted evidence/transcript fallback выбранного sales-like `РАЗБОР ЗВОНКА`; Step 8Y зафиксировал целевой additive `LLM2 -> report_evidence -> reporting layer` contract in `docs/REPORT_EVIDENCE_CONTRACT.md`; Step 8AD подключил valid `report_evidence` как preferred evidence/candidate source with Step 8W fallback, without replacing `BusinessOutcomeResolver` final authority; Step 8AF добавил quality guard for legacy fallback so IVR/greeting-only fragments are not used as proof when better sales-like evidence exists; Step 8AH-1 зафиксировал единый display contract for client/call references across manager_daily blocks; Step 8AH-2 зафиксировал human-readable table layout contract and status-order call-list sorting; Step 8AH-7 подключил valid `report_evidence.call_report_summary` для call-list topic/context, tomorrow text enrichment, and voice-of-customer manager action with guarded fallback; Step 8-STABLE зафиксировал stable analysis selection so normal `manager_daily` prefers reusable production/stable rows and excludes controlled sample / verification analyses unless explicitly opted in; Step 8AH-8C усилил `СИТУАЦИЯ ДНЯ`, чтобы client-reaction conclusions prefer persisted client-grounded evidence over manager-only fragments when such evidence exists; Step 8AH-8D усилил `ГОЛОС КЛИЕНТА`, чтобы manager action was signal-specific rather than generic; Step 8AH-8E усилил `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, чтобы context/recommendation/opening phrase came from one signal-specific follow-up profile; Step 8AH-11A добавил `data_scope` для coaching-блоков, чтобы expanded/rolling evidence не рендерился как plain report-day; Step 8AH-11B добавил `daily_coaching_focus` как единый source for focus stage across main coaching blocks; Step 8AH-11C добавил downstream problem-statement normalization so positive/neutral LLM2 or fallback wording is not rendered as a manager-facing problem; Step 8AH-11D добавил quality gate for Additional Situations so generic/contextless cards are hidden and valid cards use evidence/context-backed, stage-specific wording; Step 8AH-11E добавил quality gate for call-list context so weak, truncated, technical, or empty contexts are replaced by human-readable deterministic fallbacks without changing report-day semantics.

---

## A. Problem Statement

### Текущая проблема

`manager_daily` сейчас слишком рано сжимает день до узкого аналитического ядра.

В результате:
- менеджер в финальном отчёте видит только `coaching_core` subset — малую часть дня;
- список звонков дня фактически совпадает с coaching core, а не отражает весь содержательный рабочий день;
- оперативный слой (все звонки дня) и коучинговый слой (узкое ядро для deep review) не разведены;
- счётчики в service note не дают полного представления о воронке отбора;
- менеджер может ошибочно считать, что в отчёте пропущены его звонки.

### Требуемое разграничение

Необходимо явно развести два слоя:
- **оперативный слой дня** — всё, что произошло за день в содержательном смысле;
- **коучинговый слой** — узкое ядро для deep review, coaching-блоков и аналитики.

Отчёт должен отражать оба слоя с явным указанием, что принадлежит каждому.

---

## B. Data Layers Model

### Слой 1: `raw_calls`

**Назначение:** полный операционный лог дня из телефонии.

**Критерии включения:** все CDR-записи из OnlinePBX за выбранный период/день.

**Критерии исключения:** нет (это полный источник).

**Примеры:**
| Класс звонка | Пример |
|---|---|
| beep / no speech / IVR | автодозвон без ответа, IVR-меню без живого разговора |
| support / internal / service | техподдержка, внутренние переговоры |
| sales / follow-up | полноценный звонок клиенту, перезвон по договорённости |
| coaching-worthy sales call | sales звонок с выявлением потребностей, работой с возражениями |

---

### Слой 2: `meaningful_calls`

**Назначение:** содержательные разговоры дня — то, что реально произошло в рабочем общении с клиентами.

**Критерии включения:**
- реальный голосовой контакт с живым собеседником;
- наличие распознаваемого speech-контента (не пустой трафик);
- для CDR-only / no-transcript звонков — достаточный source-side сигнал живого разговора: `source_status=answered`, `direction in/out`, `duration >= 90`.

**Transcript-first rule:** если у звонка есть непустой transcript, он считается `meaningful_calls` независимо от того, является ли он sales/follow-up/support/internal. Support/internal с transcript остаётся meaningful, но не становится coaching_core автоматически.

**Критерии исключения:**
- beep, автоответчик, IVR без живого разговора;
- звонки без распознаваемого speech (empty/garbage transcript);
- CDR-only / no-transcript звонки без достаточного live-сигнала: не `answered`, не `in/out`, или `duration < 90`;
- короткие partial contact / routing-like / no-speech звонки без содержания;
- технические и служебные звонки без клиентской составляющей (зависит от правила — см. Open Questions).

**Назначение в отчёте:**
- `meaningful_calls` — это список звонков дня в `СПИСОК ЗВОНКОВ ДНЯ`;
- менеджер должен видеть в списке всё, что он содержательно делал за день.

**Примеры:**
| Класс | Входит в meaningful_calls? |
|---|---|
| beep / no speech / IVR | нет |
| CDR-only answered in/out >= 90с | да, как probable live conversation |
| CDR-only < 90с / missed / local | нет |
| support / internal | зависит от правила (см. F) |
| sales / follow-up | да |
| coaching-worthy sales call | да |

---

### Слой 3: `coaching_core`

**Назначение:** звонки, которые идут в coaching-блоки, deep review, СИТУАЦИЯ ДНЯ, РАЗБОР ЗВОНКА, БАЛЛЫ ПО ЭТАПАМ.

**Критерии включения:**
- классифицированы как `sales`, `follow-up` или иные coaching-релевантные типы;
- имеют готовый анализ (`ready_analysis`) — прошли LLM-1 → LLM-2 и не признаны semantic-empty;
- не помечены как `not_eligible` или `not_coachable_or_reportable`;
- analysis_eligibility ≠ `not_eligible`.

**Критерии исключения:**
- звонки с `call_type=support` или `call_type=internal`, если помечены `not_eligible`;
- семантически пустые анализы (`semantically_empty_analysis`);
- failed analysis (`is_failed=true`);
- звонки без транскрипта или без анализа.

**Назначение в отчёте:**
- `coaching_core` используется в коучинговых блоках: СИТУАЦИЯ ДНЯ, БАЛЛЫ ПО ЭТАПАМ, РАЗБОР ЗВОНКА, ГОЛОС КЛИЕНТА, ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ;
- `coaching_core` используется для readiness decision (full_report / signal_report / skip_accumulate);
- `coaching_core` — это не весь список дня.

**Примеры:**
| Класс | Входит в coaching_core? |
|---|---|
| beep / no speech / IVR | нет |
| support / internal | нет (если not_eligible) |
| sales / follow-up с ready analysis | да |
| coaching-worthy sales call | да |

---

## C. Report Contract для `manager_daily`

### Принципиальное правило

> **Ежедневный отчёт не должен показывать менеджеру только узкое аналитическое ядро (`coaching_core`) как будто это весь день.**
>
> Список звонков дня и deep-review / coaching-блоки — это разные слои. Они должны быть явно разведены в report contract и в runtime.

---

### Service Note / Шапка отчёта

Service note должна отображать полную воронку отбора:

```
Найдено в телефонии: {raw_calls_total}
Содержательных разговоров: {meaningful_calls_total}
С готовым разбором: {coaching_candidate_calls_total}
Вошло в отчёт: {included_in_report_total}
```

Дополнительно — если применялось rolling window:
```
Данные за {window_days_used} рабочих дн. (с {window_start} по {window_end})
```

Если часть звонков исключена — краткие причины исключения:
- `too_short_or_no_speech: N`
- `support_internal: N`
- `not_enough_analysis: N`

---

### СПИСОК ЗВОНКОВ ДНЯ

- Использует **`meaningful_calls`**, а не только `coaching_core`.
- Включает все содержательные звонки дня, вне зависимости от их coaching-eligibility.
- Звонки, не вошедшие в coaching core, показываются в списке без глубокого coaching-блока, но присутствуют.
- Колонки since Step 8AH-2: `#` / `Клиент` / `Тип / суть` / `Контекст` / `Статус`.
- `Клиент` содержит unified client/call reference from Step 8AH-1, including date/time, so separate `Время` column is no longer rendered.
- `Тип / суть` uses valid, non-generic `report_evidence.call_report_summary.short_topic` when available; otherwise it falls back to the deterministic `classification.call_type` / `scenario_type` label.
- `Контекст` is selected through the Step 8AH-11E call-list context quality gate. The gate prefers useful `call_report_summary.short_context`, then specific `short_topic`, then deterministic outcome/next-step/signal fallbacks.
- The call-list context gate rejects empty, bare-dash, low-information, truncated-with-ellipsis, technical-code-like, and bad-deadline contexts such as `до После...`, `до На этой неделе`, or `→ до Конец года 2026`.
- For `Договорённость`, `Перенос`, `Открыт`, and sales-related `Отказ`, the renderer should not show bare `—`; if summary context is missing/weak, reporting generates a human-readable fallback.
- Sort order: `Договорённость`, `Перенос`, `Отказ`, `Открыт`, `Тех/сервис`, `Не подходит для разбора`, then technical/unclassified buckets. Within each status group, sort by call time.

---

### Единый client/call display reference

Во всех `manager_daily` блоках, где отображается клиент или звонок, кроме самих фрагментов звонка, используется единый reader-facing reference:

```text
имя / ФИО / безопасный persisted label · телефон · дата, время
```

Fallback rules:
- если имени/label нет: `телефон · дата, время`;
- если телефона нет: `имя · дата, время`;
- если имя/label уже является тем же телефоном, телефон не дублируется;
- reporting layer не выдумывает ФИО и не извлекает новое имя из transcript ad hoc;
- unsafe / suspicious labels are rejected before display and fall back to phone/date/time.

Source priority:
1. persisted analysis call metadata (`scores_detail.call.contact_name` / `contact_phone` and compatible aliases);
2. persisted interaction metadata (`contact_name`, `contact_label`, `customer_name`, `contact_phone` and compatible aliases);
3. existing call reference fields already assembled in the reporting payload.

Since Step 8AH-8B, candidate names/labels are rendered only if they pass the safe display-name guard:
- exact unsafe/generic labels such as `ужас`, `алло`, `да`, `нет`, `не знаю`, `клиент`, `абонент`, `заявка`, `договор`, `эдо`, `поддержка`, `продажи`, `техподдержка`, `менеджер`, and `неизвестно` are rejected;
- phone-like values, duplicate phone labels, digit-bearing labels, URL/email-like values, too-long values, and symbol-noisy values are rejected;
- valid persisted names/FIO/name fragments such as `Надежда Анатольевна`, `Агирим`, `Акмарал`, `Екатерина`, `Максим`, and `Нур-Султан` remain allowed;
- if `report_evidence.call_report_summary.client_display_name` is used by future display paths, `client_name_confidence=low` must not become the primary label when a phone is available.

Этот display contract применяется к `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` и client column in `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ`. Структурное объединение колонок call list остаётся отдельным layout step.

Since Step 8AH-2, that structural call-list layout step is complete: `Время` is merged into `Клиент` through the unified display reference.

Since Step 8AH-7, richer per-call topic/context may come from valid `report_evidence.call_report_summary`:
- `short_topic` can fill `Тип / суть` only when specific and non-generic;
- `short_context` can fill `Контекст` when useful;
- broad `short_topic` values such as `Обсуждение...`, `Разговор...`, `Звонок...`, `Продажи...`, or `Холодный звонок...` fall back to deterministic type/scenario labels;
- missing or invalid `report_evidence` falls back to the previous deterministic/legacy fields.

Since Step 8AH-11E, `Контекст` is no longer a raw summary/follow-up passthrough. The quality gate chooses the first usable source:
1. high-quality `call_report_summary.short_context`;
2. specific `call_report_summary.short_topic` normalized as a sentence;
3. final outcome + next step / deadline fallback;
4. call type + customer signal fallback;
5. safe deterministic fallback.

Fallback examples:
- `open` without a clear next step: `Контакт открыт, следующий шаг не зафиксирован.`;
- `rescheduled` with a deadline: `Клиент попросил вернуться в согласованный срок: {deadline}.`;
- invoice/payment agreement: `Есть коммерческий следующий шаг: отправить счёт, подтвердить получение и согласовать оплату.`;
- refusal without reason: `Клиент отказался, причина отказа не извлечена.`;
- technical/service: `Технический / сервисный звонок, продажный контекст не выявлен.`;
- after-signature service/sales attempt: `Звонок после подписания документа, продажный потенциал не раскрыт.`;
- materials/KP/WhatsApp request: `Клиент попросил материалы, следующий контакт нужно закрепить отдельно.`

Payload diagnostics:
- `call_list_context_quality.status`;
- total calls;
- count of contexts sourced from `call_report_summary.short_context` / `short_topic`;
- count of deterministic fallbacks;
- retained bare contexts, if any;
- rejected candidate contexts with reasons: `empty_context`, `bare_dash`, `truncated_context`, `technical_fragment`, `bad_deadline_wording`, `low_information`.

This gate does not change final status, outcome totals, report-day call-list inclusion, status sorting, or coaching-block data-scope behavior.

### Outcome resolver grounded-source rule

Since Step 8AH-8A, hard `Отказ` matching in `BusinessOutcomeResolver` must be grounded in the transcript / classification / follow-up surface, not in synthetic coaching narrative.

Allowed sources for hard refusal tokens:
- transcript text;
- classification fields;
- persisted `follow_up` fields such as `reason_not_fixed` / `next_step_text`.

Excluded from hard refusal token matching:
- `recommendations`;
- `gaps`;
- `strengths`;
- `report_evidence.situation_candidates[].what_it_means`;
- other LLM-written coaching explanations that describe a risk such as “предложение будет неактуально” rather than a client refusal.

Reason: Step 8AH-8A showed that a valid open follow-up (`Вы можете отправить предложение, я вам написала почту`) can be incorrectly flipped to `Отказ` if the resolver treats synthetic coaching guidance as client outcome evidence. Other legacy resolver paths may still use broader analysis text where already established, but hard refusal requires grounded outcome evidence.

---

### Коучинговые блоки

Используют **только `coaching_core`**:
- СИТУАЦИЯ ДНЯ
- БАЛЛЫ ПО ЭТАПАМ
- РАЗБОР ЗВОНКА
- ГОЛОС КЛИЕНТА
- ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ

Readiness decision (`full_report` / `signal_report` / `skip_accumulate`) также считается по `coaching_core`.

### Data scope for coaching blocks

Since Step 8AH-11A, coaching blocks carry a deterministic `data_scope` assigned by the reporting layer:

| `data_scope` | Meaning | Rendering rule |
|---|---|---|
| `report_day` | The selected call/metric comes only from report-day calls. | Existing day wording is allowed: `Ситуация дня`, `Сегодня`. |
| `expanded_coaching_base` | A selected coaching call comes from the expanded coaching base rather than the report-day call list. | The block must explain that the call was selected from the expanded coaching base and must not present it as a plain report-day situation. |
| `rolling_window` | The metric/pattern is aggregated from a rolling-window coaching base. | The renderer must use `За последние N рабочих дней` / rolling-window wording and must not say `Сегодня` for that metric. |

Applied blocks:
- `СИТУАЦИЯ ДНЯ` / coaching situation;
- `РАЗБОР ЗВОНКА`;
- `ЧЕЛЛЕНДЖ НА ЗАВТРА`;
- `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`, when applicable.

`data_scope` is not an LLM2 output and does not change `report_evidence`. It is derived from selected persisted artifacts, report-day filters, and the effective coaching window. `ИТОГ ДНЯ`, `ДЕНЬГИ НА СТОЛЕ`, and `СПИСОК ЗВОНКОВ ДНЯ` remain report-day only, and rolling/expanded calls must not enter the call list.

### Daily coaching focus

Since Step 8AH-11B, the main coaching blocks share one structured focus object:

```json
{
  "stage_id": "Э3",
  "stage_code": "needs_discovery",
  "stage_name": "Выявление детальных потребностей",
  "problem_signal": "specific_use_cases_not_identified",
  "problem_statement": "Конкретные сценарии использования не были выявлены",
  "data_scope": "report_day | expanded_coaching_base | rolling_window",
  "evidence_call_id": "...",
  "breakdown_call_id": "...",
  "challenge_metric_source": "score_by_stage.priority",
  "confidence": "high | medium | low",
  "validation": {"status": "passed | warning", "issues": []}
}
```

Selection rule:
- `daily_coaching_focus` is derived by the deterministic reporting layer from aggregated `score_by_stage` priority and existing problem text.
- `БАЛЛЫ ПО ЭТАПАМ`, `СИТУАЦИЯ` / coaching situation, `РАЗБОР ЗВОНКА`, `ГЛАВНЫЙ ФОКУС НА ЗАВТРА`, and `ЧЕЛЛЕНДЖ НА ЗАВТРА` must use this focus stage.
- `report_evidence.situation_candidates` and `report_evidence.manager_coaching_moments` are filtered to `daily_coaching_focus.stage_code`.
- Legacy fallback may use uncoded text-only gap evidence, but it stays attached to the selected focus stage and must not switch the main focus.
- If no suitable evidence exists for the focus stage, the block renders an explicit insufficient-evidence message instead of silently using another stage.
- Stage mismatch between focus, Situation, and Breakdown is exposed in `daily_coaching_focus_validation` as a warning.

This does not change outcome totals, report-day call-list semantics, Step 8AH-11A `data_scope`, or the `report_evidence` schema.

### Problem wording normalization

Since Step 8AH-11C, manager-facing coaching problem text is normalized downstream by the reporting layer before it reaches the PDF/DOCX render model.

The normalizer applies to:
- `score_by_stage[].problem_summary` and the `Основная проблема` text in `БАЛЛЫ ПО ЭТАПАМ`;
- `daily_coaching_focus.problem_statement`;
- Situation Day / coaching situation problem wording;
- Call Breakdown `Что было` problem wording;
- `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` gap titles and gap body text;
- DOCX fallback stage/additional-situation problem text.

Rules:
- positive or neutral statements must not be rendered as the problem for a `Фокус на завтра`, `Зона внимания`, or `Зона роста`;
- if a persisted criterion/title says a positive behavior such as `Менеджер не ушел в презентацию слишком рано`, the renderer rewrites it into the missing behavior, for example `Квалификация не была завершена до предложения`;
- Additional Situation gap title and body must not contradict each other; if title is positive but body describes a gap, the title is rewritten as a gap;
- if no safe rewrite is possible, the safe fallback is `Проблема требует уточнения по evidence`, not a positive statement presented as a problem.

Payload diagnostics:
- `problem_wording_diagnostics.status` is `warning` when any problem wording was normalized or still looks unsafe;
- `problem_wording_diagnostics.normalized_count` counts normalized manager-facing problem fields;
- `daily_coaching_focus.validation.issues` may include `positive_or_neutral_problem_wording_normalized` when the focus problem needed rewriting.

This normalizer does not change score values, final outcomes, report-day call-list semantics, `data_scope`, `daily_coaching_focus.stage_code`, `report_evidence`, or LLM2 prompts.

### Additional Situations quality gate

Since Step 8AH-11D, `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` is filtered by a reporting-layer quality gate before rendering.

Minimum manager-facing situation contract:

```json
{
  "title": "...",
  "stage_id": "Э2",
  "problem_signal": "...",
  "data_scope": "report_day | expanded_coaching_base | rolling_window",
  "evidence_call_id": "...",
  "evidence_quote": "...",
  "what_happened": "...",
  "why_it_matters": "...",
  "next_action": "...",
  "why_this_works": "...",
  "confidence": "high | medium | low"
}
```

Gate rules:
- a situation is not rendered when it has neither grounded evidence nor concrete call context;
- duplicate problem signals are filtered so the block does not repeat the same secondary pattern;
- low-confidence or unresolved title/body mismatches are filtered;
- generic text such as `Клиент не получил достаточно конкретики...` or `Задать уточняющий вопрос...` must not be repeated across unrelated signals;
- if generic wording can be safely adapted, the reporting layer replaces it with stage-specific guidance:
  - primary contact: trust, call reason, and conversation relevance;
  - qualification: role, current process, and need before an offer;
  - needs discovery: concrete scenarios and decision criteria;
  - presentation: product value tied to the client's task;
  - objection handling: specific risk or doubt;
  - completion: date, channel, owner, and next step.

If no situation passes the gate, the section is hidden; no empty placeholder, `—`, `None`, or generic filler is rendered. Payload diagnostics expose `additional_situations_quality.status`, input/rendered/filtered counts, filter reasons (`missing_evidence`, `generic_wording`, `title_body_mismatch`, `duplicate_signal`, `low_confidence`), and rendered-situation metadata.

This gate does not change final outcomes, call-list report-day semantics, `data_scope`, `daily_coaching_focus`, problem wording normalization, LLM2 prompts, or the `report_evidence` contract.

Since Step 8AD, evidence-bearing coaching blocks prefer valid additive LLM2 `report_evidence v1` when it exists and passes `validate_report_evidence(scores_detail, transcript)`:
- `СИТУАЦИЯ ДНЯ` prefers usable `report_evidence.situation_candidates`;
- `РАЗБОР ЗВОНКА` prefers usable `report_evidence.manager_coaching_moments`;
- `ГОЛОС КЛИЕНТА` prefers usable grounded `report_evidence.voice_of_customer`;
- `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` prefers usable high/medium `report_evidence.additional_situations`;
- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` may use `report_evidence.follow_up_candidates` for text enrichment, but only after the final `payload.call_list[]` status allows inclusion.
- Since Step 8AH-7, `call_report_summary.manager_next_action`, `short_context`, `hotness_reason`, and safe `suggested_manager_phrase` may enrich `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, and `manager_next_action` may enrich `ГОЛОС КЛИЕНТА`; deterministic final outcome and Step 8AH-3 hotness priority remain final authority.
- Since Step 8AH-8D, `ГОЛОС КЛИЕНТА` manager action first uses a valid specific `call_report_summary.manager_next_action` only when it aligns with the detected client quote signal; otherwise reporting uses deterministic signal-specific actions for internal discussion, current-solution-enough, trust barrier, materials/price request, refusal, and service/signing issues. Generic fallback is last resort and must not replace a clear client signal.
- Since Step 8AH-8E, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` uses signal-specific follow-up profiles for invoice/payment, meeting/demo, materials/KP/WhatsApp, internal discussion, rescheduled callbacks, trust/channel barriers, weak open, and generic agreements. The same profile supplies `Контекст`, `Рекомендация`, and the safe opening phrase. LLM2 `manager_next_action` may override only when specific and aligned; deterministic hotness and final inclusion/exclusion remain unchanged.
- Since Step 8AH-8F, `РАЗБОР ЗВОНКА` ranks evidence-backed coaching moments above fragmentless moments. Missing fragments must render an explicit weak-evidence note instead of a bare `—`; weak/missing call-breakdown evidence must not be presented as strong proof.

If `report_evidence` is missing or invalid, the report uses the current Step 8W persisted evidence/transcript fallback. Reporting diagnostics must expose `report_evidence_available`, `report_evidence_valid`, validation issues, and `report_evidence_source=report_evidence|legacy_fallback`.

Since Step 8AF, legacy evidence fallback has an information-quality guard:
- greeting-only, name-confirmation, connection/noise, `ТЕЛЕФОННЫЙ ЗВОНОК`, and IVR-like boilerplate are not selected as proof fragments while any more meaningful sales-like fragment exists;
- fallback ranking prefers valid `report_evidence`, then usable sales-like evidence, then transcript fragments with business terms, and keeps greeting/IVR fragments only as last resort;
- low-information last-resort fragments must be marked weak/partial rather than rendered as strong proof;
- fresh LLM2 finding rows that provide `text` without `title` are still valid for report aggregation and legacy `РАЗБОР ЗВОНКА` fallback.

---

### Счётчики в итоговом блоке ИТОГ ДНЯ

Итоговая таблица (ЗВОНКОВ / ДОГОВОРЁННОСТЬ / ПЕРЕНОС / ОТКАЗ / ОТКРЫТ / ТЕХ/СЕРВИС / БЕЗ РАЗБОРА) считается по **`meaningful_calls`** report-day, а не по `coaching_core`.

Это позволяет показать реальный операционный результат дня, а не только аналитическое подмножество.

**Источник данных в коде:**
- `payload.call_outcomes_summary` строится из `operational_meaningful_artifacts` — report-day meaningful calls (тот же источник, что и `call_list`).
- Звонки без готового reusable разбора (`status is None`) считаются как `unclassified_count`, а не как `open`.
- Колонка `БЕЗ РАЗБОРА` показывается только если `unclassified_count > 0`.
- `call_outcomes_summary.unclassified_by_bucket` разделяет manager-facing причины: `Без транскрипта`, `Без анализа`, `Не подходит для разбора`, `Ошибка анализа`, `Ошибка провайдера`, `Нет итога`, `Нет классификации`, `Без разбора`.
- Сумма всех категорий (включая `БЕЗ РАЗБОРА`) обязана равняться `meaningful_calls_total`.

**Business outcome resolver (Step 8R):**
- Финальный `status` для `call_list[]` и `call_outcomes_summary` определяется deterministic reporting-layer resolver из уже сохранённых данных: transcript / `interaction.text`, selected stable reusable or persisted failed analysis, `scores_detail.classification`, `scores_detail.follow_up`, fail reason and metadata.
- Resolver не запускает STT/LLM, не меняет analyzer prompt, scoring, eligibility, selection model, rolling window, delivery или PDF layout.
- Приоритет категорий:
  1. technical blockers: `Без транскрипта`, `Без анализа`, `Ошибка анализа`, `Ошибка провайдера`;
  2. `Тех/сервис` для содержательной сервисной помощи;
  3. `Отказ` для явного отказа;
  4. `Договорённость` только для реального следующего коммерческого шага;
  5. `Перенос`;
  6. `Открыт`;
  7. `Не подходит для разбора` только для truly semantic-empty / no business signal.
- `not_coachable_or_reportable` больше не означает автоматическое `Не подходит для разбора` в manager-facing outcome. Сначала resolver пытается найти business outcome; если найден сервис, отказ, перенос, договорённость или open/follow-up, в отчёт попадает бизнес-категория. Если business signal отсутствует, остаётся `Не подходит для разбора`.
- `duration_below_threshold` / coaching non-eligibility не должны перебивать business outcome в report-day call list, если transcript or persisted analysis содержит бизнес-смысл.

**Stable analysis selection (Step 8-STABLE):**
- Normal `manager_daily` report runs do not use raw latest-by-`created_at` blindly.
- Analysis rows may carry purpose in existing JSON without migration: `scores_detail.analysis_purpose` and `scores_detail.meta.analysis_purpose`.
- Allowed purpose values are `production`, `controlled_sample`, and `verification`; unmarked legacy rows are treated as `production`.
- Default manager_daily behavior is `include_controlled_samples=false`: rows marked `controlled_sample` or `verification` are excluded from normal reporting.
- The selected row is the newest reusable stable analysis. If the newest stable row is invalid/non-reusable, reporting falls back to an older reusable stable row. If no reusable stable row exists, the newest allowed non-reusable row is returned for existing rejection diagnostics.
- Explicit opt-in (`include_controlled_samples=true` / `--include-controlled-samples`) allows controlled rows to participate in selection for bounded verification only.
- Future controlled sample / verification persistence must mark purpose explicitly. Controlled/verification rows must not overwrite a production row with the same `instruction_version`.

**`coaching_core` и rolling window не влияют на `call_outcomes_summary`** — они используются только в coaching-блоках (СИТУАЦИЯ ДНЯ, БАЛЛЫ ПО ЭТАПАМ, РАЗБОР ЗВОНКА, ГОЛОС КЛИЕНТА, ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ).

**Post-summary outcome alignment (Step 8U):**
- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` строится из финального report-day `payload.call_list[]` / `BusinessOutcomeResolver` status, а не из raw `follow_up` по `coaching_core`.
- В блок попадают только final `Договорённость`, `Перенос`, `Открыт`.
- Final `Отказ`, `Тех/сервис`, `Не подходит для разбора`, `Без транскрипта`, `Без анализа`, `Ошибка анализа`, `Ошибка провайдера` не становятся tomorrow sales actions.
- Priority label is a deterministic follow-up hotness, separate from final outcome:
  - `hot -> Горячий`: final `Договорённость`, especially when existing persisted text/follow-up fields mention invoice, payment, meeting/Zoom/demo, concrete date/deadline, purchase, connection, or commercial proposal.
  - `rescheduled -> Перенос`: final `Перенос`.
  - `warm -> Тёплый`: final `Открыт` with an explicit existing signal such as request for materials/information/KP/WhatsApp, "посмотрю/подумаем/посоветуюсь", or other clear interest without a hard commitment.
  - `low -> Низкий`: final `Открыт` without a clear deadline or next commercial step.
- Tomorrow sorting uses hotness order `Горячий -> Перенос -> Тёплый -> Низкий`, then nearest deadline, then call time.
- `Открытый` remains a final status label in call outcomes/call list, but must not be used as a `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` priority label.
- Если после фильтрации нет кандидатов, блок показывает safe empty state и не фабрикует follow-up.
- Normal coaching examples for report-day calls (`РАЗБОР ЗВОНКА`, `СИТУАЦИЯ ДНЯ`, `ЧЕЛЛЕНДЖ`) exclude final `Отказ`, `Тех/сервис`, and unclassified technical buckets when at least one final sales-like candidate (`Договорённость`, `Перенос`, `Открыт`) exists. If no sales-like candidate exists, sparse fallback behavior may remain explicit rather than silently treating service/refusal as normal sales coaching.

**Situation Day evidence contract (Step 8W):**
- `СИТУАЦИЯ ДНЯ` must not render a strong coaching conclusion without either a call reference + evidence fragment or an honest insufficient-evidence state.
- Primary evidence source remains `situation_evidence_quote` from persisted `evidence_fragments.client_text` linked to the Situation Day/focus stage by `criterion_code`.
- Since Step 8AH-8C, if the conclusion is about client reaction/state (trust or distrust, convenience to talk, doubt, objection, refusal/reschedule, need, current process, or client barrier), manager-only evidence is not strong proof when valid client-grounded evidence exists.
- For such client-reaction cases, evidence ranking prefers usable `report_evidence.situation_candidates` with client dialogue, then relevant client quotes from valid persisted `report_evidence.voice_of_customer` / `quote_bank`, then transcript/dialogue excerpt, then manager-only fallback, then explicit weak/insufficient evidence.
- If a client quote replaces a manager-only fragment, the payload marks `source=report_evidence.client_grounded_situation`, `client_grounded=true`, and aligns `what_happened`, `what_it_means`, `what_was_missing`, and `next_time_action` to the selected client signal without inventing new client facts.
- If stage-linked quote is absent, the reporting layer may use the selected sales-like `call_breakdown` call as bounded fallback evidence source. The selected call is referenced by `call_breakdown.call_id` plus `date_label`, `time_label`, `client_label`, and `client_phone`.
- Fallback order:
  1. `evidence_fragments.client_text` from the selected breakdown call, with `manager_text` when present;
  2. persisted `interaction.metadata_.segments` from the selected breakdown call, 1-3 short turns;
  3. persisted `interaction.text` from the selected breakdown call, 1-3 short text chunks;
  4. if none of the above exists, render `Недостаточно подтверждённых фрагментов звонков для доказательного разбора ситуации дня.`
- Segment/text fallback must skip greeting-only and IVR-like boilerplate when better transcript evidence exists. If only low-information text remains, payload marks `partial_reason=low_information_fragment_only` / `evidence_quality=weak` so the renderer does not present it as strong proof.
- Speaker roles must not be invented. When persisted segment speaker roles are unreliable or generic, the payload uses `speaker=unknown` and the renderer shows `Реплика`, not `Клиент` / `Менеджер`.
- If there is no explicit priority stage below the threshold but a meaningful key problem and selected breakdown call exist, the focus deep-dive may use the lowest-scoring available stage as a bounded Situation Day fallback.
- This is payload/render assembly only: no analyzer prompt, STT/LLM, scoring, eligibility, selection model, rolling-window, business outcome resolver, or delivery behavior changes.

**Target report evidence architecture (Step 8Y):**
- Step 8W fallback is the backward-compatible path for legacy analyses, not the final semantic architecture.
- Target path: `STT -> transcript/segments -> LLM1 routing -> LLM2 deep analysis + report_evidence -> deterministic reporting layer`.
- LLM2 should add an additive `report_evidence` package to each analyzed call. The approved MVP-1 analysis contract remains valid and is not replaced.
- `report_evidence` contains report-ready candidates for `business_outcome`, `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, and reusable quote bank.
- Reporting layer remains deterministic: it selects report scope/report-day calls, validates/ranks candidates, applies final `BusinessOutcomeResolver` status, aggregates, renders, and falls back to Step 8W logic when `report_evidence` is absent or invalid.
- Final `BusinessOutcomeResolver` status wins over `report_evidence.business_outcome` conflicts. For example, explicit refusal beats LLM-open, service/document help beats LLM-not-suitable, and technical blockers remain blockers.
- Full contract, validation requirements, backward compatibility, prompt update plan, and rollout Step 8Z..8AI live in `docs/REPORT_EVIDENCE_CONTRACT.md`.

**`ДЕНЬГИ НА СТОЛЕ`** использует только actionable outcomes из того же `call_outcomes_summary` (`agreed` + `open` + `rescheduled` из report-day meaningful). Buckets `Без транскрипта`, `Без анализа`, `Не подходит для разбора`, `Ошибка анализа`, `Ошибка провайдера` и прочий `БЕЗ РАЗБОРА` не входят в money calculation. Если actionable outcomes = 0, показывается `Данных для данного раздела недостаточно.`.

### Manager-Facing Completeness Gate

Обычный manager-facing daily report считается готовым к business delivery только если техническая обработка report-day call list завершена.

Gate проходит, когда в `call_list[]` нет blocking buckets:
- `Без транскрипта`;
- `Без анализа`;
- technical `Ошибка анализа`;
- `Ошибка провайдера`.

Gate может пропустить отчёт, если в нём остались:
- normal outcomes (`Договорённость`, `Перенос`, `Отказ`, `Открыт`);
- `Не подходит для разбора` для semantic-empty / not business-meaningful calls after BusinessOutcomeResolver pass;
- `Тех/сервис`.

Если gate не проходит, runtime возвращает operator-facing `review_required` с reason `incomplete_day_call_processing`, counts и affected calls. Business email не отправляется; operator/test preview может быть создан только как incomplete preview.

---

## D. Rolling Window Rule

### Операционный слой дня

- `raw_calls` — всегда только за выбранный день.
- `meaningful_calls` — всегда только за выбранный день.
- СПИСОК ЗВОНКОВ ДНЯ — всегда только за выбранный день.

Операционный слой не расширяется rolling window. Менеджер видит свой рабочий день.

### Коучинговый слой

- `coaching_core` и readiness decision **могут** использовать rolling window `1 → 2 → 3` рабочих дня для набора аналитической базы, если за один день звонков слишком мало для `full_report`.

**Порядок проверки:**
1. Сначала — только текущий рабочий день.
2. Если `full_report` не достигнут — последние 2 рабочих дня.
3. Если `full_report` не достигнут — последние 3 рабочих дня.
4. Дальше окно не расширяется.

### Transparency rule

Если rolling window применён (окно > 1 дня), это **обязательно** явно отражается в отчёте:
- в service note: «Данные за N рабочих дн. (с … по …)»;
- в structured result: `window_days_used`, `window_start`, `window_end`;
- в coaching-блоках — там, где данные из окна, а не только из текущего дня.

СПИСОК ЗВОНКОВ ДНЯ при этом **не расширяется** — он всегда за один выбранный день.

---

## E. Counters and Exclusion Reasons

### Минимальный набор счётчиков

Эти счётчики должны стать частью payload / report contract:

| Счётчик | Описание |
|---|---|
| `raw_calls_total` | Все CDR-записи из телефонии за день |
| `meaningful_calls_total` | Содержательные звонки дня: transcript-first calls + CDR-only probable live conversations; без beep/IVR/no-speech/partial contact |
| `service_calls_total` | Технические / служебные звонки, исключённые из meaningful |
| `coaching_candidate_calls_total` | Звонки, имеющие transcript + analysis, не помеченные not_eligible |
| `analyzed_calls_total` | Звонки с готовым анализом (is_failed=false, not semantic-empty) |
| `included_in_report_total` | Звонки, вошедшие в итоговый coaching_core для report |

### Причины исключения

Structured exclusion reasons (код → количество):

| Код | Смысл |
|---|---|
| `too_short_or_no_speech` | Звонок слишком короткий или без распознаваемого speech |
| `ivr_or_autoanswer` | IVR, автоответчик, beep без живого разговора |
| `support_internal` | Служебный / внутренний звонок без coaching-релевантности |
| `not_enough_analysis` | Нет готового анализа (нет transcript / is_failed / semantic-empty) |
| `not_selected_for_core_review` | Звонок есть в meaningful, но не прошёл отбор в coaching_core (по coverage / thresholds) |

### Использование

- Все счётчики должны передаваться в payload как явные поля.
- Exclusion reasons должны быть structured (не вычисляться на renderer-стороне).
- Service note строится из этих счётчиков, а не из магических чисел.
- Они доступны в operator diagnostics и в observability.

---

## F. Open Questions / Edge Cases

### F.1 — Входит ли support/service в СПИСОК ЗВОНКОВ ДНЯ?

**Текущее решение:** support/internal звонки **входят** в `meaningful_calls`, если у них есть реальный speech-контент (живой разговор с коллегой / клиентом по тех. вопросу).

Они **не входят** в `coaching_core` и не участвуют в coaching-блоках.

В СПИСОК ЗВОНКОВ они отображаются с типом `ТЕХ/СЕРВИС` или `ВНУТРЕННИЙ`, без coaching-оценки.

**Edge case:** если звонок помечен как `support` в classification, но содержит mixed-content (техвопрос + продажа), он обрабатывается по основному типу из `classification.call_type`.

### F.2 — Mixed calls (техника + продажа)

Звонок с mixed content (например: клиент сначала с тех. вопросом, потом продажа) обрабатывается по `classification.call_type` из analyzer.

Analyzer должен явно маркировать тип. Если тип `support` — звонок идёт в `service_calls_total`, в `meaningful_calls` (если есть живой контент), но не в `coaching_core`.

Если analyzer вернул `analysis_eligibility=not_eligible` — звонок фиксируется как `not_coachable_or_reportable` и не участвует в coaching-слое.

### F.3 — Короткие, но содержательные follow-up calls

Follow-up calls с короткой длительностью (например: «Перезванивает, как договорились, уточняет детали — 90 секунд») входят в `meaningful_calls`, если:
- есть реальный разговор (не beep / IVR);
- `call_type=follow-up` или `sales`.

В `coaching_core` они входят только если имеют ready analysis. Порог длины не является единственным критерием исключения.

### F.4 — Bound на число calls в СПИСОК ЗВОНКОВ ДНЯ

**Текущее решение:** СПИСОК ЗВОНКОВ ДНЯ не имеет жёсткого количественного ограничения (не обрезается произвольно до N).

### F.5 — CDR-only / no-transcript звонки после расширения raw source-day

После снятия hardcoded source-side duration cutoff `raw_calls` снова означает полный CDR-день по manager/extension/date scope.

Чтобы `meaningful_calls` не превращался в список всех коротких answered/no-transcript попыток, для CDR-only звонков действует отдельное deterministic rule:
- если transcript есть — применяется transcript-first rule, звонок остаётся meaningful;
- если transcript нет, звонок считается meaningful только как probable live conversation при `source_status=answered`, `direction in/out`, `duration >= 90`;
- если transcript нет и звонок `missed`, `local`, не `answered`, не `in/out`, или `duration < 90`, он исключается из meaningful как `too_short_or_no_speech`.

Это правило не меняет semantics `raw_calls`: такие звонки остаются в полном source-day счётчике. Оно также не меняет `coaching_core`: coaching-блоки по-прежнему требуют ready analysis и coaching eligibility.

Если звонков очень много (> 20), operator может видеть полный список, а в manager-facing PDF показывается подмножество с явным указанием: «Показано X из Y. Полный список доступен в системе.»

Конкретное число для усечения — open question для следующей итерации.

### F.5 — Что считать «рабочим днём» для rolling window?

Рабочий день = любой день с CDR-данными в системе для данного менеджера.

Выходные и праздники не пропускаются автоматически — если данные есть, они учитываются. Если в «рабочий день» данных нет, он пропускается при расширении окна.

Более умное calendar-based расширение (с учётом нерабочих дней) — open question для следующей итерации.

---

## Связь с другими docs

| Doc | Связь |
|---|---|
| `docs/MANUAL_REPORTING_PILOT.md` | readiness policy, rolling window, delivery rules — должны соответствовать этому contract |
| `docs/DECISIONS.md` | ADR-048 фиксирует этот selection model как standing rule |
| `docs/BUSINESS_READY_REPORT_PACK_TASKS.md` | implementation tasks для реализации этого contract |
| `docs/report_templates/reference/manager_daily_reference.md` | visual/semantic reference для report layout |
