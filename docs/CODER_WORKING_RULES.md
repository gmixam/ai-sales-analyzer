
## `docs/CODER_WORKING_RULES.md`

```md
# CODER_WORKING_RULES

## Назначение
Этот документ фиксирует постоянные правила работы ИИ-кодера в проекте.

Это universal working policy, а не описание конкретного шага.

Task-промпты должны ссылаться на этот документ и содержать только переменную часть задачи, локальные ограничения, expected output и обязательный close-out.

## 0. Repo-first source of truth

Основной source of truth для проекта — GitHub-репозиторий.

Канонический контекст брать из repo, прежде всего из:
- `docs/`
- связанных prompt/source assets в repo

Текущий чат — управленческая дельта поверх repo.

Files in Sources, внешние snapshots и старый контекст прошлых чатов считаются reference-only слоем, если они не перенесены и не зафиксированы в repo docs.

При конфликте источников приоритет такой:
1. явная управленческая дельта из текущего чата;
2. repo docs;
3. Sources / reference snapshots;
4. старый чат / память агента.

Устойчивое решение из чата не считается постоянным source of truth, пока не зафиксировано в repo docs.

## 1. Обязательный порядок входа в задачу

В начале каждой новой задачи кодер должен:
1. Прочитать [docs/CONTEXT_INDEX.md](docs/CONTEXT_INDEX.md) и документы из обязательного порядка чтения.
2. Прочитать [docs/CODER_WORKING_RULES.md](docs/CODER_WORKING_RULES.md) как universal working policy.
3. Зафиксировать текущую Веху roadmap, текущий Шаг roadmap и ближайший допустимый scope.
4. Отделить universal project rules от stage-specific rules и local task instructions.
5. Сначала проверить факты в коде и документах, и только потом делать выводы или изменения.

## 2. Verification-First

Если что-то не подтверждено фактами в коде, runtime evidence или актуальных документах, это нельзя считать установленным.

По умолчанию кодер должен:
- сначала проверять фактическое состояние;
- различать `confirmed`, `inferred` и `not yet confirmed`;
- не достраивать бизнес-логику, runtime behavior или implementation status по догадкам;
- не объявлять documented-but-not-implemented как already implemented без проверки.

## 3. Scope Control

Кодер обязан удерживать текущий scope и не расширять задачу без явного решения.

Базовые правила:
- не делать scope creep;
- не переходить к следующей вехе только потому, что текущая задача рядом;
- не трогать runtime behavior, если задача относится только к documentation / operating model / process layer;
- всё, что не относится к подтверждённому текущему шагу, считать out of scope, если не сказано иное;
- scheduler / retries / beat / full automation loop не делать, пока это не подтверждено отдельным шагом;
- checklist definition, analysis contract и manager card считать разными сущностями и не смешивать их.

### 3.1 Generated report correction rule

Generated reports are verification artifacts, not source of truth.

Если проблема найдена в PDF, DOCX, HTML, Telegram preview или другом generated report artifact, кодер не должен править этот artifact вручную и не должен подгонять один конкретный отчёт, менеджера, звонок, номер или PDF.

Любая report-quality проблема должна быть сведена к upstream-механизму:
- prompt / prompt asset;
- schema / contract;
- validator;
- renderer / template;
- normalizer / formatter;
- selection logic;
- deterministic reporting logic;
- regression tests / verification checks.

Отчётные artifacts пересобираются только после system-level fix или явно зафиксированного no-code decision. Если нужен временный exception для review handoff, он должен быть назван как explicit temporary policy в docs/decision/progress, а не скрыт как ручная правка PDF.

## 4. Task normalization rule

Если входящая задача дана не в project task format, кодер не должен сразу переходить к реализации.

Сначала он обязан:
1. восстановить недостающий контекст из repo docs;
2. оформить задачу в project task format;
3. явно определить:
   - Веху roadmap,
   - Шаг roadmap,
   - Что делаем,
   - Для чего,
   - scope,
   - expected output,
   - какие docs обновить,
   - close-out;
4. только после этого выполнять задачу.

Это правило обязательно даже если пользователь дал задачу коротко или в свободной форме.

## 5. Правило по документации

Документация проекта является рабочим слоем управления и должна обновляться вместе с существенными изменениями понимания проекта.

### 5.0 Documentation impact gate

После любых изменений кодер обязан сделать явную documentation-impact проверку.

Минимальное правило:
- если менялся runtime code, tests, prompt assets, scripts, hooks, infra, report renderer, report contract, selection logic или process layer, то `docs/PROGRESS.md` должен быть обновлён в том же changeset;
- если изменение меняет standing behavior, boundary, architecture, operating rule или default role split, нужно также обновить `docs/DECISIONS.md`;
- если изменение меняет конкретный source-of-truth слой, нужно обновить профильный документ, а не только `PROGRESS.md`.

`PROGRESS.md` — это минимальный audit log, а не замена профильной документации.

Профильные docs по типу изменения:
- roadmap/current focus: `docs/ROADMAP.md`, `docs/CONTEXT_INDEX.md`, `docs/PROGRESS.md`;
- report behavior / manager-facing contract: `docs/BUSINESS_READY_REPORT_PACK_TASKS.md`, `docs/MANAGER_DAILY_SELECTION_MODEL.md`, `docs/REPORT_EVIDENCE_CONTRACT.md`;
- prompt behavior: `docs/PROMPTS_GUIDE.md`, relevant prompt asset docs, `docs/LLM2_MANAGER_DAILY_INSTRUCTIONS_MAP.md` when LLM2 behavior changes;
- process / agent rules: `docs/CODER_WORKING_RULES.md`, `docs/TASK_PROMPT_TEMPLATE.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, and `docs/DECISIONS.md`;
- provider/routing/runtime architecture: `docs/AI_PROVIDER_ROUTING.md`, `docs/ARCHITECTURE.md`;
- manual reporting operation: `docs/MANUAL_REPORTING_PILOT.md`, `docs/DEV_ONBOARDING.md` when onboarding/current-stage instructions change.

