# CONTEXT_INDEX

## Назначение
Этот файл задаёт быстрый и стабильный порядок входа в задачу для ИИ-кодера.
Использовать как стартовую точку в новой сессии.

## Первое действие при восстановлении сессии

Если чат оборвался, история не подгрузилась или работа продолжается в новом чате,
сначала открыть:

```text
/root/ai-sales-analyzer/docs/ACTIVE_WORK_STATE.md
/root/ai-sales-analyzer/docs/RUNTIME_PROFILES.md
```

`ACTIVE_WORK_STATE.md` является короткой оперативной карточкой текущего этапа, а
не заменой общего прогресса. История проекта и завершенные шаги фиксируются в
`docs/PROGRESS.md`, решения — в `docs/DECISIONS.md`. В active-state карточке
фиксируются только текущий статус, последняя безопасная точка восстановления,
pending approval gates и то, что нужно от пользователя. Если там указан
`status: waiting_for_user`, агент не должен продолжать реализацию до ответа
пользователя.

## Текущая рабочая рамка на 2026-06-03

### Актуализация 2026-06-03: audit/fix pass закрыт

Текущий pass по аудиту и исправлениям механизма принят пользователем после
визуальной проверки отчета. Следующий агент должен считать эти изменения
базовой точкой, а новый прогон начинать только как отдельную задачу.

Что важно открыть перед новым тестом:

```text
/root/ai-sales-analyzer/docs/ACTIVE_WORK_STATE.md
/root/ai-sales-analyzer/docs/PROGRESS.md
/root/ai-sales-analyzer/docs/DECISIONS.md
/root/ai-sales-analyzer/docs/RUNTIME_PROFILES.md
/root/ai-sales-analyzer/TMP_REPORT_LAYER_AUDIT.md
/root/ai-sales-analyzer/TMP_LLM2_INPUT_OPTIMIZATION_TASKS.md
/root/ai-sales-analyzer/TMP_LLM2_SEMANTIC_DEFECT_REGISTRY.md
```

Короткий итог закрытого pass:

- `LLM2A/LLM2B/common prompt` переработаны для более компактного input без
  provider-specific условий;
- `TMP_LLM2_SEMANTIC_DEFECT_REGISTRY.md` является новым рабочим документом для
  формирования предложений по системным правилам и классам смысловых дефектов;
- Report Layer audit tasks `RL-T2/RL-T6/RL-T7/RL-T8` внедрены;
- `Все звонки дня -> Суть звонка` теперь использует rich context и не режется
  прежним коротким лимитом;
- Тимур `2026-06-01` проверен через OpenAI-compatible preview, но полный
  manager-facing отчет по дню не считается готовым из-за неполного coverage.

### Актуализация 2026-06-02: LLM2 compact input и semantic defect registry

Текущая активная работа сместилась к оптимизации и калибровке `LLM-2`:

- compact input profile для `LLM2A/B/C/D`;
- фактическое измерение size/tokens/time/repair по pass-ам;
- сбор смысловых дефектов LLM2 в отдельный registry;
- вывод системных правил вместо точечных prompt-хаков.

Дополнительные текущие рабочие файлы:

```text
/root/ai-sales-analyzer/TMP_LLM2_INPUT_OPTIMIZATION_TASKS.md
/root/ai-sales-analyzer/TMP_LLM2_SEMANTIC_DEFECT_REGISTRY.md
/root/ai-sales-analyzer/docs/KIMI_K26_TRIAL_HANDOFF_2026-06-02.md
```

`TMP_LLM2_SEMANTIC_DEFECT_REGISTRY.md` фиксирует смысловые классы проблем
вроде false callback/follow-up из фразы "можете обращаться", утечки
recommendation в factual follow_up, score inflation и ownership
`LLM2B`/`LLM2D`/adapter. Следующий агент должен смотреть туда перед новыми
точечными исправлениями качества `LLM-2`.

`docs/KIMI_K26_TRIAL_HANDOFF_2026-06-02.md` фиксирует итог Kimi K2.6 trial:
`LLM2` и `LLM3` маршрутизируются на `kimi-k2.6`, но текущий layered `LLM2`
contract для K2.6 пока blocked из-за невалидного/пустого JSON, медленных
ответов и пустых `stage_scores`. Не запускать полный день K2.6 без отдельной
contract simplification задачи.

Сейчас активная задача: возврат к исходной точке аудита всего механизма анализа,
а не продолжение локальных Gate 5 block fixes. Проверяется цепочка
`LLM-1 -> LLM-2 -> validators/normalizers -> report evidence registry -> report
block router -> Report Layer -> LLM-3 -> payload/render/PDF/Telegram`.

Работа остается в автономном режиме исполнения: главный агент координирует,
implementation agents правят ограниченные участки, а отдельные simulation agents
проверяют `LLM-1`, `LLM-2` и `LLM-3` без правки кода.

