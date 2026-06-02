# AI_PROVIDER_ROUTING

## Назначение
Этот документ фиксирует верхнеуровневую схему AI provider orchestration для MVP-1.

Цель:
- failover между account/provider entries;
- cost control;
- weighted A/B tests;
- vendor/account isolation;
- audit-friendly routing metadata без изменения analyzer contract.

Это не:
- automation readiness;
- scheduler/retries/beat на уровне pipeline;
- broad refactor runtime pipeline.

Каноническая карта режимов запуска находится в
`docs/RUNTIME_PROFILES.md`. Этот документ описывает техническую routing-модель и
env-поля, но не должен быть единственным handoff-файлом для запуска тестов или
боевого контура.

## Где в системе реально запускается AI

### STT
- runtime owner: `core/app/agents/calls/extractor.py`
- current execution point: `CallsExtractor.transcribe()`
- routing layer: `core/app/core_shared/ai_routing.py`

### LLM-1
- runtime owner: `core/app/agents/calls/analyzer.py`
- current execution point: `CallsAnalyzer._request_llm1_first_pass()`
- current role: separate first-pass classification / summary / follow-up context before final approved-contract generation

### LLM-2
- runtime owner: `core/app/agents/calls/analyzer.py`
- current execution point: `_request_analysis_content()`
- current role: actual approved deep-analysis generation path that returns the final approved analyzer contract

### LLM-3
- runtime owner: report block composer modules under `core/app/agents/calls/*_composer.py`
- current execution points: bounded report-composer calls for Situation Day, Call Breakdown, Voice of Customer, Tomorrow wording, and Additional Situations where enabled
- current role: manager-facing narrative composition from already selected/grounded material
- current model in the active runtime is configured through the LLM3 provider pool; recent SFB work used `gpt-4o`
- LLM3 is not final authority for report scope, call inclusion, status, deadlines, or facts

## Configuration model

Каждый слой поддерживает свой provider pool:
- `STT`
- `LLM-1`
- `LLM-2`
- `LLM-3`

Для каждого pool поддерживаются:
- `routing_policy`
- `fixed_account_alias`
- `force_account_alias`
- `entries[]`

Каждый entry поддерживает поля:
- `provider`
- `account_alias` или `account_id`
- `model`
- `api_base`
- `endpoint`
- `api_key_env`
- `enabled`
- `priority`
- `weight`
- `timeout_sec`
- `max_retries_for_this_provider`
- `tags`
- `notes`

## Env schema

### STT
- `AI_STT_ROUTING_POLICY`
- `AI_STT_PROVIDERS_JSON`
- `AI_STT_FIXED_ACCOUNT_ALIAS`
- `AI_STT_FORCE_ACCOUNT_ALIAS`

### LLM-1
- `AI_LLM1_ROUTING_POLICY`
- `AI_LLM1_PROVIDERS_JSON`
- `AI_LLM1_FIXED_ACCOUNT_ALIAS`
- `AI_LLM1_FORCE_ACCOUNT_ALIAS`

### LLM-2
- `AI_LLM2_ROUTING_POLICY`
- `AI_LLM2_PROVIDERS_JSON`
- `AI_LLM2_FIXED_ACCOUNT_ALIAS`
- `AI_LLM2_FORCE_ACCOUNT_ALIAS`

### LLM-3
- `AI_LLM3_ROUTING_POLICY`
- `AI_LLM3_PROVIDERS_JSON`
- `AI_LLM3_FIXED_ACCOUNT_ALIAS`
- `AI_LLM3_FORCE_ACCOUNT_ALIAS`

## Active model profiles

As of 2026-06-01, the current pilot runtime uses real OpenAI-compatible LLMs,
not Codex subagents:

```text
AI_LLM_EXECUTION_MODE=openai_compatible
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SIMULATION_ENABLED=false
LLM3_ENABLED=true
```

Default daily pilot profile: `cost_optimized`.

```text
STT  -> whisper-1
LLM1 -> gpt-5.4-nano
LLM2 -> gpt-5.4-mini
LLM3 -> gpt-5.4-mini
```

