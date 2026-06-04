# AI Sales Analyzer — правила входа для агентов

Используй документацию GitHub-репозитория как основной source of truth.

Основные канонические правила находятся здесь:
- `docs/CODER_WORKING_RULES.md`
- `docs/TASK_PROMPT_TEMPLATE.md`
- `docs/PILOT_OPERATIONS.md`

Перед началом любой задачи:
1. Прочитай `docs/CODER_WORKING_RULES.md`.
2. Если задача связана с запуском STT/LLM/report pipeline, тестового режима,
   Codex-subagents или business delivery, прочитай `docs/PILOT_OPERATIONS.md`
   и `docs/RUNTIME_PROFILES.md`.
3. Если запрос пользователя не оформлен в формате проектной задачи, сначала нормализуй его.
4. Используй документацию репозитория как основной source of truth.
5. Держи scope ограниченным.
6. Не опирайся на память или скрытый контекст конкретного агента как на source of truth.
7. Перед сдачей результата заполни close-out checklist.
8. После каждого non-doc изменения выполни documentation-impact проверку и обнови
   `docs/PROGRESS.md` плюс все затронутые source-of-truth документы.

Критические правила по умолчанию:
- repo-first;
- verification first;
- без scope creep;
- документация ведется на русском языке; технические идентификаторы можно оставлять в исходном виде;
- обновлять `docs/PROGRESS.md`, когда изменился статус проекта;
- обновлять `docs/DECISIONS.md`, когда изменилось стабильное решение;
- non-doc изменения не завершены, пока не обработан documentation impact;
- repo hooks блокируют commit/push, если non-doc изменения не включают `docs/PROGRESS.md`;
- задача не завершена без close-out.
