# Временное ТЗ: новый механизм блока "Ситуация дня"

## Актуальный план: перенос report-writing из LLM2 в Report Layer + LLM3

Дата актуализации: 2026-05-19.

### Целевая архитектура

Мы не переносим весь LLM2 в Report Layer. Мы переносим из LLM2 все функции написания отчета.

Целевая схема:

```text
Transcript / STT
  -> LLM2 Call Analyzer
      -> structured facts per call
      -> evidence scenes
      -> manager actions
      -> customer signals
      -> gaps and counter-evidence
      -> next step facts

Daily Report
  -> Report Layer
      -> selects calls and patterns
      -> groups facts across the day
      -> validates evidence
      -> runs LLM3 composers
      -> repairs/blocks weak outputs
      -> renders PDF / Telegram
```

### Новая роль LLM2

LLM2 остается анализатором одного звонка.

Он должен извлекать:

- тип звонка;
- бизнес-исход;
- потребность клиента;
- клиентский контекст;
- роли, участники, масштаб, процесс;
- этапы продаж;
- действия менеджера;
- ошибки менеджера как факты, а не отчетный текст;
- customer signals;
- next step facts;
- evidence scenes с контекстом до/после;
- speaker attribution, если доступно;
- proof_type, quote_role;
- counter-evidence: что менеджер уже сделал частично или полностью.

LLM2 не должен быть автором финальных блоков отчета.

### Новая роль Report Layer + LLM3

Report Layer отвечает за отчетную логику:

- выбрать главный кейс дня;
- выбрать звонок для разбора;
- сгруппировать клиентские сигналы;
- проверить доказательства;
- проверить counter-evidence;
- решить, можно ли показывать блок менеджеру;
- собрать payload для PDF/Telegram.

LLM3 отвечает за report composition:

- редакторски собрать блок из фактов и сцен;
- объяснить проблему менеджеру понятным языком;
- не анализировать звонок с нуля;
- не выдумывать факты вне payload;
- возвращать структурированный JSON под конкретный composer.

Report Layer остается валидатором и safety gate:

- same call_id;
- enough context;
- no short quote as only proof;
- no contradiction with transcript scenes;
- no unsupported recommendation;
- fallback or repair when LLM3 response is weak.

### Что уже перенесено

1. `Ситуация дня`

- composer: `SituationDayComposer`;
- слой: Report Layer + LLM3;
- status: пилот реализован;
- LLM2 теперь источник фактов/кандидатов, но не финальный автор блока.

2. `Разбор звонка`

- composer: `CallBreakdownComposer`;
- слой: Report Layer + LLM3;
- status: пилот реализован;
- добавлены:
  - transcript scenes;
  - composition_rules;
  - mini-scene repair;
  - counter-evidence gate;
  - deterministic fallback.

Контрольный результат по Толегену 2026-05-14:

- PDF успешно отправлен в Telegram test delivery;
- `Ситуация дня`: `llm3_used=true`;
- `Разбор звонка`: `llm3_used=true`;
- `call_breakdown_quality=passed`;
- counter-evidence repair работает.

### Вывод после UI-прогона 2026-05-18

Прогон за 2026-05-18 показал, что проблема не сводится к одному блоку или одному менеджеру.

Фактическая картина:

- Толеген: новый механизм нашел verified `Ситуация дня` и `Разбор звонка`;
- Алишер: `Ситуация дня` не собрана, хотя были готовые анализы;
- Тимур: `Ситуация дня` не собрана, хотя были готовые анализы;
- `Разбор звонка` у Алишера и Тимура ушел в legacy fallback, потому что новый `CallBreakdownComposer` сейчас запускается только после verified `Ситуации дня`.

Root cause:

```text
Нет единого evidence layer для отчетных блоков.

LLM2 складывает полезные факты в разные места:
- block_candidates;
- semantic_case;
- manager_coaching_moments;
- call_report_summary;
- score_by_stage;
- situation_candidates;
- voice_of_customer;
- transcript-derived patterns.

Но каждый блок отчета сам решает, куда смотреть и чему верить.
Из-за этого факт может существовать, но не попасть в нужный composer.
```

Симптом:

- механизм пишет: "не найдена достаточно сильная мини-сцена";
- но на самом деле иногда мини-сцена или manager gap есть в другом источнике, например `manager_coaching_moments`;
- либо есть повторяющийся pattern по нескольким звонкам, но нет одного идеального звонка.

Пример по 2026-05-18:

- Алишер: в `manager_coaching_moments` был момент про слабую фиксацию следующего шага, но `SituationDayComposer` его не использовал как источник;
- Тимур: один `fit=true` block candidate был слишком слабым и с counter-evidence в транскрипте, поэтому gate правильно не принял его;
- у Тимура было много customer signals, но они не должны превращаться в `Ситуацию дня`, потому что это не manager gap.

Вывод:

Нужно не точечно чинить `SituationDayComposer`, а ввести общий слой evidence normalization/routing для всех блоков отчета.

## Roadmap v2: Evidence Registry + Block Router

### Цель этапа

Создать единый механизм, который до запуска block composers собирает, нормализует и маршрутизирует доказательства по отчетным блокам.

Новая целевая схема:

```text
Transcript / STT
  -> LLM2 Call Analyzer
      -> raw per-call facts
      -> report_evidence fragments
      -> coaching moments
      -> customer signals
      -> next-step facts

Daily Report
  -> Evidence Registry
      -> normalized evidence items
      -> proof type
      -> proof strength
      -> block suitability
      -> counter-evidence
      -> transcript scenes
  -> Block Router
      -> Situation Day candidates
      -> Call Breakdown candidates
      -> Voice Of Customer candidates
      -> Follow-up candidates
      -> Challenge candidates
      -> Additional Situations candidates
  -> LLM3 Block Composers
  -> Shared Quality Gates
  -> PDF / Telegram
```

### Новые сущности

#### Evidence Registry

Единый normalized item:

```json
{
  "evidence_id": "string",
  "call_id": "uuid",
  "manager_id": "uuid",
  "source": "block_candidates | semantic_case | manager_coaching_moments | transcript_pattern | call_report_summary | voice_of_customer | score_by_stage",
  "evidence_type": "manager_gap | customer_signal | service_issue | positive_case | follow_up_opportunity | neutral_summary",
  "proof_type": "direct_gap | sequence_inference | absence_in_context | customer_signal | service_issue | positive_case",
  "proof_strength": "strong | medium | weak | insufficient",
  "stage_code": "string|null",
  "problem_title": "string|null",
  "manager_gap": "string|null",
  "customer_context": "string|null",
  "dialogue_scene": "string|null",
  "supporting_quote": "string|null",
  "counter_evidence": [],
  "block_suitability": {
    "situation_day": "eligible | weak | forbidden",
    "call_breakdown": "eligible | weak | forbidden",
    "voice_of_customer": "eligible | weak | forbidden",
    "follow_up": "eligible | weak | forbidden",
    "challenge": "eligible | weak | forbidden",
    "additional_situations": "eligible | weak | forbidden"
  },
  "rejection_reasons": []
}
```

#### Block Router

Единая маршрутизация:

- `Ситуация дня`: только `manager_gap`, strong/medium proof, не service/refusal-only;
- `Разбор звонка`: verified `manager_gap` или лучший `manager_coaching_moment`, даже если `Ситуация дня` отсутствует;
- `Голос клиента`: только `customer_signal` с контекстом;
- `Позвони завтра`: `follow_up_opportunity`, открытый потенциал, согласованный next step;
- `Челлендж`: повторяющийся coaching pattern или stage gap;
- `Дополнительные ситуации`: вторичные manager gaps или positive cases;
- `Список звонков`: neutral/customer/service summaries без попытки делать из них coaching problem.

### Proof type policy

Нужно перестать требовать, чтобы каждая проблема доказывалась одной цитатой.

Поддерживаемые типы:

- `direct_gap`: фраза менеджера прямо показывает ошибку;
- `sequence_inference`: ошибка видна из последовательности диалога;
- `absence_in_context`: проблема в том, что нужное действие отсутствует в достаточно полной сцене;
- `customer_signal`: клиентский сигнал, не manager gap;
- `service_issue`: сервис/поддержка, не sales coaching;
- `positive_case`: удачный пример;
- `follow_up_opportunity`: есть следующий контакт или открытая возможность.

