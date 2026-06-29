# PILOT-39E: Controlled company-wide transcription rollout

Дата: 2026-06-29
Статус: `implemented_first_pass`

Связанные документы:

- [`docs/PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md`](PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md)
- [`docs/PILOT39A_COMPANY_WIDE_UPSTREAM_SCOPE_TZ.md`](PILOT39A_COMPANY_WIDE_UPSTREAM_SCOPE_TZ.md)
- [`docs/PILOT39B_UNIVERSAL_LLM1_CALL_CARD_TZ.md`](PILOT39B_UNIVERSAL_LLM1_CALL_CARD_TZ.md)
- [`docs/PILOT39C_SELECTIVE_DOWNSTREAM_ANALYSIS_SCOPE_TZ.md`](PILOT39C_SELECTIVE_DOWNSTREAM_ANALYSIS_SCOPE_TZ.md)
- [`docs/PILOT39D_COMPANY_WIDE_COST_QUOTA_MONITORING_TZ.md`](PILOT39D_COMPANY_WIDE_COST_QUOTA_MONITORING_TZ.md)

## Цель

Подготовить controlled rollout, чтобы расширить ночной upstream
`call-processing` на всю компанию безопасно:

```text
OnlinePBX -> STT -> transcript/segments -> LLM1 universal call card
```

При этом LLM2/LLM3-анализ и отчеты должны остаться только по утвержденному
downstream scope, сейчас ЭДО.

## Главный риск

Оператор может проверить вручную собранный `scope`, а scheduled runtime ночью
возьмет другой `scope` из env. Поэтому rollout должен проверять именно тот
scope, который строит scheduled task `ensure_daily_upstream`.

## Что реализовать в first pass

### 1. Rollout preflight CLI без provider STT/LLM calls

Добавить операторский скрипт, например:

```text
core/report_scripts/company_transcription_rollout_preflight.py
```

Команды:

```bash
python core/report_scripts/company_transcription_rollout_preflight.py scope-preview --date YYYY-MM-DD --json
python core/report_scripts/company_transcription_rollout_preflight.py dry-run --date YYYY-MM-DD --json
python core/report_scripts/company_transcription_rollout_preflight.py latest-run-check --date YYYY-MM-DD --json
```

Требования:

- `scope-preview` строит scope через тот же resolver, что scheduled upstream:
  `core/app/core_shared/workers/tasks.py::_daily_upstream_scope`;
- показывает `scope_mode`, `scope_hash`, даты, manager/extension/department
  counts, diagnostics, fallback department, min duration;
- не вызывает OnlinePBX/STT/LLM;
- `dry-run` запускает только `CallProcessingService.ensure(..., mode=DRY_RUN)`
  по этому runtime scope и required artifacts:
  `transcript,transcript_segments,llm1_first_pass`;
- `dry-run` не должен fetch recording URL, запускать STT, LLM1, LLM2, LLM3,
  email, Telegram или report layer;
- `dry-run` возвращает forecast поля из `PILOT-39A/39D`: total/targeted CDR,
  eligible/no-audio/missed/zero-talk, billable minutes estimate,
  provider-call estimate/budget/status, forecast cost/status;
- `latest-run-check` читает latest/covering call-processing run за дату и
  показывает, есть ли ready upstream run, scope hash, status, costs и blockers.

### 2. Acceptance gates

CLI должен возвращать machine-readable summary:

```json
{
  "status": "ok | warning | blocked",
  "date": "YYYY-MM-DD",
  "scope": {
    "scope_mode": "company",
    "scope_hash": "...",
    "scope_manager_count": 0,
    "scope_extension_count": 0,
    "scope_department_count": 0,
    "scope_diagnostics": []
  },
  "forecast": {
    "source_targeted_total": 0,
    "eligible_audio_calls": 0,
    "billable_minutes_estimate": 0,
    "provider_calls_estimate": 0,
    "provider_calls_budget_status": "within_budget",
    "forecast_budget_status": "within_budget",
    "forecast_cost_usdt": null
  },
  "acceptance": {
    "scope_mode_is_company": true,
    "has_extensions": true,
    "has_fallback_department": true,
    "budget_not_blocked": true,
    "no_provider_stt_llm_calls_in_dry_run": true,
    "ready_for_provider_backed_trial": true
  },
  "operator_next_step": "..."
}
```

### 3. Документация rollout-порядка

Обновить roadmap/backlog так, чтобы следующий агент видел порядок:

1. `scope-preview` за выбранный день.
2. `dry-run` за 2-3 рабочих дня, сравнить объемы и budget.
3. Только после ручного утверждения оператора: один provider-backed upstream
   run по company scope.
4. Проверить ЭДО reports через covering lookup.
5. Убедиться, что нет LLM2/LLM3/report generation outside selected
   downstream scope.
6. Только после этого включать permanent company schedule.

## Чего не делать в рамках first pass

- Не запускать provider-backed company-wide upstream.
- Не менять production schedule на company-wide.
- Не отправлять email/Telegram.
- Не расширять LLM2/LLM3/reporting scope.
- Не менять STT provider/model.

## Acceptance criteria

- Есть CLI/скрипт, который строит scheduled runtime scope без ручного JSON.
- `scope-preview` не делает внешних provider calls.
- `dry-run` делает только read-only CDR forecast и не запускает STT/LLM1.
- В summary понятно, можно ли переходить к provider-backed trial.
- Backlog/roadmap/progress обновлены.

## First pass implementation

Добавлен операторский CLI:

```bash
python core/report_scripts/company_transcription_rollout_preflight.py scope-preview --date YYYY-MM-DD --json
python core/report_scripts/company_transcription_rollout_preflight.py dry-run --date YYYY-MM-DD --json
python core/report_scripts/company_transcription_rollout_preflight.py latest-run-check --date YYYY-MM-DD --json
```

Поведение:

- `scope-preview` вызывает runtime resolver
  `core/app/core_shared/workers/tasks.py::_daily_upstream_scope` и не запускает
  `CallProcessingService`, OnlinePBX/STT/LLM/reporting;
- `dry-run` вызывает только `CallProcessingService.ensure(...,
  mode=EnsureMode.DRY_RUN)` по scheduled runtime scope и required artifacts
  `transcript,transcript_segments,llm1_first_pass`;
- `latest-run-check` читает latest exact run, затем covering run через
  `ProcessingRunRepository`, и возвращает `run_id/status/scope_hash`,
  counts/costs/blockers/acceptance;
- все команды возвращают `status`, `scope`, `forecast` где применимо,
  `acceptance`, `blockers` и `operator_next_step`.

Порядок rollout после first pass:

1. Выполнить `scope-preview` за выбранный рабочий день.
2. Выполнить `dry-run` за 2-3 рабочих дня и сравнить объемы, provider-call
   estimate, budget и forecast cost.
3. Только после ручного approval оператора выполнить один provider-backed
   upstream run по company scope.
4. Проверить ЭДО reports через covering lookup.
5. Проверить, что LLM2/LLM3/report generation не запускались вне selected
   downstream scope.
6. Только после этого отдельно включать permanent company schedule.

## Проверки

Минимально:

```bash
python3 -m py_compile \
  core/report_scripts/company_transcription_rollout_preflight.py

git diff --check

docker compose exec -T api python -m pytest -q \
  /app/tests/test_scheduled_call_processing_upstream.py \
  /app/tests/test_call_processing_service.py \
  -k "company or dry_run or forecast or scope"
```

Если добавляются новые unit tests для CLI, включить их в focused запуск.
