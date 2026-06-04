# Временная карта LLM-узлов

Дата фиксации: 2026-05-26

Цель документа: быстро увидеть, какой LLM-узел за что отвечает в текущем механизме, какая функция его запускает, какая инструкция используется и какой артефакт должен быть создан.

Важно: STT не является LLM-узлом. STT только превращает аудио в транскрипт. Дальше LLM-узлы работают уже с текстом звонка, метаданными и промежуточными артефактами.

## Короткая карта

| LLM-узел | Механизм / функция | Инструкция | Артефакт |
|---|---|---|---|
| LLM-1. Классификатор и карточка звонка перед LLM-2 | `CallsAnalyzer._request_llm1_first_pass()` -> `CallsAnalyzer._request_llm_content(layer="llm1", request_kind="classification_first_pass")` | `classify.md` | Целевой `llm1_first_pass` JSON: решение `идет / не идет в LLM-2`, причина допуска/отсева, базовая классификация, краткая карточка звонка, технические признаки маршрутизации, audit/reason codes. |
| LLM-2. Основной анализ звонка | `CallsAnalyzer._request_analysis_content()` -> `CallsAnalyzer._request_llm_content(layer="llm2", request_kind="approved_contract_generation")` | `analyze.md` + checklist/contract MVP1 + `agreements.md` + `insights.md` | Основной контракт анализа: оценки, сильные/слабые стороны, рекомендации, темы, договоренности, инсайты, evidence для отчета. Сохраняется в `Analysis`, `Agreement`, `Insight`. |
| LLM-3. Ситуация дня | `compose_daily_situation_day()` -> `_try_llm3_daily_situation()` -> `_request_llm3_daily_situation()` | `situation_day_daily_composer_v2.md` | JSON-блок для раздела отчета `СИТУАЦИЯ ДНЯ`. |
| LLM-3. Разбор звонка | `compose_call_breakdown()` / `compose_call_breakdown_from_situation()` -> `_try_llm3_call_breakdown()` -> `_request_llm3_call_breakdown()` | `call_breakdown_composer_v2.md` | JSON-блок для раздела отчета `РАЗБОР ЗВОНКА`: моменты звонка, что произошло, доказательство, лучший следующий шаг. |
| LLM-3. Голос клиента | `compose_voice_of_customer()` -> `_try_llm3_voice_of_customer()` -> `_request_llm3_voice_of_customer()` | `voice_of_customer_composer_v2.md` | JSON-блок для раздела отчета `ГОЛОС КЛИЕНТА`: клиентские сигналы, сцены, цитаты/смысл, выводы для менеджера. |
| LLM-3. Позвони завтра | `compose_call_tomorrow_wording()` -> `_try_llm3_call_tomorrow_wording()` -> `_request_llm3_call_tomorrow_wording()` | `call_tomorrow_wording_composer_v1.md` | JSON-блок с улучшенными формулировками для раздела `ПОЗВОНИ ЗАВТРА`: причина, следующий шаг, скрипт открытия звонка. |

## Целевая роль LLM-1

Зафиксированное решение: `LLM-1` должен стать дешевым классификатором и карточкой звонка перед `LLM-2`.

`LLM-1` должен отвечать на три вопроса:

1. Что это за звонок.
2. Какая краткая карточка звонка нужна downstream-механизму.
3. Нужно ли отправлять конкретный звонок в дорогой полноценный анализ `LLM-2`.

`LLM-1` не должен:

- глубоко оценивать качество работы менеджера;
- писать развернутые рекомендации;
- готовить `report_evidence`;
- выбирать или формировать блоки отчета;
- дублировать работу `LLM-2`.

Минимальный целевой артефакт `LLM-1`:

```text
analysis_eligibility
eligibility_reason
basic_call_classification
short_call_card
routing_flags
audit_reason_codes
```

Будущая архитектурная граница: `LLM-1` может быть вынесен в STT/post-STT enrichment service, где после транскрипции формируется карточка звонка и eligibility. Сам STT при этом остается только преобразованием аудио в текст.

Архитектурное решение зафиксировано здесь:

```text
/root/ai-sales-analyzer/docs/DECISIONS.md
ADR-082: LLM-1 становится классификатором и карточкой звонка перед LLM-2
```

