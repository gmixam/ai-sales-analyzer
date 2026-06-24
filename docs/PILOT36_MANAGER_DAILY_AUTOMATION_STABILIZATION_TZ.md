# PILOT-36: stabilization of automatic manager_daily production flow

Дата: 2026-06-19

## Контекст

Live-аудит production-запуска за `2026-06-18` показал, что расписание само
стартует, но дневной процесс не всегда приходит к чистому финальному состоянию.

Подтвержденные факты:

- `call_processing` в `00:00 Asia/Almaty` успешно забрал звонки и подготовил
  STT/LLM1 artifacts;
- `analysis` schedule в `04:00 Asia/Almaty` стартовал;
- вместо ожидаемых `4` manager_daily batches за день было создано `16`;
- осталось `5` open blockers: `4` по Алишеру и `1` по Тимуру;
- у Алишера email есть в `managers.email`, но delivery получил
  `primary_email=None` и поставил `missing_recipient`;
- по Толегену есть delivered batch, но более поздние failed duplicates мешают
  `sla-status` выбрать правильный финальный результат;
- SLA precheck/hardcheck в `09:30/10:00 Asia/Almaty` были отправлены beat, но
  worker упал с `ModuleNotFoundError: report_scripts`.

Главный вывод: проблема не в том, что расписание не запускается. Проблема в
устойчивости выполнения после старта: дубли, финальные статусы, доставка,
SLA-check и ROP summary.

## Общий принцип работы

PILOT-36 выполняется не одной большой правкой, а четырьмя последовательными
подзадачами.

Перед каждой подзадачей агент должен:

1. подготовить короткое мини-ТЗ;
2. получить утверждение оператора;
3. реализовать только утвержденный объем;
4. выполнить focused verification;
5. обновить `docs/PILOT_BACKLOG.md`, `docs/PROGRESS.md` и при необходимости
   этот файл.

Без отдельного утверждения не запускать полный production pipeline и не
отправлять бизнес-письма менеджерам.

## Подзадачи

### PILOT-36A - Защита запуска и SLA

Статус: `implemented_first_pass`

Цель: один scheduled manager-day не должен запускаться параллельно несколько
раз, а SLA-check должен работать без Codex.

Что требуется разобрать и реализовать после утверждения мини-ТЗ:

- lock / idempotency guard на уровне `schedule_id + planned_for +
  manager_id/report_date`;
- исправить scheduled SLA task import, чтобы
  `calls.manager_daily_sla_precheck` и `calls.manager_daily_sla_hardcheck`
  стабильно вызывали `scheduled_reporting_preflight.sla_check`;
- исправить выбор финального batch в `sla-status`: delivered batch должен иметь
  приоритет над поздним failed duplicate типа `no_candidate_all_reported`;
- не менять смысловую аналитику LLM2/LLM3 и не запускать новые STT/LLM без
  необходимости.

Ожидаемая проверка:

- focused tests для scheduled reporting / preflight / SLA;
- ручной запуск SLA-check task или CLI в контейнере без import error;
- controlled scan не создает повторные batches на один manager-day;
- `sla-status --date 2026-06-18` выбирает корректный delivered статус для
  Толегена.

Результат first pass 2026-06-19:

- добавлен PostgreSQL advisory transaction lock перед созданием `manager_daily`
  batch по ключу `schedule_id + planned_for + manager_id/report_date`;
- если lock занят, scan не запускает report pipeline, не создает рабочий batch
  и не сдвигает schedule как успешно обработанный;
- scheduled SLA-check получил устойчивый loader для
  `scheduled_reporting_preflight.sla_check` вместо хрупкой зависимости от
  текущего `sys.path`;
- `sla-status` выбирает главный manager-day batch по приоритету:
  delivered/manager-email-sent важнее поздних failed duplicates;
- дубли не скрываются: кандидаты сохраняются в `diagnostics.batch_candidates`;
- проверено: `py_compile`, `git diff --check`, focused docker pytest
  `66 passed, 1 skipped, 5 subtests passed`, live `sla-status` за
  `2026-06-18` выбирает delivered batch для Тимура и Толегена.

### PILOT-36B - Recovery текущего состояния за 2026-06-18

Статус: `implemented_first_pass`

Цель: убрать текущие зависшие open blockers и сделать состояние дня понятным
для следующего auto-run.

Что требуется разобрать и реализовать после утверждения мини-ТЗ:

- выбрать основной batch по каждому менеджеру за `2026-06-18`;
- лишние open `review_required` batches перевести в безопасный terminal/recovery
  статус, предпочтительно `paused`, с причиной duplicate/recovery;
- не удалять исторические rows из БД;
- проверить, что `open-batches` больше не показывает blocker за `2026-06-18`;
- зафиксировать recovery-команду и порядок проверки.

Ожидаемая проверка:

- `scheduled_reporting_preflight.py open-batches`;
- `scheduled_reporting_preflight.py sla-status --date 2026-06-18`;
- отсутствие блокировки следующего `manager_daily` дня старыми rows.

Результат first pass 2026-06-19:

- read-only карта за `2026-06-18` подтвердила `16` batches: основные
  delivered batches Тимура `81930100-16e6-428e-baaa-0768eb3d773a` и Толегена
  `e7a339db-fd95-4f68-95e8-532fa3c9ed70`; Илья остался no-calls /
  `not_applicable`; Алишер остался диагностируемым `missing_recipient` с PDF;
- через dry-run-first recovery в `paused` переведены только open blockers:
  `7af29112-6550-48d2-a5e8-97a9ea5e2e68`,
  `7ce8fd21-19e1-4f5c-91bf-e7e9098db3c3`,
  `c4bce3f2-8b42-4530-afef-a2387b9aadc7`,
  `ccf1f45d-6fdc-44c7-bc23-4acfbab25556`,
  `54109056-16c9-48ee-a14a-75ed62cde8bd`;
- delivered batches и failed historical duplicates не менялись, rows не
  удалялись;
- проверено: `open-batches --date 2026-06-18` вернул `0` open batches и `0`
  blockers; `sla-status --date 2026-06-18` показывает counts
  `blocked=1`, `not_applicable=1`, `on_time=2`, где Алишер остается
  `blocked/missing_recipient` на paused diagnostic batch, Илья
  `not_applicable`, Тимур и Толеген `delivered/on_time`.

### PILOT-36C - Доставка и production statuses

Статус: `implemented_first_pass`

Цель: production batch не должен зависать в `review_required`, а доставка
должна использовать email менеджера из актуальной карточки.

#### Контекст проблемы

После recovery `PILOT-36B` открытых batch-блокеров за `2026-06-18` не осталось,
но кейс Алишера показывает дефект production delivery:

- в `managers.email` у Алишера есть `g.alisher@dogovor24.kz`;
- PDF отчета был собран;
- delivery при этом получил `primary_email=None`;
- batch/draft ушли в `missing_recipient` / `review_required` вместо понятного
  production terminal status.

Это значит, что проблема не в наличии email как данных, а в цепочке передачи
получателя из manager scope в delivery layer.

#### Цель этапа

Production `manager_daily` должен по каждому менеджеру завершаться одним
понятным состоянием:

- отчет доставлен;
- звонков нет;
- отчет не готов из-за анализа;
- нет email получателя;
- ошибка отправки;
- batch поставлен на паузу как recovery/duplicate.

При `review_required=false` production flow не должен оставлять batch/draft в
ручном статусе `review_required` как финальном результате.

#### Scope реализации

1. Recipient resolver
   - Найти, где формируется `primary_email` для manager delivery.
   - Проверить цепочку:
     `scheduled manager scope -> manager entity -> report payload -> delivery attempt -> draft/batch observability`.
   - Исправить дефект, при котором `managers.email` заполнен, но delivery
     получает `primary_email=None`.
   - Приоритет источника email для manager_daily production:
     `manager.email` из БД / manager entity, без ручного парсинга ФИО или
     смысловых данных отчета.
   - Если email пустой, явно фиксировать `missing_recipient` с manager id/name.

2. Production final statuses
   - Для production schedule (`review_required=false`,
     `business_email_enabled=true`) не использовать `review_required` как
     финальный статус успешной сборки.
   - Нормализовать статусы batch/draft/observability:
     - `delivered` - PDF сформирован и email менеджеру отправлен;
     - `no_calls` / `not_applicable` - за день нет звонков для отчета;
     - `missing_recipient` - PDF может быть готов, но нет email получателя;
     - `analysis_not_ready` - звонки есть, но не хватает анализа для
       полноценного отчета;
     - `delivery_failed` - получатель есть, но отправка упала технически;
     - `blocked` - требуется операторское вмешательство;
     - `paused` / `duplicate_paused` - recovery/duplicate batch не должен
       блокировать новые дни.
   - Сохранить совместимость со старым review flow: если schedule реально
     `review_required=true`, старый ручной статус допускается.

