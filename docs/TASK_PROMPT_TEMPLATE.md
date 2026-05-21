# TASK_PROMPT_TEMPLATE

## Короткий шаблон task-промпта

```md
Работаем по проекту ai-sales-analyzer.

Веха roadmap:
- <milestone>

Шаг roadmap:
- <step>

Что делаем:
- <what we are doing now>

Для чего:
- <why this step exists>

Используй как source of truth:
- docs/CONTEXT_INDEX.md
- docs/CODER_WORKING_RULES.md
- <task-specific docs only>

Сама задача:
- <exact task for this run>

Input / case ids:
- <interaction_id / analysis_id / external_id / file / dataset / prompt asset>

Scope boundaries этой задачи:
- in scope: <allowed scope>
- out of scope: <explicitly excluded scope>
- local restrictions: <local restrictions>

Expected output:
- <exact expected result for this task>

Какие документы обновить:
- docs/PROGRESS.md
- docs/DECISIONS.md
- <other affected docs only>

Documentation impact:
- non-doc changes require docs/PROGRESS.md in the same changeset
- behavior/contract/process changes require affected source-of-truth docs
- if docs are intentionally not updated, state the exact reason in close-out

## Close-out (обязательно заполнить перед сдачей)
- [ ] Documentation impact проверен — да / явно исключён (причина: ...)
- [ ] PROGRESS.md обновлён — да / нет / явно исключён (причина: ...)
- [ ] DECISIONS.md обновлён — да / нет / явно исключён (причина: ...)
- [ ] Другие docs обновлены — перечислить / нет / явно исключено
- [ ] Commit сделан — да / нет
- [ ] Push выполнен — да / нет
