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
| Permanent split schedule runtime | `active` | `call_processing_beat` 00:00 Almaty + `analysis_beat` 08:00 Almaty running |
| Legacy rollback path | `available` | `CALL_PROCESSING_MODE=legacy` remains supported |
| No-audio CDR status | `implemented_first_pass` | `docs/PILOT25_NO_AUDIO_CDR_STATUS_TZ.md`; new split upstream rows classify missed/duration=0/no-recording CDR as `NO_AUDIO`, exclude them from STT/LLM1 requirements, and keep them visible in source/report funnel. Existing 2026-06-15 pilot cleanup completed for 41 rows; next upstream cycle should confirm new rows are classified correctly on ingest |

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
- с 2026-06-15 unattended blockers/failures отправляются в Telegram через
  `ALERT_TELEGRAM_*`;
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

Статус: `implemented_first_pass`

ТЗ: `docs/PILOT27_AUTOMATIC_SLA_CHECK_TZ.md`

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

Статус: `implemented_runtime_active`

ТЗ: `docs/call_processing_split/SPLIT_COMPLETE_07A_PRODUCTION_SCHEDULE_ACTIVATION_TZ.md`

Текущее состояние 2026-06-15:

- CLI activation guard внедрен:
  `scheduled_reporting_preflight.py create-production-manager-daily`;
- runtime-mounted copies доступны в `/app/report_scripts`;
- dry-run по 4 менеджерам за `2026-06-15` прошел без записи в БД:
  `start_date=2026-06-16`, `start_time=08:00`, `timezone=Asia/Almaty`,
  `business_email_enabled=false`, `billable_pipeline_started=false`,
  `conflicts=[]`;
- реальный production schedule row создан:
  `97e6c120-6aa3-4664-99ae-3982054698d7`;
- `next_run_at=2026-06-16T03:00:00+00:00`
  (`2026-06-16 08:00 Asia/Almaty`);
- legacy `beat` остановлен;
- split `analysis_beat` запущен и маршрутизирует scan-task в `analysis` queue;
- `business_email_enabled=false`, `review_required=true`;
- первый due-scan не запускался вручную; автоматический scan до `next_run_at`
  обработал `0` schedules;
- отдельный scheduled `call-processing` entrypoint на `00:00 Asia/Almaty`
  включен в рамках `SPLIT-COMPLETE-07B/07C`.

Что было сделано:

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
- не выполнять ручной `scan-due` до первого автоматического окна;
- убедиться, что batch/draft создается в split-mode, а не через legacy path;
- проверить, что business delivery остается за review/approval gate, если
  отдельно не утверждено автодоставлять менеджерам;
- зафиксировать результат: schedule id, next_run_at, observability/alert
  readiness и статус для дальнейшего cutover.

Что не делать на этом этапе:

- не запускать ручной provider-backed full-day pipeline вместо scheduler;
- не включать business email менеджерам без отдельного operator approval;
- не считать сам факт реализованного scheduled-flow кода активацией расписания.

Почему добавлено:

- `SPLIT-COMPLETE-04` подготовил код scheduled flow, но не означает, что в БД
  уже есть production `report_schedules`;
- `SPLIT-COMPLETE-07` является rehearsal и прямо не включает production
  schedule на автозапуск;
- на 2026-06-15 фактическая проверка сначала показала отсутствие active
  schedules и остановленный `analysis_beat`; затем activation была выполнена.

Критерий готовности:

- [x] в БД есть активный schedule row для пилотных менеджеров;
- [x] manager scope соответствует последнему Bitrix sync: уволенные/inactive не
  выбраны, `Робот Договор24` исключен;
- [x] `analysis_beat` запущен в split-profile и маршрутизирует scan-task в
  `analysis` queue;
- [ ] первый автоматический due scan создает expected reviewable batch/draft
  или понятный no-data/blocker с Telegram alert;
- [ ] observability первого автоматического цикла подтверждает
  `CALL_PROCESSING_MODE=external_service` и отсутствие local STT/LLM1 execution
  внутри analysis.

### SPLIT-COMPLETE-07B — Scheduled call-processing upstream at 00:00

