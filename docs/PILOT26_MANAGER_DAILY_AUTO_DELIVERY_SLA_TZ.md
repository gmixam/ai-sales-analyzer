# PILOT-26: manager_daily auto-delivery до 10:00

Дата: 2026-06-16

## Контекст

Пилот переходит от полуавтоматического режима к ежедневной доставке отчетов
менеджерам и РОП без участия Codex/оператора в штатном случае.

Текущий runtime уже умеет:

- запускать split upstream по расписанию;
- строить `manager_daily` drafts;
- отправлять manager PDF по email вручную после review;
- отправлять РОП один общий email с PDF менеджеров;
- слать технические alerts в Telegram при blockers/failures.

Но активный `manager_daily` schedule все еще работает как review-first flow:

- `review_required=true`;
- scheduled branch создает draft и останавливается на review;
- business email delivery не происходит автоматически;
- SLA до 10:00 не контролируется как отдельный объект.

## Цель

Сделать боевой режим, при котором каждый рабочий день менеджеры ЭДО и РОП
получают письма с отчетами за предыдущий рабочий день до `10:00 Asia/Almaty`,
если отчеты готовы.

Если отчет не успел собраться до SLA, система не отправляет сырой или пустой
отчет, фиксирует причину задержки, шлет alert админу и автоматически отправляет
отчет позже, когда он станет готов.

## Принятое продуктовое решение

1. Время анализа переносится с `08:00` на `04:00 Asia/Almaty`.
2. Целевой SLA доставки менеджерам и РОП: до `10:00 Asia/Almaty`.
3. Если отчет готов после `10:00`, использовать **вариант А**:
   поздняя автоматическая отправка разрешена, но с фиксацией `sla_missed=true`
   и причиной задержки.
4. Менеджеру не отправлять неполный/сырой PDF только ради соблюдения времени.
5. РОП должен получать общий пакет только по фактически отправленным менеджерским
   отчетам. Если часть отчетов не готова, РОП получает либо частичный пакет с
   явным списком неготовых, либо отдельный status/update согласно реализации
   SLA-monitor.

## Целевой рабочий день

Все времена ниже в `Asia/Almaty`.

| Время | Событие | Ожидаемое поведение |
| --- | --- | --- |
| `00:00` | Call-processing upstream | Собрать звонки за предыдущий рабочий день, построить STT/segments/LLM1, сохранить costs/observability |
| `04:00` | Analysis/reporting schedule | Запустить LLM2/LLM3/report layer по готовым artifacts и подготовить/отправить manager reports в production auto-delivery режиме |
| `09:30` | Pre-SLA check | Проверить готовность и delivery по каждому менеджеру; отправить warning админу по неготовым/зависшим отчетам |
| `10:00` | Hard SLA check | Зафиксировать `sla_missed=true` по неготовым/недоставленным отчетам, отправить critical alert админу |
| После `10:00` | Late completion | Когда отчет стал готов, автоматически отправить менеджеру и РОП, пометить `sla_status=late` |

## Scope

В scope задачи входят:

- production auto-delivery branch для `manager_daily`;
- перенос active schedule на `04:00 Asia/Almaty`;
- поддержка `review_required=false` как боевого режима;
- SLA-monitor/checker до `10:00`;
- late delivery после SLA;
- observability/status fields для SLA и delivery;
- документация operating flow.

В scope не входят:

- weekly/monthly ROP reports;
- новый UI;
- ручной календарь праздников;
- изменение LLM2/LLM3 качества анализа;
- переоценка admission gate `llm2_admission_non_commercial_or_unusable`.

## Требования к scheduled delivery

### 1. Два режима schedule

`review_required=true`:

- текущий контрольный режим;
- schedule создает draft;
- business email не уходит без approve;
- подходит для тестов и спорных дней.

`review_required=false`:

- production auto-delivery;
- schedule после сборки отчета сразу запускает business email delivery;
- manager email отправляется только если отчет manager-facing safe;
- после успешной manager delivery РОП получает общий пакет.

### 2. Business email

Для auto-delivery должны быть выполнены условия:

- `business_email_enabled=true`;
- `review_required=false`;
- SMTP настроен;
- primary email менеджера resolved;
- manager-facing gates позволяют отправку;
- отчет относится строго к выбранному report day;
- PDF успешно построен.

Если условие не выполнено:

- менеджеру не отправлять;
- batch/draft получает structured status/reason;
- SLA-monitor использует этот reason для alert.

### 3. ROP daily package

ROP email должен отправляться на `MANAGER_DAILY_ROP_EMAIL_TO`
(`edo.rop@dogovor24.kz`) после manager delivery.

Поведение:

- включается через `MANAGER_DAILY_ROP_EMAIL_ENABLED=true`;
- содержит PDF только тех менеджеров, кому отчет реально отправлен;
- содержит текстовую сводку:
  - дата отчета;
  - кому отправлено;
  - кто не получил;
  - причина, если отчет не готов/заблокирован/поздний;
- если часть менеджеров не готова к `10:00`, РОП должен получить понятный статус,
  а поздние отчеты должны досылаться после готовности.

## SLA model

Добавить в batch/draft observability или отдельную устойчивую структуру:

- `sla_deadline_at`;
- `sla_precheck_at`;
- `sla_hardcheck_at`;
- `delivered_at`;
- `sla_status`:
  - `on_time`;
  - `late`;
  - `missed_pending`;
  - `blocked`;
  - `not_applicable`;
- `sla_missed`;
- `sla_missed_reason`;
- `late_delivery_at`;
- `manager_email_status`;
- `rop_email_status`;

Если нет миграции БД, допустимо first pass хранить эти поля в
`scheduled_report_batches.observability` и `scheduled_report_drafts.delivery`.

## SLA-monitor

Нужен отдельный технический checker, который можно запускать:

- по расписанию beat;
- вручную через CLI;
- из тестов.

Минимальные команды CLI:

```bash
python /app/report_scripts/scheduled_reporting_preflight.py sla-status \
  --date YYYY-MM-DD

python /app/report_scripts/scheduled_reporting_preflight.py sla-check \
  --date YYYY-MM-DD \
  --phase precheck

python /app/report_scripts/scheduled_reporting_preflight.py sla-check \
  --date YYYY-MM-DD \
  --phase hard
```

`sla-status` должен показать:

- список активных менеджеров schedule scope;
- есть ли calls за report day;
- есть ли upstream STT/LLM1;
- есть ли analysis;
- есть ли draft/PDF;
- manager email status;
- ROP email status;
- SLA status/reason.

`sla-check --phase precheck`:

- в `09:30` шлет warning alert админу, если отчет не готов или не доставлен;
- не отправляет сырой отчет.

`sla-check --phase hard`:

- в `10:00` фиксирует `sla_missed=true`;
- шлет critical alert админу;
- не запрещает late delivery.

## Late delivery

Если отчет был не готов до `10:00`, но позже стал готов:

- отправить менеджеру автоматически;
- отправить/обновить РОП-пакет или отправить РОПу late update;
- установить `sla_status=late`;
- сохранить `late_delivery_at`;
- в alert/observability указать причину задержки.

Важно: late delivery не должна создавать дубли, если отчет уже был доставлен.

## Рабочие дни

First pass:

- auto-delivery запускать по рабочим дням `Mon-Fri` в `Asia/Almaty`;
- если за предыдущий день нет звонков, отчет менеджеру не формировать;
- админу/observability показывать `no_calls_for_report_day`, а не failure.

Праздники:

- отдельный календарь праздников не вводить в first pass;
- если нужна точная праздничная логика, завести отдельную задачу после первых
  рабочих автодоставок.

## Изменения в коде

Ожидаемые зоны правок:

- `core/app/agents/calls/scheduled_reporting.py`
  - поддержать production branch при `review_required=false`;
  - не форсировать `run_report(... send_email=False)` в production режиме;
  - корректно выставлять batch/draft status после delivery;
  - сохранять SLA/delivery observability;
  - не создавать дубли late delivery.
- `core/app/agents/calls/reporting.py`
  - убедиться, что ROP bundle работает при auto-delivery;
  - сохранить частичные/late ROP summaries.