Manual comparison profile: `max_quality`.

```text
STT  -> whisper-1
LLM1 -> gpt-5.4-mini
LLM2 -> gpt-5.5
LLM3 -> gpt-5.4
```

`max_quality` is not the default because per-call LLM2 analysis becomes too
expensive for daily operation. Use it only for selected control runs or disputed
quality checks.

Hybrid validation profile: `stt_llm1_api_llm2_llm3_subagents`.

```text
STT  -> API provider route
LLM1 -> OpenAI-compatible API provider route
LLM2 -> Codex subagent runtime
LLM3 -> Codex subagent runtime
```

Use this profile when STT and LLM1 should stay real provider/API calls, while
the semantic-analysis and report-composition layers are imitated by Codex
subagents:

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
  runs the container-visible contract runner and is useful for deterministic
  smoke checks of the hybrid wiring.
- `AI_LLM_SUBAGENT_COMMAND=<codex command>` uses the generic Codex subagent CLI
  path when Codex is available inside the runtime environment.

`AI_LLM_SUBAGENT_RUNTIME_LAYERS` is additive and layer-scoped. When it is empty,
the legacy behavior is preserved: `AI_LLM_EXECUTION_MODE=subagent_runtime` or
`AI_LLM_SUBAGENT_RUNTIME_ENABLED=true` sends all analyzer/composer LLM layers
through subagents. When it contains a comma-separated layer list, only those
layers are intercepted.

Kimi / Moonshot trial entries are available as additional OpenAI-compatible
provider-pool sources:

```text
LLM1 alias: kimi_llm1_main
LLM2 alias: kimi_llm2_main
LLM3 alias: kimi_llm3_main
LLM1 model: moonshot-v1-8k
LLM2/LLM3 model: kimi-k2.6
api_base: https://api.moonshot.ai/v1
api_key_env: MOONSHOT_API_KEY
```

They are configured with `provider="openai"` because the current LLM executors
use the OpenAI SDK / Chat Completions-compatible adapter. To test Kimi, switch
the relevant `AI_LLM*_FIXED_ACCOUNT_ALIAS` to the Kimi alias and recreate the
runtime containers. Keep the default OpenAI aliases for normal `cost_optimized`
runs.

## Supported routing policies

### `fixed`
- всегда выбирается один configured entry
- по `fixed_account_alias`, либо первый enabled entry по `priority`

### `failover`
- сначала primary entry
- затем fallback entries по `priority`
- fallback происходит только внутри локального AI вызова, не на уровне pipeline scheduler/retry

### `weighted_ab`
- выбирается один enabled entry по `weight`
- выбор детерминирован по `layer + subject_key + pool signature`
- при одинаковом `subject_key` выбор повторяемый

### `manual_force`
- явный override account selection
- может быть включён через `AI_*_FORCE_ACCOUNT_ALIAS`
- legacy manual STT override (`assemblyai` / `whisper`) тоже маппится в этот режим без ломки current manual flow

## Backward compatibility

Если JSON pool не задан, routing layer автоматически строит legacy single-provider pool из текущих settings:

- `STT`:
  - `assemblyai` path из `STT_PROVIDER`
  - либо `openai whisper` path из `OPENAI_MODEL_STT`
- `LLM-1`:
  - legacy entry from `OPENAI_MODEL_CLASSIFY`
- `LLM-2`:
  - legacy entry from `OPENAI_MODEL_ANALYZE`
- `LLM-3`:
  - legacy entry from the report-composer LLM3 settings / OpenAI-compatible pool
  - used only when composer feature flags enable LLM3 for the block

Если у слоя есть только один enabled entry, поведение остаётся effectively single-provider.

## Runtime metadata

Layer routing metadata persists in `interaction.metadata.ai_routing`.

