# Call-processing / STT service split completion roadmap

Дата актуализации: 2026-06-15

## Цель

Полностью завершить перенос транскрибации и upstream-call processing в отдельный
контур `call-processing`, где:

- `call_processing_api/worker` владеет OnlinePBX source discovery, audio fetch,
  STT, `transcript`, `transcript_segments` и `llm1_first_pass`;
- `analysis_api/worker` не делает STT/LLM1 в external mode, а только читает
  готовые upstream artifacts и выполняет LLM2/LLM3/reporting;
- legacy monolith остается rollback-путем до подтвержденного cutover.

## Текущее состояние

Кодовая реализация split-контура выполнена локально и первый реальный
operator-only split-run уже проведен.

Последний split-run:

- дата запуска: 2026-06-14;
- отчетный день: 2026-06-12;
- scope: Алишер, Тимур, Толеген;
- путь: `call_processing_api/worker` -> `analysis_api`;
- runtime: `CALL_PROCESSING_MODE=external_service`,
  `AI_LLM2_INPUT_PROFILE=compact`, OpenAI-compatible, subagent/simulation off,
  `LLM3_ENABLED=true`;
- delivery: `telegram_test_only`, business email disabled.

Результат:

- upstream found `73` interactions;
- `105/219` artifact requirements ready, `114` missing;
- successful upstream ensure made `101` provider calls:
  `36` source/recording, `32` STT, `33` LLM1;
- analysis reused `35` external LLM1 artifacts;
- `28` analyses built, `7` failed as
  `llm2_admission_non_commercial_or_unusable`;
- Толеген: `67` calls, `31` STT/LLM1, `25` analyses, `full_report`;
- Алишер: `6` calls, `4` STT/LLM1, `3` analyses,
  `skip_accumulate` / operator preview;
- Тимур: no calls found for `extension=311` / selected manager id on
  `2026-06-12`, so no report was produced.

Важно: этот run подтверждает, что split-route работает, но не закрывает
production cutover, потому что день был неполным по менеджерам и статус был
`partial`.

## Что уже закрыто

| Блок | Статус | Подтверждение |
| --- | --- | --- |
| Contract/schema/API/CLI для call-processing | `done` | focused split tests green |
| Additive DB models/migration/views | `implemented_local` | DB contract tests green |
| STT artifact build в call-processing | `implemented_local_provider_backed` | fake-provider tests + real split run |
| LLM1 artifact build в call-processing | `implemented_local_provider_backed` | fake-provider tests + real split run |
| Analysis external-service mode | `done` | real run logs `llm1_external_artifact_loaded` |
| Split Docker services | `done` | `call_processing_*` and `analysis_*` started |
| Active artifact duplicate fix | `done` | commit `e81ae74` |
| Stale processing run cleanup | `done` | commit `5eda14b`; no open `queued/running` split runs |
| Legacy rollback path | `available` | `CALL_PROCESSING_MODE=legacy` remains supported |

## Оставшиеся этапы до полного закрытия

### SPLIT-COMPLETE-00 — Production run alerts без Codex

Статус: `implemented_local`

Что сделано:

- добавлен fail-safe email alert layer для автоматических прогонов;
- технический канал уведомлений отделен от business delivery менеджерам;
- alert recipient задается через `ALERT_EMAIL_TO`, текущий целевой адрес:
  `admin@dogovor24.kz`;
- алерт сохраняется в `observability.alerts` и не ломает сам прогон, даже если
  SMTP недоступен;
- `skip_accumulate`, `partial`, `blocked`, `no_data`, missing/review statuses и
  quota/error blockers становятся operator/admin-visible;
- manager business email gate не ослаблен: preview/skip states менеджерам не
  отправляются автоматически.

Runtime config:

```text
ALERT_EMAIL_ENABLED=true
ALERT_EMAIL_TO=admin@dogovor24.kz
ALERT_EMAIL_MIN_LEVEL=warning
ALERT_EMAIL_ON_START=true
ALERT_EMAIL_ON_SUCCESS=false
```

Важно:

- это production-механизм, который должен работать без Codex;
- Telegram не является обязательным каналом мониторинга;
- `sales@dogovor24.kz` остается business/ROP copy для отчетов, но не является
  основным technical alert recipient.

Проверки:

