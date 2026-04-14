# Rich Daily And Pilot Changeset Plan

## Назначение документа

Этот документ фиксирует согласованный changeset для следующего этапа развития `ai-sales-analyzer` без выполнения самих кодовых изменений в рамках текущего шага.

Документ объединяет два контура:
- доработки rich daily report для `manager_daily`;
- задачи подготовки и доведения manual reporting path до pilot-ready состояния.

Документ предназначен как handoff-артефакт для следующей реализации и должен снять архитектурные решения заранее, чтобы следующий исполнитель не принимал их заново "по месту".

## Текущее baseline-состояние проекта

### Что уже есть в коде

- В проекте уже реализован bounded `manual_reporting_pilot_v1`.
- Текущий reporting flow собран вокруг `core/app/agents/calls/reporting.py`.
- Поддерживаются два preset'а:
  - `manager_daily`
  - `rop_weekly`
- Для `manager_daily` уже есть:
  - source-aware discovery;
  - ingest missing calls;
  - reuse/build path;
  - readiness-layer с исходами `full_report`, `signal_report`, `skip_accumulate`;
  - normalized payload;
  - versioned rendering через template assets.
- Текущий renderer собран вокруг `core/app/agents/calls/report_templates.py` и versioned assets в `core/app/agents/calls/report_template_assets/`.
- Analyzer уже сохраняет в `scores_detail` часть полезных структурированных данных:
  - `classification.call_type`
  - `classification.scenario_type`
  - `follow_up.next_step_fixed`
  - `follow_up.next_step_type`
  - `follow_up.next_step_text`
  - `evidence_fragments`
  - `strengths`
  - `gaps`
  - `recommendations`
- Delivery, operator preview и bounded manual orchestration уже присутствуют в текущем runtime.

### Чего ещё нет

- Нет полноценного rich per-call reporting package, достаточного для целевого rich daily report без дополнительных эвристик по месту.
- Нет формализованного `call_outcome` как отдельного стабильного слоя данных для отчётности.
- Нет richer `customer_card` со stable structured полями и traceability.
- Нет отдельного day-level persisted summary/history слоя для воспроизводимых сравнений `today vs average / best`.
- Нет полноценного coaching-layer уровня целевого rich daily format.
- Текущий renderer/template для `manager_daily` остаётся bounded-представлением и не соответствует целевому формату из согласованных внешних документов.
- Pilot-ready контур ещё не закрыт полностью на уровне freeze policy, KPI evidence, operational runbook и fresh full-chain readiness.

### Standing architectural rule

- Core checklist scoring не переписывается.
- Все новые rich-reporting данные добавляются рядом с existing checklist scoring, а не вместо него.
- Основной фокус следующей реализации: `manager_daily`.
- `rop_weekly` не перерабатывается широко, кроме мест, где совместимость архитектуры или pilot-evidence этого прямо требует.

## Decision summary

### Основной принцип реализации

Следующая реализация идёт по слоям:
1. extraction/schema/rules
2. aggregation/history
3. coaching
4. renderer
5. pilot readiness closure
6. live/manual validation

### Default по хранению данных

Использовать следующий default:
- сначала расширять existing JSON/contracts и reporting-layer;
- не вводить новые persisted таблицы только ради отдельных extracted полей;
- новые таблицы и миграции добавлять только там, где нужен stable derived artifact:
  - day-history;
  - baseline/reference values;
  - reproducible day aggregation;
  - pilot KPI evidence layer.

### Default по scope

- `manager_daily` является primary target.
- `rop_weekly` остаётся bounded persisted-only path.
- Full dashboard и broad monthly scope в этот changeset не входят как обязательная часть первой реализации.
- Full call card и dashboard должны быть явно квалифицированы как:
  - либо обязательный artefact до пилота;
  - либо официально выведенный из стартового pilot scope.

## Public interfaces and type changes

Следующая реализация должна считать нижеописанные интерфейсные изменения заранее утверждёнными.

### 1. Analyzer/reporting contract

Нужно расширить analyzer/reporting contract без переписывания core checklist scoring.

