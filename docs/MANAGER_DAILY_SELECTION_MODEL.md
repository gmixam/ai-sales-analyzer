# Manager Daily — Selection Model & Report Contract

## Назначение

Этот документ фиксирует canonical selection model и report contract для `manager_daily`.
Он является source of truth для bounded implementation tasks по этой теме.

**Первичная фиксация:** 2026-04-30.
**Implementation update:** 2026-05-08 — Step 8R добавил reporting-layer `BusinessOutcomeResolver` как legacy deterministic outcome classifier for diagnostics/counters; Step 8U выровнял post-summary blocks (`КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, normal coaching examples) с единым outcome source; Step 8W сделал `СИТУАЦИЯ ДНЯ` evidence-based через persisted evidence/transcript fallback выбранного sales-like `РАЗБОР ЗВОНКА`; Step 8Y зафиксировал целевой additive `LLM2 -> report_evidence -> reporting layer` contract in `docs/REPORT_EVIDENCE_CONTRACT.md`; Step 8AD подключил valid `report_evidence` как preferred evidence/candidate source with Step 8W fallback; Step 8AF добавил quality guard for legacy fallback so IVR/greeting-only fragments are not used as proof when better sales-like evidence exists; Step 8AH-1 зафиксировал единый display contract for client/call references across manager_daily blocks; Step 8AH-2 зафиксировал human-readable table layout contract and status-order call-list sorting; Step 8AH-7 подключил valid `report_evidence.call_report_summary` для call-list topic/context, tomorrow text enrichment, and voice-of-customer manager action with guarded fallback; Step 8-STABLE зафиксировал stable analysis selection so normal `manager_daily` prefers reusable production/stable rows and excludes controlled sample / verification analyses unless explicitly opted in; Step 8AH-8C усилил `СИТУАЦИЯ ДНЯ`, чтобы client-reaction conclusions prefer persisted client-grounded evidence over manager-only fragments when such evidence exists; Step 8AH-8D усилил `ГОЛОС КЛИЕНТА`, чтобы manager action was signal-specific rather than generic; Step 8AH-8E усилил `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, чтобы context/recommendation/opening phrase came from one signal-specific follow-up profile; Step 8AH-11A добавил `data_scope` для coaching-блоков, чтобы expanded/rolling evidence не рендерился как plain report-day; Step 8AH-11B добавил `daily_coaching_focus` как единый source for focus stage across main coaching blocks; Step 8AH-11C добавил downstream problem-statement normalization so positive/neutral LLM2 or fallback wording is not rendered as a manager-facing problem; Step 8AH-11D добавил quality gate for Additional Situations so generic/contextless cards are hidden and valid cards use evidence/context-backed, stage-specific wording; Step 8AH-11E добавил quality gate for call-list context so weak, truncated, technical, or empty contexts are replaced by neutral diagnostics or LLM-provided context without inventing business meaning; Step 8AH-11H добавил quality gate for Call Breakdown so manager-facing rows require confirming evidence, aligned corrective recommendations, and clean wording; 2026-05-12 block-fit update добавил `semantic_case.report_block_fit` и block-specific gates, чтобы valid semantic case не использовался в неподходящем блоке; 2026-05-12 role/problem-fit update добавил block roles, problem-fit alignment, and problem-fragment evidence gate for problem-oriented blocks; 2026-05-14 v14 proof-layer update добавил proof metadata and counter-evidence gates for problem-oriented semantic cases so `СИТУАЦИЯ ДНЯ` / problem `РАЗБОР ЗВОНКА` cannot use a quote that proves the opposite of the claimed manager gap; 2026-05-14 v15 block-ready target зафиксировал, что LLM2 готовит `report_evidence.block_candidates` for `situation_day`, `call_breakdown`, `voice_of_customer`, `money_on_table`, `tomorrow_follow_up`, `tomorrow_challenge`, and `call_list_context`, while Reporting keeps deterministic validation/selection/rendering authority only.

**Current semantic-report update:** 2026-05-21 — SFB-1..SFB-5 implemented in
`feature/llm2-block-ready-v15` (`73cb5cf`). `manager_daily` now uses LLM3
narrative composers for selected report blocks while this selection model
continues to own report-day scope, `meaningful_calls`, `coaching_core`,
evidence gates, counters/diagnostics, and renderer eligibility. Business
meaning shown to a manager must come only from LLM-provided semantic fields.
`Ситуация
дня` is a single narrative block; `Разбор звонка` is a concrete call-turn
breakdown and must not duplicate it; `Голос клиента` is customer-signal
interpretation; call-list context may prefer richer `manager_visible_summary`
when validated.

**LLM-only semantic reporting update:** 2026-06-05 — действующее правило:
manager-facing business meaning comes only from LLM (`scores_detail.status_details`,
`report_evidence.business_outcome`, `follow_up`, `call_report_summary`,
`block_candidates`, `semantic_case` and other approved LLM semantic fields).
Deterministic mechanisms may only diagnose, validate evidence, enforce format,
count rows, sort, and select among LLM-provided candidates. They must not invent
or finalize business status, agreement/refusal/open meaning, hotness, call
essence, situation-day thesis, stage problem, recommendation, praise, or
manager-facing sales advice. If LLM meaning/evidence is missing, the report
must show a neutral state such as `Без подтвержденного статуса`, `Суть не
сформирована LLM`, or `Нет LLM-комментария`.

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

**Назначение:** звонки, которые идут в narrative/coaching-блоки, deep review, `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`.

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
- `coaching_core` используется в narrative/coaching-блоках: `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`;
- `БАЛЛЫ ПО ЭТАПАМ` считаются шире: из всех report-day meaningful calls с reusable analysis и числовыми `score_by_stage`, чтобы stage aggregate не выглядел как оценка только по выбранным coaching examples;
- `payload.stage_score_scope` обязан показывать manager-facing строку охвата: `Посчитано по N разобранным звонкам из M содержательных звонков дня`; при низком покрытии добавляется предупреждение, что это срез по доступным разборам, а не полная оценка дня;
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
- `Контекст` is selected through the Step 8AH-11E/SFB-5 call-list context quality gate. The gate now prefers useful richer LLM context (`call_report_summary.manager_visible_summary`, valid `block_candidates.call_list_context.manager_visible_summary` / `call_list_context_rich`, or semantic-case manager-visible context), then useful `short_context`, then specific `short_topic`. If no LLM context passes, reporting shows neutral missing-context wording and diagnostics; it must not generate a new business meaning from transcript/status/follow-up fields.
- The call-list table remains compact. Richer context is preserved in payload as
  `call_list_context_rich` / `manager_visible_summary`, but the visible
  `call_list_context` rendered in PDF/email is one compact phrase with a
  `150` character limit. Rich context is allowed to preserve meaning, not to
  turn the row into a full call breakdown.
- The call-list context gate rejects empty, bare-dash, low-information, truncated-with-ellipsis, technical-code-like, and bad-deadline contexts such as `до После...`, `до На этой неделе`, or `→ до Конец года 2026`.
- For `Договорённость`, `Перенос`, `Открыт`, and sales-related `Отказ`, the renderer should not show bare `—`; if LLM summary/context is missing or weak, reporting shows a neutral state such as `Суть не сформирована LLM` and exposes the missing-field diagnostic.
- Sort order: `Договорённость`, `Перенос`, `Отказ`, `Открыт`, `Тех/сервис`, `Не подходит для разбора`, then technical/unclassified buckets. Within each status group, sort by call time.

---

### Единый client/call display reference

Во всех `manager_daily` блоках, где отображается клиент или звонок, кроме самих фрагментов звонка, используется единый reader-facing reference:

```text
имя / ФИО из LLM1/STT analysis · телефон · дата, время
```

Fallback rules:
- если имени/label нет: `телефон · дата, время`;
- если телефона нет: `имя · дата, время`;
- если имя/label уже является тем же телефоном, телефон не дублируется;
- reporting layer не выдумывает ФИО и не извлекает новое имя из transcript ad hoc;
- reporting layer не использует Bitrix/CRM/telephony metadata name fields как источник видимого ФИО;
- unsafe / suspicious labels are rejected before display and fall back to phone/date/time.

Source priority:
1. persisted analysis call metadata name from LLM1/STT (`scores_detail.call.contact_name` and compatible aliases);
2. persisted analysis call phone (`scores_detail.call.contact_phone`) or safe telephony phone metadata;
3. date/time from call metadata.

Visible client names must not fall back to interaction/telephony/Bitrix name fields
(`contact_name`, `contact_label`, `customer_name`, `client_name`). Those fields may
remain available for diagnostics or upstream enrichment, but manager-facing display
uses a name only after LLM1/analyzer has persisted it in analysis. See
[`PILOT-13`](PILOT13_CONTACT_NAME_SOURCE_TZ.md).

Since Step 8AH-8B, candidate names/labels are rendered only if they pass the safe display-name guard:
- exact unsafe/generic labels such as `ужас`, `алло`, `да`, `нет`, `не знаю`, `клиент`, `абонент`, `заявка`, `договор`, `эдо`, `поддержка`, `продажи`, `техподдержка`, `менеджер`, and `неизвестно` are rejected;
- phone-like values, duplicate phone labels, digit-bearing labels, URL/email-like values, too-long values, and symbol-noisy values are rejected;
- valid persisted names/FIO/name fragments such as `Надежда Анатольевна`, `Агирим`, `Акмарал`, `Екатерина`, `Максим`, and `Нур-Султан` remain allowed;
- if `report_evidence.call_report_summary.client_display_name` is used by future display paths, `client_name_confidence=low` must not become the primary label when a phone is available.

Этот display contract применяется к `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` и колонке клиента в приложении `ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ` (`call_list`). Структурное объединение колонок call list остаётся отдельным layout step.

Since Step 8AH-2, that structural call-list layout step is complete: `Время` is merged into `Клиент` through the unified display reference.

### Dialogue display contract

For every manager-facing block that renders call replicas:
- every line must show a speaker side;
- use `Менеджер` / `Клиент` only when role attribution is reliable;
- if attribution is uncertain, use neutral `Сторона 1` / `Сторона 2`;
- each replica starts on a new line;
- final PDF/DOCX/HTML rendering should style dialogue text in italic;
- dialogue is evidence and must not be invented, paraphrased as a quote, or
  merged into a single dense paragraph.

Since Step 8AH-7, richer per-call topic/context may come from valid `report_evidence.call_report_summary`:
- `short_topic` can fill `Тип / суть` only when specific and non-generic;
- `short_context` can fill `Контекст` when useful;
- broad `short_topic` values such as `Обсуждение...`, `Разговор...`, `Звонок...`, `Продажи...`, or `Холодный звонок...` fall back to deterministic type/scenario labels;
- missing or invalid `report_evidence` does not authorize deterministic business-summary generation; report rows use other valid LLM semantic fields or neutral missing-LLM states.

Since Step 8AH-11E/SFB-5, `Контекст` is no longer a raw summary/follow-up
passthrough. The quality gate chooses the first usable rich source:
1. high-quality `call_report_summary.manager_visible_summary`;
2. valid richer block-candidate context (`manager_visible_summary` /
   `call_list_context_rich`);
3. high-quality `call_report_summary.short_context`;
4. specific `call_report_summary.short_topic` normalized as a sentence;
5. neutral missing-LLM context state.

After source selection, the visible table context is compacted to one sentence.
The full selected text remains available in `call_list_context_rich`; diagnostics
expose `compacted_context_count`, `visible_context_limit`, and
`max_visible_context_length`.

Neutral missing-context examples:
- `Суть не сформирована LLM`;
- `Нет готового LLM-контекста`;
- `Контекст не подтвержден LLM`.

Payload diagnostics:
- `call_list_context_quality.status`;
- total calls;
- count of contexts sourced from `call_report_summary.short_context` / `short_topic`;
- count of neutral missing-LLM contexts;
- retained bare contexts, if any;
- rejected candidate contexts with reasons: `empty_context`, `bare_dash`, `truncated_context`, `technical_fragment`, `bad_deadline_wording`, `low_information`.

This gate does not create or change business status, outcome totals, report-day call-list inclusion, status sorting, or coaching-block data-scope behavior.

### Step 8AH-11 Semantic Regression Checkpoint

Before any verification rebuild after Step 8AH-11A..11H, run the targeted semantic checkpoint:

```bash
docker compose exec -T api pytest -q tests/test_manual_reporting.py -k 'step8ah11'
```

What it covers:
- **Data scope:** non-report-day coaching evidence is labeled as expanded/rolling; rolling/expanded metrics do not say `Сегодня`; `call_list` stays report-day only.
- **Daily coaching focus:** `БАЛЛЫ ПО ЭТАПАМ`, `СИТУАЦИЯ`, `РАЗБОР`, and `ЧЕЛЛЕНДЖ` share `daily_coaching_focus.stage_code`; missing evidence for the focus stage renders explicit insufficient-evidence fallback rather than silently switching stage.
- **Problem wording:** positive/neutral wording is normalized before manager-facing render; known phrases such as `Менеджер не ушел в презентацию слишком рано` do not appear as problems; Additional Situation title/body contradictions are normalized or filtered.
- **Additional Situations:** empty placeholders are hidden; weak/contextless/generic cards are filtered; rendered cards expose evidence/context-backed, stage-specific wording.
- **Call-list context:** technical deadline strings, meaningless truncated contexts, and bare `—` for sales/open/follow-up rows are blocked; weak `call_report_summary` context falls back to deterministic human-readable text.
- **Call Breakdown:** rows without confirming evidence are filtered; the missing-fragment note is not rendered as proof; problem rows cannot keep positive-only recommendations; punctuation artifacts such as `.:` are cleaned.

Diagnostic expectations covered by the checkpoint:
- `data_scopes`;
- `daily_coaching_focus_validation`;
- `problem_wording_diagnostics`;
- `additional_situations_quality`;
- `call_breakdown_quality`;
- `call_list_context_quality`.

When this checkpoint fails, fix the upstream mechanism first and do not rebuild PDFs until the targeted semantic checkpoint is green.

Known unrelated technical debt: the full `tests/test_manual_reporting.py tests/test_ai_provider_routing.py` suite currently has 5 selection/counter failures outside Step 8AH-11 semantic quality gates. They are tracked separately and must not be mixed into Step 8AH-11 content-quality fixes:
- `test_build_manager_daily_payload_enriches_outcomes_focus_and_dynamics`;
- `test_call_list_adds_analysis_not_reusable_reason`;
- `test_day_summary_uses_without_breakdown_bucket_and_preserves_total`;
- `test_manager_facing_completeness_gate_passes_with_non_coachable_bucket`;
- `test_unclassified_manager_buckets_are_added_to_call_list`.

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

### Claim-safety для вывода о следующем шаге

С 2026-05-21 в `manager_daily` действует мягкий guard для спорных coaching-выводов
про фиксацию следующего шага.

Правило:
- если выбранная `Ситуация дня` содержит next-step gap, но в видимом
  `call_list` за тот же день есть другие звонки со статусом `Договорённость`
  или `Перенос` и явным `next_step` / `deadline`, отчет не должен звучать как
  общая оценка “менеджер не договаривается о следующем шаге”;
- в таком случае формулировка сужается до выбранной сцены: проблема остается
  полезной для разбора, но описывает конкретный фрагмент, а не весь стиль
  работы менеджера;
- guard применяется к `situation_day_coaching_view`, verified
  `situation_day_evidence_packet` и `call_breakdown`;
- payload раскрывает диагностику в `next_step_claim_safety`, а также в
  `selection_diagnostics` / `call_breakdown_quality` для затронутых блоков.

Это не новый hard gate и не причина скрывать блок: selection, evidence
verification, score, outcome totals, call-list status, LLM2 prompt и LLM3
composer не меняются. Цель guard — убрать необоснованное day/global
обобщение, когда данные дня показывают counter-evidence.

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

### Call Breakdown quality gate

Since Step 8AH-11H, `РАЗБОР ЗВОНКА` is filtered by a reporting-layer quality gate before manager-facing render.

Gate rules:
- a table row is rendered only when it has a confirming evidence fragment / quote / concrete call context;
- the weak-evidence text `Нет подтверждающего фрагмента в сохранённых данных` is not rendered as a manager-facing fragment;
- if a row describes a growth/problem moment, the recommendation must be corrective and actionable; positive-only recommendations such as “продолжать использовать...” are filtered unless the row is explicitly a best-practice row;
- problem wording, fragment, and recommendation must have the same semantic polarity and must not duplicate each other;
- punctuation artifacts such as `говорить.: Менеджер...` are normalized before render;
- if no row passes the gate for the focus stage, the block shows the explicit fallback `Недостаточно подтверждённых фрагментов для детального разбора по фокусному этапу.` and does not silently switch to another stage.

Payload diagnostics:
- `call_breakdown_quality.status`;
- input/rendered/filtered row counts;
- filter reasons: `missing_evidence`, `no_confirming_fragment`, `recommendation_polarity_mismatch`, `duplicate_problem_wording`, `low_information`, `stage_mismatch`;
- rendered-row metadata.

This gate does not change final outcomes, report-day call-list semantics, `data_scope`, `daily_coaching_focus`, problem wording normalization, Additional Situations quality, call-list context quality, LLM2 prompts, or the `report_evidence` contract.

### Narrative report block roles

Since SFB-1..SFB-5, the final manager-facing shape of several blocks is
narrative-first, while selection and evidence checks remain deterministic:

- `Ситуация дня` renders one readable `Что произошло` narrative that explains
  the business episode and supports it with grounded replicas. It should not be
  split into repeated visible subblocks; the structured table below is enough
  for action/example separation.
- `Разбор звонка` renders the concrete call story and `Ход звонка` turning
  points. It must not repeat `Ситуацию дня` as separate conclusions such as
  `Что не сработало` / `Как провести лучше`.
- `Голос клиента` renders customer scenes as `Что клиент имеет в виду` and
  `Как с этим работать`. Its purpose is interpreting the client's real signal,
  not diagnosing the manager again.
- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` may use LLM3 wording for reason/action/example
  phrase only after deterministic inclusion has already accepted the contact.
- `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` render as short narrative cards only when the
  existing quality gate passes; otherwise the block is hidden.

The role boundary is part of the report contract. A block that duplicates
another block's job should be corrected in composer prompt/rendering, not by
loosening evidence gates.

Since Step 8AD, evidence-bearing coaching blocks prefer valid additive LLM2 `report_evidence v1` when it exists and passes `validate_report_evidence(scores_detail, transcript)`:
- `СИТУАЦИЯ ДНЯ` prefers usable `report_evidence.situation_candidates`;
- `РАЗБОР ЗВОНКА` prefers usable `report_evidence.manager_coaching_moments`;
- `ГОЛОС КЛИЕНТА` prefers usable grounded `report_evidence.voice_of_customer`;
- `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` prefers usable high/medium `report_evidence.additional_situations`;
- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` may use `report_evidence.follow_up_candidates` for text enrichment, but only after the final `payload.call_list[]` status allows inclusion.
- Since Step 8AH-7, `call_report_summary.manager_next_action`, `short_context`, `hotness_reason`, and safe `suggested_manager_phrase` may enrich `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, and `manager_next_action` may enrich `ГОЛОС КЛИЕНТА`; after the 2026-06-05 LLM-only update, deterministic logic validates/filters these fields but does not create final outcome or hotness priority.
- Since Step 8AH-8D, `ГОЛОС КЛИЕНТА` manager action first uses a valid specific `call_report_summary.manager_next_action` only when it aligns with the detected client quote signal; if no LLM action is valid, reporting may hide the action or show neutral missing-LLM wording, but must not replace it with generic deterministic advice.
- Since Step 8AH-8E, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` uses LLM-provided signal-specific follow-up candidates for invoice/payment, meeting/demo, materials/KP/WhatsApp, internal discussion, rescheduled callbacks, trust/channel barriers, weak open, and generic agreements. Deterministic code may select/sort among accepted candidates; it must not create hotness, context, recommendation, or opening phrase.
- Since Step 8AH-8F, `РАЗБОР ЗВОНКА` ranks evidence-backed coaching moments above fragmentless moments. Since Step 8AH-11H, fragmentless moments are filtered out of manager-facing rows; if no valid row remains, the explicit insufficient-evidence fallback is rendered instead of a weak fragment row.

If `report_evidence` is missing or invalid, the report may use other valid LLM semantic fields or neutral insufficient-evidence states. Step 8W persisted evidence/transcript fallback can remain as diagnostics/proof formatting only; it must not create manager-facing business meaning. Reporting diagnostics must expose `report_evidence_available`, `report_evidence_valid`, validation issues, and source selection.

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

**Business outcome resolver (Step 8R, superseded for manager-facing meaning on 2026-06-05):**
- `BusinessOutcomeResolver` is legacy deterministic logic and must not be the final authority for manager-facing business meaning.
- Visible `call_list_status` / `final_manager_status` may come only from LLM semantic fields, in this order when valid and evidence-backed:
  1. `scores_detail.status_details.status`;
  2. `report_evidence.business_outcome.status`;
  3. other approved LLM semantic status fields explicitly added to the report contract.
- If no LLM status is available or evidence is insufficient, payload must keep `call_list_status = None` / `final_manager_status = None` and render a neutral label such as `Без подтвержденного статуса`.
- Deterministic code may still count technical blockers (`Без транскрипта`, `Без анализа`, `Ошибка анализа`, `Ошибка провайдера`), validate evidence, format labels, sort rows, and expose diagnostics.
- `BusinessOutcomeResolver` may remain only as diagnostics: `resolver_status`, `resolver_reason_code`, `resolver_confidence`, mismatch counters, and investigation notes. Its output must not be promoted into `Договорённость`, `Перенос`, `Отказ`, `Открыт`, or `Тех/сервис` unless LLM supplied that same business meaning.
- `not_coachable_or_reportable`, `duration_below_threshold`, and coaching non-eligibility are not business statuses. They can explain readiness/coverage, but they must not create a manager-facing outcome.
- Confirmed pilot issue on 2026-06-05: in Tolegen's manager_daily report for 2026-06-04, resolver fallback produced false `Договорённость` rows where LLM did not confirm agreement through `business_outcome` / `status_details`. This is the concrete regression that triggered `docs/LLM_ONLY_SEMANTIC_REPORTING_TZ.md`.

**Stable analysis selection (Step 8-STABLE):**
- Normal `manager_daily` report runs do not use raw latest-by-`created_at` blindly.
- Analysis rows may carry purpose in existing JSON without migration: `scores_detail.analysis_purpose` and `scores_detail.meta.analysis_purpose`.
- Allowed purpose values are `production`, `controlled_sample`, and `verification`; unmarked legacy rows are treated as `production`.
- Default manager_daily behavior is `include_controlled_samples=false`: rows marked `controlled_sample` or `verification` are excluded from normal reporting.
- The selected row is the newest reusable stable analysis. If the newest stable row is invalid/non-reusable, reporting falls back to an older reusable stable row. If no reusable stable row exists, the newest allowed non-reusable row is returned for existing rejection diagnostics.
- Explicit opt-in (`include_controlled_samples=true` / `--include-controlled-samples`) allows controlled rows to participate in selection for bounded verification only.
- Future controlled sample / verification persistence must mark purpose explicitly. Controlled/verification rows must not overwrite a production row with the same `instruction_version`.

**`coaching_core` и rolling window не влияют на `call_outcomes_summary`** — они используются только в narrative/coaching-блоках (`СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`). `БАЛЛЫ ПО ЭТАПАМ` используют отдельный day-ready stage-score scope и обязаны показывать охват данных.

**Post-summary outcome alignment (Step 8U, LLM-only semantic rule):**
- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` строится только из LLM-подтвержденных semantic fields: `status_details`, `business_outcome`, `follow_up`, `follow_up_candidates`, `call_report_summary.manager_next_action`, `call_report_summary.hotness` / `hotness_reason`, or valid `block_candidates.tomorrow_follow_up`.
- В блок попадают только контакты с LLM-подтвержденным next step / reason to follow up and enough evidence. Deterministic code may select among those candidates and sort by LLM-provided deadline/time, but it must not invent priority or hotness.
- LLM-confirmed `refusal`, `tech_service`, `not_suitable`, technical blockers, or missing LLM status do not become tomorrow sales actions.
- Priority/hotness label is manager-facing business meaning. It must come from LLM. If LLM did not provide it, render `не определен LLM` or exclude the row when there is no sufficient next step.
- `Открытый` remains a possible LLM-confirmed final status label in call outcomes/call list, but must not be converted into a tomorrow priority without LLM priority/hotness.
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
- Target path: `STT -> transcript/segments -> LLM1 routing -> LLM2 deep analysis + semantic_case + report_evidence -> deterministic reporting layer`.
- LLM2 should add an additive `report_evidence` package to each analyzed call. The approved MVP-1 analysis contract remains valid and is not replaced.
- Starting with the semantic-analysis upgrade target added on 2026-05-12, LLM2 should provide `report_evidence.semantic_case` as the coherent per-call meaning source for report blocks. This changes the intended role from fragment/candidate production to meaningful call analysis, while keeping the upgrade additive and backward-compatible.
- Starting with the block-fit update on 2026-05-12, fresh LLM2 `semantic_case` output should include `report_block_fit` for `situation_day`, `call_breakdown`, `voice_of_customer`, `additional_situations`, and `call_tomorrow`. This lets LLM2 say where one call is suitable while the Report Layer remains deterministic.
- Starting with the role/problem-fit update on 2026-05-12, fresh `report_block_fit` also includes `block_role`, `title_mode`, `problem_fit`, `evidence_target`, and `gap_proven`. Problem blocks (`СИТУАЦИЯ ДНЯ`, main `РАЗБОР ЗВОНКА`) must prove what went wrong and align with the daily focus problem; neutral/action blocks (`ГОЛОС КЛИЕНТА`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`) can show the situation as-is without forcing a manager gap.
- Starting with the v15 block-ready target on 2026-05-14, fresh LLM2 output should also include optional `report_evidence.block_candidates` for `situation_day`, `call_breakdown`, `voice_of_customer`, `money_on_table`, `tomorrow_follow_up`, `tomorrow_challenge`, and `call_list_context`. These candidates are intended to be renderable material for each block, not just suitability flags.
- LLM2 must prepare block-specific meaning: `situation_day` gets a teachable thesis and better next action; `call_breakdown` gets one to three deeper moments; `voice_of_customer` gets a real customer signal without forcing a manager problem; `money_on_table` gets only concrete commercial opportunities; `tomorrow_follow_up` gets client-specific next action/opening/risk; `tomorrow_challenge` gets a skill standard signal; `call_list_context` gets short non-generic topic/context/action text.
- v15 proof rules are strict. `direct_gap` is only for a quote/fragment that directly proves the manager gap; `sequence_inference` is for event order; `absence_in_context` is for an expected action missing from the available record; `context_support` is context only and cannot prove a `fit=true` manager-gap problem. A product-offer quote does not directly prove missing qualification; for that claim the proof is normally sequence or absence.
- `report_evidence` contains report-ready candidates for `business_outcome`, `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `ДЕНЬГИ НА СТОЛЕ`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, `ЧЕЛЛЕНДЖ НА ЗАВТРА`, `call_list` context for the visible appendix `ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ`, legacy `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`, and reusable quote bank.
- Reporting layer remains deterministic only for non-semantic operations: it selects report scope/report-day calls, validates/ranks LLM semantic cases and candidates, aggregates counts, formats, renders, and exposes diagnostics. It does not apply `BusinessOutcomeResolver` as a final business-status authority and does not create manager-facing business meaning when `semantic_case` / `report_evidence` is absent or invalid.
- Starting with the semantic-case preference implementation on 2026-05-12, `manager_daily` prefers valid `semantic_case` for `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, and `ГОЛОС КЛИЕНТА`; legacy `report_evidence v1` candidates remain the fallback path for older analyses.
- Future v15 reporting selection should prefer valid `block_candidates[block]` before `semantic_case.report_block_fit`, but only after the schema/validator and report-layer gates accept them. Until then, `semantic_case` and legacy `report_evidence v1` remain the safe implemented sources.
- A valid `semantic_case` is not enough by itself: each block applies its own suitability gate. `СИТУАЦИЯ ДНЯ` requires a manager gap or missed opportunity, problem title, and problem-fit alignment with the daily focus; `РАЗБОР ЗВОНКА` requires a coachable manager moment or strong-practice role with grounded manager evidence; `ГОЛОС КЛИЕНТА` requires a grounded customer signal.
- Starting with the semantic-case diagnostics implementation on 2026-05-12, `payload.report_evidence_diagnostics` exposes per-call semantic-case availability, validity, usage, filter reason, and block-level source selection using `semantic_case`, `report_evidence_v1`, or `legacy_fallback`.
- Block diagnostics include selected/rejected semantic candidates with rejection reasons such as `customer_signal_without_manager_gap`, `positive_diagnosis_not_problem_case`, `manager_fragment_missing`, `title_mode_not_problem`, `problem_signal_mismatch`, or `report_block_fit_score_below_threshold`.
- `BusinessOutcomeResolver` status does not win over `report_evidence.business_outcome` conflicts for manager-facing meaning. Conflicts are diagnostics / human-review signals. The visible business status is selected only from valid LLM semantic status fields; if LLM evidence is missing or conflicting, show a neutral unconfirmed state rather than resolver-created meaning.
- Для manager-facing `Договорённость` действует дополнительный safety rule:
  LLM2 `business_outcome.status=agreement` принимается в видимый
  `call_list_status=agreed` только при явном коммерческом следующем шаге:
  счёт/оплата/КП/договор/подписание/подключение/демо/встреча/Zoom или
  конкретный next-contact с действием. Если LLM2 называет `agreement` только
  слабый интерес (`скиньте материалы`, `посмотрю`, `подумаем`) без
  коммерческого шага, Report Layer не показывает `Договорённость`; payload
  фиксирует `call_list_status_fallback_reason=llm2_agreement_without_explicit_commercial_step`
  или `agreement_missing_evidence` и оставляет видимый статус нейтральным либо
  выбирает другой valid LLM-provided status.
