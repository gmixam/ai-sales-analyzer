# Agent Project Operating System Template

Практический шаблон для проектов, где над кодом, данными, операциями и
документацией работают AI-агенты. Его можно положить в новый репозиторий,
создать описанную структуру файлов и использовать как систему handoff,
roadmap, backlog, мини-ТЗ, runtime profiles, decisions, feedback, post-run
audit и agent protocols.

Файл не описывает конкретный проект. Все примеры ниже общие. Значения в угловых
скобках нужно заменить на реальные данные нового проекта.

## Базовые принципы

- `AGENTS.md` в корне проекта - главный вход для любого агента.
- Репозиторий и документы в нем являются source of truth. Память агента,
  переписка и локальные догадки не являются source of truth.
- Если агенту дали конкретную задачу, он читает `AGENTS.md`,
  `docs/00_handoff/ACTIVE_WORK_STATE.md`,
  `docs/00_handoff/CONTEXT_INDEX.md`, backlog и конкретное ТЗ.
- Если агенту не дали конкретную задачу, он читает стартовый маршрут и
  возвращает статус проекта, риски и рекомендуемый следующий шаг, но не
  начинает реализацию без подтверждения.
- Новую или неоднозначную задачу сначала оформить как `TASK_TZ.md`, затем
  реализовывать.
- Worker-агентам всегда задавать file scope: какие файлы можно читать и какие
  файлы можно менять.
- Главный агент отвечает за интеграцию, тесты, финальную проверку и обновление
  статусов.
- Production pipeline, бизнес-доставку, оплату/API budget и внешние отправки
  нельзя запускать без явного разрешения, если это не уже утвержденный
  production schedule.

## Рекомендуемая структура

```text
project-root/
  AGENTS.md
  README.md

  docs/
    00_handoff/
      ACTIVE_WORK_STATE.md
      CONTEXT_INDEX.md

    01_strategy/
      CONCEPT.md
      ROADMAP.md
      DECISIONS.md

    02_operations/
      OPERATIONS_RUNBOOK.md
      RUNTIME_PROFILES.md
      SCHEDULES.md
      DELIVERY_RULES.md

    03_backlog/
      PROJECT_BACKLOG.md
      FEEDBACK.md
      OPERATIONAL_FINDINGS.md

    04_tasks/
      TASK_TEMPLATE.md
      PROJECT-001_TASK_TZ.md

    05_metrics/
      KPI_MEASUREMENTS.md
      COST_TRACKING.md
      POST_RUN_AUDIT_TEMPLATE.md

    06_agent_instructions/
      DELEGATION_PROTOCOL.md
      PRODUCTION_SAFETY_RULES.md
      REVIEW_PROTOCOL.md
      AGENT_RESPONSE_FORMAT.md

    07_architecture/
      ARCHITECTURE.md
      DATA_FLOW.md
      INTEGRATIONS.md
      RUNTIME_MODES.md

    08_reports/
      MANAGEMENT_SUMMARIES.md
      WEEKLY_SUMMARIES.md
      PILOT_RESULTS.md

    archive/
      YYYY-MM-task-history/
      YYYY-MM-old-audits/
```

## Назначение файлов

| Файл | Назначение |
| --- | --- |
| `AGENTS.md` | Главная инструкция входа для агентов: порядок чтения, правила scope, safety, close-out. |
| `README.md` | Человеческое описание проекта, быстрый старт, основные команды. |
| `ACTIVE_WORK_STATE.md` | Короткая оперативная карточка: текущий статус, активный runtime, последняя безопасная точка, следующий шаг. |
| `CONTEXT_INDEX.md` | Карта чтения: какие документы открыть для разных типов задач. |
| `CONCEPT.md` | Продуктовая идея, пользователи, границы проекта. |
| `ROADMAP.md` | Крупные этапы, milestones, acceptance criteria по этапам. |
| `DECISIONS.md` | Стабильные архитектурные, продуктовые и операционные решения. |
| `OPERATIONS_RUNBOOK.md` | Как запускать, проверять, останавливать и восстанавливать систему. |
| `RUNTIME_PROFILES.md` | Разрешенные режимы запуска: dev/test/staging/production, модели, budgets, env. |
| `SCHEDULES.md` | Утвержденные расписания и владельцы. |
| `DELIVERY_RULES.md` | Правила внешних отправок, business delivery, preview/test delivery. |
| `PROJECT_BACKLOG.md` | Очередь задач с ID, статусами, проверками результата и ссылками на ТЗ. |
| `FEEDBACK.md` | Журнал обратной связи от пользователей, менеджеров, операторов, ревьюеров. |
| `OPERATIONAL_FINDINGS.md` | Факты из запусков: сбои, аномалии, неполные данные, cost spikes. |
| `TASK_TEMPLATE.md` | Базовый шаблон мини-ТЗ. |
| `PROJECT-001_TASK_TZ.md` | Конкретное ТЗ на задачу. |
| `KPI_MEASUREMENTS.md` | Замеры качества, покрытия, SLA, бизнес-метрик. |
| `COST_TRACKING.md` | Стоимость запусков, API, инфраструктуры, отклонения от budget. |
| `POST_RUN_AUDIT_TEMPLATE.md` | Шаблон проверки после значимого запуска. |
| `DELEGATION_PROTOCOL.md` | Как главный агент делегирует задачи worker-агентам. |
| `PRODUCTION_SAFETY_RULES.md` | Что нельзя запускать без разрешения, gates, rollback, secrets. |
| `REVIEW_PROTOCOL.md` | Как проверять изменения, тесты, docs impact, безопасность. |
| `AGENT_RESPONSE_FORMAT.md` | Формат финального ответа агента. |
| `ARCHITECTURE.md` | Основная архитектура системы. |
| `DATA_FLOW.md` | Потоки данных, владельцы данных, входы/выходы. |
| `INTEGRATIONS.md` | Внешние сервисы, contracts, credentials policy. |
| `RUNTIME_MODES.md` | Техническая карта режимов исполнения. |
| `MANAGEMENT_SUMMARIES.md` | Короткие управленческие итоги. |
| `WEEKLY_SUMMARIES.md` | Еженедельные summaries. |
| `PILOT_RESULTS.md` | Итоги пилотов, GO/NO-GO, выводы. |
| `archive/` | История, старые аудиты и документы, которые больше не являются входом по умолчанию. |

