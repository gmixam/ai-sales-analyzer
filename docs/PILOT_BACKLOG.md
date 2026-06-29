# Pilot Backlog

Дата актуализации: 2026-06-29

## Назначение

Рабочий список задач этапа пилотирования MVP-1. Использовать этот файл как
оперативный backlog после закрытия основного pass по LLM2 / Report Layer /
delivery.

Связанные source of truth:

- `docs/ACTIVE_WORK_STATE.md` - короткое текущее состояние;
- `docs/PILOT_OPERATIONS.md` - ежедневный порядок запуска;
- `docs/MVP1_PILOT_METRICS_MEASUREMENTS.md` - KPI, замеры и стоимость;
- `docs/MANAGER_REPORT_FEEDBACK.md` - комментарии РОП/менеджеров по отчетам.
- `docs/MANAGER_DAILY_CALL_FEEDBACK_MINI_TZ.md` - draft мини-ТЗ по
  объяснению оценок в таблице звонков.
- `docs/LLM2_STATUS_DETAILS_MINI_TZ.md` - draft мини-ТЗ по статусным деталям
  звонка в `LLM2D`.
- `TMP_PILOT14_EDO_SCOPE_SCORING_TZ.md` - временное ТЗ и реализация первого
  pass по рамкам оценки ЭДО.
- `docs/PILOT18_BALANCED_COACHING_TZ.md` - draft мини-ТЗ по balanced coaching
  и ответственности LLM2D за важность рекомендации.
- `docs/PILOT20_FULL_REPORT_COVERAGE_AUDIT_TZ.md` - ТЗ фазы 1 по аудиту
  покрытия анализа до `full_report`.
- `docs/PILOT22_MANAGER_DAILY_STRICT_REPORT_DAY_TZ.md` - ТЗ по запрету
  подмешивания прошлых дней в менеджерский daily-отчет.
- `docs/PILOT23_MANAGER_DAILY_COMPACT_SUMMARY_TZ.md` - draft мини-ТЗ по
  сокращению служебного текста в верхнем блоке и `БАЛЛЫ ПО ЭТАПАМ`.
- `docs/PILOT24_SCHEDULED_AUTOMATION_FIRST_RUN_FIX_TZ.md` - ТЗ по стабилизации
  первого unattended daily schedule: strict previous-day, duplicate guard,
  timeout analysis -> call-processing.
- `docs/PILOT25_NO_AUDIO_CDR_STATUS_TZ.md` - ТЗ по техническому статусу
  no-audio/missed CDR в split upstream.
- `docs/PILOT26_MANAGER_DAILY_AUTO_DELIVERY_SLA_TZ.md` - ТЗ по production
  auto-delivery manager_daily до `10:00 Asia/Almaty` с late delivery.
- `docs/PILOT27_AUTOMATIC_SLA_CHECK_TZ.md` - ТЗ по автоматическому запуску
  SLA-check в `09:30/10:00 Asia/Almaty` без Codex.
- `docs/PILOT28_OPERATOR_ALERT_SUMMARY_TZ.md` - ТЗ по коротким операторским
  уведомлениям без сырого JSON.
- `docs/PILOT29_WHISPER_SPEAKER_ROLE_ATTRIBUTION_TZ.md` - ТЗ по усилению
  определения ролей speaker на текущем Whisper STT без смены модели.
- `docs/PILOT30_OPENAI_DIARIZE_MODEL_EVALUATION_TZ.md` - optional/deferred ТЗ
  по будущей оценке OpenAI diarization STT model.
- `docs/PILOT31_WEIGHTED_FOCUS_STAGE_TZ.md` - ТЗ по weighted focus stage для
  блока `БАЛЛЫ ПО ЭТАПАМ`.
- `docs/PILOT33_MANAGER_DAILY_OPEN_BATCH_GUARD_TZ.md` - ТЗ по исправлению
  scheduled guard, из-за которого старые `review_required` batches блокируют
  новый `manager_daily` auto-run.
- `docs/PILOT34_DUPLICATE_OPEN_BATCH_DIAGNOSTICS_TZ.md` - ТЗ по concrete
  diagnostics для duplicate/open-batch blocker ids.
- `docs/PILOT35_MANAGER_DAILY_SILENT_SKIP_GUARD_TZ.md` - ТЗ по защите
  `manager_daily` schedule от тихого пропуска без batch/draft/alert.
- `docs/PILOT36_MANAGER_DAILY_AUTOMATION_STABILIZATION_TZ.md` - epic-ТЗ по
  стабилизации production `manager_daily` после live-проверки `2026-06-18`:
  lock от дублей, SLA-check, recovery, production statuses, recipient resolver,
  ROP digest и короткие итоги автозапуска.
- `docs/PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md` - draft-ТЗ по
  расширению `call-processing` на всю компанию: STT+LLM1 карточка для всех,
  LLM2/LLM3 analysis только для выбранного downstream scope.

## Правило работы

1. Сначала чинить надежность дневного пилотного контура: данные, расписание,
   математика отчета, применимость этапов.
2. Затем добавлять операционную доставку для РОП.
3. Weekly/monthly отчеты делать после стабильной daily-механики.
4. Скрытые блоки возвращать по одному и только при наличии доказуемых данных.
5. Комментарии менеджеров не чинить вручную в PDF. Сначала занести их в
   `docs/MANAGER_REPORT_FEEDBACK.md`, проверить данные, затем при системной
   причине добавить или обновить задачу в этом backlog.
6. После каждого полуавтоматического прогона выполнять post-run audit по
   `docs/PILOT_OPERATIONS.md#post-run-audit`. Если аномалия/ошибка не
   исправлена сразу, добавить ее в раздел `Operational findings` ниже и
   привязать к существующей задаче или создать новую `PILOT-*`.

## Очередность работ

### P0 - Стабилизация автоматического `manager_daily`

Цель: production-расписание каждый день должно приходить к понятному состоянию:
по каждому менеджеру либо один доставленный отчет, либо один объясненный
финальный статус; SLA-check работает без Codex; РОП получает понятную сводку.

