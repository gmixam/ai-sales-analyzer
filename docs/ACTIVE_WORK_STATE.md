# Активное состояние работ

Дата обновления: 2026-06-04

Статус: `completed`

## Назначение

Этот файл является короткой оперативной карточкой текущего этапа, а не основным журналом прогресса проекта.

Основные файлы проекта:

```text
docs/PROGRESS.md   -> общий хронологический прогресс проекта
docs/DECISIONS.md  -> принятые архитектурные и продуктовые решения
docs/CONTEXT_INDEX.md -> порядок входа в контекст
```

`ACTIVE_WORK_STATE.md` нужен только для быстрого восстановления текущего состояния, если:

- чат оборвался;
- серверная связь восстановилась без истории чата;
- пришлось создать новый чат;
- работу продолжает другой агент;
- нужно понять, где остановились и что делать дальше.

Файл не должен дублировать подробную историю из `PROGRESS.md`. В нем фиксируется только текущий этап, pending gates, последняя безопасная точка восстановления и следующий практический шаг.

После завершения этапа итог должен быть перенесен в `PROGRESS.md` и, если есть новое правило/решение, в `DECISIONS.md`. Сам `ACTIVE_WORK_STATE.md` затем может быть очищен или переведен на следующий активный этап.

## Глобальное правило

Перед началом новой рабочей сессии агент должен открыть:

```text
/root/ai-sales-analyzer/docs/ACTIVE_WORK_STATE.md
/root/ai-sales-analyzer/docs/RUNTIME_PROFILES.md
/root/ai-sales-analyzer/docs/CONTEXT_INDEX.md
/root/ai-sales-analyzer/docs/DECISIONS.md
/root/ai-sales-analyzer/docs/PROGRESS.md
```

Если `ACTIVE_WORK_STATE.md` содержит `status: waiting_for_user`, агент не должен продолжать реализацию до получения ответа пользователя.

## Статусы

```text
planning
in_progress
waiting_for_user
blocked
ready_for_review
completed
paused
```

## Уведомление пользователя

Когда требуется действие пользователя, агент должен:

1. остановить дальнейшую реализацию на безопасной точке;
2. обновить этот файл:
   - `status: waiting_for_user`;
   - что именно нужно от пользователя;
   - какие варианты решения есть;
   - что будет сделано после ответа;
3. написать в чат короткое сообщение с явным маркером:

```text
НУЖНО ВАШЕ УТВЕРЖДЕНИЕ
```

4. если доступен безопасный operator/test Telegram-канал, отправить короткий Telegram ping только в тестовый/операторский чат, без бизнес-доставки менеджерам.

Важно: Telegram ping — вспомогательный канал. Source of truth остается этот файл и чат.

Для истории проекта source of truth остается `docs/PROGRESS.md`; эта карточка хранит только оперативное состояние.

## Текущая задача

Тема: MVP-1 pilot report delivery after report-layer fixes.

Текущий audit/fix pass закрыт пользователем после визуальной проверки отчетов
за `2026-06-03` и фактической business-email доставки менеджерам.
Новый runtime default: `AI_LLM2_INPUT_PROFILE=compact`.

Новых веток, runtime-профилей или delivery-режимов для последних исправлений
не создавалось. Работа выполнена в существующей ветке
`feature/llm2-block-ready-v15`; для доставки использован уже существующий
режим `business_email_only`.

## 2026-06-04: отчеты 2026-06-03 отправлены менеджерам

Контекст:

- пользователь проверил Telegram test delivery отчетов за `2026-06-03` по
  Алишеру, Тимуру и Толегену;
- были замечания к `Ситуации дня`, пустому `Голосу клиента`, времени, статусам
  и тексту письма;
- после исправлений отчеты отправлены менеджерам на бизнес-почту.

Что внедрено:

- `Ситуация дня`: LLM3 daily composer больше не откатывается в короткую
  proof-card карточку, если нет exact-stage candidate по дневному фокусу.
  При отсутствии exact-stage candidate разрешен strongest evidence-backed
  related manager-gap candidate с честным объяснением связи с фокусом.
- `Ситуация дня`: если LLM3 меняет `stage_code`, `proof_type` или
  `proof_strength` как label, хороший narrative сохраняется, но канонические
  значения остаются из исходного проверенного кандидата.
- `Голос клиента`: пустой блок скрывается из PDF вместо заголовка с
  placeholder-комментарием.
- Время в report-facing call references приведено к `UTC+5` через
  `core/app/agents/calls/report_time.py`.
- `БАЛЛЫ ПО ЭТАПАМ`: колонка `Звонков` переименована в `Оценено`.
- `sale_processing` и `sale_final` получили русские stage labels.
- Support/internal/not eligible calls больше не должны выглядеть как
  manager-facing `Ошибка анализа`.
- Текст manager_daily email summary заменен на верхний блок отчета:
  найдено в телефонии, содержательных, исключено, вошло в коучинговый разбор,
  статусы и `Балл дня`.

Фактическая business-email доставка:

- Алишер: `g.alisher@dogovor24.kz`, CC `sales@dogovor24.kz`,
  `email_status=delivered`.
- Тимур: `zh.timur@dogovor24.kz`, CC `sales@dogovor24.kz`,
  `email_status=delivered`.
- Толеген: `zh.tolegen@dogovor24.kz`, CC `sales@dogovor24.kz`,
  `email_status=delivered`.

Команда delivery была report-only:

```bash
docker compose exec -T api python -m app.agents.calls.manual_reporting_runner \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --preset manager_daily \
  --mode report_from_ready_data_only \
  --date-from 2026-06-03 \
  --date-to 2026-06-03 \
  --manager-id d42e8246-772e-4a04-bbe7-2b88f45db695 \
  --manager-id 656abe58-7c23-476a-a9f6-d76305cf42e0 \
  --manager-id 5638c619-8732-435c-9664-a7188f13effd \
  --analysis-instruction-version pilot_20260603_compact_v1 \
  --delivery-mode business_email_only \
  --send-business-email
```

Верхний runner status может быть `partial` из-за исторических
`analysis_reuse_rejected:*:instruction_version_mismatch`, но по трем отчетам
delivery status был `delivered`.

Следующий практический шаг:

1. При новом полном прогоне использовать compact default и реальные
   OpenAI-compatible маршруты, если пользователь не попросит иной профиль.
2. После каждого полного дневного прогона заполнять KPI/стоимость по
   `docs/MVP1_PILOT_METRICS_MEASUREMENTS.md`.
3. Business delivery менеджерам запускать только после operator review или
   явного указания пользователя.

## 2026-06-04: LLM2 compact input принят как default

Решение пользователя:

- для будущих прогонов использовать `AI_LLM2_INPUT_PROFILE=compact`;
- compact больше не должен быть только тестовым override;
- full profile остается только как legacy/debug fallback до отдельного решения
  о физическом удалении.

Что должно быть перед прогоном 3 менеджеров за `2026-06-03`:

- пересоздать runtime containers после изменения дефолта;
- подтвердить в `api` container:
  `CallsAnalyzer._llm2_input_profile() == "compact"`;
- подтвердить, что:
  `AI_LLM_EXECUTION_MODE=openai_compatible`,
  `AI_LLM_SUBAGENT_RUNTIME_ENABLED=false`,
  `AI_LLM_SIMULATION_ENABLED=false`,
  `AI_LLM2_FIXED_ACCOUNT_ALIAS=llm2_main`,
  `AI_LLM3_FIXED_ACCOUNT_ALIAS=llm3_main`;
- запускать только `telegram_test_only`, без business delivery менеджерам;
- после каждого manager-day фиксировать KPI и `observability.ai_costs` в USDT.

## 2026-06-03: Report Layer правки + полный прогон Тимура 2026-06-01

Контекст:

- пользователь попросил доработать механизм отчета и затем сразу запустить
  полный день Тимура за `2026-06-01` вместе со STT;
- режим запуска: реальные OpenAI-compatible маршруты, без Codex subagents и
  без local simulation;
- доставка: `telegram_test_only`, только оператору/пользователю.

Что внедрено перед прогоном:

- `RL-T2`: диагностика meaningful/selection model теперь явно показывает
  transcript-priority policy и excluded call samples.
- `RL-T6`: `Все звонки дня -> Суть звонка` теперь берет outcome/follow-up
  essence выше generic summary, увеличен visible context limit, trim старается
  сохранить итог/договоренность.
- `RL-T7`: добавлен класс доказательности `call_list_essence` и отдельная
  evidence policy для справочной сути звонка.
- `RL-T8`: call breakdown diagnostics теперь различают смысловые proof issues
  и format issues; небольшие format issues нормализуются/диагностируются
  вместо полного немого провала.

Runtime hardening во время прогона:

- `core/app/agents/calls/orchestrator.py`: `agreements` в виде списка строк
  теперь нормализуются перед DB mirror и не валят persist analysis.
- `core/app/agents/calls/reporting.py`: Report Layer пропускает не-dict элементы
  в `score_by_stage`, `criteria_results`, `gaps`, `recommendations`,
  `evidence_fragments`, `product_signals` при агрегациях отчета.

Проверки:

- `python3 -m py_compile core/app/agents/calls/reporting.py core/app/agents/calls/orchestrator.py ...` -> OK.
- `docker compose exec -T api python -m pytest -q /app/tests/test_ai_provider_routing.py -k "string_agreement_items or raw_llm_response"` -> `2 passed`.
- `docker compose exec -T api python -m pytest -q /app/tests/test_manual_reporting.py -k "stage_scores_ignore_non_dict or stage_scores_use_all_ready_meaningful_day_analyses"` -> `2 passed`.
- До запуска Тимура также проходили focused Report Layer checks:
  `call_list_context`, `sfb5`, `a2_a3`, `selection_model`,
  `meaningful_call`, `call_breakdown_quality_gate`, `call_list`.

Команда последнего успешного запуска:

```bash
docker compose exec -T \
  -e AI_LLM_EXECUTION_MODE=openai_compatible \
  -e AI_LLM_SUBAGENT_RUNTIME_ENABLED=false \
  -e AI_LLM_SUBAGENT_RUNTIME_LAYERS= \
  -e AI_LLM_SIMULATION_ENABLED=false \
  -e LLM3_ENABLED=true \
  -e AI_LLM2_ANALYSIS_MODE=layered \
  -e AI_LLM2_INPUT_PROFILE=full \
  -e AI_STT_FIXED_ACCOUNT_ALIAS=stt_main \
  -e AI_LLM1_FIXED_ACCOUNT_ALIAS=llm1_main \
  -e AI_LLM2_FIXED_ACCOUNT_ALIAS=llm2_main \
  -e AI_LLM3_FIXED_ACCOUNT_ALIAS=llm3_main \
  api python -m app.agents.calls.manual_reporting_runner \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --preset manager_daily \
  --mode build_missing_and_report \
  --date-from 2026-06-01 \
  --date-to 2026-06-01 \
  --manager-id 656abe58-7c23-476a-a9f6-d76305cf42e0 \
  --analysis-instruction-version timur_20260601_report_layer_fullstack_v1 \
  --delivery-mode telegram_test_only
```

Результат прогона:

- PDF доставлен в Telegram test-only: `message_id=368`.
- Artifact: `Ежедневный отчет - Тимур Жуматаев - 1 июня 2026.pdf`.
- Email delivery skipped, как и требовалось.
- STT route: `stt_main / whisper-1`.
- LLM1 route: `llm1_main / gpt-5.4-nano`.
- LLM2 route: `llm2_main / gpt-5.4-mini`.
- В observability последнего результата LLM3 route не появился:
  `report_composer.enabled=false`, отчет построен deterministic/template layer,
  а не LLM3-composer output.

Статус результата:

- Runner status: `blocked`.
- Report status: `review_required`.
- Readiness: `signal_report`.
- Причина: `incomplete_day_call_processing`.
- Relevant calls for report day: `34`.
- Ready analyses used in report: `13`.
- Analysis coverage: `38.2%`.
- Manager-facing completeness blocked by `analysis_error=7`.
- В errors также есть 8 случаев
  `Analyzer did not admit call into layered LLM-2`; это нужно отдельно
  разобрать, потому что часть звонков не дошла до LLM2 не из-за Report Layer.

Следующий практический шаг:

1. Не считать этот отчет полноценным manager-facing отчетом; это operator
   preview / incomplete report.
2. Разобрать `analysis_build_failed:*:Analyzer did not admit call into layered
   LLM-2` по 7-8 звонкам Тимура за `2026-06-01`.
3. Проверить, это корректное LLM1 admission decision или слишком жесткое
   правило допуска к layered LLM2.
4. Если нужно проверить именно LLM3-composer, включить/проверить Report
   Composer path отдельно: в последнем успешном delivery LLM3 фактически не
   исполнялся, несмотря на `LLM3_ENABLED=true`.

### 2026-06-03: Ready-data-only отчет с реальным LLM3

После уточнения пользователя выполнен отдельный запуск только формирования
отчета на уже сохраненных данных:

