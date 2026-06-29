# PILOT-40: OnlinePBX-all upstream without Bitrix scope dependency

Дата: 2026-06-29
Статус: `implemented_first_pass_live_enabled`

Связанные документы:

- [`docs/PILOT_BACKLOG.md`](PILOT_BACKLOG.md)
- [`docs/ACTIVE_WORK_STATE.md`](ACTIVE_WORK_STATE.md)
- [`docs/PILOT39A_COMPANY_WIDE_UPSTREAM_SCOPE_TZ.md`](PILOT39A_COMPANY_WIDE_UPSTREAM_SCOPE_TZ.md)
- [`docs/PILOT39C_SELECTIVE_DOWNSTREAM_ANALYSIS_SCOPE_TZ.md`](PILOT39C_SELECTIVE_DOWNSTREAM_ANALYSIS_SCOPE_TZ.md)

## Контекст

После `PILOT-39` upstream `call-processing` умеет режим `company`, но этот
режим все еще строит scope из локальных active managers with extension. Это
лучше, чем только ЭДО, но не равно требованию:

```text
сервис транскрибации должен выгружать все звонки из OnlinePBX,
а сервис анализа отдельно должен брать только менеджеров ЭДО.
```

Текущая привязка:

- `CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE=company` строит `manager_ids` и
  `extensions` из таблицы `Manager`;
- `CallProcessingService` фильтрует CDR по `scope.extensions`;
- `OnlinePBXIntake.resolve_manager_mapping()` после local extension lookup
  может обращаться к Bitrix mapper.

## Цель

Добавить отдельный upstream режим, например:

```text
CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE=onlinepbx_all
```

В этом режиме ночной `call-processing`:

- берет CDR напрямую из OnlinePBX за день;
- не строит scope из Bitrix/Manager directory;
- не фильтрует CDR по `manager_ids` или `extensions`;
- сохраняет все звонки с техническим fallback department;
- по возможности может присвоить `manager_id` через локальный unique extension
  lookup, но не должен ходить в Bitrix для расширения/исправления scope;
- строит STT/LLM1 только для звонков с аудио, как и раньше.

Downstream analysis/reporting при этом остается только по ЭДО manager allowlist
из активного `manager_daily` schedule.

## Архитектурное правило

```text
OnlinePBX-all upstream:
  OnlinePBX CDR -> save interactions -> STT -> LLM1 call_card

Selective downstream:
  Bitrix/Manager allowlist ЭДО -> LLM2 -> LLM3 -> reports
```

Наличие transcript/LLM1 artifact по всей компании не должно запускать LLM2/LLM3
по всей компании.

## Что изменить

### 1. Настройки

Файл:

- `core/app/core_shared/config/settings.py`

Добавить значение:

```text
onlinepbx_all
```

в `CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE_VALUES`.

### 2. Scheduled upstream scope resolver

Файл:

- `core/app/core_shared/workers/tasks.py`

В `_daily_upstream_scope()` добавить ветку `onlinepbx_all`:

- `scope_mode = onlinepbx_all`;
- `department_id = None`;
- `fallback_department_id = CALL_PROCESSING_DAILY_UPSTREAM_DEPARTMENT_ID`;
- `manager_ids = []`;
- `extensions = []`;
- `scope_manager_count = 0`;
- `scope_extension_count = 0`;
- `scope_department_count = 0` или `1`, если fallback department задан;
- diagnostics должны явно писать, что upstream не использует manager directory
  для scope, например `onlinepbx_all_no_manager_directory_scope`.

Если fallback department пустой, preflight должен блокировать запуск, потому
что `interactions.department_id` сейчас обязательный.

### 3. CallProcessingService discovery/filtering

Файл:

- `core/app/agents/call_processing/service.py`

Изменить поведение для `onlinepbx_all`:

- не требовать `scope.extensions`;
- CDR `targeted` должен включать все records, прошедшие только технические
  duration filters;
- provider-call forecast/budget должен считаться по всем targeted CDR;
- provider-backed safety gate должен работать так же, как для `company`:
  после read-only CDR discovery и до `get_recording_url`/STT/LLM1, если
  forecast превышает budget;
- `_find_interactions()` должен уметь читать persisted interactions за дату
  без manager/extension filter, но только по `source/date/min/max`.

### 4. OnlinePBXIntake mapping

Файл:

- `core/app/agents/calls/intake.py`

Добавить режим, например `skip_bitrix_mapping` / `onlinepbx_all_mapping`:

- local unique extension lookup по таблице `Manager` можно оставить, чтобы
  ЭДО calls получили `manager_id` и downstream analysis смог их выбрать;