Работа ведется по одному блоку за раз: сначала мини-ТЗ на утверждение, затем
реализация, проверка и переход к следующему блоку.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-36A | Защита запуска и SLA | `implemented_first_pass` | Реализован first pass: перед созданием `manager_daily` batch добавлен PostgreSQL advisory transaction lock по ключу `schedule_id + planned_for + manager_id/report_date`; scheduled SLA-check больше не зависит от хрупкого `report_scripts` import и имеет fallback loader; `sla-status` выбирает главный batch по приоритету, где delivered/manager-email-sent важнее поздних failed-дублей, а все кандидаты остаются в diagnostics | Проверено: `py_compile`, `git diff --check`, sync `core/report_scripts` vs `scripts`; focused docker pytest `66 passed, 1 skipped, 5 subtests passed`; live `sla-status --date 2026-06-18` теперь выбирает delivered batch для Толегена и Тимура, а failed duplicates видны в `diagnostics.batch_candidates`. Остаток: старые open blockers за 2026-06-18 закрываются в PILOT-36B |
| PILOT-36B | Recovery текущего состояния 2026-06-18 | `implemented_first_pass` | Выполнен safe recovery через `scheduled_reporting_preflight.py recover-open-batches`: 5 старых open blockers за `2026-06-18` переведены `review_required -> paused` с причиной `PILOT-36B_2026-06-18_duplicate_open_blocker_recovery`; rows не удалялись; delivered batches Тимура/Толегена и failed historical duplicates Ильи/Тимура/Толегена не менялись | Проверено: dry-run `matched=5/planned=5/skipped=0`, apply `applied=5`; `open-batches --date 2026-06-18` вернул `open_batches_count=0`, `potential_manager_daily_blockers_count=0`; `sla-status --date 2026-06-18` остается понятным: Алишер `blocked/missing_recipient` на paused diagnostic batch, Илья `not_applicable`, Тимур и Толеген `delivered/on_time` |
| PILOT-36C | Доставка и production-статусы | `implemented_first_pass` | Реализован first pass: `manager_daily` recipient resolver теперь добирает `Manager.email` из БД по single-manager scope/payload/artifacts, если `ReportArtifact.manager` не присоединен; production schedule (`review_required=false`, `business_email_enabled=true`) больше не оставляет blocked delivery outcomes финальным `review_required`; batch/draft observability нормализует `delivered`, `missing_recipient`, `analysis_not_ready`, `delivery_failed`, `no_calls/not_applicable`, `paused` | Проверено: `py_compile`, `git diff --check`, sync `core/report_scripts` vs `scripts`; docker focused pytest `/app/tests/test_scheduled_reporting.py /app/tests/test_scheduled_reporting_preflight.py` -> `49 passed`; read-only `sla-status --date 2026-06-18` показывает Алишера: `manager_card_email=g.alisher@dogovor24.kz`, historical delivery recipient пустой, PDF ready, reason `missing_recipient`. Новых писем/STT/LLM/report generation не запускалось |
| PILOT-36D | ROP digest, частичная готовность и короткие итоги | `implemented_first_pass` | Scheduled `manager_daily` больше не шлёт per-manager ROP-copy из каждого одиночного `run_report`; после общего scan собирается один ROP digest по всем менеджерам scope, со статусами `delivered/no_calls/not_ready/missing_recipient/delivery_failed/blocked/will_retry/review_required/already_reported`, готовыми PDF во вложении и observability `scheduled_rop_daily_digest` без binary content | Проверено: `git diff --check`, `py_compile`, docker focused pytest `/app/tests/test_scheduled_reporting.py` -> `29 passed, 5 subtests passed`; manual ROP bundle smoke -> `3 passed`. Реальная отправка/production restart не выполнялись |
| PILOT-37A | Runtime restart / code-version gate | `implemented_first_pass` | ТЗ: [`docs/PILOT37_RUNTIME_DEPLOYMENT_AND_AUDIT_TZ.md`](PILOT37_RUNTIME_DEPLOYMENT_AND_AUDIT_TZ.md). Добавлен runtime identity/status gate для API/worker: commit/branch best-effort, process start, uptime, service identity, feature markers `scheduled_rop_daily_digest`, `deferred_to_scheduled_rop_digest`, latest upstream handoff; preflight `runtime-status` показывает mismatch до следующего scheduled run | Проверено: `py_compile`; docker focused pytest `tests/test_runtime_identity_gate.py tests/test_scheduled_call_processing_upstream.py` -> `15 passed`; live pre-restart `runtime-status` вернул `blocked` с причинами `status response has no runtime object` и `NotRegistered: runtime.identity`, то есть gate ловит старый runtime |
| PILOT-37B | Recovery 2026-06-24 | `completed_operational_recovery` | Analysis runtime перезапущен, post-restart `runtime-status=warning` только из-за `git_commit=unknown`, markers true. Алишер восстановлен single-manager/day за `2026-06-24` без повторной STT/LLM1; отправлен email на `g.alisher@dogovor24.kz`; отправлен штатный `scheduled_rop_daily_digest` РОПу с 3 PDF | Проверено: `sla-status --date 2026-06-24` -> `late=1`, `on_time=2`, `not_applicable=1`; Алишер delivered late; `open-batches=0`; digest rows=4, attachments=3 |
| PILOT-37C | Artifact retrieval hardening | `implemented_first_pass` | Убрана системная причина `/call-processing/runs/latest` -> `{run_id}` UUID failure: generic route стал `/runs/{run_id:uuid}`, repository invalid ids возвращает `None`, runtime gate расширен на call-processing marker `call_processing_latest_route_hardening`. Analysis handoff переводит `get_processed_artifacts` read timeout в `waiting_upstream` retry metadata, если upstream уже ready/partial | Проверено: `py_compile`, `git diff --check`, docker focused pytest `37 passed`; live call-processing `runtime-status` не `blocked`, marker true; `/call-processing/runs/latest` возвращает `404 run not found`, без UUID error |
| PILOT-37D | ROP digest SLA check | `implemented_first_pass` | `sla-status` теперь явно показывает верхнеуровневый `rop_digest`: `status/sent/recipient/attachments_count/rows_count/message_id/delivery_metadata/reason/operator_action`; delivered manager reports без `scheduled_rop_daily_digest` дают `missing_digest`, all no-calls/not_applicable - `not_required`; no-calls строка digest больше не нормализуется как `blocked` | Проверено: `py_compile`, `git diff --check`, focused pytest `57 passed, 5 subtests passed`; live read-only `sla-status --date 2026-06-24` показывает `ROP digest: status=sent`, `attachments=3`, `rows=4`, Илья `not_applicable/no_calls_for_report_day` |
| PILOT-37E | Automatic post-run audit | `implemented_first_pass` | Добавлен read-only `post-run-audit --date YYYY-MM-DD`: scope active schedules/managers, manager outcomes, ROP digest из 37D, open batches/blockers, technical findings, recommended next actions, `billable_pipeline_started=false`; human output без сырого JSON | Проверено: `py_compile`, `git diff --check`, focused pytest `100 passed, 5 subtests passed`; live read-only `post-run-audit --date 2026-06-24` показал `attention_required`, 4 менеджера, `ROP digest=sent`, `open blockers=0`, `billable_pipeline_started=no` |
| PILOT-38 | Covering upstream scope handoff | `implemented_first_pass` | ТЗ: [`docs/PILOT38_COVERING_UPSTREAM_SCOPE_HANDOFF_TZ.md`](PILOT38_COVERING_UPSTREAM_SCOPE_HANDOFF_TZ.md). First pass реализован: exact upstream lookup сохранен, добавлен read-only covering lookup в repository/API/client; analysis handoff использует covering run после exact miss; summary пишет `call_processing_scope_match`, requested/covering scope hashes; downstream artifacts остаются ограничены requested interactions | Проверка: host `py_compile` OK; focused docker pytest pack по call-processing API/reporting/scheduled upstream выполняется в финальной валидации. Live recovery/production pipeline и email/Telegram не запускались |

### P0B - Расширение `call-processing` на всю компанию

