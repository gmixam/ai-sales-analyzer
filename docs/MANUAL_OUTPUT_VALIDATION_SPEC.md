# MANUAL_OUTPUT_VALIDATION_SPEC

## Статус
- Этап: MVP-1
- Режим: Manual Output Validation
- Статус: active
- Назначение: stage policy для ручного подтверждения качества и пригодности уже существующих output materials до любого перехода к automation readiness

## Что это за документ
Этот документ содержит только stage-specific policies для текущего этапа.

Он не заменяет universal coder rules из [docs/CODER_WORKING_RULES.md](docs/CODER_WORKING_RULES.md).
Если задача находится внутри Manual Output Validation, правила этого документа считаются обязательными по умолчанию и не должны каждый раз полностью повторяться в task-промпте.

## 1. Stage Scope

Цель этапа:
- вручную проверить фактически генерируемые системой материалы;
- подтвердить их структурную корректность, читаемость и business usefulness;
- зафиксировать findings и acceptance criteria до следующего этапа.

В этот этап не входит:
- scheduler;
- retries;
- beat;
- full automation loop;
- automation readiness work без явного подтверждения.

## 2. Materials For Manual Validation

По умолчанию вручную проверяем:
1. Transcript
2. Analysis result
3. Checklist / `score_by_stage` / `criteria_results`
4. Strengths / gaps / recommendations
5. Agreements / follow-up / next steps
6. Compact manager-facing card / summary
7. Telegram delivery content
8. Consistency: transcript -> analysis -> card -> delivery
9. Пригодность для менеджера
10. Пригодность для РОПа
11. Понятность формулировок
12. Отсутствие шума, галлюцинаций и структурных ошибок

## 3. Stage Language Policy

### 3.1 Transcript language policy
- transcript сохраняется на исходном языке звонка;
- `interaction.text`, `segments`, raw source text и source quotes не должны автоматически переводиться;
- автоматический перевод transcript не является целью этого этапа.

### 3.2 Business output language policy
- все business-facing outputs должны быть на русском языке;
- это относится к `summary`, `strengths`, `gaps`, `recommendations`, `follow_up`, `next_step_text`, compact delivery и manager-facing materials.

### 3.3 Allowed non-Russian exceptions
- system values;
- `stage_code`, `criterion_code`, `instruction_version`;
- enum / status / code;
- JSON keys, field names, table names;
- technical identifiers и internal logs;
- дословные source quotes / transcript fragments, intentionally included as evidence.

### 3.4 Validation rule
Если текст не является system value и не является дословным source fragment, mixed-language business-facing output считается defect.

Использовать категории:
- `low_readability`
- `wrong_business_interpretation` when meaning is distorted
- `localization_inconsistency` as explicit validation note

## 4. Acceptance Criteria

### 4.1 Transcript
- completeness: текст звонка не пустой и покрывает разговор
- structural correctness: сегменты сохранены в ожидаемой структуре
- readability: текст можно читать без критической деградации
- business usefulness: достаточно для анализа звонка
- consistency: transcript согласуется с call metadata
- no obvious hallucinations / noise: нет явно выдуманных фрагментов
- no critical omissions: нет критически пропущенного куска разговора

### 4.2 Analysis result
- completeness: все обязательные top-level поля присутствуют
- structural correctness: approved contract соблюдён
- readability: summary и explanatory fields читаемы
- business usefulness: анализ даёт actionable understanding звонка
- consistency with transcript: факты опираются на transcript
- no obvious hallucinations / noise: нет выдуманных событий/договорённостей
- no critical omissions: не пропущены ключевые outcome/follow-up сигналы

### 4.3 Checklist / score by stage / criteria results
- completeness: applicable stages и criteria раскрыты
- structural correctness: approved stage/criterion structure соблюдена
- readability: evidence/comment fields понятны
- business usefulness: scoring помогает coaching review
- consistency with transcript: stage applicability и criterion scores подтверждаемы текстом
- no obvious hallucinations / noise: нет stage/criterion, которых нет в transcript
- no critical omissions: нет пропавших важных этапов