```bash
docker compose exec -T \
  -e AI_LLM_EXECUTION_MODE=openai_compatible \
  -e AI_LLM_SUBAGENT_RUNTIME_ENABLED=false \
  -e AI_LLM_SIMULATION_ENABLED=false \
  -e LLM3_ENABLED=true \
  -e AI_LLM3_FIXED_ACCOUNT_ALIAS=llm3_main \
  api python -m app.agents.calls.manual_reporting_runner \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --preset manager_daily \
  --mode report_from_ready_data_only \
  --date-from 2026-06-01 \
  --date-to 2026-06-01 \
  --manager-id 656abe58-7c23-476a-a9f6-d76305cf42e0 \
  --analysis-instruction-version timur_20260601_report_layer_fullstack_v1 \
  --delivery-mode telegram_test_only
```

Лог:

```text
review_packages/timur_20260601_llm3_report_only_20260603/run.log
```

Результат:

- STT/LLM1/LLM2 не строились заново:
  `transcripts_built=0`, `analyses_built=0`.
- PDF доставлен в Telegram test-only:
  `Ежедневный отчет - Тимур Жуматаев - 1 июня 2026.pdf`,
  `message_id=369`.
- Реальный LLM3 подтвержден diagnostics:
  - `situation_day_daily_composer_v2`: `llm3_used=true`,
    route `llm3_main / gpt-5.4-mini`, `execution_status=executed`,
    `request_kind=situation_day_daily_composer`;
  - `call_breakdown_composer`: `llm3_used=true`,
    route `llm3_main / gpt-5.4-mini`, `execution_status=executed`,
    `request_kind=call_breakdown_composer`;
  - `call_tomorrow_wording_composer_v1` был вызван, но результат отклонен
    quality gate: `llm3_used=false`,
    `llm3_rejection_reason=...unsupported_claim:кп`.

Статус отчета остался `blocked / review_required`, потому что это тот же
неполный набор готовых анализов:

- `ready_analyses=13`;
- `analysis_coverage=38.2%`;
- report readiness: `signal_report`;
- причина: неполная обработка дня / часть анализов отсутствует или не подходит
  под текущую instruction_version.

### 2026-06-03: Call-list essence fix и закрытие pass

После review пользователь подтвердил, что исправления видны. Последняя проблема
в этом pass была в блоке `Все звонки дня -> Суть звонка`: текст выглядел как
обрезанный и не всегда показывал, чем закончился звонок.

Что исправлено:

- `core/app/agents/calls/report_templates.py`: compact call-list теперь
  использует `call_list_context_rich` выше короткого `call_list_context`.
- Лимит отображения сути звонка увеличен с `220` до `700` символов.
- Значения не пересочиняются в Report Layer: берется уже подготовленный смысл,
  а renderer только сохраняет его в более читаемом объеме.
- Добавлен regression test:
  `test_call_list_compact_rows_use_rich_context_without_220_char_truncation`.

Проверки:

- `python3 -m py_compile core/app/agents/calls/report_templates.py core/tests/test_report_templates_situation_day.py` -> OK.
- `docker compose exec -T api python -m pytest -q /app/tests/test_report_templates_situation_day.py -k "call_list_compact_rows"` -> `2 passed, 5 deselected`.
- `node --check scripts/generate_docx_report.js` -> OK.

Контрольный rerender только отчета:

```text
review_packages/timur_20260601_llm3_report_only_call_essence_fix_20260603/run.log
```

Результат:

- STT/LLM1/LLM2 не строились заново:
  `transcripts_built=0`, `analyses_built=0`.
- PDF доставлен в Telegram test-only:
  `Ежедневный отчет - Тимур Жуматаев - 1 июня 2026.pdf`,
  `message_id=370`.
- Compact rows теперь используют длинный rich context: проверенные значения
  `Суть звонка` были примерно `337-538` символов вместо прежнего короткого
  trim.

Финальный статус pass:

- `RL-T2`, `RL-T6`, `RL-T7`, `RL-T8` закрыты.
- LLM2 input optimization / semantic defect registry / Report Layer audit
  задокументированы.
- Полный день Тимура остается operator preview, не manager-facing complete
  report, потому что покрытие анализов дня неполное (`ready_analyses=13`,
  `analysis_coverage=38.2%`).
- Новый тест/прогон нужно запускать отдельным следующим шагом.

## 2026-06-02: Kimi K2.6 trial остановлен на LLM2

Короткий handoff:

```text
/root/ai-sales-analyzer/docs/KIMI_K26_TRIAL_HANDOFF_2026-06-02.md
```

Факт текущего Kimi runtime после перенастройки 2026-06-03:

- `LLM2` route: `kimi_llm2_main / moonshot-v1-128k`;
- `LLM3` route: `kimi_llm3_main / moonshot-v1-128k`;
- `AI_LLM_EXECUTION_MODE=openai_compatible`;
- `AI_LLM_SUBAGENT_RUNTIME_ENABLED=false`;
- `AI_LLM_SIMULATION_ENABLED=false`.

Что проверено:

- route-plan в контейнере подтверждал `kimi-k2.6` для `LLM2` и `LLM3`;
- targeted routing tests прошли;
- Kimi K2.6 rerun по готовым STT Толегена за `2026-06-01` остановлен по
  просьбе пользователя;
- Telegram report по K2.6 rerun не формировался и не отправлялся.

Почему остановлено:

- `LLM2A` Kimi K2.6 часто возвращал пустой/невалидный JSON;
- при `AI_LLM2_OUTPUT_MAX_TOKENS=8192` ответ упирался в лимит и ломал JSON;
- при `16384` / `32768` запросы становились слишком долгими и зависали;
- единственный формально сохраненный K2.6 analysis имел
  `score=0.0`, `stages=0`, `criteria=0`, то есть непригоден для отчета.

Текущая безопасная точка:

- активного `llm2_ready_stt_layered_runner` процесса нет;
- не запускать полный день через `LLM2=kimi-k2.6` без упрощения LLM2 contract;
- не строить manager-facing отчет из K2.6 artifacts с `stages=0` /
  `criteria=0`;
- для ближайшего качественного тестирования вернуться к Codex-subagent или
  OpenAI max-quality для `LLM2`, либо отдельно сделать Kimi-specific contract
  simplification.

## 2026-06-02: Semantic defect registry для LLM2

Текущая рабочая рамка:

- `LLM2` compact input profile внедрен и проверяется на контрольном звонке
  Толегена `2026-06-01`, interaction
  `9b71f8fa-6f94-4079-8987-32f9a9d36061`.
- Технические проблемы compact runtime частично закрыты: pass diagnostics,
  evidence hydration from LLM2B, lighter LLM2D payload.
- Оставшийся blocker качества — смысловая калибровка: false
  `callback_planned/follow_up` из vague availability, recommendation leakage
  into follow_up, score inflation на `cn_fixed_next_step`.

Текущие рабочие файлы:

```text
/root/ai-sales-analyzer/TMP_LLM2_INPUT_OPTIMIZATION_TASKS.md
/root/ai-sales-analyzer/TMP_LLM2_SEMANTIC_DEFECT_REGISTRY.md
```

Правило для следующего агента:

- не чинить смысловые ошибки LLM2 как одиночные prompt patches;
- сначала зафиксировать/обновить defect class в
  `TMP_LLM2_SEMANTIC_DEFECT_REGISTRY.md`;
- затем закрывать класс через systemic rule, deterministic normalization,
  diagnostics и regression tests.

Следующий практический шаг:

1. Закрыть `SD-001`, `SD-002`, `SD-003` из semantic defect registry:
   - `callback_planned` требует concrete callback evidence;
   - recommendation text не должен попадать в factual `follow_up`;
   - `cn_fixed_next_step` не может быть `2/2` на "можете обращаться".
2. Закрыть `SD-006`:
   - absence-based criteria должны иметь scene/evidence context или
     missing-evidence explanation, а не пустой evidence.
3. Запустить тот же one-call compact smoke.
4. Только после приемлемого качества переходить к small quality set.

## 2026-06-01: Подключение реального LLM3 в OpenAI-compatible режиме

Контекст: после Codex-subagent проверок пользователь попросил вернуть реальные
LLM-вызовы: в режиме `AI_LLM_EXECUTION_MODE=openai_compatible` все LLM-слои
должны работать через OpenAI-compatible provider routing, а не через Codex
subagents.

Правило runtime:

- `AI_LLM_EXECUTION_MODE=subagent_runtime` или
  `AI_LLM_SUBAGENT_RUNTIME_ENABLED=true` -> LLM вызовы идут через Codex
  subagent runtime;
- `AI_LLM_SIMULATION_ENABLED=true` -> включается локальная симуляция;
- `AI_LLM_EXECUTION_MODE=openai_compatible`,
  `AI_LLM_SUBAGENT_RUNTIME_ENABLED=false`,
  `AI_LLM_SIMULATION_ENABLED=false` -> `LLM-1`, `LLM-2` и `LLM-3` идут через
  реальные OpenAI-compatible provider pools.

Что изменено:

- `core/app/agents/calls/llm_simulation.py`: compatibility wrapper
  `request_llm3_composer()` больше не уходит в локальную LLM3-симуляцию, если
  simulation выключена. Он выбирает:
  1. subagent runtime, если он явно включен;
  2. local simulation, если она явно включена;
  3. OpenAI-compatible LLM3 route через `AIProviderRouter`, если оба тестовых
     режима выключены.
- Добавлен OpenAI-compatible helper для прямых LLM3 composer-boundary вызовов
  с `response_format={"type": "json_object"}`, retry по provider config,
  routing metadata и usage metadata.
- `core/tests/test_llm3_subagent_runtime.py`: добавлен unit-test, который
  фиксирует, что при `openai_compatible + simulation=false + subagent=false`
  прямой LLM3 wrapper вызывает OpenAI-compatible client.

Env для следующего реального запуска:

```text
AI_LLM_EXECUTION_MODE=openai_compatible
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SIMULATION_ENABLED=false
LLM3_ENABLED=true
AI_LLM3_PROVIDERS_JSON=...
AI_LLM3_FIXED_ACCOUNT_ALIAS=llm3_main
OPENAI_API_KEY_LLM3_MAIN=...
```

Проверки:

- `python3 -m py_compile core/app/agents/calls/llm_simulation.py core/tests/test_llm3_subagent_runtime.py` -> OK.
- `python3 core/tests/test_llm3_subagent_runtime.py LLM3SubagentRuntimeTests.test_llm3_direct_composer_uses_openai_compatible_when_simulation_is_off` -> OK.
- `docker compose exec -T api python -m pytest -q /app/tests/test_llm3_subagent_runtime.py` -> `6 passed`.
- Полный host-side `python3 core/tests/test_llm3_subagent_runtime.py` в текущем
  host окружении не проходит из-за отсутствующих dependency (`pydantic`,
  `openai`) у системного `python3`; контейнерная проверка выше является
  валидной targeted проверкой с зависимостями проекта.

Следующий практический шаг:

1. В контейнере/боевом окружении проверить, что `.env` действительно содержит
   `LLM3_ENABLED=true` и валидный `AI_LLM3_PROVIDERS_JSON`.
2. Запустить следующий controlled run в `openai_compatible` без Codex subagents.
3. В routing metadata отчета проверить `selected_execution_mode=openai_compatible`
   для LLM1/LLM2/LLM3 и отсутствие `codex_subagent_runtime`.

## 2026-06-01: Реальные LLM-профили и текущий cost optimized runtime

После проверки max quality стало видно, что анализ получается дороговатым для
ежедневной эксплуатации. Пользователь решил переключить активный runtime на
экономный production-профиль, а max quality оставить как отдельный ручной режим
для контрольных прогонов и спорных кейсов.

Текущий активный runtime в `.env` должен быть:

```text
AI_LLM_EXECUTION_MODE=openai_compatible
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SIMULATION_ENABLED=false
LLM3_ENABLED=true
```

Текущий активный профиль `cost_optimized`:

```text
STT  -> whisper-1
LLM1 -> gpt-5.4-nano
LLM2 -> gpt-5.4-mini
LLM3 -> gpt-5.4-mini
```

Роли:

- `LLM1` (`gpt-5.4-nano`) — дешевый admission / classification / routing
  слой. Он решает, стоит ли звонок вести дальше в анализ, и дает первичный
  структурный снимок.
- `LLM2` (`gpt-5.4-mini`) — основной per-call semantic analysis: суть звонка,
  договоренности, отказ/перенос, доказательства, оценки, рекомендации.
- `LLM3` (`gpt-5.4-mini`) — bounded report composition поверх LLM2-артефактов,
  а не повторный анализ сырого STT.

Ручной профиль `max_quality` для точечных сравнений качества:

```text
STT  -> whisper-1
LLM1 -> gpt-5.4-mini
LLM2 -> gpt-5.5
LLM3 -> gpt-5.4
```

Подготовленный hybrid-профиль `stt_llm1_api_llm2_llm3_subagents`:

```text
STT  -> API provider route
LLM1 -> OpenAI-compatible API provider route
LLM2 -> Codex subagent runtime
LLM3 -> Codex subagent runtime
```

Env для включения hybrid-профиля:

```text
AI_LLM_EXECUTION_MODE=openai_compatible
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SUBAGENT_RUNTIME_LAYERS=llm2,llm3
AI_LLM_SIMULATION_ENABLED=false
LLM3_ENABLED=true
AI_LLM_SUBAGENT_RUNNER_CMD=<runner command>
AI_LLM_SUBAGENT_RUN_ID=<run-id>
AI_LLM_SUBAGENT_ARTIFACT_DIR=/tmp/asa_llm_subagent_runs
AI_LLM_SUBAGENT_TIMEOUT_SEC=300
```

Runner options:

- `AI_LLM_SUBAGENT_RUNNER_CMD=python /app/report_scripts/llm_subagent_contract_runner.py`
  — контейнерный contract-runner для smoke-проверки wiring без реального Codex
  CLI.
- `AI_LLM_SUBAGENT_COMMAND=<codex command>` — generic Codex subagent CLI path,
  если Codex доступен внутри runtime окружения.

`AI_LLM_SUBAGENT_RUNTIME_LAYERS` — новый layer-scoped переключатель. Если он
пустой, работает старое поведение: глобальный `subagent_runtime` перехватывает
все LLM-слои. Если задан `llm2,llm3`, то LLM1 остается на API, а LLM2/LLM3
выполняются через subagent runtime.

Логика выбора профилей:

- `cost_optimized` — профиль по умолчанию для ежедневного пилота и будущей
  production-эксплуатации.
- `max_quality` — не включать по умолчанию; использовать только для проверки
  качества на выбранных днях/менеджерах или для разбора спорных результатов.
- `stt_llm1_api_llm2_llm3_subagents` — использовать для гибридной проверки,
  когда нужна реальная входная классификация LLM1, но смысловой слой LLM2 и
  Report LLM3 должны имитироваться Codex-subagents.

Что сделано:

- `.env` обновлен: `AI_LLM1_PROVIDERS_JSON`, `AI_LLM2_PROVIDERS_JSON`,
  `AI_LLM3_PROVIDERS_JSON` на `cost_optimized`.
- `.env` и `.env.example` получили `AI_LLM_SUBAGENT_RUNTIME_LAYERS`; в текущем
  активном env он пустой, поэтому `cost_optimized` остается активным.
- `.env` и `.env.example` также получили `AI_LLM_SUBAGENT_RUNNER_CMD`, чтобы
  runner path можно было задавать явно для hybrid-профиля.
- Technical smoke без pipeline выполнен с временным env override:
  `AI_LLM_SUBAGENT_RUNTIME_LAYERS=llm2,llm3` и
  `AI_LLM_SUBAGENT_RUNNER_CMD=python /app/report_scripts/llm_subagent_contract_runner.py`.
  Результат: `llm1_subagent=False`, `llm2_subagent=True`,
  `llm3_subagent=True`; LLM2 metadata получила
  `selected_execution_mode=subagent_runtime`, LLM3 `_routing.provider`
  получил `subagent_runtime`.
- Kimi / Moonshot trial sources подготовлены как дополнительные provider
  entries и активированы через `AI_LLM*_FIXED_ACCOUNT_ALIAS`:
  `kimi_llm1_main`, `kimi_llm2_main`, `kimi_llm3_main`,
  recommended trial models: `LLM1=moonshot-v1-8k`,
  `LLM2=moonshot-v1-128k`, `LLM3=moonshot-v1-128k`,
  `api_base=https://api.moonshot.ai/v1`,
  `api_key_env=MOONSHOT_API_KEY`. Чтобы попробовать Kimi, сначала заполнить
  `MOONSHOT_API_KEY`, затем переключить нужные `AI_LLM*_FIXED_ACCOUNT_ALIAS`
  на Kimi alias, пересоздать `api/worker/beat` и выполнить route-plan check.
  Без отдельного подтверждения пользователя pipeline не запускать.
- `api`, `worker`, `beat` пересозданы командами
  `docker compose up -d --force-recreate api worker` и
  `docker compose up -d --force-recreate beat`, потому что Docker читает env
  при старте контейнеров.
- Тестовый pipeline / STT / LLM-анализ / Report Layer не запускались.

Проверка внутри `api`, `worker` и `beat` контейнеров:

```text
mode=openai_compatible
subagent=False
simulation=False
llm3_enabled=True
llm1: alias=llm1_main model=gpt-5.4-nano mode=openai_compatible timeout=120
llm2: alias=llm2_main model=gpt-5.4-mini mode=openai_compatible timeout=300
llm3: alias=llm3_main model=gpt-5.4-mini mode=openai_compatible timeout=300
```

Следующий шаг: когда пользователь отдельно разрешит тест, запускать controlled
run уже на `cost_optimized` профиле и в routing metadata проверить выбранные
модели. До отдельного разрешения не запускать STT/LLM/report pipeline.

Статус на 2026-06-01:

- Post-review implementation pass A1-A8 выполнен через Codex subagents под
  контролем основного агента.
- Full-day rerun Толегена за 2026-05-19 не запускался.
- Telegram/business delivery не запускалась.
- Следующая точка: пользователь проверяет выполненные задачи; только после
  отдельного подтверждения можно запускать controlled rerun.
- Новая выявленная архитектурная проблема: `LLM-2A/LLM-2B` фактически
  отрезали коммерческие короткие звонки из stage scoring через внутренний
  `analysis_eligibility=not_eligible` / `duration_below_threshold`.
- Принято рабочее решение: право решить, идет ли звонок в `LLM-2`, должно быть
  только на входе в `LLM-2`. Узлы `LLM-2A/2B/2C/2D` не должны добавлять новые
  условия допуска и не должны целиком останавливать анализ звонка, который уже
  был передан в `LLM-2`.
- Implementation выполнен без pipeline/full-day rerun: обновлены prompt/contract,
  runtime admission snapshot, LLM-2A override guard, LLM-2B empty-scoring guard,
  layered normalizer и targeted tests.

Статус предыдущего full-day run на 2026-05-28:

- Запущен fresh full-day run по готовым STT для
  `Толеген Жангазиев / 2026-05-19`.
- Режим выполнения:
  `AI_LLM_EXECUTION_MODE=subagent_runtime`,
  `AI_LLM_SUBAGENT_RUNTIME_ENABLED=true`,
  `AI_LLM_SIMULATION_ENABLED=false`.
- Роли LLM выполняли реальные Codex subagents через `codex exec`.
- Выбрано ровно `24` звонка за день, без расширения периода.
- STT не пересобирался: `transcripts_reused=24`, `transcripts_built=0`.
- Анализ пересобран свежо: `analyses_built=24`, `analyses_reused=0`.
- Report readiness: `full_report`, `ready_analyses=24/24`,
  `analysis_coverage=100.0`.
- Первый PDF был остановлен scan gate из-за английских evidence labels
  `verified / strong`.
- Отчет был перерендерен из существующего payload с русской локализацией
  evidence labels; повторный scan прошел.
- Финальный PDF отправлен только в test/operator Telegram:
  `message_id=342`, `document_id=BQACAgIAAxkDAAIBVmoYPSg02etmDBXK5s5XE1RFGvSWAALEmwACfMbBSCH34U5-Jys3OwQ`.
- Completion ping в test/operator Telegram отправлен: `message_id=343`.
- Business delivery менеджерам/РОПам не запускалась.
- Пользователь проверил PDF и подтвердил качественный смысловой результат по
  `Ситуации дня` и `Разбору звонка`: механизм хорошо забрал ситуацию и
  смысл конкретного звонка.
- Новый выявленный gap: в блоке `Все звонки дня` слабо передается суть
  договоренности/контекста звонка. Нужно коротко показывать именно смысл,
  который должен давать LLM-2: например, `отказался, потому что нет
  потребности`, `договорились созвониться на презентацию`, `тема -
  документы/презентация/подписание`.
- В блоке `Контакты в работу` контекст передан лучше. Рассмотреть объединение
  с дневным списком: одна таблица всех звонков, где отдельно указано,
  брать ли контакт в работу и когда, а остальные строки остаются статусами
  с короткой сутью звонка.
- Post-review comments ping в test/operator Telegram отправлен:
  `message_id=344`.

Run package:

```text
/root/ai-sales-analyzer/core/review_packages/codex-full-day-tolegen-2026-05-19-2026-05-28-precise24-ru/
```

Ключевые артефакты:

```text
summary.json
prepare_summary.json
payload.json
payload_ru_fixed.json
subagent_artifact_counts_corrected.json
report_text_scan_ru_fixed.json
delivery_result_ru_fixed.json
completion_telegram_ping.json
post_review_comments_telegram_ping.json
Ежедневный отчет - Толеген Жангазиев - 19 мая 2026 - RU.pdf
```

Subagent evidence:

```text
input_files=123
output_files=123
LLM-1 classification first pass: 24
LLM-2A facts/scenes: 24
LLM-2B scoring/gaps: 24
LLM-2C claim/proof: 24
LLM-2D recommendations: 24
LLM-3 composers: 3
```

Текущая архитектурная позиция:

```text
Механизм впервые прошел один полный день Толегена за 2026-05-19 через реальные
Codex subagents, без blocking semantic/evidence validators, по готовым STT, с
готовым PDF в test/operator Telegram. Первый human review принят по главным
смысловым блокам. Следующий фокус - улучшить дневную таблицу звонков и
контакты в работу, не ломая принятые `Ситуацию дня` и `Разбор звонка`.
```

Итог по слоям:

1. `Validators / normalizers`
   - Статус: `completed_for_test`.
   - Blocking validators отключены:
     `AI_LLM2_REPORT_EVIDENCE_VALIDATION_ENABLED=false`,
     `AI_LLM2_SEMANTIC_VALIDATION_ENABLED=false`.
   - Schema/shape repair, enum/stage normalization и diagnostics сохранены.
   - Анализы не блокировались proof gate на уровне бизнес-отчета.

2. `LLM-2 / subagent runtime`
   - Статус: `controlled_llm2_only_rerun_completed_2026-06-01`.
   - Fresh full-day run выполнен через реальные Codex subagents.
   - По каждому из `24` звонков есть pass outputs:
     `LLM-2A`, `LLM-2B`, `LLM-2C`, `LLM-2D`.
   - `24/24` анализов готовы для report layer.
   - Gap after review: только `3/24` анализа получили числовой
     `score_by_stage`; `21/24` получили пустой scoring, потому что `LLM-2A`
     пометил их `not_eligible`, чаще всего из-за порога `180` секунд, хотя
     часть звонков была коммерчески релевантной.
   - Выполнено: внутренний stop gate из `LLM-2A/2B` убран на уровне prompt /
     contract и runtime guard. Если звонок дошел до `LLM-2B`,
     `stage_scores=[]` считается ошибкой выполнения/repair case, а не
     нормальным результатом.
   - Контрольный LLM2-only rerun после fix:
     `codex_llm2_gate_v1_20260601`,
     `/root/ai-sales-analyzer/core/review_packages/codex-llm2-only-tolegen-2026-05-19-2026-06-01`.
     Запускал только ready STT -> persisted LLM1 snapshot -> layered
     `LLM-2A/2B/2C/2D` через Codex `subagent_runtime`; не запускал source
     discovery, STT rebuild, LLM-1, LLM-3, report build или delivery.
   - Результат LLM2-only rerun: `24/24` ready STT processed; `20` admitted
     and scored with non-empty `score_by_stage`; `4` rejected before LLM-2 as
     `llm2_admission_non_commercial_or_unusable`; `0` admitted calls with
     empty `score_by_stage`; subagent artifacts `80 input / 80 output`.

3. `Registry / router`
   - Статус: `completed_for_test`.
   - Router работал в diagnostics-only/no-hard-proof режиме.
   - Report pool получил usable material без старого hard proof gate.
   - Итоговый readiness: `full_report_ready`.

4. `Report Layer / selection`
   - Статус: `post_review_iteration_completed_ready_for_user_review`.
   - Coverage: `relevant_calls=24`, `ready_analyses=24`.
   - Все ключевые content blocks готовы:
     `day_summary`, `review`, `key_problem`, `recommendations`.
   - Payload сохранен в `payload.json` и локализованная версия в
     `payload_ru_fixed.json`.
   - Выполнено 2026-06-01: `Все звонки дня` переведен на приоритет
     `report_evidence.call_essence`, outcome/follow-up essence и meaningful
     fallback. Строки договоренности/переноса/отказа/service теперь должны
     показывать конкретную суть, причину, next step и срок, если он есть.
   - Выполнено 2026-06-01: `Контакты в работу` синхронизированы с тем же
     source model / call-list строкой, чтобы не было расхождения контекста.

5. `LLM-3 / narrative`
   - Статус: `completed_for_test`.
   - Сформированы `3` LLM-3 outputs:
     `situation_day`, `call_tomorrow_wording`, `call_breakdown`.
   - Выходы приняты как `verified`.
   - Manager-facing PDF после rerender прошел русский text scan.