Цель: транскрибировать и формировать LLM1-карточки звонков по всей компании,
но не расширять LLM2/LLM3-анализ и отчеты автоматически. Analysis/reporting
работает только по выбранному downstream scope, сейчас ЭДО.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-39A | Company-wide upstream scope | `planned` | ТЗ: [`docs/PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md`](PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md). Подготовить company-wide scope для ночного `call-processing`: все активные сотрудники с extension, без уволенных/технических пользователей; сохранить pilot/department fallback; добавить dry-run с прогнозом CDR, eligible audio, STT/LLM1 и стоимости | Dry-run показывает весь company scope, текущий ЭДО analysis не расширяется, covering upstream подходит для узкого downstream scope |
| PILOT-39B | Universal LLM1 call card | `planned` | Зафиксировать schema `llm1_first_pass` как универсальную карточку звонка: тема, продукт/направление, тип обращения, горячесть, намерение, outcome, применимость к анализу, краткая суть, качество STT и speaker role mapping; не добавлять ЭДО-специфику в общий LLM1 prompt | Новые карточки пригодны для поиска/отбора звонков по темам и отделам; старые artifacts не ломаются |
| PILOT-39C | Selective downstream analysis scope | `planned` | Явно разделить `upstream_scope` и `analysis_scope` в настройках, schedule payload, diagnostics и summary; запретить автоматический LLM2/LLM3/reporting по всему company-wide upstream | Company-wide STT/LLM1 не создает отчеты по не-пилотным менеджерам; ROP digest содержит только выбранный analysis scope |
| PILOT-39D | Cost, quota and monitoring for company-wide STT/LLM1 | `planned` | Добавить лимиты/алерты и cost summary для корпоративного upstream: total calls, eligible calls, billable minutes, STT cost, LLM1 cost, cost per call card; показывать budget/quota warnings | Оператор видит стоимость и риски до/после прогона; provider quota/budget проблемы дают короткий alert |
| PILOT-39E | Controlled rollout company-wide transcription | `planned` | Провести read-only CDR forecast, dry-run без provider calls, один company-wide provider-backed upstream без расширения analysis, затем проверить ЭДО reports через covering lookup | Нет unexpected LLM2/LLM3/report generation вне выбранного scope; ЭДО reports не деградировали; cost summary понятен |

### P1 - Надежность дневного пилота