Для `absence_in_context` обязателен counter-evidence gate:

- проверить, не сделал ли менеджер нужное действие в другом месте транскрипта;
- если сделал частично, не формулировать как полный провал;
- если сцена слишком короткая, не показывать как доказанную проблему.

### Задачи следующего системного этапа

#### ER-1. Evidence Registry contract

Цель: описать и реализовать единый normalized evidence item.

Файлы:

- новый `core/app/agents/calls/report_evidence_registry.py`;
- тесты `core/tests/test_report_evidence_registry.py`;
- документация `docs/REPORT_EVIDENCE_CONTRACT.md`.

Задачи:

- собрать evidence items из `block_candidates`, `semantic_case`, `manager_coaching_moments`, `situation_candidates`, `voice_of_customer`, `call_report_summary`, transcript patterns;
- сохранить source lineage;
- нормализовать `evidence_type`, `proof_type`, `proof_strength`, `stage_code`;
- не терять rejected/weak candidates, а отдавать diagnostics.

#### ER-2. Manager coaching moments as first-class evidence

Цель: сделать `manager_coaching_moments` полноценным источником для `Ситуации дня` и `Разбора звонка`.

Задачи:

- извлекать `what_happened`, `what_better`, `dialogue_fragment`, `stage_code`, `evidence_quality`;
- строить mini-scene из `dialogue_fragment` или transcript repair;
- поддержать `absence_in_context`;
- отбрасывать moments без сцены и без возможности восстановить сцену из transcript.

#### ER-3. Block Router

Цель: централизованно решать, какой evidence item может питать какой блок.

Файлы:

- новый `core/app/agents/calls/report_block_router.py`;
- тесты `core/tests/test_report_block_router.py`.

Задачи:

- запретить customer signals как `Ситуация дня`;
- направлять customer signals в `Голос клиента` / `Позвони завтра`;
- направлять service issues в service/follow-up context, но не в sales coaching;
- выбирать fallback candidate для `Разбор звонка`, если нет verified `Ситуации дня`;
- отдавать diagnostics: почему каждый candidate принят/отклонен.

#### ER-4. Situation Day pattern-level mode

Цель: если нет одного идеального звонка, но есть повторяющийся доказуемый паттерн, строить `Ситуацию дня` по паттерну.

Формат:

- "В нескольких звонках повторилось...";
- 2-3 короткие сцены;
- общий manager gap;
- что делать иначе;
- критерий приемки: менеджер понимает не абстрактный вывод, а конкретное повторяющееся поведение.

Примеры паттернов:

- не фиксирует следующий шаг;
- не проверяет уместность разговора;
- не уточняет роль/ЛПР;
- рано предлагает продукт;
- не резюмирует потребность;
- оставляет клиента в режиме "я сам перезвоню".

#### ER-5. Decouple CallBreakdownComposer from SituationDayComposer

Цель: `Разбор звонка` не должен зависеть только от verified `Ситуации дня`.

Правило:

1. Если есть verified `Ситуация дня`, разбирать тот же звонок.
2. Если ее нет, брать лучший verified `manager_gap` / `manager_coaching_moment` из Evidence Registry.
3. Если нет доказанного manager gap, не показывать legacy-мусор; вернуть honest insufficient.

#### ER-6. Shared Quality Gate

Цель: единый gate для всех report blocks.

Проверки:

- есть `call_id`;
- есть usable scene или pattern-level scenes;
- proof type разрешен для блока;
- customer signal не используется как manager gap;
- service issue не используется как sales coaching;
- recommendation соответствует evidence type;
- нет counter-evidence;
- язык отчета русский;
- блок не дублирует другой блок;
- fallback не протаскивает слабые legacy rows.

#### ER-7. Apply to remaining composers

Экстраполировать проблему на остальные блоки:

- `VoiceOfCustomerComposer`: брать только routed `customer_signal`;
- `FollowUpComposer`: брать только routed `follow_up_opportunity`;
- `ChallengeComposer`: брать routed repeated pattern / stage gap;
- `AdditionalSituationsComposer`: брать secondary manager gaps / positive cases;
- `CallListContext`: брать neutral/service/customer summaries без coaching claims.

### Критерии приемки ER-этапа

На прогоне 2026-05-18:

- Толеген сохраняет verified `Ситуация дня` и `Разбор звонка`;
- Алишер: если есть доказанный `manager_coaching_moment`, `Разбор звонка` строится без зависимости от `Ситуации дня`;
- Тимур: слабый candidate с counter-evidence не проходит в `Ситуацию дня`;
- если нет одного сильного звонка, но есть повторяющийся паттерн, `Ситуация дня` строится в pattern-level mode;
- customer signals не становятся manager gaps;
- service issues не становятся sales coaching;
- diagnostics показывают, куда ушел каждый candidate и почему;
- legacy fallback не показывает строки вроде "Недостаточно данных..." как полноценный разбор.

### Что еще нужно перенести из LLM2

Приоритет 1. `Голос клиента`

Проблема:

- цитаты могут быть обрывочными;
- рекомендации иногда не соответствуют цитате;
- нет достаточного контекста;
- менеджеру непонятно, почему это важно.

Нужен:

`VoiceOfCustomerComposer`

Функции:

- собрать customer signals за день;
- сгруппировать похожие сигналы;
- выбрать 2-4 наиболее полезных клиентских голоса;
- расширить короткие цитаты до мини-сцен;
- проверить, что рекомендация соответствует смыслу сигнала;
- отбрасывать слабые/непонятные цитаты.

Приоритет 2. `Позвони завтра`

Проблема:

- рекомендации follow-up могут быть общими;
- не всегда учитывается реальная договоренность;
- может смешиваться интерес, отказ, сервисный вопрос и следующий шаг.

Нужен:

`FollowUpComposer`

Функции:

- брать только звонки с реальным next step или открытым потенциалом;
- разделять горячий/теплый/низкий приоритет;
- формулировать конкретную причину звонка;
- проверять дедлайн и договоренность;
- давать opening phrase, основанную на контексте звонка.

Приоритет 3. `Челлендж на завтра`

Проблема:

- челлендж может строиться от слабой метрики или случайного паттерна;
- не всегда связан с главным качественным провалом дня.

Нужен:

`ChallengeComposer`

Функции:

- брать повторяющийся паттерн дня;
- связывать challenge с `Ситуацией дня` и stage scores;
- формулировать измеримое действие на завтра;
- не выбирать challenge, если доказательств недостаточно.

Приоритет 4. `Деньги на столе` / pipeline / summary

Проблема:

- пока используются грубые оценки;
- без CRM это должно быть явно помечено;
- summary должно соответствовать реальным call outcomes.

Нужен:

`DaySummaryComposer` или deterministic summary layer.

Функции:

- связывать итоги дня с call outcomes;
- не делать неподтвержденных финансовых выводов;
- показывать assumptions;
- готовить короткое summary для Telegram/PDF.

Приоритет 5. Остальные report-specific тексты

Постепенно вынести из LLM2:

- финальные рекомендации дня;
- формулировки stage coaching;
- morning card text;
- любые `report block candidates`, которые сейчас выглядят как готовый текст отчета.

### План миграции по этапам

Этап A. Зафиксировать LLM2 Fact Contract.

- Описать, какие поля LLM2 обязан отдавать как факты.
- Разделить facts и report prose.
- Добавить `counter_evidence` в контракт LLM2.
- Добавить требования к scenes: до/после, speaker, quote_role, proof_type.

Результат: LLM2 становится стабильным поставщиком сырья.

Этап B. Завершить `SituationDayComposer` и `CallBreakdownComposer`.

- Расширить counter-evidence gate на другие claims:
  - не назначил следующий шаг;
  - не выявил потребность;
  - не резюмировал;
  - не обработал возражение.
- Прогнать 2-3 менеджера и несколько дат.
- Определить, когда fallback допустим, а когда блок лучше скрывать.

Результат: два ключевых блока готовы к production pilot.

Этап C. Реализовать `VoiceOfCustomerComposer`.

- Новый LLM3 prompt.
- Новый payload contract.
- Quote expansion до мини-сцены.
- Recommendation consistency gate.
- Тест на кейс, где цитата `Ладно, хорошо я перезвоню` не должна превращаться в неподтвержденную рекомендацию про договор.

Результат: самый слабый оставшийся блок перестает зависеть от готового текста LLM2.