## Стартовый маршрут агента

### Если задача задана явно

1. Прочитать `AGENTS.md`.
2. Прочитать `docs/00_handoff/ACTIVE_WORK_STATE.md`.
3. Прочитать `docs/00_handoff/CONTEXT_INDEX.md`.
4. Найти задачу в `docs/03_backlog/PROJECT_BACKLOG.md`.
5. Открыть конкретное ТЗ из `docs/04_tasks/`.
6. Открыть документы, указанные в `CONTEXT_INDEX.md` для этого типа задачи.
7. Проверить runtime/safety, если задача связана с запуском, внешними сервисами,
   деньгами, production или доставкой.
8. Реализовать строго в scope.
9. Прогнать проверки.
10. Обновить статусы: backlog, task TZ, active state, decisions/feedback/findings
    при необходимости.
11. Дать финальный отчет.

### Если задача не задана явно

1. Прочитать `AGENTS.md`.
2. Прочитать `ACTIVE_WORK_STATE.md`.
3. Прочитать `CONTEXT_INDEX.md`.
4. Прочитать `PROJECT_BACKLOG.md`, `ROADMAP.md`, `DECISIONS.md`.
5. Вернуть:
   - текущий статус проекта;
   - последние безопасные точки;
   - активные риски;
   - рекомендуемый следующий шаг;
   - какие подтверждения нужны.
6. Не начинать реализацию и не запускать production-действия без подтверждения.

## Шаблон `AGENTS.md`

````md
# AGENTS.md

Этот файл - главный вход для AI-агентов в проекте `<project_name>`.

Используй документацию репозитория как основной source of truth. Не опирайся на
память, скрытый контекст или устные предположения, если они противоречат файлам
проекта.

## Перед началом любой задачи

1. Прочитай этот файл.
2. Прочитай `docs/00_handoff/ACTIVE_WORK_STATE.md`.
3. Прочитай `docs/00_handoff/CONTEXT_INDEX.md`.
4. Если задача есть в backlog, открой `docs/03_backlog/PROJECT_BACKLOG.md` и
   конкретное ТЗ из `docs/04_tasks/`.
5. Если задача новая или неоднозначная, сначала подготовь/обнови ТЗ и получи
   подтверждение, если меняются scope, production, бюджет, внешние отправки или
   бизнес-логика.
6. Если задача связана с runtime, pipeline, расписанием, внешними API, оплатой
   или доставкой, прочитай:
   - `docs/02_operations/OPERATIONS_RUNBOOK.md`;
   - `docs/02_operations/RUNTIME_PROFILES.md`;
   - `docs/06_agent_instructions/PRODUCTION_SAFETY_RULES.md`.

## Если конкретной задачи нет

Верни краткий статус проекта:

- текущий этап;
- активный runtime;
- последние выполненные работы;
- главные риски;
- рекомендуемый следующий шаг;
- что нужно подтвердить перед реализацией.

Не начинай реализацию без подтверждения пользователя.

## Рабочие правила

- Держи scope ограниченным.
- Не делай скрытые refactor/cleanup вне задачи.
- Не меняй production settings без явного разрешения.
- Не запускай внешнюю отправку, платежные/API-budget действия и production
  pipeline без явного разрешения, если это не утвержденное расписание.
- Worker-агентам всегда задавай file scope.
- Главный агент отвечает за интеграцию, тесты и обновление статусов.
- Любые non-doc изменения требуют docs-impact проверки.
- Если принято стабильное решение, обнови `docs/01_strategy/DECISIONS.md`.
- Если найден operational issue, обнови
  `docs/03_backlog/OPERATIONAL_FINDINGS.md` или backlog.
- Если получена обратная связь, обнови `docs/03_backlog/FEEDBACK.md`.

## Close-Out Checklist

