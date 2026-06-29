# PILOT-39C: Selective downstream analysis scope

Дата: 2026-06-29
Статус: `implemented_first_pass`

Связанные документы:

- [`docs/PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md`](PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md)
- [`docs/PILOT39A_COMPANY_WIDE_UPSTREAM_SCOPE_TZ.md`](PILOT39A_COMPANY_WIDE_UPSTREAM_SCOPE_TZ.md)
- [`docs/PILOT_BACKLOG.md`](PILOT_BACKLOG.md)

## Цель

Зафиксировать техническую границу:

```text
company-wide upstream STT+LLM1 != company-wide LLM2/LLM3/reporting
```

`call-processing` может подготовить STT/LLM1 по всей компании, но
`manager_daily` analysis/reporting должен запускаться только по явно заданному
downstream scope: сейчас это утвержденные менеджеры ЭДО.

## Почему задача нужна

Аудит показал:

- сам `call-processing.ensure_daily_upstream` не вызывает LLM2/LLM3/reporting;
- `PILOT-38` covering lookup использует широкий upstream только как источник
  готовых artifacts;
- реальный риск находится в downstream schedule: если `manager_daily` schedule
  создан с пустым `manager_ids`, общий путь может превратить пустой set в
  department-wide analysis/reporting.

Нужно сделать так, чтобы `manager_daily` не мог случайно стать отчетом по всему
отделу/компании из-за пустого или неправильно расширенного scope.

## Требуемое поведение

### 1. Explicit allowlist для `manager_daily`

Для production/review `manager_daily` schedule должен быть явный непустой список
`manager_ids`.

Если `preset=manager_daily` и `manager_ids` пустой:

- schedule не должен запускать LLM2/LLM3/reporting по department-wide scope;
- должен быть понятный skipped/blocked diagnostic status;
- оператор должен видеть причину: `manager_daily_manager_scope_not_configured`
  или близкий код.

Важно: не ломать другие presets, если они легально работают по department-wide
scope.

### 2. Не копировать upstream company managers в reporting schedule

Никакой код не должен брать resolved `company` upstream managers/extensions и
автоматически записывать их в `ReportingSchedule.manager_ids`.

`CALL_PROCESSING_DAILY_UPSTREAM_SCOPE_MODE=company` влияет только на
`call-processing` upstream, не на `report_schedules`.

### 3. Diagnostics: upstream scope отдельно, analysis scope отдельно

В scheduled/manager_daily observability или summary нужно явно показывать:

- `analysis_scope_source`, например `reporting_schedule.manager_ids`;
- `analysis_department_id`;
- `analysis_manager_ids`;
- `analysis_manager_count`;
- `analysis_date_from`;
- `analysis_date_to`;
- если используется covering upstream:
  - `call_processing_scope_match`;
  - `call_processing_requested_scope_hash`;
  - `call_processing_covering_scope_hash`;
  - `upstream_scope_wider_than_analysis` when detectable.

Цель diagnostics: оператор должен глазами видеть, что upstream был широкий, но
analysis остался узким.

### 4. Negative test with non-pilot manager

Добавить тест, где:

- есть pilot manager и non-pilot manager;
- upstream/covering может быть wider;
- `manager_daily` выбирает только pilot manager;
- non-pilot interactions не попадают в selected interactions / report scope;
- LLM2/LLM3/reporting не запускается для non-pilot manager.

Можно покрыть на уровне scheduled service / reporting filters без реальных
LLM/STT/provider calls.

### 5. Schedule creation/update guard

Если в проекте есть CLI/API/helper для создания `manager_daily` schedule, добавить
guard там тоже:

- создание `manager_daily` без `manager_ids` должно падать/возвращать понятную
  ошибку;
- уже существующие schedules проверяются при runtime scan, чтобы старый bad
  schedule не ушел в department-wide.

## Что не делать в PILOT-39C

- не менять LLM1 card schema - это `PILOT-39B`;
- не менять company-wide upstream scope реализацию - это `PILOT-39A`;
- не включать production company-wide schedule - это `PILOT-39E`;
- не запускать реальные STT/LLM/report/email/Telegram;
- не делать UI.

## Файлы-ориентиры

- `core/app/agents/calls/scheduled_reporting.py`
- `core/app/agents/calls/reporting.py`
- `core/app/agents/call_processing/client.py`
- `core/app/agents/call_processing/repositories.py`
- `core/tests/test_scheduled_reporting.py`
- `core/tests/test_call_processing_reporting_integration.py`
- `core/tests/test_manual_reporting.py`

## Минимальный test plan

1. `manager_daily` schedule with empty `manager_ids`:
   - does not call report runner;
   - returns/skips/records clear diagnostic blocker.

2. `manager_daily` with explicit manager allowlist:
   - still runs the existing per-manager path;
   - selected `ReportRunFilters.manager_ids` contains exactly one pilot manager.

3. Covering upstream + narrow analysis:
   - reporting can use covering upstream;
   - selected interactions remain limited to requested manager ids;
   - diagnostics show requested/covering scope and analysis scope.

4. Static checks:

```bash
python3 -m py_compile <changed python files>
git diff --check
```

5. Focused docker tests:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_scheduled_reporting.py \
  /app/tests/test_call_processing_reporting_integration.py \
  -k "manager_daily or scope or covering or upstream"
```

## Acceptance criteria

- Empty `manager_daily.manager_ids` cannot silently produce department-wide
  analysis/reporting.
- Company-wide upstream does not change downstream schedule scope.
- Diagnostics clearly separate upstream scope and analysis scope.
- Existing pilot `manager_daily` schedules with explicit managers keep working.