6. `Renderer / PDF / Telegram`
   - Статус: `renderer_followup_completed_ready_for_rerun_after_approval`.
   - Первичный PDF не был отправлен из-за scan failure.
   - После локализации labels создан финальный PDF:
     `Ежедневный отчет - Толеген Жангазиев - 19 мая 2026 - RU.pdf`.
   - Финальный scan:
     `passed=true`, разрешенные ASCII tokens: `CRM-`, `IVR`.
   - Telegram test/operator delivery: `sent`, target `74665909`,
     message id `342`.
   - Выполнено 2026-06-01: renderer поддерживает compact call-list table:
     `Статус`, `В работу`, `Когда`, `Суть звонка / договоренность`.
   - Выполнено 2026-06-01: visible evidence/status labels локализованы, raw
     `verified/strong/medium` не должны попадать в видимый отчет.

7. `Observability / verification`
   - Статус: `post_review_targeted_verified`.
   - Run package содержит summary, payload, scan, delivery result и
     subagent artifacts.
   - Подтверждено, что фоновые `codex exec` процессы после прогона не висят.
   - Pre-test targeted suite перед запуском: `88 passed, 2 subtests passed`.
   - Выполнено 2026-06-01: добавлены per-row diagnostics для call-list context
     (`source`, `priority`, `selected_reason`, `quality`, `weak_reason`,
     rejected sources).
   - Выполнено 2026-06-01: subagent artifact counter теперь считает indexed
     `*_output.json` и legacy `output.json`.

## Новые задачи перед следующим controlled rerun

Цель: проверить 24 готовых STT Толегена за `2026-05-19` так, чтобы все
коммерчески релевантные звонки, прошедшие входной допуск в `LLM-2`, получили
анализ и применимые stage scores. `LLM-1` в этой итерации не дорабатывается.

### LLM-2 admission gate

Status: `implemented_pending_controlled_verification`.

- Вынести решение `analyze / do_not_analyze` на вход в `LLM-2`, до запуска
  pass chain `LLM-2A -> LLM-2B -> LLM-2C -> LLM-2D`.
- Gate должен исключать только: нет речи/мусор/IVR, внутренние звонки, чистую
  техподдержку без коммерческого смысла, непригодную STT или отсутствие
  понятного manager-client exchange.
- Длительность `<180` секунд не должна сама по себе делать коммерчески
  релевантный звонок `not_eligible`.
- Глобальную переменную `CALLS_MIN_DURATION_SEC=180` не менять в этой итерации,
  чтобы не сломать source/intake/STT behavior.

### LLM-2A facts / scenes

Status: `implemented_pending_controlled_verification`.

- Убрать из `LLM-2A` право останавливать анализ через
  `analysis_eligibility=not_eligible` для звонка, уже допущенного во входной
  `LLM-2` gate.
- `LLM-2A` должен собирать факты, сцены, evidence ledger, реакции клиента,
  возражения, договоренности и сроки.
- `LLM-2A` может писать quality/risk notes, но не должен закрывать scoring
  для коммерчески допущенного звонка.

### LLM-2B scoring / gaps

Status: `implemented_pending_controlled_verification`.

- Убрать fail-closed условие вида
  `llm2a_artifact.analysis_eligibility=not_eligible -> stage_scores=[]` для
  звонков, которые уже были переданы в `LLM-2B`.
- Если звонок пришел в `LLM-2B`, он обязан вернуть `stage_scores` по
  применимым этапам.
- Неприменимые этапы не должны получать искусственные нули; они просто не
  включаются в scoring.
- Пустой `stage_scores=[]` после допущенного коммерческого звонка должен
  попадать в retry/repair/diagnostics как ошибка выполнения.

### LLM-2C / LLM-2D

Status: `implemented_pending_controlled_verification`.

- `LLM-2C` не отбрасывает звонок целиком: он проверяет claims, evidence и
  counter-evidence, отклоняет или soften только конкретные claims.
- `LLM-2D` не меняет eligibility и не скрывает звонок: рекомендации строятся
  только из доказанных/softened claims и scoring.

### Report Layer / stage score coverage

Status: `verified_no_new_duration_filter_pending_controlled_rerun`.

- Report Layer не должен добавлять новый фильтр по длительности для блока
  `БАЛЛЫ ПО ЭТАПАМ`.
- Проверить, что блок берет все анализы с числовым `score_by_stage`.
- После правок ожидаемый эффект: `БАЛЛЫ ПО ЭТАПАМ` считает не только 3 длинных
  звонка, а все коммерчески релевантные допущенные звонки с применимым
  scoring; support/мусор остаются вне scoring.

### Controlled verification

Status: `pending_after_implementation`.

- Запускать только после реализации задач выше и отдельного подтверждения
  пользователя.
- Scope проверки: готовые `24` STT Толегена за `2026-05-19`.
- Запускать не отдельный `LLM-2B`, а полный layered `LLM-2` chain:
  `LLM-2A -> LLM-2B -> LLM-2C -> LLM-2D`, затем Report build и PDF preview
  в test/operator Telegram.
- Почему не только `LLM-2B`: `LLM-2B` скорит только по сценам/evidence из
  нового `LLM-2A`; `LLM-2C` должен проверить новые claims/proof/counter-evidence;
  `LLM-2D` должен собрать финальный `scores_detail`, recommendations и
  compatibility output для Report Layer.
- Запускать Analysis + Report без STT rebuild, без source discovery, без
  LLM-1 доработки и без business delivery менеджерам.
- Проверить diagnostics:
  `LLM-2A/2B/2C/2D artifact counts`, количество звонков с `stage_scores`,
  причины исключения из входного `LLM-2` gate, покрытие `БАЛЛЫ ПО ЭТАПАМ`.
- Ожидаемый результат проверки: stage-score coverage становится существенно
  выше прежних `3/24`; коммерчески релевантные короткие звонки получают
  применимый scoring, а support/мусор исключаются до `LLM-2` с явной причиной.

Запрещено в следующем запуске:

```text
не запускать полный pipeline;
не пересобирать STT;
не запускать source discovery;
не отправлять business delivery менеджерам;
не запускать только LLM-2B изолированно как финальную проверку.
```

Разрешенный следующий запуск:

```text
24 ready STT Толегена за 2026-05-19
-> layered LLM-2A/2B/2C/2D через Codex subagent_runtime
-> report build
-> PDF preview только в test/operator Telegram
-> diagnostics по admission/scoring/report coverage
```

Post-review follow-up status before next controlled rerun:

```text
DONE 2026-06-01:
1. Report Layer улучшил контекст в `Все звонки дня`:
   короткая LLM-2 суть звонка, причина отказа/интереса, тема и договоренность.
2. Report Layer / renderer проверили объединение `Контакты в работу`
   и `Все звонки дня`: одна таблица со статусом, флагом "в работу", сроком и
   короткой сутью; либо общий source для двух блоков без расхождения контекста.
3. Renderer локализует evidence labels сам, без ручного
   post-run rerender payload.
4. Visible labels и renderer checks не должны выводить raw `verified/strong`.
5. Subagent artifact counter учитывает текущие *_output.json artifacts,
   а не только output.json.

REMAINING:
6. Controlled rerun LLM2-only полного дня Толегена за 2026-05-19 выполнен
   2026-06-01: `20/20` admitted calls получили stage scores, `4/24`
   исключены до LLM-2 как non-commercial/support.
7. Следующий шаг после проверки пользователем: report build/PDF preview на
   controlled_sample analyses `codex_llm2_gate_v1_20260601`, без STT/source
   rebuild и без business delivery.
8. Перед production rollout нужен отдельный broad regression pass.

REPORT SENT 2026-06-01:
- Собран manager_daily PDF по Толегену за `2026-05-19` поверх
  controlled_sample analyses `codex_llm2_gate_v1_20260601`.
- Пакет:
  `/root/ai-sales-analyzer/core/review_packages/codex-report-tolegen-2026-05-19-llm2-gate-v1`.
- Delivery: test/operator Telegram only, target `74665909`,
  `message_id=355`,
  `document_id=BQACAgIAAxkDAAIBY2odysjfY_1oP21HD9pvWJy4Yo3RAAK8nwACnI3xSNklMpeqBb9dOwQ`.
- PDF: `Ежедневный отчет - Толеген Жангазиев - 19 мая 2026.pdf`,
  `5` pages, `156145` bytes.
- Build summary: transcripts_built `0`, analyses_built `0`,
  analyses_reused `20`, status `review_required` because report is operator
  preview over controlled samples; business email skipped.
```

Post-review backlog по слоям для следующего агента:

Порядок выполнения:

```text
1. LLM-2 / call essence
2. Report Layer / Все звонки дня
3. Report Layer / Контакты в работу
4. Renderer / PDF table shape
5. Validators / normalizers diagnostics
6. Registry / router source consistency
7. LLM-3 wording guardrail, only if needed
8. Observability / regression
9. Controlled rerun after user approval
```

1. `LLM-1`
   - Статус: `later_not_before_next_report_pass`.
   - Сейчас не трогать: текущий gap не в role attribution и не в STT.
   - Позже отдельно вернуться к speaker confidence, role attribution и
     source-of-truth для имен/ролей.

2. `LLM-2 / call essence`
   - Статус: `completed_2026-06-01`.
   - Главный вход для следующего pass.
   - Проверить, где сейчас формируется короткая суть звонка для дневной таблицы:
     `call_report_summary.manager_visible_summary`, `short_context`,
     `business_outcome`, follow-up fields.
   - Усилить контракт/нормализацию так, чтобы по каждому звонку был короткий
     manager-facing call essence: тема, итог, причина отказа/интереса,
     конкретная договоренность, следующий шаг.
   - Acceptance examples:
     `отказался, потому что нет потребности`;
     `договорились созвониться на презентацию`;
     `тема - документы/подписание`.
   - Не ломать уже принятые `Ситуацию дня` и `Разбор звонка`.

3. `Validators / normalizers`
   - Статус: `completed_2026-06-01_soft_diagnostics_only`.
   - Blocking semantic/evidence validators не возвращать.
   - Добавить мягкую нормализацию/diagnostics для нового call essence:
     пусто, технический текст, английский текст, слишком общий context.
   - Diagnostics должны предупреждать, но не блокировать отчет.

4. `Registry / router`
   - Статус: `completed_2026-06-01`.
   - Не возвращать старый hard proof gate.
   - Проверить, нужен ли отдельный routed source для `call_list_context` /
     `call_essence`.
   - Убедиться, что `Все звонки дня` и `Контакты в работу` не берут разные
     контексты для одного и того же звонка без причины.

5. `Report Layer / Все звонки дня`
   - Статус: `completed_2026-06-01_ready_for_rerun_review`.
   - Перестроить выбор контекста: приоритет у LLM-2 call essence /
     follow-up essence, затем meaningful deterministic fallback.
   - Для строк с договоренностью обязательно показывать тему договоренности,
     что именно договорились и следующий шаг.
   - Для отказов показывать короткую причину.
   - Для сервисных/технических звонков показывать суть обращения.
   - Убрать слабые generic contexts.

6. `Report Layer / Контакты в работу`
   - Статус: `completed_2026-06-01_shared_source_compact_table`.
   - Рассмотреть объединение с `Все звонки дня`:
     единая таблица всех звонков + колонки `Статус`, `В работу`, `Когда`,
     `Суть звонка / договоренность`.
   - Предпочтительный продуктовый вариант после review: один дневной список,
     где видно, какие контакты брать в работу и когда, а остальные остаются
     статусными строками.
   - Если не объединять, оба блока должны брать context из одного source,
     чтобы не было ситуации, где в одном блоке context хороший, а в другом
     слабый.

7. `LLM-3`
   - Статус: `completed_2026-06-01_guardrail_only`.
   - `Ситуация дня` и `Разбор звонка` приняты, их не переписывать.
   - Если LLM-3 будет участвовать в wording для call-list/contacts, он не
     должен менять статус, дату, договоренность, тему или смысл LLM-2.
   - Роль LLM-3 в этом pass: только сжать/упаковать формулировку на русском,
     если это действительно нужно.

8. `Renderer / PDF`
   - Статус: `completed_2026-06-01`.
   - Поддержать новую форму таблицы без раздувания PDF.
   - Если блоки объединяются, сделать таблицу читаемой: статус, в работу,
     срок/когда, суть звонка/договоренность.
   - Закрепить русскую локализацию evidence labels в renderer.
   - Перевести English scan на visible text.

9. `Observability / regression`
   - Статус: `completed_2026-06-01_targeted`.
   - Добавить diagnostics по каждой строке дневной таблицы: источник context,
     source priority, почему выбран именно этот text.
   - Добавить regression на строки: отказ с причиной, договоренность о
     презентации, перенос/созвон, сервисный/технический контакт.
   - Починить счетчик subagent artifacts, чтобы он считал `*_output.json`.
   - После реализации сделать controlled rerun только после отдельного
     подтверждения пользователя.

