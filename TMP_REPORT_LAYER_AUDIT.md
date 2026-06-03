# Аудит Report Layer

Дата: 2026-06-03

Цель: пройти слой отчета по цепочке и отделить проблемы анализа от проблем выбора, сжатия, сборки, рендера и доставки отчета.

## 1. Вход в слой отчета

Основные точки входа:

- `core/app/agents/calls/manual_reporting_runner.py` - ручной CLI-запуск.
- `core/app/agents/calls/scheduled_reporting.py` - плановые reviewable-отчеты.
- `core/app/core_shared/api/routes/pipeline.py` - запуск через операторский UI/API.

Главный оркестратор:

- `core/app/agents/calls/reporting.py::CallsManualReportingOrchestrator.run_report`

Поддерживаемые режимы:

- `build_missing_and_report` - source discovery, сохранение недостающих звонков, достройка STT и анализа для недостающих артефактов, затем отчет.
- `report_from_ready_data_only` - source discovery и возможное сохранение новых `Interaction`, но без нового STT/LLM анализа; отчет строится из уже готовых данных.

Риск:

- Название `report_from_ready_data_only` звучит как полностью read-only, но для `manager_daily` он все равно делает source discovery и может сохранять новые interactions. Для чистого аудита отчета это нужно учитывать.

## 2. Период, окна и выбор звонков

Для `manager_daily` выбранный день превращается в 1/2/3-дневные рабочие окна:

- `MANAGER_DAILY_MAX_WINDOW_WORKDAYS = 3`
- `CallsManualReportingOrchestrator._build_manager_daily_windows`

Назначение: если за один день не хватает материала, механизм может построить сигнальный/накопительный отчет по расширенному окну.

Риск:

- Для теста "строго один день" нужно проверять, какие блоки берут только `operational_day_artifacts`, а какие могут использовать расширенное окно.

## 3. Подготовка ReportArtifact

Функция:

- `CallsManualReportingOrchestrator._prepare_artifacts`

Для каждого звонка собирается:

- `Interaction`
- STT (`interaction.text`)
- выбранный reusable `Analysis`
- `original_analysis`
- менеджер
- время звонка
- причина переиспользования/отклонения анализа

Политика выбора анализа:

- По умолчанию берется newest reusable stable analysis.
- Controlled/verification samples исключаются, если не включен `include_controlled_samples`.
- При `analysis_instruction_version` переиспользуются только анализы с точным совпадением версии.

Риск:

- Если указан `analysis_instruction_version`, старые хорошие анализы не могут закрыть readiness. Это корректно для тестов версии, но может давать "много missing" в отчете.

## 4. Meaningful / usable / coaching core

В слое есть несколько разных множеств звонков:

- `window_artifacts` - все звонки выбранного окна.
- `operational_day_artifacts` - звонки выбранного дня.
- `operational_meaningful_artifacts` - содержательные звонки дня.
- `usable_artifacts` - звонки с transcript + reusable analysis.
- `coaching_content_artifacts` - звонки, которые можно использовать в коучинговых блоках.
- `stage_score_artifacts` - готовые содержательные sales-like звонки с числовыми оценками этапов.

Это объясняет расхождения вида:

- "Все звонки дня" показывает больше звонков.
- "Баллы по этапам" считает меньше звонков.
- "Разбор звонка" берет еще более узкую выборку.

Риск:

- Нужно явно показывать scope каждого блока, иначе пользователь воспринимает разные числа как ошибку.

## 5. Readiness и completeness gate

Readiness:

- `_evaluate_manager_daily_readiness`
- проверяет количество звонков, количество ready-анализов, coverage и наличие смысловых блоков.

Completeness gate:

- `_build_manager_facing_completeness_gate`
- блокирует бизнес-доставку менеджеру, если в call list есть звонки без transcript, без анализа, с ошибкой анализа или provider error.

Риск:

- Оператору отчет может быть отправлен как preview/review_required, но менеджеру он не должен уходить при неполной обработке дня.

## 6. Нормализация report_evidence

Функция:

- `_build_report_evidence_index`

Что делает:

- валидирует `report_evidence`;
- валидирует `block_candidates`;
- определяет доступность/валидность `semantic_case`;
- сохраняет diagnostics по каждому звонку.

Особенность:

- Даже если `report_evidence` невалиден, `call_essence` может быть мягко сохранен как fallback для списка звонков.

Риск:

- В таблице "Все звонки дня" может появляться текст из soft fallback, а основные коучинговые блоки могут его не использовать.

## 7. Сбор payload ежедневного отчета

Главная функция:

- `build_manager_daily_payload`

Собирает:

- header
- day summary
- call outcomes summary
- stage scores
- situation day
- call breakdown
- voice of customer
- additional situations
- call tomorrow
- call list
- diagnostics
- data scopes

Риск:

- Функция слишком большая и совмещает выбор данных, fallback logic, quality gates, diagnostics и финальный payload. Доработки нужно делать локальными зонами, а не широким рефакторингом.

## 8. Таблица "Все звонки дня"

Источник данных:

- `_build_meaningful_call_list`
- `_build_daily_call_row`
- `_select_call_list_context`
- `_compact_call_list_visible_context`

Рендер:

- `report_templates.py::_build_call_list_compact_rows`
- `report_templates.py::_call_list_essence_label`

Найденная проблема:

- `call_list_context_rich` часто содержит полный смысл звонка и финал.
- `call_list_context` сжимается до `CALL_LIST_VISIBLE_CONTEXT_LIMIT = 150`.
- `_summary_text` берет первую фразу и режет ее по лимиту.
- В результате "Суть звонка" часто описывает начало звонка, но не отвечает на вопрос "чем закончилось".

Пример дефекта:

- Было по смыслу: клиент занят, предложил написать позже, конкретная дата не зафиксирована.
- В таблице: "клиент ответил, что сейчас занят, и"

Задача:

- Для "Суть звонка" формировать отдельный manager-facing текст: тема -> что выяснили -> итог/финал.
- Не использовать первую фразу как единственный compact summary.
- Не резать строку так, чтобы исчезал итог звонка.

## 9. Рендер HTML/PDF

Файл:

- `core/app/agents/calls/report_templates.py`

