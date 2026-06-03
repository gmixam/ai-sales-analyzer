# TMP: задачи по доработке LLM2A / LLM2B / общей инструкции LLM2

Дата: 2026-06-02
Статус: внедрено в runtime compact-профиль, full-day pipeline не запускался

## Статус реализации 2026-06-02

- Блок 1 / общая инструкция LLM2: выполнено.
  - Создан отдельный runtime common prompt:
    `core/app/agents/calls/prompts/llm2_common_runtime.md`.
  - Runtime LLM2 теперь подключает `llm2_common_runtime`, а не полный
    `llm2_pass_contracts.md`.
  - `llm2_pass_contracts.md` сохранен как архитектурный / handoff-контракт.

- Блок 2 / LLM2A: выполнено для compact-профиля.
  - Compact payload LLM2A больше не отправляет одновременно `transcript` и
    `segments`.
  - Вместо этого отправляется один `dialogue` с compact turns.
  - `start_ms/end_ms` и другие segment timestamps не попадают в dialogue.
  - Соседние мелкие STT segments с одной надежностью speaker-role склеиваются
    в более крупные turns без удаления текста.
  - LLM1 остается compact prior / hypothesis, не source of truth.

- Блок 3 / LLM2B: выполнено для compact-профиля.
  - `compact_scoring_rubric` больше не содержит per-criterion `score_rules`.
  - В payload остаются `criterion_code`, `criterion_name`, `stage`,
    `max_score` и контекст LLM2A.
  - Общий scoring guidance добавлен в
    `core/app/agents/calls/prompts/analyze_scoring_gaps.md`.
  - Pre-filter applicable stages не добавлялся.
  - LLM2B не дробился на subcalls.
  - Fail-closed handling пустых scoring artifacts уже присутствует в runtime:
    `_validate_llm2b_scoring_after_admission`.

- Проверки:
  - `docker compose exec -T api python -m py_compile /app/app/agents/calls/analyzer.py`
    - passed.
  - `docker compose exec -T api python -m pytest -q /app/tests/test_ai_provider_routing.py -k 'llm2_compact_profile or llm2_layered_runtime_uses_compact_common_prompt or llm2_layered_pass'`
    - `5 passed`.
  - `docker compose exec -T api python -m pytest -q /app/tests/test_llm2_layered_analysis.py`
    - `10 passed, 2 subtests passed`.
  - `git diff --check` - passed.

Подробный отчет по input size:

- `TMP_LLM2A_LLM2B_COMMON_PROMPT_REWORK_IMPLEMENTATION_REPORT.md`.

## Цель

Сократить размер input для LLM2 и повысить стабильность работы через
OpenAI-compatible модели без создания отдельного механизма под Kimi и без
просадки качества анализа.

Механизм должен оставаться универсальным:

- без model-specific веток в prompt;
- без новых stop-условий внутри LLM2;
- без технической обрезки, которая удаляет бизнес-смысл звонка;
- фактический допуск звонка к LLM2 остается до входа в LLM2;
- если звонок допущен в LLM2, узлы LLM2A/LLM2B/LLM2C/LLM2D выполняют свои роли
  на том input, который им передан.

## Текущая проблема

Текущий input LLM2 слишком большой, потому что в нем смешаны разные сущности:

1. Общий prompt LLM2 содержит и глобальные правила, и описание всех узлов:
   LLM2A, LLM2B, LLM2C, LLM2D.
2. LLM2A получает дублированный текст звонка: `transcript` и `segments` в
   значительной степени несут один и тот же смысл.
3. LLM2A получает больше metadata и контекста LLM1, чем нужно для его роли.
4. LLM2B получает большие scoring rules по каждому критерию внутри user
   payload.

В результате каждый узел LLM2 получает информацию, которая относится либо к
другим узлам, либо к архитектурной документации, а не к текущей задаче.

## Термины

- Полный input LLM: полный `messages[]`, который отправляется в модель.
- System message: сообщение с role `system`; сейчас оно собирается из общего
  prompt LLM2 и prompt конкретного узла.
- User message: сообщение с role `user`; содержит JSON payload для текущего
  узла.
- User payload: JSON внутри user message.
- Output: ответ модели / артефакт узла.

## Блок 1: общая инструкция LLM2

### Задача 1.1: отделить общие runtime-правила от архитектурного контракта

Текущий исходник:

- `core/app/agents/calls/prompts/llm2_pass_contracts.md`

Проблема:

- Файл используется как общий prompt, но содержит полный контракт для
  LLM2A/LLM2B/LLM2C/LLM2D.
- Из-за этого LLM2B получает описание LLM2A/LLM2C/LLM2D, и такая же проблема
  возникает у остальных узлов.

Что нужно изменить:

- Оставить `llm2_pass_contracts.md` как архитектурную / handoff-документацию,
  если он нужен в таком виде.
- Создать или подключить отдельный runtime common prompt, который содержит
  только правила, общие для всех узлов LLM2.

Runtime common prompt должен включать:

- правило ответа только в JSON;
- правило допустимых источников;
- запрет выдумывать факты, имена, цитаты, timestamps, договоренности, роли
  спикеров;
- прямые цитаты должны быть точными подстроками transcript;
- использовать `unknown`, если роль спикера ненадежна;
- цепочку источников истины:
  `transcript -> scenes -> evidence -> claim -> proof_card -> recommendation`;
- fail-closed дисциплину доказательности;
- границу допуска: LLM2 не добавляет whole-call stop conditions после того,
  как звонок уже допущен в LLM2;
- общие enum только если они действительно нужны всем узлам.

Runtime common prompt не должен включать:

- полные input/output схемы всех узлов LLM2;
- описания purpose для узлов, которые не являются текущим узлом;
- примеры или контракты, которые нужны только одному узлу.

Ожидаемый результат:

- Каждый узел LLM2 получает только:
  - компактные общие runtime-правила LLM2;
  - свой node-specific prompt;
  - свой user payload.

### Задача 1.2: держать node-specific контракты в prompt конкретного узла

Что нужно изменить:

- Перенести node-specific schema / purpose / forbidden behavior в prompt
  соответствующего узла.
- Для LLM2B это означает: scoring contract и scoring guidance должны жить в
  prompt LLM2B, а не в общем prompt и не повторяться по каждому критерию в
  payload.

Ожидаемый результат:

- Общая инструкция становится небольшой и стабильной.
- Prompt каждого узла становится местом, где определена реальная роль именно
  этого узла.

## Блок 2: LLM2A Facts / Scenes / Evidence Ledger

Текущий prompt узла:

- `core/app/agents/calls/prompts/analyze_facts_scenes.md`

Текущий диагностический пример payload:

- `review_packages/llm2_input_samples_tolegen_20260601/llm2a_facts_scenes.json`

### Задача 2.1: убрать дублирование transcript/segments из user payload

Проблема:

- `transcript` и `segments` в значительной степени дублируют одно и то же
  содержание звонка.
- Это увеличивает input, но не добавляет достаточно дополнительного смысла для
  LLM2A.

Что нужно изменить:

- Заменить дублирующую связку `transcript + full segments` на компактный
  dialogue input.
- Компактный dialogue должен сохранять:
  - роль спикера, если она известна;
  - текст реплики;
  - хронологический порядок;
  - достаточные границы реплик, чтобы восстановить смысл звонка.

Нельзя удалять фактический бизнес-смысл звонка.

Ожидаемый результат:

- LLM2A по-прежнему видит полный бизнес-разговор, но не получает его дважды.

### Задача 2.2: убрать timestamps из input модели, но сохранить их в backend metadata

Проблема:

- Миллисекундные timestamps не нужны для смысловой роли LLM2A.
- Они добавляют шум и tokens.

Что нужно изменить:

- Не отправлять `start_ms/end_ms` или похожие детальные поля времени в LLM2A,
  если только конкретная downstream-задача evidence mapping не требует их прямо
  в prompt.
- Сохранять timing в backend/STT metadata, чтобы deterministic code мог позже
  сопоставить evidence с исходными STT segments.

Ожидаемый результат:

- LLM2A фокусируется на смысле, scenes и evidence.
- Система все равно может трассировать evidence обратно к исходным STT данным
  вне prompt.

### Задача 2.3: сократить контекст LLM1 до compact prior

Проблема:

- Контекст LLM1 может стать слишком большим или слишком сильно влиять на LLM2A.
- LLM2A не должен воспринимать LLM1 как источник истины.

Что нужно изменить:

- Передавать только компактные поля LLM1 prior/hypothesis, которые помогают
  сориентировать LLM2A:
  - admission status/reason;
  - примерная гипотеза о типе звонка / business outcome;
  - ключевые warnings, если они есть.
- Явно обозначить это как prior context, а не proof.

Ожидаемый результат:

- LLM2A использует сам dialogue как источник истины.
- LLM1 помогает сориентироваться, но не доминирует над анализом.

### Задача 2.4: упростить task contract LLM2A в payload

Проблема:

- Часть инструкций повторяется и в prompt, и в payload.

Что нужно изменить:

- Держать устойчивый role/instruction текст в prompt LLM2A.
- User payload оставить сфокусированным на данных звонка и минимальных
  параметрах задачи.

Ожидаемый результат:

- Payload становится меньше.
- Становится меньше пересекающихся или потенциально конфликтующих инструкций.

## Блок 3: LLM2B Scoring / Gaps

Текущий prompt узла:

- `core/app/agents/calls/prompts/analyze_scoring_gaps.md`

Текущий диагностический пример payload:

- `review_packages/llm2_input_samples_tolegen_20260601/llm2b_scoring_gaps.json`

### Задача 3.1: вынести per-criterion score rules из user payload

Проблема:

- `compact_scoring_rubric` сейчас содержит большие `score_rules` по каждому
  критерию.
- В диагностическом примере это самая большая часть user payload LLM2B.

Что нужно изменить:

- Не удалять scoring logic.
- Вынести повторяющиеся scoring guidance в prompt LLM2B как общую инструкцию
  по оценке.