Verification 2026-06-01:

```text
docker compose exec -T api python -m pytest -q \
  /app/tests/test_report_evidence_registry.py \
  /app/tests/test_report_block_router.py \
  /app/tests/test_report_evidence_proof_card_validation.py \
  /app/tests/test_llm2_layered_analysis.py \
  /app/tests/test_report_templates_situation_day.py
-> 44 passed, 2 subtests passed

docker compose exec -T api python -m pytest -q \
  /app/tests/test_manual_reporting.py \
  -k 'a2_a3 or call_list_context or call_list_uses_call_essence or call_tomorrow_uses_call_list'
-> 4 passed, 208 deselected

docker compose exec -T api python -m pytest -q \
  /app/tests/test_llm3_subagent_runtime.py \
  -k 'artifact_counter or output_json or subagent'
-> 5 passed

node --check scripts/generate_docx_report.js
docker compose exec -T api python -m py_compile \
  /app/app/agents/calls/reporting.py \
  /app/app/agents/calls/report_templates.py \
  /app/app/agents/calls/report_evidence.py \
  /app/app/agents/calls/report_evidence_registry.py \
  /app/app/agents/calls/report_block_router.py \
  /app/app/agents/calls/llm2_layered_analysis.py \
  /app/app/agents/calls/llm_simulation.py
git diff --check -- touched scoped files
-> passed
```

Known verification note:

```text
Широкий full suite текущего dirty worktree не считается gate для этого pass:
по отчету Copernicus широкий набор имел unrelated legacy failures
(`47 failed, 205 passed`). Для текущего pass подтверждены scoped/targeted
checks выше. Перед production rollout нужен отдельный broad regression pass.
```

Мини-брифы задач для агентов:

Использовать эти карточки как прямой scope для implementation agents. Каждый
агент должен работать в своем слое, не запускать full-day прогон и не делать
business delivery без отдельного подтверждения пользователя.

### Agent Task A1 — LLM-2 call essence

Цель:
сделать так, чтобы у каждого звонка появился короткий управленческий смысл для
дневной таблицы: о чем говорили, чем закончилось, почему отказ/интерес, какая
договоренность и следующий шаг.

Где смотреть:
`core/app/agents/calls/prompts/analyze_v17_universal_evidence.md`,
`core/app/agents/calls/prompts/llm2_pass_contracts.md`,
`core/app/agents/calls/llm2_layered_analysis.py`,
`core/app/agents/calls/report_evidence.py`,
`core/app/agents/calls/analyzer.py`.

Что сделать:
- найти текущие поля `call_report_summary.manager_visible_summary`,
  `short_context`, `business_outcome`, `follow_up`, `call_list_context`;
- выбрать/ввести единый normalized field для manager-facing call essence;
- для agreement/reschedule/open обязательно сохранять topic + agreement +
  next step;
- для refusal сохранять short refusal reason;
- для tech_service/support сохранять суть обращения;
- обеспечить fallback только из уже имеющихся фактов/STT, без выдумывания.

Acceptance:
- строка типа `есть договоренность` без темы и следующего шага считается
  недостаточной;
- хорошие примеры:
  `отказался, потому что сейчас нет потребности`,
  `договорились созвониться на презентацию по ЭДО`,
  `клиент просит решить вопрос с документами/подписанием`;
- accepted блоки `Ситуация дня` и `Разбор звонка` не меняются по смыслу.

Проверка:
targeted tests для LLM-2/report evidence плюс ручной inspect artifacts на
контрольных звонках Толегена. Full-day rerun не запускать.

### Agent Task A2 — Report Layer / Все звонки дня

Цель:
перестроить видимую дневную таблицу так, чтобы она показывала не только статус,
а короткую суть каждого звонка.

Где смотреть:
`core/app/agents/calls/reporting.py`,
`core/app/agents/calls/report_templates.py`,
`core/app/agents/calls/report_block_router.py`,
`scripts/generate_docx_report.js`,
`core/tests/test_manual_reporting.py`.

Что сделать:
- в выборе context отдать приоритет новому LLM-2 call essence /
  follow-up essence;
- deterministic fallback использовать только если он meaningful;
- для договоренностей показывать `о чем договорились` + `что дальше` +
  `когда`, если срок есть;
- для отказов показывать причину;
- для service/technical строк показывать суть запроса;
- убрать generic text вроде `есть договоренность`, `контакт в работу`,
  `нужно продолжить работу` без конкретики.

Acceptance:
- по каждой строке руководитель понимает, что произошло в звонке;
- agreement row отвечает минимум на вопрос `о чем договоренность?`;
- refusal row отвечает минимум на вопрос `почему отказ?`;
- если данных нет, строка честно помечается как слабый/неясный контекст в
  diagnostics, но отчет не блокируется.

Проверка:
unit/regression на четыре типа строк: refusal with reason, presentation
agreement, callback/reschedule, service/technical.

### Agent Task A3 — Report Layer / Контакты в работу

Цель:
убрать расхождение, когда `Контакты в работу` передает контекст лучше, чем
`Все звонки дня`, и решить продуктово: объединяем блоки или оставляем два
блока на одном источнике.

Где смотреть:
`core/app/agents/calls/reporting.py`,
`core/app/agents/calls/call_tomorrow_wording_composer.py`,
`core/app/agents/calls/report_block_router.py`,
`scripts/generate_docx_report.js`.

Предпочтительное решение:
единая таблица всех звонков с колонками `Статус`, `В работу`, `Когда`,
`Суть звонка / договоренность`. Контакты в работу становятся флагом/колонкой,
а не отдельным конкурирующим источником смысла.

Допустимое решение:
оставить отдельный блок, но оба блока должны читать один и тот же call essence
source. Нельзя, чтобы в одном блоке была нормальная суть, а в другом по тому же
звонку был generic context.

Acceptance:
- по звонку с follow-up одна и та же тема/договоренность видна и в дневной
  таблице, и в рабочем follow-up представлении;
- нет дублирующих противоречивых формулировок.

### Agent Task A4 — Renderer / PDF table shape

Цель:
поддержать новую компактную таблицу в PDF без раздувания отчета и без
английских технических labels.

Где смотреть:
`scripts/generate_docx_report.js`,
`core/app/agents/calls/report_templates.py`,
`core/app/agents/calls/report_template_assets/manager_daily/*`,
renderer-related tests.

Что сделать:
- обновить table shape под новую модель: статус, в работу, когда, суть;
- убедиться, что длинный текст не ломает PDF;
- локализовать evidence/status labels в renderer, чтобы не было raw
  `verified`, `strong`, `medium` в видимом отчете;
- English scan должен проверять visible report text, а не raw HTML/CSS.

Acceptance:
- PDF остается читаемым;
- нет английских служебных labels в видимом тексте;
- таблица не раздувает отчет и не скрывает принятые смысловые блоки.

### Agent Task A5 — Validators / normalizers diagnostics

Цель:
не возвращать блокирующие валидаторы, но дать агентам и оператору понятный
сигнал, где call essence слабый.

Где смотреть:
`core/app/agents/calls/report_evidence.py`,
`core/app/agents/calls/report_evidence_registry.py`,
`core/app/agents/calls/report_block_router.py`,
`core/app/agents/calls/reporting.py`.

Что сделать:
- добавить soft diagnostics для пустого, технического, английского и слишком
  общего call essence;
- diagnostics должны сохранять source, priority и причину, почему выбран или
  отклонен context;
- никакой diagnostic не должен блокировать формирование отчета.

Acceptance:
- отчет строится даже при warning;
- warning помогает быстро найти слабую строку в таблице;
- old hard semantic/evidence validators не восстановлены.

### Agent Task A6 — Registry / router source consistency

Цель:
зафиксировать один источник смысла для `Все звонки дня` и `Контакты в работу`.

Где смотреть:
`core/app/agents/calls/report_evidence_registry.py`,
`core/app/agents/calls/report_block_router.py`,
`core/app/agents/calls/report_evidence.py`,
`core/tests/test_report_evidence_registry.py`,
`core/tests/test_report_block_router.py`.

Что сделать:
- проверить, нужен ли отдельный normalized route `call_essence` /
  `call_list_context`;
- не возвращать hard proof gate для дневной таблицы;
- не допускать, чтобы два блока выбирали разные contexts для одного call_id без
  явной причины в diagnostics.

Acceptance:
- source consistency видна в diagnostics;
- router не отбрасывает полезную суть звонка только из-за старого proof gate;
- follow-up и call-list используют согласованный source.

### Agent Task A7 — LLM-3 wording guardrail

Цель:
если LLM-3 участвует в упаковке текста для таблицы, он только сжимает русский
текст, но не меняет факты.

Где смотреть:
`core/app/agents/calls/llm_simulation.py`,
`core/app/agents/calls/situation_day_daily_composer.py`,
`core/app/agents/calls/call_breakdown_composer.py`,
LLM-3 composer tests.

Что сделать:
- не трогать принятые `Ситуация дня` и `Разбор звонка`;
- для call-list wording запретить изменение статуса, даты, темы,
  договоренности и next step;
- при сомнении лучше вывести LLM-2 essence как есть, чем красиво
  переформулировать с потерей смысла.

Acceptance:
- LLM-3 output не противоречит LLM-2 source fields;
- никаких новых смысловых claim от LLM-3.

### Agent Task A8 — Observability / regression

Цель:
после доработки можно быстро доказать, что таблица стала лучше и не сломала
остальные блоки.

Где смотреть:
`core/tests/test_manual_reporting.py`,
`core/tests/test_report_block_router.py`,
`core/tests/test_report_evidence_registry.py`,
`core/tests/test_llm2_layered_analysis.py`,
artifact counters in report/subagent runtime code.

Что сделать:
- добавить regression cases: отказ с причиной, договоренность о презентации,
  перенос/созвон, service/technical call;
- добавить per-row diagnostic artifact для call list;
- починить artifact counter, чтобы counted outputs включали `*_output.json`;
- подготовить dry-run/preview verification command, но не запускать полный
  Толеген 19 мая без approval.

Acceptance:
- targeted tests проходят;
- diagnostics показывают source и качество каждой строки;
- финальная сводка агенту/пользователю отдает статусы по слоям.

Текущая точка ожидания:

```text
ГОТОВО К ПРОВЕРКЕ ПОЛЬЗОВАТЕЛЕМ

Post-review задачи A1-A8 выполнены. Смысловые блоки `Ситуация дня` и
`Разбор звонка` не должны быть изменены по смыслу. Доработан основной gap:
дневная таблица звонков и `Контакты в работу` теперь используют call essence /
follow-up essence и compact table.

Новый full-day прогон Толегена за 2026-05-19 НЕ запускался. Следующий шаг -
пользователь проверяет статусы задач. После отдельного подтверждения можно
запускать controlled rerun полного дня Толегена за 2026-05-19.
```

Telegram notification:

```text
status: sent
target: test/operator Telegram
messages_sent: 1 PDF document + 1 completion ping
pdf_message_id: 342
completion_ping_message_id: 343
post_review_comments_ping_message_id: 344
post_review_implementation_ping_2026_06_01: sent, messages_sent=1
business_delivery: not_run
```

Не входит в pre-test backlog:

- STT quality и role attribution.
- Production `LLM-1` redesign.
- Business delivery менеджерам вне test/operator Telegram.
- Большая переработка UI/scheduler.

Следующее действие после review пользователя:

```text
Если пользователь подтверждает, что post-review задачи выполнены, запустить
controlled rerun:
Толеген Жангазиев / 2026-05-19 / full-day / ready STT / без business delivery
до отдельного решения.
```

## Предыдущая задача

Тема: Report Layer closeout Blocks 4/5/7/8 после analysis-layer closeout.

Статус на 2026-05-27:

- Blocks 4/5/7/8 выполнены автономно через implementation/regression agents.
- Финальная регрессия Толегена за `2026-05-18`, `2026-05-19`, `2026-05-20`
  пересобрана через DOCX->PDF.
- Последний дефект регрессии закрыт: технический токен `document_type` больше
  не проходит в reader-facing текст Python render model и DOCX generator.
- PDF text scan по трем дням чистый: `Контекст:`, `document_type`, сырые UUID,
  raw id keys, inline `Как с этим работать:` / `Что сделать:` и
  `Доказательный фрагмент:` не найдены.
- Acceptance suite Report Layer: `68 passed`; быстрый targeted suite для
  Blocks 4/5/document_type: `9 passed, 202 deselected, 5 subtests passed`;
  `node --check scripts/generate_docx_report.js` и `git diff --check` прошли.

Финальные артефакты:

```text
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/report_layer_final_regression_2026-05-27/
```

Следующее действие:

```text
Дождаться пользовательского review финальных PDF в Telegram и решения:
accept Report Layer closeout или вернуть конкретный блок на доработку.
```

## Предыдущая задача

Тема: analysis-layer closeout handoff перед переходом к Report Layer.

Scope текущего закрытия:

```text
LLM-2 runtime production path + validators + registry/router proof pool.
STT/role attribution и LLM-1 отложены и не входят в текущий scope.
```

