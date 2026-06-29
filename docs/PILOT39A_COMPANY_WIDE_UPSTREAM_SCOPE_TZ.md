# PILOT-39A: Company-wide upstream scope and dry-run forecast

Дата: 2026-06-29
Статус: `implemented_first_pass`

Связанные документы:

- [`docs/PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md`](PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md)
- [`docs/PILOT_BACKLOG.md`](PILOT_BACKLOG.md)
- [`docs/call_processing_split/COMPLETION_ROADMAP.md`](call_processing_split/COMPLETION_ROADMAP.md)

## Цель

Подготовить `call-processing` к ночной транскрибации по всей компании:

```text
OnlinePBX -> STT -> transcript/segments -> LLM1 call card
```

При этом `analysis/reporting` не должен автоматически расширяться на всю
компанию. LLM2/LLM3 и отчеты остаются только для выбранного downstream scope.

## Текущее ограничение

Сейчас scheduled upstream строится в
`core/app/core_shared/workers/tasks.py::_daily_upstream_scope()` только из:

- `CALL_PROCESSING_DAILY_UPSTREAM_DEPARTMENT_ID`;
- `CALL_PROCESSING_DAILY_UPSTREAM_MANAGER_IDS`.

Если `department_id` пустой, `CallProcessingService._discover_and_persist_source_calls()`
вообще не идет в OnlinePBX:

```python
if mode is EnsureMode.DRY_RUN or not scope.department_id or not hasattr(self.session, "query"):
    return counts
```

Также `OnlinePBXIntake.get_manager_by_extension()` ищет менеджера только внутри
одного отдела fallback:

```python
Manager.extension == extension
Manager.department_id == self.department_id
Manager.active.is_(True)
```

Для company-wide режима это нужно изменить без поломки текущего ЭДО pilot
scope.

## Принципы

1. **Не запускать provider calls в dry-run.**
2. **Не расширять downstream analysis.** Company-wide upstream только готовит
   STT/LLM1 artifacts; LLM2/LLM3/reporting выбирают свой scope отдельно.
3. **Сохранять department/managers режим как fallback.**
4. **Не включать production schedule автоматически.** Реальный switch будет в
   отдельной задаче rollout.
5. **Не менять STT provider/model.**

## Требуемое поведение

### 1. Новый режим upstream scope

Добавить конфигурацию режима scheduled upstream, например:

```text
CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE=managers|department|company
```

Ожидаемая логика:

- `managers` - текущий режим: department + explicit manager_ids.
- `department` - все active managers с extension внутри указанного department.
- `company` - все active managers с extension по всем отделам, кроме
  технических/исключенных пользователей.

Если env не задан, default должен сохранить текущую production-семантику:
`managers`.

### 2. Company-wide manager directory

Для `company` scope определить активных сотрудников так:

- источник: локальная таблица `managers`, которая обновляется через Bitrix sync;
- включаем только `Manager.active is True`;
- нужен непустой `Manager.extension`;
- исключаем технических пользователей по явным признакам:
  - имя содержит `Робот`;
  - email пустой или явно technical/no-reply, если такое уже принято в проекте;
  - позже можно добавить env blacklist, но не делать сложный UI.

Важно: если локальная таблица неполная, dry-run должен показать diagnostics, а
не молча считать, что вся компания = текущие 4 менеджера.

### 3. Scope model

Не обязательно делать глобальный `department_id=None` везде, если это рискованно.
Допустимые варианты:

- добавить company-wide wrapper, который строит `extensions` всех активных
  менеджеров и использует safe fallback department для `OnlinePBXIntake`;
- либо расширить `ProcessingScope`/service так, чтобы `department_id=None`
  означал company-wide discovery.

Выбрать менее рискованный вариант, совместимый с текущими tests и
`PILOT-38 covering upstream`.

### 4. Intake / manager mapping

Company-wide сохранение interaction должно корректно определять реальный
department/manager по extension:

- сначала искать active manager по extension среди всех отделов;
- если найден один - использовать его `manager_id` и `department_id`;
- если найдено несколько - не выбирать случайно, писать diagnostics
  `ambiguous_local_extension_match`;
- если локально не найден - использовать существующий Bitrix mapping;
- если Bitrix тоже не нашел - fallback department сохраняется только как
  технический fallback, с diagnostics `manual_fallback`.

Текущий department-only поиск должен сохраниться для department/managers
режимов, чтобы не менять поведение пилота без необходимости.