Контрольные даты: `2026-05-18`, `2026-05-19`, `2026-05-20`.

Текущий product decision:

- техническая сборка и доставка отчетов в целом работали;
- блокер пилота — нестабильное качество анализа, evidence и подкрепления claims;
- утвержденная граница `LLM-2`: смысл звонка, факты, оценка, gaps,
  recommendations и универсальный evidence pack;
- `LLM-2` не должен быть report-template engine;
- LLM-калибровка выполняется через `subagent_runtime`, не через реальные LLM;
- финальная проверка — реальные отчеты до PDF/Telegram;
- `LLM-1` закрепляется/переносится в последнюю очередь.
- Gate 5 block-by-block movement остановлен до approval target mechanism;
- локальные Block 2 правки после пользовательского комментария не считать
  принятой целевой архитектурой.

Текущие входные документы:

1. [docs/ACTIVE_WORK_STATE.md](docs/ACTIVE_WORK_STATE.md)
2. [docs/RUNTIME_PROFILES.md](docs/RUNTIME_PROFILES.md) — runtime-профили: real API, max quality, hybrid Codex-subagents, full subagent, local simulation
3. [docs/GATE5_AUTONOMOUS_EXECUTION_STATUS.md](docs/GATE5_AUTONOMOUS_EXECUTION_STATUS.md) — task-status отчет по блокам и агентам
4. [docs/LLM2_ARCHITECTURE_AUDIT_AND_TARGET_MODEL.md](docs/LLM2_ARCHITECTURE_AUDIT_AND_TARGET_MODEL.md) — текущая рабочая карта правок механизма
5. [docs/BUSINESS_READY_REPORT_PACK_TASKS.md](docs/BUSINESS_READY_REPORT_PACK_TASKS.md) — backlog/task breakdown Вехи 6.5
6. [docs/REPORT_LAYER_LLM3_STRUCTURE_AUDIT_2026-05-27.md](docs/REPORT_LAYER_LLM3_STRUCTURE_AUDIT_2026-05-27.md) — вспомогательный артефакт, не основной source of truth
7. [docs/TMP_LLM_NODES_ARTIFACTS_MAP.md](docs/TMP_LLM_NODES_ARTIFACTS_MAP.md)
8. [docs/LLM_SUBAGENT_TESTING_MODE.md](docs/LLM_SUBAGENT_TESTING_MODE.md)
9. [docs/DECISIONS.md](docs/DECISIONS.md)
10. [docs/PROGRESS.md](docs/PROGRESS.md)

## Историческая рабочая рамка на 2026-05-21

Сейчас активная задача относится к `Веха 6.5 — Business-ready Report Pack` и ветке
`LLM2 v15 semantic/report-block quality stabilization`.

Текущий runtime-факт: свежие LLM2 анализы используют
`edo_sales_mvp1_call_analysis_v15_block_ready`, а финальный `manager_daily`
собирается из persisted calls/analyses через ready-only/no-delivery preview для
проверки качества до доставки бизнесу.

Текущий product decision: смысловые блоки отчета должны быть менее зажаты
жесткими micro-field/table структурами. Строгими остаются call identity,
report-day scope, evidence grounding, counter-evidence gates, final status
selection and no invented facts. Свободнее стали только manager-facing
composition and rendering inside already verified blocks.

Последний закрепленный changeset: `73cb5cf Improve manager daily semantic report
blocks` на `feature/llm2-block-ready-v15`. Он закрыл SFB-1..SFB-5 и role-boundary
pass for `Разбор звонка` / `Голос клиента`.

Для этой задачи не считать `MANUAL_OUTPUT_VALIDATION_SPEC.md` текущим stage-specific source по умолчанию. Он остаётся историческим источником для старой single-call validation. Текущий вход для LLM2/report-quality задач:

1. [docs/PROMPTS_GUIDE.md](docs/PROMPTS_GUIDE.md)
2. [docs/REPORT_EVIDENCE_CONTRACT.md](docs/REPORT_EVIDENCE_CONTRACT.md)
3. [docs/MANAGER_DAILY_SELECTION_MODEL.md](docs/MANAGER_DAILY_SELECTION_MODEL.md)
4. [docs/BUSINESS_READY_REPORT_PACK_TASKS.md](docs/BUSINESS_READY_REPORT_PACK_TASKS.md)
5. [docs/MANAGER_REPORT_FEEDBACK.md](docs/MANAGER_REPORT_FEEDBACK.md)
6. [docs/MANAGER_DAILY_REPORT_AUDIT.md](docs/MANAGER_DAILY_REPORT_AUDIT.md)
7. [docs/PROGRESS.md](docs/PROGRESS.md)