Статус: `implemented_runtime_active`

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
CALL_PROCESSING_DAILY_UPSTREAM_MANAGER_IDS=["5638c619-8732-435c-9664-a7188f13effd","cfba5067-d356-4c8b-895a-0f5808647978","656abe58-7c23-476a-a9f6-d76305cf42e0","d42e8246-772e-4a04-bbe7-2b88f45db695"]
CALL_PROCESSING_DAILY_UPSTREAM_PROVIDER_CALL_BUDGET=300
ALERT_TELEGRAM_ENABLED=true
ALERT_TELEGRAM_MIN_LEVEL=warning
```

Что выполнено в runtime:

- env `CALL_PROCESSING_DAILY_UPSTREAM_ENABLED=true` и provider budget `300`
  включены в `.env.call-processing` после approval;
- отдельный Celery beat process `call_processing_beat` запущен;
- beat schedule подтвержден:
  `scheduled-call-processing-daily-upstream ->
  call_processing.ensure_daily_upstream`, crontab `0 0 * * *`, timezone
  `Asia/Almaty`, queue `call_processing`;
- technical Telegram alert smoke отправлен успешно;
- ручной STT/LLM/report/business email во время activation не запускались.

Почему добавлено:

- аудит `SPLIT-COMPLETE-07A` подтвердил, что scheduled analysis scan существует,
  но отдельного production-ready ночного upstream scheduler на `00:00
  Asia/Almaty` пока не найдено;
- без этого полный автоматический контур либо зависит от добора missing
  artifacts в `08:00 analysis`, либо требует ручного запуска call-processing.

Критерий готовности:

- [x] local tests подтверждают, что task scheduled/routed в `call_processing`
  queue;
- [x] runtime smoke подтверждает, что `call_processing_beat` запланировал
  previous-day upstream на `00:00 Asia/Almaty`;
- [ ] первый автоматический upstream cycle создает previous-day artifacts по
  расписанию;
- [ ] `analysis` в `08:00` переиспользует готовые external artifacts;
- [ ] split boundary соблюден: STT/LLM1 не выполняются внутри `analysis`;
- [ ] первый upstream scheduled cycle проходит без business delivery и с
  cost/alert observability.

### SPLIT-COMPLETE-07C — Runtime schedule activation for pilot

Статус: `implemented_permanent_split_schedule`

ТЗ: `docs/call_processing_split/SPLIT_COMPLETE_07C_RUNTIME_SCHEDULE_ACTIVATION_TZ.md`

Что сделать:

- [x] остановить legacy `beat`;
- [x] создать production `manager_daily` schedule row для 4 менеджеров ЭДО;
- [x] запустить split `analysis_beat`;
- [x] после отдельного approval включить `call_processing_beat` для постоянного
  upstream run на `00:00 Asia/Almaty`;
- [x] включить `CALL_PROCESSING_DAILY_UPSTREAM_ENABLED=true` и per-run guard
  `CALL_PROCESSING_DAILY_UPSTREAM_PROVIDER_CALL_BUDGET=300`;
- [x] включить Telegram technical alerts для unattended blockers/failures;
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
- `call_processing_beat` running after upstream provider budget/enablement was
  approved;
- Telegram technical alerts enabled for warning/error blockers;
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

### SPLIT-COMPLETE-07D — Manager daily auto-delivery SLA

Статус: `production_active_first_pass`

ТЗ: `docs/PILOT26_MANAGER_DAILY_AUTO_DELIVERY_SLA_TZ.md`

Зачем добавлено:

- После первого реального дня split-runtime отчеты за `2026-06-15` были
  проверены оператором и вручную отправлены Тимуру, Толегену и РОП.
- Пользователь подтвердил целевой режим: менеджеры и РОП должны получать письма
  до `10:00 Asia/Almaty` каждого рабочего утра.
- Текущий scheduled manager_daily умеет готовить review drafts, но не является
  полноценным unattended business delivery flow.

Что сделано:

- [x] добавить production branch `review_required=false` для `manager_daily`;
- [x] production-create default = `04:00 Asia/Almaty`,
  `business_email_enabled=true`, `review_required=false`;
- [x] автоматически отправлять готовые manager reports при
  `business_email_enabled=true`;
- [x] отправлять РОП daily package после manager delivery через существующий
  `run_report` / ROP bundle path;
- [x] добавить SLA-monitor/checker CLI `sla-status` и `sla-check`;
- [x] при задержке не отправлять сырой отчет, а фиксировать SLA status/reason;
- [x] покрыть review/production/SLA paths focused тестами.
- [x] runtime activation: active schedule `97e6c120-6aa3-4664-99ae-3982054698d7`
  переведен на `04:00 Asia/Almaty`, `review_required=false`,
  `business_email_enabled=true`;
- [ ] наблюдать первый auto-delivery день и подтвердить manager/ROP emails до
  `10:00`;
- [ ] при необходимости расширить ROP partial/late update wording после первого
  реального дня.

Критерий готовности:

- review режим не меняется и не отправляет manager email без approve;
- production режим доставляет manager/ROP emails автоматически;
- pending до `09:30` дает warning alert;
- pending до `10:00` фиксирует SLA miss и critical alert;
- late completion досылается без дублей;
- active schedule переведен на `04:00 Asia/Almaty`; первый production cycle еще
  нужно подтвердить по факту.

### SPLIT-COMPLETE-07E — Automatic SLA-check schedule

Статус: `implemented_first_pass`

Контекст:

- `SPLIT-COMPLETE-07D` включил production auto-delivery: manager_daily schedule
  запускается в `04:00 Asia/Almaty`, отправляет менеджерам и РОП при готовности.
- CLI-контроль уже готов: `scheduled_reporting_preflight.py sla-status` и
  `scheduled_reporting_preflight.py sla-check --phase precheck|hard`.
- First pass 2026-06-17 привязал проверки SLA в `09:30` и `10:00` к
  Celery beat для analysis runtime.

Что сделать:

- [x] добавить автоматический запуск `sla-check --phase precheck` каждый рабочий
  день в `09:30 Asia/Almaty`;
- [x] добавить автоматический запуск `sla-check --phase hard` каждый рабочий день
  в `10:00 Asia/Almaty`;
- [x] добавить auto-date режим: утром checker сам выбирает previous report day
  по `Asia/Almaty`, без ручной передачи даты;
- [x] precheck должен слать warning alert, если manager/ROP delivery еще не
  завершена;
- [x] hard-check должен фиксировать `sla_missed=true`, `sla_status` и reason для
  pending/blocked manager-day;
- [x] no-calls/no-audio дни не должны создавать шумный alert, если manager-day
  объективно не требует отчета;
- [ ] если отчет позже дошел, late delivery остается разрешенной и не должна
  дублировать уже доставленные письма;
- [x] добавить focused tests для scheduled SLA task/beat integration;
- [x] задокументировать команды ручной проверки для Codex/operator fallback.

Критерий готовности:

- в `09:30` без участия Codex появляется warning alert по всем неготовым отчетам;
- в `10:00` без участия Codex фиксируется hard SLA miss и critical alert;
- если все отчеты доставлены до `09:30/10:00`, SLA-check завершаетcя без шума;
- CLI `sla-status` показывает те же статусы, что зафиксировал автоматический
  checker.
- состояние runtime и rollback path задокументированы.

Проверено в first pass:

- `test_call_processing_runtime_split.py` +
  `test_scheduled_call_processing_upstream.py`
  `-k "sla or celery_queue_routing or celery_beat_schedule"` -> `6 passed`;
- `test_scheduled_reporting_preflight.py -k "sla"` -> `10 passed`;
- `py_compile` для worker/preflight/test файлов -> OK.

До `done`: подтвердить первый реальный scheduled run `09:30/10:00` без Codex.

### SPLIT-COMPLETE-07F — Duplicate/open-batch diagnostics

Статус: `implemented_first_pass`

ТЗ: [`docs/PILOT34_DUPLICATE_OPEN_BATCH_DIAGNOSTICS_TZ.md`](../PILOT34_DUPLICATE_OPEN_BATCH_DIAGNOSTICS_TZ.md)

Контекст:

- `PILOT-33` снял функциональную блокировку нового `manager_daily` дня старым
  open batch.
- Но расследование duplicate/open-batch случаев пока требует ручного поиска:
  diagnostics не всегда показывает concrete `blocked_by_batch_id` /
  `blocked_by_draft_id`.

Что сделать:

- [x] добавить диагностический результат для duplicate manager-day guard без
  изменения текущего поведения;
- [x] сохранить `blocked_by_batch_id`, `blocked_by_draft_id`,
  `blocked_by_reason`, `manager_id`, `report_date` в
  `scheduled_candidate_selection`;
- [x] расширить `open-batches` JSON/human output concrete blocker ids и
  recovery hint;
- [x] сохранить no-noise policy: `paused` batches не являются default blockers;
- [x] добавить focused tests на duplicate/open-batch diagnostics.

Критерий готовности:

- оператор по одному `open-batches` или `scheduled_candidate_selection` видит,
  какой batch/draft стал причиной skip/blocker;
- создание новых `manager_daily` batch не становится строже;
- focused tests и `py_compile` проходят.

Проверено в first pass:

- `test_scheduled_reporting.py` +
  `test_scheduled_reporting_preflight.py`
  `-k "duplicate or open_batch or recovery or blocker"` ->
  `14 passed, 24 deselected, 2 subtests passed`;
- весь `test_scheduled_reporting.py` -> `19 passed, 2 subtests passed`;
- preflight focused `open_batch/recovery/blocker` ->
  `6 passed, 13 deselected`;
- `py_compile` и `git diff --check` -> OK.

### SPLIT-COMPLETE-07G — Manager daily silent-skip guard

Статус: `draft_ready`

ТЗ: [`docs/PILOT35_MANAGER_DAILY_SILENT_SKIP_GUARD_TZ.md`](../PILOT35_MANAGER_DAILY_SILENT_SKIP_GUARD_TZ.md)

Контекст:

- scheduled analysis может обработать due schedule и сдвинуть `next_run_at`,
  но не создать ни одного `scheduled_report_batches` /
  `scheduled_report_drafts`;
- такой сценарий нельзя считать успешным unattended запуском, потому что
  менеджеры и РОП не получают отчеты, а оператор не получает понятный сигнал.

Что сделать:

- [x] добавить zero-batch guard для `manager_daily`;
- [x] сохранять per-manager selection diagnostics;
- [x] использовать concrete duplicate/open-batch ids из `PILOT-34`;
- [x] отправлять короткий operator alert без raw JSON;
- [x] сохранять `scheduled_manager_daily_run` summary;
- [ ] подтвердить, что SLA-check `09:30/10:00` реально страхует delivery без
  Codex в первом production window.

Критерий готовности:

- если schedule processed, но batches/drafts не появились, создается failed
  diagnostic record и отправляется short alert;
- по каждому менеджеру понятно, почему отчет создан/не создан;
- первый следующий production auto-run подтвержден как `ok` или сам прислал
  понятную проблему.

Проверено в first pass:

- scheduled reporting / run alerts / preflight focused:
  `41 passed, 12 deselected, 2 subtests passed`;
- split runtime SLA focused: `6 passed, 14 deselected`;
- `py_compile`, `git diff --check` и sync `core/report_scripts` vs `scripts`
  прошли.

### SPLIT-COMPLETE-07H — Manager daily production stabilization

Статус: `implemented_first_pass_in_progress`

ТЗ: [`docs/PILOT36_MANAGER_DAILY_AUTOMATION_STABILIZATION_TZ.md`](../PILOT36_MANAGER_DAILY_AUTOMATION_STABILIZATION_TZ.md)

Контекст:

- live-аудит auto-run за `2026-06-18` подтвердил, что расписание стартует:
  `call_processing` отработал в `00:00 Asia/Almaty`, `analysis` schedule
  стартовал в `04:00 Asia/Almaty`;
- проблема не в запуске beat, а в устойчивости выполнения после старта:
  создано `16` manager_daily batches вместо ожидаемых `4`, осталось `5`
  open blockers, SLA precheck/hardcheck упали с
  `ModuleNotFoundError: report_scripts`;
- у Алишера email есть в `managers.email`, но delivery получил
  `primary_email=None`;
- по Толегену delivered batch есть, но поздние failed duplicates сбивают
  итоговый `sla-status`.

Что сделать:

- [x] PILOT-36A: lock/idempotency guard для `schedule_id + planned_for +
  manager_id/report_date`, SLA-check import fix, корректный batch-priority в
  `sla-status`;
- [ ] PILOT-36B: recovery текущих open/duplicate batches за `2026-06-18`;
- [ ] PILOT-36C: recipient resolver и production terminal statuses без
  финального `review_required`;
- [ ] PILOT-36D: ROP daily digest, partial readiness и короткий итог
  автозапуска.

Критерий готовности:

- следующий production auto-run приходит к одному понятному финальному статусу
  по каждому менеджеру;
- `open-batches` не показывает зависшие дубли текущего дня;
- SLA-check `09:30/10:00` работает без Codex;
- РОП получает один daily digest с готовыми PDF и статусом проблемных
  менеджеров.

PILOT-36A first pass проверен 2026-06-19: focused docker pytest
`66 passed, 1 skipped, 5 subtests passed`; live `sla-status --date 2026-06-18`
теперь выбирает delivered batch для Тимура и Толегена, а failed/open duplicates
показывает в diagnostics.

### SPLIT-COMPLETE-09 — Company-wide transcription, selective analysis

Статус: `implemented_first_pass`

ТЗ: [`docs/PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md`](../PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md)

Контекст:

- текущий split-контур уже разделяет upstream `call-processing` и downstream
  `analysis/reporting`;
- следующий целевой шаг - расширить upstream на всю компанию, чтобы
  формировать STT и `llm1_first_pass` карточки звонков для поиска и будущей
  аналитики;
- LLM2/LLM3-анализ и менеджерские отчеты не должны автоматически расширяться
  на всю компанию. Они остаются только для выбранного analysis scope.

Что сделать:

- [x] `PILOT-39A`: company-wide upstream scope и dry-run/forecast
  ([ТЗ](../PILOT39A_COMPANY_WIDE_UPSTREAM_SCOPE_TZ.md));
- [x] `PILOT-39B`: universal LLM1 call card contract
  ([ТЗ](../PILOT39B_UNIVERSAL_LLM1_CALL_CARD_TZ.md));
- [x] `PILOT-39C`: явное разделение upstream scope и downstream analysis scope
  ([ТЗ](../PILOT39C_SELECTIVE_DOWNSTREAM_ANALYSIS_SCOPE_TZ.md));
- [x] `PILOT-39D`: cost/quota/monitoring для company-wide STT+LLM1
  ([ТЗ](../PILOT39D_COMPANY_WIDE_COST_QUOTA_MONITORING_TZ.md));
- [x] `PILOT-39E`: controlled rollout без unexpected analysis outside scope
  ([ТЗ](../PILOT39E_CONTROLLED_COMPANY_TRANSCRIPTION_ROLLOUT_TZ.md)).

Controlled rollout порядок после first pass:

1. `scope-preview --date YYYY-MM-DD --json` за выбранный рабочий день.
2. `dry-run --date YYYY-MM-DD --json` за 2-3 рабочих дня; сравнить volume,
   provider-call estimate, budget и forecast cost.
3. Только после ручного approval оператора: один provider-backed upstream run
   по company scope.
4. Проверить ЭДО reports через covering lookup.
5. Убедиться, что LLM2/LLM3/report generation не запускались вне selected
   downstream scope.
6. Только после этого включать permanent company schedule отдельным решением.

Критерий готовности:

- ночной `call-processing` может подготовить STT+LLM1 по company-wide scope;
- ЭДО `manager_daily` продолжает анализировать только утвержденных менеджеров;
- широкий upstream используется как covering source для узких analysis scopes;
- стоимость, квоты и ошибки видны оператору до того, как они сорвут
  автоматизацию.

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
