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

Статус: `planned`

Что это значит:

- это не ручной полный дневной прогон;
- это проверка, что автоматический scheduled/reviewable flow умеет в split-mode
  создать batch/draft, дождаться/использовать call-processing artifacts, собрать
  report preview, пройти review/delivery gate и не вызвать legacy STT/LLM1.

Что сделать:

- controlled schedule create/draft smoke без бизнес-доставки;
- проверить `scheduled_report_batches` / `scheduled_report_drafts`;
- проверить, что report observability содержит external-service source summary;
- затем отдельно проверить approve/delivery только после operator approval.

Критерий готовности:

- один controlled scheduled manager_daily draft создан в split-mode без UI и без
  business delivery;
- delivery gate не отправляет менеджерам без explicit approval.

### SPLIT-COMPLETE-05 — ROP weekly / scheduled reviewable smoke

Статус: `planned`

Что сделать:

- проверить `rop_weekly` в external-service окружении на готовых persisted data;
- проверить scheduled reviewable reporting path на реальных artifacts;
- не запускать STT/LLM1 из ROP weekly.

Критерий готовности:

- weekly/reporting smoke проходит или явно показывает persisted-data blocker;
- split-boundary не нарушается.

### SPLIT-COMPLETE-06 — Production secret partitioning

Статус: `planned`

Что сделать:

- разделить env/credentials по ролям сервисов;
- `call-processing` должен иметь OnlinePBX/STT/LLM1 credentials;
- `analysis` в external mode не должен нуждаться в STT/LLM1 credentials;
- проверить route/env plan в контейнерах.

Критерий готовности:

- analysis service в external mode может собрать отчет по готовым artifacts без
  STT/LLM1 secrets;
- call-processing service отдельно имеет только нужные upstream secrets.

### SPLIT-COMPLETE-07 — Production cutover rehearsal

Статус: `planned_requires_operator_approval`

Что сделать:

- пройти `CUTOVER_ROLLBACK_RUNBOOK.md` на согласованном окне;
- сделать DB backup;
- применить/проверить additive migration;
- поднять split services;
- выполнить dry-run -> ensure -> manager_daily preview;
- не включать business delivery до approval.

Критерий готовности:

- rehearsal проходит без rollback;
- operator подтверждает readiness к production cutover.

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
