# MANUAL_OUTPUT_VALIDATION_RUN_003_SECOND_CASE

## Цель run

Провести `Manual Output Validation Run 003` на втором реальном persisted case, отличном от уже проверенного кейса:

- `interaction_id=2ea673d2-8a5c-4ab3-9e96-339392003b00`
- `analysis_id=5a8f8414-f59a-4671-8879-bac3bf5e2f4d`
- `external_id=384e3a87-3d38-4a84-9656-0feec40be59a`

Приоритет выбора:
- case с `agreements`, если такой существует;
- иначе наиболее отличный business context среди already persisted analyzed cases.

## Итоговый статус run

- `initial status on 2026-03-19`: blocked by missing second persisted analyzed case
- `current status`: completed
- `stage`: `Manual Output Validation`
- `new runtime execution for unblocking`: `yes`
- `live intake for unblocking`: `yes`
- `reason`: после initial blocker был успешно получен второй persisted analyzed case через existing manual MVP-1 flow, а затем выполнен полный second-case verification

## Verification Method

Для выбора второго кейса были выполнены read-only проверки PostgreSQL:

1. Проверка общего количества persisted entities
2. Проверка списка `interactions`
3. Проверка `interactions join analyses`
4. Попытка ранжировать кандидатов по наличию `agreements` и другим artifacts

## DB Evidence

### A. Total counts

Confirmed:

- `interactions_count = 1`
- `analyses_count = 1`
- `joined_cases_count = 1`

### B. Existing interactions inventory

Confirmed single existing interaction:

- `interaction_id`: `2ea673d2-8a5c-4ab3-9e96-339392003b00`
- `external_id`: `384e3a87-3d38-4a84-9656-0feec40be59a`
- `status`: `DELIVERED`
- `analyzed_at`: `2026-03-18 09:41:57.746926+00`
- `created_at`: `2026-03-18 09:19:57.594776+00`
- `duration_sec`: `757`
- `has_text`: `true`

### C. Candidate selection result

When excluding the already validated case:

- `interactions join analyses`: `0 rows`
- ranked candidate query by `agreements_count`: `0 rows`

Conclusion:

- no second persisted analyzed case exists in the current database state
- no alternative case can be selected for `Run 003` without creating new persisted data

## Unblocking Update

On `2026-03-19`, a new real call was processed through the existing manual MVP-1 flow.

New persisted case:

- `interaction_id`: `52fa496a-6045-4d0f-aba5-f5e98e3c2da8`
- `analysis_id`: `096745aa-5c00-4213-b4d4-e1a252c1416e`
- `external_id`: `fe449b87-6c82-48d0-89de-ef9a2fac3cdc`
- `date`: `2026-03-19`
- `status`: `DELIVERED`
- `stt_provider`: `whisper`

Persisted evidence for the new case:

- transcript persisted in `interactions.text`
- transcript segments persisted in `interactions.metadata.segments`
- analysis persisted in `analyses.scores_detail`
- raw analysis payload persisted in `analyses.raw_llm_response`
- delivery audit persisted in `interactions.metadata.manual_pilot_delivery`
- `agreements_count = 1`
- `agreements_rows = 1`

Updated DB totals after unblocking:

- `interactions_count = 2`
- `analyses_count = 2`
- `joined_cases_count = 2`

Conclusion:

- the sampling blocker for `Run 003` is removed
- a second persisted analyzed case now exists
- `Run 003` can now proceed as an actual cross-case verification step

## Defect / Gap Record

### Finding 1

- `test_case_id`: `manual_output_validation_run_003_second_case`
- `artifact_under_review`: `validation sample inventory`
- `expected`: available second persisted analyzed case, preferably with agreements or clearly different business context
- `actual`: only one persisted analyzed case exists in DB and it is the already validated Run 001 / Run 002 case
- `severity`: `medium`
- `reproducibility`: `always`
- `category`: `missing_data`
- `notes`: blocker is on validation sample availability, not on transcript/analyzer/delivery runtime correctness
- `evidence`: `interactions_count=1`, `analyses_count=1`, `joined_cases_count=1`, exclusion query for existing case returns `0 rows`
- `proposed_fix`: obtain at least one additional persisted analyzed case before retrying Run 003