3. SLA / diagnostics visibility
   - `sla-status` должен показывать не только общий blocked-status, но и
     конкретную причину: `missing_recipient`, `analysis_not_ready`,
     `delivery_failed`, `no_calls`.
   - Для cases с PDF ready, но без отправки, статус должен быть понятным:
     `missing_recipient`, а не "отчет не собрался".
   - В diagnostics должны быть manager id/name, resolved email или причина,
     почему email не найден.

4. Recovery compatibility
   - Не менять уже доставленные batches Тимура/Толегена за `2026-06-18`.
   - Не удалять paused recovery rows.
   - Не запускать STT/LLM/report pipeline в рамках реализации без отдельного
     утверждения.

#### Не входит в этап

- отправка реальных писем менеджерам;
- полный дневной production прогон;
- ROP digest;
- изменение LLM/STT логики;
- изменение содержания PDF отчета;
- чистка исторических batch rows через SQL вручную.

#### Проверка результата

Минимальная verification:

- focused unit/integration tests на recipient resolver:
  - заполненный `managers.email` попадает в delivery attempt;
  - пустой email дает `missing_recipient`;
  - production mode не оставляет финальный `review_required`;
  - review mode продолжает поддерживать `review_required`.
- focused tests на status derivation:
  - delivered email -> batch/draft `delivered`;
  - PDF ready + no email -> `missing_recipient`;
  - technical send exception -> `delivery_failed`;
  - no calls -> `no_calls` / `not_applicable`.
- dry-run/read-only проверка кейса Алишера за `2026-06-18`: система должна
  видеть `g.alisher@dogovor24.kz` как recipient candidate.
- `git diff --check`.
- `python3 -m py_compile` по измененным Python-файлам.
- focused pytest для scheduled reporting / preflight / delivery text.

#### Критерии приемки

- Алишер с `managers.email=g.alisher@dogovor24.kz` больше не классифицируется
  как `missing_recipient` на этапе recipient resolve.
- Production batch при `review_required=false` не остается в финальном
  `review_required`.
- Operator/SLA output дает короткую понятную причину недоставки.
- Старый manual review flow не сломан.
- Новых production-писем в рамках этой задачи не отправлено.

#### Результат first pass 2026-06-19

Реализовано:

- recipient resolver для `manager_daily` больше не зависит только от
  `ReportArtifact.manager`: если artifact пришел без manager entity, resolver
  добирает `Manager.email` из БД по единственному manager id из payload/header
  или interaction artifacts;
- production delivery assessment больше не использует `review_required` как
  финальный статус для blocked outcomes при `review_required=false` и
  `business_email_enabled=true`;
- production observability нормализует причины:
  `missing_recipient`, `analysis_not_ready`, `delivery_failed`,
  `no_calls_for_report_day` / `not_applicable`, `delivered/on_time|late`;
- draft/batch observability теперь хранит `primary_email`, `cc_emails` и
  `recipient_resolve_status`, чтобы отличать "email найден, но отправка упала"
  от "email не найден";
- `sla-status` сохраняет `manager_card_email` отдельно от delivery transport
  status, поэтому historical case Алишера виден как:
  `manager_card_email=g.alisher@dogovor24.kz`, delivery `primary_email=None`,
  PDF ready, reason `missing_recipient`.

Проверено:

- `python3 -m py_compile` по измененным Python-файлам;
- docker focused pytest:
  `/app/tests/test_scheduled_reporting.py /app/tests/test_scheduled_reporting_preflight.py`
  -> `49 passed`;
- `git diff --check`;
- read-only live diagnostic:
  `sla-status --date 2026-06-18` -> counts `blocked=1`,
  `not_applicable=1`, `on_time=2`; Алишер диагностируется как historical
  `missing_recipient` с PDF ready и видимым `manager_card_email`.

Не выполнялось: реальные письма/Telegram, STT/LLM/report generation,
production pipeline, ручные SQL-изменения live data.

### PILOT-36D - ROP digest, partial readiness and concise summaries

Статус: `implemented_first_pass`

Дата реализации first pass: 2026-06-24

Цель: РОП каждый день получает один понятный email со статусами всех менеджеров,
а оператор получает короткие уведомления без raw JSON.

Что реализовано:

- scheduled `manager_daily` больше не отправляет per-manager ROP-copy из
  каждого одиночного `run_report`; эта отправка помечается как
  `deferred_to_scheduled_rop_digest`;
- после завершения общего scheduled manager_daily scan собирается один ROP
  digest по всем менеджерам scope;
