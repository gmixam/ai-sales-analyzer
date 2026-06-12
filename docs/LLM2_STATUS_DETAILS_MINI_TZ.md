# Мини-ТЗ: статусные детали звонка для LLM2D и отчета

Дата: 2026-06-05
Статус: `implemented_first_pass`

## Implementation Note 2026-06-05

Первый pass внедрен:

- `LLM2D` prompt/contract обновлен: `final_normalized_analysis.status_details`
  входит в ожидаемый JSON output.
- Compact payload `llm2d_recommendations` получил короткий
  `status_details_contract`, чтобы схема была доступна без возврата тяжелого
  full contract.
- `llm2_layered_analysis.py` явно нормализует `status_details` и сохраняет его
  в top-level `scores_detail`.
- `llm_simulation.py` возвращает deterministic `status_details` для режима
  имитации.
- Report Layer сначала строит `call_feedback_summary.outcome` из
  `scores_detail.status_details`, если статус совпадает со статусом строки;
  при mismatch или отсутствии блока используется старый fallback.
- `owner` и часть `type` enum локализуются в manager-facing `Итог`.

Важно: старые сохраненные анализы не получают `status_details` автоматически.
Для проверки качества на историческом дне нужно перезапустить `LLM2D`/`LLM2` по
выбранным звонкам.

## Назначение

Сделать верхнеуровневые статусы звонков понятными и проверяемыми в отчете.
Сейчас `LLM2` определяет статус (`Договоренность`, `Перенос`, `Отказ`,
`Открыт`, `Тех/сервис`), но отчету часто не хватает структурной информации:
какая именно договоренность, почему отказ, на когда перенос, почему звонок
остался открытым, что именно было сервисным вопросом.

Нужно добавить в `LLM2D` отдельный структурный блок `status_details`, а Report
Layer должен выводить короткий `Итог` из этого блока.

## Принципы

- Верхнеуровневый статус не придумывается заново в Report Layer.
- За смысловую структуру статуса отвечает `LLM2D`.
- Report Layer только отображает готовые поля и применяет fallback для старых
  анализов без `status_details`.
- Для каждого статуса своя министруктура, а не один общий объект со смешанными
  полями.
- Заполняется только структура текущего статуса, остальные структуры `null`.
- Все поля должны быть на русском языке и основаны на звонке.
- Если данных нет, поле должно быть `null`, а не выдуманная догадка.
- В отчете выводится короткий `Итог`, а полный `status_details` хранится в
  payload / `scores_detail` для диагностики и будущих отчетов.

## Где формировать

Формировать блок нужно в `LLM2D`.

Причина:

- `LLM2A` собирает факты и сцены;
- `LLM2B` оценивает критерии;
- `LLM2C` проверяет доказательность;
- `LLM2D` уже отвечает за manager-facing выводы, рекомендации и упаковку
  результата анализа.

`LLM2D` должен получать финальный `business_outcome.status` и заполнить
министруктуру только для этого статуса. Он не должен менять сам статус.

## Общая обертка

```json
"status_details": {
  "status": "agreement | rescheduled | refusal | open | service",
  "agreement": null,
  "rescheduled": null,
  "refusal": null,
  "open": null,
  "service": null
}
```

## Что собираем по статусам

### Договоренность

```json
"agreement": {
  "type": "invoice | cp | demo | presentation | callback | documents | connection | consultation | other",
  "what_agreed": "о чем конкретно договорились",
  "manager_commitment": "что должен сделать менеджер",
  "client_commitment": "что должен сделать или подтвердить клиент",
  "owner": "manager | client | both | other | unknown",
  "deadline": "дата, время или период, если есть",
  "evidence": "короткая реплика или подтверждение из звонка"
}
```

### Перенос

```json
"rescheduled": {
  "reason": "почему перенесли",
  "return_when": "когда вернуться",
  "return_owner": "manager | client | both | other | unknown",
  "preparation_needed": "что подготовить до следующего контакта",
  "evidence": "короткая реплика или подтверждение из звонка"
}
```

### Отказ

```json
"refusal": {
  "type": "no_need | expensive | already_has_solution | not_decision_maker | not_relevant_now | competitor | no_budget | other",
  "reason": "почему отказался",
  "finality": "final | temporary | unclear",
  "return_condition": "при каком условии можно вернуться",
  "recommended_next_action": "закрыть / вернуться позже / уточнить у ЛПР / другое",
  "evidence": "короткая реплика или подтверждение из звонка"
}
```

### Открыт

```json
"open": {
  "why_open": "почему статус открыт",
  "missing_to_close": "чего не хватает для следующего статуса",
  "next_action": "логичный следующий шаг",
  "owner": "manager | client | both | other | unknown",
  "deadline": "срок, если есть",
  "evidence": "короткая реплика или подтверждение из звонка"
}
```

### Тех/сервис

