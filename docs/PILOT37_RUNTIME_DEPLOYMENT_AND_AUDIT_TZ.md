# PILOT-37: runtime deployment gate and post-run hardening

Дата постановки: 2026-06-25

## Контекст

Автопрогон за `2026-06-24` показал два системных риска:

- код `PILOT-36D/36E` был закоммичен, но `analysis_worker` / `analysis_beat`
  продолжили работать на старом импортированном runtime-коде до restart;
- Алишер не дошел до LLM2/report, хотя STT и LLM1 были готовы:
  `call_processing_client_read_timeout: operation=get_processed_artifacts timeout_sec=180`;
- РОП получил старые per-manager copies по Тимуру и Толегену, но не новый
  единый `scheduled_rop_daily_digest`, потому что scheduled runtime не взял
  новый код.

Цель `PILOT-37`: сделать так, чтобы такие проблемы выявлялись до или сразу
после автозапуска, а не вручную в чате после провала.

## Очередность задач

1. `PILOT-37A` - runtime restart / code-version gate.
2. `PILOT-37B` - recovery report date `2026-06-24`, добрать Алишера и
   отправить корректный ROP digest.
3. `PILOT-37C` - artifact retrieval hardening для
   `get_processed_artifacts timeout_sec=180`.
4. `PILOT-37D` - ROP digest SLA check.
5. `PILOT-37E` - automatic post-run audit.

---

## PILOT-37A - Runtime restart / code-version gate

Статус: `implemented`

### Цель

После каждого commit/restart оператор и SLA-check должны видеть, какой код
фактически загружен в API/worker/beat. Если service runtime не соответствует
ожидаемому commit или не содержит обязательные feature markers, система должна
показать это явно до следующего scheduled run.

### Что сделать

#### 1. Runtime identity helper

Добавить общий helper, который возвращает runtime identity:

- `service`: значение `APP_SERVICE` / `settings.app_service`;
- `process_type`: api / worker / beat / unknown, насколько это можно определить
  из env или argv;
- `pid`;
- `started_at_utc`: фиксируется при импорте helper-модуля;
- `uptime_sec`;
- `git_commit`: текущий commit из `git rev-parse HEAD` или env fallback;
- `git_branch`: текущая ветка, если доступна;
- `git_dirty`: best-effort bool;
- `code_markers`: проверка наличия ключевых runtime markers:
  - `scheduled_rop_daily_digest`;
  - `deferred_to_scheduled_rop_digest`;
  - latest upstream/readiness handoff marker для `PILOT-36E`.

Важно:

- helper не должен падать, если `.git` недоступен внутри container;
- если commit определить нельзя, вернуть `unknown`, а не exception;
- не читать секреты и не выводить env целиком.

#### 2. API endpoint

Расширить lightweight status endpoint:

- `GET /status` должен возвращать не только `{"service": "ok"}`, но и
  `runtime`;
- формат должен быть стабильным и JSON-safe.

Минимальный пример:

```json
{
  "service": "ok",
  "runtime": {
    "service": "analysis",
    "process_type": "api",
    "git_commit": "3f22be2...",
    "started_at_utc": "2026-06-25T...",
    "uptime_sec": 123,
    "code_markers": {
      "scheduled_rop_daily_digest": true,
      "deferred_to_scheduled_rop_digest": true,
      "latest_upstream_handoff": true
    }
  }
}
```

#### 3. Celery runtime probe task

Добавить safe Celery task, который возвращает runtime identity worker-а:

- task name: например `runtime.identity`;
- task не должен запускать STT/LLM/report;
- task должен быть routable на analysis/call_processing queues через existing
  Celery routing helpers;
- результат должен позволять Codex/operator проверить, какой код реально
  загружен в `analysis_worker`.

#### 4. Preflight command

Добавить CLI/preflight check, чтобы Codex мог выполнить одну команду и увидеть:

- API runtime identity;
- worker runtime identity через Celery task;
- expected commit = repo HEAD или явно переданный `--expected-commit`;
- статус:
  - `ok`, если runtime commit совпадает и markers true;
  - `warning`, если commit unknown, но markers true;
  - `blocked`, если commit mismatch или обязательный marker false.

Подходящие места:

- существующий `scripts/scheduled_reporting_preflight.py` /
  `core/report_scripts/scheduled_reporting_preflight.py`; или
- новый отдельный script, если так безопаснее.

#### 5. Operator alert integration