Для каждого слоя пишутся:
- `layer`
- `policy`
- `requested_policy`
- `forced_override`
- `force_reason`
- `configured_pool_size`
- `selected_provider`
- `selected_account_alias`
- `selected_api_key_env`
- `selected_model`
- `selected_api_base`
- `selected_endpoint`
- `executed_endpoint_path`
- `selected_timeout_sec`
- `selected_max_retries_for_this_provider`
- `selected_execution_mode`
- `selected_supports_api_base`
- `selected_supports_endpoint`
- `selected_supports_model`
- `selected_requires_openai_compatible_api`
- `fallback_used`
- `provider_failure`
- `executed`
- `execution_status`
- `skip_reason`
- `request_kind`
- `provider_request_id`
- `notes`
- `usage`
- `attempted_count`
- `attempted[]`

`attempted[]` хранит audit trail попыток по provider/account/model/capability с `status=success|failed`.
`execution_status` различает как минимум:
- `executed`
- `attempted_failed`
- `skipped`
- `planned`

## Confirmed implementation state

- Shared router implementation lives in `core/app/core_shared/ai_routing.py`.
- `STT` routing is both selected and executed in `CallsExtractor.transcribe()`.
- `LLM-1` routing is both selected and executed in `CallsAnalyzer._request_llm1_first_pass()`.
- `LLM-2` routing is both selected and executed in `CallsAnalyzer._request_analysis_content()`.
- Routing metadata is persisted into `interaction.metadata.ai_routing` and surfaced back through the manual orchestration result.

## Confirmed adapter scope and bounded gaps

- `STT` execution currently supports two concrete provider adapters only:
  - `assemblyai`
  - `openai` with Whisper-style transcription path
- `LLM-1` execution currently uses the OpenAI Python client with routed `model`, `api_base`, `timeout_sec`, and per-provider retry settings.
- `LLM-2` execution currently uses the OpenAI Python client with routed `model`, `api_base`, `timeout_sec`, and per-provider retry settings.
- This means multi-provider config is already real, but non-OpenAI `LLM` vendors are currently practical only when they expose an OpenAI-compatible chat API, or after a future bounded adapter addition.
- `endpoint` is part of the configuration and audit schema, but current `STT` / `LLM` executors do not yet consume it directly in runtime request construction.
- for OpenAI `STT`, `selected_endpoint` reflects configured intent, while `executed_endpoint_path` reflects the actual SDK execution route (`/audio/transcriptions`) used by `client.audio.transcriptions.create(...)`.

## Execution compatibility note

Current code separates concerns like this:
- router decides which configured candidate should be selected;
- executor decides whether that candidate can actually be executed.

Confirmed current behavior:
- router validates pool structure and routing policy, but does not yet validate execution capability;
- `STT` executor enforces compatibility implicitly via provider branches in `CallsExtractor._transcribe_with_candidate()`;
- `LLM-2` executor effectively assumes an OpenAI-compatible request path because it always builds an `OpenAI(...)` client in `CallsAnalyzer._request_analysis_content()`.

This means a config entry may be routing-valid but still execution-unsupported.

## Recommended adapter capability contract

For the next bounded step, execution support should be expressed explicitly per layer and per candidate:

- `layer`
- `provider`
- `execution_mode`
- `supports_api_base`
- `supports_endpoint`
- `supports_model`
- `requires_openai_compatible_api`

Minimal execution modes for MVP-1:
- `openai_compatible`
- `vendor_specific`

Confirmed interpretation for current runtime:
- `STT / assemblyai` -> `vendor_specific`
- `STT / openai` -> `openai_compatible`
- `LLM-1 / openai` -> `openai_compatible`
- `LLM-2 / openai` -> `openai_compatible`

Future non-OpenAI-compatible vendors should not be treated as executable only because they were present in `AI_*_PROVIDERS_JSON`.

## Implemented compatibility guardrail

Current runtime now uses a combined guardrail, with the hard stop at executor-preflight.

Implemented split:
- config parse stage remains structural only;
- router selection now annotates candidates with execution capability metadata;
- executor request-build stage performs the final compatibility stop before building the provider client/request.

