# MANUAL_OUTPUT_VALIDATION_RUN_001

## Цель run

Провести первый фактический manual verification run по уже сохранённому live кейсу и собрать evidence pack по цепочке:

`transcript -> analysis -> delivery -> persistence`

Этот run не запускает новый звонок, не повторяет STT/LLM и не расширяет automation scope.

## Test Case Metadata

- `test_case_id`: `manual_output_validation_run_001`
- `source_interaction_id`: `2ea673d2-8a5c-4ab3-9e96-339392003b00`
- `source_analysis_id`: `5a8f8414-f59a-4671-8879-bac3bf5e2f4d`
- `source_call_id`: `384e3a87-3d38-4a84-9656-0feec40be59a`
- `manager`: `Pilot Manager 212`
- `department`: `Manual Live Validation`
- `source`: `onlinepbx`
- `duration_sec`: `757`
- `status`: `DELIVERED`
- `analyzed_at`: `2026-03-18 09:41:57.746926+00`
- `delivery mode`: `delivery_replay`
- `delivery target`: Telegram test-only chat `74665909`
- `instruction_version`: `edo_sales_mvp1_call_analysis_v1`
- `tables with records`:
  - `interactions`
  - `analyses`
  - `insights`
  - `departments`
  - `managers`
- `tables without case rows`:
  - `agreements` (0 rows for this interaction)

## Evidence By Artifact

### A. Source Persistence Evidence

Confirmed for the same persisted case:

- `interactions_count` by `external_id=384e3a87-3d38-4a84-9656-0feec40be59a`: `1`
- `analyses_count` by `interaction_id=2ea673d2-8a5c-4ab3-9e96-339392003b00`: `1`
- `insights_count`: `4`
- `agreements_count`: `0`

Conclusion:

- no duplicate `interaction`
- no duplicate `analysis`
- delivery replay reused the same persisted entities

### B. Transcript Evidence

Transcript is stored in:

- `interactions.text`
- `interactions.metadata.segments`
- `interactions.metadata.confidence`

Observed runtime facts:

- `text` is present
- `segments_count = 331`
- `confidence = null`
- transcript includes a long contiguous conversation and concrete product walkthrough fragments

Representative transcript evidence:

- Opening:
  - `Сейчас я в бухгалтерию отправила, ее посадят, автоматический доступ откроется. Давайте пока презентацию вам проведу.`
- Core walkthrough:
  - `А в рамках вашей подписки будет доступны документы.`
- Ending / next step:
  - `Я вас передам в отдел сервиса.`
  - `В отдел сервиса за вами менеджер будет. Она с вами познакомится, она вам позвонит.`

Transcript verdict:

- `completeness`: acceptable for business review
- `structural correctness`: transcript + segments are persisted
- `readability`: acceptable, but raw transcript is noisy and contains repeated filler tokens
- `business usefulness`: sufficient for validating summary, next step, and delivery

### C. Analysis Evidence

Persisted analysis is stored in:

- `analyses.scores_detail`
- `analyses.raw_llm_response`
- `analyses.strengths`
- `analyses.weaknesses`
- `analyses.recommendations`
- derived `insights`

Confirmed top-level contract presence:

- `call`: present
- `classification`: present
- `summary`: present
- `score`: present
- `score_by_stage`: present
- `strengths`: present
- `gaps`: present
- `recommendations`: present
- `agreements`: present
- `follow_up`: present
- `summary.next_step_text`: present
- `criteria_results`: present inside `score_by_stage`

Observed content:

- `checklist_score.score_percent = 62.5`
- `summary.short_summary`:
  - `The call involved a detailed walkthrough of the client's subscription features and document access process.`
- `summary.outcome_text`:
  - `The client was guided through accessing documents and features.`
- `summary.next_step_text`:
  - `The client will be contacted by the service department for further assistance.`
- `follow_up.next_step_text`:
  - same as summary next step

Observed stage coverage in this case:

- `contact_start`
- `qualification_primary`
- `presentation`

Observed artifact shape mismatch:

- persisted `strengths`/`gaps` items contain:
  - `criterion_code`
  - `comment`
  - `evidence`
