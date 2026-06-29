# PILOT-39: Company-wide transcription service with selective analysis

Дата: 2026-06-29
Статус: `draft_ready`

## Контекст

Сейчас `call-processing` используется как upstream-контур для пилотного scope
ЭДО: OnlinePBX discovery -> audio fetch -> STT -> `transcript` /
`transcript_segments` -> `llm1_first_pass`.

Следующий целевой шаг: расширить транскрибацию и LLM1-карточку звонка на всю
компанию, но не расширять LLM2/LLM3-анализ автоматически. Анализ и отчеты
должны по-прежнему запускаться только по утвержденному downstream scope
например ЭДО Продажи, пока другой scope явно не добавлен.

## Архитектурное правило

`call-processing` владеет сырой обработкой звонков и карточкой звонка:

```text
OnlinePBX -> STT -> transcript/segments -> LLM1 call card
```

`analysis/reporting` владеет глубоким анализом и отчетами:

```text
selected managers/departments -> LLM2 -> LLM3 -> reports/delivery
```

Наличие STT/LLM1 artifact по звонку не должно само запускать LLM2/LLM3.
Downstream analysis всегда выбирает свой scope отдельно.

## Что считаем карточкой звонка

LLM1 artifact должен быть достаточным, чтобы позже искать и отбирать звонки
без повторного чтения полного transcript:

- кто звонил / кому звонили, если это доказано из STT;
- отдел/менеджер/extension и технические metadata;
- тема звонка;
- продукт/направление;
- тип обращения;
- горячесть/срочность;
- намерение клиента;
- результат разговора на верхнем уровне;
- применимость к дальнейшему анализу;
- краткая суть звонка;
- признаки качества STT и speaker role mapping.

Важно: карточка не должна сужать смысл звонка только под ЭДО. Она должна быть
универсальной корпоративной call card, пригодной для поиска по темам,
отделам, продуктам, горячести, типам обращений и последующего отбора в разные
аналитические контуры.

## Задачи

### PILOT-39A — Company-wide upstream scope

Статус: `planned`

Что сделать:

- проверить текущую модель `_daily_upstream_scope`;
- убрать обязательную привязку ночного upstream к одному отделу/четырем
  менеджерам, либо добавить отдельный production schedule для company-wide
  scope;
- определить безопасный способ строить company-wide scope из Bitrix/OnlinePBX:
  все активные сотрудники с extension, без уволенных и технических пользователей;
- сохранить возможность pilot/department scope как fallback;
- сделать dry-run режим, который показывает количество CDR, eligible audio,
  ожидаемые STT/LLM1 и прогноз стоимости до запуска provider calls.

Проверка:

- dry-run за выбранный день показывает весь company scope;
- текущий ЭДО manager_daily analysis продолжает видеть только своих менеджеров;
- `PILOT-38` covering lookup может использовать широкий upstream как источник
  для узкого analysis scope.

### PILOT-39B — LLM1 universal call card contract

Статус: `planned`

Что сделать:

- описать и зафиксировать schema `llm1_first_pass` как универсальную карточку
  звонка;
- проверить, какие поля уже есть в artifact и какие нужно нормализовать;
- добавить backward-compatible поля для поиска: topic, product_area,
  request_type, urgency, intent, outcome, department_hint, analysis_eligibility;
- не добавлять ЭДО-специфичные правила в общий LLM1 prompt;
- сохранить speaker role mapping из `PILOT-29`.

Проверка:

- старые artifacts без новых полей не ломают LLM2/reporting;
- новые artifacts дают карточку, достаточную для фильтрации звонков по темам и
  направлениям без повторной LLM1 обработки.

### PILOT-39C — Selective downstream analysis scope

Статус: `planned`

Что сделать:

- явно разделить upstream transcription scope и downstream analysis scope в
  настройках, schedule payload, diagnostics и документации;
- запретить analysis запускаться по всему company-wide upstream автоматически;
- сделать проверку, что manager_daily анализирует только утвержденных
  менеджеров/отделы, даже если upstream содержит всю компанию;
- в summary показывать `upstream_scope` и `analysis_scope` отдельно.

Проверка:

- company-wide upstream ready не создает отчеты по не-пилотным менеджерам;
- ЭДО отчеты продолжают строиться из широкого covering upstream;
- ROP digest содержит только выбранный analysis scope.

### PILOT-39D — Cost, quotas and monitoring for company-wide STT/LLM1

Статус: `planned`

Что сделать:

- добавить отдельные лимиты/алерты для company-wide STT и LLM1;
- считать стоимость STT+LLM1 по всему upstream run;
- показывать прогноз и факт: total calls, eligible calls, billable minutes,
  STT cost, LLM1 cost, cost per call card;
- добавить warning, если company-wide upstream выходит за дневной бюджет или
  provider quota.

Проверка:

- Codex по запросу может ответить: сколько стоила корпоративная транскрибация
  за день и сколько из нее использовал ЭДО analysis;
- reuse artifacts не увеличивает current-run cost;
- budget/quota проблемы видны оператору коротким alert.

### PILOT-39E — Controlled rollout and acceptance

Статус: `planned`

Что сделать:

- сначала провести read-only CDR forecast на несколько рабочих дней;
- затем controlled dry-run без provider calls;
- затем один company-wide provider-backed upstream run без расширения analysis;
- затем проверить, что ЭДО daily report строится из company-wide upstream через
  covering lookup;
- только после этого включать постоянный company-wide schedule.

Проверка:

- no unexpected LLM2/LLM3/report generation outside selected analysis scope;
- upstream artifacts ready по company-wide scope;
- ЭДО reports не деградировали;
- cost summary и alerts понятны.

## Что не делаем в этой задаче

- не расширяем LLM2/LLM3-анализ на всю компанию;
- не меняем STT provider/model;
- не включаем новые бизнес-отчеты для других отделов;
- не делаем UI для поиска карточек;
- не удаляем pilot EDO schedule до подтвержденного rollout.

## Риски

- резкий рост стоимости STT/LLM1;
- provider quota/rate limits на ночном окне;
- шумные или слишком общие LLM1-классификации;
- смешение company-wide upstream scope и manager_daily analysis scope;
- ошибки Bitrix/extension directory могут привести к пропуску сотрудников или
  включению технических пользователей.

## Рекомендуемая очередность

1. `PILOT-39A`: scope/dry-run/forecast.
2. `PILOT-39C`: жесткое разделение upstream и downstream scope.
3. `PILOT-39D`: бюджеты, квоты, мониторинг.
4. `PILOT-39B`: нормализация universal call card.
5. `PILOT-39E`: controlled rollout.

