# Manager Daily — Selection Model & Report Contract

## Назначение

Этот документ фиксирует canonical selection model и report contract для `manager_daily`.
Он является source of truth для bounded implementation tasks по этой теме.

**Doc-only фиксация. Код не меняется.**
Фиксация: 2026-04-30.

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
- длительность выше минимального порога (без конкретного числа — задаётся в конфигурации);
- наличие распознаваемого speech-контента (не пустой трафик).

**Критерии исключения:**
- beep, автоответчик, IVR без живого разговора;
- звонки без распознаваемого speech (empty/garbage transcript);
- звонки короче минимального порога длины без содержания;
- технические и служебные звонки без клиентской составляющей (зависит от правила — см. Open Questions).

**Назначение в отчёте:**
- `meaningful_calls` — это список звонков дня в `СПИСОК ЗВОНКОВ ДНЯ`;
- менеджер должен видеть в списке всё, что он содержательно делал за день.

**Примеры:**
| Класс | Входит в meaningful_calls? |
|---|---|
| beep / no speech / IVR | нет |
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
- Колонки: `#` / `Время` / `Клиент` / `Тема` / `Статус` / `Следующий шаг` / `Контекст`.

---

### Коучинговые блоки

Используют **только `coaching_core`**:
- СИТУАЦИЯ ДНЯ
- БАЛЛЫ ПО ЭТАПАМ
- РАЗБОР ЗВОНКА
- ГОЛОС КЛИЕНТА
- ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ

Readiness decision (`full_report` / `signal_report` / `skip_accumulate`) также считается по `coaching_core`.

---

### Счётчики в итоговом блоке ИТОГ ДНЯ

Итоговая таблица (ЗВОНКОВ / ДОГОВОРЁННОСТЬ / ПЕРЕНОС / ОТКАЗ / ОТКРЫТ / ТЕХ/СЕРВИС) считается по **`meaningful_calls`**, а не только по `coaching_core`.

Это позволяет показать реальный операционный результат дня, а не только аналитическое подмножество.

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
| `meaningful_calls_total` | Содержательные звонки дня (после beep/IVR фильтрации) |
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
