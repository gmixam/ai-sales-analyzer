# TMP: отчет по внедрению LLM2 input rework

Дата: 2026-06-02
Статус: внедрено, pipeline/test run на 6 звонков не запускался

## Что внедрено

### Common LLM2 instruction

- Создан compact runtime prompt:
  `core/app/agents/calls/prompts/llm2_common_runtime.md`.
- Runtime LLM2 теперь собирает system message из:
  - `llm2_common_runtime.md`;
  - node-specific prompt текущего узла.
- Полный `llm2_pass_contracts.md` больше не отправляется в каждый runtime
  вызов LLM2. Он остается архитектурным / handoff-контрактом.

### LLM2A

- Compact payload LLM2A больше не отправляет дублирующую пару:
  `transcript + segments`.
- Вместо этого отправляется один `dialogue`.
- `dialogue` сохраняет весь текст звонка, но убирает:
  - full transcript duplicate;
  - raw segments duplicate;
  - `start_ms/end_ms`;
  - мелкую STT-нарезку как отдельный JSON object на каждую секунду.
- Соседние STT segments с одинаковой надежной speaker-role склеиваются в более
  крупные turns без удаления текста.
- Ненадежные speaker labels вроде `A/B` не выдаются модели как manager/client;
  они нормализуются в `unknown`.

### LLM2B

- `compact_scoring_rubric` больше не содержит per-criterion `score_rules`.
- В payload остаются:
  - `criterion_code`;
  - `criterion_name`;
  - `stage_code`;
  - `stage_name`;
  - `applicability_rule`;
  - `max_score`;
  - LLM2A scenes/evidence/business outcome.
- Общий scoring guidance перенесен в
  `core/app/agents/calls/prompts/analyze_scoring_gaps.md`.
- Не добавлялись:
  - pre-filter applicable stages;
  - новые LLM2 stop conditions;
  - дробление LLM2B на несколько subcalls;
  - Kimi-specific prompt/payload.

## Методика расчета input size

Для сравнения использован тот же диагностический пакет:

- `review_packages/llm2_input_samples_tolegen_20260601`

`Было`:

- сохраненные старые `full_inputs/*_full_input_messages.json`;
- метрика: `len(system message content) + len(user message content)`.

`Стало`:

- текущий `llm2_common_runtime.md`;
- текущие node-specific prompts;
- текущая compact payload shape для LLM2A/LLM2B;
- для LLM2C/LLM2D payload не менялся в этой задаче, уменьшение идет за счет
  нового common runtime prompt.

Это расчет размера input до вызова модели. Реальные provider tokens будут
измеряться на следующем controlled run.

## Input size по узлам

| Узел | Было system | Было payload | Было total | Стало system | Стало payload | Стало total | Разница total | Снижение total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LLM2A | 19 651 | 15 773 | 35 424 | 7 660 | 4 563 | 12 223 | -23 201 | 65.5% |
| LLM2B | 20 115 | 17 987 | 38 102 | 9 013 | 12 374 | 21 387 | -16 715 | 43.9% |
| LLM2C | 18 904 | 3 847 | 22 751 | 6 540 | 3 847 | 10 387 | -12 364 | 54.3% |
| LLM2D | 19 044 | 6 033 | 25 077 | 6 680 | 6 033 | 12 713 | -12 364 | 49.3% |

## Payload-specific эффект

| Узел | Payload было | Payload стало | Разница | Снижение |
| --- | ---: | ---: | ---: | ---: |
| LLM2A | 15 773 | 4 563 | -11 210 | 71.1% |
| LLM2B | 17 987 | 12 374 | -5 613 | 31.2% |
| LLM2C | 3 847 | 3 847 | 0 | 0.0% |
| LLM2D | 6 033 | 6 033 | 0 | 0.0% |

## Проверки

- `docker compose exec -T api python -m py_compile /app/app/agents/calls/analyzer.py`
  - passed.
- `docker compose exec -T api python -m pytest -q /app/tests/test_ai_provider_routing.py -k 'llm2_compact_profile or llm2_layered_runtime_uses_compact_common_prompt or llm2_layered_pass'`
  - `5 passed, 39 deselected`.
- `docker compose exec -T api python -m pytest -q /app/tests/test_llm2_layered_analysis.py`
  - `10 passed, 2 subtests passed`.
- `git diff --check`
  - passed.

## Следующий шаг после проверки пользователем

Не запускать full-day pipeline автоматически.

После ручной проверки изменений следующий шаг:

- controlled test на 6 звонках;
- цепочка: ready STT -> LLM2 -> LLM3/report;
- сформировать отчет и отправить пользователю в Telegram.