Temporary plans such as `TMP_SITUATION_DAY_COMPOSER_TZ.md`,
`docs/TEMP_LLM2_BLOCK_READY_V15_PLAN.md`, and
`docs/TEMP_LLM2_SEMANTIC_ANALYSIS_PLAN.md` are historical implementation notes
unless a current task explicitly reopens them.

Текущий baseline для качества: persisted calls/analyses -> ready-only/no-delivery
`manager_daily` payload/preview. Не использовать отсутствие сохранённых
PDF/drafts как blocker для LLM2 quality comparison и не включать PDF persistence
repair в этот changeset без отдельного решения.

`docs/LLM2_MANAGER_DAILY_INSTRUCTIONS_MAP.md` обновлен как map текущих LLM2
инструкций, но итоговый manager-facing текст по ряду блоков теперь делает LLM3
composer/report layer. LLM2 остается per-call semantic evidence producer, not
final report author.

## Обязательный порядок чтения

### 0. [docs/ACTIVE_WORK_STATE.md](docs/ACTIVE_WORK_STATE.md)
Зачем читать:
- восстановить текущий статус после обрыва связи или нового чата;
- увидеть, чего ждем от пользователя;
- не продолжать реализацию, если работа стоит на approval gate;
- понять последнюю безопасную точку восстановления.

### 1. [docs/RUNTIME_PROFILES.md](docs/RUNTIME_PROFILES.md)
Читать перед любым запуском STT/LLM/report pipeline или изменением runtime env.

Зачем читать:
- выбрать правильный профиль запуска: `cost_optimized`, `max_quality`,
  `hybrid API + Codex-subagents`, `full Codex-subagent runtime` или
  `local simulation`;
- не перепутать реальные Codex-subagents с deterministic contract runner;
- явно проверить, какие слои идут через API, а какие через subagent runtime.

### 2. [docs/CODER_WORKING_RULES.md](docs/CODER_WORKING_RULES.md)
Зачем читать:
- понять постоянные правила работы кодера в этом проекте;
- не дублировать universal policies из task-промптов;
- сразу увидеть порядок входа в задачу, scope control, verification-first и правила обновления docs.

### 3. [docs/CONCEPT_MVP1.md](docs/CONCEPT_MVP1.md)
Зачем читать:
- понять продуктовую рамку MVP-1;
- увидеть, что входит в MVP-1 и что не входит;
- не расширять scope за пределы подтверждённого этапа.

### 4. [docs/ROADMAP.md](docs/ROADMAP.md)
Зачем читать:
- понять, в какой вехе проект находится сейчас;
- не перепутать Manual Output Validation с automation readiness;
- увидеть следующий допустимый переход.

### 5. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
Зачем читать:
- понять pipeline и архитектурные инварианты;
- не ломать determinism, contract stability и platform rules;
- увидеть, что считается runtime behavior, а что operating layer.

### 6. [docs/DECISIONS.md](docs/DECISIONS.md)
Зачем читать:
- понять уже принятые решения и ограничения;
- не принимать повторно уже закрытые вопросы;
- видеть, какие изменения требуют явного ADR/update.

### 7. [docs/PROGRESS.md](docs/PROGRESS.md)
Зачем читать:
- понять фактический статус и последний подтверждённый шаг;
- увидеть, что уже сделано, что в работе и что остаётся открытым;
- не возвращаться к уже закрытым вопросам без причины.

### 8. [docs/MANUAL_OUTPUT_VALIDATION_SPEC.md](docs/MANUAL_OUTPUT_VALIDATION_SPEC.md)
Читать по умолчанию только для исторической Manual Output Validation / single-call validation задачи. Для текущей LLM2 v15 report-quality задачи использовать рабочую рамку выше.

Зачем читать:
- понять stage-specific policies для Manual Output Validation;
- использовать acceptance criteria, defect taxonomy и exit criteria без повторения в task-промпте;
- не уходить в automation readiness без явного подтверждения.

### 9. [docs/PROMPTS_GUIDE.md](docs/PROMPTS_GUIDE.md)
Читать, если задача затрагивает prompt assets, prompt docs или prompt behavior.

Зачем читать:
- понять, какие prompt policies являются постоянными;
- понять, что должно жить в source prompt assets / docs, а не в task-промпте;
- не дублировать language/output/schema constraints в каждом новом запросе.

### 10. [docs/MANUAL_REPORTING_PILOT.md](docs/MANUAL_REPORTING_PILOT.md)
Читать, если задача относится к ручному запуску отчётности, report presets, reuse logic, report-composer scope или delivery rules для reporting pilot.

Зачем читать:
- понять границы `Manual Reporting Pilot`;
- не перепутать ручной reporting pilot с automation readiness;
- видеть agreed launch parameters, presets, delivery rules и reuse/recompute policy.