Не отправлять alert на каждый status-запрос. Но если preflight запускается в
режиме check и видит `blocked`, он должен вернуть короткий человекочитаемый
summary:

- что не так;
- какой сервис затронут;
- что сделать: restart конкретных services.

Автоотправку email/Telegram в рамках `37A` можно не включать, если нет
готового безопасного места. Главное - структурированный result для Codex и
SLA-check.

### Не входит в 37A

- не восстанавливать Алишера за `2026-06-24`;
- не менять LLM2/report semantics;
- не увеличивать timeout;
- не менять ROP digest logic;
- не запускать billable pipeline.

### Проверка

Минимальные проверки:

- `python3 -m py_compile` по измененным Python-файлам;
- focused tests для runtime identity helper/status endpoint/task/preflight;
- `docker compose exec -T api python ...runtime-status...` показывает
  текущий API/runtime commit;
- `docker compose exec -T api python ...runtime-status... --expected-commit $(git rev-parse HEAD)`
  возвращает `ok` после restart или `blocked` до restart, если worker старый;
- task `runtime.identity` не запускает billable actions.

### Критерий готовности

Задача считается готовой, когда Codex может одной командой ответить:

- какой commit загружен в `analysis_api`;
- какой commit загружен в `analysis_worker`;
- есть ли в runtime markers `PILOT-36D/36E`;
- нужен ли restart перед следующим scheduled run.

---

## PILOT-37B - Recovery 2026-06-24

Статус: `completed_operational_recovery_2026-06-25`

### Цель

Восстановить report date `2026-06-24` после внедрения runtime gate:

- применить новый код в `analysis_api` / `analysis_worker` / `analysis_beat`;
- добрать Алишера без повторной STT/LLM1, потому что upstream уже готов
  (`11/11` transcript, `11/11` transcript_segments, `11/11` LLM1);
- сформировать и отправить отчет Алишеру;
- отправить РОПу корректную единую сводку по дню или, если автоматический
  digest нельзя безопасно replay-нуть, зафиксировать controlled manual ROP
  recovery summary.

### Текущий факт по 2026-06-24

- Алишер: `17` звонков, `11` с аудио, STT/LLM1 ready, LLM2/report missing.
- Тимур: report delivered, ROP old per-manager copy sent.
- Толеген: report delivered, ROP old per-manager copy sent.
- Илья: no-calls / `not_applicable`.
- Open batches: `0`.
- Причина провала Алишера:
  `call_processing_client_read_timeout: operation=get_processed_artifacts timeout_sec=180`.
- Новый `scheduled_rop_daily_digest` отсутствует, потому что runtime до restart
  работал старым импортированным кодом.

### Что сделать

#### 1. Pre-restart gate

Запустить `runtime-status` до restart и сохранить результат в комментарии /
operator notes:

- ожидаемый статус: `blocked`;
- ожидаемые причины: API status без `runtime`, worker `NotRegistered:
  runtime.identity`.

#### 2. Restart analysis runtime

Перезапустить только analysis side:

- `analysis_api`;
- `analysis_worker`;
- `analysis_beat`.

Не перезапускать call-processing без необходимости.

#### 3. Post-restart gate

Запустить `runtime-status` после restart:

- обязательные markers:
  - `scheduled_rop_daily_digest=true`;
  - `deferred_to_scheduled_rop_digest=true`;
  - `latest_upstream_handoff=true`;
- статус должен быть `ok` или `warning`, если commit внутри container
  `unknown`, но markers true;
- если статус `blocked`, не запускать recovery.

#### 4. Recovery Алишера

Добрать только Алишера за `2026-06-24`.

Правила:

- не запускать full company/day STT повторно;
- не пересобирать Тимура/Толегена без необходимости;
- использовать готовые call-processing artifacts;
- режим: `build_missing_and_report` или ближайший существующий recovery-safe
  path, который строит missing LLM2/report по single manager/day;
- бизнес email можно включить только для Алишера, если report readiness
  позволяет manager-facing delivery.

#### 5. ROP recovery

После отчета Алишера нужно дать РОПу понятную картину по дню.

Предпочтительно:

- запустить штатную новую логику `scheduled_rop_daily_digest`, если есть safe
  replay path без повторного STT/LLM и без дублей manager emails.

Если штатного safe replay path нет:

- отправить controlled manual ROP recovery email на `edo.rop@dogovor24.kz`;
- приложить готовые PDF за день, которые доступны в runtime;
- в тексте указать статусы:
  - Алишер: delivered / recovered;
  - Тимур: delivered earlier;
  - Толеген: delivered earlier;
  - Илья: no calls.