- `python3 -m py_compile` по измененным Python-файлам;
- `git diff --check`;
- focused pytest:
  `/app/tests/test_run_alerts.py /app/tests/test_manual_reporting.py -k "run_alert or admin_alert"`
  plus manual reporting runner checks -> `12 passed`.

### SPLIT-COMPLETE-01 — Выбрать валидный контрольный день

Статус: `next`

Что сделать:

- выбрать день, где у всех трех пилотных менеджеров есть звонки в OnlinePBX;
- до provider-backed run сделать dry-run по scope;
- проверить, что в scope реально есть Алишер, Тимур и Толеген.

Почему нужно:

- 2026-06-12 не подходит как финальный acceptance day: по Тимуру в выбранном
  scope не было звонков.

Критерий готовности:

- dry-run показывает calls/interactions по всем трем менеджерам;
- operator подтверждает, что этот день годится для контрольного split-smoke.

### SPLIT-COMPLETE-02 — Повторить provider-backed full-day split smoke

Статус: `planned`

Что сделать:

1. Запустить `call_processing_api` dry-run.
2. Запустить `call_processing_api` ensure.
3. Запустить `analysis_api` `manager_daily` в
   `CALL_PROCESSING_MODE=external_service`.
4. Delivery mode только `telegram_test_only`, пока нет operator approval.

Проверить:

- `call_processing_mode=external_service`;
- analysis logs contain `llm1_external_artifact_loaded`;
- no local STT/LLM1 execution inside analysis;
- `transcripts_built` in analysis-side prepared artifacts remains `0`;
- no unexpected `llm1_first_pass_missing` / `transcript_missing_external_service`;
- reports generated for all expected managers or blockers are explicitly
  explained.

Критерий готовности:

- at least one full-day split run across the selected pilot managers completes
  with understandable readiness and no split-boundary regression.

### SPLIT-COMPLETE-03 — Нормализовать cost summary для split-runs

Статус: `implemented_local`

ТЗ: `docs/call_processing_split/SPLIT_COMPLETE_03_COST_SUMMARY_TZ.md`

Что сделать:

- объединять стоимость upstream `call-processing` и downstream `analysis` в один
  manager-day/run summary;
- не считать reuse как новый расход, но показывать original artifact cost;
- в KPI фиксировать total split cost, STT, LLM1, LLM2, LLM3 и cost per analyzed
  call.

Что уже сделано:

- `call-processing` возвращает `EnsureResponse.costs` и сохраняет тот же
  upstream summary в `CallProcessingRun.counts_json["costs"]`;
- upstream cost считается только по newly built STT/LLM1 artifacts; dry-run,
  reuse и legacy backfill не добавляют current-run cost;
- `analysis/reporting` читает upstream summary из
  `source_summary.call_processing_costs`, если external `EnsureResponse`
  вернул `costs`;
- итоговый `observability.ai_costs` в split-mode содержит `upstream`,
  `downstream`, верхние STT/LLM1/LLM2/LLM3 totals и общий
  `total_current_run_cost_usdt`;
- старые/legacy ответы без upstream `costs` не падают и сохраняют прежний
  downstream-only contract.

Почему нужно:

- 2026-06-12 split-run уже имел cost telemetry в разных частях контура, но в KPI
  был помечен как требующий нормализованного merged summary.

Критерий готовности:

- для новых split-run Codex/оператор читает стоимость из одного
  `observability.ai_costs`, без ручной реконструкции из нескольких JSON/log
  sources.

### SPLIT-COMPLETE-04 — Scheduled flow в split-контуре

Статус: `implemented_local`

ТЗ: `docs/call_processing_split/SPLIT_COMPLETE_04_SCHEDULED_FLOW_TZ.md`

Что это значит:

- это не ручной полный дневной прогон;
- это техническая подготовка автоматизации: `call-processing` каждый день в
  `00:00 Asia/Almaty` готовит STT/LLM1 за предыдущий день, а
  `analysis/reporting` каждый день в `08:00 Asia/Almaty` ищет неотчитанные дни
  с фактическими звонками и создает reviewable batch/draft;
- отдельный календарь выходных/праздников не ведем: пустые дни без звонков
  пропускаются без manager-facing отчета, а ближайший неотчитанный рабочий день
  выбирается по данным в lookback-window;