- User payload сфокусировать на:
  - criterion code;
  - criterion name;
  - stage;
  - max score;
  - коротком описании критерия, если оно нужно;
  - LLM2A scenes/evidence/business outcome.

Prompt LLM2B должен объяснять общий принцип оценки:

- `0`: ожидаемое поведение отсутствует, противоречит звонку или не
  подтверждено evidence;
- частичный балл: поведение есть, но оно неполное, слабое, расплывчатое или
  подтверждено только частично;
- максимальный балл: поведение явно присутствует и подтверждено scenes/evidence;
- not applicable только когда этап/критерий действительно не происходил в
  контексте звонка;
- absence-based scoring должен ссылаться на scenes/evidence или объяснять
  missing evidence reason.

Ожидаемый результат:

- Модель по-прежнему понимает, как оценивать критерии.
- Повторяющийся rubric payload становится существенно меньше.

### Задача 3.2: не выбирать applicable stages до LLM2B

Решение:

- Не добавлять новый upstream filter, который заранее решает, какие этапы
  чек-листа применимы до запуска LLM2B.

Причина:

- LLM2B является узлом, который отвечает за оценку.
- Applicability должна определяться во время scoring на основе LLM2A
  scenes/evidence, а не угадываться до scoring.

Ожидаемый результат:

- Нет скрытой фильтрации этапов перед LLM2B.

### Задача 3.3: пока не дробить LLM2B

Решение:

- На этом этапе не дробить LLM2B на несколько scoring subcalls.

Причина:

- Сейчас утвержденная оптимизация - это упрощение payload, а не архитектурное
  дробление.

Ожидаемый результат:

- LLM2B пока остается одним scoring node.

### Задача 3.4: добавить fail-closed обработку пустых scoring artifacts

Проблема:

- Если LLM2B возвращает пустые `stage_scores` или `criteria_results` для
  допущенного коммерческого звонка, report layer может остаться без
  доказанного бизнес-материала.

Что нужно изменить:

- Считать пустые scoring artifacts LLM2B runtime quality failure для analysis,
  а не успешным бизнес-анализом.
- Это должно быть diagnostic/fail-closed behavior, а не validator, который
  молча удаляет полезный контент.

Ожидаемый результат:

- Система не строит уверенные отчеты из пустых scoring outputs.
- Ошибки видны в diagnostics, их можно rerun или audit.

## Что не делаем в рамках этой доработки

В текущей задаче не нужно делать следующее:

- не создавать Kimi-specific prompt или Kimi-specific payload;
- не добавлять новые stop-условия внутри LLM2;
- не ограничивать анализ только duration;
- не pre-filter checklist stages перед LLM2B;
- не дробить LLM2B на несколько узлов;
- не удалять содержательный transcript content;
- не запускать full pipeline, пока prompt/input изменения не утверждены и не
  внедрены.

## Ожидаемая оптимизация

На основе диагностического примера по Толегену за 2026-06-01:

- User payload LLM2A, вероятно, можно сократить примерно на 70-80% за счет
  удаления дублирования transcript/segments, timestamps и лишнего LLM1/task
  payload.
- User payload LLM2B, вероятно, можно сократить примерно на 40% за счет
  переноса повторяющихся `score_rules` из payload в prompt LLM2B.
- Common system prompt может существенно сократиться, потому что каждый узел
  больше не будет получать полный архитектурный контракт 2A/2B/2C/2D.

Точную оптимизацию нужно измерить после внедрения через runtime diagnostics:

- system message chars/tokens;
- user payload chars/tokens;
- output tokens;
- wall time;
- repair count;
- scoring completeness;
- ручной quality audit на том же контрольном звонке.

## План проверки

После внедрения проверять в такой последовательности:

1. Static checks:
   - prompt files существуют;
   - загрузка node prompt продолжает работать;
   - нет случайного удаления исходных prompts/docs.

2. Unit tests:
   - сборка compact/common prompt;
   - LLM2A payload больше не отправляет одновременно duplicated transcript и
     full segments;
   - LLM2B payload больше не отправляет повторяющиеся per-criterion
     score rules;
   - fail-closed diagnostics для пустых LLM2B scoring artifacts.

3. One-call controlled run:
   - использовать тот же контрольный звонок Толегена за 2026-06-01, который уже
     использовался для diagnostics;
   - запускать только ready STT -> LLM2;
   - сравнить before/after payload sizes, tokens, wall time и output quality.

4. Manual audit:
   - проверить, что LLM2A по-прежнему забирает реальный смысл звонка;
   - проверить, что LLM2B не завышает score;
   - проверить, что слабые/расплывчатые фразы о follow-up не считаются твердой
     договоренностью;
   - проверить, что `criteria_results` и `stage_scores` заполнены, если звонок
     допущен и подлежит scoring.

## Approval gate

Внедрение начинать только после утверждения этого файла.

После внедрения не запускать full-day pipeline автоматически. Сначала нужно
запустить one-call controlled LLM2 test и разобрать diagnostics.