Этап D. Реализовать `FollowUpComposer`.

- Проверять реальные договоренности и next step facts.
- Генерировать приоритет и opening phrase.
- Блокировать follow-up, если нет доказанного повода.

Результат: `Позвони завтра` становится доказательным и полезным.

Этап E. Реализовать `ChallengeComposer`.

- Связать challenge с повторяющимся паттерном дня.
- Проверять, что паттерн доказан несколькими звонками или сильным кейсом.

Результат: челлендж становится коучинговым инструментом, а не случайным советом.

Этап F. Упростить LLM2 prompt.

После каждого перенесенного блока:

- удалить из LLM2 обязанность писать финальный report prose для этого блока;
- оставить только факты, сцены, сигналы, evidence;
- удалить дублирующие report-specific поля;
- обновить тесты контрактов.

Результат: LLM2 легче, стабильнее, дешевле в сопровождении.

### Критерии готовности полного переноса

LLM2 больше не пишет финальный отчетный текст.

Для каждого блока:

- есть отдельный composer;
- есть LLM3 prompt/contract или deterministic composer;
- есть quality gate;
- есть counter-evidence check, если блок содержит критику менеджера;
- есть fallback/insufficient mode;
- есть unit tests;
- есть preview comparison на реальных звонках;
- есть diagnostics в payload.

### Ближайшая следующая задача

Рекомендуемый следующий шаг:

`VoiceOfCustomerComposer`

Почему:

- это следующий самый проблемный блок после `Ситуации дня` и `Разбора звонка`;
- он прямо связан с исходными замечаниями: обрывочные цитаты, нет контекста, рекомендация не соответствует смыслу;
- перенос даст заметное улучшение качества отчета для менеджера.

## Цель

Переделать механизм формирования блока "Ситуация дня" так, чтобы он показывал менеджеру не короткий вывод с сомнительным фрагментом, а понятную доказательную сцену дня:

- что произошло;
- какой был бизнес-контекст клиента;
- где именно менеджер потерял качество разговора;
- почему это важно;
- что нужно было сказать или сделать;
- какая фраза поможет в следующий раз.

Проверочная цель: прогнать звонки Толегена Жангазиева за 2026-05-13, 2026-05-14 и 2026-05-15 и сравнить новый результат с ручным эталоном:

`TMP_TOLEGEN_SITUATION_DAY_MANUAL_2026-05-11_2026-05-17.md`

## Главная проблема текущего механизма

Сейчас Call Analyzer / LLM2 слишком много решает внутри анализа одного звонка:

- оценивает звонок;
- извлекает факты;
- пишет coaching hints;
- формирует кандидатов для report blocks;
- пытается заранее подготовить "Ситуацию дня".

Report Layer после этого часто выбирает один из готовых кандидатов, вместо того чтобы заново собрать дневной смысл из всех звонков.

Из-за этого "Ситуация дня" получается слабой:

- выбирается фрагмент, который легко процитировать, но он не всегда самый полезный;
- контекст клиента обрезан;
- ошибка менеджера не всегда доказана;
- не видна последовательность разговора;
- менеджер без памяти о звонке не понимает, почему сделан такой вывод.

## Предлагаемое изменение архитектуры

Оставляем текущий Report Layer, но добавляем внутри него отдельный composer:

`SituationDayComposer`

Новая логика:

`Call Analyzer / LLM2 -> факты и сцены по звонкам -> Report Layer -> SituationDayComposer -> Quality Gate -> отчет`

Call Analyzer больше не должен быть автором финального блока "Ситуация дня". Он должен быть поставщиком сырья.

## Роль Call Analyzer / LLM2 после изменения

LLM2 должен извлекать по каждому звонку:

- тип звонка;
- бизнес-исход;
- клиентский контекст;
- потребность;
- масштаб;
- роли участников;
- следующий шаг;
- договоренности;
- manager gaps;
- customer signals;
- coaching scenes;
- цитаты и соседний контекст;
- признаки сложного B2B-кейса.

LLM2 не должен финально решать, какая ситуация станет "Ситуацией дня" в отчете.

## Нужен ли LLM3

Да, LLM3 стоит рассмотреть как отдельный управляемый слой для report composition.

Предлагаемая роль LLM3:

`LLM3 = Report Composer / Editorial Reasoner`

LLM3 не анализирует аудио и не оценивает весь звонок с нуля. Он получает уже подготовленное сырье:

- краткие summaries звонков;
- транскриптные сцены;
- extracted facts от LLM2;
- список кандидатов;
- score/stage данные;
- business outcome;
- customer signals;
- manager gaps.

Задача LLM3:

- выбрать лучший эпизод дня;
- собрать полноценную "Ситуацию дня";
- объяснить проблему как редактор/коуч;
- вернуть структурированный блок;
- указать evidence references.

Почему LLM3 может быть полезен:

- проще управлять промптом для отчетной логики;
- можно менять формат блока без риска сломать анализ звонка;
- LLM2 разгружается;
- Report Layer получает отдельный смысловой шаг;
- легче A/B тестировать качество report composition.

Риск:

- появляется дополнительный LLM-вызов;
- нужно контролировать стоимость и latency;
- нужен строгий контракт ответа и quality gate.

Рекомендация:

Внедрять LLM3 только для `SituationDayComposer` как пилот. Если качество подтвердится, затем расширять на `CallBreakdownComposer`, `VoiceOfCustomerComposer` и другие блоки.

## SituationDayComposer: требования

### Входные данные

Для одного менеджера и одного дня:

- список всех звонков дня;
- транскрипты или transcript excerpts;
- сохраненные анализы LLM2;
- business outcomes;
- manager gaps;
- customer signals;
- coaching scenes;
- block candidates, если есть;
- данные о длительности и типе звонка;
- список failed / not_coachable анализов с кратким контекстом, если есть транскрипт.

### Выходные данные

Структурированный блок:

- `status`: `verified`, `insufficient`, `no_data`;
- `selected_call_id`;
- `problem_title`;
- `client_context`;
- `evidence_scene`;
- `manager_gap`;
- `why_it_matters`;
- `next_time_action`;
- `suggested_phrase`;
- `proof_type`: `direct_gap`, `sequence_inference`, `business_context_inference`;
- `proof_strength`: `strong`, `medium`, `weak`;
- `rejected_candidates`;
- `quality_diagnostics`.

### Критерии выбора ситуации

Composer должен выбирать не просто самый низкий score и не первую цитату, а лучший coaching episode по критериям:

- бизнес-значимость клиента;
- доказуемая ошибка или точка роста;
- понятный контекст;
- польза для менеджера;
- наличие конкретного следующего действия;
- связь с повторяющимся паттерном дня;
- возможность показать сцену без ручной правки.

### Паттерны, которые нужно поддержать

1. КП без микроквалификации.

Признак: клиент просит КП, менеджер соглашается отправить, но не выясняет объем, роль, процесс, критерии выбора, срок решения.

2. Сложный B2B-запрос без перевода в управляемый следующий шаг.

Признак: клиент описывает роли, юрлица, пользователей, объем, интеграции, юридический риск, но менеджер завершает "уточню/перезвоню" без демо, ЛПР, даты и резюме требований.

3. Интерес клиента без фиксации решения.

Признак: клиент явно проявляет интерес, но менеджер не закрепляет следующий шаг, участников, срок и цель следующего контакта.

4. Ошибка последовательности.

Признак: проблема доказывается не одной цитатой, а ходом разговора: что было до, что спросил клиент, что сделал менеджер после.

## Quality Gate для "Ситуации дня"

Блок считается непригодным, если:

- нет выбранного звонка;
- нет контекста клиента;
- есть только короткая цитата без предыстории;
- вывод не связан с доказательной сценой;
- проблема сформулирована абстрактно;
- рекомендация общая;
- непонятно, что именно менеджер должен изменить;
- перепутаны роли клиента/менеджера;
- блок нельзя понять, если менеджер не помнит звонок.

Если блок не проходит gate:

- выбрать следующего кандидата;
- если кандидатов нет, вернуть `no reliable situation day`.

## Разгрузка LLM2

По мере переноса задач в Report Layer / LLM3 нужно упрощать LLM2.

### Что убрать из LLM2 постепенно

1. Финальное написание "Ситуации дня".

LLM2 может давать кандидатов и сцены, но не финальный блок.

