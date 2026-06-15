# SPLIT-COMPLETE-03 — unified split-run cost summary

Дата подготовки: 2026-06-15
Статус: `implemented_local`

Обновление 2026-06-15: upstream и downstream части реализованы локально.
`call-processing` возвращает `EnsureResponse.costs` и сохраняет upstream cost
summary в `CallProcessingRun.counts_json["costs"]`; `analysis` читает upstream
summary из `EnsureResponse.costs`, сохраняет его как
`source_summary.call_processing_costs` и при наличии поля строит единый
`observability.ai_costs` (`split_ai_costs_v1`). Если upstream/old response не
вернул `costs`, legacy/downstream-only contract сохраняется без падения. Полный
pipeline не запускался.

## Цель

Сделать единый расчет стоимости для split-run, где upstream `call-processing`
строит OnlinePBX/STT/LLM1 artifacts, а downstream `analysis` строит LLM2/LLM3 и
manager reports.

После доработки по каждому run должен быть один понятный cost summary в USDT:

- сколько стоил upstream: source/audio fetch, STT, LLM1;
- сколько стоил downstream: LLM2, LLM3/report composers;
- сколько стоил весь manager-day/report run;
- сколько стоит один transcribed call, analyzed call и manager-day report;
- что было новым расходом текущего run, а что было reuse уже созданных
  artifacts.

UI не нужен. Основной потребитель: автоматический pipeline, `observability`,
KPI-файл и Codex/оператор по запросу.

## Почему это нужно

Текущий механизм `observability.ai_costs` уже считает downstream/reporting
стоимость на стороне `analysis`, но split-run расход физически делится на две
части:

1. `call-processing` делает billable STT/LLM1/provider work;
2. `analysis` переиспользует upstream artifacts и считает LLM2/LLM3.

Сейчас для split-run нельзя надежно ответить “сколько стоил весь прогон” без
ручной реконструкции из нескольких источников. Это мешает пилотным KPI и
контролю бюджета.

## Текущее состояние

Уже есть:

- `core/app/agents/calls/ai_costs.py` — price catalog и расчет downstream
  `observability.ai_costs`;
- STT/LLM metadata в legacy/manual контуре через `interaction.metadata_.ai_routing`;
- `call-processing` service считает provider-call counts:
  `provider_calls_planned`, `provider_calls_made`, quota summary;
- `analysis` в external mode получает `call_processing_run_id`,
  `call_processing_provider_calls_made`, ready/missing counts.

Не хватает:

- upstream `call-processing` cost summary для STT/LLM1;
- передачи upstream cost summary в `EnsureResponse`;
- merge-функции на стороне `analysis`, которая объединяет upstream + downstream;
- явного разделения `current_run_cost_usdt` и reuse/original artifact cost;
- тестов, что split-mode не считает upstream reuse как новый downstream расход.

## Scope

### In scope

- Добавить upstream cost accounting для `call-processing`.
- Расширить `EnsureResponse` backward-compatible полем `costs`.
- В `analysis` external mode сохранить upstream costs в source/build summary.
- Объединить upstream + downstream в `observability.ai_costs`.
- Сохранить совместимость legacy mode.
- Обновить тесты и документацию.

### Out of scope

- UI.
- Онлайн-запросы к billing API провайдеров.
- Изменение бизнес-отчетов менеджерам.
- Запуск полного pipeline.
- Изменение pricing catalog values без отдельного решения.

## Требования к данным

### Upstream `call-processing` должен вернуть

В `EnsureResponse.costs`:

```json
{
  "schema_version": "split_upstream_ai_costs_v1",
  "pricing_catalog_version": "ai_cost_pricing_usdt_2026-06-04_v1",
  "currency": "USDT",
  "cost_status": "available | usage_missing | price_missing | no_billable_work",
  "stt_cost_usdt": 0.0,
  "llm1_cost_usdt": 0.0,
  "total_current_run_cost_usdt": 0.0,
  "reused_artifact_original_cost_usdt": null,
  "cost_per_transcribed_call_usdt": null,
  "by_layer": [],
  "by_request_kind": [],
  "notes": []
}
```