Уже закрыто:

- граница `LLM-2` как владельца смысла/evidence утверждена;
- pass contracts/prompts `LLM-2A/2B/2C/2D` подготовлены;
- additive `proof_card` и isolated admission validation добавлены;
- registry/router читают proof status и не повышают legacy-only candidates до
  verified source;
- LLM-node simulation по 9 звонкам Толегена дала `12 verified`, `10 soften`,
  `3 reject`, quote validation errors `0`;
- control runner summary по 9 звонкам: validation `9/9`, load/match issues
  `0`, registry `102` items, router routes `situation_day=4`,
  `call_breakdown=4`, `voice_of_customer=5`, `follow_up=11`,
  `additional_situations=1`, `challenge=4`.
- analyzer runtime path `LLM-2A -> LLM-2B -> LLM-2C -> LLM-2D`
  включен как default через `AI_LLM2_ANALYSIS_MODE=layered`;
  legacy `monolithic` остается явным fallback-режимом;
- runtime path создает pass chain `LLM-2A -> LLM-2B -> LLM-2C -> LLM-2D`,
  нормализует через `llm2_layered_analysis.py`, сохраняет pass artifacts и
  routing metadata в `scores_detail`;
- runtime smoke по 9 baseline звонкам Толегена завершен `9/9 ok`,
  complete pass chains `9/9`, proof cards `9 proven`, gaps `9`,
  recommendations `9`;
- full focused analysis-layer checks прошли: `68 passed, 2 subtests passed`;
  control runner по 9 звонкам повторно завершен `completed`.

Что остается вне текущего closeout:

1. STT quality / role attribution.
2. `LLM-1` classification/eligibility/card и будущий вынос в отдельный сервис.
3. Report Layer / `LLM-3` / renderer wording поверх proof pool.

Guardrail:

```text
Не запускать Report Layer / LLM-3 / PDF preview / Telegram preview /
Telegram or email business delivery до отдельного Report Layer шага поверх
закрытого analysis proof pool.
```

Причина паузы:

```text
Пользователь указал, что в `СИТУАЦИЯ ДНЯ` строгая структура отчета показывает
claim, который не доказывается приведенным фрагментом разговора. До проверки
механизма анализа движение по Gate 5 block-by-block остановлено.
```

Активная точка восстановления:

```text
LLM-1 -> LLM-2 -> validators/normalizers -> report evidence registry
-> report block router -> Report Layer -> LLM-3 -> payload/render/PDF/Telegram
```

Это возврат не к Block 2, а к pre-block архитектурной развилке: сначала
проверить весь механизм анализа и владение смыслом/evidence, затем уже
возвращаться к блокам отчета.

Текущий audit artifact:

```text
/root/ai-sales-analyzer/docs/LLM2_CLAIM_EVIDENCE_FIT_AUDIT_2026-05-27.md
```

Рабочий вывод аудита:

- первичная проверка claim/evidence должна быть в `LLM-2`, а не в `LLM-3`;
- `LLM-2` должен строить не report-specific заготовки, а универсальный
  analysis/evidence artifact: смысл звонка, факты, оценки, gaps,
  recommendations, evidence и counter-evidence;
- prompt LLM2 уже содержит правила `gap_proven`, `proof_type`, `quote_role`,
  `counter_evidence`, но runtime enforcement не является единым hard gate;
- `validate_report_evidence()` умеет ловить часть proof conflicts, но не
  подключен как обязательный admission gate в analyzer normalization;
- legacy arrays (`manager_coaching_moments`, `situation_candidates`,
  `additional_situations`) могут попасть в registry/router без полного proof
  contract и затем выглядеть как verified evidence;
- Report Layer остается safety gate, но не должен заменять LLM2-анализ.
- локальные правки Block 2 после пользовательского комментария считаются
  post-checkpoint worktree state и не являются принятой целевой архитектурой.

Слойная рамка движения:

| Слой | Что отвечает за смысл/доказательство | Текущий вывод |
| --- | --- | --- |
| `LLM-1` | Не отвечает за доказательство coaching claims; только классификация, карточка, eligibility | Закреплять последним |
| `LLM-2` | Главный владелец смысла звонка, gaps, recommendations, evidence, counter-evidence | Упростить и убрать report-specific routing |
| Validators / normalizers | Делают `claim -> evidence -> counter-evidence` admission gate | Усилить, потому что текущие проверки слишком формальные |
| Registry / router | Маршрутизируют только нормализованный доказанный evidence pool | Legacy arrays не должны становиться verified source |
| Report Layer | Выбирает фокус/кейс и применяет hard gates | Не должен заменять анализ `LLM-2` |
| `LLM-3` | Оформляет выбранный материал в manager-facing narrative | Не должен проверять или усиливать слабый claim |
| Renderer / PDF / Telegram | Показывает payload и чистит форму | Не должен менять смысл или маскировать слабое доказательство |

Главное правило:

```text
Доказательство является частью смысла.
Если вывод из звонка не подкреплен конкретным моментом разговора, где явно
видна заявленная проблема, такой вывод не должен попадать в отчет как уверенный
coaching claim.
```

Где структура вредит:

- `LLM-2` начинает заполнять report-specific поля вместо анализа звонка;
- validators проверяют форму JSON, но не доказывают claim;
- registry/router принимают legacy candidates без полного proof contract;
- Report Layer ищет блок для заполнения и может собрать уверенный кейс из
  слабого материала;
- `LLM-3` получает слишком жесткую micro-field форму и пишет структуру вместо
  смысла;
- renderer показывает raw labels, таблицы и обязательные секции так, будто
  доказательство уже есть.

Контрольные даты:

```text
2026-05-18
2026-05-19
2026-05-20
```

Утверждено пользователем:

- технически отчеты в целом собирались и уходили;
- блокер пилота — нестабильное качество анализа, доказательной базы и подкрепления выводов;
- граница `LLM-2` утверждена;
- все LLM-узлы в калибровочном цикле проверяются через `subagent_runtime`;
- реальные отчеты через субагентов являются обязательной финальной проверкой;
- `LLM-1` закрепляется/переносится в последнюю очередь.

## Правило оркестрации субагентов

В этой задаче работа должна выполняться через два разных типа субагентов:

1. `implementation subagents` — выполняют доработки механизма, prompt pack, validators, artifact capture, report layer / `LLM-3` integration, тесты и подготовку отчетов.
2. `LLM-node simulation subagents` — имитируют только runtime-поведение `LLM-1`, `LLM-2`, `LLM-3`: получают те же инструкции/контекст, возвращают те же JSON contracts и проходят те же validators/normalizers/quality gates.

Роль основного агента в чате:

- оркестрировать работу;
- запускать нужных субагентов;
- выдавать им ограниченные задачи;
- не смешивать implementation-роль и LLM-node simulation-роль;
- собирать результаты и артефакты;
- проверять, что изменения соответствуют утвержденным границам;
- обновлять `ACTIVE_WORK_STATE.md`, `PROGRESS.md` и `DECISIONS.md`;
- останавливать работу на approval gates и вызывать пользователя.

Запрещено:

- использовать одного и того же субагента одновременно как исполнителя доработки и как имитатор LLM-узла в одном проверочном контуре;
- проверять доработку тем же агентом, который ее сделал, без отдельного artifact/validator/report-level контроля;
- подменять LLM-node simulation обычной local simulation;
- обходить реальные runtime boundaries ради удобства теста.

Основные source of truth:

```text
/root/ai-sales-analyzer/docs/LLM2_ARCHITECTURE_AUDIT_AND_TARGET_MODEL.md
/root/ai-sales-analyzer/docs/BUSINESS_READY_REPORT_PACK_TASKS.md
/root/ai-sales-analyzer/docs/TMP_LLM_NODES_ARTIFACTS_MAP.md
/root/ai-sales-analyzer/docs/LLM_SUBAGENT_TESTING_MODE.md
/root/ai-sales-analyzer/docs/DECISIONS.md
```

## Текущий план

Движение остается послойным. Текущий активный слой `LLM-2` закрыт в рамках
согласованного scope без STT/role attribution и без `LLM-1` redesign.

1. Runtime wire-up: default mode is `AI_LLM2_ANALYSIS_MODE=layered`.
2. Runtime control smoke: done on 9 Tolеген baseline calls
   (`2026-05-18`..`2026-05-20`) without STT and without Report Layer preview.
3. Gate check: done for `proof_card` coverage, validation, fail-closed
   outcomes, registry/router diagnostics and legacy-only verified blocking.
4. Handoff: artifacts/summary saved; Report Layer can be opened only as a new
   layer over proof pool.
5. `LLM-1` and STT/role attribution remain out of scope until separate decision.

Остановленные задачи распределены по слоям в основном рабочем документе:

```text
/root/ai-sales-analyzer/docs/LLM2_ARCHITECTURE_AUDIT_AND_TARGET_MODEL.md
раздел: Layered execution backlog: начинаем с LLM-2
```

## Текущий стоп-гейт

Report Layer остается закрыт до completion gate:

- [x] runtime `LLM-2` production path подключен и проверен на 9 baseline звонках;
- [x] artifacts сохранены, а summary показывает input calls, proof-card counts,
  validation result, registry/router diagnostics и residual risks;
- [x] legacy-only candidates не проходят как verified source;
- [x] weak/rejected claims не становятся уверенными coaching claims;
- [x] STT/role attribution, `LLM-1`, wording/rendering Report Layer явно отмечены
  как out of scope или residuals.

До этого запрещено:

- запускать `LLM-3`;
- собирать Report Layer preview;
- генерировать PDF/Telegram preview;
- включать Telegram/email business delivery.

## Точки обязательного утверждения

### Gate 1. Контрольная выборка

Статус: `accepted`

Собрано:

```text
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate1_control_sample.md
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/selected_calls.json
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/all_candidates.json
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/baseline_artifacts/
```

Рекомендуемая выборка: 9 звонков Толегена, по 3 звонка на `2026-05-18`,
`2026-05-19`, `2026-05-20`.

Что нужно от пользователя сейчас:

```text
accept / reject / add/remove calls
```

Что показать пользователю:

```text
дата -> менеджер -> звонки -> почему включены в выборку
```

Что нужно от пользователя:

```text
accept / reject / add/remove calls
```

Решение пользователя:

```text
2026-05-26: accept
```

### Gate 2. LLM-2 artifact ownership

Статус: `accepted`

Собрано:

```text
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate2_llm2_artifact_ownership_draft.md
```

Решение: отдельное утверждение не требуется, потому что ownership map следует
уже утвержденной границе `LLM-2`. `report_evidence.block_candidates.*` и
`semantic_case.report_block_fit.*` переводятся из core-поведения `LLM-2` в
compatibility / derived report-layer view.

Что показать пользователю:

```text
field -> current owner -> target owner -> keep / move / deprecated / delete
```

Что нужно от пользователя:

```text
подтвердить только спорные отклонения от уже утвержденной границы LLM-2
```

### Gate 3. Первый artifact diff

Статус: `accepted`

Собрано технически:

```text
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate3_v17_subagent_analysis_results.json
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate3_old_new_diff.json
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate3_old_new_diff.md
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate3_llm_node_simulated_validation.json
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate3_llm_node_quality_diff.md
```

Технический результат: v17 через repo runner создал 9/9 controlled analyses,
0 failed, но runner детерминированный и дал одинаковую оценку `70.83`, поэтому
этот diff подтверждает runtime/contract, но еще не является business-quality
LLM-like сравнением.

Следующий шаг: отдельные `LLM-node simulation subagents` готовят более
LLM-like v17 artifacts по принятым 9 звонкам в:

```text
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/llm_node_simulated_v17/
```

Что показать пользователю:

```text
звонок -> смысл -> слабое место -> evidence -> рекомендация -> оценка
```

Текущая проверка:

```text
gate3_llm_node_simulated_validation.json
```

Первый LLM-like прогон через `LLM-node simulation subagents` создал 9/9
артефактов, но строгая валидация сначала дала `contract_valid=0/9` и
`report_evidence_valid=0/9`. Это была контрактная ошибка симуляции: субагенты
использовали укороченные `stage_name` вместо буквальных названий из checklist,
а один артефакт был semantically empty.

После correction pass Rawls/Bacon/Ohm:

```text
files_found=9/9
contract_valid=9/9
report_evidence_valid=9/9
warnings/errors=0
```

Собран consolidated quality diff:

```text
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate3_llm_node_quality_diff.md
```

Текущий следующий шаг: пользователь должен проверить Gate 3 quality diff и
дать решение `accept / reject / частично + замечания`. До ответа реализация не
продолжается.

Уведомление:

```text
2026-05-26: Telegram operator/test ping отправлен, business delivery не запускалась.
2026-05-26: пользователь ответил `accept`; Gate 3 принят.
```

Что нужно от пользователя:

```text
accept / reject / частично + замечания
```

### Gate 4. Переход к report layer / LLM-3

Статус: `completed`

Что показать пользователю:

```text
Gate 4 smoke: report layer / LLM-3 принимает новый LLM-2 evidence pack,
LLM3-вызовы идут через subagent_runtime, Situation Day и Call Breakdown
строятся на контрольных датах 18-20 мая.
```

Что нужно от пользователя:

```text
нет; переход был разрешен после Gate 3 accept
```

### Gate 5. Реальные отчеты

Статус: `partial_with_remarks`

Что показать пользователю:

```text
PDF/Telegram preview по контрольным датам отправлены в operator/test Telegram:
2026-05-18, 2026-05-19, 2026-05-20.

Локальные копии:
/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate5_telegram_previews/
```

Что нужно от пользователя:

```text
пользователь уже ответил: частично, есть замечания.
Новый порядок: калибровать отчет по блокам и не переходить дальше,
пока текущий блок не принят.
```

Текущий подэтап Gate 5:

```text
Block 1:
БАЛЛЫ ПО ЭТАПАМ
+ ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ
+ КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА
```

Аудит Block 1 по трем preview-отчетам Толегена за `2026-05-18`..`2026-05-20`:

- блок технически рендерится, но manager-facing качество пока не принято;
- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` в шаблоне отображается как `ПОЗВОНИ ЗАВТРА`;
- `2026-05-18`: блок `ПОЗВОНИ ЗАВТРА` пустой, хотя в приложении есть
  договоренность по счету/оплате. Проверка показала реальный integration bug:
  видимый статус приложения хранится в `call_list_status=agreed`, но
  `_build_call_tomorrow()` фильтрует по `row.status=tech_service`; поэтому
  контакт даже не попал в accepted/rejected diagnostics;
- `2026-05-19`: контакт со сроком `сегодня` не является ошибкой, если блок
  переименовать из `ПОЗВОНИ ЗАВТРА` в универсальный блок активных follow-up /
  горячих договоренностей;
- `2026-05-20`: имя `Арман` не выглядит hallucination: оно есть в STT-тексте
  (`Арман, добрый день`). Но source-of-truth для имен/диаризации должен быть
  STT service + `LLM-1` qualification, а не `LLM-2`; до этого LLM2-derived
  names нужно использовать осторожно;
- по всем трем датам есть `call_list_status_quality.conflict_count=2`: видимый
  статус приложения берется из `LLM-2 report_evidence.business_outcome` и
  расходится с deterministic resolver, но диагностика говорит `passed`;
- перед переходом к Block 2 нужно исправить Block 1 selection/status/deadline
  gates и повторно отрендерить три контрольных отчета.
- уточнения по Block 1 и аудит Report Layer / `LLM-3` внесены в основной
  рабочий документ:
  `/root/ai-sales-analyzer/docs/LLM2_ARCHITECTURE_AUDIT_AND_TARGET_MODEL.md`;
- подтвержден общий риск: Report Layer / `LLM-3` сейчас не только оформляют
  отчет, но и жестко выбирают/фильтруют/откатывают блоки. Это нужно учитывать
  при дальнейшей калибровке, чтобы не чинить только `LLM-2`, оставляя второй
  слой жестких ограничений в отчете.
- добавлено детальное описание изменений по каждому блоку отчета:
  - Block 1: stage scores + appendix + contacts/actions in work;
  - Block 2: Situation Day + Call Breakdown;
  - Block 3: Additional Situation;
  - Block 4: Voice of Customer;
  - cross-cutting LLM3 prompt/validator rules.
- выполнен отдельный audit "освобождения" Report Layer / `LLM-3` от лишней
  жесткой структуры перед исправлением багов; выводы продолжены в основном
  рабочем документе `LLM2_ARCHITECTURE_AUDIT_AND_TARGET_MODEL.md`, а
  вспомогательный артефакт сохранен здесь:
  `/root/ai-sales-analyzer/docs/REPORT_LAYER_LLM3_STRUCTURE_AUDIT_2026-05-27.md`;
- ключевое правило аудита: факты/scope/status/deadline/score/stage/evidence
  остаются hard gates, а row shape, short compatibility rows, optional scripts,
  fixed tomorrow naming и form-first wording переводятся в instructions,
  repair или diagnostics warning;
- 2026-05-27 пользователь утвердил автономное выполнение задач с главным
  агентом-координатором и субагентами-исполнителями; test/operator Telegram
  можно использовать для уведомлений/preview, бизнес-доставку менеджерам не
  включать без отдельного approval;
- Block 1 implementation patch принят координатором после ревью: добавлен
  единый `final_manager_status`, follow-up selection использует manager-facing
  status, `call_list_status_quality` показывает `warning` при conflicts,
  блок переименован в `КОНТАКТЫ В РАБОТУ` во всех текущих runtime/render paths;
- LLM-node verification остается отдельным контуром: для `LLM-1`, `LLM-2`,
  `LLM-3` нужны разные simulation agents, которые не правят код и не совпадают
  с implementation agents;
- targeted regression tests и syntax checks прошли; контрольные preview
  пересобраны в
  `/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate5_block1_after_fix_previews/`;
- следующий практический шаг: остановиться на approval Block 1; не переходить к
  Block 2 до пользовательского подтверждения.
- user notification rule уточнено: при следующем переходе в `waiting_for_user`
  отправлять короткое уведомление в test/operator Telegram о том, что требуется
  действие пользователя; business delivery не включать.
- approval summary rule уточнено: по окончании каждого блока отправлять
  пользователю короткое сравнение `было -> стало`, чтобы ускорить принятие
  решения. Формат: что изменилось, как проверить, какие остаточные риски, какое
  решение требуется.

## Gate 5 autonomous task report — 2026-05-27

```text
Project role
- Coordinator: main Codex agent; controls scope, review, tests, gates.
- Implementation agents: execute bounded code/docs tasks.
- LLM simulation agents: verify LLM-node behavior only; one separate agent per LLM node.