Цель: каждый дневной прогон должен давать проверяемые цифры и понятный статус
до отправки менеджерам или РОП.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-01 | Bitrix manager sync preflight | `done` | Добавлен CLI `core/report_scripts/bitrix_manager_sync_preflight.py`: выбирает отдел по id/name, запускает `BitrixManagerMapper.sync_department_directory`, печатает active/inactive, email, extension, Bitrix ID, added/deactivated, warnings и `schedule_scope_candidates`. Scope расписания строится только по `active=true`, есть `email`, есть `extension`; inactive/уволенные не считаются, `Робот Договор24` исключается как технический пользователь | Последняя live-сверка 2026-06-15 по `[ЭДО] Отдел Продаж` (`472cda28-ce71-494c-9068-25d3ffbf7399`): `synced=5`, `deactivated=1`, active=`5`, schedule candidates=`4` — Алишер, Илья, Тимур, Толеген; `Робот Договор24` active в Bitrix, но исключен из schedule scope |
| PILOT-02 | Проверка расписания без UI | `baseline_done` | Добавлен CLI `core/report_scripts/scheduled_reporting_preflight.py` с командами `status`, `scan-due`, `create`, `approve`; проверены `status` и безопасный `scan-due` без UI | Текущий факт: активных schedules нет, `scan-due` вернул `processed_count=0`; в review queue есть старые batches Manual Live Validation. Полную цепочку create -> draft -> approve/delivery нужно проверять отдельным controlled schedule на пилотный отдел |
| PILOT-03 | Математика первого блока | `done` | `selection_model` разделяет day-funnel exclusions (`too_short`, `ivr`) и processing/coaching reasons (`support`, `not_enough_analysis`, `not_selected`); `not_enough_analysis` считается только по содержательным звонкам; DOCX/PDF note больше не называет отсутствие анализа причиной исключения из списка дня | Контейнерный focused pytest: `/app/tests/test_manual_reporting.py -k "selection_model or sm2_too_short or sm4 or render_report_email_uses_short_body"` -> `13 passed`; `py_compile` и `node --check scripts/generate_docx_report.js` -> OK |
| PILOT-04 | Применимость этапов в `БАЛЛЫ ПО ЭТАПАМ` | `done` | `applicable=false` критерии больше не создают `score_by_stage` в LLM2 adapter и не попадают в дневную агрегацию persisted `score_by_stage`; слабые наблюдаемые этапы с `applicable=true, score=0` остаются в расчете | Контейнерный focused pytest: `/app/tests/test_llm2_layered_analysis.py /app/tests/test_manual_reporting.py -k "non_applicable_criteria or stage_scores_use_all_ready or stage_scores_ignore_non_dict or stage_scores_expose_low_coverage"` -> `5 passed` |
| PILOT-12 | Видимый список звонков только по готовым разборам | `done` | В `ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ` показывать только звонки с готовым неошибочным анализом; верхняя воронка остается по всему дню и отдельно показывает содержательные звонки без готового разбора | Проверено на Толегене 2026-06-03: воронка `38 / 24 / 14`, строк в таблице `14`, payload сохраняет `24` содержательных и `14` ready-analysis rows; Telegram test delivery `message_id=395`; focused pytest `19 passed` |
| PILOT-13 | ФИО контакта в `Контактах` и merged call list | `implemented_first_pass` | ТЗ: [`docs/PILOT13_CONTACT_NAME_SOURCE_TZ.md`](PILOT13_CONTACT_NAME_SOURCE_TZ.md). First pass внедрен: analyzer не prefill-ит `contact_name` из metadata, LLM input очищается от name-полей, prompt требует имя только из STT, Report Layer/composer не извлекают и не fallback-ят ФИО из STT/Bitrix/telephony metadata | Focused tests: 5 PILOT-13 tests passed, 6 subtests passed. Следующий шаг: controlled rerender свежего manager_daily отчета и визуальная проверка `Контакт`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `КОНТАКТЫ В РАБОТУ` |
| PILOT-17 | LLM-only semantic reporting | `implemented_first_pass` | Первый pass внедрен по `docs/LLM_ONLY_SEMANTIC_REPORTING_TZ.md`: manager-facing `call_list_status` / `final_manager_status` берутся только из `scores_detail.status_details.status` или `report_evidence.business_outcome.status`; `BusinessOutcomeResolver` оставлен diagnostic-only; отсутствие LLM-статуса отображается как `Статус не подтвержден`; верхняя сводка/email получили отдельный счетчик; `agreement` без LLM action anchor + evidence уходит в `agreement_missing_evidence` | Focused проверки прошли. Следующий шаг - контрольный rerender/прогон Толегена за 2026-06-04: false `Договорённость` из resolver fallback должна исчезнуть; payload должен показывать `missing_llm_semantic_status` / `agreement_missing_evidence`, `business_outcome_resolver_visible_usage_count=0`, `status_not_confirmed_*` counters |
| PILOT-20 | Повышение покрытия анализа до `full_report` | `implemented_first_pass` | Фаза 1 выполнена по `docs/PILOT20_FULL_REPORT_COVERAGE_AUDIT_TZ.md`; audit package: `review_packages/pilot20_full_report_coverage_audit_2026-06-04_2026-06-05/`. First pass фазы 2 внедрен: `_evaluate_manager_daily_readiness` считает `full_report` coverage по содержательным звонкам (`meaningful_ready_analysis_total / meaningful_calls_total`), raw coverage сохранен как диагностика | Проверено focused tests: readiness/group-result `6 passed`, selection_model `9 passed`, `py_compile` и `git diff --check` OK. Следующий шаг: controlled rerender/ready-only проверка на реальных отчетах; `llm2_admission_non_commercial_or_unusable` пока не чинить, а фиксировать на новых звонках |
| PILOT-21 | `КОНТАКТЫ В РАБОТУ` в `signal_report` | `new` | Во время PILOT-20 sweep найден соседний дефект: `test_signal_report_model_uses_manager_facing_polish_rules` падает, потому что `call_tomorrow.rows` пустой в `signal_report`, хотя тест ожидает 1 hot contact. Нужно разобрать, это устаревший тест после LLM-only/status gates или реальный regression в сборке `call_tomorrow` для сигнального отчета | Сначала провести bounded audit без правок: воспроизвести fixture, проверить `payload.call_tomorrow.contacts`, `selection_diagnostics`, `call_tomorrow_quality`, source final status/evidence. Затем либо обновить устаревшее ожидание теста, либо исправить `_build_call_tomorrow` / render path так, чтобы только доказанные контакты попадали в блок |
| PILOT-22 | Строгий отчетный день в `manager_daily` | `implemented_first_pass` | ТЗ: [`docs/PILOT22_MANAGER_DAILY_STRICT_REPORT_DAY_TZ.md`](PILOT22_MANAGER_DAILY_STRICT_REPORT_DAY_TZ.md). Внедрено: `manager_daily` строит только окно report day (`window_days_used=1`), `skip_accumulate` не получает прошлые artifacts, business email блокируется `strict_report_day_gate`, если period/window расширился или `included_in_report_total > meaningful_calls_total` | Проверено focused pytest: strict-day group result, expanded-window email safety, normal full_report path -> `3 passed`. Следующий шаг: controlled rerender Тимура за `2026-06-11`: отчет и письмо должны быть строго за `2026-06-11`, без `10-11 июня`; при `1` содержательном и `0` готовых разборах текст не должен показывать `в разбор вошло — 18` |
| PILOT-23 | Компактный верхний блок и краткие пояснения | `implemented_first_pass` | ТЗ: [`docs/PILOT23_MANAGER_DAILY_COMPACT_SUMMARY_TZ.md`](PILOT23_MANAGER_DAILY_COMPACT_SUMMARY_TZ.md). First pass внедрен: сокращены selection/header note, email summary, строка `Статусы без разбора` и scope note в `БАЛЛЫ ПО ЭТАПАМ`; расчеты readiness/selection/scoring не менялись | Focused pytest `7 passed`, `py_compile`, `node --check scripts/generate_docx_report.js`, `git diff --check` OK. Следующий шаг: controlled rerender Толегена за `2026-06-11` и визуальная проверка верхнего блока/`БАЛЛЫ ПО ЭТАПАМ`; после подтверждения перевести в `done` |
| PILOT-24 | Стабилизация unattended daily schedule после первого автозапуска | `implemented_first_pass` | ТЗ: [`docs/PILOT24_SCHEDULED_AUTOMATION_FIRST_RUN_FIX_TZ.md`](PILOT24_SCHEDULED_AUTOMATION_FIRST_RUN_FIX_TZ.md). First pass внедрен: production `manager_daily` с `previous_day` выбирает только вчерашний день, open/report-ready batch guard защищает от дублей при минутном scan, technical failed batch без draft не блокирует retry, analysis -> call-processing timeout увеличен до `180` секунд и `ReadTimeout` получает явный reason | Focused tests: scheduled reporting / call-processing client / split runtime / scheduled upstream `34 passed, 1 skipped`; runtime settings: `call_processing_mode=external_service`, `call_processing_client_timeout_sec=180`, alert Telegram enabled. Следующий шаг: дождаться следующего auto-window или выполнить approved controlled verification без business email |
| PILOT-25 | No-audio CDR не должен быть `ELIGIBLE` | `implemented_first_pass` | ТЗ: [`docs/PILOT25_NO_AUDIO_CDR_STATUS_TZ.md`](PILOT25_NO_AUDIO_CDR_STATUS_TZ.md). First pass внедрен: split upstream сохраняет missed/duration=0/no-recording CDR как технический статус `NO_AUDIO`, answered с аудио остается `ELIGIBLE`, `NO_AUDIO` не создает STT/segments/LLM1 requirements и не должен делать upstream `partial` только из-за missed CDR. External source summary сохраняет полный `source_targeted_total`, даже если artifact-eligible interactions меньше | Tests: call-processing service/scheduled upstream `26 passed`; focused no-audio/selection/reporting integration `13 passed` + external summary `2 passed`; `py_compile` и `git diff --check` OK. Cleanup за `2026-06-15` выполнен: `41` pilot-scope missed/no-audio rows переведены из `ELIGIBLE` в `NO_AUDIO`; контрольный report rerun подтвердил, что `NO_AUDIO` не требует STT/LLM1 |
| PILOT-26 | Auto-delivery и SLA до 10:00 для `manager_daily` | `production_active_first_pass` | ТЗ: [`docs/PILOT26_MANAGER_DAILY_AUTO_DELIVERY_SLA_TZ.md`](PILOT26_MANAGER_DAILY_AUTO_DELIVERY_SLA_TZ.md). First pass внедрен: `manager_daily` различает review (`review_required=true`) и production (`review_required=false`) режимы; production schedule вызывает business email delivery и ROP bundle через существующий `run_report`; batch/draft получают SLA/delivery observability; CLI получил `sla-status` и `sla-check`; production-create default теперь `04:00`, `business_email_enabled=true`, `review_required=false`. Runtime activation выполнен 2026-06-16: active schedule `97e6c120-6aa3-4664-99ae-3982054698d7` переведен на `04:00 Asia/Almaty`, `review_required=false`, `business_email_enabled=true`, `next_run_at=2026-06-17 04:00 Asia/Almaty` | Проверено: focused tests `19 passed`; split/upstream regressions `26 passed`, runtime/client `20 passed, 1 skipped`, reporting/no-audio/selection `16 passed`; `sla-status --date 2026-06-16` видит production schedule. Следующий шаг - наблюдать первый auto-delivery день и отдельно привязать `sla-check precheck/hard` к расписанию, если нужен автоматический SLA alert без Codex |
| PILOT-27 | Автоматический SLA-check в 09:30/10:00 | `implemented_first_pass` | ТЗ: [`docs/PILOT27_AUTOMATIC_SLA_CHECK_TZ.md`](PILOT27_AUTOMATIC_SLA_CHECK_TZ.md). Roadmap: `SPLIT-COMPLETE-07E`. First pass внедрен: добавлены Celery tasks `calls.manager_daily_sla_precheck` / `calls.manager_daily_sla_hardcheck`, beat entries `09:30` и `10:00` по `Asia/Almaty` для analysis runtime, routing в `analysis` queue, task wrappers вызывают существующий `scheduled_reporting_preflight.sla_check`, а `sla-status/sla-check` получили default `--date auto` = previous report day по Алматы. SLA-check не запускает STT/LLM/report pipeline и молчит при отсутствии affected managers | Проверено: runtime split/scheduled upstream SLA tests `6 passed`; preflight SLA tests `10 passed`; `py_compile` OK. До `done`: дождаться первого реального scheduled run `09:30/10:00`, подтвердить no-noise при норме и короткий alert + hard SLA observability при проблеме |
| PILOT-28 | Короткие операторские уведомления без JSON | `implemented_first_pass` | ТЗ: [`docs/PILOT28_OPERATOR_ALERT_SUMMARY_TZ.md`](PILOT28_OPERATOR_ALERT_SUMMARY_TZ.md). First pass внедрен: `run_alerts.py` поддерживает `operator_summary` и fallback summary без raw JSON; SLA `precheck/hard` и `manager_daily` run monitor передают короткий human summary; полный JSON/details остается в observability/logs | Проверено: `test_run_alerts.py` + `test_scheduled_reporting_preflight.py` -> `20 passed`; focused `test_manual_reporting.py -k manager_daily_run_monitor...` -> `4 passed`; общий alert/admin focused sweep -> `14 passed, 261 deselected, 4 subtests passed`; `py_compile` и `git diff --check` OK |
| PILOT-29 | Усиление speaker role attribution на текущем Whisper STT | `sample_verified` | ТЗ: [`docs/PILOT29_WHISPER_SPEAKER_ROLE_ATTRIBUTION_TZ.md`](PILOT29_WHISPER_SPEAKER_ROLE_ATTRIBUTION_TZ.md). First pass внедрен и sample-проверен: `whisper-1` остается активным STT; для Whisper убрана презумпция `speaker A = manager`; STT artifacts сохраняют diarization warning; LLM1 artifact содержит `speaker_role_mapping`; LLM2 compact/full input получает mapping; старые artifacts без mapping не падают. Дополнительно Report/Call Breakdown composer больше не выводит `manager/client` из raw STT speaker IDs или текста при weak diarization | Tests: role/STT/LLM1 focused `9 passed`; compact LLM2 + call breakdown `13 passed`; `py_compile` и `git diff --check` OK. Read-only sample audit: на свежем прогоне `2026-06-26` найдено 60 `llm1_first_pass` artifacts, у всех есть `speaker_role_mapping`, `stt_model=whisper-1`, `diarization_source=whisper_time_segments_without_speaker_labels`, `speaker_a_is_manager=false`. Остаточный unrelated test debt: полный focused pack дает `42 passed, 1 failed` по `cost_status` (`available` vs `price_missing`) вне speaker attribution |
| PILOT-30 | Optional evaluation `gpt-4o-transcribe-diarize` | `optional_deferred` | ТЗ: [`docs/PILOT30_OPENAI_DIARIZE_MODEL_EVALUATION_TZ.md`](PILOT30_OPENAI_DIARIZE_MODEL_EVALUATION_TZ.md). Отдельная будущая задача: controlled comparison текущего `whisper-1` + LLM1 role attribution против OpenAI diarization STT model. В рамках PILOT-29 не выполняется | Не включено в production; решение о переходе возможно только после отдельного experiment, оценки качества/стоимости/fallback и обновления runtime profiles/cost catalog |
| PILOT-31 | Weighted focus stage в `БАЛЛЫ ПО ЭТАПАМ` | `implemented_second_pass` | ТЗ: [`docs/PILOT31_WEIGHTED_FOCUS_STAGE_TZ.md`](PILOT31_WEIGHTED_FOCUS_STAGE_TZ.md). Внедрено: сами stage scores не меняются, изменен только выбор фокусного этапа; учитываются просадка, экспертный вес этапа и coverage по звонкам. После ручной проверки Толегена за `2026-06-15` снят `critical low-score override`: `score < 3.0` теперь отдельный `Критический сигнал`, но не перехватывает фокус | Focused tests: `/app/tests/test_manual_reporting.py -k "weighted_focus or critical_low_score or stage_scores"` -> `6 passed`; `py_compile`, `node --check scripts/generate_docx_report.js`, `git diff --check` OK. Следующий шаг: rerender Толегена за `2026-06-15`: ожидаемый фокус — `Выявление детальных потребностей`, а `Продажа: финал` — отдельный критический сигнал |
| PILOT-32 | Лучший учебный кейс для `СИТУАЦИЯ ДНЯ` / `РАЗБОР ЗВОНКА` | `implemented_first_pass_llm_ownership` | ТЗ: [`docs/PILOT32_FOCUS_CASE_SELECTION_TZ.md`](PILOT32_FOCUS_CASE_SELECTION_TZ.md). Внедрен second pass под архитектурное правило: смысловой выбор кейса и содержательные тексты `СИТУАЦИИ ДНЯ` / `РАЗБОР ЗВОНКА` формирует LLM3 на базе LLM2 evidence; Report Layer только проверяет контракт/stage/call id и блокирует нарушенный render; legacy/report-evidence/transcript/gaps fallback больше не строит смысловой breakdown | Проверено: Report Layer focused `20 passed, 1 skipped`; LLM3 composer `13 passed`; `py_compile`, `node --check`, `git diff --check` OK. До `done`: rerender Толегена за `2026-06-15` и визуально проверить, что `sale_final` не подменяет `needs_discovery`, а LLM3-owned case отображается корректно или дается neutral empty-state |
| PILOT-33 | `manager_daily` open-batch guard блокирует новый день | `implemented_first_pass` | ТЗ: [`docs/PILOT33_MANAGER_DAILY_OPEN_BATCH_GUARD_TZ.md`](PILOT33_MANAGER_DAILY_OPEN_BATCH_GUARD_TZ.md). First pass внедрен: `manager_daily` больше не применяет общий `_has_open_batch(schedule_id)` до выбора manager-day; duplicate protection уточнена на `schedule_id + manager_id + report_date`; non-manager_daily guard сохранен; добавлены `open-batches` diagnostics и dry-run-first `recover-open-batches`. Recovery/catch-up 2026-06-17 выполнен: `3` старых batch за `2026-06-15` переведены `review_required -> paused`; за `2026-06-16` без повторного STT/LLM1 достроены LLM2/Report Layer; Алишер и Толеген получили email, РОП получил копии, SLA=`late`; Тимур no-audio остался `review_required/missing_recipient`, Илья no-calls `not_applicable`; schedule сохранен на следующий auto-run `2026-06-17T23:00:00+00:00`. Visibility fix: `paused` исключен из default open-batch diagnostics, explicit recovery `--status paused` сохранен | Проверено: scheduler guard tests `8 passed`; preflight/recovery/SLA tests `12 passed`; full focused scheduled/preflight `28 passed`; live post-check подтверждает delivered batches Алишера/Толегена, а `open-batches` больше не шумит старыми paused recovery batches. Следующий шаг: наблюдать следующий auto-run; оставшийся хвост — duplicate diagnostics желательно дополнить concrete blocker id/alert |
| PILOT-34 | Concrete diagnostics для duplicate/open-batch | `implemented_first_pass` | ТЗ: [`docs/PILOT34_DUPLICATE_OPEN_BATCH_DIAGNOSTICS_TZ.md`](PILOT34_DUPLICATE_OPEN_BATCH_DIAGNOSTICS_TZ.md). Внедрено: duplicate guard получил `_manager_day_duplicate_diagnostics(...)` с concrete `blocked_by_batch_id` / `blocked_by_draft_id`, `_has_manager_day_duplicate(...) -> bool` остался совместимым wrapper, `scheduled_candidate_selection` сохраняет `skipped_already_reported_details`, а `open-batches` JSON/human output показывает blocker ids, draft ids/statuses и recovery hint | Проверено: focused duplicate/open-batch/recovery/blocker suite `14 passed, 24 deselected, 2 subtests passed`; весь `test_scheduled_reporting.py` `19 passed, 2 subtests passed`; preflight focused `6 passed, 13 deselected`; `py_compile` и `git diff --check` OK |
| PILOT-35 | `manager_daily` silent-skip guard | `implemented_first_pass` | ТЗ: [`docs/PILOT35_MANAGER_DAILY_SILENT_SKIP_GUARD_TZ.md`](PILOT35_MANAGER_DAILY_SILENT_SKIP_GUARD_TZ.md). Внедрено: zero-batch guard создает failed diagnostic batch с reason `manager_daily_zero_batches_after_candidate_selection`; `scheduled_manager_daily_run` summary сохраняет реальные/diagnostic batches, failed/review/report-ready counts и `status=ok|partial|failed`; failed/no-draft run получает short operator alert без raw JSON; SLA precheck/hardcheck registration покрыт тестами | Проверено: scheduled reporting / run alerts / preflight focused `41 passed, 12 deselected, 2 subtests passed`; split runtime SLA focused `6 passed, 14 deselected`; `py_compile`, `git diff --check`, sync `core/report_scripts` vs `scripts` OK. До `done`: подтвердить первый реальный auto-run `04:00` и SLA window `09:30/10:00` |