- в digest есть строка по каждому менеджеру: `delivered`, `no_calls`,
  `not_ready`, `missing_recipient`, `delivery_failed`, `blocked`,
  `will_retry`, `review_required` или `already_reported`;
- к письму прикладываются все runtime PDF тех менеджеров, чей manager email
  реально доставлен;
- отсутствие отчета по одному менеджеру не блокирует digest по остальным;
- если upstream еще ожидается и есть hourly retry, ROP digest не отправляется
  промежуточно; после финального состояния digest фиксируется в
  `scheduled_rop_daily_digest`;
- digest summary сохраняется в `batch.observability` и `batch.diagnostics`
  без binary PDF content.

Проверка:

- `git diff --check`;
- `python3 -m py_compile core/app/agents/calls/reporting.py
  core/app/agents/calls/scheduled_reporting.py core/tests/test_scheduled_reporting.py`;
- docker focused pytest `/app/tests/test_scheduled_reporting.py` ->
  `29 passed, 5 subtests passed`;
- docker focused pytest `/app/tests/test_manual_reporting.py -k
  "manager_daily_rop_bundle or render_report_email_uses_short_body"` ->
  `3 passed, 258 deselected`.

Не выполнялось: реальные ROP/manager email sends, production schedule restart,
STT/LLM/report generation.

### PILOT-36E - Upstream readiness handoff, retry and analysis resume

Статус: `implemented_first_pass`

Дата постановки: 2026-06-24

#### Контекст проблемы

Восстановление report date `2026-06-23` показало новый системный дефект
автоматического контура:

- `call_processing` может корректно добрать STT/LLM1 за день, но занимает
  дольше `CALL_PROCESSING_CLIENT_TIMEOUT_SEC=180`;
- `analysis/build_missing_and_report` синхронно вызывает
  `call_processing ensure` и падает с
  `call_processing_client_read_timeout: operation=ensure_processed_calls_async
  timeout_sec=180`;
- после ручного upstream ensure за `2026-06-23` scope стал `ready`
  (`artifacts_missing=0`, построено `29` STT и `30` LLM1);
- затем `report_from_ready_data_only` смог отправить PDF в Telegram, но не
  построил недостающие LLM2-анализы: он только переиспользовал уже готовые
  `39` analyses и оставил `104` missing analyses;
- менеджерские email были заблокированы delivery gate, потому что часть
  отчетов осталась `skip_accumulate` / `signal_report`, а не полноценным
  production-delivery результатом;
- Тимур и Толеген были отправлены на email только ручным override после
  рендера PDF из payload, что не должно требоваться в автоматическом режиме.

Главный вывод: проблема не в самих STT/LLM1 и не в SMTP. Проблема в связке
`call_processing -> analysis`: analysis одновременно пытается ждать долгий
upstream, принимать решение о готовности, строить LLM2 и отправлять отчет.

#### Цель этапа

Сделать production `manager_daily` устойчивым к долгому upstream:

1. `analysis` не должен падать финально только потому, что synchronous
   `call_processing ensure` не уложился в `180 sec`.
2. Если upstream за день уже готов, `analysis` должен уметь продолжить с шага
   LLM2/Report без повторного полного call-processing ensure.
3. Если upstream еще не готов, система должна поставить понятный статус
   `waiting_upstream` / `upstream_not_ready` и повторить попытку до delivery
   deadline, а не создавать failed manager-facing batch.
4. Доставка менеджеру должна происходить автоматически, когда отчет стал
   допустимым для manager-facing delivery, без ручного override.

#### Scope реализации

1. Единый scope handoff
   - Вынести/переиспользовать единый builder manager_daily upstream scope:
     `department_id + manager_ids + report_date + source`.
   - `call_processing` и `analysis` должны использовать один и тот же scope и
     `scope_hash` для production day.
   - В observability сохранять:
     - `call_processing_run_id`;
     - `call_processing_scope_hash`;
     - `call_processing_status`;
     - `artifacts_ready`;
     - `artifacts_missing`;
     - `last_finished_at` / `last_seen_at`.

2. Не блокировать analysis на долгом synchronous ensure
   - Для scheduled production `manager_daily` запретить зависимость от
     долгого HTTP read в `ensure_processed_calls_async`.
   - Перед запуском нового ensure analysis должен сначала проверить последний
     upstream run для точного scope/date.
   - Если upstream `ready`, analysis сразу переходит к LLM2/report layer.
   - Если upstream `running`, `partial`, `blocked` или отсутствует, analysis
     не должен создавать финальный failed report batch с причиной timeout.
     Вместо этого создать/обновить diagnostic state:
     `waiting_upstream`, `upstream_partial`, `upstream_blocked` или
     `upstream_missing`.
   - Если нужен новый ensure, запускать его как отдельный upstream job или
     через короткий accepted/run-id path; не ждать весь full-day ensure внутри
     analysis HTTP call.