Правила:

- `DRY_RUN` не создает current-run cost.
- Backfill из legacy artifacts не создает current-run cost.
- Уже готовые active artifacts не создают current-run cost.
- Новый STT artifact создает `stt_cost_usdt`.
- Новый LLM1 artifact создает `llm1_cost_usdt`.
- Если usage/model/price отсутствует, статус должен быть `usage_missing` или
  `price_missing`, а не `0`.

### Downstream `analysis` должен вернуть

В `observability.ai_costs`:

```json
{
  "schema_version": "split_ai_costs_v1",
  "pricing_catalog_version": "ai_cost_pricing_usdt_2026-06-04_v1",
  "currency": "USDT",
  "cost_status": "available | partial | usage_missing | price_missing",
  "upstream": {},
  "downstream": {},
  "stt_cost_usdt": 0.0,
  "llm1_cost_usdt": 0.0,
  "llm2_cost_usdt": 0.0,
  "llm3_cost_usdt": 0.0,
  "total_current_run_cost_usdt": 0.0,
  "reused_artifact_original_cost_usdt": null,
  "cost_per_transcribed_call_usdt": null,
  "cost_per_analyzed_call_usdt": null,
  "cost_per_manager_day_report_usdt": null,
  "budget_status": "within_budget | warning | over_budget | no_budget_configured",
  "by_layer": [],
  "by_request_kind": []
}
```

Правила:

- В split-mode итог = upstream current-run cost + downstream current-run cost.
- В legacy mode итог должен остаться совместимым с текущим
  `estimate_run_ai_costs`.
- Если upstream cost missing/partial, общий `cost_status` не должен быть
  `available`.
- `cost_per_analyzed_call_usdt` считать по фактически построенным/готовым
  analyzed calls для report run, а не по всем найденным звонкам.
- `cost_per_manager_day_report_usdt` считать как полный current-run cost на
  сформированный manager-day report.

## Предлагаемые изменения по коду

### 1. Общий cost helper

Файл: `core/app/agents/calls/ai_costs.py`

Добавить функции:

- `estimate_call_processing_costs(...)`
- `merge_split_ai_costs(upstream_costs, downstream_costs, counters, budget)`

Важно: не создавать второй price catalog. Использовать существующий
`PRICING_CATALOG_VERSION` и `_PRICE_CATALOG`.

### 2. Upstream cost collection

Файл: `core/app/agents/call_processing/service.py`

Что сделать:

- во время `_ensure_artifacts()` собирать список newly built STT/LLM1 artifacts
  или lightweight execution entries;
- после ensure сформировать `upstream_costs`;
- не считать dry-run/backfill/reuse как current-run cost;
- вернуть cost summary в `EnsureResponse.costs`; отдельный DB `result_json` в
  текущей схеме не требуется и не является зависимостью downstream merge;
- вернуть `costs` в `EnsureResponse`.

### 3. API/client/schema

Файлы:

- `core/app/agents/call_processing/schemas.py`
- `core/app/agents/call_processing/client.py`
- `core/app/core_shared/api/routes/call_processing.py`
- при необходимости `core/app/agents/call_processing/cli.py`

Что сделать:

- добавить optional `costs: dict[str, Any] = Field(default_factory=dict)` в
  `EnsureResponse`;
- убедиться, что local client и HTTP client сохраняют/передают это поле;
- CLI `ensure` может просто показывать `costs` в JSON output, отдельного UI не
  нужно.

### 4. Downstream merge

Файл: `core/app/agents/calls/reporting.py`

Что сделать:

- в `_ensure_call_processing_source_artifacts()` сохранить
  `response.costs` в `source_summary`;
- в `_build_run_observability()` передать upstream costs в
  `estimate_run_ai_costs` или новую merge-функцию;