### P2 - Ежедневный отчет для РОП

Цель: РОП каждый день получает одну управленческую сводку по менеджерам с
приложенными manager_daily PDF.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-05 | `rop_daily_digest` | `implemented_first_pass` | First pass закрыт через `PILOT-36D`: scheduled `manager_daily` отправляет один ежедневный ROP digest после финального состояния scan; прикладывает готовые manager PDF и показывает строку статуса по каждому менеджеру scope | Один email РОП содержит manager_daily PDF attachments по доставленным менеджерам и summary по всем менеджерам; промежуточный digest не шлётся, если upstream ещё ждёт hourly retry |

### P3 - Расписание и delivery gate

Цель: ежедневный пилот можно вести по расписанию, но бизнес-доставка остается
под контролем оператора.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-06 | Scheduled daily operating flow | `planned` | Перевести проверенный scheduled flow в понятный Codex/CLI порядок: что запланировано, что готово к review, что approve, что delivered/failed | Codex по запросу может показать состояние расписания и выполнить approve/delivery без UI |
| PILOT-26 | Production auto-delivery SLA | `production_active_first_pass` | First pass реализован по `docs/PILOT26_MANAGER_DAILY_AUTO_DELIVERY_SLA_TZ.md`: `04:00` production-create default, production auto-delivery branch, manager email, ROP package, SLA status/check CLI. Active schedule уже переведен в production mode | Требуется наблюдение первого рабочего auto-delivery дня; automatic beat для `sla-check` 09:30/10:00 пока не привязан |