Перед финальным ответом проверь:

- [ ] задача выполнена в заявленном scope;
- [ ] тесты/проверки запущены или явно указано, почему не запускались;
- [ ] production/delivery/budget действия не выполнялись без разрешения;
- [ ] backlog/TZ/status docs обновлены при необходимости;
- [ ] secrets, токены, приватные данные не попали в код, логи и документы;
- [ ] финальный ответ содержит измененные файлы, проверки и остаточные риски.
````

## Шаблон `ACTIVE_WORK_STATE.md`

````md
# ACTIVE_WORK_STATE

Дата обновления: YYYY-MM-DD
Статус: `active | waiting_for_user | blocked | paused | done`

## Назначение

Короткая оперативная карточка проекта. История хранится в roadmap/backlog,
решения - в `DECISIONS.md`, режимы запуска - в `RUNTIME_PROFILES.md`.

Перед началом новой сессии открыть:

```text
AGENTS.md
docs/00_handoff/ACTIVE_WORK_STATE.md
docs/00_handoff/CONTEXT_INDEX.md
docs/03_backlog/PROJECT_BACKLOG.md
docs/01_strategy/ROADMAP.md
docs/01_strategy/DECISIONS.md
docs/02_operations/RUNTIME_PROFILES.md
docs/02_operations/OPERATIONS_RUNBOOK.md
```

Если статус `waiting_for_user`, агент не должен продолжать реализацию до ответа
пользователя.

## Current Status

- Текущий этап: `<этап проекта>`.
- Текущая цель: `<что сейчас стабилизируем/строим>`.
- Последний закрытый пакет: `<commit/task/run/date>`.
- Что считается source of truth: `<ключевые документы>`.

## Active Runtime

```text
RUNTIME_PROFILE=<dev|test|staging|production|custom>
EXTERNAL_DELIVERY_ENABLED=false
BUSINESS_DELIVERY_ENABLED=false
API_BUDGET_MODE=<disabled|limited|approved>
SCHEDULE_MODE=<off|review_required|production>
```

Source of truth по runtime: `docs/02_operations/RUNTIME_PROFILES.md`.

## Last Safe Point

- Код: `<branch/commit/tag>`.
- Данные: `<backup/snapshot/run id, если применимо>`.
- Последний безопасный запуск: `<дата, режим, результат>`.
- Rollback path: `<как откатиться>`.

## Active Risks

| Риск | Влияние | Что делать |
| --- | --- | --- |
| `<risk>` | `<impact>` | `<mitigation>` |

## Current Priority

| Priority | Task ID | Статус | Следующий шаг |
| --- | --- | --- | --- |
| P1 | PROJECT-001 | `planned` | `<next step>` |

## Next Step

Рекомендуемый следующий шаг:

```text
<одна конкретная рекомендуемая задача>
```

Нужно подтверждение пользователя перед:

- `<production action>`;
- `<external delivery>`;
- `<budget/API spend>`;
- `<schema/data migration>`.
````

## Шаблон `CONTEXT_INDEX.md`

````md
# CONTEXT_INDEX

## Назначение

Быстрый порядок входа в проект для нового AI-агента или инженера.

Текущий этап: `<current_stage>`.

## Обязательный порядок чтения

1. `AGENTS.md`
   - правила входа, scope, safety, close-out.
2. `docs/00_handoff/ACTIVE_WORK_STATE.md`
   - текущий статус, последняя безопасная точка, следующий шаг.
3. `docs/03_backlog/PROJECT_BACKLOG.md`
   - актуальная очередь задач.
4. `docs/01_strategy/ROADMAP.md`
   - этапы и acceptance criteria.
5. `docs/01_strategy/DECISIONS.md`
   - стабильные решения.
6. `docs/02_operations/RUNTIME_PROFILES.md`
   - разрешенные runtime-профили.
7. `docs/02_operations/OPERATIONS_RUNBOOK.md`
   - запуск, проверка, rollback, post-run audit.

## Если задача связана с кодом

Дополнительно открыть:

- `docs/07_architecture/ARCHITECTURE.md`;
- `docs/07_architecture/DATA_FLOW.md`;
- релевантное ТЗ из `docs/04_tasks/`;
- тесты рядом с изменяемым кодом.

## Если задача связана с production/runtime

Дополнительно открыть:

- `docs/02_operations/RUNTIME_PROFILES.md`;
- `docs/02_operations/SCHEDULES.md`;
- `docs/02_operations/DELIVERY_RULES.md`;
- `docs/06_agent_instructions/PRODUCTION_SAFETY_RULES.md`;
- `docs/05_metrics/COST_TRACKING.md`.

## Если задача связана с feedback

Дополнительно открыть:

- `docs/03_backlog/FEEDBACK.md`;
- `docs/03_backlog/PROJECT_BACKLOG.md`;
- `docs/08_reports/MANAGEMENT_SUMMARIES.md`, если нужно понять бизнес-контекст.

## Не считать актуальным входом

- Старые файлы в `docs/archive/`, если они противоречат handoff/backlog/decisions.
- Локальные runtime artifacts, logs, temp outputs, если они не зафиксированы в
  source-of-truth документах.