Поверх текущего `scores_detail` должен появиться richer per-call reporting payload, который покрывает:
- `call_outcome`
- `customer_card`
- `next_step`
- `evidence_fragments`
- `opportunity_signals`
- `deal_value_hint`
- scenario segmentation fields, пригодные для day aggregation

Требование:
- checklist scoring должен остаться обратно совместимым;
- existing `strengths/gaps/recommendations/follow_up` не должны ломаться;
- новый reporting payload должен быть пригоден для deterministic day-level assembly.

### 2. `manager_daily` normalized payload

Нужно расширить normalized payload для `manager_daily`, чтобы он поддерживал:
- day summary верхнего уровня;
- pipeline warm leads;
- lost money / money-on-table block;
- stage summary с historical comparison;
- shortlisted follow-up block;
- coaching blocks;
- final Telegram wrapper, согласованный с PDF.

Требование:
- payload должен строиться из stable structured inputs, а не из ad-hoc reader heuristics в renderer;
- readiness-layer должен продолжать работать, но теперь опираться на richer payload readiness, а не только на bounded placeholder-friendly структуру.

### 3. DB/storage strategy

Согласованный storage-default:
- per-call rich fields по умолчанию хранить в existing JSON contract/persisted analysis payload;
- отдельные таблицы/миграции добавлять только для:
  - history/baseline;
  - stable day summary persistence;
  - pilot KPI evidence, если это невозможно надёжно считать из текущих persisted run artifacts.

Следствие:
- не вводить широкую нормализацию всех новых extracted сущностей в relational schema без явной необходимости;
- не делать broad DB redesign ради rich daily report.

## Work packages

## WP1. Расширение per-call reporting package

### Цель

Сделать так, чтобы по каждому звонку был доступен единый rich reporting package, достаточный для построения rich daily report без дополнительных LLM-вызовов на этапе рендера.

### Что уже есть в коде

- В analyzer уже есть `classification`, `follow_up`, `evidence_fragments`, `strengths`, `gaps`, `recommendations`.
- Часть classification already approved через `call_type` и `scenario_type`.
- Delivery и bounded reporting уже умеют использовать часть этих данных.

### Чего не хватает

Нужно добавить или расширить следующие данные:
- `call_outcome`
  - обязательная outcome-классификация звонка;
  - целевые значения:
    - `договор`
    - `перенос`
    - `отказ`
    - `открыт`
    - `тех/сервис`
  - дополнительно хранить:
    - краткое объяснение классификации;
    - признак `next_step_fixed`.
- richer `customer_card`
  - имя;
  - телефон;
  - компания;
  - роль;
  - направление ДО;
  - текущий инструмент;
  - тип лида;
  - температура;
  - названный объём;
  - названная боль;
  - для интерпретируемых полей:
    - `source`
    - `confidence`
- structured `next_step`
  - дата;
  - время;
  - канал;
  - кто делает шаг;
  - подтверждён ли шаг клиентом;
  - есть ли дедлайн.
- normalized `evidence_fragments`
  - цитата;
  - говорящий;
  - таймкод;
  - категория сигнала;
  - пригодность для renderer/coaching.
- `opportunity_signals`
  - интерес без шага;
  - мягкий уход;
  - техзвонок без допродажи;
  - не дожал ЛПР;
  - попросили КП/WhatsApp без договорённости;
  - упущенная альтернатива при возражении.
- `deal_value_hint`
  - оценка потенциала сделки;
  - источник расчёта:
    - CRM
    - названо в звонке
    - тарифная матрица
    - минимум

### Какие интерфейсы/контракты расширяются

- analyzer output contract;
- normalized persisted analysis payload;
- internal reporting extraction helpers;
- renderer input contract для `manager_daily`.

### Какие модули затрагиваются

- `core/app/agents/calls/analyzer.py`
- `core/app/agents/calls/orchestrator.py`
- `core/app/agents/calls/reporting.py`
- repo docs/sources, где фиксируется approved reporting contract

### Критерии готовности