### P4 - Отчеты РОП weekly/monthly

Цель: после стабильных daily-данных дать РОП недельную и месячную управленческую
картину.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-07 | `rop_weekly` pilot-ready | `planned` | Довести существующий persisted-only weekly preset: проверить payload, шаблон, delivery, читаемость выводов и связи с daily reports | Weekly строится только из готовых persisted данных, отправляется РОП после review, не запускает STT/LLM |
| PILOT-08 | `rop_monthly` design/preset | `planned` | Спроектировать monthly как следующий preset на базе weekly/daily: динамика, KPI, GO/NO-GO, системные проблемы, решения РОП | Есть утвержденный контракт monthly и минимальный первый отчет без запуска новых анализов |

### P5 - Возврат скрытых блоков

Цель: постепенно вернуть полезные блоки без потери доверия к отчету.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-09 | `Голос клиента` | `planned` | Вернуть блок только при наличии реальных клиентских сцен/сигналов; пустой блок по-прежнему скрывать | В PDF блок появляется только с доказуемыми сигналами и не показывает placeholder |
| PILOT-10 | `Утренняя карточка` | `planned` | Сначала вернуть как Telegram/ROP-внутренний формат, не как обязательный блок manager PDF | Утренняя карточка не раздувает PDF менеджера и может быть отправлена отдельно |
| PILOT-11 | `Деньги на столе` | `deferred` | Возвращать только после CRM-ready или другого доказуемого источника суммы/сделки | Нет выдуманного потенциала по среднему чеку без доказательства |

### P6 - Справедливость оценки по роли менеджера

Цель: отчет не должен оценивать менеджера ЭДО по продажным критериям там, где
правильное действие - передать клиента, решить сервисный вопрос или не вести
продажу по продукту вне зоны ответственности.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-14 | Рамки обязанностей менеджера ЭДО | `implemented_first_pass` | Реализован первый pass по `TMP_PILOT14_EDO_SCOPE_SCORING_TZ.md`: `LLM2A` формирует `edo_scope`, `LLM2B` использует его для применимости sales scoring, `LLM2D` учитывает scope в рекомендациях, adapter сохраняет `scores_detail.edo_scope`, Report Layer только отображает/считает scope и не штрафует `none/unclear` как продажи | Focused проверки пройдены: LLM2 layered/runtime `23 passed, 2 subtests passed`; report regression `PILOT-14` passed. Следующий шаг - проверить на реальном LLM2/Report прогоне: звонки техподдержки/юр-направления не получают sales-push, `БАЛЛЫ ПО ЭТАПАМ` считают только применимые звонки/этапы |
| PILOT-15 | Объяснение оценок в таблице звонков | `implemented_first_pass` | Реализован первый pass по мини-ТЗ `docs/MANAGER_DAILY_CALL_FEEDBACK_MINI_TZ.md`: из существующих `scores_detail.strengths/gaps/recommendations/criteria_results` собирается `call_feedback_summary`, 4-я колонка стала `Итог / обратная связь`, новых LLM-вызовов и изменения scoring нет. Feedback Толегена: формат эффективен | Нужно проверить второй pass по тону: не натягивать улучшения там, где нет доказанного gap; focused tests passed, DOCX smoke подтвердил новый заголовок |
| PILOT-16 | Статусные детали звонка в LLM2D | `implemented_first_pass` | Внедрен первый pass по мини-ТЗ `docs/LLM2_STATUS_DETAILS_MINI_TZ.md`: `LLM2D` prompt/contract и compact payload знают `status_details`, adapter сохраняет блок в `scores_detail`, simulation возвращает deterministic структуру, Report Layer строит короткий `Итог` из status-specific mini-structure при совпадении статуса | Нужно проверить на реальном LLM2/LLM2D прогоне: у договоренностей должна появиться конкретика “о чем договорились”; старые анализы без LLM status details после PILOT-17 должны давать нейтральное состояние или использовать только другой valid LLM semantic source |
| PILOT-18 | Balanced coaching без forced improvement | `implemented_first_pass` | Реализован first pass по `docs/PILOT18_BALANCED_COACHING_TZ.md`: `LLM2D` contract/runtime возвращает `coaching_decision` с `improve|maintain|no_comment`, adapter сохраняет `scores_detail.coaching_decision`, Report Layer отображает `Улучшить` только при `improve`, `Поддерживать/Корректно` при `maintain`, ничего не добавляет при `no_comment`; дневная агрегация не берет legacy recommendations, если LLM2D уже дала `no_comment` | Focused проверки пройдены: LLM2 layered/runtime + report regressions `31 passed, 2 subtests passed`; `git diff --check`, `py_compile`, `node --check` OK. Следующий шаг - контрольный LLM2/Report rerender на реальных звонках Толегена/Алишера и review PDF |
| PILOT-19 | Прозрачность методики scoring для менеджера | `planned` | Добавить понятное объяснение, как считаются `Балл дня` и `БАЛЛЫ ПО ЭТАПАМ`: какие звонки оцениваются, что значит `Оценено`, как применимость этапов влияет на расчет, почему звонок/этап мог не попасть в балл | На отчете Тимура менеджер видит, что именно считается и почему; `БАЛЛЫ ПО ЭТАПАМ` не выглядит как черный ящик |