Что делает:

- build render model;
- HTML;
- PDF;
- таблицы;
- DOCX-first PDF для manager_daily v2;
- filename;
- morning card text.

Риск:

- Для одной и той же секции могут существовать разные пути рендера: HTML path, direct PDF path, DOCX-first path. При правках таблиц нужно проверять фактический путь PDF, а не только HTML.

## 10. Доставка

Файл:

- `core/app/agents/calls/delivery.py`

Каналы:

- Telegram test delivery;
- business email;
- telegram + email;
- preview only.

Риск:

- Статус run может быть `review_required`, но Telegram test delivery оператору все равно может быть выполнен. Это нормально для проверки, но должно быть явно отделено от бизнес-доставки менеджеру.

## Первичные задачи по итогам аудита

### P1. Исправить "Все звонки дня -> Суть звонка"

Сделать отдельную сборку суть-звонка для таблицы:

- тема звонка;
- ключевой контекст;
- финал/исход;
- договоренность или отсутствие следующего шага.

Проверить на отчете Толеген 2026-06-01 без нового STT/LLM, только пересборкой отчета.

### P1. Явно разделить scope блоков в diagnostics и видимых notes

Особенно:

- "Все звонки дня";
- "Баллы по этапам";
- "Разбор звонка";
- "Ситуация дня".

### P2. Упростить/локализовать call_list context selection

Сейчас выбор контекста размазан между:

- `call_report_summary.manager_visible_summary`;
- `call_essence`;
- `semantic_case`;
- `business_outcome`;
- deterministic fallback.

Нужно сделать понятный порядок источников и диагностику, почему выбран именно этот источник.

### P2. Проверить readiness/completeness логику для операторских тестов

Нужно явно описать:

- когда отчет можно отправлять менеджеру;
- когда можно отправлять только оператору;
- когда отчет считается полноценным;
- когда отчет считается preview/review_required.

### P3. Проверить расхождение HTML/PDF/DOCX-first путей

Для таблиц и визуального оформления правки должны подтверждаться на фактическом PDF, который уходит в Telegram.

## Согласованные следующие доработки по 4 техническим пунктам

Статус задач ниже после реализации 2026-06-03: `implemented / focused_tests_passed`.

Важно: пользователь разрешил после реализации запустить полный full-stack прогон
Тимура за `2026-06-01` со STT и Telegram test-only доставкой.

### RL-T2. Meaningful-call diagnostics

Статус: `implemented / focused_tests_passed`.

Связанный пункт аудита: `C. Ограничители meaningful-call отбора`.

Решение:

- текущую логику отбора не менять;
- если у звонка есть STT, длительность не должна отсекать звонок;
- если STT нет, технические пороги допустимы;
- добавить прозрачность в diagnostics/operator summary.

Что сделать:

- явно показывать, какие звонки исключены из "Все звонки дня" как `too_short_or_no_speech`;
- отдельно показывать счетчики: всего звонков, со STT, meaningful, исключены по короткости/без речи;
- проверить, что наличие STT имеет приоритет над duration-фильтром meaningful-call.

Acceptance:

- оператор видит список/счетчик исключенных коротких звонков;
- ни один звонок с готовым STT не исключается только из-за длительности;
- бизнес-логика отбора не меняется без отдельного решения.

Реализация:

- `selection_model` дополнен `transcript_calls_total`,
  `no_transcript_calls_total`, `meaningful_policy`, `excluded_calls_total`,
  `excluded_call_samples`;
- logic `_classify_meaningful_call` не менялась: STT по-прежнему имеет
  приоритет над duration-фильтрами.

### RL-T6. Call List: доработать существующий `call_list_context`

Статус: `implemented / focused_tests_passed`.

Связанный пункт аудита: `G. Ограничители Call List`.

Решение:

- не создавать новый смысловой слой и не выдумывать новую "суть";
- доработать существующее поле `call_list_context`;
- использовать уже готовые источники смысла;
- убрать слепую схему "первая фраза + 150 символов".

Что сделать:

- источниками оставить существующие поля: `call_essence`, `business_outcome`, `call_report_summary`, `follow_up`, `call_list_context_rich`;
- для видимой "Суть звонка" собирать compact-формулировку по схеме: `тема -> реакция/позиция клиента -> итог звонка`;
- учитывать все статусы:
  - договоренность: о чем договорились и следующий шаг;
  - перенос: какую тему перенесли и куда должен вернуться контакт;
  - отказ: от чего отказался клиент и почему, если причина есть;
  - открыт: какая тема/интерес есть и что не зафиксировано;
  - тех/сервис: какой вопрос решали;
  - без разбора: почему нет нормальной сути;
- лимит можно оставить/увеличить, но применять только после сборки правильной итоговой формулировки;
- промпт LLM2 можно уточнить, чтобы `call_essence.manager_visible_text` был коротким итогом звонка, но технический выбор/обрезку нужно исправлять в Report Layer.

Acceptance:

- в таблице "Все звонки дня" каждая содержательная строка отвечает на вопрос "о чем был звонок и чем закончился";
- `Суть звонка` не дублирует колонку `Договоренность`;
- для отказов/переносов/техподдержки тоже есть фактическая суть, а не только статус;
- строки не обрываются на середине фразы;
- пересборка отчета из готовых данных показывает улучшение без нового STT/LLM.

Реализация:

- `CALL_LIST_VISIBLE_CONTEXT_LIMIT` увеличен до `220`;
- `_compact_call_list_visible_context` больше не режет первую фразу вслепую;
- добавлен выбор outcome-фразы по маркерам: договоренность, отказ, перенос,
  дата возврата, не закреплен следующий шаг, сервисный вопрос и т.д.;
- structured `business_outcome/follow_up` теперь выбирается раньше generic
  `short_context`, чтобы начало звонка не вытесняло итог.

### RL-T7. Разделить gates по назначению блока

Статус: `implemented / focused_tests_passed`.

Связанный пункт аудита: `H. Ограничители report_evidence / semantic_case`.

Решение:

- строгие gates оставить для доказательных коучинговых блоков;
- для справочной таблицы "Все звонки дня" применять более мягкий фактический подход;
- новые факты не придумывать, использовать только уже имеющийся анализ.