- Старые отчеты, если их статус был заменен новым audit или decision.

## Перед запуском pipeline или внешнего действия

1. Назвать runtime-профиль.
2. Проверить env/config без вывода секретов.
3. Проверить delivery mode.
4. Проверить budget/API ограничения.
5. Проверить rollback path.
6. После запуска заполнить post-run audit.
````

## Шаблон `PROJECT_BACKLOG.md`

````md
# PROJECT_BACKLOG

Дата актуализации: YYYY-MM-DD

## Назначение

Рабочий backlog текущего этапа. Это очередь внедрения, а не журнал всех мыслей.
Feedback хранится в `FEEDBACK.md`, факты запусков - в
`OPERATIONAL_FINDINGS.md`, решения - в `DECISIONS.md`.

## Правила работы

1. Каждая задача имеет ID, priority, статус, краткое описание и проверку
   результата.
2. Новая/неоднозначная задача получает ТЗ в `docs/04_tasks/`.
3. Feedback не чинится вручную в артефакте. Сначала запись в `FEEDBACK.md`,
   затем проверка данных, затем задача в backlog.
4. Operational finding связывается с существующей задачей или создает новую.
5. После реализации статус обновляет главный агент, который сделал интеграцию
   и проверки.

## Статусы

| Статус | Значение |
| --- | --- |
| `new` | задача добавлена, ТЗ еще нет или не утверждено |
| `planned` | ТЗ готово, реализация не начата |
| `in_progress` | идет реализация |
| `implemented_first_pass` | первый pass внедрен, нужны проверки/наблюдение |
| `production_active_first_pass` | включено в production, нужен мониторинг |
| `blocked` | нужен внешний ответ/данные/доступ |
| `done` | принято и проверено |
| `deferred` | осознанно отложено |

## P1 - Надежность / критичный путь

| ID | Задача | Статус | ТЗ | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- | --- |
| PROJECT-001 | `<short task>` | `planned` | `docs/04_tasks/PROJECT-001_TASK_TZ.md` | `<implementation summary>` | `<acceptance check>` |

## P2 - Пользовательская ценность

| ID | Задача | Статус | ТЗ | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- | --- |
| PROJECT-002 | `<short task>` | `new` | `<link or TBD>` | `<what>` | `<check>` |

## P3 - Операционное улучшение

| ID | Задача | Статус | ТЗ | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- | --- |
| PROJECT-003 | `<short task>` | `deferred` | `<link>` | `<what>` | `<check>` |

## Feedback Links

| Feedback ID | Связанная задача | Статус связи | Комментарий |
| --- | --- | --- | --- |
| FB-YYYY-MM-DD-01 | PROJECT-001 | `planned` | `<why linked>` |

## Operational Findings Links

| Finding ID | Связанная задача | Статус связи | Наблюдение |
| --- | --- | --- | --- |
| FIND-YYYY-MM-DD-01 | PROJECT-001 | `new` | `<short fact>` |

## Следующий рекомендуемый шаг

1. `<PROJECT-001 next action>`.
2. `<PROJECT-002 next action>`.
3. `<что нужно подтвердить перед production>`.
````

## Шаблон `ROADMAP.md`

````md
# ROADMAP

Дата актуализации: YYYY-MM-DD

## Цель проекта

`<одним абзацем: какую проблему решаем и для кого>`

## Этапы

| Этап | Статус | Цель | Acceptance criteria |
| --- | --- | --- | --- |
| Phase 0 - Discovery | `done` | `<goal>` | `<criteria>` |
| Phase 1 - MVP | `active` | `<goal>` | `<criteria>` |
| Phase 2 - Pilot | `planned` | `<goal>` | `<criteria>` |
| Phase 3 - Production | `planned` | `<goal>` | `<criteria>` |

## Текущий этап

- Этап: `<phase>`.
- Что уже закрыто: `<done>`.
- Что блокирует переход дальше: `<blockers>`.
- GO/NO-GO критерии: `<criteria>`.

## Milestones

| ID | Milestone | Target | Статус | Проверка |
| --- | --- | --- | --- | --- |
| M1 | `<name>` | YYYY-MM-DD | `planned` | `<evidence>` |

## Не входит в текущий этап

- `<explicit non-goal>`;
- `<explicit non-goal>`.

## Связанные документы

- `docs/03_backlog/PROJECT_BACKLOG.md`;
- `docs/01_strategy/DECISIONS.md`;
- `docs/05_metrics/KPI_MEASUREMENTS.md`.
````

## Шаблон `TASK_TZ.md`

````md
# PROJECT-001: <название задачи>

Дата: YYYY-MM-DD
Статус: `draft | approved | in_progress | implemented_first_pass | done | blocked`

## Контекст

`<что произошло, почему задача появилась, какие документы/feedback/findings связаны>`

Связанные документы:

- `docs/03_backlog/PROJECT_BACKLOG.md`;
- `docs/03_backlog/FEEDBACK.md`;
- `docs/03_backlog/OPERATIONAL_FINDINGS.md`;
- `<дополнительные ссылки>`.