### 5. Dry-run / forecast

Нужен безопасный dry-run/forecast без STT/LLM1 provider calls, который показывает:

- report_date;
- scope_mode;
- departments/managers/extensions в scope;
- source_records_total;
- source_targeted_total;
- eligible_audio_calls;
- no_audio / missed / zero talk;
- billable_minutes estimate;
- estimated STT cost;
- estimated LLM1 card cost;
- estimated total STT+LLM1 cost;
- warnings/diagnostics.

Можно расширить existing `ensure_daily_call_processing_upstream(dry_run=True)`
или добавить отдельный helper/summary, но dry-run не должен вызывать
`get_recording_url`, STT, LLM1.

### 6. Budget guard

Provider-backed ensure в company mode должен требовать явный budget:

- если budget <= 0 - `blocked`;
- если forecast превышает budget - warning или blocked согласно существующему
  паттерну проекта;
- dry-run должен работать даже при budget=0.

### 7. Observability

В task response / run counts добавить понятные поля:

- `scope_mode`;
- `scope_manager_count`;
- `scope_extension_count`;
- `scope_department_count`;
- `scope_diagnostics`;
- `forecast_costs` или compatible cost summary.

## Что не делать в PILOT-39A

- не менять LLM1 prompt/card schema - это `PILOT-39B`;
- не включать company-wide production schedule - это `PILOT-39E`;
- не расширять LLM2/LLM3 analysis - это запрещено;
- не запускать реальные STT/LLM1 provider calls в ходе реализации без отдельного
  указания пользователя.

## Файлы-ориентиры

- `core/app/core_shared/config/settings.py`
- `core/app/core_shared/workers/tasks.py`
- `core/app/agents/call_processing/schemas.py`
- `core/app/agents/call_processing/service.py`
- `core/app/agents/calls/intake.py`
- `core/app/agents/calls/bitrix_readonly.py`
- `core/tests/test_scheduled_call_processing_upstream.py`
- `core/tests/test_call_processing_service.py`
- `core/tests/test_call_processing_api.py`

## Минимальный test plan

1. Unit tests:
   - default mode remains current `managers`;
   - `department` mode resolves all active managers with extension in department;
   - `company` mode resolves all active managers with extension across
     departments, excluding technical/inactive/no-extension users;
   - company dry-run does not call STT/LLM1/get_recording_url;
   - ambiguous local extension does not randomly assign manager;
   - existing EDO scheduled upstream tests remain green.

2. Static checks:
   - `python3 -m py_compile` for changed Python files;
   - `git diff --check`.

3. Focused docker tests:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_scheduled_call_processing_upstream.py \
  /app/tests/test_call_processing_service.py \
  /app/tests/test_call_processing_api.py \
  -k "daily_upstream or company or department or dry_run or scope"
```

## Acceptance criteria

- Можно получить company-wide dry-run forecast без provider calls.
- Current pilot upstream config без нового env ведет себя как раньше.
- Company-wide upstream не запускает LLM2/LLM3/reporting.
- Summary явно показывает scope mode, количество менеджеров/extensions,
  прогноз стоимости и diagnostics.
- Следующий агент может перейти к `PILOT-39C` или `PILOT-39D` без повторного
  разбора текущего ограничения.

## Implementation status 2026-06-29

First pass реализован:

- добавлен `CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE=managers|department|company`,
  default `managers`;
- `department/company` scope строится из local `managers`: active + extension,
  исключаются inactive/no-extension/technical users (`Робот`, no-reply/technical email);
- company dry-run делает read-only CDR forecast без `get_recording_url`, STT,
  LLM1, email, Telegram или reporting;
- provider-backed ensure остается под `provider_call_budget > 0`;
- company-wide mapping ищет unique local extension across departments и не
  назначает manager при `ambiguous_local_extension_match`;
- response/planned diagnostics содержат `scope_mode`, manager/extension/
  department counts, CDR forecast counters и forecast costs.

Остатки для следующих задач:

- `PILOT-39B`: универсальная LLM1 card schema/prompt не менялись;
- `PILOT-39C`: downstream `analysis_scope`/`upstream_scope` нужно разделить
  явно, включая риск manager_daily schedule с пустыми `manager_ids`;
- `PILOT-39D`: cost/quota/monitoring нужно довести до production-grade,
  особенно LLM1 estimate без token usage;
- `PILOT-39E`: controlled rollout и production schedule switch не выполнялись.