Что сделать:

- описать разные классы доказательности:
  - `business_report_claim` - высокий порог для `Ситуации дня`, `Разбора звонка`, рекомендаций;
  - `call_list_essence` - средний порог для краткой фактической сути звонка;
  - `operator_diagnostic` - слабые/неполные данные можно показывать только оператору с пометкой;
- проверить, что call list не обедняется из-за gates, предназначенных для коучинговых выводов;
- сохранить защиту от неподтвержденных управленческих claims.

Acceptance:

- `Ситуация дня` и `Разбор звонка` по-прежнему проходят строгий proof/safety gate;
- `Все звонки дня` может использовать фактический `call_essence/business_outcome`, даже если материал недостаточен для большого coaching claim;
- diagnostics показывают, какой класс доказательности применен к блоку.

Реализация:

- `call_list_context_quality.evidence_class = call_list_essence`;
- `call_breakdown_quality.evidence_class = business_report_claim`;
- строгий proof gate для coaching blocks не ослаблялся.

### RL-T8. Call Breakdown: нормализация формы + диагностика

Статус: `implemented / focused_tests_passed`.

Связанный пункт аудита: `I. Ограничители Call Breakdown Composer`.

Решение:

- доказательность не ослаблять;
- не терять хороший смысл только из-за небольшой технической ошибки формы;
- добавить diagnostics, различающие смысловую слабость и форматную проблему.

Что сделать:

- если composer/LLM3 вернул больше 4 моментов, выбирать лучшие 2-4 вместо полного отклонения;
- если строка неполная, нормализовать форму до 4 колонок без добавления новых фактов;
- если fragment короче 90 символов, проверять информативность, а не только длину;
- если stage_code mismatch, фиксировать это в diagnostics и решать по severity, а не всегда терять весь результат;
- не пропускать блок в бизнес-отчет без доказательств.

Acceptance:

- если результат не попал в PDF, diagnostics объясняют: слабый смысл, нет доказательств или проблема формата;
- небольшие форматные нарушения не уничтожают весь разбор;
- финальный `Разбор звонка` остается доказательным и безопасным для бизнес-отчета.

Реализация:

- `_apply_call_breakdown_quality_gate` режет rendered rows до 4 и пишет
  `extra_rows_trimmed_count`;
- короткая row shape нормализуется до 4 колонок без добавления новых фактов и
  фиксируется как `format_issue`;
- filtered rows получили `issue_class`: `format_issue`,
  `semantic_weakness`, `missing_or_ungrounded_proof`.

Focused checks:

```text
python3 -m py_compile core/app/agents/calls/reporting.py core/tests/test_manual_reporting.py tests/test_manual_reporting.py -> OK
docker compose exec -T api python -m pytest -q /app/tests/test_manual_reporting.py -k "call_list_context or sfb5 or a2_a3 or selection_model or meaningful_call or call_breakdown_quality_gate" -> 27 passed
docker compose exec -T api python -m pytest -q /app/tests/test_report_templates_situation_day.py -k "call_list" -> 2 passed
docker compose exec -T api python -m pytest -q /app/tests/test_report_block_router.py /app/tests/test_call_breakdown_composer.py -k "call_breakdown" -> 14 passed
```

---

# Разбор Report Layer по узлам

Эта схема нужна для дальнейшего аудита: каждый узел рассматриваем отдельно по принципу `вход -> задача -> выход -> риски -> что проверяем`.

## Узел R0. Report Run Controller

Файл:

- `core/app/agents/calls/reporting.py::CallsManualReportingOrchestrator.run_report`

Задача:

- принять параметры запуска;
- определить preset;
- определить режим;
- определить delivery options;
- запустить всю цепочку отчета.

Вход:

- `preset_code`
- `mode`
- `ReportRunFilters`
- `analysis_instruction_version`
- delivery flags

Выход:

- общий run result;
- reports;
- diagnostics;
- delivery status.

Риски:

- режим `report_from_ready_data_only` звучит как полностью read-only, но для `manager_daily` может делать source discovery и сохранять новые `Interaction`;
- один запуск может одновременно проверять Report Layer и upstream-слои, если выбран `build_missing_and_report`.

Что аудируем:

- корректность режима;
- не запускаются ли STT/LLM там, где должен быть только отчет;
- прозрачно ли в diagnostics видно, что именно запускалось.

## Узел R1. Source Discovery / Intake Sync

Файл:

- `core/app/agents/calls/reporting.py::_discover_and_persist_source_calls`

Задача:

- сходить в источник телефонии;
- найти звонки за период;
- применить фильтры менеджера/extension/duration;
- сохранить недостающие `Interaction`.

Вход:

- период;
- manager ids;
- extensions;
- duration filters;
- OnlinePBX source records.

Выход:

- source summary;
- новые или уже существующие persisted interactions.

Риски:

- в ready-only режиме узел все равно может создавать новые `Interaction`;
- фильтр manager_id + extension работает как intersection;
- источник и локальная база могут расходиться по количеству звонков.

Что аудируем:

- сколько звонков найдено в телефонии;
- сколько попало в фильтр менеджера;
- сколько уже было в базе;
- сколько создано заново;
- какие звонки source-build-eligible.

## Узел R2. Interaction Selector

Файл:

- `core/app/agents/calls/reporting.py::_select_interactions`

Задача:

- выбрать persisted calls из базы под период и фильтры.

Вход:

- persisted `Interaction`;
- period;
- manager ids;
- extensions;
- duration filters.

Выход:

- список selected interactions.

Риски:

- если у звонка нет нормального `call_started_at` в metadata, он выпадает;
- manager_id и extension могут пересекаться слишком узко;
- duration filters могут незаметно исключить звонки.

Что аудируем:

- почему конкретный звонок вошел/не вошел;
- совпадают ли selected interactions с ожиданием по телефонии;
- есть ли звонки без даты/extension/manager_id.

## Узел R3. Artifact Builder / Reuse Policy

Файл:

- `core/app/agents/calls/reporting.py::_prepare_artifacts`

Задача:

- для каждого звонка собрать `ReportArtifact`;
- переиспользовать готовый STT;
- выбрать reusable analysis;
- при режиме `build_missing_and_report` достроить missing STT/analysis.