## Цель

`<какой результат должен получить пользователь/система>`

## Принятое решение

`<если решение уже принято: какой вариант выбран и почему>`

Если решение не принято:

- Вариант A: `<описание>`;
- Вариант B: `<описание>`;
- Рекомендация: `<что выбрать>`;
- Что нужно подтвердить: `<вопросы пользователю>`.

## Scope

В scope:

- `<изменение 1>`;
- `<изменение 2>`;
- `<документация/тесты>`.

Не в scope:

- `<явный non-goal>`;
- `<не делать в этой задаче>`.

## Требования

### Functional

1. `<requirement>`.
2. `<requirement>`.

### Safety

1. Не запускать production delivery без явного разрешения.
2. Не выводить секреты в логи, документы и финальный отчет.
3. Сохранять backward compatibility, если явно не согласовано иное.

### Observability

- `<какие статусы/логи/метрики должны появиться>`;
- `<как оператор поймет результат>`.

## File Scope

Разрешено менять:

- `path/to/file_a.py`;
- `path/to/test_file.py`;
- `docs/03_backlog/PROJECT_BACKLOG.md`;
- `docs/04_tasks/PROJECT-001_TASK_TZ.md`.

Не менять без отдельного подтверждения:

- `<sensitive file>`;
- `<production config>`;
- `<unrelated module>`.

## План реализации

1. `<step>`.
2. `<step>`.
3. `<step>`.

## Acceptance Criteria

1. `<observable result>`.
2. `<test/check passes>`.
3. `<docs updated>`.
4. `<no production side effects without approval>`.

## Test Plan

- Unit: `<commands or tests>`.
- Integration: `<commands or tests>`.
- Manual smoke: `<what to inspect>`.
- Safety check: `<what must not happen>`.

## Rollout Plan

1. Реализовать first pass.
2. Запустить focused tests.
3. Провести controlled smoke в безопасном режиме.
4. Обновить backlog/status docs.
5. Включать production только после явного подтверждения или утвержденного
   schedule.

## Разделение по агентам

### Controller

- держит общий scope;
- выдает worker-агентам file scope;
- интегрирует изменения;
- запускает тесты;
- обновляет статусы.

### Worker A - <area>

- File scope: `<files>`;
- Задача: `<specific work>`;
- Не делать: `<boundaries>`.

### Worker B - <area>

- File scope: `<files>`;
- Задача: `<specific work>`;
- Не делать: `<boundaries>`.

## Риски

| Риск | Вероятность | Влияние | Защита |
| --- | --- | --- | --- |
| `<risk>` | `<low/medium/high>` | `<impact>` | `<mitigation>` |

## Definition of Done

- [ ] код/документы изменены в scope;
- [ ] tests/checks passed или причины пропуска указаны;
- [ ] backlog обновлен;
- [ ] active state обновлен, если поменялся текущий статус;
- [ ] decisions обновлены, если принято стабильное решение;
- [ ] production/external delivery не запускались без разрешения.
````

## Шаблон `DECISIONS.md`

````md
# DECISIONS

Стабильные решения проекта. Записывать только решения, которые должны пережить
одну задачу и быть известны будущим агентам.

## Формат ADR

```md
## ADR-000: <короткое название>

- **Decision:** <что решили>
- **Reason:** <почему>
- **Applies to:** <какие части системы/процесса>
- **Constraints:** <ограничения и non-goals>
- **Alternatives considered:** <если важно>
- **Date:** YYYY-MM-DD
- **Status:** accepted | superseded | deprecated
```

## ADR-001: <пример>

- **Decision:** `<решение>`.
- **Reason:** `<причина>`.
- **Applies to:** `<область>`.
- **Constraints:** `<границы>`.
- **Date:** YYYY-MM-DD
- **Status:** accepted

## Superseded Decisions

| ADR | Чем заменено | Дата | Причина |
| --- | --- | --- | --- |
| ADR-000 | ADR-001 | YYYY-MM-DD | `<why>` |
````

## Шаблон `FEEDBACK.md`

````md
# FEEDBACK

## Назначение

Журнал обратной связи от пользователей, клиентов, операторов, менеджеров и
ревьюеров. Это не backlog и не место для немедленных правок. Каждая запись
проходит путь:

```text
обратная связь -> затронутый блок -> ожидаемое поведение -> что проверить в
данных -> причина -> предложение -> задача или no-code решение
```

## Правила

- Фиксировать исходную формулировку без спора с участником.
- Отделять факт комментария от гипотезы команды.
- Проверять фактические претензии по исходным данным и артефактам.
- Не чинить один итоговый артефакт вручную, если проблема системная.
- Если feedback подтверждает системную проблему, связать его с задачей в
  `PROJECT_BACKLOG.md`.

## Статусы

