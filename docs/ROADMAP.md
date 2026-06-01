# ROADMAP

## Назначение документа
Этот документ нужен как короткая карта движения проекта.
Он не заменяет концепт, архитектуру или progress, а собирает в одном месте:
- основные вехи;
- смысл каждой вехи;
- что должно быть на выходе;
- критерий готовности для перехода дальше;
- где проект находится сейчас.

## Веха 1. Foundation
### Смысл
Поднять техническую основу проекта и подготовить скелет pipeline.

### Что должно быть на выходе
- VPS / runtime среда
- Docker Compose
- PostgreSQL schema
- базовая структура агента calls
- extractor TAR → MP3
- базовые operational docs

### Критерий готовности
Среда поднимается стабильно, первый транскрипт или заготовка под него может быть сохранена в БД.

---

## Веха 2. Source Integration & STT
### Смысл
Научиться получать реальные звонки и превращать их в текст.

### Что должно быть на выходе
- интеграция с OnlinePBX API
- intake новых звонков
- Bitrix24 read-only для отбора и маппинга менеджеров
- фильтрация звонков по бизнес-правилам
- извлечение аудио
- AssemblyAI STT
- transcript storage в interactions / связанных сущностях

### Критерий готовности
Система способна взять звонок из источника, привязать его к нужному менеджеру, получить transcript и сохранить его без ручного вмешательства.

---

## Веха 3. Analyzer Ready
### Смысл
Научиться делать корректный AI-анализ звонка по утверждённым MVP-1 правилам.

### Что должно быть на выходе
- checklist definition встроен в analyzer flow
- approved contract встроен
- LLM-1 / LLM-2 логика работает в рамках CallsAnalyzer
- score_by_stage и criteria_results валидируются
- невалидные stage/criterion коды режутся
- AnalysisResult wrapper остаётся совместимым

### Критерий готовности
Один тестовый звонок проходит через analyze_call() и возвращает корректный JSON по approved contract.

---

## Веха 3.5. Manual Live Validation
### Смысл
Проверить первый живой end-to-end flow на реальном звонке вручную до полной automation readiness.

### Что должно быть на выходе
- manual trigger через CLI и/или manual API endpoint
- реальный OnlinePBX как live source
- корректная endpoint normalization / override config для OnlinePBX live intake
- временный pilot mode с explicit whitelist / test target config
- extractor + temporary Whisper STT + analyzer + persistence собраны в один ручной прогон
- delivery notification уходит только в test Telegram / Email
- Bitrix24 и scheduler для этого шага не требуются

### Критерий готовности
Пользователь может вручную запустить pipeline на одном реальном кейсе и увидеть сохранённый analysis result и test delivery output.

---

## Веха 3.6. Manual Output Validation
### Смысл
Вручную подтвердить качество и пригодность материалов, которые pipeline уже умеет формировать в ручном режиме.

### Что должно быть на выходе
- validation inventory фактически существующих output artifacts
- acceptance criteria для transcript, analysis, scoring, agreements, compact manager card и Telegram delivery
- validation log по найденным проблемам
- подтверждение consistency между transcript -> analysis -> delivery
- configurable manual controls для cost-aware ручной проверки

### Критерий готовности
Ручная выборка подтверждает, что output materials структурно корректны, читаемы, business-useful и не содержат критичных пропусков или явных галлюцинаций.

---

## Веха 4. Delivery Ready
### Смысл
Довести результат анализа до пользователя в понятной и полезной форме.

### Что должно быть на выходе
- delivery.py
- карточка звонка для менеджера
- канал Email
- канал Telegram
- базовый delivery flow без ручной сборки отчёта

### Критерий готовности
Карточка звонка по реальному звонку доставляется менеджеру или в тестовый канал в ожидаемом формате.

---

## Веха 4.5. Manual Reporting Pilot
### Смысл
Вручную запускать source-aware parameterized report run без перехода в automation readiness.