### Не входит в 37B

- не чинить корень `get_processed_artifacts timeout` - это `37C`;
- не менять LLM2/report semantics;
- не менять шаблон отчета;
- не запускать повторный STT/LLM1 для уже готовых артефактов.

### Проверка

- `runtime-status` после restart не `blocked`;
- `sla-status --date 2026-06-24` показывает Алишера не `missed_pending`, а
  delivered или clear recovered state;
- у Алишера есть PDF/draft/report за `2026-06-24`;
- manager email Алишеру отправлен на `g.alisher@dogovor24.kz`;
- РОП получил одну понятную recovery-сводку по `2026-06-24`;
- `open-batches --date 2026-06-24` остается `0`.

### Факт выполнения 2026-06-25

- Pre-restart `runtime-status` был `blocked`: API `/status` не содержал
  `runtime`, worker вернул `NotRegistered: 'runtime.identity'`.
- Перезапущены только `analysis_api`, `analysis_worker`, `analysis_beat`.
  Post-restart `runtime-status`: `warning` из-за `git_commit=unknown` внутри
  container, но обязательные markers true:
  `scheduled_rop_daily_digest`, `deferred_to_scheduled_rop_digest`,
  `latest_upstream_handoff`.
- Алишер восстановлен single-manager/day recovery за `2026-06-24` без повторной
  STT/LLM1: persisted `CallArtifact` rows использованы для transcript /
  transcript_segments / `llm1_first_pass`; построен только missing analysis
  layer и report.
- Первый scheduled recovery attempt создал failed batch
  `b94a774d-a1a0-4195-9421-886e1896bc68`: call-processing API
  `/call-processing/runs/latest` попал в generic `/runs/{run_id}` route и
  вернул `500` (`invalid input syntax for type uuid: "latest"`). Это остается
  в scope `PILOT-37C`.
- Успешный recovery batch Алишера:
  `c16c5073-4687-496b-8049-23f14b3c0e12`, draft
  `6da1b1d8-0393-48a4-a535-67ef4eafa3c0`, PDF
  `Ежедневный отчет - Алишер Гайнидинов - 24 июня 2026.pdf`.
- Email Алишеру отправлен на `g.alisher@dogovor24.kz`, CC `sales@dogovor24.kz`;
  delivery status `delivered`. В отчете: `17` calls total, `11` with audio,
  LLM2/report-ready analyses `7`, admission rejects `4`.
- РОПу отправлен штатный `scheduled_rop_daily_digest` на
  `edo.rop@dogovor24.kz`, subject
  `Ежедневная сводка по отчётам ЭДО — 2026-06-24`, attachments `3`:
  Алишер, Тимур, Толеген. Manager emails Тимура/Толегена не replay-ились.
  В digest row Ильи штатный status вывел `blocked` с reason
  `no_calls_for_report_day`; operational interpretation: no calls /
  not_applicable.
- Final `sla-status --date 2026-06-24`: counts `late=1`, `on_time=2`,
  `not_applicable=1`; Алишер `late` because recovered after SLA deadline.
- Final `open-batches --date 2026-06-24`: `open_batches_count=0`,
  `potential_manager_daily_blockers_count=0`.

---

## PILOT-37C - Artifact retrieval hardening

Статус: `implemented_first_pass`

Результат `2026-06-25`: generic run route hardened to UUID-only
`/call-processing/runs/{run_id:uuid}`, repository read now returns `None`
for invalid run ids, and regression covers `runs/latest` missing as `404 run
not found` through the latest handler. Runtime identity/preflight supports
`--target api|worker|both` and marker subset; call-processing API/worker were
restarted and show marker `call_processing_latest_route_hardening=true`
(`warning` only because container `git_commit=unknown`). Analysis handoff now
turns `get_processed_artifacts` read timeout into `waiting_upstream` retry
metadata for scheduled manager-day when upstream is ready or partial, without
rerunning STT/LLM1.

### Цель

Убрать системную причину, по которой analysis при готовом upstream может
падать final failed:

- `get_processed_artifacts timeout_sec=180`;
- `/call-processing/runs/latest` в live runtime попадает в generic
  `/runs/{run_id}` и обрабатывается как UUID `"latest"`;
- call-processing side тоже может работать на старом runtime-коде, если после
  commit не был перезапущен.

### Что обнаружено в 37B