| Статус | Значение |
| --- | --- |
| `new` | комментарий зафиксирован |
| `triaged` | затронутый блок и гипотеза определены |
| `needs_data_check` | нужна проверка данных |
| `confirmed` | дефект/потребность подтверждены |
| `not_reproduced` | не подтвердилось |
| `proposal_ready` | есть предложение |
| `linked_to_task` | связано с backlog/TZ |
| `implemented` | изменение внедрено |
| `closed` | результат проверен |

## Шаблон записи

```md
### FB-YYYY-MM-DD-N - <короткое название>

- Дата артефакта/события:
- Дата получения:
- Участник / роль:
- Канал:
- Статус:
- Критичность:
- Затронутые блоки:
- Исходный комментарий:
- Наблюдаемая проблема:
- Что проверить в данных:
- Первичные гипотезы:
- Предложения по улучшению:
- Решение / следующая задача:
- Ответственный:
- Ссылки / артефакты:
```

## Записи

### FB-YYYY-MM-DD-01 - <пример>

- Дата артефакта/события: YYYY-MM-DD
- Дата получения: YYYY-MM-DD
- Участник / роль: `<role>`
- Канал: `<channel>`
- Статус: `new`
- Критичность: `<low|medium|high>`
- Затронутые блоки: `<blocks>`
- Исходный комментарий: `<verbatim or short paraphrase>`
- Наблюдаемая проблема: `<problem>`
- Что проверить в данных: `<checks>`
- Первичные гипотезы: `<hypotheses>`
- Предложения по улучшению: `<proposal>`
- Решение / следующая задача: `<PROJECT-XXX or no-code>`
- Ответственный: `<owner>`
- Ссылки / артефакты: `<links>`
````

## Шаблон `OPERATIONS_RUNBOOK.md`

````md
# OPERATIONS_RUNBOOK

Дата обновления: YYYY-MM-DD

## Назначение

Короткая инструкция: как запускать систему, что проверять до запуска, как
проверять результат, где брать стоимость и что делать при сбое.

## Runtime по умолчанию

```text
RUNTIME_PROFILE=<safe_default>
ENVIRONMENT=<dev|staging|production>
EXTERNAL_DELIVERY_ENABLED=false
BUSINESS_DELIVERY_ENABLED=false
API_BUDGET_LIMIT=<value or disabled>
```

Source of truth по режимам: `docs/02_operations/RUNTIME_PROFILES.md`.

## Ежедневный / регулярный порядок

1. Определить цель запуска: `<build/test/report/delivery/etc>`.
2. Проверить active state и backlog.
3. Назвать runtime profile.
4. Проверить env/config без вывода секретов.
5. Проверить budget/API limits.
6. Проверить delivery mode.
7. Запустить только разрешенный command/schedule.
8. Проверить status/readiness/outputs.
9. Заполнить post-run audit.
10. Если найдено отклонение, занести в `OPERATIONAL_FINDINGS.md` и связать с
    backlog.

## Preflight Checklist

- [ ] runtime profile выбран;
- [ ] environment соответствует задаче;
- [ ] secrets не печатаются в логах;
- [ ] budget лимит понятен;
- [ ] external delivery выключена или явно разрешена;
- [ ] production schedule не конфликтует с ручным запуском;
- [ ] rollback path понятен;
- [ ] есть критерий успешности запуска.

## Delivery Modes

| Mode | Назначение | Требует подтверждения |
| --- | --- | --- |
| `preview_only` | собрать без отправки | нет |
| `test_delivery` | отправить в тестовый канал | обычно нет, если канал безопасен |
| `business_delivery` | отправить внешним бизнес-получателям | да |
| `production_schedule` | утвержденное расписание | подтверждается при включении schedule |

## Post-Run Audit

После значимого запуска проверить:

- верхний status: `success | partial | blocked | failed`;
- readiness по группам/объектам;
- built/reused/skipped/error counts;
- rejected/missing artifacts;
- delivery result по каждому каналу;
- cost и price_missing;
- аномалии пользовательского результата;
- warnings/errors в logs/observability;
- что не было случайной business delivery в test mode.

## Incident / Blocker

Если запуск сломался:

1. Не повторять бесконечно без новой гипотезы.
2. Зафиксировать run id, время, profile, scope.
3. Определить impact.
4. Остановить внешние отправки, если есть риск некорректной доставки.
5. Создать finding.
6. Связать finding с backlog task.
7. Если нужен rollback, выполнить только утвержденный rollback path.

## Полезные команды

```bash
<safe status command>
<safe test command>
<safe dry-run command>
```

Команды, требующие подтверждения:

```bash
<production command>
<external delivery command>
<paid API heavy command>
```
````

## Шаблон `RUNTIME_PROFILES.md`

````md
# RUNTIME_PROFILES

Дата обновления: YYYY-MM-DD

## Назначение

Карта разрешенных режимов запуска. Перед pipeline, тестом с внешними API,
production schedule или delivery агент должен явно назвать профиль и проверить
env/config.

## Общие правила

- Не запускать runtime "по памяти".
- Не смешивать результаты разных профилей в одном отчете без явной пометки.
- Simulation/smoke доказывает wiring, но не доказывает качество модели или
  бизнес-результата.
- Production профиль требует явного разрешения или заранее утвержденного
  schedule.

