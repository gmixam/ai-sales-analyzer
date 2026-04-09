# DEV_ONBOARDING

## Назначение
Этот документ нужен для быстрого и безопасного входа нового разработчика в проект без потери текущего контекста.

Он не заменяет source-of-truth docs, а даёт короткий путь:
- что за проект;
- где реальные границы scope;
- как поднять окружение;
- чем проверять базовую работоспособность;
- как не сломать текущую фазу проекта.

## Что это за проект

`ai-sales-analyzer` — внутренний MVP-1 pipeline для анализа звонков отдела продаж.

Текущая operating shape:
- project находится на этапе `4.5 Manual Reporting Pilot`
- ручной запуск анализа и отчётности уже реализован
- подтверждённые preset’ы:
  - `manager_daily`
  - `rop_weekly`

Current runtime split:
- `manager_daily` — source-aware manual path
- `rop_weekly` — persisted-only aggregation

## С чего входить в контекст

Обязательная стартовая точка:
1. [docs/CONTEXT_INDEX.md](docs/CONTEXT_INDEX.md)

Дальше обязательно:
1. [docs/CODER_WORKING_RULES.md](docs/CODER_WORKING_RULES.md)
1. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
1. [docs/PROGRESS.md](docs/PROGRESS.md)
1. [docs/MANUAL_REPORTING_PILOT.md](docs/MANUAL_REPORTING_PILOT.md)

Если задача затрагивает AI routing:
1. [docs/AI_PROVIDER_ROUTING.md](docs/AI_PROVIDER_ROUTING.md)

Если задача затрагивает analyzer contract:
1. [docs/mvp1_sources/MVP1_CALL_ANALYSIS_CONTRACT_v1.md](docs/mvp1_sources/MVP1_CALL_ANALYSIS_CONTRACT_v1.md)
1. [docs/mvp1_sources/MVP1_CHECKLIST_DEFINITION_v1.md](docs/mvp1_sources/MVP1_CHECKLIST_DEFINITION_v1.md)

## Текущий roadmap status

Текущая веха:
- `4.5 Manual Reporting Pilot`

Что уже подтверждено:
- manual operator UI и API path работают
- `manager_daily` readiness logic уже встроена
- stricter reuse/version checks уже встроены
- semantic-empty analysis handling уже встроен
- Git baseline уже создан

Что остаётся открытым:
- `closed_with_known_verification_gap` ещё не снят

Confirmed residual blocker:
- это operational issue, а не product/runtime bug
- billable quota не восстановлена для:
  - `OPENAI_API_KEY_STT_MAIN`
  - `OPENAI_API_KEY_LLM1_MAIN`

Важно:
- этот gap нельзя "попутно закрывать" в unrelated задачах
- если задача не про operational quota restore и final rerun, этот gap просто явно учитывается как открытый

## In Scope / Out of Scope

Сейчас обычно in scope:
- bounded fixes внутри Manual Reporting Pilot
- docs hardening
- operator workflow clarity
- repo hygiene
- bounded verification

Сейчас обычно out of scope:
- scheduler
- retries
- beat
- automation expansion
- broad analyzer redesign
- contract redesign
- hidden refactor "заодно"

Если задача не просит иного, нельзя:
- менять approved analyzer contract
- расширять `rop_weekly` в source/build path
- размывать preset split
- маскировать открытый verification gap

## Локальный запуск

### 1. Подготовить env

```bash
cp .env.example .env
```

Что важно знать:
- `.env.example` даёт безопасный стартовый шаблон, но не production-ready secrets
- для реального routed AI/runtime path понадобятся актуальные значения для OpenAI routing и test-delivery env vars
- не коммитить `.env`

### 2. Поднять стек

```bash
make up
make status
```

### 3. Проверить health

```bash
curl -s http://localhost:8081/health
```

### 4. Открыть operator UI

```text
http://localhost:8000/pipeline/calls/report-ui
```

### 5. Зайти в контейнер API при необходимости

```bash
make shell
```

## Базовые команды для проверки

Миграции:

```bash
make migrate
```

Тесты:

```bash
docker compose run --rm api python -m unittest tests.test_ai_provider_routing tests.test_manual_reporting
```

Логи:

```bash
make logs
```

Postgres shell:

```bash
make db-shell
```

## Практические entrypoints

Operator UI:
- `/pipeline/calls/report-ui`

Operator API:
- `/pipeline/calls/report-run`

Health:
- `/health`

Manual report runner:

```bash
docker compose run --rm api python -m app.agents.calls.manual_reporting_runner --help
```

## Git workflow

Текущее состояние:
- локальный baseline commit уже создан
- основная ветка: `main`
- remote может быть ещё не настроен или не авторизован на конкретной машине

Базовые правила:
- не коммитить secrets
- не коммитить `.env`, локальные TLS keys, caches и runtime artifacts
- не делать force-push / history rewrite без явного согласования
- перед пушем смотреть `git status`

Рекомендуемый минимальный flow:
1. Синхронизировать контекст по docs.
2. Сделать bounded change.
3. Прогнать ровно ту verification, которая нужна по задаче.
4. Обновить docs, если изменился standing understanding или фактический статус.
5. Только потом коммитить.

## Что не надо делать "по пути"

Не надо без отдельной задачи:
- пытаться закрыть quota blocker кодом
- менять operating model Manual Reporting Pilot
- включать scheduler/retries/beat
- менять analyzer contract
- запускать broad cleanup/refactor только потому, что что-то выглядит устаревшим

## Где фиксировать изменения понимания

- [docs/PROGRESS.md](docs/PROGRESS.md) — если меняется фактический статус, рабочий фокус или открытые блокеры
- [docs/DECISIONS.md](docs/DECISIONS.md) — если принимается новое standing rule
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — если меняется standing runtime/data-flow explanation
- [docs/MANUAL_REPORTING_PILOT.md](docs/MANUAL_REPORTING_PILOT.md) — если меняется operating model reporting pilot