- persisted `recommendations` items contain:
  - `criterion_code`
  - `recommendation`

This differs from the approved example/contract shape, where:

- `strengths` / `gaps` should contain `title`, `evidence`, `impact`
- `recommendations` should contain `priority`, `problem`, `why_it_matters`, `better_phrase`

### D. Delivery Evidence

Actual Telegram delivery text was rendered from the persisted case via `CallsDelivery.build_notification_text()` without rerunning intake/STT/analyzer.

Observed delivery content:

```text
Карточка звонка — manual pilot
Interaction ID: 2ea673d2-8a5c-4ab3-9e96-339392003b00
Внешний код: 384e3a87-3d38-4a84-9656-0feec40be59a
Менеджер: Pilot Manager 212
Контакт: +77072221464
Дата/время: 2026-03-18T05:27:59+00:00
Длительность: 757 сек
Тип звонка: sales_primary
Сценарий: repeat_contact
Eligibility: eligible / duration_ge_180_sec_and_sales_relevant

Краткое резюме: The call involved a detailed walkthrough of the client's subscription features and document access process.
Итог: The client was guided through accessing documents and features.
Следующий шаг: The client will be contacted by the service department for further assistance.

Скоринг: None / None | 15/24 (62.5%, basic)
Critical failure: False

Этапы:
- Первичный контакт: 6/8
- Квалификация и первичная потребность: 3/8
- Формирование предложения (презентация/КП): 6/8

Сильные стороны:
- None: None
- None: None

Зоны роста:
- None: None
- None: None

Рекомендации:
- [medium] None -> None
- [medium] None -> None

Follow-up: next_step_fixed=True, text=The client will be contacted by the service department for further assistance., reason_not_fixed=—
```

Delivery audit persisted in metadata:

- `mode = delivery_replay`
- `status = DELIVERED`
- `targets = [{"channel":"telegram","target":"74665909","status":"sent"}]`
- `attempted_at = 2026-03-18T10:37:04.432315+00:00`

Analysis fields actually used by delivery:

- `call`
- `classification`
- `summary`
- `score.checklist_score`
- `score.critical_failure`
- `score_by_stage`
- `strengths`
- `gaps`
- `recommendations`
- `follow_up`

What did not make it into delivery:

- `agreements`
- `product_signals`
- `analytics_tags`
- `evidence_fragments`
- `data_quality`
- full criterion-level detail

### E. Consistency Findings

#### Transcript -> Analysis

Verified:

- summary about account/subscription walkthrough is supported by transcript
- delivery of access/password reset and product navigation is supported by transcript
- next step about transfer to service is directly supported by transcript tail

Conclusion:

- `summary` is materially consistent with transcript
- `follow_up.next_step_text` is materially consistent with transcript

Detected quality gaps:

- analysis text is in English while source transcript and manager-facing delivery wrapper are Russian
- transcript is noisy, but still sufficient for business review

#### Analysis -> Delivery

Verified:

- delivery keeps call metadata, classification, summary, next step, score percent, and stage list
- no duplicate case was created during delivery replay

Detected quality gaps:

- delivery formatter expects fields that are absent in persisted `strengths/gaps/recommendations`
- this causes visible `None` values in manager-facing Telegram content
- delivery prints `legacy_card_score` and `legacy_card_level` as `None / None`

Conclusion:

- no critical business meaning was invented in delivery
- but delivery readability and structural usefulness are degraded by formatter/contract mismatch

## Manager Card Gap

Comparison against `MVP1_MANAGER_CARD_FORMAT_v1.md`:

- current runtime output is only a compact single-call delivery summary
- there is no separate runtime artifact implementing Part A/B/C/D/E full manager card format
- there is no manager-level summary table
- there is no manager-level stage summary table
- there is no per-manager call table aggregation artifact

Verdict:

- `full manager card`: `not implemented`
- `compact single-call summary`: `implemented`
- overall verdict against approved manager-card format: `partially implemented`

## Manual Controls Verification

### Implemented and verified

1. `duration filters`
- `CALLS_MIN_DURATION_SEC`
- enforced in intake eligibility filter