Вход:

- selected interactions;
- existing analyses;
- instruction version guard;
- mode.

Выход:

- `ReportArtifact[]`;
- build summary;
- build errors.

Риски:

- хороший старый анализ будет отклонен при несовпадении `analysis_instruction_version`;
- failed analysis сохраняется как original_analysis, но не как reusable;
- controlled samples по умолчанию исключаются.

Что аудируем:

- сколько STT reused/built;
- сколько analysis reused/built;
- сколько analysis rejected;
- причины rejection;
- какие звонки оказались без usable analysis.

## Узел R4. Grouping And Window Readiness

Файл:

- `core/app/agents/calls/reporting.py::_build_manager_daily_reports_with_readiness`
- `core/app/agents/calls/reporting.py::_evaluate_manager_daily_readiness`

Задача:

- сгруппировать звонки по менеджеру;
- пройти 1/2/3-дневные окна;
- решить, можно ли строить full report, signal report или нужно skip_accumulate.

Вход:

- artifacts;
- manager daily windows;
- thresholds;
- preliminary payload.

Выход:

- readiness outcome;
- selected window;
- reason codes.

Риски:

- пользователь ожидает строго один день, а readiness может выбрать расширенное окно;
- отчет может быть не построен, даже если звонки есть, если не хватает ready analyses/content blocks;
- coverage считается по текущей логике usable/relevant.

Что аудируем:

- какое окно выбрано;
- сколько relevant calls;
- сколько ready analyses;
- почему full_report/signal_report/skip_accumulate.

## Узел R5. Meaningful / Usable / Coaching Scope Classifier

Файл:

- `core/app/agents/calls/reporting.py::_classify_meaningful_call`
- `core/app/agents/calls/reporting.py::_split_usable_artifacts`
- `core/app/agents/calls/reporting.py::_filter_coaching_artifacts_by_final_outcome`
- `core/app/agents/calls/reporting.py::_filter_stage_score_artifacts`

Задача:

- разделить звонки на разные множества для разных блоков отчета.

Вход:

- artifacts;
- transcript presence;
- analysis presence;
- classification;
- final outcome;
- stage scores.

Выход:

- meaningful calls;
- usable calls;
- coaching content calls;
- stage score calls.

Риски:

- разные блоки считают разные множества звонков;
- пользователь видит разные цифры и воспринимает это как ошибку;
- stage scores могут быть меньше call list не из-за фильтра Report Layer, а из-за отсутствия score_by_stage.

Что аудируем:

- состав каждого множества;
- почему звонок попал в call list, но не попал в stage scores;
- почему звонок попал/не попал в coaching blocks.

## Узел R6. Report Evidence Index

Файл:

- `core/app/agents/calls/reporting.py::_build_report_evidence_index`

Задача:

- собрать и провалидировать LLM2 evidence для отчета;
- нормализовать `report_evidence`;
- проверить `semantic_case`;
- проверить `block_candidates`;
- сохранить diagnostics.

Вход:

- `scores_detail`;
- `report_evidence`;
- transcript.

Выход:

- evidence index by interaction id;
- normalized evidence;
- validation errors/warnings.

Риски:

- `report_evidence` может быть invalid, но `call_essence` все равно используется как soft fallback;
- блоки могут использовать разные источники: block_candidates, semantic_case, report_evidence_v1, legacy fallback;
- diagnostics есть, но сложно читаются без отдельного summary.

Что аудируем:

- source policy;
- сколько evidence valid/invalid/missing;
- какие блоки взяли semantic_case;
- какие блоки ушли в fallback.

## Узел R7. Call List Builder

Файл:

- `core/app/agents/calls/reporting.py::_build_meaningful_call_list`
- `core/app/agents/calls/reporting.py::_build_daily_call_row`
- `core/app/agents/calls/reporting.py::_select_call_list_context`
- `core/app/agents/calls/reporting.py::_compact_call_list_visible_context`

Задача:

- собрать приложение "Все звонки дня";
- определить статус звонка;
- определить контакт;
- определить суть звонка;
- определить договоренность/рекомендацию;
- сохранить diagnostics качества.

Вход:

- operational day artifacts;
- business_outcome;
- call_essence;
- call_report_summary;
- semantic_case;
- follow_up.

Выход:

- `call_list`;
- `call_list_context_quality`;
- `call_list_status_quality`;
- `agreement_outcome_diagnostics`.

Риски:

- найденный дефект: "Суть звонка" режется до 150 символов;
- compact context берет начало, а не финал звонка;
- `call_list_context_rich` полнее, чем видимое `call_list_context`;
- порядок источников может выбирать слабый `manager_visible_summary` вместо outcome-rich essence.

Что аудируем:

- source каждого `call_list_context`;
- есть ли в видимой сути финал звонка;
- не обрывается ли текст;
- корректен ли статус;
- не дублируются ли "Суть звонка" и "Договоренность".

## Узел R8. Outcome Summary Builder

Файл:

- `core/app/agents/calls/reporting.py::_build_call_outcomes_summary_from_call_list`

Задача:

- посчитать итоги дня по статусам: договоренность, перенос, отказ, открыт, тех/сервис, без разбора.

Вход:

- call list.

Выход:

- `call_outcomes_summary`.

Риски:

- если call list статус ошибочный, сводка дня тоже ошибочная;
- unclassified может смешивать разные причины: нет STT, нет анализа, ошибка анализа, provider error.

Что аудируем:

- соответствие counts таблице "Все звонки дня";
- прозрачность "без разбора";
- связь с completeness gate.

## Узел R9. Stage Scores Builder

Файл:

- `core/app/agents/calls/reporting.py::_aggregate_stage_scores`
- `core/app/agents/calls/reporting.py::_build_stage_score_scope`

Задача:

- агрегировать оценки по этапам;
- показать проблемы по этапам;
- описать scope блока.

Вход:

- stage_score_artifacts.

Выход:

- `score_by_stage`;
- `stage_score_scope`.

Риски:

- блок может считать меньше звонков, чем call list;
- если LLM2 не дал `score_by_stage`, звонок не попадет в агрегат;
- в отчете нужно явно объяснять coverage.

Что аудируем:

- сколько звонков вошло в stage score;
- почему остальные не вошли;
- корректны ли комментарии/основные проблемы;
- не слишком ли агрессивны фильтры.

## Узел R10. Situation Day Builder

Файл:

- `core/app/agents/calls/reporting.py::_build_verified_situation_day_from_daily_composer`
- `core/app/agents/calls/situation_day_daily_composer.py`
- `core/app/agents/calls/situation_day_writer.py`

Задача:

- выбрать главную ситуацию дня;
- доказать ее на звонке/сцене;
- собрать manager-facing объяснение.

Вход:

- coaching_content_artifacts;
- report evidence index;
- evidence registry;
- daily coaching focus.

Выход:

- `situation_day_coaching_view`;
- `situation_evidence_quote`;
- `situation_day_evidence_packet`;
- diagnostics.

Риски:

- ситуация может быть слишком общей;
- ситуация может конфликтовать с доказательством;
- заголовок может дублировать весь смысл, хотя смысл должен быть внутри блока "Что произошло".

Что аудируем:

- почему выбрана именно эта ситуация;
- есть ли доказательство;
- есть ли связь между проблемой и репликами;
- нет ли противоречий call list.

## Узел R11. Call Breakdown Builder

Файл:

- `core/app/agents/calls/reporting.py::_build_call_breakdown_from_evidence_registry_route`
- `core/app/agents/calls/call_breakdown_composer.py`

Задача:

- разобрать выбранный звонок по моментам;
- показать, что было, подтверждение и рекомендацию.

Вход:

- selected situation packet;
- routed evidence items;
- score_by_stage.

Выход:

- `call_breakdown`;
- `call_breakdown_quality`.

Риски:

- может повторять "Ситуацию дня";
- может выбрать недостаточно доказанный момент;
- таблица может визуально сливаться без разделителей.

Что аудируем:

- совпадает ли звонок с ситуацией дня;
- не дублирует ли блок соседние блоки;
- есть ли понятный ход звонка;
- хватает ли визуального разделения.

## Узел R12. Voice Of Customer Builder

Файл:

- `core/app/agents/calls/reporting.py::_build_voice_of_customer_from_report_evidence`
- `core/app/agents/calls/voice_of_customer_composer.py`

Задача:

- выбрать клиентские сигналы;
- показать, что клиент сказал и что это значит для работы менеджера.

Вход:

- report evidence;
- coaching artifacts;
- call list context.

Выход:

- `voice_of_customer`.

Риски:

- может брать ту же ситуацию, что Situation Day;
- может выводить слабые/общие цитаты;
- может быть пустым при наличии хороших клиентских сигналов.

Что аудируем:

- качество клиентских цитат;
- связь цитаты с рекомендацией;
- отсутствие дублей с Situation Day.

## Узел R13. Call Tomorrow / Follow-Up Builder

Файл:

- `core/app/agents/calls/reporting.py::_build_call_tomorrow`
- `core/app/agents/calls/call_tomorrow_wording_composer.py`

Задача:

- выбрать контакты в работу;
- определить приоритет, срок и рекомендацию.

Вход:

- call list;
- report evidence index;
- follow_up/business_outcome.

Выход:

- `call_tomorrow`.

Риски:

- блок скрыт как отдельный раздел и merged into call list;
- логика "в работу" теперь должна согласованно жить в таблице "Все звонки дня";
- договоренность может быть без понятной темы.

Что аудируем:

- все ли договоренности/переносы попали в работу;
- есть ли тема договоренности;
- есть ли срок/ответственный/следующий шаг.

## Узел R14. Additional Situations Builder

Файл:

- `core/app/agents/calls/reporting.py::_build_additional_situations_from_report_evidence`
- `core/app/agents/calls/reporting.py::_apply_additional_situations_quality_gate`

Задача:

- добавить 1-3 дополнительные ситуации, не дублирующие основные блоки.

Вход:

- evidence;
- worked/improve items;
- excluded primary call ids.

Выход:

- `additional_situations`;
- quality diagnostics.

Риски:

- дублирование с Situation Day / Call Breakdown / Voice of Customer;
- слишком общие ситуации;
- слабые доказательства.

Что аудируем:

- уникальность ситуаций;
- качество доказательств;
- полезность для менеджера.

## Узел R15. Payload Finalizer / Diagnostics

Файл:

- `core/app/agents/calls/reporting.py::build_manager_daily_payload`

Задача:

- собрать финальный normalized payload;
- добавить diagnostics;
- добавить data scopes;
- добавить selection model.

Вход:

- результаты всех builder-узлов.

Выход:

- payload manager_daily.

Риски:

- слишком много логики в одном узле;
- payload может содержать правильный rich context, но render model берет short context;
- diagnostics могут быть полными, но нечитабельными для оператора.

Что аудируем:

- какие поля реально уходят в render model;
- какие diagnostics нужны оператору;
- где теряется смысл между payload и PDF.

## Узел R16. Manager-Facing Completeness Gate

Файл:

- `core/app/agents/calls/reporting.py::_build_manager_facing_completeness_gate`

Задача:

- решить, можно ли отправлять отчет менеджеру;
- заблокировать бизнес-доставку, если обработка дня неполная.

Вход:

- call list.

Выход:

- `manager_report_allowed`;
- blocking counts;
- affected calls.

Риски:

- операторский Telegram preview может уходить при `review_required`;
- пользователь может путать preview для проверки и боевую отправку менеджеру.

Что аудируем:

- корректность blocking buckets;
- понятность причины review_required;
- отделение operator delivery от manager delivery.

## Узел R17. Render Model Builder

Файл:

- `core/app/agents/calls/report_templates.py::_build_render_model`

Задача:

- превратить payload в набор секций для шаблона.

Вход:

- manager_daily payload;
- semantic/visual template assets.

Выход:

- render model sections.

Риски:

- здесь может теряться или переименовываться смысл;
- `call_tomorrow` скрыт и merged into `call_list`;
- `compact_rows` могут отличаться от `rows`.

Что аудируем:

- какие payload fields используются в каждой секции;
- нет ли расхождения между rich payload и compact render fields;
- корректны ли заголовки и hidden sections.

## Узел R18. HTML/PDF Renderer