## Feedback intake

Комментарии РОП/менеджеров проходят через `docs/MANAGER_REPORT_FEEDBACK.md`.

Если комментарий повторяется или подтверждает системную проблему, обновить
соответствующую задачу в этом файле:

| Feedback ID | Связанная задача | Статус связи | Комментарий |
| --- | --- | --- | --- |
| 2026-06-05-Алишер-01 | PILOT-14 | `implemented_first_pass` | Менеджер просит учитывать границы обязанностей ЭДО: юр-направление и техподдержка не должны оцениваться как непроданная продажа. Первый pass внедрен, нужен контрольный реальный прогон |
| 2026-06-05-Алишер-02 | PILOT-15 | `implemented_first_pass` | Менеджеру не хватает объяснения, почему выставлены оценки; первый pass внедрен, следующий шаг - review контрольного PDF |
| 2026-06-05-Толеген-01 | PILOT-17 | `implemented_first_pass` | У Толегена за 2026-06-04 появились false `Договорённость` из resolver fallback при отсутствии LLM-подтверждения через `business_outcome` / `status_details`. Первый pass закрывает resolver fallback для видимого статуса; нужна контрольная проверка на rerender/прогоне |
| 2026-06-05-Толеген-02 | PILOT-15 | `positive_feedback` | Менеджер считает правки по `Итог / обратная связь` эффективными |
| 2026-06-05-Толеген-03 | PILOT-18 | `implemented_first_pass` | Не везде есть целесообразность натягивать “что улучшить”; нужен balanced coaching. First pass внедрен: `LLM2D` выбирает `improve/maintain/no_comment`; Report Layer не достраивает рекомендацию, `LLM3` только компонуeт уже данные LLM2-сигналы |
| 2026-06-05-Тимур-01 | PILOT-19 | `new` | Баллы вызывают вопросы, потому что непонятно, как считается и что считается |
| 2026-06-12-Толеген-01 | PILOT-23 | `implemented_first_pass` | В отчете за `2026-06-11` верхний блок и `БАЛЛЫ ПО ЭТАПАМ` слишком многословны и дублируют объяснение механизма. First pass внедрен, нужна визуальная проверка на rerender отчета |

## Operational findings