Current capability metadata includes:
- `execution_mode`
- `supports_api_base`
- `supports_endpoint`
- `supports_model`
- `requires_openai_compatible_api`

Current hard-stop behavior:
- `STT` fails fast with `Unsupported STT adapter path: ...` when a routed candidate is not compatible with the current provider-specific or OpenAI-compatible executor path.
- `LLM-1` fails fast before `OpenAI(...)` client construction when a routed candidate is not supported by the current OpenAI-compatible executor path.
- `LLM-2` fails fast before `OpenAI(...)` client construction when a routed candidate is not supported by the current OpenAI-compatible executor path.
- compatibility failure reason is persisted through existing `attempted[]` and `provider_failure` audit fields.

## Implemented bounded execution capability map

Current shared capability map covers:
- `STT / assemblyai` -> `vendor_specific`
- `STT / openai` -> `openai_compatible`
- `LLM-1 / openai` -> `openai_compatible`
- `LLM-2 / openai` -> `openai_compatible`

Entries outside this bounded map may still be config-valid, but are not treated as execution-ready by current runtime.

## Representative validation status

Confirmed on 2026-03-19 with runtime-safe scenarios:
- supported `STT / openai` candidate passes preflight and exposes `openai_compatible` capability metadata;
- unsupported `STT` provider fails fast with explicit `Unsupported STT adapter path: ...`;
- supported `LLM-1 / openai` candidate passes preflight and exposes `openai_compatible` capability metadata;
- supported `LLM-2 / openai` candidate passes preflight and exposes `openai_compatible` capability metadata;
- non-OpenAI-compatible `LLM-2` provider fails fast before client build, and the failure reason is persisted in `attempted[]` plus `provider_failure=true`;
- legacy single-provider mode and legacy manual `STT` override remain backward-compatible.

## De-legacy env status

Confirmed on fresh-container runtime on 2026-03-19:
- when `AI_LLM1_PROVIDERS_JSON` and `AI_LLM2_PROVIDERS_JSON` are explicitly configured, routed `selected_model` comes from the new routing config even if legacy `OPENAI_MODEL_CLASSIFY` / `OPENAI_MODEL_ANALYZE` are unset or intentionally conflicting;
- `OPENAI_MODEL_CLASSIFY` and `OPENAI_MODEL_ANALYZE` therefore remain only as legacy fallback inputs for the old single-provider path;
- `OPENAI_API_KEY` is still a bootstrap dependency of `Settings` when it is truly absent from runtime env, even if routed candidates use only per-layer `api_key_env` secrets;
- existing `AI_*_FIXED_ACCOUNT_ALIAS` env values still affect fresh runtime selection and must either match the active pool or be cleaned up alongside provider-pool changes.

## Risks and non-goals

- This step should not introduce provider auto-discovery or a plugin framework.
- This step should not validate remote model availability or vendor credentials at settings-load time.
- This step should not expand local failover into pipeline-level retries or scheduler semantics.
- This step should not redesign `CallsAnalyzer` / `CallsExtractor` around a new universal adapter hierarchy.

## Current MVP-1 limitation

- STT routing is fully wired into execution.
- LLM-1 routing is wired into actual analyzer first-pass execution.
- LLM-2 routing is wired into actual analyzer request execution.
- Current analyzer runtime stays contract-safe: `LLM-1` returns bounded intermediate context (`classification`, `summary`, `follow_up`, `data_quality`, optional `analysis_focus`), while `LLM-2` still returns the final approved analyzer contract.
- For analyzer forensics, the persisted raw-vs-normalized boundary is now explicit:
  - `LLM-2` raw response text is stored in `analyses.raw_llm_response`
  - normalized approved-contract result is stored separately in `analyses.scores_detail`
  - if the output is semantically invalid (`semantically_empty_analysis`), the attempt may still be persisted for audit, but only as `is_failed=true` and must not be treated as a reusable successful analysis

Это сознательное ограничение текущего шага:
- manual MVP-1 flow не ломается;
- approved analyzer contract не меняется;
- business logic не переписывается преждевременно.
