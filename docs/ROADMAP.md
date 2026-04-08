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
- рабочий pipeline source → transcript → analysis → delivery
- ручная проверка качества на выборке

### Критерий готовности
Система готова к запуску на пилотной группе и не требует дополнительных архитектурных решений перед стартом.

---

## Веха 7. Pilot Live
### Смысл
Проверить реальную ценность системы в живой работе.

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
По текущему состоянию проект находится между:
- Вехой 4. Delivery Ready
- и Вехой 4.5. Manual Reporting Pilot

Что уже в основном собрано:
- архитектурная основа;
- source pipeline по звонкам;
- STT;
- approved checklist/contract в analyzer;
- fixture-level проверка analyzer;
- live manual pipeline;
- Telegram delivery replay;
- Bitrix24 read-only mapping на реальных полях.

Что является следующим главным фокусом:
- Manual Reporting Pilot как отдельный промежуточный режим;
- параметрический ручной запуск отчётов без scheduler/retries/beat;
- reuse уже собранных артефактов и bounded model/version selection;
- только после этого обсуждать automation settings и automated reporting.

## Что особенно важно не потерять по пути
- Bitrix24 read-only нужен в следующем шаге для полного управленческого отбора и маппинга, но первый live manual validation допускает временный pilot mode без него.
- После закрытия Вехи 3.5 Bitrix24 read-only становится основным путём manager/department mapping, а manual bootstrap остаётся резервным режимом.
- После подтверждения Bitrix24 read-only mapping ближайший шаг больше не automation, а Manual Output Validation.
- После закрытия Manual Output Validation ближайший согласованный шаг больше не automation readiness, а `Manual Reporting Pilot`.
- Bitrix24 write-back относится уже к MVP-2 «Договорённости».
- Checklist definition, analysis contract и manager card — это три разные сущности.
- Delivery не равно reporting: после карточки звонка ещё нужен полноценный контур ежедневных и еженедельных отчётов.