- Для каждого звонка доступен единый rich per-call package.
- Один persisted call artifact позволяет построить:
  - статус звонка;
  - customer card;
  - следующий шаг;
  - evidence-based coaching inputs;
  - opportunity/lost-money signals.
- Existing checklist scoring и current downstream consumers не сломаны.

## WP2. Правила классификации и extraction

### Цель

Убрать плавающую интерпретацию rich-reporting полей и сделать extraction воспроизводимым.

### Что уже есть в коде

- Есть approved checklist и contract.
- Есть `call_type` / `scenario_type`.
- Есть evidence-aware outputs.

### Чего не хватает

Нужно формально зафиксировать versioned rules для:
- `call_outcome`
- `next_step`
- `opportunity_signals`
- `deal_value_hint`
- scenario segmentation

Особенно важно закрепить:
- когда звонок считается `переносом`;
- когда считается `открытым`;
- когда техзвонок относится к `тех/сервис`;
- что требуется, чтобы `next_step` считался зафиксированным;
- как детектируются фразы:
  - "скиньте в WhatsApp"
  - "подумаю"
  - "надо согласовать"
  - "у нас уже есть система"
  - "не сейчас"
  - resolved tech issue without upsell
- как работает fallback-порядок для `deal_value_hint`

### Какие интерфейсы/контракты расширяются

- analyzer prompt/contract layer;
- versioned reference rules doc;
- reporting normalization rules.

### Какие модули затрагиваются

- `core/app/agents/calls/analyzer.py`
- `core/app/agents/calls/prompts/`
- repo docs/reference sources for business rules

### Критерии готовности

- Есть один versioned reference для rich classification rules.
- LLM extraction и downstream code используют одни и те же правила.
- По спорному звонку оператор может объяснить, почему outcome/next-step/signal были определены именно так.

## WP3. Day aggregator для rich daily summary

### Цель

Преобразовать набор rich per-call результатов за день в воспроизводимый `day_summary`, который покрывает целевой daily report.

### Что уже есть в коде

- В текущем `reporting.py` уже есть bounded day-level сборка:
  - KPI overview
  - call outcomes summary
  - call list
  - recommendations
  - focus dynamics
  - readiness layer

### Чего не хватает

Нужно реализовать полноценный day aggregator, который считает:
- outcome aggregation;
- scenario counts;
- stage summary;
- warm pipeline summary;
- lost money summary;
- shortlist selection;
- pattern clustering;
- stable inputs для coaching blocks.

Итоговый `day_summary` должен покрывать:
- шапку rich daily report;
- pipeline тёплых лидов;
- блок "Деньги на столе";
- баллы по этапам;
- shortlist follow-up;
- signal clustering;
- сводный список всех звонков.

### Какие интерфейсы/контракты расширяются

- internal normalized day summary contract;
- `manager_daily` payload builder;
- readiness criteria for rich deliverable path.

### Какие модули затрагиваются

- `core/app/agents/calls/reporting.py`
- возможно новый bounded day-aggregator helper/module рядом с reporting slice

### Критерии готовности

- Из одного набора звонков за день строится deterministic `day_summary`.
- Повторный запуск на тех же persisted данных даёт тот же summary.
- `day_summary` достаточно полон, чтобы renderer не занимался business-logic выводами самостоятельно.

## WP4. History and baseline layer

### Цель

Сделать historical comparison и baseline metrics расчётными, а не декоративными.

### Что уже есть в коде

- Есть bounded `focus_criterion_dynamics`.
- В проекте уже есть `manager_progress`, но он не является полноценной history-базой для rich daily report.

### Чего не хватает

Нужно определить и реализовать:
- storage для daily history;
- rolling averages;
- best/reference values;
- baseline layer, не смешивающий разные сценарии звонков.

History должна поддерживать:
- `today vs average`;
- `today vs best`;
- repeated pattern frequency;
- repeat-call conversion comparison;
- reference values для challenge blocks.

### Какие интерфейсы/контракты расширяются

- persisted day-history schema;
- reporting lookup layer for history/baseline reads;
- renderer inputs for comparison metrics.

### Какие модули затрагиваются