2. Финальное написание "Разбора звонка".

LLM2 должен давать manager gaps и evidence scenes. Разбор должен собирать composer.

3. Финальное написание "Голоса клиента".

LLM2 должен давать customer signals с контекстом. Composer должен выбирать и оформлять.

4. Дублирующие report-specific поля.

После появления composers убрать поля, которые существуют только для текущего рендера и дублируют друг друга.

### Что усилить в LLM2 вместо этого

- стабильное извлечение фактов;
- сцены с контекстом до/после;
- speaker attribution;
- proof_type;
- quote_role;
- counter_evidence;
- business significance;
- manager gap as fact, not report prose;
- next step facts.

## План реализации

### Этап 1. Спецификация контракта SituationDayComposer

- Описать входной payload.
- Описать выходной JSON.
- Описать статусы и reasons.
- Описать quality diagnostics.

Результат: документированный контракт.

### Этап 2. Первый SituationDayComposer в Report Layer

- Создать composer, который получает все звонки дня.
- Собирает candidate pool из LLM2 facts и transcript excerpts.
- Ранжирует кандидатов.
- Вызывает LLM3 или локальный deterministic composer для финальной редакторской сборки.
- Возвращает структурированный блок.

Результат: новый блок "Ситуация дня" без зависимости от готового `situation_candidate`.

### Этап 3. LLM3 pilot

- Добавить отдельный prompt для LLM3 только под `SituationDayComposer`.
- Запретить LLM3 выдумывать факты вне входного payload.
- Требовать evidence references.
- Требовать rejected candidates.
- Требовать reason, если надежной ситуации нет.

## Текущий статус пилота на 2026-05-18

### Что уже перенесено из LLM2

Финальное формирование двух блоков больше не должно полагаться на готовый текст LLM2:

1. `Ситуация дня`

- формируется в Report Layer через `SituationDayComposer`;
- LLM2 используется как источник фактов, сцен и кандидатов;
- LLM3 подключен как report composer;
- quality gate проверяет выбранный звонок, контекст, доказательность и пригодность блока.

2. `Разбор звонка`

- формируется в Report Layer через `CallBreakdownComposer`;
- блок привязан к тому же verified call_id, что и `Ситуация дня`;
- LLM3 подключен как writer по отдельному контракту;
- если ответ LLM3 слабый, включается deterministic fallback в Report Layer.

Важно: LLM2 пока не выключен из процесса полностью. Его роль меняется: он дает сырье и факты, но не должен быть автором финального текста этих блоков.

### Контрольный прогон Толегена

Проверочный отчет:

`core/review_packages/call_breakdown_llm3_quality_gate_2026-05-14_Толеген_Жангазиев/report_01/report_preview.txt`

Payload:

`core/review_packages/call_breakdown_llm3_quality_gate_2026-05-14_Толеген_Жангазиев/report_01/payload.json`

Результат:

- `Ситуация дня`: `report_evidence.situation_day_composer.v1`, `llm3_used=true`;
- выбран звонок `ec7d0d6a-7633-4c41-bafb-1cdafc58e3c7`;
- `Разбор звонка`: `report_evidence.call_breakdown_composer.v1`, тот же звонок;
- LLM3 для `Разбора звонка` был вызван, но не прошел gate;
- финальный `Разбор звонка` собрал fallback composer в Report Layer;
- итоговый блок содержит 3 доказательных момента: требования, следующий шаг, ценность.

### Следующие задачи

1. Усилить вход для `CallBreakdownComposer`.

- Передавать не только bounded context из `Ситуации дня`, но отдельные transcript scenes: потребность, уточнения, закрытие.
- Сохранять больше соседнего контекста вокруг ключевых реплик.
- Улучшить speaker attribution: `Клиент` / `Менеджер` вместо общего `Контекст`.

2. Усилить LLM3 contract для `Разбора звонка`.

- Требовать заполненные `rows` и `moments` одновременно.
- Для сложного B2B требовать 3 момента.
- Запрещать короткие фрагменты как самостоятельное доказательство.
- Требовать мини-сцену, понятную менеджеру без памяти о звонке.

3. Повторить прогон Толегена.

- Сравнить LLM3 writer против fallback;
- проверить, что LLM3 проходит gate без ручной правки;
- оценить, стал ли `Разбор звонка` менее абстрактным и лучше доказывает ошибку.

Статус на 2026-05-18: выполнено для Толегена за 2026-05-14.

- финальный отчет: `core/review_packages/call_breakdown_llm3_repaired_2026-05-14_Толеген_Жангазиев/report_01/report_preview.txt`;
- `Ситуация дня`: LLM3 прошел;
- `Разбор звонка`: LLM3 прошел;
- fallback для `Разбора звонка` не использовался;
- quality gate: `passed`;
- rows: 3.

Что изменилось в механизме:

- LLM3 получает несколько сцен звонка, а не только короткий excerpt из `Ситуации дня`;
- Report Layer расширяет короткий фрагмент LLM3 до мини-сцены, если в payload есть соседний контекст;
- для complex B2B задано системное правило: минимум 3 момента;
- добавлена эвристика speaker attribution для случаев, когда persisted diarization не разделила спикеров.

Оставшийся риск:

- LLM3 может сформулировать спорный момент, если в звонке есть counter-evidence. Например, по Толегену LLM3 выделил "Квалификацию участников", хотя менеджер частично задавал вопросы про пользователей. Следующий системный gate должен проверять не только наличие фрагмента, но и отсутствие опровергающих действий менеджера.

4. После стабилизации перенести тот же подход на `Голос клиента`.

- Сейчас этот блок все еще может давать обрезанные цитаты и несвязанные рекомендации;
- нужен отдельный `VoiceOfCustomerComposer`, который будет группировать клиентские сигналы с контекстом и проверять соответствие рекомендации.

Результат: управляемый report-composition вызов.

### Этап 4. Quality Gate

- Проверить полноту контекста.
- Проверить доказательность сцены.
- Проверить связь рекомендации с проблемой.
- Проверить роли реплик.
- Проверить, что блок понятен без памяти о звонке.

Результат: слабые блоки не проходят в отчет.

### Этап 5. Упрощение LLM2 prompt

- Убрать из LLM2 обязанность финально писать "Ситуацию дня".
- Оставить извлечение фактов, сцен и кандидатов.
- Сократить дублирующие report fields.
- Добавить требования к evidence scene и speaker attribution.

Результат: LLM2 становится легче и стабильнее.

### Этап 6. Проверка на Толегене

Прогнать:

- 2026-05-13;
- 2026-05-14;
- 2026-05-15.

Сравнить с ручным эталоном:

`TMP_TOLEGEN_SITUATION_DAY_MANUAL_2026-05-11_2026-05-17.md`

## Критерии приемки

Для каждого из трех дней новый механизм должен:

- выбрать тот же звонок, что в ручном эталоне, или объяснимо выбрать лучший;
- дать полный контекст клиента;
- показать доказательную сцену;
- объяснить конкретную ошибку менеджера;
- дать конкретное действие на следующий раз;
- не использовать обрывочную цитату как единственное доказательство;
- не путать роли клиента и менеджера;
- получить `proof_strength = strong` или объяснить, почему доказательство только medium;
- пройти quality gate.

## Метрики сравнения

Оцениваем каждый блок по шкале 0-2:

- `business_relevance`: выбран значимый кейс;
- `context_completeness`: понятен контекст клиента;
- `evidence_quality`: сцена доказывает проблему;
- `manager_gap_clarity`: понятно, что менеджер сделал не так;
- `action_specificity`: рекомендация конкретна;
- `no_hallucination`: нет фактов вне транскрипта;
- `manager_readability`: менеджер поймет блок без памяти о звонке.

Цель: минимум 11 из 14 баллов по каждому дню.

## Открытые вопросы

1. Делать LLM3 обязательным или fallback-опцией?
2. Какой лимит контекста давать LLM3 на день: все звонки или top-N кандидатов?
3. Нужно ли LLM3 видеть полные транскрипты или только подготовленные сцены?
4. Должен ли composer выбирать только продажные кейсы или иногда сервисный звонок тоже может быть "Ситуацией дня"?
5. Как хранить результат composer: в report payload, отдельной таблице или generated draft?

## Рекомендация по следующему шагу

Начать с пилота:

1. Сделать `SituationDayComposer` только для блока "Ситуация дня".
2. Добавить LLM3 prompt для редакторской сборки блока.
3. Прогнать Толегена за 13-15 мая.
4. Сравнить с ручным эталоном.
5. После подтверждения качества перенести этот подход на "Разбор звонка" и "Голос клиента".

---

## Обновление статуса на 2026-05-18

Пилот `SituationDayComposer` реализован и подключен в Report Layer.

Реализованные файлы:

- `core/app/agents/calls/situation_day_composer.py`
- `core/app/agents/calls/prompts/situation_day_composer_v1.md`
- `core/app/agents/calls/reporting.py`
- `core/tests/test_situation_day_composer.py`

LLM3 подключен через существующий routing-механизм, аналогично LLM2:

- `LLM3_ENABLED=true/false`;
- `AI_LLM3_ROUTING_POLICY`;
- `AI_LLM3_PROVIDERS_JSON`;
- `AI_LLM3_FIXED_ACCOUNT_ALIAS`;
- `OPENAI_API_KEY_LLM3_MAIN`.

Проверочный прогон Толегена за 2026-05-14:

- отчет: `core/review_packages/situation_day_llm3_pilot_2026-05-14_Толеген_Жангазиев/report_01/report_preview.txt`;
- payload: `core/review_packages/situation_day_llm3_pilot_2026-05-14_Толеген_Жангазиев/report_01/payload.json`;
- краткий обзор: `TMP_TOLEGEN_LLM3_REPORT_2026-05-14.md`.

Результат LLM3:

- `llm3_enabled=true`;
- `llm3_used=true`;
- `llm3_error=null`;
- route alias: `llm3_main`;
- model: `gpt-4o`.

Выбранная ситуация:

- звонок `ec7d0d6a-7633-4c41-bafb-1cdafc58e3c7`;
- дата/время: 2026-05-14 09:48;
- клиент/телефон: `+77768578827`;
- тема: "Сложный B2B-запрос не переведен в управляемый следующий шаг";
- source: `transcript.pattern_inference`;
- evidence packet: `verified / strong`.

Вывод по пилоту:

`SituationDayComposer` решает основную проблему блока "Ситуация дня" лучше старого механизма:

- выбран смыслово сильный кейс, а не удобная короткая цитата;
- контекст клиента стал связан с выводом;
- проблема менеджера объясняется как последовательность разговора;
- рекомендация стала конкретнее;
- блок можно понять без памяти о звонке.

Ограничение:

`Разбор звонка` пока остается старым блоком и может быть слабее новой "Ситуации дня". В текущем прогоне он показал:

> Недостаточно подтверждённых фрагментов для детального разбора по фокусному этапу.

То есть новый механизм улучшил выбор и объяснение ситуации дня, но следующий блок не умеет разложить выбранный кейс по ошибкам менеджера.

---

## Следующий шаг: CallBreakdownComposer

### Цель

Создать отдельный composer для блока "Разбор звонка", чтобы он не дублировал "Ситуацию дня" и не проваливался в абстрактный текст, а раскладывал выбранный звонок по конкретным ошибкам менеджера.

Нужное поведение:

`Ситуация дня` отвечает на вопрос: "какая главная проблема/точка роста дня?"

`Разбор звонка` отвечает на вопрос: "где именно в выбранном звонке менеджер ошибся, что надо было сказать/сделать иначе, и как это повлияло на ход разговора?"

### Почему это нужно

После пилота видно, что `SituationDayComposer` выбрал правильный звонок Эльдара, но старый `call_breakdown` не смог качественно разобрать его по шагам.

Проблема старого блока:

- он зависит от `report_evidence.block_candidates.call_breakdown`;
- не всегда совпадает с новой `Ситуацией дня`;
- может вернуть insufficient, хотя для выбранной ситуации есть хороший транскриптный контекст;
- не раскладывает сложный B2B-звонок по управляемым продажным действиям.

### Архитектура

Добавить:

`CallBreakdownComposer`

Поток:

`SituationDayComposer -> selected_call_id + evidence_packet -> CallBreakdownComposer -> Quality Gate -> report call_breakdown`

Если `SituationDayComposer` вернул `verified`:

- `CallBreakdownComposer` должен в первую очередь разбирать тот же `selected_call_id`;
- использовать `situation_day_evidence_packet.dialogue_excerpt`;
- расширить контекст вокруг выбранной сцены;
- найти 2-4 конкретных момента;
- объяснить, что было не так и как надо было сделать.

Если `SituationDayComposer` не вернул `verified`:

- использовать старую логику `call_breakdown` как fallback.

### Входные данные CallBreakdownComposer

- `selected_call_id` из `SituationDayComposer`;
- полный transcript выбранного звонка;
- `situation_day_evidence_packet`;
- `situation_day_coaching_view`;
- LLM2 facts по звонку:
  - `score_by_stage`;
  - `manager_coaching_moments`;
  - `block_candidates.call_breakdown`;
  - `semantic_case`;
  - `call_report_summary`;
  - `recommendations`;
- stage/focus данные отчета;
- call metadata для ссылки на звонок.

### Выходные данные CallBreakdownComposer

Структура должна быть совместима с текущим `call_breakdown` payload:

- `is_placeholder`;
- `call_id`;
- `client_label`;
- `client_phone`;
- `date_label`;
- `time_label`;
- `client_call_reference`;
- `stage_code`;
- `stage_name`;
- `rows`;
- `moments`;
- `summary_line`;
- `source_note`;
- `call_breakdown_source`;
- `call_breakdown_evidence_strength`;
- `call_breakdown_fragment_present`;
- `selection_diagnostics`;
- `call_breakdown_quality`.

Каждый `moment` должен содержать:

- `moment`;
- `what`: что сделал менеджер;
- `moment_summary`: почему это проблема;
- `supporting_quote` или `dialogue_context`;
- `better`: что сделать иначе;
- `suggested_phrase`;
- `proof_type`;
- `quote_role`;
- `proof_explanation`.

### Требования к содержанию

Для звонка Эльдара 2026-05-14 composer должен разобрать минимум такие моменты:

1. Менеджер услышал сложный B2B-контекст, но не собрал его в резюме.

Пример смысла:

- клиент: сеть школ, 16 школ, общий кабинет, разделение доступа, головной офис;
- проблема: менеджер уточнял детали, но не зафиксировал карту требований;
- лучше: "Правильно понял: 16 школ, общий кабинет, роли по школам, головной офис видит всё. Верно?"

2. Менеджер не перевел запрос в управляемый next step.

Пример смысла:

- клиент спрашивает, можно ли настроить сценарий;
- менеджер отвечает "Давайте сейчас уточню";
- проблема: нет демо/созвона, участников, времени, цели следующего шага;
- лучше: "Я уточню техническую часть, но предлагаю сразу назначить 20 минут и показать сценарий по вашим школам. Кто должен быть на встрече?"

3. Менеджер не усилил ценность решения.

Пример смысла:

- клиент говорит о юридической значимости, SMS, ЭЦП, доступах;
- проблема: менеджер отвечает функционально, но не связывает решение с рисками и управлением процессом;
- лучше: "Здесь важно не просто подписать документ, а настроить роли и юридически надежный маршрут по всем школам."

### Quality Gate для CallBreakdownComposer

Блок не проходит, если:

- выбран не тот звонок, что в `SituationDayComposer`, без явной причины;
- нет минимум 2 моментов для сложного B2B-звонка;
- момент строится только на общей рекомендации без сцены;
- `supporting_quote` противоречит выводу;
- нет конкретной фразы или действия;
- блок повторяет "Ситуацию дня" одним абзацем;
- менеджеру непонятно, где именно он ошибся.

### LLM3 для CallBreakdownComposer

LLM3 можно использовать, но только как report-composer:

- получает bounded payload по одному выбранному звонку;
- не анализирует все звонки заново;
- не выдумывает факты;
- возвращает структурированный `call_breakdown`;
- обязан указывать evidence refs;
- при нехватке доказательств возвращает `insufficient`.

Нужно создать prompt:

`core/app/agents/calls/prompts/call_breakdown_composer_v1.md`

### Задачи для агентов

#### Агент 1. Контракт и интеграция

Цель: спроектировать контракт и точку интеграции `CallBreakdownComposer`.

Задачи:

- изучить текущие функции:
  - `_build_call_breakdown_from_report_evidence`;
  - `_build_call_breakdown_from_situation_day_packet`;
  - `_apply_call_breakdown_quality_gate`;
  - `_reduce_situation_call_breakdown_repetition`;
- определить минимальный совместимый output;
- предложить место вызова после verified `situation_day_evidence_packet`;
- описать fallback на старую логику.

Результат:

- короткий технический план;
- список файлов для изменения;
- риски совместимости.

#### Агент 2. Реализация composer

Цель: реализовать изолированный `CallBreakdownComposer`.

Задачи:

- создать `core/app/agents/calls/call_breakdown_composer.py`;
- добавить input adapter для выбранного звонка;
- собрать transcript scenes вокруг ключевых B2B-сигналов;
- построить deterministic fallback writer;
- добавить LLM3-ready writer;
- вернуть payload, совместимый с текущим `call_breakdown`.

Результат:

- новый composer;
- unit tests;
- без изменения доставки и PDF.

#### Агент 3. Prompt и тестовые кейсы

Цель: подготовить LLM3 prompt и тесты качества.

Задачи:

- создать `core/app/agents/calls/prompts/call_breakdown_composer_v1.md`;
- описать вход/выход;
- добавить запрет на выдумывание фактов;
- добавить обязательные требования к 2-4 моментам;
- подготовить тест на кейс Эльдара 2026-05-14;
- проверить, что блок не повторяет "Ситуацию дня".

Результат:

- prompt;
- focused tests;
- expected output для кейса Толегена.

### Задачи для нас с пользователем

1. Согласовать, что `Разбор звонка` должен разбирать тот же звонок, что и `Ситуация дня`, если ситуация verified.

2. Согласовать формат:

- оставить таблицу `Момент / Что было / Фрагмент / Рекомендация`;
- или перейти к более читаемому формату:
  - "Момент";
  - "Что произошло";
  - "Почему это ошибка";
  - "Как сказать/сделать лучше";
  - "Фрагмент".

3. После реализации прогнать Толегена за 2026-05-14 и сравнить:

- старый `Разбор звонка`;
- новый `CallBreakdownComposer`;
- ручное понимание звонка.

4. После приемки решить, переносим ли тот же подход на `Голос клиента`.

### Критерии приемки следующего шага

На отчете Толегена за 2026-05-14:

- `Ситуация дня` остается verified и выбирает звонок Эльдара;
- `Разбор звонка` разбирает тот же звонок;
- есть минимум 2 конкретных момента;
- каждый момент содержит контекст, ошибку, доказательство и альтернативное действие;
- блок не дублирует "Ситуацию дня";
- менеджер понимает, что именно нужно поменять в поведении;
- LLM3 usage и fallback отражены в diagnostics.

Минимальная оценка по шкале 0-2:

- `same_call_alignment`: 2;
- `moment_specificity`: 2;
- `evidence_quality`: 2;
- `action_specificity`: 2;
- `non_duplication`: 2;
- `manager_readability`: 2.

Цель: 10 из 12 минимум.

## Обновление 2026-05-18: VoiceOfCustomerComposer

### Что перенесено

Блок `Голос клиента` переведен на отдельный report-composer:

- новый файл `core/app/agents/calls/voice_of_customer_composer.py`;
- prompt `core/app/agents/calls/prompts/voice_of_customer_composer_v1.md`;
- интеграция в `build_manager_daily_payload` после legacy-сборки блока;
- LLM3 используется только как writer поверх уже отобранных customer-signal candidates;
- deterministic fallback остается обязательным.

### Системные правила качества

Composer больше не должен пропускать в отчет короткую реплику без контекста:

- `quote_context` обязан содержать саму клиентскую реплику;
- вместо обрывка должна быть мини-сцена из звонка;
- рекомендация должна соответствовать типу клиентского сигнала;
- vague callback вроде `Ладно, хорошо, я перезвоню` отклоняется, если нет достаточной сцены;
- LLM3-ответ отклоняется, если смысл/действие не на русском;
- LLM3-ответ отклоняется, если переформулировал доказательство вместо фактического фрагмента.

Добавлены категории клиентских сигналов:

- запрос материалов/канала;
- запрос КП;
- договор/подписание;
- роли/доступы/демо;
- внутреннее обсуждение или перенос решения;
- возражение `текущее решение достаточно`;
- барьер доверия/безопасный канал.

### Контрольный прогон Толегена 2026-05-14

Preview:

`core/review_packages/voice_customer_composer_2026-05-14_Толеген_Жангазиев/report_01/report_preview.txt`

Результат по спорному кейсу:

- реплика `Ладно, хорошо, я перезвоню` была найдена как candidate;
- quality gate отклонил ее с причиной `vague_callback_without_context`;
- блок `Голос клиента` не стал строить рекомендацию про договор на основании этой слабой фразы;
- в отчет попал другой customer signal с мини-сценой и действием.

### Тесты

Пройдены:

- `python3 core/tests/test_voice_of_customer_composer.py`;
- `python3 -m py_compile core/app/agents/calls/voice_of_customer_composer.py core/app/agents/calls/reporting.py core/tests/test_manual_reporting.py core/tests/test_call_breakdown_composer.py`;
- `docker compose exec -T api pytest -q tests/test_voice_of_customer_composer.py tests/test_call_breakdown_composer.py tests/test_situation_day_composer.py`;
- `docker compose exec -T api pytest -q tests/test_manual_reporting.py -k voice_of_customer`.

### Следующий шаг

После push пользователь запускает через UI анализ звонков за 2026-05-18.

Проверить в результате:

- `Ситуация дня` берет новый composer;
- `Разбор звонка` берет `CallBreakdownComposer`;
- `Голос клиента` имеет `source_note=report_evidence.voice_of_customer_composer.v1`;
- в `Голос клиента` нет коротких orphan quotes без сцены;
- рекомендации соответствуют реальному customer signal;
- PDF и Telegram формируются штатно.

## Обновление 2026-05-19: Evidence Registry + Block Router

### Что реализовано

- добавлен общий `ReportEvidenceRegistry`, который собирает доказательства из `block_candidates`, `semantic_case`, `manager_coaching_moments`, `situation_candidates`, `voice_of_customer`, `call_report_summary`;
- добавлен `ReportBlockRouter`, который распределяет evidence items по блокам и объясняет отказы;
- `Report Layer` теперь уважает `block_suitability.fit=false`, чтобы customer-signal не попадал в `Ситуацию дня` или `Разбор звонка` как проблема менеджера;
- `Разбор звонка` больше не зависит только от verified `Ситуации дня`: если Situation Day не прошла, router может выбрать лучший manager-gap fallback;
- добавлен осторожный fallback для `Ситуации дня` из Evidence Registry, если есть manager-gap с контекстом или повторяющийся паттерн;
- в payload добавлены `report_evidence_registry_diagnostics` и `report_block_router_diagnostics`.

### Проверка 2026-05-18 ready-data-only

Команда:

`docker compose exec -T api python -m app.agents.calls.manual_reporting_runner --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 --preset manager_daily --mode report_from_ready_data_only --date-from 2026-05-18 --date-to 2026-05-18 --delivery-mode preview_only`

Результат:

- Алишер: `Ситуация дня` и `Разбор звонка` заполнены через Evidence Registry / CallBreakdownComposer;
- Тимур: слабый customer-signal больше не выбран как проблема менеджера; выбран manager coaching moment;
- Толеген: основной SituationDayComposer и CallBreakdownComposer продолжают работать;
- все заполненные `call_breakdown_quality.status=passed`.

### Остаточный риск

Качество текста fallback-блоков еще нужно human-review: механизм теперь не оставляет блоки пустыми и не смешивает типы доказательств, но формулировки `what_happened/what_was_missing` для registry fallback местами повторяются. Следующий шаг — улучшить writer-слой fallback, а не снова менять отбор доказательств.

## План следующего этапа: единый writer для `Ситуации дня`

Дата: 2026-05-19.

Статус на 2026-05-19: пилот реализован и проверен на ready-data-only прогоне за 2026-05-18.

### Цель

Убрать разный стиль и разную структуру `Ситуации дня` между менеджерами. Отбор evidence может оставаться многослойным, но финальный блок должен собираться одним writer/schema/template путем.

Целевая схема:

`sources -> Evidence Registry -> Block Router -> SituationDayWriter -> unified template`