Если кодер считает, что docs update не нужен, он обязан явно написать в close-out:
- `docs impact: явно исключён`;
- почему изменение не меняет status, behavior, contract, roadmap, prompt, process или user-facing output.

Автоматический Git barrier является страховкой, а не заменой этого правила:
- `pre-commit` и `pre-push` блокируют non-doc changes без `docs/PROGRESS.md`;
- агент всё равно обязан обновить профильные docs вручную, когда это требуется по смыслу.

### 5.1 Когда обязательно обновлять `DECISIONS.md`

Обновлять [docs/DECISIONS.md](docs/DECISIONS.md) обязательно, если:
- принято новое постоянное архитектурное или process-level решение;
- меняется ранее утверждённый инвариант, boundary или default operating rule;
- выбран новый standing behavior, который будет использоваться дальше по умолчанию.

Не обновлять `DECISIONS.md`, если:
- изменение чисто редакционное;
- задача только уточняет существующую формулировку без нового решения;
- речь только о локальном task-level instruction.

### 5.2 Когда обязательно обновлять `PROGRESS.md`

Обновлять [docs/PROGRESS.md](docs/PROGRESS.md) обязательно после значимых задач, которые:
- меняют фактический статус проекта;
- закрывают или открывают новый рабочий шаг;
- фиксируют найденный blocking gap или его устранение;
- меняют operating model, рабочий фокус или структуру документации, на которую будут опираться следующие задачи.

## 6. Если код и документы расходятся

Если найден gap между code и docs, кодер должен:
1. Не скрывать расхождение и не выбирать сторону молча.
2. Явно указать, что именно подтверждено кодом, а что подтверждено только документом.
3. Если задача позволяет, обновить docs или code так, чтобы расхождение стало явным и управляемым.
4. Если расхождение влияет на архитектурное решение, boundary или standing policy, обновить `DECISIONS.md`.
5. Если расхождение влияет на фактический статус шага, findings или next focus, обновить `PROGRESS.md`.

## 7. Prompt Layer Rule

Task-промпт не должен повторно перечислять постоянные правила проекта.

В task-промпте должна оставаться только:
- переменная часть текущего шага;
- конкретная задача;
- конкретные case ids / inputs;
- локальные ограничения именно этой задачи;
- ожидаемый результат именно этого шага;
- какие docs обновить;
- обязательный close-out.

Постоянные project-wide правила должны жить здесь.

Stage-specific policies должны жить в stage docs.

Prompt-asset policies должны жить в [docs/PROMPTS_GUIDE.md](docs/PROMPTS_GUIDE.md) и source prompt assets.

## 8. Close-out rule

Каждая рабочая задача должна заканчиваться обязательным close-out.

Минимальный обязательный close-out:
- выполнена ли documentation-impact проверка;
- обновлён ли `PROGRESS.md`;
- обновлён ли `DECISIONS.md`;
- какие ещё docs обновлены;
- сделан ли `commit`;
- выполнен ли `push`.

Без заполненного close-out задача не считается завершённой.

Если какой-то пункт не выполнен, он должен быть отмечен как:
- `нет` с причиной;
или
- `явно исключён` с причиной.

## 9. Обязательный формат ответа кодера

По умолчанию ответ кодера после выполнения задачи должен содержать:
1. какие файлы изменены;
2. что изменено по сути;
3. что проверено или чем подтверждён результат;
4. какие docs обновлены и почему;
5. заполненный close-out;
6. какие ограничения, риски или intentionally untouched areas остались.

Если задача документационная, нужно отдельно обозначить:
- какие правила вынесены в постоянные docs;
- что осталось task-specific;
- как изменилась будущая форма task-промптов.

## 9.1 Git close-out по умолчанию

Если пользователь явно не ограничил задачу только analysis/docs/review и на машине есть рабочий Git remote/auth path, кодер должен по умолчанию доводить change до Git close-out:
- сделать осмысленный `commit`;
- выполнить `push`;
- при необходимости синхронизироваться с remote перед push.

Ограничения:
- не делать `force-push`, history rewrite, risky `rebase` или иное неоднозначное вмешательство без явного согласования;
- если `push` / `sync` заблокированы remote auth, branch protection, divergence или иным внешним blocker, кодер должен явно назвать blocker, а не делать вид, что Git-этап завершён;
- это process rule для обычного bounded close-out, а не разрешение скрывать незакрытые runtime/verification gaps.

## 10. Что считать stage-specific, а не universal

Следующие типы правил не должны жить в universal coder rules:
- acceptance criteria конкретного этапа;
- defect taxonomy конкретного этапа;
- exit criteria конкретного этапа;
- ручные cost controls конкретного этапа;
- artifact inventory конкретного этапа;
- language/output policies, если они пока привязаны только к одному этапу.

Такие правила должны жить в соответствующем stage doc.

## 11. Связанные документы
- Universal working rules: [docs/CODER_WORKING_RULES.md](docs/CODER_WORKING_RULES.md)
- Prompt template: [docs/TASK_PROMPT_TEMPLATE.md](docs/TASK_PROMPT_TEMPLATE.md)
- Prompt policies: [docs/PROMPTS_GUIDE.md](docs/PROMPTS_GUIDE.md)
- Roadmap: [docs/ROADMAP.md](docs/ROADMAP.md)
- Decisions: [docs/DECISIONS.md](docs/DECISIONS.md)
- Progress: [docs/PROGRESS.md](docs/PROGRESS.md)
