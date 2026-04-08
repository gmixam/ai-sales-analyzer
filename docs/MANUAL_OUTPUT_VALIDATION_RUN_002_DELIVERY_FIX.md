# MANUAL_OUTPUT_VALIDATION_RUN_002_DELIVERY_FIX

## Цель

Устранить критичный quality gap в compact manager-facing delivery для уже существующего persisted case и подтвердить fix без нового live intake/STT/analyzer run.

Проверяемый кейс:

- `interaction_id`: `2ea673d2-8a5c-4ab3-9e96-339392003b00`
- `analysis_id`: `5a8f8414-f59a-4671-8879-bac3bf5e2f4d`
- `external_id`: `384e3a87-3d38-4a84-9656-0feec40be59a`

## Что было сломано

### Structural root cause

1. Compact delivery renderer `CallsDelivery.build_notification_text()` ожидал approved/example-like shape:
   - `strengths[]`: `title`, `impact`
   - `gaps[]`: `title`, `impact`
   - `recommendations[]`: `priority`, `problem`, `better_phrase`
2. Persisted analysis у реального кейса содержал legacy criterion-based shape:
   - `strengths[]` / `gaps[]`: `criterion_code`, `comment`, `evidence`
   - `recommendations[]`: `criterion_code`, `recommendation`
3. Из-за этого formatter печатал:
   - `None: None`
   - `[medium] None -> None`
   - `None / None` для legacy score block

### Language root cause

1. В analyzer prompt не было жёстко зафиксировано, что business-facing fields должны быть на русском языке.
2. Persisted analysis у реального кейса содержал English business text в:
   - `summary.short_summary`
   - `summary.outcome_text`
   - `summary.next_step_text`
   - criterion-based comments / recommendations
3. Delivery renderer до фикса просто пробрасывал эти значения в Telegram card.
4. Transcript при этом уже был source-native и не требовал перевода.

## Какой fix выбран

Выбран комбинированный минимальный fix:

1. `Delivery-side normalization adapter`
- compact delivery теперь умеет читать и approved shape, и legacy criterion-based shape
- criterion names подтягиваются из `score_by_stage[*].criteria_results`
- пустые legacy values больше не печатаются как `None`

2. `Russian manager-facing render policy`
- business-facing delivery text локализуется на русский в render layer
- transcript/source fragments не переводятся
- system values не трогаются

3. `Analyzer-side future guard`
- `CallsAnalyzer` теперь нормализует legacy finding/recommendation shape к approved contract shape для будущих persisted outputs
- analyzer prompt дополнен явным language rule для business-facing fields

## Какие тесты добавлены

`tests/test_calls_delivery_text.py`

Проверки:

1. legacy persisted shape рендерится без:
   - `None: None`
   - `None / None`
   - `[medium] None -> None`
2. compact card для business-facing output рендерится на русском
3. transcript source text не переводится и не мутируется
4. analyzer normalization превращает legacy criterion-based shape в approved contract-like shape

Runtime result:

- `3 tests`
- `OK`

## Output Before

Критичные фрагменты до фикса:

- `Скоринг: None / None | 15/24 (62.5%, basic)`
- `Сильные стороны: - None: None`
- `Зоны роста: - None: None`
- `Рекомендации: - [medium] None -> None`
- `Eligibility: ...`
- `Follow-up: ...`
- English summary / outcome / next step inside Russian wrapper

## Output After

Фактический compact delivery preview после фикса и replay:

```text
Карточка звонка — ручная проверка
Interaction ID: 2ea673d2-8a5c-4ab3-9e96-339392003b00
Внешний код: 384e3a87-3d38-4a84-9656-0feec40be59a
Менеджер: Pilot Manager 212
Контакт: +77072221464
Дата/время: 2026-03-18T05:27:59+00:00
Длительность: 757 сек
Тип звонка: Продажи — первичный
Сценарий: Повторный контакт
Статус анализа: eligible / duration_ge_180_sec_and_sales_relevant

Краткое резюме: Менеджер подробно провёл клиента по возможностям подписки и доступу к документам.
Итог: Клиенту помогли с доступом к документам и базовыми возможностями сервиса.
Следующий шаг: С клиентом свяжется отдел сервиса и поможет по дальнейшим вопросам.

Скоринг по чек-листу: 15/24 (62.5%, Базовый)
Критический сбой: нет

Этапы:
- Первичный контакт: 6/8
- Квалификация и первичная потребность: 3/8
- Формирование предложения (презентация/КП): 6/8

Сильные стороны:
- Понятно обозначил причину звонка: Чётко обозначил цель звонка.
- Связал ценность продукта с контекстом клиента: Связал ценность решения с контекстом клиента.

Зоны роста:
- Выяснил, как сейчас устроен процесс / документооборот: Не уточнил, как у клиента сейчас устроен процесс.
- Объяснил решение ясно, без путаницы: Объяснение было понятным, но не хватило краткости.

Рекомендации:
- [средний] Отдельно уточнять, как у клиента сейчас устроен процесс, чтобы точнее подстраивать презентацию.
- [средний] Давать более краткие и понятные примеры, чтобы объяснение было яснее.

Дальнейшие действия: шаг зафиксирован — да; следующий шаг — С клиентом свяжется отдел сервиса и поможет по дальнейшим вопросам.; причина, если не зафиксирован — —
```

## Что подтверждено

1. `interaction_id` остался тем же
2. `analysis_id` остался тем же
3. `interactions_count = 1`
4. `analyses_count = 1`
5. `delivery replay` по existing persisted case выполнен успешно
6. Telegram target:
   - `74665909`
   - `status=sent`
7. `interaction.status = DELIVERED`
8. delivery audit обновлён:
   - `mode = delivery_replay`
   - `attempted_at = 2026-03-18T13:19:40.822239+00:00`
   - `error_message = null`
9. compact card больше не содержит:
   - `None: None`
   - `None / None`
   - `[medium] None -> None`

## Что всё ещё остаётся открытым

1. Existing persisted `analysis.scores_detail` у этого historical case не переписан задним числом и всё ещё содержит English business text внутри JSON.
2. Full manager card по approved format всё ещё не реализован как отдельный runtime artifact.
3. `analysis_result_excerpt` в delivery response остаётся technical/internal excerpt и может содержать historical English fields из persisted analysis payload.

## Language policy verification

- `transcript language preserved`: `yes`
- `business output translated to Russian`: `yes` for compact manager-facing delivery
- `allowed non-Russian values remaining`:
  - `eligible`
  - `duration_ge_180_sec_and_sales_relevant`
  - `Interaction ID`
  - reason: system values / technical identifiers

## Blocking Issue Verdict

- `blocking issue resolved`: `yes`

Почему:

- critical structural defect in compact manager-facing delivery removed
- manager-facing preview no longer leaks `None` placeholders
- business-facing card is now Russian in runtime delivery output
- transcript remained source-native
- analyzer top-level contract was not broken

## Recommended Next Step

Продолжать `Manual Output Validation` на следующих artifacts/cases без перехода в automation readiness.