## Профиль 1: local smoke

Назначение: быстрый дешевый smoke без внешней доставки и без дорогих API.

```text
ENVIRONMENT=local
RUNTIME_PROFILE=local_smoke
SIMULATION_ENABLED=true
EXTERNAL_DELIVERY_ENABLED=false
BUSINESS_DELIVERY_ENABLED=false
API_BUDGET_LIMIT=0
```

Когда использовать:

- проверка wiring;
- локальная разработка;
- regression tests.

## Профиль 2: controlled test

Назначение: тест с реальными внешними API в ограниченном scope.

```text
ENVIRONMENT=staging
RUNTIME_PROFILE=controlled_test
SIMULATION_ENABLED=false
EXTERNAL_DELIVERY_ENABLED=false
TEST_DELIVERY_ENABLED=true
API_BUDGET_LIMIT=<small_limit>
```

Когда использовать:

- controlled run;
- проверка качества;
- ручной smoke перед production.

Перед запуском:

- [ ] scope ограничен;
- [ ] budget approved;
- [ ] delivery test-only;
- [ ] rollback не требуется или понятен.

## Профиль 3: production schedule

Назначение: утвержденный регулярный production runtime.

```text
ENVIRONMENT=production
RUNTIME_PROFILE=production_schedule
SIMULATION_ENABLED=false
BUSINESS_DELIVERY_ENABLED=true
API_BUDGET_LIMIT=<approved_limit>
SCHEDULE_ENABLED=true
REVIEW_REQUIRED=<true|false>
```

Когда использовать:

- только для утвержденного schedule;
- только с понятным alerting и rollback;
- только после проверки delivery rules.

## Профиль 4: production manual

Назначение: ручной production запуск вне расписания.

Требует явного подтверждения пользователя в текущей сессии.

```text
ENVIRONMENT=production
RUNTIME_PROFILE=production_manual
BUSINESS_DELIVERY_ENABLED=<explicit>
API_BUDGET_LIMIT=<explicit>
```

## Таблица профилей

| Profile | API spend | External delivery | Business delivery | Кто разрешает |
| --- | --- | --- | --- | --- |
| `local_smoke` | нет | нет | нет | агент |
| `controlled_test` | ограничен | test-only | нет | владелец задачи |
| `production_schedule` | approved | да | по schedule | владелец проекта |
| `production_manual` | explicit | explicit | explicit | пользователь |
````

## Шаблон `POST_RUN_AUDIT.md`

````md
# POST_RUN_AUDIT

Run ID: `<run_id>`
Дата/время: YYYY-MM-DD HH:MM TZ
Агент: `<agent>`
Runtime profile: `<profile>`
Scope: `<what was run>`

## Summary

- Status: `success | partial | blocked | failed`
- Цель запуска: `<goal>`
- Итог: `<short outcome>`
- Production/external delivery: `none | test_only | business_delivery | schedule`

## Preflight

- [ ] runtime profile назван;
- [ ] env/config проверены без секретов;
- [ ] budget проверен;
- [ ] delivery mode проверен;
- [ ] rollback path понятен.

## Results

| Объект/группа | Readiness | Output | Delivery | Notes |
| --- | --- | --- | --- | --- |
| `<item>` | `<ready/partial/blocked>` | `<artifact>` | `<status>` | `<notes>` |

## Counts

| Metric | Value |
| --- | --- |
| total_items | `<n>` |
| built | `<n>` |
| reused | `<n>` |
| skipped | `<n>` |
| failed | `<n>` |

## Cost

| Layer/Service | Cost | Notes |
| --- | --- | --- |
| `<api/service>` | `<amount/currency>` | `<notes>` |
| Total | `<amount/currency>` | `<notes>` |

## Delivery Check

- Test channel: `<status>`;
- Business recipients: `<none/status>`;
- Accidental external delivery: `no | yes`;
- Evidence: `<message id/log/artifact without secrets>`.

## Anomalies

| ID | Severity | Observation | Linked task/finding |
| --- | --- | --- | --- |
| FIND-YYYY-MM-DD-01 | `<low/medium/high>` | `<fact>` | `<PROJECT-XXX>` |

## Follow-Up

- `<next action>`;
- `<owner>`;
- `<deadline if any>`.

## Decision

- [ ] no follow-up needed;
- [ ] add/update backlog task;
- [ ] add/update operational finding;
- [ ] escalate to user;
- [ ] block further production runs until fixed.
````

## Правила делегирования задач агентам

````md
# DELEGATION_PROTOCOL

## Роли

### Controller Agent

Главный агент:

- читает handoff/context/backlog/TZ;
- формирует план;
- делит работу на независимые chunks;
- выдает worker-агентам file scope;
- не теряет общий контекст;
- интегрирует изменения;
- запускает проверки;
- обновляет документы и статусы;
- дает финальный отчет.

### Worker Agent

Worker-агент:

- работает только в своем file scope;
- не меняет production config;
- не запускает внешние отправки;
- не расширяет задачу без согласования;
- возвращает краткий результат, измененные файлы, проверки и риски.