Первый recovery attempt по Алишеру создал failed batch
`b94a774d-a1a0-4195-9421-886e1896bc68`:

- error: `call_processing_ensure_failed: call-processing run read failed:
  status=500 body=Internal Server Error`;
- live root cause: `/call-processing/runs/latest` попал в generic
  `/call-processing/runs/{run_id}` и `"latest"` был интерпретирован как UUID.

В актуальном repo route `/runs/latest` уже расположен перед `/runs/{run_id}`,
но call-processing runtime мог не быть перезапущен. `37C` должен сделать
проверку и защиту так, чтобы это больше не проходило незамеченным.

### Что сделать

#### 1. Call-processing runtime gate

Перед кодовыми изменениями проверить runtime call-processing side:

- `runtime-status --api-url http://call_processing_api:8000/status` или
  доступный внутренний URL;
- worker queue `call_processing`;
- expected result после restart: markers true или отдельный понятный статус,
  если marker set относится только к analysis path.

Если current preflight не подходит для call-processing markers, расширить его:

- поддержать `--target api|worker|both`;
- поддержать `--required-marker` subset;
- для call-processing достаточно проверить наличие runtime identity task и
  commit/started_at, а не требовать analysis-only markers.

#### 2. Route regression

Добавить focused test, который гарантирует:

- `GET /call-processing/runs/latest?...` вызывается именно latest handler;
- строка `"latest"` не попадает в `{run_id}`;
- при отсутствии run возвращается `404 run not found`, а не `500 invalid UUID`.

Если для FastAPI route order нужен явный fix - внести его.

#### 3. Restart call-processing runtime

После проверки / правки перезапустить только при необходимости:

- `call_processing_api`;
- `call_processing_worker`;
- `call_processing_beat` только если route/task code используется beat-ом.

После restart подтвердить:

- `/call-processing/health` OK;
- `/call-processing/runs/latest` больше не падает как UUID route;
- call-processing runtime identity виден.

#### 4. Retrieval behavior в analysis

Проверить path в `CallsManualReportingOrchestrator` /
`CallProcessingClient`:

- если latest upstream ready и artifacts missing = 0, analysis не должен
  запускать повторный тяжелый ensure;
- если read of artifacts timeout still happens, scheduled manager-day должен
  получить retry/waiting status, а не финальный failed, когда upstream уже
  частично/полностью готов;
- не увеличивать timeout как основное решение;
- не делать повторный STT/LLM1.

#### 5. Controlled verification

Проверка без business email:

- single manager/day dry/safe path на Алишере или synthetic scope, где upstream
  ready;
- убедиться, что latest lookup работает;
- убедиться, что retrieval timeout не превращается в final failed без retry
  metadata.

### Не входит в 37C

- не менять LLM2 admission / scoring / report semantics;
- не пересылать отчеты менеджерам;
- не запускать full-day/full-company STT;
- не чинить ROP digest no-calls wording - это `37D`.

### Проверка

- focused tests по call-processing latest route;
- focused tests по runtime-status marker subset / call-processing queue, если
  preflight расширяется;
- focused tests по analysis handoff/retry behavior;
- `runtime-status` для call-processing side после restart не `blocked`;
- live smoke `/call-processing/runs/latest` не дает UUID error;
- `git diff --check`, `py_compile`.

---

## PILOT-37D - ROP digest SLA check

Статус: `implemented_first_pass`

Цель: SLA/post-run check должен явно видеть, что по дню есть единый
`scheduled_rop_daily_digest`; если есть manager deliveries, но digest нет -
это отдельная проблема.

### Контекст

После recovery `2026-06-24` единый ROP digest был отправлен, но текущий
операторский контроль видит это только через ручной SQL-аудит
`scheduled_report_batches.observability->scheduled_rop_daily_digest`. В
`sla-status` нет отдельного поля "сводка РОП отправлена / не отправлена".

Дополнительно в live-аудите найдено смысловое искажение: менеджер без звонков
за день (`no_calls_for_report_day`) в строке digest может выглядеть как
`blocked`. Для пилота это неправильно: отсутствие звонков - штатный
`not_applicable/no_calls`, а не проблема доставки.

### Что нужно сделать

