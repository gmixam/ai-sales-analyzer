# TASK_PROMPT_TEMPLATE

## Короткий шаблон task-промпта

```md
Работаем по проекту ai-sales-analyzer.

Контекст:
- использовать docs/CONTEXT_INDEX.md как стартовую точку;
- соблюдать docs/CODER_WORKING_RULES.md;
- текущий этап: <stage>;
- stage-specific policy: <stage doc>;

Текущий шаг:
- <current step>

Что делаем:
- <what we are doing now>

Для чего:
- <why this step exists>

Конкретная задача:
- <exact task for this run>

Input / case ids:
- <interaction_id / analysis_id / external_id / file / dataset / prompt asset>

Scope boundaries этой задачи:
- <allowed scope>
- <out of scope>
- <local restrictions>

Expected output:
- <exact expected result for this task>

Если будут изменения, обновить:
- <docs to update if affected>
```

## Принцип шаблона
Этот шаблон должен оставаться коротким.
Постоянные project rules, stage policies, language expectations, output behavior и schema constraints не нужно каждый раз повторять в task-промпте, если они уже закреплены в docs и source assets.