- итоговый `observability.ai_costs` должен содержать `upstream` и `downstream`,
  но верхние поля `stt_cost_usdt`, `llm1_cost_usdt`, `llm2_cost_usdt`,
  `llm3_cost_usdt`, `total_current_run_cost_usdt` должны быть доступны на
  прежнем уровне.

### 5. KPI docs

Файлы:

- `docs/MVP1_PILOT_METRICS_MEASUREMENTS.md`
- `docs/call_processing_split/COMPLETION_ROADMAP.md`

Что сделать:

- зафиксировать, что для split-run источник стоимости:
  `observability.ai_costs`, где upstream + downstream уже объединены;
- убрать формулировку, что split cost нужно вручную реконструировать.

## Acceptance Criteria

1. `DRY_RUN` в `call-processing` возвращает `costs.total_current_run_cost_usdt=0`
   или `no_billable_work`.
2. Upstream ensure с built STT/LLM1 возвращает стоимость STT/LLM1.
3. Backfilled/reused upstream artifacts не увеличивают current-run cost.
4. `analysis` external mode показывает один `observability.ai_costs` с
   `upstream`, `downstream` и total.
5. Legacy mode не ломается и сохраняет прежний contract верхних полей
   `observability.ai_costs`.
6. Missing price/usage дает `price_missing` / `usage_missing`, а не ноль.
7. KPI/operator может по одному `observability.ai_costs` ответить:
   - общая стоимость run;
   - STT / LLM1 / LLM2 / LLM3;
   - стоимость analyzed call;
   - стоимость manager-day report;
   - что было current-run, а что reuse.

## Test Plan

Минимальный набор:

- `tests/test_ai_costs.py`
  - upstream STT по duration/billable minutes;
  - upstream LLM1 по token usage;
  - merge upstream + downstream;
  - price_missing / usage_missing;
  - dry-run/no_billable_work.
- `tests/test_call_processing_service.py`
  - ensure response includes `costs`;
  - dry-run does not add current cost;
  - reuse/backfill does not add current cost.
- `tests/test_call_processing_api.py`
  - API serializes `EnsureResponse.costs`.
- `tests/test_call_processing_cli.py`
  - CLI JSON contains `costs`.
- `tests/test_manual_reporting.py`
  - external-service source summary carries upstream costs;
  - `observability.ai_costs` contains merged split total;
  - legacy path still has compatible top-level cost fields.

Проверки перед завершением:

```bash
python3 -m py_compile \
  core/app/agents/calls/ai_costs.py \
  core/app/agents/call_processing/service.py \
  core/app/agents/call_processing/schemas.py \
  core/app/agents/call_processing/client.py \
  core/app/agents/calls/reporting.py

docker compose exec -T api python -m pytest -q \
  /app/tests/test_ai_costs.py \
  /app/tests/test_call_processing_service.py \
  /app/tests/test_call_processing_api.py \
  /app/tests/test_call_processing_cli.py \
  /app/tests/test_manual_reporting.py \
  -k "ai_costs or split_costs or call_processing_costs or observability"

git diff --check
```

## Риски и ограничения

- Если upstream artifacts сейчас не сохраняют достаточно usage metadata, часть
  стоимости может стать `usage_missing`. Это лучше, чем тихий ноль.
- Если часть provider calls была сделана до внедрения cost summary, historical
  run нельзя автоматически восстановить без ручной реконструкции.
- Стоимость остается estimated list-price в USDT, не фактический billing
  invoice.

## Разделение по агентам

### Agent A — upstream call-processing costs

- `service.py`, `schemas.py`, `client.py`, API/CLI response;
- тесты service/API/CLI;
- не трогать downstream report rendering.

### Agent B — downstream merge + KPI docs

- `ai_costs.py`, `reporting.py`;
- тесты `test_ai_costs.py`, `test_manual_reporting.py`;
- docs update.

### Main agent — контроль

- проверить contract совместимость;
- прогнать focused tests;
- обновить roadmap status;
- не запускать полный pipeline без отдельного approval.