```json
"service": {
  "type": "signing | access | registration | error | consultation | legal_product | transfer | internal | other",
  "request": "с каким вопросом обратился клиент",
  "action_taken": "что сделал менеджер",
  "follow_up_needed": true,
  "follow_up_action": "что нужно сделать дальше",
  "owner": "manager | client | support | legal | other | unknown",
  "sales_scoring_applicability": "limited | not_applicable",
  "evidence": "короткая реплика или подтверждение из звонка"
}
```

## Что выводим в отчет

В колонке `Итог / обратная связь` выводится не вся структура, а короткая строка
`Итог`, собранная из ключевых полей.

### Договоренность

```text
Итог: договорились — <what_agreed>; срок: <deadline>; ответственный: <owner>.
```

Пример:

```text
Итог: договорились — выставить счет; срок: сегодня; ответственный: менеджер.
```

### Перенос

```text
Итог: перенос — <return_when>; причина: <reason>; ответственный: <return_owner>.
```

Пример:

```text
Итог: перенос — после согласования; причина: клиенту нужно обсудить внутри; ответственный: менеджер.
```

### Отказ

```text
Итог: отказ — <reason>; тип: <type>; возврат: <return_condition>.
```

Пример:

```text
Итог: отказ — уже есть решение; тип: конкурент; возврат: если появится новый контрагент.
```

### Открыт

```text
Итог: открыт — <why_open>; следующий шаг: <next_action>; ответственный: <owner>.
```

Пример:

```text
Итог: открыт — интерес есть, срок не закреплен; следующий шаг: согласовать дату демо; ответственный: менеджер.
```

### Тех/сервис

```text
Итог: сервис — <request>; сделано: <action_taken>; дальше: <follow_up_action>.
```

Пример:

```text
Итог: сервис — вопрос по подписанию; сделано: объяснил порядок; дальше: проверить успешное подписание.
```

## Изменения в механизме

1. Обновить prompt/contract `LLM2D`.
2. Добавить `status_details` в JSON output `LLM2D`.
3. Обновить нормализацию в `llm2_layered_analysis.py`, чтобы блок не терялся
   при merge в финальный `scores_detail`.
4. Обновить Report Layer:
   - сначала брать `status_details`;
   - если `status_details` нет, использовать текущий fallback по
     `call_list_next_step`, `llm2_business_outcome_reason`,
     `llm2_business_outcome_evidence`, `reason`, `deadline`.
5. Обновить `call_feedback_summary.outcome`, чтобы он не дублировал
   `Суть звонка`, а отражал короткое подтверждение статуса.

## Совместимость со старыми анализами

Для уже сохраненных анализов `status_details` не появится автоматически.
До перегона `LLM2D` или всего `LLM2` Report Layer должен использовать fallback.

Это значит:

- новый контракт начнет полноценно работать на будущих анализах;
- для старых отчетов улучшение будет ограничено fallback-логикой;
- если нужно проверить качество `status_details` на старом дне, нужно
  перезапустить `LLM2D`/`LLM2` по выбранным звонкам.

## Тесты

- `LLM2D` contract test: output содержит `status_details`.
- Normalization test: `status_details` сохраняется в `scores_detail`.
- Report Layer test:
  - для `agreement` итог берет `what_agreed`, `deadline`, `owner`;
  - для `rescheduled` итог берет `return_when`, `reason`, `return_owner`;
  - для `refusal` итог берет `reason`, `type`, `return_condition`;
  - для `open` итог берет `why_open`, `next_action`, `owner`;
  - для `service` итог берет `request`, `action_taken`, `follow_up_action`.
- Fallback test: старый анализ без `status_details` продолжает рендериться.
- Regression test: `Итог` не дублирует длинную `Суть звонка`.

## Критерии приемки

- В `scores_detail` по каждому новому анализу есть `status_details`.
- Заполнена только структура текущего статуса.
- В отчете `Итог` коротко объясняет статус, а не пересказывает весь звонок.
- Для `Договоренности` видно, какая именно договоренность.
- Для `Переноса` видно, когда и почему вернуться.
- Для `Отказа` видно, почему отказ и можно ли вернуться.
- Для `Открыт` видно, почему не закрыли в другой статус.
- Для `Тех/сервис` видно, что было сервисным вопросом и что сделано.
- Старые анализы без `status_details` не ломают отчет.

## Решения / остаточные вопросы

1. `evidence` пока хранится только в payload / `scores_detail`, в PDF не
   выводится.
2. `owner` локализуется в отчете как `менеджер / клиент / обе стороны /
   поддержка / юристы / другой ответственный`.
3. Для `agreement.type` текущий enum можно расширять под специфику ЭДО после
   первых реальных примеров.
4. Для исторических отчетов нужен отдельный перезапуск `LLM2D`/`LLM2`; без
   этого Report Layer использует fallback.