## Verification Run On The Second Case

Run performed on the persisted case:

- `interaction_id`: `52fa496a-6045-4d0f-aba5-f5e98e3c2da8`
- `analysis_id`: `096745aa-5c00-4213-b4d4-e1a252c1416e`
- `external_id`: `fe449b87-6c82-48d0-89de-ef9a2fac3cdc`

## Evidence By Artifact

### A. Transcript

Persisted transcript facts:

- `interaction.status = DELIVERED`
- `duration_sec = 624`
- `segments_count = 133`
- transcript is present in `interactions.text`
- source language is Russian

Representative transcript evidence:

- customer request:
  - `Мне нужно подписать от имени ТООшки договор, договор дарения машины. У вас можно онлайн подписать...`
- commercial discussion:
  - `Единственное, это будет платное подписание, 25 тысяч тенге.`
- next-step signal:
  - `Я вам направлю.`
  - `Клиенту будет отправлен счет на оплату.` confirmed later by persisted analysis and delivery

Transcript verdict:

- `completeness`: acceptable for business review
- `structural correctness`: transcript and segments are persisted
- `readability`: acceptable
- `business usefulness`: sufficient for validating pricing, payment agreement, and next-step handling

### B. Analysis

Persisted analysis facts:

- `instruction_version = edo_sales_mvp1_call_analysis_v1`
- `score_total = 75`
- `is_failed = false`
- `call_topic = Подписать договор дарения машины онлайн.`
- `agreements_count = 1`
- `strengths_count = 0`
- `weaknesses_count = 0`
- `recommendations_count = 0`

Observed content:

- `classification.call_type = sales_repeat`
- `classification.scenario_type = repeat_contact`
- `summary.short_summary` is in Russian
- `summary.outcome_text` is in Russian
- `summary.next_step_text` is in Russian
- `follow_up.next_step_fixed = true`
- `follow_up.next_step_text = Отправить клиенту счет на оплату.`

Analysis verdict:

- `completeness`: required top-level fields are present
- `structural correctness`: approved contract shape is preserved
- `consistency with transcript`: supported by persisted transcript
- `business usefulness`: acceptable for manager-facing review

### C. Delivery

Confirmed persisted delivery audit:

- `mode = live_run`
- `status = DELIVERED`
- `targets = [{"channel":"telegram","target":"74665909","status":"sent"}]`
- `error_message = null`

Read-only rebuilt compact delivery preview from persisted `interaction + analysis.scores_detail`:

```text
Карточка звонка — ручная проверка
Interaction ID: 52fa496a-6045-4d0f-aba5-f5e98e3c2da8
Внешний код: fe449b87-6c82-48d0-89de-ef9a2fac3cdc
Менеджер: 322
Контакт: Зарина
Дата/время: 2026-03-19T06:16:29+00:00
Длительность: 624 сек
Тип звонка: Продажи — повторный
Сценарий: Повторный контакт
Статус анализа: eligible / duration_ge_180_sec_and_sales_relevant

Краткое резюме: Клиент Зарина интересуется возможностью подписания договора дарения машины онлайн. Обсуждаются детали регистрации и оплаты услуги.
Итог: Клиент согласился на условия и планирует оплатить услугу.
Следующий шаг: Клиенту будет отправлен счет на оплату.

Скоринг по чек-листу: 12/16 (75.0%, Сильный)
Критический сбой: нет

Этапы:
- Первичный контакт: 6/8
- Квалификация и первичная потребность: 6/8

Сильные стороны:
- Нет зафиксированных сильных сторон

Зоны роста:
- Нет зафиксированных зон роста

Рекомендации:
- Нет рекомендаций

Дальнейшие действия: шаг зафиксирован — да; следующий шаг — Отправить клиенту счет на оплату.; причина, если не зафиксирован — —
```