3. Analysis resume после готового STT/LLM1
   - Добавить режим/ветку внутри `build_missing_and_report`:
     `skip_upstream_ensure_if_ready=true`.
   - Если call-processing artifacts уже `ready`, но LLM2 analyses отсутствуют,
     runner должен строить недостающие LLM2-анализы, а не переходить в
     ready-only reuse.
   - Для кейса `2026-06-23` ожидаемое поведение:
     upstream ready -> LLM2 строится по звонкам с готовыми STT/LLM1 ->
     Report Layer формирует deliverable/signal/skip status -> допустимые
     менеджерские отчеты отправляются штатно.

4. Retry до delivery deadline
   - Если в `04:00 Asia/Almaty` upstream еще не готов, scheduled flow должен
     запланировать retry/checkpoint **раз в час** до утреннего cutoff:
     `05:00`, `06:00`, `07:00`, `08:00`, `09:00 Asia/Almaty`.
   - Если на любой hourly-проверке upstream уже готов, analysis должен сразу
     продолжить с LLM2/report/delivery, не дожидаясь следующего часа.
   - Если к `09:00 Asia/Almaty` upstream все еще не готов, manager-day получает
     понятный статус `upstream_not_ready_before_deadline`, а в `10:00`
     SLA-контроль сообщает итог по доставке/недоставке.
   - Retry должен быть idempotent:
     - не создавать дубли batch/draft на тот же manager-day;
     - обновлять существующий diagnostic/pending state;
     - после готовности продолжать с LLM2/report.
   - После cutoff система должна дать понятный terminal статус:
     `upstream_not_ready_before_deadline`, `analysis_not_ready`,
     `delivery_failed` или `not_applicable`.

5. Delivery gate без ручного override
   - Не ослаблять manager-facing gate: `skip_accumulate` не отправлять
     менеджеру как обычный отчет.
   - `signal_report` / `full_report`, если они признаны допустимыми текущими
     правилами, должны отправляться бизнес-email автоматически в production
     mode.
   - Если отчет отправлен только в Telegram/operator preview, причина должна
     быть явной:
     `manager_email_skipped_due_to_readiness`,
     `missing_recipient`, `delivery_failed`, `business_email_disabled`.
   - Ручной override PDF/email не должен быть штатным способом восстановления
     после нормального upstream-ready состояния.

6. Короткая диагностика и alert
   - В operator alert не выводить raw JSON.
   - Для такого класса проблем alert должен отвечать на 4 вопроса:
     - какая дата;
     - какие менеджеры затронуты;
     - где остановилось: upstream / LLM2 / report / delivery;
     - что система сделает дальше: retry / ждет upstream / нужна ручная
       проверка.

#### Не входит в этап

- изменение смысла LLM2/LLM3 анализа;
- изменение STT/LLM1 промптов или провайдеров;
- ослабление правил `skip_accumulate`;
- weekly/monthly ROP reports;
- UI;
- ручная SQL-чистка исторических rows;
- повторная отправка исторических email за `2026-06-23` как часть тестов.

#### Acceptance criteria

- `analysis/build_missing_and_report` не падает финально из-за
  `call_processing_client_read_timeout=180`, если upstream еще выполняется.
- Если upstream scope уже `ready`, analysis не запускает долгий full ensure
  повторно и строит недостающие LLM2 analyses.
- Для production schedule появляется понятный pending/retry статус до cutoff.
- Retry не создает дубли batches/drafts для одного manager-day.
- Manager email отправляется штатно для `signal_report` / `full_report`, если
  recipient resolved и business email включен.
- `skip_accumulate` остается неотправляемым менеджеру.
- `sla-status` и operator alert показывают конкретную причину:
  `waiting_upstream`, `upstream_not_ready_before_deadline`,
  `analysis_missing_after_upstream_ready`, `manager_email_skipped_due_to_readiness`
  и т.п.

#### Verification plan