### Проблемы из human-review

1. `Что произошло` иногда содержит сырой диалог вместо объяснения ситуации.
2. `Суть момента` есть не во всех путях и стоит ниже, чем нужно.
3. Разные источники дают разные лейблы: `Контекст из звонка`, `Подтверждение из звонка`.
4. Registry fallback для Тимура/Алишера слишком коротко заполняет `Что произошло`.
5. Registry fallback не генерирует `Варианты речёвок`.
6. Роли `Клиент` / `Менеджер` не всегда надежны, из-за чего фрагменты выглядят как сплошной текст.
7. В `Разбор звонка` есть лишняя мета-фраза `В звонке есть coachable-момент...`.

### Задачи для агентов

#### SDW-1. Единый контракт `SituationDayWriter`

Зона: `core/app/agents/calls/situation_day_writer.py`, tests.

Сделать:

- создать единый writer, который принимает selected/routed evidence item, transcript scene, diagnostics;
- возвращает единый контракт:
  - `moment_summary`;
  - `what_happened`;
  - `manager_error`;
  - `evidence_explanation`;
  - `next_time_action`;
  - `scripts`;
  - `role_confidence`;
  - `source_note`;
  - `quality`;
- запретить сырой диалог в `what_happened`;
- разрешить цитаты только как встроенное подтверждение с ролью: `Клиент: ...`, `Менеджер: ...`;
- добавить deterministic fallback без LLM3;
- добавить LLM3-ready path поверх того же контракта.

Критерий приемки:

- любой source path отдает одинаковые ключи;
- `what_happened` не является простым склеенным transcript;
- `scripts` всегда есть минимум 2, если блок verified.

#### SDW-2. Подключить writer ко всем путям `Ситуации дня`

Зона: `core/app/agents/calls/reporting.py`.

Сделать:

- убрать право `SituationDayComposer`, registry fallback и legacy path напрямую формировать финальный view;
- после выбора evidence всегда прогонять результат через `SituationDayWriter`;
- сохранить diagnostics о первичном источнике: composer / registry / legacy;
- сделать registry fallback не writer, а только selector.

Критерий приемки:

- у Толегена, Тимура, Алишера одинаковая структура блока;
- нет разных лейблов `Контекст из звонка` / `Подтверждение из звонка`;
- при разных source paths финальная структура совпадает.

#### SDW-3. Обновить шаблон `Ситуации дня`

Зона: `core/app/agents/calls/report_templates.py`.

Новая структура:

1. `Суть момента`;
2. `Что произошло`;
3. `В чем ошибка менеджера`;
4. `Как сделать лучше`;
5. `Варианты речёвок`.

Сделать:

- убрать отдельный блок `Контекст` / `Подтверждение из звонка`;
- доказательства встраивать в `Что произошло`;
- если роли неизвестны, не показывать сырой диалог как доказательство;
- `Суть момента` поставить выше `Что произошло`;
- `Варианты речёвок` рендерить всегда для verified блока.

Критерий приемки:

- в PDF/Telegram нет отдельного сплошного блока реплик;
- менеджер понимает ситуацию без памяти о звонке;
- все доказательства объясняют вывод, а не просто лежат рядом.

#### SDW-4. Role mapping для `Клиент` / `Менеджер`

Зона: STT metadata / report layer helpers.

Сделать:

- проверить текущую AssemblyAI diarization: `speaker_labels=True`, `speakers_expected=2`;
- добавить post-STT / report-layer role resolver:
  - по manager extension / направлению звонка;
  - по приветствию и self-introduction;
  - по типовым фразам менеджера;
- сохранять `speaker_role_confidence`;
- если confidence низкий, writer не должен выдавать сырой диалог как `Клиент/Менеджер`;
- добавить diagnostics `speaker_role_mapping_status`.

Критерий приемки:

- где роль уверенная, цитаты подписаны `Клиент` / `Менеджер`;
- где роль не уверенная, блок остается понятным через narrative summary, а не через сырой transcript;
- нет сплошного текста без указания ролей.

#### SDW-5. Убрать мета-фразу из `Разбор звонка`

Зона: `core/app/agents/calls/call_breakdown_composer.py`.

Сделать:

- заменить текст `В звонке есть coachable-момент...` на конкретное описание ошибки;
- `Что было` должно начинаться с поведения менеджера, а не с внутренней терминологии;
- добавить тест, что `coachable-момент` не появляется в rendered rows.

Критерий приемки:

- в отчете нет слова `coachable`;
- `Что было` звучит как конкретный разбор: `Менеджер не уточнил...`, `Менеджер завершил...`, `Менеджер не зафиксировал...`.

### Задачи для нас с пользователем

1. После реализации прогнать ready-data-only за 2026-05-18.
2. Проверить минимум три отчета: Толеген, Тимур, Алишер.
3. Оценить блок `Ситуация дня` по шкале 0-2:
   - единая структура;
   - понятность без памяти о звонке;
   - подтверждение встроено в объяснение;
   - роли понятны или сырой диалог скрыт;
   - есть конкретные речёвки;
   - нет дублирования с `Разбором звонка`.
4. Цель: минимум 10/12 по каждому менеджеру.

### До повторного UI-прогона 18 мая нужно закрыть

- SDW-1;
- SDW-2;
- SDW-3;
- SDW-5;
- минимальный SDW-4 на report-layer уровне.

Полный STT role resolver можно вынести вторым этапом, если текущих metadata не хватит.

## Реализация SDW v1: 2026-05-19

### Что сделано

- создан `SituationDayWriter`;
- все выбранные `Ситуации дня` проходят через единый writer перед рендером;
- шаблон блока унифицирован:
  - `Суть момента`;
  - `Что произошло`;
  - `В чем ошибка менеджера`;
  - `Как сделать лучше`;
  - `Варианты речёвок`;
- отдельный mini-card `Контекст` / `Подтверждение из звонка` убран из `Ситуации дня`;
- при низкой уверенности в ролях writer не подписывает сырой диалог как `Клиент` / `Менеджер`;
- доказательный фрагмент встраивается в `Что произошло`;
- `Разбор звонка` больше не рендерит внутреннюю фразу `coachable-момент`.

### Проверка на 2026-05-18

Preview-only ready-data-only:

`/tmp/ui_2026-05-18_sdw_rerun_v3.json`

Результат:

- Алишер: writer applied, `scripts_count=2`, `call_breakdown_quality=passed`, нет `Контекст из звонка`, нет `coachable`;
- Тимур: writer applied, `scripts_count=2`, `call_breakdown_quality=passed`, нет `Контекст из звонка`, нет `coachable`;
- Толеген: writer applied, длинная склейка реплик больше не попадает в `Что произошло`; `scripts_count=2`, `call_breakdown_quality=passed`.

### Проверки

- local unittest focused suite: `16 tests OK`;
- docker pytest focused suite: `37 passed`;
- ready-data-only preview 2026-05-18 completed.

### Остаток

`role_confidence` сейчас в основном `low`, потому что persisted STT содержит сырые speakers `A/B` или unknown, а не надежный mapping `client/manager`. Полный role resolver нужно делать отдельным следующим этапом на уровне STT/extractor/report-layer metadata.

## Новый целевой план: упростить `Ситуацию дня` через Daily LLM3 Composer

Дата: 2026-05-19.

### Почему меняем направление

SDW v1 улучшил форму, но не решает главный источник нестабильности: текущий механизм пытается собрать смысловой блок из множества report-facing фрагментов LLM2 и fallback-путей.

Текущая проблема:

`LLM2 report candidates -> registry/router -> writer -> template`

Это все еще зависит от того, насколько хорошо LLM2 заранее угадал финальный блок отчета.

Целевой механизм:

`LLM2 facts + transcript scenes for the day -> LLM3 Daily Situation Composer -> Report Layer verification -> Template`

### Новое разделение ответственности

#### LLM2

Роль: анализатор отдельного звонка.

LLM2 должен давать:

- summary звонка;
- stage/outcome;
- scores;
- manager gaps;
- strengths;
- customer signals;
- evidence fragments;
- transcript quality flags;
- call worthiness flags.

LLM2 не должен отвечать за финальный текст `Ситуации дня` и не должен решать, какой блок отчета использовать.

#### LLM3

Роль: daily report composer.

LLM3 должен:

- смотреть все звонки менеджера за день;
- использовать LLM2 facts как карту;
- использовать transcript scenes как подтверждение;
- выбрать одну лучшую обучающую ситуацию;
- объяснить ее менеджеру понятным языком;
- дать доказательство/мини-сцену;
- дать конкретную ошибку и речёвки;
- отклонить ситуацию, если доказательство слабое или противоречит transcript.

#### Report Layer

Роль: validator + renderer.

Report Layer должен:

- собрать input package для LLM3;
- проверить, что LLM3 не выдумал `call_id`;
- проверить, что quote/scene есть в transcript или persisted evidence;
- проверить обязательные поля;
- отрендерить;
- если verified блока нет, показать честное `Нет надежно подтвержденной ситуации дня`, а не собирать слабый fallback.

### Задачи для следующего этапа

#### DDC-1. Daily Situation input package

Зона:

- `core/app/agents/calls/reporting.py`;
- новый helper/module, если потребуется.

Сделать:

- собрать для каждого менеджера за день компактный пакет звонков:
  - `call_id`;
  - client label / reference;
  - outcome;
  - stage;
  - score;
  - LLM2 summary;
  - manager gaps;
  - strengths;
  - customer signals;
  - candidate evidence fragments;
  - transcript mini-scenes;
  - quality flags.
- ограничить размер пакета:
  - не весь transcript целиком;
  - только релевантные сцены/фрагменты;
  - top N calls по usefulness.
- добавить diagnostics:
  - `daily_situation_input_calls_count`;
  - `daily_situation_input_fragments_count`;
  - `daily_situation_input_sources`.

Критерий приемки:

- пакет можно сохранить в payload diagnostics;
- по нему понятно, какие звонки и фрагменты были доступны LLM3;
- в пакет не попадают service-only/noise calls как основные candidates.

#### DDC-2. `SituationDayDailyComposer` на LLM3

Зона:

- новый файл `core/app/agents/calls/situation_day_daily_composer.py`;
- prompt `core/app/agents/calls/prompts/situation_day_daily_composer_v1.md`;
- tests.

Сделать:

- LLM3 получает daily input package;
- выбирает одну ситуацию дня или возвращает `insufficient`;
- output contract:
  - `status`;
  - `selected_call_id`;
  - `situation_title`;
  - `moment_summary`;
  - `what_happened`;
  - `manager_error`;
  - `evidence_scene`;
  - `supporting_quote`;
  - `why_it_matters`;
  - `next_time_action`;
  - `scripts`;
  - `rejected_candidates`;
  - `selection_reason`;
  - `source_fact_ids`.
- запретить:
  - пересчитывать score;
  - менять stage/outcome без явного contradiction;
  - делать полный анализ звонка заново;
  - выбирать customer_signal как manager_gap;
  - выдумывать quote/call_id.

Критерий приемки:

- LLM3 выбирает ситуацию на уровне дня, а не только из заранее выбранного single candidate;
- transcript используется для контекста и доказательства;
- output уже похож на понятный report block, а не на набор полей.

#### DDC-3. Report Layer verification для Daily Composer

Зона:

- `core/app/agents/calls/reporting.py`;
- tests.

Сделать:

- проверить `selected_call_id` существует в дневном пакете;
- проверить `supporting_quote` или `evidence_scene` grounded в transcript/evidence;
- проверить обязательные поля;
- проверить, что выбранная ситуация является `manager_gap`, а не `customer_signal/service_issue`;
- если verification failed:
  - не запускать registry fallback для финального написания;
  - вернуть explicit insufficient result.

Критерий приемки:

- слабые/неподтвержденные ситуации не попадают в отчет;
- diagnostics объясняют отказ;
- нет скрытого возврата к старому fallback, который пишет слабую `Ситуацию дня`.

#### DDC-4. Упростить текущую цепочку `Ситуации дня`

Зона:

- `core/app/agents/calls/reporting.py`.

Сделать:

- сделать `SituationDayDailyComposer` primary path;
- оставить `SituationDayWriter` только как normalizer/compat layer, если нужен;
- отключить registry/legacy deterministic fallback как финального автора `Ситуации дня`;
- Evidence Registry оставить только как input source для daily package и diagnostics;
- старые пути сохранить за feature flag, если нужен rollback.

Критерий приемки:

Цепочка для `Ситуации дня` должна быть:

`build_daily_situation_input -> SituationDayDailyComposer -> verify -> SituationDayWriter/template`

А не:

`composer -> registry fallback -> legacy fallback -> deterministic fallback`.

#### DDC-5. Prompt simplification для LLM2

Зона:

- LLM2 prompt / contract docs;
- пока можно начать с документации и feature flag, без немедленной ломки текущего анализа.

Сделать:

- убрать из будущего LLM2 prompt ответственность за финальные report blocks;
- оставить structured call facts;
- явно разделить:
  - `call_analysis_facts`;
  - `report_block_candidates` deprecated / compatibility only.

Критерий приемки:

- LLM2 не обязан угадывать `Ситуацию дня`;
- новые отчеты используют LLM2 как fact map, а не как report writer.

### Что не делаем в этом этапе

- не переписываем весь отчет;
- не меняем scoring;
- не трогаем PDF-дизайн;
- не делаем полный STT role resolver;
- не удаляем старые поля LLM2 из БД;
- не переделываем `Голос клиента` и `Разбор звонка`, пока не подтвердим качество `Ситуации дня`.

### Проверка качества

Контрольный прогон:

- ready-data-only за 2026-05-18;
- менеджеры: Толеген, Тимур, Алишер;
- сравнение с текущим SDW v1 результатом.

Оценка 0-2:

- выбран действительно лучший обучающий момент дня;
- менеджер понимает ситуацию без памяти о звонке;
- доказательство встроено в объяснение;
- ошибка менеджера сформулирована как поведение, а не общий вывод;
- речёвки применимы к сцене;
- нет customer_signal/service_issue под видом manager_gap.

Цель:

- минимум 10/12 по каждому менеджеру;
- если composer возвращает insufficient, это считается допустимым только при понятной диагностике и отсутствии сильного manager-gap.

### Результат реализации пилота

Сделано:

- создан `core/app/agents/calls/situation_day_daily_input.py`;
- создан `core/app/agents/calls/situation_day_daily_composer.py`;
- создан prompt `core/app/agents/calls/prompts/situation_day_daily_composer_v1.md`;
- добавлены тесты для daily input и daily composer;
- `manager_daily` подключен к новой цепочке:

`daily input -> SituationDayDailyComposer / LLM3 -> Report Layer verification -> SituationDayWriter/template`

Что изменилось в механизме:

- `Ситуация дня` больше не пишется финально через старые legacy/registry/block/semantic fallback-пути;
- Evidence Registry используется как источник фактов и diagnostics, а не как автор финального блока;
- LLM3 выбирает manager-gap candidate на уровне дня и не должен пересчитывать score или делать полный анализ звонка;
- Report Layer проверяет выбранный call/quote и fail-closed возвращает explicit insufficient, если доказательство не проходит;
- если в evidence есть клиентский контекст, он теперь встраивается в `what_happened` как связка:

`Контекст звонка -> подтверждающий фрагмент -> проблема для разбора`

Проверка:

- `python3 -m unittest core.tests.test_situation_day_daily_input core.tests.test_situation_day_daily_composer core.tests.test_situation_day_writer core.tests.test_report_templates_situation_day core.tests.test_call_breakdown_composer` — passed;
- `docker compose exec -T api python -m pytest -q tests/test_situation_day_daily_input.py tests/test_situation_day_daily_composer.py tests/test_situation_day_writer.py tests/test_report_templates_situation_day.py tests/test_call_breakdown_composer.py` — passed, 25 tests;
- ready-data-only preview за `2026-05-18` сформировал verified `Ситуацию дня` через `report_evidence.situation_day_daily_composer.v1` для Алишера, Тимура и Толегена.

Наблюдение по качеству:

- после первого pilot preview блок все еще был слабым, потому что candidate мог содержать только одну реплику;
- механизм усилен на уровне input/candidate builder: теперь `Что произошло` строится не как одиночная цитата, а как понятное описание ситуации с контекстом и доказательством;
- оставшееся ограничение: `role_confidence` остается `low`, если persisted evidence содержит только одну роль. Это не решается текущим шагом без отдельного STT/diarization role resolver.