### 11. [docs/MANAGER_DAILY_SELECTION_MODEL.md](docs/MANAGER_DAILY_SELECTION_MODEL.md)
Читать, если задача затрагивает отбор звонков для `manager_daily`, report contract, слои данных, rolling window или счётчики / причины исключения.

Зачем читать:
- понять canonical разграничение `raw_calls` / `meaningful_calls` / `coaching_core`;
- видеть, что именно должно попадать в список звонков дня vs коучинговые блоки;
- понять rolling window rule и transparency requirements;
- получить перечень bounded implementation tasks для реализации этого contract.

### 12. [docs/REPORT_EVIDENCE_CONTRACT.md](docs/REPORT_EVIDENCE_CONTRACT.md)
Читать, если задача затрагивает LLM2 report-ready evidence, `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, prompt update plan или будущую интеграцию `report_evidence`.

Зачем читать:
- понять target architecture `LLM2 -> report_evidence -> reporting layer`;
- увидеть additive JSON contract и validation rules;
- не превращать reporting layer в semantic analyzer;
- понять backward compatibility с Step 8W fallback.

### 13. [docs/MANAGER_REPORT_FEEDBACK.md](docs/MANAGER_REPORT_FEEDBACK.md)
Читать, если задача основана на комментариях менеджеров/РОПа по фактически полученным отчетам или если нужно планировать улучшения качества report blocks по обратной связи.

Зачем читать:
- сохранить точную формулировку обратной связи от участников;
- отделить факт жалобы от наших гипотез и будущих code changes;
- увидеть приоритетные проверки по `ДЕНЬГИ НА СТОЛЕ`, договоренностям, полноте звонков, объему отчета и спорным coaching-выводам;
- не чинить отчет вручную, а вести проблему к проверяемому upstream-исправлению.

### 14. [docs/MANAGER_DAILY_REPORT_AUDIT.md](docs/MANAGER_DAILY_REPORT_AUDIT.md)
Читать, если задача затрагивает оформление, порядок блоков, формулировки, объем PDF/email или product-shape ежедневного отчета `manager_daily`.

Зачем читать:
- увидеть текущую карту проблем ежедневного отчета как продукта;
- понять приоритеты `P0/P1/P2` по доверию, объему, дублям и оформлению;
- не возвращать рискованные блоки вроде `ДЕНЬГИ НА СТОЛЕ` без evidence/CRM-ready поведения;
- сверять будущие правки с целевой структурой 4-5 страниц и honest coverage.

### 15. [docs/MANAGER_DAILY_REPORT_P2_FIX_PLAN.md](docs/MANAGER_DAILY_REPORT_P2_FIX_PLAN.md)
Читать перед внедрением P2 после human-review тестового отчета Толегена за `2026-05-21` и новых прогонов за `2026-05-22`.

Зачем читать:
- понять уточненные P2.0/P2.1 проблемы, найденные уже на живом PDF: `БАЛЛЫ ПО ЭТАПАМ` считались по слишком узкому `coaching_core`, а `Ситуация дня` / `Разбор звонка` могли исчезать при наличии фрагментов;
- закрепить требование честного охвата для stage scores: `N разобранных звонков из M содержательных`;
- увидеть, что P2.0 уже внедрен 2026-05-25, а P2.1 остается отдельной следующей задачей;
- учесть новый открытый P2.5: блок follow-up интересов не должен называться строго `завтра`, если срок в разговоре другой;
- учесть новый открытый P2.6 по отчетам Тимура за `2026-05-22`: rolling-window counts, неверный claim про следующий шаг, raw labels `Контекст` / `Сторона`, единая диаризация evidence;
- отличить проблему низкого data coverage от проблемы selection/gating;
- использовать acceptance criteria для `Другие заметные моменты`, scene-scoped тона и первой страницы.

### 16. `docs/mvp1_sources/`
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
- **LLM2 report-ready evidence contract:** [docs/REPORT_EVIDENCE_CONTRACT.md](docs/REPORT_EVIDENCE_CONTRACT.md)
- Prompt policies и prompt/task split: [docs/PROMPTS_GUIDE.md](docs/PROMPTS_GUIDE.md)
- Product-аудит ежедневного отчета: [docs/MANAGER_DAILY_REPORT_AUDIT.md](docs/MANAGER_DAILY_REPORT_AUDIT.md)
- Короткий шаблон будущих task-промптов: [docs/TASK_PROMPT_TEMPLATE.md](docs/TASK_PROMPT_TEMPLATE.md)

## Как использовать индекс в новой сессии
В начале новой задачи ИИ должен:
1. Прочитать документы в порядке выше.
2. Зафиксировать текущий этап, допустимый scope и недопустимые расширения.
3. Проверить, относится ли задача к stage-specific policy.
4. Только после этого переходить к verification, analysis и изменениям.
