# Активное состояние работ

Дата обновления: 2026-06-04

Статус: `completed`

## Назначение

Короткая оперативная карточка текущего этапа. История проекта хранится в
`docs/PROGRESS.md`, решения - в `docs/DECISIONS.md`, режимы запуска - в
`docs/RUNTIME_PROFILES.md`.

Перед началом новой сессии открыть:

```text
docs/ACTIVE_WORK_STATE.md
docs/CONTEXT_INDEX.md
docs/PILOT_OPERATIONS.md
docs/RUNTIME_PROFILES.md
docs/MVP1_PILOT_METRICS_MEASUREMENTS.md
docs/PROGRESS.md
docs/DECISIONS.md
```

Если статус станет `waiting_for_user`, агент не должен продолжать реализацию до
ответа пользователя.

## Текущий этап

Тема: MVP-1 pilot operations.

Этап правок механизма закрыт. Начинается пилотирование: ежедневные прогоны,
замеры KPI, контроль стоимости и доставка отчетов после operator review.

Актуальный runtime default:

```text
AI_LLM_EXECUTION_MODE=openai_compatible
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SIMULATION_ENABLED=false
AI_LLM2_ANALYSIS_MODE=layered
AI_LLM2_INPUT_PROFILE=compact
LLM3_ENABLED=true
```

Source of truth по режимам: `docs/RUNTIME_PROFILES.md`.

## Последняя безопасная точка

Последний закрытый пакет:

- локальный commit `13995a0 Polish manager daily report delivery`;
- ветка `feature/llm2-block-ready-v15`;
- новых веток, runtime-профилей или delivery-режимов для последних исправлений
  не создавалось;
- использован существующий режим business delivery: `business_email_only`.

Фактическая business-email доставка отчетов за `2026-06-03`:

- Алишер: `g.alisher@dogovor24.kz`, CC `sales@dogovor24.kz`,
  `email_status=delivered`;
- Тимур: `zh.timur@dogovor24.kz`, CC `sales@dogovor24.kz`,
  `email_status=delivered`;
- Толеген: `zh.tolegen@dogovor24.kz`, CC `sales@dogovor24.kz`,
  `email_status=delivered`.

Runner мог возвращать верхний статус `partial` из-за исторических rejected
reuse-записей по mismatch версии анализа; по трем отчетам delivery status был
`delivered`.

## Пилотный порядок

1. Перед запуском проверить профиль в `docs/RUNTIME_PROFILES.md`.
2. Для полного дневного прогона использовать compact default, если пользователь
   не выбрал иной профиль.
3. Не отправлять менеджерам бизнес-письма без operator review или явного
   указания пользователя.
4. После каждого полного дневного прогона заполнить KPI и стоимость в
   `docs/MVP1_PILOT_METRICS_MEASUREMENTS.md`.
5. Если нужны расходы, читать `observability.ai_costs` и отвечать в USDT.

## Актуальные документы

- `docs/PILOT_OPERATIONS.md` - ежедневный порядок пилота.
- `docs/MVP1_PILOT_METRICS_MEASUREMENTS.md` - KPI, GO/NO-GO и экономика.
- `docs/RUNTIME_PROFILES.md` - режимы запуска и subagent/API границы.
- `docs/AI_PROVIDER_ROUTING.md` - provider pools и env.
- `docs/MANUAL_REPORTING_PILOT.md` - manual reporting pipeline.
- `docs/MANAGER_REPORT_FEEDBACK.md` - журнал обратной связи по отчетам.

## Архив

Исторические планы, длинные аудиты, недельные транскрипты и временные рабочие
файлы перенесены в `docs/archive/`. Они нужны только для расследований и не
являются текущей точкой входа в пилот.
