# CONTEXT_INDEX

## Назначение
Этот файл задаёт быстрый и стабильный порядок входа в задачу для ИИ-кодера.
Использовать как стартовую точку в новой сессии.

## Обязательный порядок чтения

### 1. [docs/CODER_WORKING_RULES.md](docs/CODER_WORKING_RULES.md)
Зачем читать:
- понять постоянные правила работы кодера в этом проекте;
- не дублировать universal policies из task-промптов;
- сразу увидеть порядок входа в задачу, scope control, verification-first и правила обновления docs.

### 2. [docs/CONCEPT_MVP1.md](docs/CONCEPT_MVP1.md)
Зачем читать:
- понять продуктовую рамку MVP-1;
- увидеть, что входит в MVP-1 и что не входит;
- не расширять scope за пределы подтверждённого этапа.

### 3. [docs/ROADMAP.md](docs/ROADMAP.md)
Зачем читать:
- понять, в какой вехе проект находится сейчас;
- не перепутать Manual Output Validation с automation readiness;
- увидеть следующий допустимый переход.

### 4. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
Зачем читать:
- понять pipeline и архитектурные инварианты;
- не ломать determinism, contract stability и platform rules;
- увидеть, что считается runtime behavior, а что operating layer.

### 5. [docs/DECISIONS.md](docs/DECISIONS.md)
Зачем читать:
- понять уже принятые решения и ограничения;
- не принимать повторно уже закрытые вопросы;
- видеть, какие изменения требуют явного ADR/update.

### 6. [docs/PROGRESS.md](docs/PROGRESS.md)
Зачем читать:
- понять фактический статус и последний подтверждённый шаг;
- увидеть, что уже сделано, что в работе и что остаётся открытым;
- не возвращаться к уже закрытым вопросам без причины.

### 7. [docs/MANUAL_OUTPUT_VALIDATION_SPEC.md](docs/MANUAL_OUTPUT_VALIDATION_SPEC.md)
Читать по умолчанию, когда задача относится к текущему этапу.

Зачем читать:
- понять stage-specific policies для Manual Output Validation;
- использовать acceptance criteria, defect taxonomy и exit criteria без повторения в task-промпте;
- не уходить в automation readiness без явного подтверждения.

### 8. [docs/PROMPTS_GUIDE.md](docs/PROMPTS_GUIDE.md)
Читать, если задача затрагивает prompt assets, prompt docs или prompt behavior.

Зачем читать:
- понять, какие prompt policies являются постоянными;
- понять, что должно жить в source prompt assets / docs, а не в task-промпте;
- не дублировать language/output/schema constraints в каждом новом запросе.

### 9. [docs/MANUAL_REPORTING_PILOT.md](docs/MANUAL_REPORTING_PILOT.md)
Читать, если задача относится к ручному запуску отчётности, report presets, reuse logic, report-composer scope или delivery rules для reporting pilot.

Зачем читать:
- понять границы `Manual Reporting Pilot`;
- не перепутать ручной reporting pilot с automation readiness;
- видеть agreed launch parameters, presets, delivery rules и reuse/recompute policy.

### 10. [docs/MANAGER_DAILY_SELECTION_MODEL.md](docs/MANAGER_DAILY_SELECTION_MODEL.md)
Читать, если задача затрагивает отбор звонков для `manager_daily`, report contract, слои данных, rolling window или счётчики / причины исключения.

Зачем читать:
- понять canonical разграничение `raw_calls` / `meaningful_calls` / `coaching_core`;
- видеть, что именно должно попадать в список звонков дня vs коучинговые блоки;
- понять rolling window rule и transparency requirements;
- получить перечень bounded implementation tasks для реализации этого contract.

### 11. `docs/mvp1_sources/`
Читать только когда задача затрагивает analyzer contract, checklist, manager card format или source prompt assets.

Минимальный набор source-of-truth файлов:
- `MVP1_CODEX_HANDOFF.md`
- `MVP1_CHECKLIST_DEFINITION_v1.md`
- `MVP1_CALL_ANALYSIS_CONTRACT_v1.md`
- `MVP1_CALL_ANALYSIS_EXAMPLE_TIMUR_v1.json`
- `MVP1_MANAGER_CARD_FORMAT_v1.md`
- `TEST_CALL_TIMUR_2026-02-24_074137.json`

## Что где зафиксировано
- Universal coder rules: [docs/CODER_WORKING_RULES.md](docs/CODER_WORKING_RULES.md)
- Stage-specific Manual Output Validation rules: [docs/MANUAL_OUTPUT_VALIDATION_SPEC.md](docs/MANUAL_OUTPUT_VALIDATION_SPEC.md)
- Manual Reporting Pilot operating model: [docs/MANUAL_REPORTING_PILOT.md](docs/MANUAL_REPORTING_PILOT.md)
- **`manager_daily` selection model и report contract (canonical):** [docs/MANAGER_DAILY_SELECTION_MODEL.md](docs/MANAGER_DAILY_SELECTION_MODEL.md)
- Prompt policies и prompt/task split: [docs/PROMPTS_GUIDE.md](docs/PROMPTS_GUIDE.md)
- Короткий шаблон будущих task-промптов: [docs/TASK_PROMPT_TEMPLATE.md](docs/TASK_PROMPT_TEMPLATE.md)

## Как использовать индекс в новой сессии
В начале новой задачи ИИ должен:
1. Прочитать документы в порядке выше.
2. Зафиксировать текущий этап, допустимый scope и недопустимые расширения.
3. Проверить, относится ли задача к stage-specific policy.
4. Только после этого переходить к verification, analysis и изменениям.
