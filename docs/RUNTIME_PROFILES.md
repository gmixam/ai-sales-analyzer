# Runtime Profiles

Дата обновления: 2026-06-02

## Назначение

Этот документ является верхнеуровневой картой режимов запуска AI Sales Analyzer.
Его нужно передавать новому агенту, если задача связана с тестированием,
контрольным прогоном, экономным ежедневным запуском или боевым контуром.

Source of truth по режимам:

- `docs/RUNTIME_PROFILES.md` — какие runtime-профили существуют и когда их
  использовать;
- `docs/AI_PROVIDER_ROUTING.md` — как устроены provider pools, routing и env;
- `docs/LLM_SUBAGENT_TESTING_MODE.md` — подробные правила subagent-runtime;
- `docs/ACTIVE_WORK_STATE.md` — какой профиль сейчас активен и что делать
  следующим.

Перед запуском pipeline агент должен явно назвать профиль и проверить env в
контейнере. Нельзя запускать тест или боевой контур "по памяти".

## Что значит "имитировать LLM"

В этом проекте фраза "LLM2/LLM3 имитируют субагенты" означает:

- runtime-вызов модели на выбранном LLM-слое заменяется вызовом внешнего
  subagent runner;
- subagent получает тот же prompt/context/input artifact, который получил бы
  соответствующий LLM-узел;
- subagent обязан вернуть тот же JSON contract;
- дальше результат проходит обычные validators, normalizers, persistence,
  report selection, readiness и renderer;
- downstream-код не должен знать, что вместо API-модели работал subagent.

Важно: это не означает, что мы подменяем весь механизм заглушкой. Механизм
pipeline остается настоящим. Заменяется только runtime executor LLM-узла.

### Реальные Codex-agents vs contract runner

Есть два разных способа включить subagent-runtime:

1. Реальные Codex-subagents.

   Это режим, где внешний runner запускает настоящий Codex agent process. Такой
   агент выполняет роль LLM-узла: читает input artifact, следует prompt/contract
   и возвращает JSON. В этом режиме "имитировать LLM" значит, что роль LLM
   исполняет реальный агент, а не OpenAI-compatible model call.

   Ожидаемый env:

   ```text
   AI_LLM_SUBAGENT_COMMAND=<codex command>
   ```

2. Contract runner.

   Это контейнерный deterministic runner:

   ```text
   AI_LLM_SUBAGENT_RUNNER_CMD=python /app/report_scripts/llm_subagent_contract_runner.py
   ```

   Он полезен для smoke-проверки wiring, artifacts и fail-closed поведения, но
   это не настоящий Codex-agent. Его нельзя использовать как доказательство
   смыслового качества LLM2/LLM3.

Не смешивать эти режимы в отчетах о качестве. Если был использован contract
runner, так и писать: "проверен wiring", а не "проверено качество агента".

## Профиль 1: cost optimized

Назначение: ежедневный пилот / будущий production baseline с контролем стоимости.

```text
STT  -> whisper-1
LLM1 -> gpt-5.4-nano
LLM2 -> gpt-5.4-mini
LLM3 -> gpt-5.4-mini
```

Env:

```text
AI_LLM_EXECUTION_MODE=openai_compatible
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SUBAGENT_RUNTIME_LAYERS=
AI_LLM_SIMULATION_ENABLED=false
LLM3_ENABLED=true
```

Когда использовать:

- обычный daily pilot;
- контроль стоимости важнее максимального качества;
- нужно сравнить качество экономного режима с предыдущими max quality
  прогонами.

Что проверить перед запуском:

```text
llm1 -> gpt-5.4-nano
llm2 -> gpt-5.4-mini
llm3 -> gpt-5.4-mini
subagent_runtime=false for llm1,llm2,llm3
```

## Профиль 2: max quality

Назначение: ручное сравнение качества, разбор спорных дней, эталонный прогон.

```text
STT  -> whisper-1
LLM1 -> gpt-5.4-mini
LLM2 -> gpt-5.5
LLM3 -> gpt-5.4
```

Env:

```text
AI_LLM_EXECUTION_MODE=openai_compatible
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SUBAGENT_RUNTIME_LAYERS=
AI_LLM_SIMULATION_ENABLED=false
LLM3_ENABLED=true
```

Когда использовать:

- точечный quality benchmark;
- сравнение с cost optimized;
- разбор спорных результатов отчета;
- не использовать как ежедневный режим без отдельного решения из-за стоимости.