Delivery verdict:

- no `None: None`
- no `None / None`
- no `[medium] None -> None`
- empty finding lists degrade gracefully to readable fallback lines
- compact card remains readable as one message

### D. Agreements Path

Confirmed persisted agreement evidence:

- `agreements_count = 1` in `analyses.scores_detail`
- `agreements_rows = 1` in derived `agreements` table

Persisted agreement row:

- `text = Клиент согласился на оплату услуги и ожидает счет.`
- `status = open`

Agreement path verdict:

- agreement signal is preserved from analysis to derived persistence
- follow-up path is also present through `follow_up.next_step_text`
- this second case is materially stronger than Run 001 for agreements validation because Run 001 had `agreements_rows = 0`

### E. Consistency

Verified:

- transcript -> analysis:
  - pricing, online signing, and payment intent are present in transcript and reflected in summary/agreement
- analysis -> delivery:
  - delivery keeps summary, next step, score, stage list, and agreement-adjacent follow-up meaning
- analysis -> agreements table:
  - persisted agreement row matches the analysis-level agreement statement

Consistency verdict:

- materially consistent
- no evidence of delivery inventing new business facts

### F. Language Policy

Verified:

- transcript remains source-native Russian
- analysis business-facing summary fields are Russian
- rebuilt delivery preview is Russian for business-facing content
- remaining non-Russian items are system/technical values:
  - `Interaction ID`
  - `eligible`
  - `duration_ge_180_sec_and_sales_relevant`

Language policy verdict:

- `transcript language preserved`: yes
- `business-facing output in Russian`: yes

### G. Business Usability

Observed:

- manager-facing card clearly communicates request, paid service, agreement to pay, and next step
- score and stage summary are readable
- agreement/follow-up signal is actionable

Usability verdict:

- acceptable for manager-facing manual review
- useful for follow-up on invoice/payment step

## Correct Next Step

The next correct step after `Run 003` is:

1. continue Manual Output Validation on additional representative cases and artifact variants
2. pay special attention to manager mapping quality and manager-facing identity fields
3. keep automation readiness postponed until remaining validation uncertainty is reduced

## Defects / Gaps Found In Run 003

### Finding 2

- `test_case_id`: `manual_output_validation_run_003_second_case`
- `artifact_under_review`: `delivery / mapping / business usability`
- `expected`: manager-facing card should identify the manager by resolved person identity when mapping is available
- `actual`: delivery card shows `Менеджер: 322`, while persisted interaction has `manager_id = null`, `mapping_source = manual_fallback`, `mapping_diagnostics = ["no_local_or_bitrix_match"]`
- `severity`: `medium`
- `reproducibility`: `confirmed on this case`
- `category`: `mapping_issue`
- `notes`: delivery fix and language policy are not blocked by this, but manager identity readability is degraded
- `evidence`: persisted interaction metadata and rebuilt delivery preview
- `proposed_fix`: validate whether this extension should resolve through Bitrix/local mapping in a later dedicated step; do not widen scope inside Run 003

## Final Verdict

- `delivery fix confirmed on more than one case`: `yes`
- `why`: second-case compact delivery preview is readable and does not leak `None` placeholders on a different persisted payload

- `language policy confirmed on more than one case`: `yes`
- `why`: second case keeps transcript source-native and business-facing output Russian, matching the policy already observed after Run 002

- `agreements path confirmed on the second case`: `yes`
- `why`: the new case preserves agreement meaning in both analysis payload and derived `agreements` table

- `remaining non-blocking gap`: `yes`
- `gap`: manager mapping is unresolved for this case and the delivery card shows extension `322` instead of a resolved manager identity

## Scope Notes

- No runtime code was changed in this step.
- No new live intake was started in this step.
- No automation readiness work was performed.
- No full manager card work was performed.
