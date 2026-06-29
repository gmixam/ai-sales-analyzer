# PILOT-39D: Company-wide STT/LLM1 cost, quota and monitoring

Дата: 2026-06-29
Статус: `implemented_first_pass`

Связанные документы:

- [`docs/PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md`](PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md)
- [`docs/PILOT39A_COMPANY_WIDE_UPSTREAM_SCOPE_TZ.md`](PILOT39A_COMPANY_WIDE_UPSTREAM_SCOPE_TZ.md)
- [`docs/PILOT39C_SELECTIVE_DOWNSTREAM_ANALYSIS_SCOPE_TZ.md`](PILOT39C_SELECTIVE_DOWNSTREAM_ANALYSIS_SCOPE_TZ.md)
- [`docs/call_processing_split/SPLIT_COMPLETE_03_COST_SUMMARY_TZ.md`](call_processing_split/SPLIT_COMPLETE_03_COST_SUMMARY_TZ.md)

## Цель

Перед company-wide provider-backed запуском оператор должен видеть:

- сколько звонков попадет в транскрибацию;
- сколько минут будет биллиться;
- сколько примерно будет стоить STT+LLM1;
- какой provider-call budget нужен;
- остановит ли прогон budget/quota;
- что именно делать, если cost/quota blocker возник.

UI не нужен. Основной просмотр - через Codex/CLI/read-only artifacts и короткие
operator alerts.

## Результат first pass

- Company dry-run/forecast возвращает `provider_calls_estimate`,
  `provider_calls_budget`, `provider_calls_budget_status`,
  `forecast_budget_status`, `forecast_cost_usdt` и
  `forecast_billable_minutes` в summary fields.
- Для `scope_mode=company` provider-backed ensure добавлен safety gate: после
  read-only CDR discovery и до `get_recording_url`/STT/LLM1 прогон блокируется,
  если forecast provider-call estimate превышает budget.
- Blocker пишет понятные поля `reason`, `error_class` и
  `admin_action_required`; scheduled company-wide upstream alert формирует
  короткий operator summary без raw JSON.
- Managers mode и downstream analysis scope не расширялись.

Проверки: `py_compile` измененных Python-файлов OK; `git diff --check` OK;
docker focused pytest
`/app/tests/test_call_processing_service.py
/app/tests/test_scheduled_call_processing_upstream.py
/app/tests/test_run_alerts.py -k "company or forecast or budget or quota or upstream"`
-> `17 passed, 30 deselected`.

## Что уже есть

В проекте уже есть:

- `EnsureResponse.costs`;
- `CallProcessingRun.counts_json["costs"]`;
- `core/app/agents/calls/ai_costs.py` и price catalog;
- `ProviderCallBudget`;
- `_quota_summary(...)`;
- `send_run_alert(...)`;
- `observability.ai_costs` downstream/split merge.

`PILOT-39A` добавил company-wide dry-run CDR forecast без STT/LLM1.

## Что нужно доработать

### 1. Forecast budget status

Для company-wide dry-run/forecast добавить понятный статус:

```text
forecast_budget_status:
  within_budget | warning | over_budget | no_budget_configured | price_missing | usage_missing
```

Минимальные входные данные:

- `eligible_audio_calls`;
- `billable_minutes_estimate`;
- `costs.total_current_run_cost_usdt` или forecast total;
- `provider_calls_estimate`;
- configured `CALL_PROCESSING_DAILY_UPSTREAM_PROVIDER_CALL_BUDGET`;
- optional daily cost budget, если уже есть подходящий env/setting; если нет -
  не вводить сложную новую систему, а явно писать `no_cost_budget_configured`.

### 2. Provider-call estimate

В forecast добавить оценку provider calls:

- 1 CDR request на день;
- до 1 recording URL request на eligible audio call без готового `record_url`;
- 1 STT request на new transcript;
- 1 LLM1 request на new LLM1 card.