- это проверка, что automatic scheduled/reviewable flow умеет в split-mode
  создать batch/draft, использовать call-processing artifacts, собрать report
  preview, пройти review/delivery gate и не вызвать legacy STT/LLM1.

Что сделать:

Что сделано:

- добавлен split-aware scheduled branch для `manager_daily` schedules с явными
  `manager_ids`;
- data-driven candidate selection выбирает самый старый неотчитанный день со
  звонками внутри lookback-window;
- пустые выходные/праздничные дни без звонков фиксируются как skip/no-draft и
  не создают manager-facing отчет;
- batch observability сохраняет `scheduled_candidate_selection`;
- duplicate protection усилен по manager-day ключу;
- scan/draft вызывает `run_report(..., send_email=False)`;
- external-service scheduled path покрыт тестами на split-boundary, costs и
  alerts.

Критерий готовности:

- один controlled scheduled manager_daily draft создан в split-mode без UI и без
  business delivery;
- delivery gate не отправляет менеджерам без explicit approval.

Проверки:

- `docker compose exec -T api python -m pytest -q /app/tests/test_scheduled_reporting.py /app/tests/test_manual_reporting.py /app/tests/test_call_processing_reporting_integration.py -k "scheduled or schedule or reviewable or external_service"` -> `38 passed`;
- `python3 -m py_compile` по scheduled/reporting/alert/test files -> passed;
- `git diff --check` -> passed.

### SPLIT-COMPLETE-05 — ROP weekly / scheduled reviewable smoke

Статус: `deferred_by_operator`

Что сделать:

- проверить `rop_weekly` в external-service окружении на готовых persisted data;
- проверить scheduled reviewable reporting path на реальных artifacts;
- не запускать STT/LLM1 из ROP weekly.

Критерий готовности:

- weekly/reporting smoke проходит или явно показывает persisted-data blocker;
- split-boundary не нарушается.

Примечание 2026-06-15:

- оператор решил временно пропустить weekly ROP smoke и перейти к техническому
  разделению секретов.

### SPLIT-COMPLETE-06 — Production secret partitioning

Статус: `implemented_local`

ТЗ: `docs/call_processing_split/SPLIT_COMPLETE_06_SECRET_PARTITIONING_TZ.md`

Что сделать:

- разделить env/credentials по ролям сервисов;
- `call-processing` должен иметь OnlinePBX/STT/LLM1 credentials;
- `analysis` в external mode не должен нуждаться в STT/LLM1 credentials;
- проверить route/env plan в контейнерах.

Что сделано:

- добавлены tracked templates без реальных секретов:
  `.env.split.common.example`, `.env.call-processing.example`,
  `.env.analysis.example`;
- реальные `.env.split.common`, `.env.call-processing`, `.env.analysis`
  остаются под `.gitignore`;
- split services в `docker-compose.yml` читают
  `.env.split.common + .env.call-processing` или
  `.env.split.common + .env.analysis`;
- monolith/rollback services продолжают использовать `.env`;
- runbook обновлен на split-команды с
  `docker compose --env-file .env.split.common --profile split ...`;
- безопасная config-проверка:
  `docker compose --env-file .env.split.common.example --profile split config --no-env-resolution --quiet`.
- добавлен `STRICT_SERVICE_SECRET_PARTITIONING` в settings;
- `analysis` strict mode fail-fast ловит upstream OnlinePBX/STT/LLM1
  secrets/config;
- `call-processing` strict mode fail-fast ловит downstream LLM2/LLM3 provider
  secrets/config;
- добавлен `split_secret_partitioning_preflight.py` с JSON summary и exit codes;
- CLI доступен в контейнерном path `report_scripts/...`.

Критерий готовности:

- analysis service в external mode может собрать отчет по готовым artifacts без
  STT/LLM1 secrets;
- call-processing service отдельно имеет только нужные upstream secrets.

Проверки:

- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_runtime_split.py /app/tests/test_service_secret_partitioning.py` -> `16 passed`;
- `docker compose exec -T api python -m ruff check ...` -> passed;
- `python3 -m py_compile` по changed settings/preflight/tests -> passed;
- `docker compose config --no-env-resolution --quiet` -> passed;
- `docker compose --env-file .env.split.common.example --profile split config --no-env-resolution --quiet` -> passed;
- container preflight smoke for clean `analysis --strict` -> passed;
- container preflight smoke for clean `call-processing --strict` -> passed;
- strict `analysis` with injected `ONLINEPBX_API_KEY` -> failed as expected.

### SPLIT-COMPLETE-07 — Production cutover rehearsal

Статус: `draft_tz_ready_requires_operator_approval`

ТЗ: `docs/call_processing_split/SPLIT_COMPLETE_07_CUTOVER_REHEARSAL_TZ.md`

Что сделать:

- пройти `CUTOVER_ROLLBACK_RUNBOOK.md` на согласованном окне;
- сделать DB backup;
- применить/проверить additive migration;
- поднять split services;
- выполнить dry-run -> ensure -> manager_daily preview;
- не включать business delivery до approval.

Что уточнено в ТЗ:

- rehearsal не является production cutover;
- перед стартом нужны реальные `.env.split.common`, `.env.call-processing`,
  `.env.analysis`;
- обязательны strict preflight для обоих сервисов;
- есть stop conditions перед каждым billable/следующим шагом;
- результатом должен быть отдельный rehearsal result/audit с `GO/NO-GO`
  recommendation для SPLIT-COMPLETE-08.

Критерий готовности:

- rehearsal проходит без rollback;
- operator подтверждает readiness к production cutover.

### SPLIT-COMPLETE-07A — Production schedule activation smoke

Статус: `implementation_in_progress`

ТЗ: `docs/call_processing_split/SPLIT_COMPLETE_07A_PRODUCTION_SCHEDULE_ACTIVATION_TZ.md`

Текущее состояние 2026-06-15:

- CLI activation guard внедрен:
  `scheduled_reporting_preflight.py create-production-manager-daily`;
- runtime-mounted copies доступны в `/app/report_scripts`;
- dry-run по 4 менеджерам за `2026-06-15` прошел без записи в БД:
  `start_date=2026-06-16`, `start_time=08:00`, `timezone=Asia/Almaty`,
  `business_email_enabled=false`, `billable_pipeline_started=false`,
  `conflicts=[]`;
- реальный schedule row еще не создан;
- due-scan не запускался;
- найден runtime blocker/risk: legacy `beat` сейчас running, поэтому перед
  enabled schedule + split `analysis_beat` нужно остановить legacy scheduler
  или иначе исключить двойную обработку;
- отдельный scheduled `call-processing` entrypoint на `00:00 Asia/Almaty` еще
  не найден и остается gap для полной автоматизации.

Что сделать:

- перед созданием schedules выполнить Bitrix manager sync для `[ЭДО] Отдел
  Продаж` и строить scope только по актуальным `schedule_scope_candidates`:
  `active=true`, есть `email`, есть `extension`, без технических пользователей
  вроде `Робот Договор24`; inactive/уволенные сотрудники не должны попадать в
  расписание;
- создать реальные активные `report_schedules` для production pilot scope;
- явно проверить, что schedules настроены на `manager_daily`, актуальных
  менеджеров production pilot scope, `Asia/Almaty`, нужное время запуска и
  split-mode;
- актуальный утвержденный production pilot scope с 2026-06-15: Алишер
  (`5638c619-8732-435c-9664-a7188f13effd`), Илья
  (`cfba5067-d356-4c8b-895a-0f5808647978`), Тимур
  (`656abe58-7c23-476a-a9f6-d76305cf42e0`), Толеген
  (`d42e8246-772e-4a04-bbe7-2b88f45db695`);
- поднять `analysis_beat` в split-профиле только после проверки env/preflight;
- выполнить первый automatic due-scan smoke без ручного запуска pipeline;
- убедиться, что batch/draft создается в split-mode, а не через legacy path;
- проверить, что business delivery остается за review/approval gate, если
  отдельно не утверждено автодоставлять менеджерам;
- зафиксировать результат: schedule id, next_run_at, batch/draft id,
  observability, alerts и статус `GO/NO-GO` для дальнейшего cutover.

Что не делать на этом этапе:

- не запускать ручной provider-backed full-day pipeline вместо scheduler;
- не включать business email менеджерам без отдельного operator approval;
- не считать сам факт реализованного scheduled-flow кода активацией расписания.

Почему добавлено:

- `SPLIT-COMPLETE-04` подготовил код scheduled flow, но не означает, что в БД
  уже есть production `report_schedules`;
- `SPLIT-COMPLETE-07` является rehearsal и прямо не включает production
  schedule на автозапуск;
- на 2026-06-15 фактическая проверка показала: активных строк
  `report_schedules` нет, `analysis_beat` остановлен, поэтому автоматический
  запуск без этого этапа не состоится.

Критерий готовности:

- в БД есть активные schedule rows для пилотных менеджеров;
- manager scope соответствует последнему Bitrix sync: уволенные/inactive не
  выбраны, `Робот Договор24` исключен;
- `analysis_beat` запущен в split-profile и маршрутизирует scan-task в
  `analysis` queue;
- первый due scan создает expected reviewable batch/draft или понятный
  no-data/blocker с admin alert;
- observability подтверждает `CALL_PROCESSING_MODE=external_service` и
  отсутствие local STT/LLM1 execution внутри analysis.

### SPLIT-COMPLETE-07B — Scheduled call-processing upstream at 00:00

Статус: `implemented_local_requires_runtime_activation`

Что сделать:

Что сделано:

- добавлен Celery task
  `call_processing.ensure_daily_upstream`, который строит scope за previous-day
  в timezone `Asia/Almaty` и вызывает `CallProcessingService.ensure(...)`;
- task требует только upstream artifacts:
  `transcript`, `transcript_segments`, `llm1_first_pass`;
- task routed только в `call_processing` queue;
- beat schedule для этого task создается только при
  `APP_SERVICE=call_processing` и
  `CALL_PROCESSING_DAILY_UPSTREAM_ENABLED=true`;
- добавлен split-service `call_processing_beat` в `docker-compose.yml`, чтобы
  upstream scheduler можно было запускать отдельно от `analysis_beat`;
- `call_processing` beat больше не планирует scheduled reporting scan, поэтому
  reporting остается в `analysis` / legacy runtime;
- безопасный `dry_run=True` поддержан для технической репетиции без provider
  calls даже если enabled-флаг выключен;
- real ensure дополнительно требует production scope и
  `CALL_PROCESSING_DAILY_UPSTREAM_PROVIDER_CALL_BUDGET > 0`, чтобы случайный
  env toggle не начал платный прогон;
- returned payload содержит `task_status`, `report_date`, `scope`,
  `required_artifacts`, `planned`, `quota`, `costs`, `status` и structured
  `error` при failure.

Runtime env для включения:

```text
APP_SERVICE=call_processing
CALL_PROCESSING_DAILY_UPSTREAM_ENABLED=true
CALL_PROCESSING_DAILY_UPSTREAM_TIMEZONE=Asia/Almaty
CALL_PROCESSING_DAILY_UPSTREAM_HOUR=0
CALL_PROCESSING_DAILY_UPSTREAM_MINUTE=0
CALL_PROCESSING_DAILY_UPSTREAM_DEPARTMENT_ID=472cda28-ce71-494c-9068-25d3ffbf7399
CALL_PROCESSING_DAILY_UPSTREAM_MANAGER_IDS=5638c619-8732-435c-9664-a7188f13effd,cfba5067-d356-4c8b-895a-0f5808647978,656abe58-7c23-476a-a9f6-d76305cf42e0,d42e8246-772e-4a04-bbe7-2b88f45db695
CALL_PROCESSING_DAILY_UPSTREAM_PROVIDER_CALL_BUDGET=200
```

Что оператору осталось сделать:

- включить env `CALL_PROCESSING_DAILY_UPSTREAM_ENABLED=true` и provider budget
  в `.env.call-processing` только после approval;
- запустить отдельный Celery beat process `call_processing_beat` после
  остановки/разделения legacy beat;
- выполнить `dry_run=True` task smoke без provider calls;
- только после этого включать provider-backed scheduled run.

Почему добавлено:

- аудит `SPLIT-COMPLETE-07A` подтвердил, что scheduled analysis scan существует,
  но отдельного production-ready ночного upstream scheduler на `00:00
  Asia/Almaty` пока не найдено;
- без этого полный автоматический контур либо зависит от добора missing
  artifacts в `08:00 analysis`, либо требует ручного запуска call-processing.

Критерий готовности:

- local tests подтверждают, что task scheduled/routed в `call_processing` queue;
- runtime smoke подтверждает, что `call-processing` сам создает previous-day
  artifacts по расписанию;
- `analysis` в `08:00` переиспользует готовые external artifacts;
- split boundary соблюден: STT/LLM1 не выполняются внутри `analysis`;
- первый upstream scheduled smoke проходит без business delivery и с cost/alert
  observability.

### SPLIT-COMPLETE-07C — Runtime schedule activation for pilot

Статус: `implemented_runtime_activation_safe`

ТЗ: `docs/call_processing_split/SPLIT_COMPLETE_07C_RUNTIME_SCHEDULE_ACTIVATION_TZ.md`

Что сделать:

- [x] остановить legacy `beat`;
- [x] создать production `manager_daily` schedule row для 4 менеджеров ЭДО;
- [x] запустить split `analysis_beat`;
- [x] не запускать `call_processing_beat`, потому что upstream provider-backed
  run на `00:00 Asia/Almaty` еще не утвержден и env/budget не включены;
- [x] проверить, что `business_email_enabled=false`, `review_required=true`,
  schedule scope = 4 утвержденных менеджера;
- [x] не запускать `scan-due`, approve, manual pipeline или STT/LLM без отдельного
  approval;
- [x] зафиксировать schedule id, `next_run_at` и состояние beat-процессов.

Результат 2026-06-15:

- schedule id: `97e6c120-6aa3-4664-99ae-3982054698d7`;
- `next_run_at=2026-06-16T03:00:00+00:00` (`08:00 Asia/Almaty`);
- legacy `beat` stopped;
- `analysis_beat` running;
- `call_processing_beat` not running until upstream provider budget/enablement
  is separately approved;
- first automatic due scan processed `0` schedules because `next_run_at` is in
  the future;
- no manual billable pipeline/STT/LLM/email/approve was triggered.

Почему добавлено:

- `07A` подготовил безопасный CLI и schedule dry-run;
- `07B` подготовил code/compose для ночного upstream scheduler;
- теперь нужен отдельный runtime activation step, где изменяется состояние
  сервисов и БД, но еще не запускается ручной billable pipeline.

Критерий готовности:

- [x] active schedule создан и безопасен;
- [x] legacy scheduler не конкурирует;
- [x] split scheduler state соответствует выбранному режиму;
- [x] менеджерам ничего не отправлено без approve;
- [x] следующий automatic cycle может пройти по расписанию или дает понятный
  blocker/alert.

### SPLIT-COMPLETE-08 — Production cutover или rollback decision

Статус: `planned_requires_operator_approval`

Что сделать:

- если rehearsal green: перевести основной runtime на split;
- если blocker: оставить `CALL_PROCESSING_MODE=legacy`, сохранить artifacts для
  audit и создать точечные задачи.

Критерий готовности:

- принято явное решение `GO` или `NO-GO`;
- состояние runtime и rollback path задокументированы.

## Ответ на вопрос про “вчерашний полный день”

Да, 2026-06-14 мы сделали provider-backed прогон за полный отчетный день
`2026-06-12` через разделенные сервисы.

Но этот run не закрывает весь перенос как production-complete, потому что:

- по Тимуру за этот день не было звонков в выбранном scope;
- итоговый статус был `partial`;
- business delivery была специально выключена;
- scheduled/автоматический flow не проверялся;
- новые split-runs после `SPLIT-COMPLETE-03` должны уже возвращать merged
  `observability.ai_costs`; сам 2026-06-12 run был выполнен до этой доработки,
  поэтому его стоимость остается исторической/частично ручной реконструкцией.

Поэтому следующий ручной full-day split-smoke нужен только на более подходящем
дне, а отдельный пункт про scheduled flow означает проверку автоматического
режима, а не повторение того же ручного запуска.

## Source of truth

- `docs/call_processing_split/IMPLEMENTATION_STATUS.md`
- `docs/call_processing_split/CUTOVER_ROLLBACK_RUNBOOK.md`
- `docs/call_processing_split/VERIFICATION_PACK.md`
- `docs/ACTIVE_WORK_STATE.md`
- `docs/PILOT_BACKLOG.md`
