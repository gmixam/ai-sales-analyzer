# CODER_WORKING_RULES

## Назначение
Этот документ фиксирует постоянные правила работы ИИ-кодера в проекте.
Это universal working policy, а не описание конкретного шага.

Task-промпты должны ссылаться на этот документ и содержать только переменную часть задачи плюс явные локальные ограничения.

## 1. Обязательный порядок входа в задачу

В начале каждой новой задачи кодер должен:
1. Прочитать [docs/CONTEXT_INDEX.md](docs/CONTEXT_INDEX.md) и документы из обязательного порядка чтения.
2. Зафиксировать текущий этап проекта и ближайший допустимый scope.
3. Отделить universal project rules от stage-specific rules и local task instructions.
4. Сначала проверить факты в коде и документах, и только потом делать выводы или изменения.

## 2. Verification-First

Если что-то не подтверждено фактами в коде, runtime evidence или актуальных документах, это нельзя считать установленным.

По умолчанию кодер должен:
- сначала проверять фактическое состояние;
- различать confirmed, inferred и not yet confirmed;
- не достраивать бизнес-логику, runtime behavior или implementation status по догадкам;
- не объявлять documented-but-not-implemented как already implemented без проверки.

## 3. Scope Control

Кодер обязан удерживать текущий scope и не расширять задачу без явного решения.

Базовые правила:
- не делать scope creep;
- не переходить к следующей вехе только потому, что текущая задача почти рядом;
- не трогать runtime behavior, если задача относится только к documentation / operating model;
- всё, что не относится к MVP-1, считать out of scope, если не сказано иное;
- scheduler / retries / beat / full automation loop не делать, пока это не подтверждено отдельным шагом;
- checklist definition, analysis contract и manager card считать разными сущностями и не смешивать их.

## 4. Правило по документации

Документация проекта является рабочим слоем управления и должна обновляться вместе с существенными изменениями понимания проекта.

### 4.1 Когда обязательно обновлять `DECISIONS.md`
Обновлять [docs/DECISIONS.md](docs/DECISIONS.md) обязательно, если:
- принято новое постоянное архитектурное или process-level решение;
- меняется ранее утверждённый инвариант, boundary или default operating rule;
- выбран новый standing behavior, который будет использоваться дальше по умолчанию.

Не обновлять `DECISIONS.md`, если:
- изменение чисто редакционное;
- задача только уточняет существующую формулировку без нового решения;
- речь только о локальном task-level instruction.

### 4.2 Когда обязательно обновлять `PROGRESS.md`
Обновлять [docs/PROGRESS.md](docs/PROGRESS.md) обязательно после значимых задач, которые:
- меняют фактический статус проекта;
- закрывают или открывают новый рабочий шаг;
- фиксируют найденный blocking gap или его устранение;
- меняют operating model, рабочий фокус или структуру документации, на которую будут опираться следующие задачи.

## 5. Если код и документы расходятся

Если найден gap между code и docs, кодер должен:
1. Не скрывать расхождение и не выбирать сторону молча.
2. Явно указать, что именно подтверждено кодом, а что подтверждено только документом.
3. Если задача позволяет, обновить docs или code так, чтобы расхождение стало явным и управляемым.
4. Если расхождение влияет на архитектурное решение, boundary или standing policy, обновить `DECISIONS.md`.
5. Если расхождение влияет на фактический статус шага, findings или next focus, обновить `PROGRESS.md`.

## 6. Prompt Layer Rule

Task-промпт не должен повторно перечислять постоянные правила проекта.

В task-промпте должна оставаться только:
- переменная часть текущего шага;
- конкретная задача;
- конкретные case ids / inputs;
- локальные ограничения именно этой задачи;
- ожидаемый результат именно этого шага;
- какие docs обновить, если изменения действительно затронут их.

Постоянные project-wide правила должны жить здесь.
Stage-specific policies должны жить в stage docs.
Prompt-asset policies должны жить в [docs/PROMPTS_GUIDE.md](docs/PROMPTS_GUIDE.md) и source prompt assets.

## 7. Обязательный формат ответа кодера

По умолчанию ответ кодера после выполнения задачи должен содержать:
1. какие файлы изменены;
2. что изменено по сути;
3. что проверено или чем подтверждён результат;
4. какие docs обновлены и почему;
5. какие ограничения, риски или intentionally untouched areas остались.

Если задача документационная, нужно отдельно обозначить:
- какие правила вынесены в постоянные docs;
- что осталось task-specific;
- как изменилась будущая форма task-промптов.

## 7.1 Git close-out по умолчанию

Если пользователь явно не ограничил задачу только analysis/docs/review и на машине есть рабочий Git remote/auth path, кодер должен по умолчанию доводить change до Git close-out:
- сделать осмысленный `commit`;
- выполнить `push`;
- при необходимости синхронизироваться с remote перед push.

Ограничения:
- не делать `force-push`, history rewrite, risky `rebase` или иное неоднозначное вмешательство без явного согласования;
- если `push` / `sync` заблокированы remote auth, branch protection, divergence или иным внешним blocker, кодер должен явно назвать blocker, а не делать вид, что Git-этап завершён;
- это process rule для обычного bounded close-out, а не разрешение скрывать незакрытые runtime/verification gaps.

## 8. Что считать stage-specific, а не universal

Следующие типы правил не должны жить в universal coder rules:
- acceptance criteria конкретного этапа;
- defect taxonomy конкретного этапа;
- exit criteria конкретного этапа;
- ручные cost controls конкретного этапа;
- artifact inventory конкретного этапа;
- language/output policies, если они пока привязаны только к одному этапу.

Такие правила должны жить в соответствующем stage doc.

## 9. Связанные документы
- Universal working rules: [docs/CODER_WORKING_RULES.md](docs/CODER_WORKING_RULES.md)
- Stage policy for current step: [docs/MANUAL_OUTPUT_VALIDATION_SPEC.md](docs/MANUAL_OUTPUT_VALIDATION_SPEC.md)
- Prompt policies: [docs/PROMPTS_GUIDE.md](docs/PROMPTS_GUIDE.md)
- Task prompt template: [docs/TASK_PROMPT_TEMPLATE.md](docs/TASK_PROMPT_TEMPLATE.md)