Важно: это estimate, не факт. Названия должны быть явными:

- `provider_calls_estimate`;
- `provider_calls_budget`;
- `provider_calls_budget_status`.

### 3. Company-wide run safety gate

Для `scope_mode=company` provider-backed ensure:

- если `provider_call_budget <= 0` - уже blocked, сохранить;
- если forecast/provider estimate явно превышает budget до запуска heavy work,
  вернуть/зафиксировать blocker до STT/LLM1;
- если точный preflight невозможен без CDR, делать blocker после read-only CDR
  discovery и до `get_recording_url`/STT/LLM1.

Цель: не начинать дорогой company-wide прогон, если уже видно, что budget
недостаточен.

### 4. Operator alert summary

Если company-wide upstream:

- forecast over budget;
- provider budget insufficient;
- quota exhausted;
- price missing;

то alert должен быть коротким и человеческим, без raw JSON:

```text
Корпоративная транскрибация за <date> не запущена/остановлена.
Причина: прогноз X provider calls превышает budget Y.
Влияние: STT/LLM1 карточки по всей компании не будут готовы; ЭДО analysis может использовать только уже готовые artifacts.
Действие: увеличить budget или запустить меньший scope.
```

### 5. Persisted summary fields

В task response / run counts / costs добавить или проверить:

- `scope_mode`;
- `provider_calls_estimate`;
- `provider_calls_budget`;
- `provider_calls_budget_status`;
- `forecast_budget_status`;
- `forecast_cost_usdt`;
- `forecast_billable_minutes`;
- `cost_status`;
- `budget_status`;
- `admin_action_required` when blocked.

### 6. Не считать reuse текущим расходом

Если artifacts уже готовы и переиспользуются:

- current-run cost не растет;
- forecast может показывать avoided/reused counts, если это уже легко доступно;
- если недоступно, не делать сложную реконструкцию в 39D.

## Что не делать в PILOT-39D

- не менять LLM1 card schema - это `PILOT-39B`;
- не включать company-wide production schedule - это `PILOT-39E`;
- не запускать реальные STT/LLM1/provider-backed ensure;
- не трогать LLM2/LLM3 analysis scope;
- не чинить unrelated debt `cost_status available vs price_missing`, если он
  не блокирует 39D tests.

## Файлы-ориентиры

- `core/app/agents/call_processing/service.py`
- `core/app/core_shared/workers/tasks.py`
- `core/app/agents/calls/ai_costs.py`
- `core/app/agents/calls/run_alerts.py`
- `core/tests/test_call_processing_service.py`
- `core/tests/test_scheduled_call_processing_upstream.py`
- `core/tests/test_run_alerts.py`
- `core/tests/test_ai_costs.py`

## Минимальный test plan

1. Company dry-run:
   - returns `provider_calls_estimate`;
   - returns `forecast_budget_status`;
   - does not call recording/STT/LLM1.

2. Company ensure with budget below estimate:
   - blocks before recording/STT/LLM1;
   - returns clear `provider_calls_budget_status=over_budget`;
   - exposes `admin_action_required`.

3. Existing managers mode:
   - keeps current behavior and tests green.

4. Alert:
   - company-wide budget/quota alert has short operator summary;
   - no raw JSON in user-facing text.

5. Static/focused checks:

```bash
python3 -m py_compile <changed python files>
git diff --check
docker compose exec -T api python -m pytest -q \
  /app/tests/test_call_processing_service.py \
  /app/tests/test_scheduled_call_processing_upstream.py \
  /app/tests/test_run_alerts.py \
  -k "company or forecast or budget or quota or upstream"
```

## Acceptance criteria

- Перед реальным company-wide запуском можно сделать dry-run и понять
  примерную стоимость/лимиты.
- Недостаточный provider budget останавливает company-wide ensure до дорогих
  provider calls.
- Operator alert объясняет причину и влияние коротко.
- ЭДО downstream analysis scope не меняется.