### 4.4 Strengths / gaps / recommendations
- completeness: есть meaningful items, если transcript даёт основание
- structural correctness: items schema-safe
- readability: формулировки короткие и пригодны для чтения менеджером
- business usefulness: рекомендации конкретны и actionable
- consistency with previous artifact: соответствуют checklist/summary
- no obvious hallucinations / noise: нет generic fluff без evidence
- no critical omissions: ключевые сильные/слабые стороны не потеряны

### 4.5 Agreements / follow-up / next steps
- completeness: commitments and next step fields заполнены, если они были в звонке
- structural correctness: agreements/follow_up не ломают contract
- readability: next step формулируется однозначно
- business usefulness: пригодно для post-call follow-up
- consistency with transcript: договорённости подтверждаемы звонком
- no obvious hallucinations / noise: нет выдуманных commitments
- no critical omissions: не потерян фиксированный next step, если он был

### 4.6 Compact manager-facing card / Telegram delivery
- completeness: текст включает header, summary, score, stages, strengths/gaps, recommendations, follow-up
- structural correctness: delivery text не ломается по format/rendering
- readability: карточка читается как одно сообщение
- business usefulness: менеджер понимает итог и следующий шаг
- consistency with previous artifact: текст построен на analysis result
- no obvious hallucinations / noise: delivery не добавляет новых фактов
- no critical omissions: не пропадает итог звонка или next step

### 4.7 Cross-artifact consistency
- transcript -> analysis: факты совпадают
- analysis -> card: human-readable summary не искажает contract
- card -> Telegram: delivery content не теряет критичные поля
- persistence: persisted rows содержат те же данные, что были в runtime output

## 5. Defect Taxonomy

Использовать такие категории:
1. `missing_data`
2. `wrong_structure`
3. `inconsistent_fields`
4. `wrong_business_interpretation`
5. `low_readability`
6. `noisy_or_redundant_text`
7. `delivery_formatting_issue`
8. `mapping_issue`
9. `persistence_issue`
10. `localization_inconsistency`

## 6. Validation Log Template

Для каждого findings использовать шаблон:
- `test_case_id`
- `source_interaction_id`
- `source_call_id`
- `artifact_under_review`
- `expected`
- `actual`
- `severity`
- `reproducibility`
- `notes`
- `evidence`
- `proposed_fix`

## 7. Manual Cost Controls For This Stage

### 7.1 Already implemented now
1. explicit whitelist / pilot mode
2. manual batch size
3. duration threshold
4. test-only delivery mode
5. department targeting for Bitrix mapping

Current controls in code/config:
- `MANUAL_PILOT_ENABLED`
- `MANUAL_PILOT_EXTERNAL_IDS`
- `MANUAL_PILOT_PHONES`
- `MANUAL_PILOT_EXTENSIONS`
- `MANUAL_PILOT_MAX_CALLS`
- CLI `--limit`
- `CALLS_MIN_DURATION_SEC`
- `TEST_DELIVERY_TELEGRAM_CHAT_ID`
- `TEST_DELIVERY_EMAIL_TO`
- `BITRIX24_TARGET_DEPARTMENT_IDS`

### 7.2 Documented next-step controls, not yet confirmed as implemented
1. allowlist by manager ids
2. allowlist by local department ids
3. max calls per day for manual validation batches
4. manual deep-analysis limit separate from intake limit
5. manual sample mode with fixed sampling policy

Эти controls нельзя считать реализованными без отдельного подтверждения в коде.

## 8. Exit Criteria

Возвращаться к automation readiness можно только когда:
1. transcript quality вручную подтверждён на representative sample
2. analysis contract quality вручную подтверждён на representative sample
3. checklist scoring и criterion-level evidence проходят manual review
4. agreements / follow-up / next steps подтверждены как business-useful
5. compact manager-facing card и Telegram content признаны пригодными
6. cross-artifact consistency подтверждена
7. critical issues `wrong_structure`, `wrong_business_interpretation`, `mapping_issue`, `persistence_issue` закрыты
8. остаются только minor readability/tuning issues, не блокирующие управленческое использование

## 9. Recommended Validation Sequence

1. выбрать ограниченную ручную выборку звонков
2. проверить transcript
3. проверить analysis contract
4. проверить scoring and criterion evidence
5. проверить agreements / follow-up
6. проверить compact card / Telegram message
7. зафиксировать findings в validation log
8. только после этого возвращаться к automation readiness
