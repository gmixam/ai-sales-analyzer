# PILOT-38 - Covering upstream scope handoff

Дата: 2026-06-26
Статус: `implemented_first_pass`

## Кратко

Нужно исправить handoff между `call_processing` и `analysis`: утренний
`manager_daily` анализ должен уметь использовать готовый upstream run, если
этот run шире, чем scope конкретного менеджера, но полностью его покрывает.

Это обязательная доработка для целевой архитектуры:

- транскрибация/STT/LLM1 будет идти по всей компании или большому списку
  менеджеров;
- анализ будет запускаться только по выбранным менеджерам или отделам;
- значит upstream scope часто будет шире, чем analysis scope.

## Что произошло 2026-06-26 на report date 2026-06-25

Ночной `call_processing` отработал успешно:

- run id: `ec04e932-e9e1-472b-8210-cf1ffb1b6b23`;
- report date: `2026-06-25`;
- status: `ready`;
- scope: 4 менеджера ЭДО;
- `interactions_total=55`;
- `artifacts_ready=165`;
- `artifacts_missing=0`;
- `transcripts_built=55`;
- `llm1_first_pass_built=55`;
- cost: `0.881954 USDT`.

Утренний `manager_daily` analysis не нашел этот run и по 3 менеджерам поставил
`upstream_not_ready_before_deadline`:

- Алишер: `missed_pending`, `upstream_not_ready_before_deadline`;
- Тимур: `missed_pending`, `upstream_not_ready_before_deadline`;
- Толеген: `missed_pending`, `upstream_not_ready_before_deadline`;
- Илья: `not_applicable`, `no_calls_for_report_day`.

Причина: exact scope lookup.

Фактический upstream run был создан по общему scope на 4 менеджеров:

```text
5183956de2771f1397738c511105cd0d4ac6c95ac5fc60b122655acec0ba6820
```

А `manager_daily` analysis искал upstream отдельно по каждому менеджеру:

```text
Алишер   698ca5f185dc04383cfd959c70e83044a001ac044c387c2e62e0554c7fd6f4f4
Тимур    e6669d5ba1562257088ac54ae9af9d893ddf57f8a2e495f95f3058c46ff45029
Илья     70750036d181439009955263b76283e9da0ce961227f43583e22082a96862497
Толеген  f254eb92520f8d3782454c274392bbce054e588bfe354bc5800ae63a7d1f66f8
```

Из-за разных hash analysis решил, что upstream отсутствует, хотя данные были
готовы.

## Цель

Если exact upstream run не найден, analysis должен искать covering run:

- та же дата или период полностью покрывает analysis period;
- тот же source;
- тот же department или более широкий company/global scope, если такой scope
  будет введен;
- upstream `manager_ids` пустой или содержит всех менеджеров из analysis
  scope;
- `extensions` пустой или содержит все extensions из analysis scope;
- `required_artifacts` совпадают с нужными analysis artifacts;
- run status `ready`;
- `artifacts_missing=0`.

Если такой run найден, analysis должен считать upstream готовым и продолжать
LLM2/report path для выбранного менеджера/отдела.

## Что нужно изменить

### 1. Call-processing repository/API

Добавлен read-only поиск covering run.

Факт реализации first pass:

- `ProcessingRunRepository.latest_for_scope(...)` оставлен exact-only;
- добавлен `ProcessingRunRepository.latest_covering_for_scope(...)`;
- добавлен read-only endpoint `GET /call-processing/runs/covering`;
- local/HTTP `CallProcessingClient` получил `get_covering_run_for_scope(...)`;
- covering candidate проверяет period, source, department/global scope,
  managers/extensions, duration bounds и `required_artifacts`;
- `ready + artifacts_missing=0` выбирается как готовый upstream;
- если готового covering run нет, возвращается лучший matching diagnostic
  candidate для readiness/status.

Рекомендуемая логика:

1. Сначала оставить текущий exact lookup по `scope_hash`.
2. Если exact run не найден, выполнить bounded поиск кандидатов:
   - `status in ('ready', 'partial', 'running', 'queued', 'failed', 'blocked')`;
   - source совпадает;
   - period candidate покрывает requested period;
   - required artifacts совпадают;
   - candidate scope содержит requested managers/extensions;
   - сначала выбирать `ready + artifacts_missing=0`;
   - если ready нет, возвращать наиболее информативный candidate для
     diagnostics/readiness.

Файлы:

- `core/app/agents/call_processing/repositories.py`
- `core/app/core_shared/api/routes/call_processing.py`
- `core/app/agents/call_processing/client.py`
- `core/app/agents/call_processing/schemas.py`, если нужен новый response field.

### 2. Analysis handoff

`CallsManualReportingOrchestrator._ensure_call_processing_source_artifacts`
использует covering lookup после exact lookup, если exact run не найден.

Ожидаемое поведение:

- exact run found ready -> как сейчас;
- exact not found, covering run found ready -> `call_processing_readiness=ready`;
- в summary сохранить:
  - `call_processing_run_id`;
  - `call_processing_scope_hash`;
  - `call_processing_scope_match=covering`;
  - `call_processing_requested_scope_hash`;
  - `call_processing_covering_scope_hash`;
  - `call_processing_ensure_skipped=true`;
- artifacts для LLM2/report выбирать только по requested interactions, а не по
  всему covering scope.

Факт реализации first pass:

- exact ready сохраняет прежний путь и получает
  `call_processing_scope_match=exact`;
- covering ready возвращает `call_processing_readiness=ready`,
  `call_processing_ensure_skipped=true`,
  `call_processing_scope_match=covering`,
  `call_processing_requested_scope_hash`,
  `call_processing_covering_scope_hash`;
- downstream artifact reads не переключены на covering scope: они по-прежнему
  строятся через selected/requested interactions.

Файлы:

- `core/app/agents/calls/reporting.py`
- `core/report_scripts/scheduled_reporting_preflight.py`, если audit/status
  должен показывать match type;
- `scripts/scheduled_reporting_preflight.py` синхронизировать, если менялся
  core script.

### 3. Диагностика

В observability/post-run audit желательно показывать, что upstream найден через
covering scope, чтобы оператор видел:

```text
upstream_ready via covering run
requested_scope_hash=...
covering_scope_hash=...
```

Это важно для будущего режима "транскрибируем всех, анализируем выбранных".

### 4. Тесты

Добавить focused tests:

- exact scope lookup по-прежнему работает;
- covering run на 4 менеджеров покрывает запрос одного менеджера;
- covering run с другим днем не подходит;
- covering run с другим department/source не подходит;
- covering run без нужного manager id не подходит;
- covering run с `artifacts_missing > 0` не считается `ready`;
- `manager_daily` analysis при covering ready не возвращает
  `upstream_missing`;
- artifacts для analysis остаются ограничены requested manager/day.

Ожидаемые тестовые файлы:

- `core/tests/test_call_processing_api.py`;
- `core/tests/test_call_processing_reporting_integration.py`;
- возможно `core/tests/test_scheduled_call_processing_upstream.py`.

## Не входит в задачу

- Не менять STT/LLM1 provider.
- Не менять расписание.
- Не запускать production прогон автоматически.
- Не пересылать отчеты менеджерам.
- Не расширять анализ на всю компанию.
- Не менять бизнес-логику отбора звонков для LLM2.

## Проверка после реализации

Минимально:

```bash
git diff --check
python3 -m py_compile \
  core/app/agents/call_processing/repositories.py \
  core/app/core_shared/api/routes/call_processing.py \
  core/app/agents/call_processing/client.py \
  core/app/agents/calls/reporting.py
docker compose exec -T analysis_api python -m pytest -q \
  tests/test_call_processing_api.py \
  tests/test_call_processing_reporting_integration.py \
  tests/test_scheduled_call_processing_upstream.py
```

First-pass verification status:

- host `py_compile` по измененным Python-файлам: OK;
- docker focused pytest pack: см. финальный отчет задачи.

Live read-only validation:

```bash
docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py \
  post-run-audit --date 2026-06-25
```

После кода, но до боевой отправки, нужен controlled recovery/rerun только
analysis/report layer за `2026-06-25`, используя уже готовые STT/LLM1:

- не повторять STT/LLM1;
- построить LLM2/report по Алишеру, Тимуру, Толегену;
- сначала отправить оператору/в Telegram на проверку;
- после проверки решить вопрос с manager email delivery.

## Критерий приемки

На данных `2026-06-25` analysis должен найти общий ready upstream run
`ec04e932-e9e1-472b-8210-cf1ffb1b6b23` как covering run для per-manager
analysis scope и не ставить `upstream_missing`.

Для будущего режима "транскрибируем всю компанию, анализируем ЭДО" analysis
должен использовать общий upstream run как источник готовых STT/LLM1, но
анализировать только заданных менеджеров.