## Полные пути к механизмам

### LLM-1 и LLM-2

Основной файл:

```text
/root/ai-sales-analyzer/core/app/agents/calls/analyzer.py
```

Ключевые функции:

```text
/root/ai-sales-analyzer/core/app/agents/calls/analyzer.py:524
CallsAnalyzer

/root/ai-sales-analyzer/core/app/agents/calls/analyzer.py:596
CallsAnalyzer.get_prompt_assets()

/root/ai-sales-analyzer/core/app/agents/calls/analyzer.py:1095
CallsAnalyzer._request_llm1_first_pass()

/root/ai-sales-analyzer/core/app/agents/calls/analyzer.py:1178
CallsAnalyzer._request_analysis_content()

/root/ai-sales-analyzer/core/app/agents/calls/analyzer.py:1196
CallsAnalyzer._request_llm_content()
```

### LLM-3: Ситуация дня

```text
/root/ai-sales-analyzer/core/app/agents/calls/situation_day_daily_composer.py
```

Ключевые функции:

```text
/root/ai-sales-analyzer/core/app/agents/calls/situation_day_daily_composer.py:91
compose_daily_situation_day()

/root/ai-sales-analyzer/core/app/agents/calls/situation_day_daily_composer.py:543
_try_llm3_daily_situation()

/root/ai-sales-analyzer/core/app/agents/calls/situation_day_daily_composer.py:567
_request_llm3_daily_situation()
```

### LLM-3: Разбор звонка

```text
/root/ai-sales-analyzer/core/app/agents/calls/call_breakdown_composer.py
```

Ключевые функции:

```text
/root/ai-sales-analyzer/core/app/agents/calls/call_breakdown_composer.py:106
compose_call_breakdown_from_situation()

/root/ai-sales-analyzer/core/app/agents/calls/call_breakdown_composer.py:283
compose_call_breakdown()

/root/ai-sales-analyzer/core/app/agents/calls/call_breakdown_composer.py:491
_try_llm3_call_breakdown()

/root/ai-sales-analyzer/core/app/agents/calls/call_breakdown_composer.py:533
_request_llm3_call_breakdown()
```

### LLM-3: Голос клиента

```text
/root/ai-sales-analyzer/core/app/agents/calls/voice_of_customer_composer.py
```

Ключевые функции:

```text
/root/ai-sales-analyzer/core/app/agents/calls/voice_of_customer_composer.py:659
compose_voice_of_customer()

/root/ai-sales-analyzer/core/app/agents/calls/voice_of_customer_composer.py:712
_try_llm3_voice_of_customer()

/root/ai-sales-analyzer/core/app/agents/calls/voice_of_customer_composer.py:741
_request_llm3_voice_of_customer()
```

### LLM-3: Позвони завтра

```text
/root/ai-sales-analyzer/core/app/agents/calls/call_tomorrow_wording_composer.py
```

Ключевые функции:

```text
/root/ai-sales-analyzer/core/app/agents/calls/call_tomorrow_wording_composer.py:50
compose_call_tomorrow_wording()

/root/ai-sales-analyzer/core/app/agents/calls/call_tomorrow_wording_composer.py:135
_try_llm3_call_tomorrow_wording()

/root/ai-sales-analyzer/core/app/agents/calls/call_tomorrow_wording_composer.py:164
_request_llm3_call_tomorrow_wording()
```

## Полные пути к инструкциям

### LLM-1

```text
/root/ai-sales-analyzer/core/app/agents/calls/prompts/classify.md
```

### LLM-2

Основная инструкция:

```text
/root/ai-sales-analyzer/core/app/agents/calls/prompts/analyze.md
```

Дополнительные prompt-активы:

```text
/root/ai-sales-analyzer/core/app/agents/calls/prompts/agreements.md
/root/ai-sales-analyzer/core/app/agents/calls/prompts/insights.md
/root/ai-sales-analyzer/core/app/agents/calls/prompts/analyze_v16_context_evidence.md
```

MVP1-источники, которые используются как утвержденные контракты/примеры:

```text
/root/ai-sales-analyzer/docs/mvp1_sources/MVP1_CHECKLIST_DEFINITION_v1.md
/root/ai-sales-analyzer/docs/mvp1_sources/MVP1_CALL_ANALYSIS_CONTRACT_v1.md
/root/ai-sales-analyzer/docs/mvp1_sources/MVP1_CALL_ANALYSIS_EXAMPLE_TIMUR_v1.json
/root/ai-sales-analyzer/docs/mvp1_sources/MVP1_MANAGER_CARD_FORMAT_v1.md
/root/ai-sales-analyzer/docs/mvp1_sources/MVP1_CODEX_HANDOFF.md
```

### LLM-3

```text
/root/ai-sales-analyzer/core/app/agents/calls/prompts/situation_day_daily_composer_v2.md
/root/ai-sales-analyzer/core/app/agents/calls/prompts/call_breakdown_composer_v2.md
/root/ai-sales-analyzer/core/app/agents/calls/prompts/voice_of_customer_composer_v2.md
/root/ai-sales-analyzer/core/app/agents/calls/prompts/call_tomorrow_wording_composer_v1.md
```

## Где появляются артефакты

### LLM-1

Основной runtime-артефакт:

```text
llm1_first_pass
```

Используется как входной контекст для LLM-2. Также попадает в routing/diagnostics metadata.

В режиме подмены LLM субагентами или симуляцией дополнительно создаются временные input/output JSON-артефакты в директориях вида:

```text
/tmp/asa_llm_subagent_runs/<run_id>/
/tmp/asa_llm_sim_runs/<run_id>/
```

### LLM-2

Основной артефакт сохраняется в БД как результат анализа звонка:

```text
Analysis.scores_detail
Analysis.raw_llm_response
Analysis.instruction_version
Analysis.score_total
Analysis.strengths
Analysis.weaknesses
Analysis.recommendations
Agreement
Insight
```

Также из LLM-2 формируются данные для отчета:

```text
report_evidence
block_candidates
```

В режиме подмены LLM субагентами или симуляцией дополнительно создаются временные input/output JSON-артефакты в директориях вида:

```text
/tmp/asa_llm_subagent_runs/<run_id>/
/tmp/asa_llm_sim_runs/<run_id>/
```

### LLM-3

LLM-3 не создает отдельный `Analysis` в БД. Он создает report composition artifacts, которые попадают в payload отчета и затем рендерятся в PDF/DOCX/HTML/text.

Основные блоки payload:

```text
situation_day
call_breakdown
voice_of_customer
call_tomorrow
```

В режиме подмены LLM субагентами или симуляцией дополнительно создаются временные input/output JSON-артефакты в директориях вида:

```text
/tmp/asa_llm_subagent_runs/<run_id>/
/tmp/asa_llm_sim_runs/<run_id>/
```

В `subagent_runtime` имена файлов формируются единообразно для LLM-1/LLM-2/LLM-3:

```text
<index>_<layer>_<request_kind>_<subject_key>_input.json
<index>_<layer>_<request_kind>_<subject_key>_output.json
```

Примеры:

```text
0001_llm1_classification_first_pass_<interaction_id>_input.json
0001_llm1_classification_first_pass_<interaction_id>_output.json
0002_llm2_approved_contract_generation_<interaction_id>_input.json
0002_llm2_approved_contract_generation_<interaction_id>_output.json
0003_llm3_situation_day_daily_composer_<subject_key>_input.json
0003_llm3_situation_day_daily_composer_<subject_key>_output.json
```

В local simulation adapter для LLM-3 могут использоваться фиксированные имена:

```text
llm3_situation_day_input.json
llm3_situation_day_output.json
llm3_call_breakdown_input.json
llm3_call_breakdown_output.json
llm3_voice_of_customer_input.json
llm3_voice_of_customer_output.json
llm3_call_tomorrow_input.json
llm3_call_tomorrow_output.json
```

## Требование для подмены LLM субагентами

Каждый субагент должен:

1. Получать тот же входной контекст, который сейчас получает соответствующий LLM-узел.
2. Исполнять ту же инструкцию из prompt-файла.
3. Возвращать тот же JSON-контракт, который ожидает текущий механизм.
4. Создавать тот же тип артефакта, чтобы downstream-механизм не отличал субагента от LLM.