1. Расширить `scheduled_reporting_preflight.py sla-status`:
   - добавить в результат верхнеуровневый блок `rop_digest`;
   - блок должен показывать `status`, `sent`, `recipient`, `attachments_count`,
     `rows_count`, `message_id`/delivery metadata если есть, и короткий
     `reason`;
   - если есть доставленные manager reports за дату, но нет
     `scheduled_rop_daily_digest`, `rop_digest.status` должен быть
     `missing_digest`, а общий operator summary должен явно подсказать, что
     нужна проверка/повторная отправка сводки РОП;
   - если по всем менеджерам только штатный `no_calls/not_applicable`, digest
     может быть `not_required`, без тревоги;
   - если digest есть и отправлен - `sent`;
   - если digest есть, но failed/blocked - отразить это отдельным reason.

2. Синхронизировать `core/report_scripts/scheduled_reporting_preflight.py` и
   runtime-mounted `scripts/scheduled_reporting_preflight.py`.

3. Исправить нормализацию строки digest по менеджеру без звонков:
   - `no_calls_for_report_day` не должен попадать в РОП-сводку как `blocked`;
   - ожидаемый manager-facing статус: `no_calls` или `not_applicable`;
   - причина должна оставаться видимой как `no_calls_for_report_day`, но не как
     operational blocker.

4. Добавить diagnostics, но не менять delivery behavior:
   - задача только про контроль, формулировки и SLA visibility;
   - не отправлять письма;
   - не строить новые отчеты;
   - не менять расписание.

### Где смотреть

- `core/report_scripts/scheduled_reporting_preflight.py`
- `scripts/scheduled_reporting_preflight.py`
- `core/app/agents/calls/scheduled_reporting.py`
- тесты scheduled reporting / preflight:
  - `core/tests/test_scheduled_reporting.py`
  - `core/tests/test_scheduled_reporting_preflight.py`

### Проверка

- `git diff --check`;
- `python3 -m py_compile` по измененным Python-файлам;
- focused pytest:
  - `docker compose exec -T analysis_api python -m pytest -q tests/test_scheduled_reporting.py tests/test_scheduled_reporting_preflight.py`
- read-only live check:
  - `docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py sla-status --date 2026-06-24`
  - в выводе должен быть понятный `rop_digest=sent`;
  - Илья/no-calls не должен отображаться как blocked в digest summary.

### Критерий приемки

- Codex/operator по одной команде `sla-status --date YYYY-MM-DD` видит:
  - отчеты менеджеров;
  - был ли отправлен единый ROP digest;
  - если digest не отправлен, это отдельная объясненная проблема;
  - no-calls менеджеры не выглядят как авария.

### Реализация 2026-06-25

- `sla-status` получил верхнеуровневый блок `rop_digest` с полями
  `status`, `sent`, `recipient`, `attachments_count`, `rows_count`,
  `message_id`, `delivery_metadata`, `reason`, `operator_summary` и
  `operator_action`.
- Если по дате есть delivered manager reports, но в batch observability /
  diagnostics нет `scheduled_rop_daily_digest`, preflight показывает
  `rop_digest.status=missing_digest` и operator action про проверку /
  повторную отправку ROP digest.
- Если все manager days штатно `no_calls` / `not_applicable`, digest
  трактуется как `not_required`, без тревоги.
- ROP digest row normalization больше не превращает
  `no_calls_for_report_day` в `blocked`: статус становится `no_calls`, а
  причина `no_calls_for_report_day` остается видимой.
- `core/report_scripts/scheduled_reporting_preflight.py` синхронизирован с
  runtime-mounted `scripts/scheduled_reporting_preflight.py`.

---

## PILOT-37E - Automatic post-run audit

Статус: `implemented_first_pass`

Цель: после каждого scheduled run автоматически фиксировать короткий аудит:
кто в scope, кому отправлено, кому не отправлено и почему, есть ли open
batches, timeout, ROP digest, next action.

### Контекст

После запусков `2026-06-23` и `2026-06-24` оператору приходилось вручную
собирать картину из `sla-status`, `open-batches`, SQL по
`scheduled_report_batches`, runtime markers и ошибок batch/draft. Для
автоматического пилота нужен один read-only post-run audit, который быстро
отвечает:

- расписание вообще стартовало или тихо пропустило день;
- по каким менеджерам есть отчет, late/missed/blocker;
- есть ли открытые batches, которые завтра заблокируют запуск;
- есть ли единая сводка РОП;
- были ли повторяющиеся технические ошибки (`timeout`, `read_timeout`,
  `missing_recipient`, `analysis_not_ready`, `upstream_not_ready`,
  `no_candidate_all_reported`);
- что сделать дальше.

### Что нужно сделать