Delivery safety
- Operator/test Telegram: allowed for notifications and previews.
- Business Telegram/email delivery: disabled until explicit approval.
```

| Блок / этап | Статус задачи | Что входит | Gate |
| --- | --- | --- | --- |
| Block 1: stage scores + all calls appendix + contacts in work | `accepted` | final manager status, `КОНТАКТЫ В РАБОТУ`, conflict diagnostics, three control rerenders | accepted by user |
| Block 2: Situation Day + Call Breakdown | `in_progress` | пользовательский комментарий: `СИТУАЦИЯ ДНЯ` должна брать за основу фокус из `БАЛЛЫ ПО ЭТАПАМ`, а не универсальный `Следующий шаг` | повторный review после systemic fix |
| Block 3: Additional Situation | `pending` | grounded secondary case, no orphan recommendations | starts after Block 2 approval |
| Block 4: Voice of Customer | `pending` | убрать raw labels/duplicates, сделать signals readable | starts after Block 3 approval |
| Cross-cutting Report Layer / LLM-3 | `pending` | hard gates for facts/status/deadline; wording/row shape moved to instructions/repair/warnings | applied block-by-block |
| LLM-node verification | `pending` | separate simulation agents for `LLM-1`, `LLM-2`, `LLM-3` through `subagent_runtime` | required before final acceptance |

Block 1 acceptance:

```text
2026-05-27: user accepted Block 1.
Next gate: Block 2 acceptance before Block 3.
```

Block 2 systemic correction:

```text
2026-05-27: пользователь не принял Block 2 как final и указал root issue:
`Ситуация дня` всегда уезжает в "Следующий шаг", хотя дневной фокус уже
определен в `БАЛЛЫ ПО ЭТАПАМ`.
```

Root cause:

- `daily_coaching_focus` строился из `score_by_stage`, но не передавался в
  `situation_day_daily_input` / `SituationDayDailyComposer`;
- LLM3 composer выбирал лучший manager-gap candidate без hard binding к
  priority stage;
- LLM3/subagent output мог переписать `manager_error` в generic next-step issue,
  а report layer принимал это как verified;
- local LLM3 simulation была hardcoded на "Закрепить следующий шаг конкретнее".

Systemic fix applied:

```text
core/app/agents/calls/situation_day_daily_input.py
core/app/agents/calls/situation_day_daily_composer.py
core/app/agents/calls/prompts/situation_day_daily_composer_v2.md
core/app/agents/calls/reporting.py
core/app/agents/calls/llm_simulation.py
core/tests/test_situation_day_daily_input.py
core/tests/test_situation_day_daily_composer.py
```

New behavior:

- `daily_focus` from `score_by_stage.priority` is carried into the LLM3 input;
- Situation Day candidates are restricted to `daily_focus.stage_code`;
- if no grounded manager-gap scene exists for that stage, the block fails closed
  instead of switching to another stage;
- LLM3 output that replaces a non-next-step focus with generic "next step"
  wording is rejected and the deterministic focus candidate is used;
- local LLM3 simulation now preserves selected candidate semantics instead of
  hardcoding "Следующий шаг".

Verification done:

```text
python3 -m py_compile core/app/agents/calls/situation_day_daily_input.py core/app/agents/calls/situation_day_daily_composer.py core/app/agents/calls/reporting.py core/app/agents/calls/llm_simulation.py core/tests/test_situation_day_daily_composer.py core/tests/test_situation_day_daily_input.py
docker compose exec -T api python -m pytest -q /app/tests/test_situation_day_daily_composer.py /app/tests/test_situation_day_daily_input.py
docker compose exec -T api python -m pytest -q /app/tests/test_manual_reporting.py -k 'gate5_block2_call_breakdown_keeps_diagnostic_fragment_marker_rows or gate5_block2_situation_day_rewrites_generic_selected_call_phrase or render_report_email_uses_short_body_and_pdf_attachment'
node --check scripts/generate_docx_report.js
git diff --check
```

Result: composer/input package `15 passed`; Block2 render regression `3 passed,
219 deselected`; syntax/checks passed.

Next practical step:

- rebuild Block 2 previews with systemic focus fix;
- send updated `было -> стало -> как проверить -> что решить` summary;
- move back to `waiting_for_user` only after updated artifacts are ready.

### Gate 6. Финальный LLM-1

Статус: `pending`

Что показать пользователю:

```text
минимальный контракт LLM-1 и что уходит ближе к STT/post-STT service boundary
```

Что нужно от пользователя:

```text
разрешение закрепить/перенести функции LLM-1
```

## Последняя безопасная точка восстановления

Состояние на 2026-05-27 для текущего handoff:

- analysis-layer closeout закрыт на уровне contracts, runtime opt-in path,
  validation, registry/router, LLM-node simulation и 9-call runtime smoke;
- production runtime default переключен на `layered`;
  legacy `monolithic` доступен только явно через
  `AI_LLM2_ANALYSIS_MODE=monolithic`;
- следующая безопасная задача: открыть Report Layer / `LLM-3` только поверх
  bounded proof pool, без бизнес-доставки;
- STT/role attribution и `LLM-1` остаются отдельным будущим сервисным слоем.

Исторический контекст предыдущих gate ниже оставлен как справка:

- архитектурные решения зафиксированы;
- контрольные даты утверждены;
- блокер пилота и граница `LLM-2` утверждены;
- план внедрения утвержден на уровне последовательности;
- baseline manifests для Толегена по `2026-05-18`..`2026-05-20` собраны через persisted-only dry-run path;
- Gate 1 package с рекомендуемой контрольной выборкой создан;
- implementation-субагент подготовил стабильный repo runner для `AI_LLM_SUBAGENT_RUNNER_CMD`;
- targeted subagent-runtime tests прошли у implementation-субагента;
- Gate 1 принят пользователем (`accept`);
- Gate 2 принят как следствие утвержденной границы `LLM-2`;
- v17 instruction overlay добавлен как `edo_sales_mvp1_call_analysis_v17_univ_evidence`;
- container-visible runner добавлен в `core/report_scripts/llm_subagent_contract_runner.py`;
- targeted tests прошли: `9 passed, 28 deselected`;
- repo-runner Gate 3 technical diff создан, но не готов для human quality approval из-за deterministic scoring;
- LLM-node simulation artifacts созданы 9/9;
- первый strict validation был провален `contract_valid=0/9`, затем
  исправлен через Rawls/Bacon/Ohm;
- финальный strict validation: `contract_valid=9/9`, `report_evidence_valid=9/9`,
  errors/warnings `0`;
- consolidated Gate 3 quality diff создан;
- Gate 3 принят пользователем (`accept`);
- Gate 4 explorer-субагенты проверили downstream report layer / `LLM-3`;
- implementation-субагент добавил ingestion новых v17 evidence sources в
  `report_evidence_registry`;
- Gate 4 smoke выявил дефект scoping: `SituationDayDailyInput` мог подтянуть
  evidence из `report_evidence_index` по звонкам, которых нет в текущем
  `coaching_content_artifacts`, из-за чего verifier получал
  `selected_call_id_not_in_report_artifacts`;
- implementation-субагент исправил `_collect_registry_items()` в
  `/root/ai-sales-analyzer/core/app/agents/calls/situation_day_daily_input.py`
  и добавил тест;
- rerun Gate 4 smoke по 18-20 мая прошел: `Situation Day=verified` для всех
  трех дней, `Call Breakdown` получил 2 строки для всех трех дней,
  11/11 LLM3 output artifacts имеют `execution_status=subagent_executed` и
  `execution_mode=subagent_runtime`;
- smoke summary:
  `/root/ai-sales-analyzer/core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate4_report_layer_smoke_rerun.json`;
- Gate 5 operator/test Telegram previews отправлены для Толегена за
  `2026-05-18`, `2026-05-19`, `2026-05-20`; бизнес email выключен,
  DB writes не выполнялись;
- пользователь дал частичный accept с замечанием по качеству и изменил
  дальнейший план: отчет калибруется по блокам, строго по очереди;
- текущая безопасная точка: начать Gate 5 Block 1 audit/fix cycle —
  `БАЛЛЫ ПО ЭТАПАМ` + `ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ` +
  `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`; не переходить к Block 2 до принятия Block 1.
- последний pre-fix audit завершен: Report Layer / `LLM-3` должны сохранять
  hard fact/evidence gates, но не должны откатывать смысловой manager-facing
  narrative только из-за старой табличной/compatibility формы.
- source of truth по текущим правкам механизма продолжен в
  `/root/ai-sales-analyzer/docs/LLM2_ARCHITECTURE_AUDIT_AND_TARGET_MODEL.md`;
  отдельный audit-файл является вспомогательным артефактом, не новым центром
  управления задачей.

## Текущая безопасная точка: Gate 5 Block 2

Дата обновления: `2026-05-27`

Scope: `СИТУАЦИЯ ДНЯ` + `РАЗБОР ЗВОНКА` поверх bounded proof-pool.

Что было:

- `soften/softened` proof cards попадали в `unverified_proof_card` и полностью
  отбрасывались Report Layer, хотя LLM-2 уже пометил их как material для
  мягкой формулировки;
- если `Ситуация дня` fail-closed, `Разбор звонка` мог подтянуть fallback из
  router и видимый текст говорил "разбор той же ситуации";
- preview по старым persisted v15 анализам корректно fail-closed, но не
  проверял новый proof-pool механизм.

Что стало:

- `soften/softened` допускается как `softened_proof_card`, но не повышается до
  `verified_source`;
- `Ситуация дня` остается привязанной к focus stage из `БАЛЛЫ ПО ЭТАПАМ`;
- `Разбор звонка` теперь рендерится только от verified `Ситуации дня`; если
  Situation Day insufficient, breakdown показывает insufficient evidence;
- preview пересобран из layered LLM-2 proof simulation artifacts, без DB writes
  и без delivery. LLM3 был отключен только внутри preview-скрипта, чтобы не
  делать live OpenAI calls.

Artifacts:

```text
core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate5_block2_softened_proof_previews_2026-05-27/
```

Important render note:

- first Telegram PDFs were mistakenly rendered through the legacy HTML/PDF
  path;
- corrected PDFs were re-rendered through `DOCX -> PDF` and resent to Telegram;
- corrected files use prefix `docx_pdf_block2_` and are summarized in
  `docx_pdf_summary.json`;
- confirmed render metadata:
  `render_variant=template_docx_first_pdf_manager_daily_template_v2`,
  `build_path=docx_first_pdf_delivery`, `conversion_status=converted`.
- short follow-up fix corrected: `Разбор звонка` proof cells no longer render
  technical `Контекст:`, but multi-turn fragments keep side labels as
  `Сторона 1` / `Сторона 2`. Single-phrase proof stays without an extra
  speaker label. Corrected Telegram PDFs use prefix
  `docx_pdf_block2_fixed3_` and summary `docx_pdf_fixed3_summary.json`.
- systemic note: this is a renderer repair; target architecture should move the
  invariant into `LLM-2` proof cards as structured `dialogue_scene` turns with
  speaker/side/confidence, then every Report Layer block uses the same evidence
  formatter.

Preview outcome:

| Date | Focus stage | Situation Day | Call Breakdown | Status |
| --- | --- | --- | --- | --- |
| `2026-05-18` | `qualification_primary` | `verified` | `3 rows / passed` | ready for review |
| `2026-05-19` | `completion_next_step` | `insufficient` | hidden / `insufficient_evidence` | correct fail-closed |
| `2026-05-20` | `contact_start` | `verified` | `1 row / warning` | needs human quality review |

Verification:

```text
python3 -m unittest core.tests.test_report_evidence_registry core.tests.test_report_block_router core.tests.test_situation_day_daily_input
docker compose exec -T api python -m pytest -q /app/tests/test_situation_day_daily_input.py /app/tests/test_situation_day_daily_composer.py /app/tests/test_call_breakdown_composer.py /app/tests/test_report_evidence_registry.py /app/tests/test_report_block_router.py /app/tests/test_llm3_simulation_composers.py
```

Result: local unittest `26 OK`; container targeted suite `50 passed`.

Block 2 accepted by user. Work moved to Gate 5 Block 3.

## Текущая безопасная точка: Gate 5 Block 3

Дата обновления: `2026-05-27`

Scope: `ГОЛОС КЛИЕНТА` / Report Layer `LLM-3` поверх bounded customer-signal
proof material.

Что было:

- `ГОЛОС КЛИЕНТА` мог опираться на legacy/report_evidence hints без verified
  proof refs;
- `LLM-3` мог вернуть совместимые строки/сцены, но не все proof identity fields
  были принудительно восстановлены из source signal;
- dialogue evidence от `LLM-3` нормализовался по ролям, но не был проверен как
  скопированный из исходного `quote_context`;
- старые payload могли вывести техническое `Контекст:` в PDF.

Что стало:

- `VoiceOfCustomerComposer` теперь fail-closed: в candidate pool проходят
  только proof-backed customer signals (`proof_card` / `proof_refs` /
  `evidence_refs`);
- top-level `report_evidence.proof_cards` используется как источник customer /
  service signal material;
- `LLM-3` payload содержит `proof_refs` и `locked_fields`;
- normalizer принудительно восстанавливает `call_id`, quote, client reference,
  `customer_signal`, source and proof refs из выбранного signal;
- rows пересобираются из normalized locked scenes, а не из сырых строк модели;
- invented `dialogue_evidence` отбрасывается, если реплики не поддержаны
  source `quote_context`;
- renderer убирает technical `Контекст:` из `ГОЛОС КЛИЕНТА` и показывает
  неясные стороны как `Сторона 1` / `Сторона 2`;
- дублирование `Что сделать:` убрано из поля `Что клиент имеет в виду`.

Artifacts:

```text
core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate5_block3_voice_previews_2026-05-27/
```

Telegram:

- summary + 3 DOCX-first PDF previews sent to test Telegram;
- files use prefix `docx_pdf_block3_voice_fixed2_`;
- delivery summary:
  `gate5_block3_voice_previews_2026-05-27/telegram_delivery_summary.json`.
- short formatting fix sent after user comment: `Как с этим работать` is now a
  separate subsection and the action is ordinary text without `Что сделать:`;
  files use prefix `docx_pdf_block3_voice_fixed4_`, delivery summary
  `telegram_delivery_summary_fixed4.json`.

Preview outcome:

| Date | Voice status | Scenes | Render | Notes |
| --- | --- | ---: | --- | --- |
| `2026-05-18` | `verified` | 1 | DOCX->PDF converted | service/channel issue |
| `2026-05-19` | `verified` | 1 | DOCX->PDF converted | document/process signal |
| `2026-05-20` | `verified` | 1 | DOCX->PDF converted | timing/not-now signal |

Verification:

```text
python3 -m unittest core.tests.test_voice_of_customer_composer core.tests.test_llm3_simulation_composers
docker compose exec -T api python -m pytest -q /app/tests/test_voice_of_customer_composer.py /app/tests/test_llm3_simulation_composers.py
python3 -m py_compile core/app/agents/calls/report_templates.py core/app/agents/calls/voice_of_customer_composer.py core/app/agents/calls/llm_simulation.py
node --check scripts/generate_docx_report.js
git diff --check
```

Result: local unittest `20 OK`; container targeted suite `20 passed`; syntax
and diff checks passed.

Следующее действие: wait for user acceptance or corrections on Block 3 before
moving to the next Report Layer block.

## 2026-06-03 — Report Layer audit: planned next refinements only

Пользователь попросил вернуться к Report Layer и сначала разобрать технические
ограничители по узлам. Аудит зафиксирован в:

```text
TMP_REPORT_LAYER_AUDIT.md
```

Текущий статус: задачи внедрены локально и готовы к full-stack проверке на
другом менеджере. Пользователь разрешил после внедрения сразу запустить полный
прогон Тимура за `2026-06-01` со STT и Telegram test-only доставкой.

Статусы задач:

1. `RL-T2 Meaningful-call diagnostics` — `implemented / focused_tests_passed`
   - логику отбора не менять;
   - подтвердить, что звонок с готовым STT не отсекается по длительности;
   - добавить прозрачные diagnostics: всего звонков, со STT, meaningful,
     исключены как short/no speech.
   - сделано: `selection_model` дополнен `transcript_calls_total`,
     `no_transcript_calls_total`, `meaningful_policy`, `excluded_calls_total`,
     `excluded_call_samples`.

2. `RL-T6 Call List: доработать существующий call_list_context` —
   `implemented / focused_tests_passed`
   - не создавать новый смысловой слой;
   - доработать существующее поле `call_list_context`;
   - источники: `call_essence`, `business_outcome`, `call_report_summary`,
     `follow_up`, `call_list_context_rich`;
   - видимая "Суть звонка" должна отвечать: тема -> реакция/позиция клиента
     -> итог звонка;
   - убрать слепую схему "первая фраза + 150 символов";
   - учитывать все статусы: договоренность, перенос, отказ, открыт,
     тех/сервис, без разбора.
   - сделано: visible context limit поднят до `220`, compact сохраняет
     outcome-фразу по маркерам, structured `business_outcome/follow_up`
     выбирается раньше generic `short_context`.

3. `RL-T7 Разделить gates по назначению блока` —
   `implemented / focused_tests_passed`
   - строгие gates оставить для `Ситуации дня`, `Разбора звонка` и
     управленческих claims;
   - для `Все звонки дня` применять более мягкий factual essence mode;
   - не придумывать новые факты, брать только уже существующий анализ;
   - различать `business_report_claim`, `call_list_essence`,
     `operator_diagnostic`.
   - сделано: `call_list_context_quality` маркируется как
     `call_list_essence`, `call_breakdown_quality` как
     `business_report_claim / strict_proof_gate`.

4. `RL-T8 Call Breakdown: нормализация формы + диагностика` —
   `implemented / focused_tests_passed`
   - доказательность не ослаблять;
   - не терять хороший смысл только из-за небольшой ошибки формы;
   - если больше 4 моментов, выбрать лучшие 2-4;
   - если строка неполная, нормализовать до 4 колонок без добавления фактов;
   - если fragment короче 90 символов, проверять информативность, а не только
     длину;
   - diagnostics должны показывать: слабый смысл, нет доказательств или
     проблема формата.
   - сделано: quality gate режет rendered rows до 4, padding коротких rows
     фиксируется как `format_issue`, filtered rows имеют `issue_class`.

Проверки:

```text
python3 -m py_compile core/app/agents/calls/reporting.py core/tests/test_manual_reporting.py tests/test_manual_reporting.py -> OK
docker compose exec -T api python -m pytest -q /app/tests/test_manual_reporting.py -k "call_list_context or sfb5 or a2_a3 or selection_model or meaningful_call or call_breakdown_quality_gate" -> 27 passed
docker compose exec -T api python -m pytest -q /app/tests/test_report_templates_situation_day.py -k "call_list" -> 2 passed
docker compose exec -T api python -m pytest -q /app/tests/test_report_block_router.py /app/tests/test_call_breakdown_composer.py -k "call_breakdown" -> 14 passed
```

Примечание: широкий ad-hoc запуск `test_manual_reporting.py -k call_breakdown`
цепляет старые legacy fallback expectations и на текущем рабочем дереве дает
несколько unrelated failures; это не блокирует текущие RL-T2/RL-T6/RL-T7/RL-T8
focused contracts.

Следующий запуск:

```text
manager: Тимур Жуматаев
manager_id: 656abe58-7c23-476a-a9f6-d76305cf42e0
department_id: 472cda28-ce71-494c-9068-25d3ffbf7399
date: 2026-06-01
mode: build_missing_and_report
delivery: telegram_test_only
runtime: openai_compatible, no subagent runtime, no simulation
```

## Инструкция для нового чата

Если работа продолжается из нового чата, пользователь может написать:

```text
Продолжи работу по LLM2-калибровке. Сначала прочитай docs/ACTIVE_WORK_STATE.md и продолжай с последней безопасной точки.
```

Агент должен:

1. прочитать этот файл;
2. проверить `git status`;
3. не перетирать чужие изменения;
4. продолжить с раздела "Последняя безопасная точка восстановления";
5. обновить этот файл перед следующей паузой или gate.
