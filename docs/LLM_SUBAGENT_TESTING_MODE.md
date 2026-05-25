# LLM_SUBAGENT_TESTING_MODE

## Назначение

Этот документ фиксирует временный режим тестирования, в котором реальные
`LLM-1`, `LLM-2` и `LLM-3` заменяются субагентами-симуляторами.

Цель режима:
- снизить стоимость повторных прогонов записанных звонков;
- получить управляемое и воспроизводимое тестирование отчета;
- тестировать текущий механизм узел за узлом и блок за блоком;
- не переписывать существующий pipeline, persistence, validators и renderer.

Это временный testing mode до стабилизации качества `manager_daily`.
После стабилизации отчета реальные LLM-узлы должны подключаться обратно
по тем же контрактам.

## Текущий implementation status

Статус на 2026-05-25: первый runtime slice реализован.

Реализовано:
- env-переключатели `AI_LLM_SIMULATION_ENABLED`,
  `AI_LLM_SIMULATION_RUN_ID`, `AI_LLM_SIMULATION_SEED`,
  `AI_LLM_SIMULATION_ARTIFACT_DIR`;
- общий временный executor `app.agents.calls.llm_simulation`;
- подмена `LLM-1` / `LLM-2` в `CallsAnalyzer._request_llm_content()`;
- подмена `LLM-3` в `_request_llm3_*()` composer-модулей;
- запись временных input/output artifacts в
  `/tmp/asa_llm_sim_runs/<run_id>/`;
- routing/diagnostic metadata с `execution_status=simulated`;
- focused regression tests для analyzer и composer boundaries.

Ограничение первого slice: симулятор возвращает контрактно-валидные
эвристические ответы для проверки pipeline и report layer. Он еще не является
калиброванной копией конкретной модели по качеству формулировок и типовым
ошибкам. Калибровка поведения субагентов по реальным LLM-ответам остается
следующим шагом.

## Главное требование

Субагенты должны полностью повторять роль текущих LLM-узлов:
- получать тот же input context, который сейчас получает реальная LLM;
- использовать те же инструкции и prompt assets;
- возвращать тот же JSON contract;
- создавать те же downstream artifacts;
- проходить те же validators, normalizers и quality gates;
- не обходить существующие проверки;
- не менять смысл границ ответственности между analyzer, report layer и renderer.

Ключевой принцип: заменяется только runtime-вызов модели. Весь механизм вокруг
него остается настоящим.

## Терминология

В этом документе `субагент` означает временный testing executor, который
имитирует поведение LLM-узла по текущим инструкциям и контрактам.

Это не меняет существующее проектное определение `agent` из `ARCHITECTURE.md`,
где agent является детерминированным Python-модулем workflow.

## Зоны подмены

### LLM-1

Runtime owner: `core/app/agents/calls/analyzer.py`.

Точка подмены:
- `CallsAnalyzer._request_llm_content(... layer="llm1")`.

Роль:
- первичная классификация звонка;
- краткий summary;
- follow-up context;
- data quality;
- фокус для `LLM-2`.

Output:
- тот же `llm1_first_pass` JSON, который сейчас передается в контекст `LLM-2`;
- audit metadata остается в `interaction.metadata.ai_routing.llm1`.

### LLM-2

Runtime owner: `core/app/agents/calls/analyzer.py`.

Точка подмены:
- `CallsAnalyzer._request_llm_content(... layer="llm2")`.

Роль:
- основной approved per-call analysis contract;
- classification;
- summary;
- scoring по чек-листу;
- strengths / gaps / recommendations;
- agreements;
- follow_up;
- product_signals;
- evidence_fragments;
- `report_evidence` для report blocks.

Output:
- тот же JSON contract, который сейчас валидируется в `CallsAnalyzer`;
- persisted `Analysis.scores_detail`;
- persisted `Analysis.raw_llm_response`;
- derived `Agreement` / `Insight` rows через существующий persistence path;
- audit metadata в `interaction.metadata.ai_routing.llm2`.

### LLM-3

Runtime owners:
- `core/app/agents/calls/situation_day_daily_composer.py`;
- `core/app/agents/calls/call_breakdown_composer.py`;
- `core/app/agents/calls/voice_of_customer_composer.py`;
- `core/app/agents/calls/call_tomorrow_wording_composer.py`.