1. Добавить read-only команду preflight:
   - рекомендуемое имя: `post-run-audit`;
   - вход: `--date YYYY-MM-DD`;
   - без запуска STT/LLM/report/delivery;
   - использует уже существующие данные и helpers:
     `sla-status`, `open-batches`, manager scope, ROP digest diagnostics,
     batch/draft observability.

2. Структура результата JSON:
   - `status`: `ok`, `attention_required` или `blocked`;
   - `report_date`;
   - `scope`: количество active schedules/managers и список менеджеров;
   - `manager_outcomes`: по каждому менеджеру `sla_status`,
     `manager_email_status`, `batch_status`, `reason`, `calls_total`,
     `calls_with_audio`, `analysis/readiness` если есть;
   - `rop_digest`: статус из `PILOT-37D`;
   - `open_batches`: count и краткий список blockers;
   - `technical_findings`: короткий список найденных проблем/аномалий;
   - `recommended_next_actions`: что делать оператору;
   - `billable_pipeline_started=false`.

3. Человекочитаемый вывод:
   - одна компактная сводка, без сырого JSON;
   - отдельно:
     - Итог дня;
     - Менеджеры;
     - ROP digest;
     - Open batches / blockers;
     - Что сделать дальше.

4. Правила статусов:
   - если все delivered/on_time/late и ROP digest sent, open blockers нет:
     `ok`;
   - если есть late или not_applicable/no_calls, но нет blockers:
     `ok` или `attention_required` только если есть реальное действие;
   - если есть missed_pending, blocked, missing_digest, failed digest,
     open-batches blockers, повторяющиеся timeout/read_timeout:
     `attention_required` или `blocked`;
   - no-calls/not_applicable не считать аварией.

5. Обновить документы:
   - этот файл;
   - `docs/PILOT_BACKLOG.md`;
   - `docs/PROGRESS.md`;
   - при необходимости `docs/PILOT_OPERATIONS.md` с короткой инструкцией:
     после scheduled day оператор/Codex запускает `post-run-audit --date ...`.

### Где смотреть

- `core/report_scripts/scheduled_reporting_preflight.py`
- `scripts/scheduled_reporting_preflight.py`
- `core/tests/test_scheduled_reporting_preflight.py`
- `docs/PILOT_OPERATIONS.md`

### Не входит в 37E

- не отправлять email/Telegram;
- не запускать pipeline;
- не чинить конкретные причины, найденные audit;
- не добавлять cron/beat schedule для audit; сейчас достаточно CLI-команды,
  которую можно вызвать вручную или подключить позднее.

### Проверка

- `git diff --check`;
- `python3 -m py_compile` по измененным Python-файлам;
- focused pytest:
  - `docker compose exec -T analysis_api python -m pytest -q tests/test_scheduled_reporting_preflight.py`
- read-only live check:
  - `docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py post-run-audit --date 2026-06-24`
  - вывод должен показывать delivered/late/not_applicable менеджеров,
    `ROP digest: sent`, `open_batches=0`, без запуска billable pipeline.

### Критерий приемки

После любого scheduled дня Codex/operator может одной командой получить
короткий audit и понять:

- день отработал штатно или требует внимания;
- кому ушли отчеты;
- кому не ушли и почему;
- ушла ли сводка РОП;
- что нужно сделать следующим шагом.

### Реализация 2026-06-25

- Добавлена read-only команда
  `scheduled_reporting_preflight.py post-run-audit --date YYYY-MM-DD`.
- Команда переиспользует существующие SLA manager rows, scope active
  `manager_daily` schedules/managers, ROP digest diagnostics из `PILOT-37D` и
  `open-batches` loader; STT/LLM/report/delivery pipeline не запускается.
- JSON результат содержит `status`, `report_date`, `scope`,
  `manager_outcomes`, `rop_digest`, `open_batches`, `technical_findings`,
  `recommended_next_actions` и `billable_pipeline_started=false`.
- Human output печатает компактные секции: итог дня, менеджеры, ROP digest,
  open batches/blockers, technical findings и next actions без сырого JSON.
- Severity rules: `late` и no-calls/`not_applicable` сами по себе не тревога;
  `missing_digest`, open blockers, `missed_pending`, `blocked`,
  failed/blocked digest и timeout/read_timeout дают
  `attention_required`/`blocked`.
- `core/report_scripts/scheduled_reporting_preflight.py` синхронизирован с
  runtime-mounted `scripts/scheduled_reporting_preflight.py`.