- `core/report_scripts/scheduled_reporting_preflight.py`
  - добавить `sla-status`;
  - добавить `sla-check`;
  - добавить безопасную команду проверки production schedule.
- `core/app/core_shared/workers/tasks.py`
  - если SLA-check запускается beat/task layer, добавить scheduled task.
- `docker-compose.yml` / env examples
  - отразить schedule/checker configuration, если нужны новые env.
- tests
  - добавить regression tests для review и production режимов.

## Настройки runtime

Целевое состояние после внедрения:

- call-processing upstream: `00:00 Asia/Almaty`;
- manager_daily analysis/reporting: `04:00 Asia/Almaty`;
- active production schedule:
  - `enabled=true`;
  - `business_email_enabled=true`;
  - `review_required=false`;
  - `report_period_rule=previous_day`;
  - `timezone=Asia/Almaty`;
  - `start_time=04:00`;
- ROP:
  - `MANAGER_DAILY_ROP_EMAIL_ENABLED=true`;
  - `MANAGER_DAILY_ROP_EMAIL_TO=edo.rop@dogovor24.kz`;
- alerts:
  - Telegram/admin alert включен для warning/error;
  - warning at precheck;
  - critical at hard SLA.

## Acceptance criteria

1. В review режиме (`review_required=true`) поведение не меняется:
   - draft создается;
   - manager email не уходит без approve.
2. В production режиме (`review_required=false`) готовый отчет:
   - строится;
   - отправляется менеджеру;
   - попадает в ROP daily package;
   - получает `sla_status=on_time`, если доставлен до `10:00`.
3. Если отчет не готов к `09:30`:
   - manager email не уходит;
   - warning alert отправлен админу;
   - причина видна в `sla-status`.
4. Если отчет не готов к `10:00`:
   - `sla_missed=true`;
   - `sla_status=missed_pending` или `blocked`;
   - critical alert отправлен админу.
5. Если отчет готов после `10:00`:
   - он автоматически отправляется менеджеру;
   - РОП получает late update/package;
   - `sla_status=late`;
   - дублей доставки нет.
6. Если у менеджера нет звонков за report day:
   - manager email не отправляется;
   - статус не считается технической ошибкой;
   - в observability причина `no_calls_for_report_day`.
7. Active schedule после rollout стоит на `04:00 Asia/Almaty`.

## Test plan

Focused unit/integration tests:

- review schedule не отправляет email;
- production schedule отправляет email при готовом отчете;
- production schedule не отправляет email при missing PDF/recipient/gate;
- ROP package содержит только delivered manager reports;
- precheck создает warning по pending/blocked manager day;
- hard check ставит `sla_missed=true`;
- late delivery отправляет один раз и не дублирует;
- previous-day logic остается strict;
- no-audio CDR не ломает SLA и не требует анализа.

Runtime smoke:

1. Создать временный controlled schedule на один manager/day:
   - `review_required=false`;
   - `business_email_enabled=true`;
   - test SMTP/real approved recipient.
2. Запустить через `scan-due`.
3. Проверить:
   - manager email sent;
   - ROP email sent;
   - batch/draft statuses;
   - `sla-status`;
   - отсутствие duplicate batch/draft.

## Rollout plan

1. Реализовать code path и tests.
2. Прогнать controlled production schedule на одном менеджере.
3. Прогнать controlled production schedule на 2-3 менеджерах без ожидания 04:00.
4. Перевести active schedule:
   - `start_time=04:00`;
   - `review_required=false`;
   - `business_email_enabled=true`.
5. На первом настоящем рабочем дне контролировать:
   - `00:00` upstream;
   - `04:00` analysis/reporting;
   - `09:30` pre-SLA;
   - `10:00` hard SLA;
   - delivery manager/ROP.

## Вопросы не для first pass

- Нужен ли отдельный официальный календарь праздников Казахстана.
- Нужно ли отправлять РОПу partial package до `10:00`, если часть отчетов еще
  собирается, или ждать late updates.
- Нужно ли менеджеру явно писать в email, что отчет отправлен позже SLA.