- DB migration layer
- `core/app/core_shared/db/models.py`
- `core/app/agents/calls/reporting.py`
- tests around historical fallback behavior

### Критерии готовности

- Report может честно показывать `Сегодня / Среднее / Рекорд`.
- При отсутствии истории используется понятный fallback с явной маркировкой.
- История по менеджеру и сегменту сценария не смешивается методически неверно.

## WP5. Coaching layer

### Цель

Построить coaching-layer поверх `day_summary`, чтобы rich daily report был управленческим инструментом, а не просто аналитической выгрузкой.

### Что уже есть в коде

- Есть bounded `signal_of_day`, `key_problem_of_day`, `recommendations`.
- Есть evidence fragments и basic recommendation cards.

### Чего не хватает

Нужно реализовать coaching layer уровня rich daily format:
- coaching library с повторяемыми паттернами и речёвками;
- `situation_of_the_day`;
- `call_review`;
- `customer_voice`;
- `additional_situations`;
- `challenge_for_tomorrow`.

Каждый такой блок должен строиться:
- из day-level aggregated signals;
- с evidence binding;
- с repeatable selection logic;
- без превращения в произвольную генерацию "по настроению модели".

### Какие интерфейсы/контракты расширяются

- day_summary -> coaching input contract;
- coaching output contract for renderer;
- evidence binding rules for coaching blocks.

### Какие модули затрагиваются

- `core/app/agents/calls/reporting.py`
- возможно отдельный coaching helper/module
- prompt/config assets, если часть logic останется model-assisted

### Критерии готовности

- Coaching-блоки опираются на данные дня, а не на вольную генерацию.
- Каждый вывод привязан к звонкам или evidence fragments.
- Повторный прогон на тех же данных даёт тот же фокус и близкое содержание.

## WP6. Renderer/template upgrade до rich daily format

### Цель

Довести renderer до полного rich daily format и убрать structural gap между текущим bounded artifact и целевым report shape.

### Что уже есть в коде

- Есть versioned template assets.
- Есть PDF/HTML/text rendering.
- Есть текущая `manager_daily` template family.

### Чего не хватает

Нужно обновить final renderer/template так, чтобы он поддерживал целевые секции rich daily report:
- шапка;
- статусы;
- деньги на столе;
- pipeline;
- баллы по этапам;
- ситуация дня;
- разбор звонка;
- голос клиента;
- дополнительные 3 ситуации;
- челлендж;
- позвони завтра;
- список всех звонков;
- утренняя карточка/сопроводительный слой.

Также нужно:
- привести stage table к целевому виду;
- решить проблему полного списка звонков:
  - либо действительно показывать полный список;
  - либо формально выводить его в приложение;
- зафиксировать цветовую схему и semantic accents;
- синхронизировать Telegram wrapper с PDF artifact.

### Какие интерфейсы/контракты расширяются

- renderer model for `manager_daily`;
- template semantic/visual assets;
- PDF/Telegram output contract.

### Какие модули затрагиваются

- `core/app/agents/calls/report_templates.py`
- `core/app/agents/calls/report_template_assets/manager_daily/...`
- delivery wrapper logic, если Telegram-card должен стать richer и синхронным с PDF

### Критерии готовности

- Финальный PDF соответствует целевому rich daily format.
- Audit шаблона и фактического артефакта не выявляет structural mismatch.
- Telegram-card логически согласована с PDF и не противоречит ему.

## WP7. Pilot readiness and operational gaps

### Цель

Закрыть product/operational условия, без которых rich daily rollout нельзя считать pilot-ready.

### Что уже есть в коде

- Есть manual reporting pilot.
- Есть readiness-layer и structured statuses.
- Есть delivery path и recipient resolution.
- Есть source-aware `manager_daily`.

### Чего не хватает

Нужно зафиксировать и затем закрыть следующие pilot-ready условия:

#### Product and policy

- freeze baseline/version policy
  - какую версию логики замораживаем на пилот;
  - change policy в течение пилота;
  - с какого дня изменения считаются новой версией.