| Finding ID | Связанная задача | Статус связи | Наблюдение |
| --- | --- | --- | --- |
| 2026-06-09-coverage-01 | PILOT-20 | `new` | Полный прогон Тимура, Толегена и Алишера за `2026-06-05` завершился доставкой отчетов, но runner status=`partial`, все 3 отчета readiness=`signal_report`: Алишер `analysis_coverage=57.1%` (`4/7`), Тимур `33.3%` (`6/18`), Толеген `41.3%` (`19/46`). В prepared artifacts: `analyses_built=35`, `analyses_reused=66`, `analyses_rejected_for_reuse=17` в build-run и `23` rejected в ready-only delivery-run. Это нужно разобрать как отдельный критичный слой надежности дневного пилота. |
| 2026-06-10-call-tomorrow-01 | PILOT-21 | `new` | После first pass PILOT-20 широкий focused sweep `/app/tests/test_manual_reporting.py -k "manager_daily_readiness or manager_daily_group_result or selection_model or full_report or signal_report"` дал 1 failure: `test_signal_report_model_uses_manager_facing_polish_rules`, `IndexError` на `sections["call_tomorrow"]["rows"][0]`. Это соседний defect/устаревшее ожидание блока `КОНТАКТЫ В РАБОТУ`, не denominator readiness. |
| 2026-06-11-coverage-10jun-01 | PILOT-20 | `observed` | Полный прогон Алишера, Тимура и Толегена за `2026-06-10` завершился доставкой всех 3 отчетов в Telegram и email, но runner status=`partial` из-за неполного анализа. Readiness: Алишер `signal_report` (`2/2` meaningful-ready, raw `50.0%`), Тимур `full_report` (`16/19`, `84.2%`), Толеген `full_report` (`21/24`, `87.5%`). На самом дне 6 failed-анализов, все `llm2_admission_non_commercial_or_unusable` (Тимур 3, Толеген 3); это не provider/quota failure, а зона наблюдения admission gate в рамках PILOT-20. |
| 2026-06-12-coverage-11jun-01 | PILOT-20 / PILOT-22 | `observed` | Полный прогон Алишера, Тимура и Толегена за `2026-06-11` завершился доставкой email всем 3 менеджерам, но runner status=`partial`, все отчеты `signal_report`: Алишер `3/7` meaningful-ready (`42.9%`), Тимур `0/1` (`0.0%`), Толеген `9/15` (`60.0%`). Все 11 failed-анализов за целевой день имеют `llm2_admission_non_commercial_or_unusable`; provider/quota ошибок нет. Дополнительная аномалия: отчет Тимура ушел с расширенным окном `2026-06-10 - 2026-06-11` и некорректной строкой письма `Из 1 содержательных ... в коучинговый разбор вошло — 18`. Решение пользователя: manager-facing daily не должен подмешивать прошлые дни; фиксируется как `PILOT-22`. |
| 2026-06-14-split-12jun-01 | PILOT-20 / split runtime | `observed` | Тестовый split-service прогон за `2026-06-12` запускался через `call_processing_api/worker` и `analysis_api` (`CALL_PROCESSING_MODE=external_service`, `AI_LLM2_INPUT_PROFILE=compact`, OpenAI-compatible, subagent/simulation off). Upstream нашел `73` interactions, подготовил `105/219` artifact requirements; `114` requirements остались missing, successful ensure сделал `101` provider calls (`36` source/recording, `32` STT, `33` LLM1). Analysis reused `35` external LLM1 artifacts, built `28` analyses, failed `7` as `llm2_admission_non_commercial_or_unusable`. В scope дня фактически есть Алишер `6` звонков и Толеген `67`; по Тимуру `extension=311` записей за день нет. В operator Telegram ушли PDF Алишера (`skip_accumulate/preview`) и Толегена (`full_report`); business email был выключен. |
| 2026-06-14-split-12jun-02 | call-processing split cleanup | `done` | При первом split ensure найден write-path дефект active artifacts: pending/active duplicate для `(interaction_id, artifact_kind, artifact_version)` мог падать на `uq_call_artifacts_active_kind_version`. Код исправлен в `ArtifactRepository.write_active()` и покрыт focused тестом. Дополнительно добавлена admin-only CLI-команда `cleanup-stale-runs`; две ранние упавшие попытки ensure `465abcb5...` и `aa915c5e...` переведены из `running` в `stale`, открытых `queued/running` split runs после cleanup нет. |
| 2026-06-16-auto-schedule-01 | PILOT-24 | `implemented_first_pass` | Первый unattended split-runtime сработал частично: `00:00` upstream за `2026-06-15` построил `50` STT и `50` LLM1, cost около `1.127513 USDT`, status=`partial`, Telegram alert sent. `08:00` reporting schedule сработал и сдвинул `next_run_at` на следующий день, но создал `8` failed batches и `0` drafts/PDF. Причины: manager_daily scheduled branch догонял старые даты (`2026-06-09`, `2026-06-10`) вместо strict previous day, analysis -> call-processing ловил `ReadTimeout`, минутный beat создал повторные попытки пока первый scan выполнялся около `95s`. First pass исправления внедрен: strict previous-day, duplicate/open-batch guard, retry после failed без draft, timeout `180`. |
| 2026-06-16-no-audio-cdr-01 | PILOT-25 | `implemented_first_pass` | Аудит STT за `2026-06-15`: в scope `91` interaction, `50` answered получили STT/LLM1, `41` missed (`duration_sec=0`, empty `raw_ref`) остались без STT. Failed STT artifacts нет. Причина: split upstream сохранял targeted CDR напрямую через `save_interactions(targeted)`, а `save_interactions()` всем новым rows ставил `status='ELIGIBLE'`; старый `filter_eligible()` в этом path не применялся. First pass исправляет новые записи и artifact planning; bounded cleanup старых `41` строк выполнен, контрольный report rerun собрал PDF по Алишеру/Тимуру/Толегену. |
| 2026-06-16-auto-delivery-sla-01 | PILOT-26 | `production_active_first_pass` | Агенты реализовали first pass production auto-delivery/SLA: core scheduled branch использует `review_required=false` как production режим, CLI добавил `sla-status/sla-check`, runtime-mounted `scripts/scheduled_reporting_preflight.py` синхронизирован с `core/report_scripts`. Dry-run production-create подтверждает целевой payload `04:00 Asia/Almaty`, `business_email_enabled=true`, `review_required=false`. Runtime activation выполнен: active schedule `97e6c120-6aa3-4664-99ae-3982054698d7` теперь `04:00`, `review_required=false`, `business_email_enabled=true`, `next_run_at=2026-06-17T04:00:00+05:00`. |
| 2026-06-19-auto-delivery-sla-01 | PILOT-36 | `new` | Live-аудит запуска за `2026-06-18`: `call_processing` в `00:00 Asia/Almaty` завершился успешно и подготовил STT/LLM1; `analysis` schedule в `04:00 Asia/Almaty` стартовал, но создал `16` manager_daily batches вместо ожидаемых `4`. По Алишеру `4` open `review_required` с `missing_recipient`, хотя `managers.email=g.alisher@dogovor24.kz`; по Тимуру есть delivered + open `review_required` + failed; по Толегену delivered batch есть, но поздние failed `no_candidate_all_reported` сбивают `sla-status`; SLA precheck/hardcheck в `09:30/10:00` упали с `ModuleNotFoundError: report_scripts`. Вывод: расписание запускается, но требуется stabilization epic `PILOT-36`. |
| 2026-06-24-upstream-analysis-handoff-01 | PILOT-36E | `implemented_first_pass` | Восстановление report date `2026-06-23` подтвердило дефект handoff: ручной `call_processing ensure` по 4 пилотным менеджерам довел upstream до `ready` (`artifacts_missing=0`, построено `29` STT и `30` LLM1), но `analysis/build_missing_and_report` снова уперся в synchronous `call_processing_client_read_timeout=180`. First pass реализован: добавлен latest upstream readiness lookup по exact scope, `build_missing_and_report` short-circuit-ит повторный full ensure при upstream `ready` и продолжает missing LLM2/report path; если upstream еще не готов, production manager-day получает `waiting_upstream` / `upstream_partial` / `upstream_blocked` / `upstream_missing` и hourly retry `05:00`, `06:00`, `07:00`, `08:00`, `09:00 Asia/Almaty`; после `09:00` статус `upstream_not_ready_before_deadline`. Проверено focused tests `82 passed, 5 subtests passed`. Следующий шаг: controlled no-business-delivery проверка или наблюдение ближайшего auto-run. |

## Следующий рекомендуемый шаг

Начать с P0 / PILOT-37:

1. PILOT-37A - runtime restart / code-version gate: понять, какой commit
   фактически загружен в API/worker/beat и есть ли feature markers текущих
   правок.
2. PILOT-37B - после 37A восстановить report date `2026-06-24`: добрать
   Алишера без повторной STT/LLM1 и отправить корректный ROP digest.
3. PILOT-37C - закрыть `get_processed_artifacts timeout_sec=180` системно,
   чтобы готовый upstream не превращался в final failed.
4. PILOT-37D - добавить ROP digest SLA check.
5. PILOT-37E - добавить automatic post-run audit.
6. PILOT-29 - sample-verified; наблюдать ближайшие новые звонки и не менять
   STT-модель до отдельной optional-задачи PILOT-30.
7. PILOT-31 - проверить на контрольном manager_daily отчете, что weighted focus
   stage в `БАЛЛЫ ПО ЭТАПАМ` выбирает управленчески логичный этап, не меняя
   сами баллы.
8. PILOT-32 - проверить first pass под LLM ownership на rerender Толегена за
   `2026-06-15`: LLM3 выбирает и пишет учебный кейс дня, Report Layer только
   проверяет контракт и stage/call gates.
9. PILOT-25 - подтвердить на следующем upstream cycle, что новые missed CDR
   сразу сохраняются как `NO_AUDIO` и не создают missing STT requirements.
10. PILOT-20 - controlled rerender/ready-only проверка на реальных отчетах после
   denominator fix: убедиться, что отчеты с высоким coverage содержательных
   звонков больше не остаются `signal_report` только из-за normal exclusions.
11. PILOT-22 - controlled rerender после first pass: проверить Тимура за
   `2026-06-11`, что отчет и письмо отражают только выбранный день, даже если
   данных мало.
12. PILOT-23 - controlled rerender после first pass: проверить Толегена за
   `2026-06-11`, что верхний блок и `БАЛЛЫ ПО ЭТАПАМ` стали компактными без
   изменения цифр.
13. PILOT-21 - bounded audit `call_tomorrow` в `signal_report`: понять, это
   устаревший тест или реальный дефект блока `КОНТАКТЫ В РАБОТУ`.
14. PILOT-17 - контрольный rerender/прогон после first pass, потому что false
   `Договорённость` напрямую бьет по доверию к отчету.
15. PILOT-19 - прозрачность scoring, потому что менеджеры должны понимать,
   какие звонки и критерии реально вошли в баллы.
16. PILOT-13 - ФИО контакта, чтобы Report Layer не пытался достраивать имя.
17. PILOT-02 / PILOT-06 - controlled schedule flow без UI.

После закрытия P1 переходить к `rop_daily_digest`.