## Обязательный формат задачи worker-агенту

```text
Task ID: PROJECT-XXX
Goal: <specific outcome>
Context files to read:
- <file>
- <file>

Allowed read scope:
- <paths>

Allowed write scope:
- <paths>

Do not change:
- <paths / behaviors>

Production safety:
- no external delivery
- no paid heavy API calls
- no production config changes

Expected output:
- changed files
- tests/checks run
- risks/open questions
```

## Когда делегировать

- Задача параллелится по независимым файлам.
- Нужен аудит отдельной области.
- Нужно подготовить тесты отдельно от реализации.
- Нужно исследовать логи/данные без изменения кода.

## Когда не делегировать

- Нужна единая архитектурная правка.
- File scopes пересекаются и высок риск конфликтов.
- Требуется production decision.
- Контекст слишком неоднозначный и сначала нужно ТЗ.
````

## Правила production safety

````md
# PRODUCTION_SAFETY_RULES

## Запрещено без явного разрешения

- Запускать production pipeline вне утвержденного schedule.
- Отправлять email/SMS/messenger сообщения реальным бизнес-получателям.
- Запускать paid API heavy runs или снимать budget limits.
- Менять production secrets, credentials, webhooks, billing settings.
- Выполнять destructive data operations.
- Делать schema migration в production без rollback plan.
- Включать новую автоматизацию, cron, beat, queue worker или scheduler.

## Разрешено без отдельного подтверждения

- Читать код и документацию.
- Запускать локальные unit tests.
- Запускать dry-run, если он гарантированно не делает внешних отправок и
  платных тяжелых действий.
- Готовить preview/test artifact без business delivery.
- Обновлять документы в рамках задачи.

## Перед production action

Агент должен явно назвать:

- действие;
- scope;
- runtime profile;
- budget/API impact;
- recipients/delivery impact;
- rollback path;
- что будет считаться успехом;
- что будет считаться стоп-сигналом.

## Secrets

- Не печатать токены, пароли, private keys, full connection strings.
- В документации использовать placeholders:
  - `<API_KEY>`;
  - `<WEBHOOK_URL>`;
  - `<USER_EMAIL>`;
  - `<ACCOUNT_ID>`.
- Если секрет случайно попал в лог/файл, остановиться и сообщить пользователю.

## Delivery Gate

Business delivery разрешена только если:

- задача явно требует business delivery или schedule уже утвержден;
- recipient scope понятен;
- preview/review пройден, если он требуется;
- report/output считается user-facing safe;
- нет active blocker в `ACTIVE_WORK_STATE.md`;
- delivery result будет проверен и зафиксирован.
````

## Формат финального отчета агента

````md
## Итог

Коротко: `<что сделано и в каком scope>`.

## Изменено

- `<file>` - `<что изменено>`;
- `<file>` - `<что изменено>`.

## Проверки

- `<command/check>` - `<result>`;
- `<command/check>` - `<result>`.

## Документация и статусы

- Backlog: `<updated/not needed>`;
- Task TZ: `<updated/not needed>`;
- Active state: `<updated/not needed>`;
- Decisions: `<updated/not needed>`;
- Findings/feedback: `<updated/not needed>`.

## Production Safety

- Production pipeline: `not run | run with approval <details>`;
- Business delivery: `not run | run with approval <details>`;
- Paid/API budget actions: `not run | run with approval <details>`;
- Secrets/private data: `not exposed`.

## Остаточные риски

- `<risk or none>`;

## Рекомендуемый следующий шаг

`<one concrete next step>`
````

## Как развернуть в новом проекте

1. Создать структуру папок из раздела "Рекомендуемая структура".
2. Скопировать шаблон `AGENTS.md` в корень проекта и заменить placeholders.
3. Создать `ACTIVE_WORK_STATE.md` и `CONTEXT_INDEX.md`.
4. Создать `ROADMAP.md`, `DECISIONS.md`, `PROJECT_BACKLOG.md`.
5. Для первой задачи создать `docs/04_tasks/PROJECT-001_TASK_TZ.md`.
6. Добавить runbook, runtime profiles и production safety rules до любых
   production/API/delivery запусков.
7. После каждого значимого запуска заполнять post-run audit.
8. После каждого изменения статуса обновлять handoff/backlog, чтобы следующий
   агент мог войти без скрытого контекста.

## Минимальный стартовый набор

Если нужно начать быстро, достаточно создать:

```text
AGENTS.md
README.md
docs/00_handoff/ACTIVE_WORK_STATE.md
docs/00_handoff/CONTEXT_INDEX.md
docs/01_strategy/ROADMAP.md
docs/01_strategy/DECISIONS.md
docs/02_operations/OPERATIONS_RUNBOOK.md
docs/02_operations/RUNTIME_PROFILES.md
docs/03_backlog/PROJECT_BACKLOG.md
docs/04_tasks/TASK_TEMPLATE.md
docs/06_agent_instructions/PRODUCTION_SAFETY_RULES.md
```

Остальные файлы можно добавить по мере появления feedback, метрик,
production-операций и отчетов.
