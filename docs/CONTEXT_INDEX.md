# CONTEXT_INDEX

## Назначение

Быстрый порядок входа в проект для нового ИИ-агента или инженера.

Текущий этап: MVP-1 pilot operations после закрытия report-layer/LLM2
audit-fix pass.

## Обязательный порядок чтения

1. [docs/ACTIVE_WORK_STATE.md](ACTIVE_WORK_STATE.md)
   - текущий статус, последняя безопасная точка, что можно запускать дальше.
2. [docs/PILOT_OPERATIONS.md](PILOT_OPERATIONS.md)
   - ежедневный порядок пилотирования, проверки, delivery gate.
3. [docs/PILOT_BACKLOG.md](PILOT_BACKLOG.md)
   - актуальная очередь задач пилота, включая Bitrix sync, расписание, РОП
     delivery и возврат скрытых блоков.
4. [docs/RUNTIME_PROFILES.md](RUNTIME_PROFILES.md)
   - какой runtime-профиль использовать и как не перепутать API/subagents.
5. [docs/MVP1_PILOT_METRICS_MEASUREMENTS.md](MVP1_PILOT_METRICS_MEASUREMENTS.md)
   - KPI, GO/NO-GO, экономика прогона и правила заполнения замеров.
6. [docs/AI_PROVIDER_ROUTING.md](AI_PROVIDER_ROUTING.md)
   - provider pools, модели, env и route-plan checks.
7. [docs/MANUAL_REPORTING_PILOT.md](MANUAL_REPORTING_PILOT.md)
   - manual reporting pipeline и режимы запуска отчетов.
8. [docs/PROGRESS.md](PROGRESS.md)
   - хронология выполненных этапов.
9. [docs/DECISIONS.md](DECISIONS.md)
   - архитектурные и операционные решения.

Если задача связана с качеством ежедневного отчета, дополнительно открыть:

- [docs/MANAGER_REPORT_FEEDBACK.md](MANAGER_REPORT_FEEDBACK.md)
- [docs/MANAGER_DAILY_CALL_FEEDBACK_MINI_TZ.md](MANAGER_DAILY_CALL_FEEDBACK_MINI_TZ.md)
- [docs/LLM2_STATUS_DETAILS_MINI_TZ.md](LLM2_STATUS_DETAILS_MINI_TZ.md)
- [docs/LLM_ONLY_SEMANTIC_REPORTING_TZ.md](LLM_ONLY_SEMANTIC_REPORTING_TZ.md)
- [docs/MANAGER_DAILY_SELECTION_MODEL.md](MANAGER_DAILY_SELECTION_MODEL.md)
- [docs/REPORT_EVIDENCE_CONTRACT.md](REPORT_EVIDENCE_CONTRACT.md)
- [docs/LLM2_MANAGER_DAILY_INSTRUCTIONS_MAP.md](LLM2_MANAGER_DAILY_INSTRUCTIONS_MAP.md)

Если задача связана с Kimi/Moonshot, дополнительно открыть:

- [docs/KIMI_K26_TRIAL_HANDOFF_2026-06-02.md](KIMI_K26_TRIAL_HANDOFF_2026-06-02.md)

## Текущие правила пилота

- Compact LLM2 input является runtime default: `AI_LLM2_INPUT_PROFILE=compact`.
- Текущие задачи пилота ведутся в `docs/PILOT_BACKLOG.md`.
- Business delivery менеджерам запускать только после operator review или
  явного указания пользователя.
- После каждого полного дневного прогона фиксировать KPI и стоимость в USDT.
- Комментарии менеджеров/РОП сначала фиксировать в
  `docs/MANAGER_REPORT_FEEDBACK.md`; системные проблемы связывать с
  `docs/PILOT_BACKLOG.md`.
- `review_packages/` и `core/review_packages/` являются локальными runtime
  артефактами, а не source of truth.
- Исторические временные планы и длинные аудиты лежат в `docs/archive/`.

## Не считать актуальным входом

- Исторические файлы в `docs/archive/`.
- Старые verification PDFs/DOCX/logs и локальные run packages.
- Устаревшие gate/status документы, если они противоречат `ACTIVE_WORK_STATE`,
  `PILOT_OPERATIONS`, `PROGRESS` или `DECISIONS`.

## Перед запуском pipeline

1. Назвать runtime-профиль из `RUNTIME_PROFILES`.
2. Проверить route-plan/env в контейнере.
3. Убедиться, что delivery mode соответствует задаче:
   - operator preview/test: Telegram test only;
   - business delivery: только после review/явного указания.
4. После прогона сохранить/прочитать `observability.ai_costs` и KPI.