- если local match не найден или extension ambiguous, не обращаться к Bitrix;
- сохранять interaction с `manager_id = null` и fallback department;
- metadata должна отражать это явно:
  - `mapping_source = onlinepbx_all_fallback`;
  - `mapping_diagnostics` содержит `bitrix_mapping_skipped_by_onlinepbx_all`.

### 5. Preflight/acceptance

Файлы:

- `core/report_scripts/company_transcription_rollout_preflight.py`
- `scripts/company_transcription_rollout_preflight.py`
- `core/tests/test_company_transcription_rollout_preflight.py`

Preflight должен считать допустимым не только `company`, но и `onlinepbx_all`.

Для `onlinepbx_all` acceptance:

- `scope_mode_is_onlinepbx_all = true`;
- `has_extensions` не требуется;
- `has_fallback_department = true` обязательно;
- ready/dry-run status `ok|warning|blocked` считается без blocker
  `scheduled_runtime_scope_has_no_extensions`;
- `operator_next_step` должен явно писать, что upstream берет все OnlinePBX CDR,
  а analysis остается selected downstream scope.

### 6. Runtime env

После реализации и тестов переключить live upstream:

```text
CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE=onlinepbx_all
```

в `.env.call-processing`, пересоздать `call_processing_api`,
`call_processing_worker`, `call_processing_beat`, затем проверить:

```bash
python /app/report_scripts/company_transcription_rollout_preflight.py scope-preview --date YYYY-MM-DD --json
python /app/report_scripts/company_transcription_rollout_preflight.py dry-run --date YYYY-MM-DD --json
```

## Чего не делать

- Не расширять `manager_daily` analysis scope.
- Не запускать provider-backed STT/LLM1 в рамках реализации без отдельного
  explicit approval.
- Не менять STT provider/model.
- Не делать Bitrix обязательным для upstream транскрибации.
- Не менять DB schema в этой задаче, если можно сохранить fallback department.

## Acceptance criteria

- `CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE=onlinepbx_all` валиден.
- Scheduled scope preview показывает no manager/extension filter и fallback
  department.
- Dry-run fetches OnlinePBX CDR and targets all records after only technical
  filters.
- Dry-run provider calls made = `0`.
- Analysis schedule остается `manager_daily` по ЭДО manager allowlist.
- Calls with unknown manager can be persisted with `manager_id=null`.
- Known local EDO extension calls still can receive `manager_id`, so downstream
  ЭДО analysis can select them.

## Проверки

Минимально:

```bash
python3 -m py_compile \
  core/app/core_shared/config/settings.py \
  core/app/core_shared/workers/tasks.py \
  core/app/agents/call_processing/service.py \
  core/app/agents/calls/intake.py \
  core/report_scripts/company_transcription_rollout_preflight.py \
  scripts/company_transcription_rollout_preflight.py

git diff --check

docker compose exec -T api python -m pytest -q \
  /app/tests/test_scheduled_call_processing_upstream.py \
  /app/tests/test_call_processing_service.py \
  /app/tests/test_company_transcription_rollout_preflight.py \
  -k "onlinepbx_all or company or dry_run or forecast or scope"
```

После переключения live env:

```bash
docker compose exec -T call_processing_worker python /app/report_scripts/company_transcription_rollout_preflight.py scope-preview --date YYYY-MM-DD --json
docker compose exec -T call_processing_worker python /app/report_scripts/company_transcription_rollout_preflight.py dry-run --date YYYY-MM-DD --json
docker compose exec -T analysis_worker python /app/report_scripts/scheduled_reporting_preflight.py --json status
```

## Результат приемки 2026-06-29

- Код реализован агентом и принят после review.
- Live `.env.call-processing` переключен на
  `CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE=onlinepbx_all`.
- `call_processing_api`, `call_processing_worker`, `call_processing_beat`
  пересозданы с новым env.
- Runtime check в `call_processing_beat`:
  - timezone `Asia/Almaty`;
  - schedule `00:00`;
  - provider call budget `700`;
  - scope mode `onlinepbx_all`.
- Scope preview: no manager/extension scope, fallback department
  `472cda28-ce71-494c-9068-25d3ffbf7399`, blockers `[]`.
- Dry-run за `2026-06-29`:
  - `362` OnlinePBX CDR fetched/targeted;
  - `150` eligible audio calls;
  - `212` no-audio/zero-talk/missed;
  - `294` billable minutes estimate;
  - `provider_calls_estimate=451`;
  - `provider_calls_budget=700`;
  - `provider_calls_made=0`;
  - blockers `[]`;
  - status `warning` только из-за partial LLM1 cost forecast до фактического
    token usage.
- Active analysis schedule не расширен: downstream остается `manager_daily`
  только по ЭДО allowlist Алишер, Илья, Тимур, Толеген.