- правила сегментации сценариев
  - первичный;
  - повторный;
  - входящий;
  - вебинар/заявка;
  - после подписания;
  - поддержка;
  - смешанный.
- KPI evidence collection
  - как считаем coverage;
  - latency;
  - pipeline failures;
  - AI quality;
  - report reading/use;
  - business effect.
- delivery success definition
  - какой канал считается боевым;
  - что считается успешной доставкой;
  - нужен ли read/open evidence.

#### Operational

- operational runbook для blocked/partial runs
  - кто реагирует;
  - в какие сроки;
  - когда rerun;
  - где фиксируется инцидент.
- quota/full-chain readiness
  - закрыть quota/provider limitations;
  - подтвердить один fresh live full-chain run;
  - снять external blocker для pilot mode.

#### Scope decisions before pilot

- full call card:
  - либо делаем до пилота;
  - либо официально не обещаем как обязательный artefact.
- dashboard:
  - либо делаем до пилота;
  - либо формально выводим из start scope.

### Какие интерфейсы/контракты расширяются

- reporting version freeze policy;
- operational runbook docs;
- pilot KPI evidence contract;
- delivery status semantics, если потребуется richer success evidence.

### Какие модули затрагиваются

- runtime config and docs
- reporting/delivery slice
- manual operator workflow
- observability/readiness reporting

### Критерии готовности

- Есть зафиксированный pilot baseline и change policy.
- Есть agreed segmentation rules.
- Есть agreed KPI evidence method.
- Есть operational rule for blocked/partial runs.
- Fresh live full-chain run подтверждён.
- Scope по full call card/dashboard формально закрыт.

## Порядок реализации

Следующий этап реализации должен идти в таком порядке и не менять его без отдельного решения:

1. WP1: per-call reporting package
2. WP2: classification and extraction rules
3. WP3: day aggregator
4. WP4: history/baseline
5. WP5: coaching layer
6. WP6: renderer/template upgrade
7. WP7: pilot readiness closure
8. final manual/live validation

Причина:
- без WP1-WP2 richer report не на чем строить;
- без WP3-WP4 coaching и comparisons будут шумными и неповторяемыми;
- без WP5 renderer будет заполняться слабыми псевдо-объяснениями;
- без WP6 нельзя проверить соответствие фактического artefact целевому формату;
- без WP7 запуск пилота останется методически незакрытым.

## Test and acceptance plan

Следующая реализация должна считаться завершённой только при прохождении нижеуказанного тестового контура.

### Unit tests

- richer per-call normalization
- классификация `call_outcome`
- классификация structured `next_step`
- классификация `opportunity_signals`
- расчёт `deal_value_hint`
- deterministic `day_summary`
- historical comparisons
- fallback behavior without history
- coaching generators with evidence binding
- renderer tests на полный rich daily structure
- regression tests, подтверждающие, что existing checklist scoring не сломан

### Integration/reporting tests

- `manager_daily` payload builder with rich inputs
- readiness decision with richer content blocks
- renderer/template output for final PDF
- Telegram wrapper consistency with PDF
- delivery/preview semantics после richer payload expansion

### Manual/live checks

- fresh full-chain run
- readiness/report delivery
- recipient resolution
- blocked/partial run handling
- KPI evidence collection
- pilot baseline freeze verification
- segmentation correctness on representative mixed calls

## Explicit non-goals for this changeset

Следующий исполнитель не должен трактовать этот документ как разрешение на:
- broad redesign analyzer architecture;
- full automation loop;
- scheduler/beat/retries rollout;
- full monthly reporting implementation;
- broad dashboard platform build;
- mass relational normalization всех extracted rich fields.

## Final implementation assumptions

- В текущем шаге изменяется только один новый файл в `docs/`.
- Этот документ является согласованной точкой входа для следующего implementation step.
- Основной target следующей реализации: `manager_daily`.
- `rop_weekly` затрагивается только в пределах совместимости архитектуры, delivery semantics и pilot evidence.
- Rich daily report должен строиться поверх existing core scoring, а не требовать пересмотра approved checklist logic.