Файл:

- `core/app/agents/calls/report_templates.py`
- `core/app/agents/calls/report_template_assets/.../layout.css`

Задача:

- сформировать HTML/PDF;
- отрисовать таблицы;
- применить стили и ширины колонок.

Вход:

- render model.

Выход:

- `report_html`;
- `pdf_bytes`;
- artifact metadata.

Риски:

- HTML и PDF пути могут отличаться;
- DOCX-first PDF может вести себя иначе, чем direct PDF;
- таблицы могут резать/центрировать/сливать текст.

Что аудируем:

- фактический PDF, который отправляется в Telegram;
- ширины колонок;
- переносы текста;
- выравнивание;
- визуальные разделители.

## Узел R19. Delivery

Файл:

- `core/app/agents/calls/delivery.py::deliver_operator_report`

Задача:

- отправить PDF в Telegram test chat и/или email;
- вернуть delivery diagnostics.

Вход:

- rendered artifact;
- delivery options;
- Telegram/email settings.

Выход:

- delivery transport status;
- message id/document id;
- delivery errors.

Риски:

- Telegram test delivery не равен бизнес-доставке менеджеру;
- preview может уйти оператору даже при `review_required`;
- подпись Telegram может скрывать важный статус отчета.

Что аудируем:

- кому ушел отчет;
- какой статус доставки;
- какой файл отправлен;
- соответствует ли отправленный PDF последней сборке.

---

# Технические ограничители внутри Report Layer

Ниже перечислены именно технические ограничители: числа, hard-coded gates, лимиты строк/символов, thresholds и сортировки, которые могут менять состав отчета или обрезать видимый результат.

## A. Ограничители запуска и режима

Файл:

- `core/app/agents/calls/reporting.py`

Ограничители:

- `REPORTING_ALLOWED_MODES = {"build_missing_and_report", "report_from_ready_data_only"}`
- `REPORT_DELIVERY_MODES = {"preview_only", "telegram_test_only", "business_email_only", "telegram_and_email"}`

Влияние:

- определяют, можно ли достраивать STT/analysis;
- определяют, куда отправлять отчет.

Риск:

- `report_from_ready_data_only` не запускает STT/LLM, но для `manager_daily` все равно может делать source discovery и сохранять новые `Interaction`.

## B. Ограничители окна отчета

Файл:

- `core/app/agents/calls/reporting.py`

Ограничитель:

- `MANAGER_DAILY_MAX_WINDOW_WORKDAYS = 3`

Влияние:

- daily report может смотреть 1/2/3 рабочих дня для readiness и коучинговой базы.

Риск:

- пользователь ожидает строго один день, а часть коучинговых блоков может работать с расширенным окном, если это не отражено в scope.

## C. Ограничители meaningful-call отбора

Файл:

- `core/app/agents/calls/reporting.py::_classify_meaningful_call`

Ограничители:

- `MEANINGFUL_ABSOLUTE_MIN_DURATION_SEC = 15`
- `MEANINGFUL_NO_TRANSCRIPT_MIN_DURATION_SEC = 90`

Логика:

- если duration <= 0 и нет transcript -> исключить;
- если duration < 15 и нет transcript -> исключить;
- если transcript есть -> считать meaningful независимо от длительности;
- если transcript нет и duration < 90 -> исключить как too short/no speech.

Влияние:

- определяет, попадет ли звонок в "Все звонки дня".

Риск:

- это не ограничивает LLM2 напрямую, но влияет на отчетный список звонков;
- если STT уже есть, длительность не является причиной исключения: звонок считается meaningful даже если он короткий;
- если STT нет, длительность становится техническим суррогатом "был ли разговор": меньше 15 секунд отсекается почти всегда, меньше 90 секунд без transcript тоже считается недостаточным сигналом;
- из-за этого один и тот же короткий звонок может попасть в отчет при наличии STT и не попасть без STT;
- это корректно для защиты от автоответчиков/тишины, но опасно для аудита полного дня: отчетный список может зависеть не только от факта звонка, но и от готовности STT.

Комментарий:

- Этот узел должен отвечать только на вопрос "был ли это содержательный контакт для приложения дня", а не "подходит ли звонок для глубокого коучинга".
- Если есть готовый STT, Report Layer не должен дополнительно отрезать звонок по длительности.
- Для тестов полного дня нужно отдельно показывать: всего звонков в телефонии, звонков с речью/STT, meaningful calls, исключено как too short/no speech.
- Потенциальная доработка: сделать диагностику по каждому исключенному звонку видимой в operator summary, чтобы было понятно, что именно не вошло в "Все звонки дня".

## D. Ограничители readiness полного отчета

Файл:

- `core/app/agents/calls/reporting.py::_evaluate_manager_daily_readiness`

Ограничители:

- `MANAGER_DAILY_FULL_REPORT_MIN_RELEVANT_CALLS = 6`
- `MANAGER_DAILY_FULL_REPORT_MIN_READY_ANALYSES = 5`
- `MANAGER_DAILY_FULL_REPORT_MIN_ANALYSIS_COVERAGE = 75.0`
- `MANAGER_DAILY_SIGNAL_REPORT_MIN_READY_ANALYSES = 2`

Влияние:

- решают, будет ли `full_report`, `signal_report` или `skip_accumulate`.

Риск:

- даже хороший отчет по меньшему количеству звонков может быть классифицирован как не full report.

## E. Ограничители reusable analysis

Файл:

- `core/app/agents/calls/reporting.py::_is_analysis_reusable_for_reporting`

Обязательные поля:

- `classification`
- `score`
- `score_by_stage`
- `strengths`
- `gaps`
- `recommendations`
- `follow_up`

Дополнительно:

- analysis не должен быть `is_failed`;
- должен быть `instruction_version`;
- должен быть `score.checklist_score.score_percent`;
- `follow_up` должен быть dict;
- при включенной semantic validation пустой semantic-анализ отклоняется.

Влияние:

- звонок может иметь persisted analysis, но не быть reusable для отчета.

Риск:

- старые или частично успешные анализы не попадают в отчет, даже если в них есть полезный смысл.

## F. Ограничители manager-facing completeness

Файл:

- `core/app/agents/calls/reporting.py::_build_manager_facing_completeness_gate`

Блокирующие buckets:

- `Без транскрипта`
- `Без анализа`
- `Ошибка анализа`
- `Ошибка провайдера`

Влияние:

- если такие звонки есть в call list, отчет получает `review_required` и не должен идти менеджеру как боевой.

Риск:

- оператору preview может уйти в Telegram, но бизнес-доставка менеджеру блокируется.

## G. Ограничители Call List

Файл:

- `core/app/agents/calls/reporting.py`

Сортировка:

- `agreed -> rescheduled -> refusal -> open -> tech_service -> unclassified`

Контекстные gates:

- reject low-info values: `—`, `нет`, `да`, `перезвон`, `созвон`, `дальше`, `позже`
- reject generic values: `есть договоренность`, `контакт в работу`, `следующий шаг не зафиксирован`
- reject technical patterns: `до после`, `до на этой`, `→ до`

Главный лимит:

- `CALL_LIST_VISIBLE_CONTEXT_LIMIT = 150`

Влияние:

- этот лимит режет "Суть звонка" перед рендером.

Риск:

- найденный дефект: видимая суть часто теряет финал звонка;
- технически в payload часто есть два уровня контекста: `call_list_context_rich` и `call_list_context`;
- `call_list_context_rich` может содержать полный смысл: тема, реакция клиента, итог, следующий шаг;
- `call_list_context` сейчас является видимой сжатой версией и обрезается до 150 символов;
- при таком подходе в таблицу часто попадает начало разговора: "менеджер представился...", а финал "клиент отказался / перенес / попросил написать / договоренность не зафиксирована" исчезает;
- это особенно заметно в строках со статусами `Договоренность`, `Перенос`, `Открыт`, где читателю важно не начало, а итог.

Комментарий:

- Для таблицы "Все звонки дня" поле "Суть звонка" должно быть не первой фразой, а отдельной управленческой формулировкой: `тема -> что выяснили -> чем закончилось`.
- Технический лимит символов можно оставить, но он должен применяться уже к правильно собранной итоговой фразе, а не к сырому summary.
- Для строк с договоренностью/переносом в сути обязательно должен быть предмет договоренности: о чем договорились, к чему вернуться, какой вопрос закрывать.
- Для отказа должна быть короткая причина отказа, если она известна.
- Для тех/сервис звонка должна быть фактическая тема обращения, а не общий статус "сервисный вопрос".
- Потенциальная доработка: создать отдельное поле `call_list_visible_essence`, которое собирается из `call_essence/business_outcome/follow_up`, и уже его отдавать в renderer.

## H. Ограничители report_evidence / semantic_case

Файл:

- `core/app/agents/calls/reporting.py`

Quality values:

- usable qualities: `direct`, `indirect`, `weak`
- `insufficient` не используется как пригодный evidence.

Минимальные scores для semantic_case:

- `situation_day`: 65
- `call_breakdown`: 55
- `voice_of_customer`: 50
- `additional_situations`: 50
- `call_tomorrow`: 50

Минимальные problem-fit scores:

- `situation_day`: 70
- `call_breakdown`: 65
- `additional_situations`: 55

Минимальные scores для block_candidates:

- `situation_day`: 70
- `call_breakdown`: 65
- `voice_of_customer`: 50
- `money_on_table`: 50
- `tomorrow_follow_up`: 50
- `tomorrow_challenge`: 50
- `call_list_context`: 50

Влияние:

- LLM2 может дать смысл, но Report Layer не возьмет его в блок, если score/role/proof type не проходит.

Риск:

- качество защищается, но часть полезного материала может уйти в fallback;
- эти gates влияют не на сам факт анализа звонка, а на то, какие фрагменты анализа разрешено использовать в конкретных блоках отчета;
- например, LLM2 может корректно описать звонок, но если `semantic_case` не подходит по role/score/problem_fit, он не попадет в `Ситуацию дня` или `Разбор звонка`;
- из-за этого отчет может выглядеть "беднее", чем фактический анализ, потому что Report Layer предпочтет deterministic fallback вместо слабодоказанного блока;
- это полезно для защиты от неподтвержденных бизнес-выводов, но может быть слишком жестко для операторского preview и для таблицы "Все звонки дня".

Комментарий:

- Нужно разделять gates для коучинговых блоков и gates для справочной таблицы.
- Для `Ситуации дня` и `Разбора звонка` высокие пороги оправданы: эти блоки делают управленческий вывод и должны быть доказаны.
- Для `Все звонки дня` требования должны быть мягче: там нужна честная краткая суть звонка, а не полноценный coaching proof.
- Сейчас есть риск, что один общий подход к safety переносится на разные по назначению блоки.
- Потенциальная доработка: описать разные классы доказательности:
  - `business_report_claim` - высокий порог для выводов и рекомендаций;
  - `call_list_essence` - средний порог для краткой фактической сути;
  - `operator_diagnostic` - можно показывать слабые/неполные данные с пометкой.
- Тогда Report Layer не будет "обеднять" call list из-за правил, которые нужны только для сильных коучинговых блоков.

## I. Ограничители Call Breakdown Composer

Файл:

- `core/app/agents/calls/call_breakdown_composer.py`

Ограничители:

- для complex B2B нужно минимум 2 момента;
- максимум 4 момента;
- максимум 4 rows;
- каждая row должна иметь 4 колонки;
- `fragment_context_min_chars = 90`;
- stage_code нельзя менять относительно ожидаемого.

Влияние:

- LLM3/композитор может вернуть разбор, но он будет отброшен, если форма/количество/контекст слабые.

Риск:

- полезный разбор может не попасть в отчет из-за технической формы;
- composer ожидает структурный результат: 1-4 момента, 4 колонки в каждой строке, достаточный фрагмент, тот же stage_code;
- для complex B2B минимум повышается до 2 моментов, то есть короткий, но важный разбор может быть отклонен как недостаточный;
- `fragment_context_min_chars = 90` защищает от пустых цитат, но может отбрасывать лаконичные, но точные фрагменты;
- если LLM3 хорошо понял смысл, но вернул 5 моментов или строку не той формы, результат может уйти в fallback.

Комментарий:

- Эти ограничения нужны, потому что `Разбор звонка` является самым доказательным блоком: он показывает конкретный эпизод, подтверждение и действие.
- Но текущая форма больше защищает структуру таблицы, чем качество смысла.
- Для проверки качества LLM3 важно отдельно смотреть: результат был слабым по смыслу или был отброшен из-за формы.
- Потенциальная доработка: не отбрасывать полностью результат при небольших нарушениях формы, а нормализовать:
  - если моментов больше 4, выбрать 2-4 лучших;
  - если fragment короче 90, проверять его информативность, а не только длину;
  - если строка неполная, восстанавливать только структуру без добавления новых фактов;
  - если stage_code mismatch, помечать mismatch в diagnostics, но не всегда терять весь разбор.
- Для бизнес-отчета финальный блок все равно должен проходить proof/quality gate, но operator diagnostics должны показывать, почему LLM3-результат не попал в PDF.

## J. Ограничители PDF/render таблиц

Файл:

- `core/app/agents/calls/report_templates.py`

Основные hard-coded размеры:

- page width/height: `595 x 842`
- margin: `42`
- stage score col widths: `[190, 44, 46, 50, 135, 46]`
- call breakdown col widths: `[66, 152, 138, 155]`
- voice table col widths: `[116, 170, 225]`
- call list rows per page: `12`
- call list col widths для 4 колонок: `[118, 128, 174, 91]`
- call list body size: `6.35`

Дополнительные лимиты:

- `call_list` recommendation cell trim: `135`
- `call_list` essence cell trim: `220`

Влияние:

- даже если payload нормальный, renderer может ухудшить читаемость через ширины, размер шрифта и trim.

Риск:

- HTML может выглядеть нормально, а PDF в Telegram - хуже, если фактический путь рендера другой.

## K. Отключенные/скрытые секции

Файл:

- `core/app/agents/calls/report_templates.py`

Ограничители:

- `MANAGER_DAILY_MONEY_ON_TABLE_HIDDEN = True`
- `call_tomorrow` hidden, потому что merged into call list;
- `challenge` hidden.

Влияние:

- данные могут быть в payload, но не отображаться отдельной секцией.

Риск:

- кажется, что блок "не работает", хотя он скрыт на уровне шаблона.

## 2026-06-03 Execution Note: Timur 2026-06-01 Full-Stack Run

Статус внедрения задач аудита:

- `RL-T2` implemented / focused_tests_passed.
- `RL-T6` implemented / focused_tests_passed.
- `RL-T7` implemented / focused_tests_passed.
- `RL-T8` implemented / focused_tests_passed.

Дополнительные runtime-hardening правки, выявленные полным днем Тимура:

- `agreements` list может содержать строки, а не dict. Persist layer теперь
  нормализует строку в `{"agreement_text": ...}` и не падает.
- Report Layer теперь пропускает не-dict элементы в агрегируемых списках:
  `score_by_stage`, `criteria_results`, `gaps`, `recommendations`,
  `evidence_fragments`, `product_signals`.

Focused checks:

- `test_persist_analysis_accepts_string_agreement_items` passed.
- `test_manager_daily_stage_scores_ignore_non_dict_score_items` passed.

Итог последнего full-stack запуска:

- Manager: Тимур Жуматаев.
- Date: `2026-06-01`.
- Runtime: `AI_LLM_EXECUTION_MODE=openai_compatible`,
  subagent runtime disabled, simulation disabled.
- Delivery: Telegram test-only delivered, `message_id=368`.
- Artifact: `Ежедневный отчет - Тимур Жуматаев - 1 июня 2026.pdf`.
- Runner status: `blocked`.
- Report status: `review_required`.
- Readiness: `signal_report`.
- Reason: `incomplete_day_call_processing`.
- Relevant report-day calls: `34`.
- Ready analyses in report: `13`.
- Analysis coverage: `38.2%`.
- Manager-facing completeness blocker: `analysis_error=7`.

Важное наблюдение по LLM3:

- В последнем успешном delivery `LLM3` не появился в `observability.ai_layers`.
- `report_composer.enabled=false`.
- Значит отчет был построен deterministic/template Report Layer, а не через
  LLM3 composer, даже при `LLM3_ENABLED=true`.

Следующий аудит:

- Разобрать `analysis_build_failed:*:Analyzer did not admit call into layered
  LLM-2` по звонкам Тимура. Это сейчас главный blocker полного manager-facing
  отчета по дню.
- Отдельно проверить, как включается LLM3 composer path, если цель следующего
  теста — именно реальное выполнение LLM3 в Report Layer.

## 2026-06-03 Closeout Note

Пользователь визуально подтвердил исправления и разрешил закрыть текущие задачи
аудита/исправлений.

Дополнительная правка после ready-data-only LLM3 preview:

- `Все звонки дня -> Суть звонка` не должен использовать короткую
  compatibility-строку, если доступен richer context.
- Renderer теперь берет `call_list_context_rich` выше `call_list_context` и
  применяет лимит `700` символов вместо прежнего `220`.
- Это не меняет смысловые значения и не заставляет Report Layer пересочинять
  суть: слой отображения просто сохраняет уже подготовленный контекст звонка.

Проверки:

- `py_compile` для `report_templates.py` и теста template situation day: OK.
- `pytest -k "call_list_compact_rows"`: `2 passed, 5 deselected`.
- `node --check scripts/generate_docx_report.js`: OK.

Контрольная доставка:

- Manager: Тимур Жуматаев.
- Date: `2026-06-01`.
- Mode: `report_from_ready_data_only`.
- Delivery: Telegram test-only, `message_id=370`.
- Log: `review_packages/timur_20260601_llm3_report_only_call_essence_fix_20260603/run.log`.

Закрытые задачи:

- `RL-T2`: diagnostics / meaningful selection model.
- `RL-T6`: call-list essence/context rendering.
- `RL-T7`: evidence class for call-list essence.
- `RL-T8`: call breakdown diagnostics / soft normalization.

Открытый риск следующего теста:

- Полный день Тимура `2026-06-01` пока остается operator preview из-за неполного
  coverage (`ready_analyses=13`, `analysis_coverage=38.2%`), а не полноценным
  manager-facing complete report.