Точки подмены:
- `_request_llm3_*()` внутри composer-модулей.

Роль:
- bounded manager-facing narrative composition поверх уже подготовленных данных.

Output:
- те же composer contracts для `Ситуации дня`, `Разбора звонка`,
  `Голоса клиента`, wording для `Позвони завтра` и других включенных
  narrative-блоков;
- те же diagnostics внутри report payload/result;
- те же normalized composer outputs после quality gates.

`LLM-3` и субагент вместо него не должны менять:
- report-day scope;
- список звонков;
- final statuses;
- score;
- deadlines;
- факты;
- выбранные contacts/call ids, если текущий contract это запрещает.

## Что не меняется

В рамках перехода на тестирование через субагентов не меняются:
- STT;
- OnlinePBX intake;
- существующий report runner;
- selection logic;
- readiness logic;
- scoring validators;
- report renderer;
- database schema;
- UI как основной способ запуска тестов.

## Режим запуска

Ожидаемый запуск на временном этапе: через чат и CLI/API, а не через UI.

Пример runtime-переключателей:

```text
AI_LLM_SIMULATION_ENABLED=true
AI_LLM_SIMULATION_RUN_ID=<run_id>
AI_LLM_SIMULATION_SEED=<seed>
AI_LLM_SIMULATION_ARTIFACT_DIR=/tmp/asa_llm_sim_runs
```

Базовый тестовый сценарий:
- `preset=manager_daily`;
- `mode=build_missing_and_report` или `report_from_ready_data_only`;
- один менеджер;
- одна дата или узкий период;
- без business delivery;
- при необходимости с Telegram test delivery только как отдельный explicit opt-in.

## Временные артефакты тестирования

На каждый прогон должен создаваться временный пакет:

```text
/tmp/asa_llm_sim_runs/<run_id>/
  llm1_input.json
  llm1_output.json
  llm2_input.json
  llm2_output.json
  llm3_situation_day_input.json
  llm3_situation_day_output.json
  llm3_call_breakdown_input.json
  llm3_call_breakdown_output.json
  llm3_voice_of_customer_input.json
  llm3_voice_of_customer_output.json
  llm3_call_tomorrow_input.json
  llm3_call_tomorrow_output.json
  report_result.json
  report_preview.txt
  report.pdf
```

Параллельно продолжают использоваться существующие persisted artifacts:
- `Interaction.text`;
- `Analysis.scores_detail`;
- `Analysis.raw_llm_response`;
- `interaction.metadata.ai_routing`;
- report `observability`;
- diagnostics внутри report payload.

## План реализации

1. [x] Зафиксировать `LLM simulation` как временный testing mode.
2. [x] Добавить общий simulation executor для `LLM-1` / `LLM-2`.
3. [x] Подключить его в `CallsAnalyzer._request_llm_content()` без изменения
   `analyze_call()`.
4. [x] Добавить simulation executor для `LLM-3` composer calls.
5. [x] Сохранять input/output каждого simulated LLM call во временные артефакты.
6. [ ] Прогнать один `manager_daily` case без доставки.
7. [ ] Проверить, что все контракты проходят текущие validators и quality gates
   на полном report run.
8. [ ] После этого менять report mechanisms и тестировать блок за блоком.

## Acceptance criteria

Режим считается готовым, когда:
- полный `manager_daily` прогон проходит без реальных LLM-вызовов;
- `LLM-1`, `LLM-2`, `LLM-3` outputs имеют те же контракты, что реальные LLM;
- создается persisted `Analysis`;
- report blocks проходят текущие gates;
- финальный report payload и PDF собираются;
- по каждому узлу есть input/output artifact;
- один и тот же case с тем же seed воспроизводится повторяемо;
- реальное подключение LLM обратно не требует изменения downstream-механизма.

## Out of scope

В этот режим не входит:
- новый STT-сервис;
- новая БД артефактов;
- новый UI для запуска тестов;
- broad analyzer redesign;
- изменение approved analysis contract только ради симуляции;
- обход validators ради красивого отчета;
- автоматическая business delivery.