- Payload раскрывает `agreement_outcome_diagnostics`: сравнение LLM2 outcome,
  resolver diagnostics, видимого `call_list_status` и evidence validation для
  всех agreement-like звонков.
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
- `Не подходит для разбора` only when LLM/eligibility evidence supports non-coachable or not business-meaningful handling;
- `Тех/сервис`.

Если gate не проходит, runtime возвращает operator-facing `review_required` с reason `incomplete_day_call_processing`, counts и affected calls. Business email не отправляется; operator/test preview может быть создан только как incomplete preview.

---

## D. Strict Report-Day Rule

### Операционный слой дня

- `raw_calls` — всегда только за выбранный день.
- `meaningful_calls` — всегда только за выбранный день.
- СПИСОК ЗВОНКОВ ДНЯ — всегда только за выбранный день.
- `coaching_core`, readiness decision, stage-score aggregates, follow-up
  blocks, PDF/email subject/body and delivery gates — тоже только за выбранный
  день.

Операционный слой не расширяется rolling window. Менеджер видит свой рабочий
день. Если данных за день мало, `manager_daily` остается честным
`signal_report`, `review_required` или `skip_accumulate` по этому дню.

### Коучинговый слой

Для manager-facing `manager_daily` коучинговый слой больше не имеет права
использовать прошлые дни как visible/content базу. Исторические звонки нельзя
подмешивать в:

- `СИТУАЦИЮ ДНЯ`;
- `РАЗБОР ЗВОНКА`;
- `БАЛЛЫ ПО ЭТАПАМ`;
- `КОНТАКТЫ В РАБОТУ`;
- `ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ`;
- верхнюю воронку и статусные счетчики;
- email subject/body.

### Transparency rule

Для `manager_daily` expanded/rolling window является delivery blocker:

- `window_days_used` должен быть `1`;
- `window_start == window_end == report_day`;
- `meta.period.date_from == meta.period.date_to == report_day`;
- `included_in_report_total <= meaningful_calls_total`.

Если любое условие нарушено, business email менеджеру не отправляется; результат
должен уйти в operator-only `review_required`. Telegram/operator preview
допустим только для диагностики.

Rolling/expanded periods остаются допустимыми только для РОП weekly/monthly,
внутренних сравнений или специальных исследований, но не для manager-facing
daily.

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