### Что должно быть на выходе
- manual parameterized launch для отчётов;
- запуск через `report_preset + period + filters`;
- presets `manager_daily` и `rop_weekly`;
- режимы `build_missing_and_report` и `report_from_ready_data_only`;
- для `manager_daily`: source discovery во внешней системе по выбранному периоду и manager filters, persistence-check и ingest missing calls без дублей;
- для `rop_weekly`: persisted-only aggregation без source/build loop;
- reuse ready artifacts без лишнего полного rerun;
- bounded missing audio / STT / analysis build по operator trigger только для `manager_daily`;
- always-on Telegram test delivery for operator manual runs, with optional business email delivery controlled separately;
- standard versioned final report templates for `manager_daily` / `rop_weekly` and PDF as the primary operator artifact;
- configurable recipient resolution через Bitrix manager / sales-head data;
- optional bounded report-composer step поверх уже готовых материалов.

### Критерий готовности
Оператор может вручную запустить `manager_daily` или `rop_weekly` по выбранным параметрам, подтянуть missing calls из source system, переиспользовать ready artifacts, достроить missing transcript/analysis при нужном режиме и получить structured report result без scheduler/retries/beat.

---

## Веха 5. Reporting Loop Ready
### Смысл
Из отдельных карточек перейти к регулярному управленческому контуру.

### Что должно быть на выходе
- ежедневный отчёт с ТОП-3 проблемными зонами
- еженедельный coaching pack
- динамика прогресса менеджера
- ежемесячная сводка по отделу
- заготовка или первая версия dashboard слоя

### Критерий готовности
Отчётный контур работает по расписанию и собирается без ручной аналитической обработки.

---

## Веха 6. Pilot Ready
### Смысл
Подготовить систему к пилоту на реальной группе менеджеров.

### Что должно быть на выходе
- финальный checklist
- pilot group 3–5 менеджеров
- baseline по этапам воронки
- pilot baseline version, pilot scope in/out и pilot KPI list зафиксированы в repo docs
- baseline metrics package, manual AI validation rule и delivery success rule зафиксированы в repo docs
- bounded `scheduled_reviewable_reporting` в existing backend/operator UI: automatic schedule -> draft artifact -> operator review/approve
- рабочий pipeline source → transcript → analysis → delivery
- ручная проверка качества на выборке

### Критерий готовности
Система готова к запуску на пилотной группе и не требует дополнительных архитектурных решений перед стартом; bounded scheduled reviewable runs допускаются до пилота, но business delivery всё ещё требует explicit operator approve. Если billable access для `OPENAI_API_KEY_STT_MAIN` и `OPENAI_API_KEY_LLM1_MAIN` временно недоступен, единственный оставшийся blocker — один bounded closure rerun после user confirmation about top-up.

---

## Веха 6.5. Business-ready Report Pack
### Смысл
Довести daily/weekly отчёты до business-ready presentation layer перед пилотом.
Для `manager_daily` текущий фокус уже вышел за чистое оформление: отчет должен
передавать смысл дня, но без полной post-pilot архитектуры rich-reporting.
На 2026-05-27 работа идет в режиме Gate 5 block-by-block калибровки качества
после test Telegram previews по контрольным датам `2026-05-18`,
`2026-05-19`, `2026-05-20`.