2. `max calls per manual batch`
- `MANUAL_PILOT_MAX_CALLS`
- CLI `--limit`

3. `test-only delivery mode`
- `TEST_DELIVERY_TELEGRAM_CHAT_ID`
- `TEST_DELIVERY_EMAIL_TO`
- replay/delivery confirmed on test-only channels

4. `pilot mode / explicit whitelist`
- `MANUAL_PILOT_ENABLED`
- `MANUAL_PILOT_EXTERNAL_IDS`
- `MANUAL_PILOT_PHONES`
- `MANUAL_PILOT_EXTENSIONS`

### Documented only

1. `allowlist by managers`
- no explicit local manager-id allowlist confirmed in runtime path
- current closest control is extension-based pilot selection

2. `allowlist by departments`
- no explicit local department allowlist confirmed for manual validation batches
- `BITRIX24_TARGET_DEPARTMENT_IDS` exists, but it is mapping scope, not a validation batch allowlist

3. `max calls per day`
- `calls_max_daily_per_manager` exists in settings
- no confirmed enforcement in the current manual validation path

### Not found

1. `manual sample mode`
- no dedicated sample-mode control or fixed sampling policy confirmed in code

2. `manual deep-analysis limit` separate from batch limit
- not confirmed as a distinct implemented control

## Defects / Issues Found

### 1. Delivery formatter is inconsistent with persisted analysis payload
- `artifact_under_review`: compact manager-facing card / Telegram delivery
- `taxonomy`: `wrong_structure`, `delivery_formatting_issue`
- `severity`: `high`
- `evidence`:
  - `Сильные стороны: - None: None`
  - `Зоны роста: - None: None`
  - `Рекомендации: - [medium] None -> None`
- `impact`:
  - manager-facing delivery is structurally degraded
  - output is visibly low-quality despite successful transport
- `proposed_fix`:
  - align `build_notification_text()` with the actual approved artifact shape
  - or normalize persisted strengths/gaps/recommendations to the approved contract shape before delivery

### 2. Summary/recommendation language is inconsistent with manager-facing Russian delivery
- `artifact_under_review`: analysis result + delivery
- `taxonomy`: `low_readability`
- `severity`: `medium`
- `evidence`:
  - Russian wrapper text with English summary and recommendation content
- `impact`:
  - reduces manager readability
  - weakens direct usefulness for business users
- `proposed_fix`:
  - enforce output language expectations for manager-facing materials during Manual Output Validation fixes

### 3. Full manager card runtime artifact is absent
- `artifact_under_review`: manager card
- `taxonomy`: `missing_data`
- `severity`: `medium`
- `evidence`:
  - only compact single-call delivery card exists at runtime
  - approved full manager card format is not generated
- `impact`:
  - manager-card validation cannot yet be completed against the full approved format
- `proposed_fix`:
  - add a separate runtime artifact for the approved manager card in a later validation/fix step

### 4. Whisper transcript metadata has no confidence signal
- `artifact_under_review`: transcript metadata
- `taxonomy`: `missing_data`
- `severity`: `low`
- `evidence`:
  - `metadata.confidence = null`
- `impact`:
  - transcript quality review has less quantitative support
- `proposed_fix`:
  - either keep as accepted Whisper limitation for this stage or add another quality heuristic explicitly

## Recommended Next Fix Order

1. Fix compact delivery formatter to match actual approved/persisted analysis shape
2. Normalize manager-facing language/readability expectations for summary and recommendations
3. Decide whether full approved manager card is required before broader artifact-validation batches
4. Only after that, continue larger-sample Manual Output Validation

## Exit Decision For This Run

- `decision`: `pass with gaps`
- `why`:
  - the run is evidence-complete and usable for validation
  - transcript, analysis, persistence, and Telegram delivery are all factually confirmed
  - but there is a high-severity manager-facing delivery formatting defect
  - and the full approved manager card remains not implemented as a runtime artifact

## Practical Verdict

- It is valid to proceed with the next Manual Output Validation step only after addressing the high-severity delivery formatting gap.
- Automation readiness must remain postponed.
