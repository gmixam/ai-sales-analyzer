# Kimi K2.6 Trial Handoff

Дата: 2026-06-02

Статус: `blocked_for_current_llm2_contract`

## Короткий вывод

Kimi / Moonshot подключен как OpenAI-compatible provider source. `LLM2` и
`LLM3` маршрутизируются на `kimi-k2.6`, но текущий layered `LLM2A/B/C/D`
контракт для Kimi K2.6 пока непригоден для полного прогона:

- ответы `LLM2A` часто приходят пустыми или невалидным JSON;
- при `max_tokens=8192` ответ упирается в лимит и ломает JSON;
- при `max_tokens=16384` / `32768` запросы становятся слишком долгими и
  зависают на первом звонке или на `LLM2B`;
- repair может формально довести проход до конца, но результат остается
  пустым: `stages=0`, `criteria=0`, `score=0.0`.

Отчет через `LLM3=kimi-k2.6` по этому K2.6 rerun не строился и в Telegram не
отправлялся, потому что `LLM2` не дал пригодных report artifacts.

## Текущая runtime-настройка

В живом `.env` после переключения:

```text
AI_LLM_EXECUTION_MODE=openai_compatible
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SUBAGENT_RUNTIME_LAYERS=
AI_LLM_SIMULATION_ENABLED=false

AI_LLM2_FIXED_ACCOUNT_ALIAS=kimi_llm2_main
AI_LLM3_FIXED_ACCOUNT_ALIAS=kimi_llm3_main

LLM2 -> kimi_llm2_main -> kimi-k2.6 -> https://api.moonshot.ai/v1/chat/completions
LLM3 -> kimi_llm3_main -> kimi-k2.6 -> https://api.moonshot.ai/v1/chat/completions
api_key_env -> MOONSHOT_API_KEY
```

Перед любым новым запуском проверить route-plan внутри контейнера:

```bash
docker compose exec -T api python - <<'PY'
from app.core_shared.ai_routing import AIProviderRouter
for layer in ("llm2", "llm3"):
    c = AIProviderRouter().build_route_plan(layer=layer, subject_key=layer).current_candidate()
    print(layer, c.account_alias, c.model, c.api_base, c.endpoint, c.timeout_sec)
PY
```

Ожидаемо:

```text
llm2 kimi_llm2_main kimi-k2.6 https://api.moonshot.ai/v1 /chat/completions 300
llm3 kimi_llm3_main kimi-k2.6 https://api.moonshot.ai/v1 /chat/completions 300
```

## Что было сделано

1. Переключили `LLM2` Kimi provider с `moonshot-v1-32k` на `kimi-k2.6`.
2. `LLM3` уже был на `kimi-k2.6`; route-plan подтвердил актуальную модель.
3. Пересоздали контейнеры `api`, `worker`, `beat`, чтобы `.env` применился.
4. Проверили targeted routing tests:

```text
docker compose exec -T api python -m pytest -q /app/tests/test_ai_provider_routing.py -k 'kimi_k26_chat_kwargs_force_supported_temperature or llm2_layered_pass_captures_provider_usage_diagnostics'
-> 2 passed

git diff --check
-> clean
```

5. Добавили технический env-control для LLM2 output cap:

```text
AI_LLM2_OUTPUT_MAX_TOKENS
```

По умолчанию остается `8192`; допустимый диапазон capped до `32768`.

6. Добавили контролируемый env-only local repair режим:

```text
AI_LLM2_LOCAL_JSON_REPAIR_ENABLED=true
```

По умолчанию выключен. Нужен только для controlled experiments с truncated JSON,
не является production-quality решением.

## Контрольные прогоны K2.6

Менеджер: Толеген Жангазиев  
Дата звонков: `2026-06-01`  
Готовые STT: `6`  
Ожидаемо коммерчески допущенных к `LLM2`: `5`; один короткий звонок `16 сек`
раньше отсекался admission gate.

### Run A: базовый K2.6, max_tokens=8192

Instruction version:

```text
llm2_compact_kimi_k26_rerun_v1_20260602
```

Output dir:

```text
/tmp/llm2_compact_kimi_k26_rerun_20260601_tolegen
```

Log:

```text
/root/ai-sales-analyzer/review_packages/llm2_compact_kimi_k26_rerun_20260601_tolegen.log
```

Факт:

- первый `LLM2A` выбрал `kimi_llm2_main / kimi-k2.6`;
- ответ пришел невалидным JSON:

```text
Unterminated string starting at: line 1 column 6484
```

- внешний `llm2a_facts_scenes_json_repair` завис на сетевом ожидании;
- запуск остановлен вручную.

### Run B: K2.6, max_tokens=32768

Instruction version:

```text
llm2_compact_kimi_k26_maxtok_v1_20260602
```

Output dir:

```text
/tmp/llm2_compact_kimi_k26_maxtok_20260601_tolegen
```

Log:

```text
/root/ai-sales-analyzer/review_packages/llm2_compact_kimi_k26_maxtok_20260601_tolegen.log
```

Факт:

- `LLM2A` первого звонка прошел без JSON repair;
- затем `LLM2B` завис слишком долго;
- запуск остановлен вручную.

### Run C: K2.6, max_tokens=16384

Instruction version:

```text
llm2_compact_kimi_k26_16k_v1_20260602
```

Output dir:

```text
/tmp/llm2_compact_kimi_k26_16k_20260601_tolegen
```

Log:

```text
/root/ai-sales-analyzer/review_packages/llm2_compact_kimi_k26_16k_20260601_tolegen.log
```

Факт:

- даже первый `LLM2A` не вернулся за разумное время;
- запуск остановлен вручную.

### Run D: K2.6, max_tokens=8192 + local repair enabled

Instruction version:

```text
llm2_compact_kimi_k26_localrepair_v1_20260602
```

Output dir:

```text
/tmp/llm2_compact_kimi_k26_localrepair_20260601_tolegen
```

Log:

```text
/root/ai-sales-analyzer/review_packages/llm2_compact_kimi_k26_localrepair_20260601_tolegen.log
```

Факт:

- первый `LLM2A` вернул пустой / не JSON ответ:

```text
Expecting value: line 1 column 1 (char 0)
```

- локальный repair не мог починить пустой ответ, поэтому включился внешний
  `llm2a_facts_scenes_json_repair`;
- первый звонок формально завершился, но результат непригоден:

```text
interaction_id=db11ca8e-f6ef-4418-8146-c7697834e005
analysis_id=f77c0291-fce9-47ac-b460-b9be0b6632e0
score=0.0
stages=0
criteria=0
passes=llm2a,llm2b,llm2c,llm2d
llm2a completion_tokens=8192
llm2a output_chars=2
llm2a repair_strategy=llm_json_repair
```

- второй звонок начал `LLM2A`, снова получил:

```text
Expecting value: line 1 column 1 (char 0)
```

- пользователь попросил остановить прогон;
- runner остановлен, активных процессов нет;
- Telegram report не строился и не отправлялся.

## Почему это важно

Codex-subagent имитация давала более качественный смысловой анализ, потому что
агент лучше держал роль `LLM2` и контракт. Kimi K2.6 теоретически сильная модель,
но в текущем OpenAI-compatible JSON режиме она плохо исполняет именно наш
layered `LLM2` contract:

- `LLM2A` слишком большой/сложный для стабильного JSON;
- `LLM2B` с расширенным output cap становится слишком медленным;
- repair не является достаточным решением, потому что иногда исходный ответ
  пустой, а иногда repair приводит к пустой структуре;
- downstream report layer нельзя кормить такими результатами.

## Чего не делать следующему агенту

- Не запускать полный день через `LLM2=kimi-k2.6` без изменения `LLM2` contract.
- Не формировать manager-facing отчет из K2.6 результатов с `stages=0` /
  `criteria=0`.
- Не считать local JSON repair production fix.
- Не смешивать Kimi K2.6 trial с Codex-subagent quality benchmark: это разные
  runtime executors.
- Не отправлять бизнес-доставку менеджерам; Telegram только test/operator.

## Следующая безопасная точка

Есть два разумных пути:

1. **Откатить `LLM2` на более стабильную модель** и оставить Kimi K2.6 только
   для `LLM3` или для отдельных experiments.

   Возможные варианты:

   ```text
   LLM2 -> gpt-5.4-mini / gpt-5.5 / прежний moonshot-v1-32k
   LLM3 -> kimi-k2.6 или OpenAI модель
   ```

2. **Сделать Kimi-specific contract simplification**, но не как prompt hack:

   - сократить `LLM2A` output contract;
   - жестко ограничить число scenes/evidence per pass;
   - вынести scoring summary в deterministic adapter;
   - добавить fail-closed правило: если `LLM2B.stage_scores=[]` после admission,
     анализ считать failed, а не `score=0`;
   - тестировать сначала один звонок, затем максимум 2-3 звонка, только потом
     день.

Рекомендация на текущий момент: для ближайшего качественного тестирования
вернуться к Codex-subagent или OpenAI max-quality для `LLM2`, а Kimi K2.6
считать отдельным исследовательским направлением.

## Быстрый вход для нового агента

Открыть по порядку:

```text
/root/ai-sales-analyzer/docs/ACTIVE_WORK_STATE.md
/root/ai-sales-analyzer/docs/RUNTIME_PROFILES.md
/root/ai-sales-analyzer/docs/KIMI_K26_TRIAL_HANDOFF_2026-06-02.md
```

Исторические материалы по LLM2 input optimization и semantic defect classes
лежат в `docs/archive/2026-05-llm2-report-layer-buildout/`. Они не являются
текущей точкой входа в пилот.

Проверить активные процессы:

```bash
docker compose exec -T api sh -lc 'ps -ef | grep llm2_ready_stt_layered_runner | grep -v grep || true'
```

Проверить Kimi route-plan:

```bash
docker compose exec -T api python - <<'PY'
from app.core_shared.ai_routing import AIProviderRouter
for layer in ("llm2", "llm3"):
    c = AIProviderRouter().build_route_plan(layer=layer, subject_key=layer).current_candidate()
    print(layer, c.account_alias, c.model, c.api_base, c.endpoint, c.timeout_sec)
PY
```

Проверить частично сохраненный невалидный K2.6 analysis:

```bash
docker compose exec -T api python - <<'PY'
from app.core_shared.db.session import get_db
from app.core_shared.db.models import Analysis
ver = "llm2_compact_kimi_k26_localrepair_v1_20260602"
with get_db() as db:
    rows = db.query(Analysis).filter(Analysis.instruction_version == ver).all()
    for a in rows:
        sd = a.scores_detail or {}
        print(a.id, a.interaction_id, a.score_total, len(sd.get("score_by_stage") or []), len(sd.get("criteria_results") or []))
PY
```