### Что должно быть на выходе
- polished business-facing report structure
- clearer top summary and visual hierarchy
- readable wording for business users
- consistent PDF artifact
- consistent list-of-calls presentation
- grounded narrative blocks for `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, and follow-up actions
- clear role boundary: LLM2 produces per-call evidence, LLM3 composes bounded narrative blocks, Report Layer validates/renders
- fact/evidence gates remain strict while form/table constraints move to LLM3 instructions, repair or diagnostics where safe
- no auto-send to business without operator review
- no external CRM/revenue/money integration unless separately reopened

### Критерий готовности
Бизнес может воспринимать `manager_daily` как рабочий продукт: отчет дает
понятную картину дня, не выдумывает факты, подкрепляет выводы репликами и
сохраняет стабильные scoring baseline / pilot boundaries.

---

## Веха 7. Pilot Live
### Смысл
Проверить реальную ценность системы в живой работе на стабильной версии после `Business-ready Report Pack`.

### Что должно быть на выходе
- 1–2 недели реального использования
- обратная связь от менеджеров и РОПа
- данные по стабильности, качеству, скорости и открываемости отчётов

### Критерий готовности
Пилот отработал достаточно долго, чтобы можно было принимать решение не по ощущениям, а по данным.

---

## Веха 8. Stabilized MVP-1
### Смысл
Сделать систему устойчивой и пригодной к регулярной эксплуатации.

### Что должно быть на выходе
- логи и контроль ошибок
- лимиты стоимости
- unit-cost расчёт
- стабильность пайплайна
- Looker Studio dashboard
- минимизация ручных действий

### Критерий готовности
Система стабильно работает, стоимость понятна, управление качеством возможно без постоянного ручного вмешательства.

---

## Веха 9. GO / NO-GO
### Смысл
Принять управленческое решение: идём дальше или останавливаемся.

### GO, если
- выполнены критичные KPI;
- пилот стабилен;
- отчёты используются;
- unit-cost оправдан;
- ценность подтверждена.

### NO-GO, если
- стабильность не достигнута;
- отчёты не используются;
- стоимость не бьётся с эффектом.

---

## Веха 10. Post-GO Expansion
### Смысл
Расширять систему модульно, не переписывая ядро.

### Порядок расширения
1. MVP-2 — Договорённости
2. MVP-3 — Голос клиента
3. Омниканальность
4. Другие отделы
5. Коммерциализация

---

## Где мы сейчас
По текущему состоянию проект находится в Вехе 6.5 `Business-ready Report Pack`.

Что уже в основном собрано:
- архитектурная основа и source-aware manual reporting path;
- STT / LLM pipeline и persisted analyses;
- manual operator run для `manager_daily` / `rop_weekly`;
- Bitrix24 read-only mapping;
- `manager_daily_template_v2`;
- LLM2 v15 `block-ready` evidence package;
- LLM3 narrative composers for Situation Day, Call Breakdown, Voice of Customer, Tomorrow Follow-up wording and Additional Situations;
- ready-only/no-delivery preview flow for report-quality review.

Что является следующим главным фокусом:
- Gate 5 Block 1: `БАЛЛЫ ПО ЭТАПАМ` + `ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ` +
  `КОНТАКТЫ В РАБОТУ`;
- ввести единый manager-facing status source для summary, appendix,
  follow-up selection и diagnostics;
- переименовать follow-up block так, чтобы он не обещал только `завтра`;
- повторно проверить контрольные отчеты `2026-05-18`, `2026-05-19`,
  `2026-05-20` через operator/test preview;
- не переходить к Block 2 до acceptance Block 1.

Что не является текущим фокусом:
- broad evidence/action consistency pass for money, warm pipeline, challenge and other non-current blocks;
- scheduler/retries/beat rollout;
- CRM/revenue integration;
- full post-pilot rich-report mechanism upgrade.

## Что особенно важно не потерять по пути
- Bitrix24 read-only нужен в следующем шаге для полного управленческого отбора и маппинга, но первый live manual validation допускает временный pilot mode без него.
- После закрытия Вехи 3.5 Bitrix24 read-only становится основным путём manager/department mapping, а manual bootstrap остаётся резервным режимом.
- После подтверждения Bitrix24 read-only mapping ближайший шаг больше не automation, а Manual Output Validation.
- После закрытия Manual Output Validation ближайший согласованный шаг больше не automation readiness, а `Manual Reporting Pilot`.
- После закрытия `Pilot Ready` следующим согласованным шагом является `Business-ready Report Pack`, а не полный mechanism upgrade rich report.
- `Pilot Live` проводится на стабильной версии после `Business-ready Report Pack`.
- Full Report Mechanism Upgrade относится к отдельному post-pilot этапу после `Pilot Live`.
- Bitrix24 write-back относится уже к MVP-2 «Договорённости».
- Checklist definition, analysis contract и manager card — это три разные сущности.
- Delivery не равно reporting: после карточки звонка ещё нужен полноценный контур ежедневных и еженедельных отчётов.