1. Unit/focused tests
   - slow call-processing ensure > 180 sec не переводит manager-day в финальный
     failed, а дает `waiting_upstream`;
   - upstream `ready` + missing LLM2 analyses -> `build_missing_and_report`
     строит LLM2 без повторного full ensure;
   - retry по тому же manager-day не создает duplicate batches;
   - `skip_accumulate` не отправляется менеджеру;
   - `signal_report` / `full_report` с resolved email отправляется;
   - alert summary не содержит raw JSON и содержит manager/date/reason/action.

2. Regression fixture по сценарию `2026-06-23`
   - upstream artifacts ready;
   - часть LLM2 analyses missing;
   - runner продолжает с LLM2/report;
   - Алишер остается not delivered при `skip_accumulate`;
   - Тимур/Толеген проходят штатную delivery ветку без ручного override.

3. Runtime checks без реальной бизнес-рассылки
   - dry-run / preview на controlled date;
   - `sla-status --date <date>` показывает pending/retry/final reason;
   - `git diff --check`;
   - `python3 -m py_compile` по измененным Python-файлам;
   - focused pytest:
     `/app/tests/test_scheduled_reporting.py`,
     `/app/tests/test_scheduled_reporting_preflight.py`,
     `/app/tests/test_call_processing_client.py`,
     релевантные tests для manual reporting external_service.

#### Рекомендуемый порядок выполнения

1. Сначала реализовать read-only upstream readiness lookup по exact scope/date.
2. Затем добавить analysis resume path: upstream ready -> build missing LLM2.
3. Затем добавить pending/retry statuses для scheduled production flow.
4. Затем обновить SLA/alerts.
5. Только после focused verification делать controlled report-day run без
   бизнес-доставки.
6. После проверки оператором включать production delivery.

#### Результат first pass 2026-06-24

Реализовано:

- добавлен read-only upstream readiness lookup по exact `ProcessingScope` /
  `scope_hash`: local client, HTTP client и API
  `GET /call-processing/runs/latest`;
- `build_missing_and_report` в external-service mode сначала проверяет latest
  upstream run; если upstream уже `ready` и `artifacts_missing=0`, полный
  `ensure` не запускается повторно, а flow продолжает build path, где могут
  строиться missing LLM2 analyses;
- если upstream `running`, `partial`, `blocked`, `failed` или отсутствует,
  production analysis возвращает понятный pending status:
  `waiting_upstream`, `upstream_partial`, `upstream_blocked`,
  `upstream_missing` вместо финального падения по
  `call_processing_client_read_timeout=180`;
- scheduled manager-day создает/переиспользует pending batch без draft и
  планирует hourly retry на `05:00`, `06:00`, `07:00`, `08:00`,
  `09:00 Asia/Almaty`;
- если к `09:00 Asia/Almaty` upstream не готов, batch получает terminal reason
  `upstream_not_ready_before_deadline`;
- delivery gate не ослаблялся: `skip_accumulate` не отправляется менеджеру,
  `signal_report/full_report` остаются в штатном production delivery path при
  resolved email.

Проверено:

- `python3 -m py_compile` по измененным Python-файлам;
- `git diff --check`;
- docker focused pytest:
  `/app/tests/test_call_processing_client.py`,
  `/app/tests/test_call_processing_api.py`,
  `/app/tests/test_call_processing_reporting_integration.py`,
  `/app/tests/test_scheduled_reporting.py`,
  `/app/tests/test_scheduled_reporting_preflight.py`
  -> `82 passed, 5 subtests passed`.

Не выполнялось: реальная business delivery и полный production pipeline.
Следующий шаг перед production-наблюдением: controlled no-business-delivery
проверка на ближайшем report day или ожидание следующего расписания с
мониторингом `waiting_upstream` / retry statuses.

## Не входит в PILOT-36

- изменение LLM2/LLM3 смысловых промптов;
- изменение STT/LLM1 pipeline;
- weekly/monthly ROP reports;
- крупный refactor reporting modules;
- UI.

## Связанные документы

- `docs/PILOT_BACKLOG.md`
- `docs/PILOT26_MANAGER_DAILY_AUTO_DELIVERY_SLA_TZ.md`
- `docs/PILOT27_AUTOMATIC_SLA_CHECK_TZ.md`
- `docs/PILOT33_MANAGER_DAILY_OPEN_BATCH_GUARD_TZ.md`
- `docs/PILOT34_DUPLICATE_OPEN_BATCH_DIAGNOSTICS_TZ.md`
- `docs/PILOT35_MANAGER_DAILY_SILENT_SKIP_GUARD_TZ.md`
- `docs/PILOT28_OPERATOR_ALERT_SUMMARY_TZ.md`