## Профиль 3: hybrid API + Codex-subagents

Назначение: реальный входной контур STT/LLM1, но LLM2 и LLM3 выполняются
Codex-subagents.

```text
STT  -> API provider route
LLM1 -> OpenAI-compatible API provider route
LLM2 -> Codex subagent runtime
LLM3 -> Codex subagent runtime
```

Env:

```text
AI_LLM_EXECUTION_MODE=openai_compatible
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SUBAGENT_RUNTIME_LAYERS=llm2,llm3
AI_LLM_SIMULATION_ENABLED=false
LLM3_ENABLED=true
AI_LLM_SUBAGENT_COMMAND=<codex command>
AI_LLM_SUBAGENT_RUN_ID=<run-id>
AI_LLM_SUBAGENT_ARTIFACT_DIR=/tmp/asa_llm_subagent_runs
AI_LLM_SUBAGENT_TIMEOUT_SEC=300
```

Когда использовать:

- нужно проверить механизм на реальных STT и реальном LLM1 admission;
- LLM2/LLM3 должны исполняться агентами Codex вместо API-моделей;
- нужно видеть input/output artifacts работы каждого LLM2/LLM3 node;
- пользователь явно просит "агенты Codex имитируют узлы LLM2/LLM3".

Что проверить перед запуском:

```text
llm1_subagent=False
llm2_subagent=True
llm3_subagent=True
AI_LLM_SUBAGENT_COMMAND is set to a real Codex command
AI_LLM_SUBAGENT_RUN_ID is unique for the run
```

Не использовать `AI_LLM_SUBAGENT_RUNNER_CMD=python /app/report_scripts/llm_subagent_contract_runner.py`
для смысловой проверки качества. Это только smoke/wiring runner.

## Профиль 4: Kimi / Moonshot trial

Назначение: попробовать Kimi как дополнительный OpenAI-compatible источник для
`LLM1`, `LLM2` и/или `LLM3` без удаления текущих OpenAI entries.

Текущий статус на 2026-06-02: `LLM2=kimi-k2.6` не принят для текущего layered
`LLM2A/B/C/D` контракта. Подробный handoff:

```text
docs/KIMI_K26_TRIAL_HANDOFF_2026-06-02.md
```

Не запускать полный день через `LLM2=kimi-k2.6` без отдельного упрощения
`LLM2` contract и one-call smoke. Kimi K2.6 можно оставлять как trial source или
использовать для `LLM3` только после отдельной проверки report composer.

Текущий рекомендуемый Kimi/Moonshot trial на 2026-06-03:

```text
LLM1 -> alias kimi_llm1_main -> model moonshot-v1-8k
LLM2 -> alias kimi_llm2_main -> model moonshot-v1-128k
LLM3 -> alias kimi_llm3_main -> model moonshot-v1-128k
```

Важно: в `AI_LLM*_PROVIDERS_JSON` поле `provider` остается `openai`, потому что
текущий runtime adapter является OpenAI-compatible executor. Отличие Kimi entry
задается через:

```text
api_base=https://api.moonshot.ai/v1
api_key_env=MOONSHOT_API_KEY
model=moonshot-v1-8k, moonshot-v1-128k, or kimi-k2.6
```

Env для ключа:

```text
MOONSHOT_API_KEY=<kimi/moonshot api key>
```

Чтобы включить Kimi только для одного узла:

```text
AI_LLM1_FIXED_ACCOUNT_ALIAS=kimi_llm1_main
# или
AI_LLM2_FIXED_ACCOUNT_ALIAS=kimi_llm2_main
# или
AI_LLM3_FIXED_ACCOUNT_ALIAS=kimi_llm3_main
```

Чтобы включить Kimi для всех LLM-узлов:

```text
AI_LLM1_FIXED_ACCOUNT_ALIAS=kimi_llm1_main
AI_LLM2_FIXED_ACCOUNT_ALIAS=kimi_llm2_main
AI_LLM3_FIXED_ACCOUNT_ALIAS=kimi_llm3_main
AI_LLM_EXECUTION_MODE=openai_compatible
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SUBAGENT_RUNTIME_LAYERS=
AI_LLM_SIMULATION_ENABLED=false
LLM3_ENABLED=true
```

Перед запуском проверить внутри контейнера:

```text
llm1_route=kimi_llm1_main:moonshot-v1-8k
llm2_route=kimi_llm2_main:moonshot-v1-128k
llm3_route=kimi_llm3_main:moonshot-v1-128k
```

Не запускать Kimi trial без заполненного `MOONSHOT_API_KEY`.

## Профиль 5: full Codex-subagent runtime

Назначение: все LLM-слои выполняются subagent runtime. STT остается обычным STT
контуром, потому что это не LLM-узел.

```text
STT  -> API provider route
LLM1 -> Codex subagent runtime
LLM2 -> Codex subagent runtime
LLM3 -> Codex subagent runtime
```

Env:

```text
AI_LLM_EXECUTION_MODE=subagent_runtime
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SUBAGENT_RUNTIME_LAYERS=
AI_LLM_SIMULATION_ENABLED=false
LLM3_ENABLED=true
AI_LLM_SUBAGENT_COMMAND=<codex command>
AI_LLM_SUBAGENT_RUN_ID=<run-id>
AI_LLM_SUBAGENT_ARTIFACT_DIR=/tmp/asa_llm_subagent_runs
AI_LLM_SUBAGENT_TIMEOUT_SEC=300
```

Когда использовать:

- нужно воспроизвести прежний полный Codex-subagent LLM run;
- пользователь хочет, чтобы Codex-agents исполняли все LLM-узлы;
- нужен полный agent-runtime audit trail.

Риск:

- LLM1 тоже будет исполняться агентом, то есть это уже не проверка реального
  API admission layer.

## Профиль 6: local simulation

Назначение: дешевый smoke/debug без реальных моделей и без реальных Codex-agents.

```text
AI_LLM_SIMULATION_ENABLED=true
AI_LLM_SIMULATION_RUN_ID=<run-id>
AI_LLM_SIMULATION_SEED=<seed>
AI_LLM_SIMULATION_ARTIFACT_DIR=/tmp/asa_llm_sim_runs
```

Когда использовать:

- проверить wiring, contracts, report rendering;
- воспроизвести deterministic path;
- не использовать как качество LLM2/LLM3.

Это не режим "реальные агенты". Это локальная симуляция.

## Мини-чеклист перед запуском

1. Назвать профиль: `cost_optimized`, `max_quality`,
   `hybrid_api_codex_subagents`, `full_codex_subagents` или `local_simulation`.
2. Проверить env внутри контейнера, а не только в `.env`.
3. Проверить route/subagent flags:

   ```text
   STT selected provider/model
   LLM1 selected model or subagent flag
   LLM2 selected model or subagent flag
   LLM3 selected model or subagent flag
   ```

4. Для subagent-профилей проверить:

   ```text
   AI_LLM_SUBAGENT_COMMAND or AI_LLM_SUBAGENT_RUNNER_CMD
   AI_LLM_SUBAGENT_RUN_ID
   AI_LLM_SUBAGENT_ARTIFACT_DIR
   ```

5. Перед business delivery отдельно подтвердить:

   ```text
   send_business_email=false unless user explicitly approved
   telegram_test_only for operator preview
   ```

## Формулировки для постановки задачи новому агенту

### Тест экономного режима

```text
Открой docs/RUNTIME_PROFILES.md и docs/ACTIVE_WORK_STATE.md.
Используй профиль cost_optimized. Проверь env в api/worker/beat контейнерах.
Запусти controlled run только после подтверждения пользователя. После запуска
собери routing metadata, стоимость/usage, report readiness и PDF/Telegram
operator delivery result.
```

### Тест hybrid Codex-subagents

```text
Открой docs/RUNTIME_PROFILES.md и docs/LLM_SUBAGENT_TESTING_MODE.md.
Используй профиль hybrid API + Codex-subagents: STT и LLM1 через API, LLM2 и
LLM3 через реальные Codex-subagents. Не используй contract runner как
доказательство качества. Проверь, что llm1_subagent=False, llm2_subagent=True,
llm3_subagent=True. После запуска собери input/output artifacts LLM2/LLM3,
routing metadata, readiness и PDF/Telegram operator delivery result.
```

### Запуск боевого контура

```text
Открой docs/RUNTIME_PROFILES.md, docs/MANUAL_REPORTING_PILOT.md и
docs/ACTIVE_WORK_STATE.md. Используй профиль cost_optimized, если пользователь
не утвердил другой. Перед business delivery проверь readiness, manager-facing
completeness gate, получателей, и только после явного подтверждения включай
business email.
```
