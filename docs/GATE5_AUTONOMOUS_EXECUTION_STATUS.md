# Gate 5 Autonomous Execution Status

Дата: 2026-05-27

Статус: `report_layer_blocks_4_5_7_8_ready_for_review`

## Правило исполнения

Главный агент ведет координацию, ревью, тесты и approval gates. Субагенты
выполняют конкретные задачи. Агенты, которые симулируют узлы `LLM`, отделены от
implementation agents: для `LLM-1`, `LLM-2` и `LLM-3` используется свой
отдельный simulation agent.

Test/operator Telegram можно использовать для уведомлений и preview. Business
delivery в Telegram/email остается выключенной до отдельного approval.
При следующем approval gate / `waiting_for_user` нужно отправлять короткий
test/operator Telegram ping о том, что требуется действие пользователя.
В конце каждого блока нужно прикладывать approval summary в формате `было ->
стало -> как проверить -> что решить`, чтобы пользователь мог быстрее принять
решение.

## Статус задач

| Блок / этап | Статус задачи | Задача | Критерий готовности |
| --- | --- | --- | --- |
| Block 1: `БАЛЛЫ ПО ЭТАПАМ` + `ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ` + `КОНТАКТЫ В РАБОТУ` | `accepted` | Введен единый manager-facing status source, follow-up block переименован, selection bug для `2026-05-18` закрыт, conflicts стали warning | Accepted by user |
| Block 2: `СИТУАЦИЯ ДНЯ` + `РАЗБОР ЗВОНКА` | `accepted_after_analysis_layer_fix` | Пересобран поверх proof pool, focus-stage binding и fail-closed gates | Accepted by user before continuing Report Layer |
| Block 3: `ГОЛОС КЛИЕНТА` | `completed` | Убраны raw labels, duplicates и repeated action text; сохранены цитаты/сигналы | Included in final regression |
| Block 4: `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` | `ready_for_review` | Слабые/orphan recommendations fail-closed; grounded secondary cases only | Final PDF review |
| Block 5: `КОНТАКТЫ В РАБОТУ` | `ready_for_review` | Контакты очищены от `Контекст:`, reason wording переведен в `Повод` | Final PDF review |
| Cross-cutting Report Layer / `LLM-3` | `ready_for_review` | Форма/wording вынесены в instructions/renderer cleanup, facts/status/deadline/score gates сохранены | Final PDF review |
| LLM-node verification | `completed_for_current_scope` | `LLM-2` и Report Layer/`LLM-3` проверены отдельными agents; `LLM-1` отложен | Current scope complete |

## Report Layer Blocks 4/5/7/8 closeout

Date: `2026-05-27`

Status: `ready_for_review`

Agents used:

- Block 4 additional situations: `019e6aa4-c8ea-74f3-8c1d-28e643be52d4`
- Block 5 contacts wording: `019e6aa4-c981-75b0-a706-d1eebdee71ac`
- Blocks 7/8 final regression: `019e6aa4-c940-7640-9bcd-faa79f3cd203`

What changed:

- Additional situations now fail closed on weak/missing evidence and dedupe
  calls already used by primary blocks.
- Contact rows strip technical `Контекст:` wording and show human-facing
  `Повод: ...`.
- `Как с этим работать` / `Что сделать` are rendered as subsections, with the
  action text below as ordinary text.
- Python render model and DOCX generator both strip reader-facing technical
  token `document_type`.

Final regression artifacts:

```text
core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/report_layer_final_regression_2026-05-27/
```

Acceptance:

```text
docker compose exec -T api env PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  /app/tests/test_situation_day_daily_input.py \
  /app/tests/test_situation_day_daily_composer.py \
  /app/tests/test_call_breakdown_composer.py \
  /app/tests/test_voice_of_customer_composer.py \
  /app/tests/test_report_evidence_registry.py \
  /app/tests/test_report_block_router.py \
  /app/tests/test_llm3_simulation_composers.py
```

Result: `68 passed`.

PDF marker scan:

| Date | Result |
| --- | --- |
| `2026-05-18` | clean |
| `2026-05-19` | clean after `document_type` cleanup |
| `2026-05-20` | clean |

Telegram: final clean PDFs sent to the test/operator chat. Message id `331`;
document message ids `332`, `333`, `334`.

## Full-stack one-day control run

Date: `2026-05-27`

Candidate: `Толеген Жангазиев / 2026-05-19`

Status: `sent_for_review`

What ran:

- Fresh in-memory analysis from persisted transcripts.
- `LLM-1`, `LLM-2A`, `LLM-2B`, `LLM-2C`, `LLM-2D` via
  `AI_LLM_EXECUTION_MODE=subagent_runtime`.
- Validators / normalizers, report evidence registry, report block router.
- Report Layer / `LLM-3` composers via subagent runtime.
- DOCX -> PDF render path.

Important fix found during the run:

- First run failed closed with `semantically empty analysis`.
- Root cause: `llm_subagent_contract_runner.py` routed layered `LLM-2A/2B/2C/2D`
  requests through old monolithic LLM2 simulation.
- Fix: runner now dispatches `llm2a_*`, `llm2b_*`, `llm2c_*`, `llm2d_*` to
  pass-specific simulation functions.

Result:

- Status: `passed`.
- Subagent artifacts: `36`.
- LLM runtime tests: `8 passed`.
- Report Layer suite: `68 passed`.
- PDF marker scan: clean.
- Telegram: message id `335`, document id `336`.

Artifacts:

```text
core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/full_stack_tolegen_2026-05-19_subagent_run_2026-05-27/
```

Review note:

- The full-stack report includes `3` call-list rows, `1` contact in work and
  `1` call breakdown.
- `ГОЛОС КЛИЕНТА` and `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` are absent because the fresh
  proof pool did not admit enough material. This is fail-closed behavior and
  should be reviewed in the PDF before widening the run.

## Историческая очередь слоев

Эта очередь была выполнена для текущего scope до перехода к финальному Report
Layer regression. `LLM-1` остается отложенным отдельным сервисным шагом.

1. `LLM-2`: спроектировать pass contracts `2A/2B/2C/2D`.
2. `LLM-2`: разложить активные инструкции и убрать report-specific routing из
   основной задачи анализа.
3. `LLM-2`: ввести `proof_card` / universal evidence pack как source of truth
   для downstream.
4. Validators / normalizers: подключить proof validation как admission gate.
5. Registry / router: выбирать report material только из normalized proof pool.
6. Report Layer / `LLM-3`: вернуть остановленные Block 2/3/4 задачи поверх
   доказанного материала.
7. Renderer: дочистить форму без изменения смысла.
8. `LLM-1`: закрепить classification/card/eligibility последним.
9. Не включать business delivery до отдельного approval.

Current audit artifact:

```text
docs/LLM2_CLAIM_EVIDENCE_FIT_AUDIT_2026-05-27.md
```

## Block 1 execution result

Implementation files:

```text
core/app/agents/calls/reporting.py
core/app/agents/calls/report_templates.py
core/app/agents/calls/report_template_assets/manager_daily/manager_daily_template_v1/semantic.json
core/app/agents/calls/report_template_assets/manager_daily/manager_daily_template_v2/semantic.json
core/app/agents/calls/prompts/call_tomorrow_wording_composer_v1.md
core/app/agents/calls/verification_report_runner.py
scripts/generate_docx_report.js
tests/test_manual_reporting.py
core/tests/test_manual_reporting.py
```

Verification:

```text
python3 -m py_compile core/app/agents/calls/reporting.py core/app/agents/calls/report_templates.py tests/test_manual_reporting.py core/tests/test_manual_reporting.py
python3 -m py_compile core/app/agents/calls/verification_report_runner.py
node --check scripts/generate_docx_report.js
python3 -m json.tool semantic.json files
git diff --check
docker compose exec -T api python -m pytest -q /app/tests/test_manual_reporting.py -k 'ddc9_call_list_uses_llm2_business_outcome_for_display_status or ddc9_call_tomorrow_uses_final_manager_status_when_resolver_conflicts or ddc9_call_list_falls_back_to_resolver_when_llm2_outcome_invalid or call_list_sorting_uses_display_status_not_resolver_status or render_report_email_uses_short_body_and_pdf_attachment'
```

Result: `4 passed, 201 deselected`.

Control previews:

```text
core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate5_block1_after_fix_previews/
```

Preview outcome:

| Date | Contacts in `КОНТАКТЫ В РАБОТУ` | Diagnostics |
| --- | ---: | --- |
| `2026-05-18` | 1 | `call_list_status_quality.status=warning`, `conflict_count=2` |
| `2026-05-19` | 1 | `call_list_status_quality.status=warning`, `conflict_count=2` |
| `2026-05-20` | 3 | `call_list_status_quality.status=warning`, `conflict_count=2` |

Known residuals for later blocks:

- `Рекомендация: ...` still appears after `Конфиденциально` in text preview;
  this is cross-cutting render/report-note cleanup for Block 2/3, not Block 1
  status selection.
- `ТЁПЛЫЕ КОНТАКТЫ ДНЯ`, empty `РАЗБОР ЗВОНКА` and raw `Контекст:` labels
  remain in later block scope.

## Block 2 execution result

Implementation files:

```text
core/app/agents/calls/situation_day_daily_input.py
core/app/agents/calls/situation_day_daily_composer.py
core/app/agents/calls/prompts/situation_day_daily_composer_v2.md
core/app/agents/calls/reporting.py
core/app/agents/calls/llm_simulation.py
core/app/agents/calls/report_templates.py
scripts/generate_docx_report.js
core/tests/test_situation_day_daily_input.py
core/tests/test_situation_day_daily_composer.py
tests/test_manual_reporting.py
core/tests/test_manual_reporting.py
```

Control previews:

```text
core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate5_block2_after_fix_previews/
```

Preview outcome:

| Date | Generic Situation phrase | Breakdown rows | Technical markers |
| --- | --- | --- | --- |
| `2026-05-18` | removed | rendered | cleared |
| `2026-05-19` | removed | rendered | cleared |
| `2026-05-20` | removed | rendered | cleared |

Verification:

```text
python3 -m py_compile core/app/agents/calls/report_templates.py tests/test_manual_reporting.py core/tests/test_manual_reporting.py
node --check scripts/generate_docx_report.js
git diff --check
docker compose exec -T api python -m pytest -q /app/tests/test_manual_reporting.py -k 'gate5_block2_call_breakdown_keeps_diagnostic_fragment_marker_rows or gate5_block2_situation_day_rewrites_generic_selected_call_phrase or render_report_email_uses_short_body_and_pdf_attachment'
```

Result: `3 passed, 204 deselected`.

## Block 2 systemic focus correction

User comment:

```text
Почему "Ситуация дня" всегда по поводу Следующий шаг, хотя мы выделяем в
Баллах по этапам фокус; какой фокус - его и стоит брать за основу.
```

Root cause:

- `daily_coaching_focus` from `score_by_stage.priority` was built in
  `reporting.py`, but was not passed to `situation_day_daily_input` or the LLM3
  daily composer.
- `SituationDayDailyComposer` ranked all manager-gap candidates and could pick
  the best generic case without focus-stage binding.
- LLM3/subagent output could rewrite a non-next-step focus into generic
  next-step wording while keeping the selected candidate verified by quote.
- Local LLM3 simulation was hardcoded to `Закрепить следующий шаг конкретнее`.

Systemic fix:

- carry `daily_focus` into the compact LLM3 input package;
- restrict Situation Day selection to `daily_focus.stage_code`;
- fail closed with `no_focus_stage_manager_gap_scene` when no grounded manager
  gap exists for the score-priority stage;
- reject LLM3 output that replaces a non-next-step focus with generic
  next-step manager_error/title/action;
- update the LLM3 prompt and local simulation to preserve focus semantics.

Verification:

```text
python3 -m py_compile core/app/agents/calls/situation_day_daily_input.py core/app/agents/calls/situation_day_daily_composer.py core/app/agents/calls/reporting.py core/app/agents/calls/llm_simulation.py core/tests/test_situation_day_daily_composer.py core/tests/test_situation_day_daily_input.py
docker compose exec -T api python -m pytest -q /app/tests/test_situation_day_daily_composer.py /app/tests/test_situation_day_daily_input.py
docker compose exec -T api python -m pytest -q /app/tests/test_manual_reporting.py -k 'gate5_block2_call_breakdown_keeps_diagnostic_fragment_marker_rows or gate5_block2_situation_day_rewrites_generic_selected_call_phrase or render_report_email_uses_short_body_and_pdf_attachment'
node --check scripts/generate_docx_report.js
git diff --check
```

Result: composer/input `15 passed`; Block2 render regression `3 passed, 219
deselected`; syntax/checks passed.

Additional Block 2 proof-pool pass:

- Report Layer now admits `soften/softened` proof as
  `softened_proof_card`, without marking it `verified_source`.
- `Разбор звонка` no longer renders a router fallback when `Ситуация дня`
  is insufficient; it fails closed with `focus_evidence_missing`.
- Control preview rebuilt from layered LLM-2 proof simulation artifacts, without
  DB writes and without delivery. LLM3 was disabled only for the preview script
  to avoid live OpenAI calls.

Artifacts:

```text
core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate5_block2_softened_proof_previews_2026-05-27/
```

Render correction:

- initial Telegram PDFs used legacy HTML/PDF rendering;
- corrected user-facing PDFs were re-rendered through the current DOCX-first
  delivery path and resent to Telegram;
- corrected filenames start with `docx_pdf_block2_`;
- `docx_pdf_summary.json` confirms
  `template_docx_first_pdf_manager_daily_template_v2` and
  `conversion_status=converted`.

Preview result:

| Date | Situation Day | Call Breakdown | Notes |
| --- | --- | --- | --- |
| `2026-05-18` | `verified` | `3 rows / passed` | focus `qualification_primary` |
| `2026-05-19` | `insufficient` | hidden / `insufficient_evidence` | correct fail-closed for focus `completion_next_step` |
| `2026-05-20` | `verified` | `1 row / warning` | focus `contact_start`, needs human quality review |

Verification:

```text
python3 -m unittest core.tests.test_report_evidence_registry core.tests.test_report_block_router core.tests.test_situation_day_daily_input
docker compose exec -T api python -m pytest -q /app/tests/test_situation_day_daily_input.py /app/tests/test_situation_day_daily_composer.py /app/tests/test_call_breakdown_composer.py /app/tests/test_report_evidence_registry.py /app/tests/test_report_block_router.py /app/tests/test_llm3_simulation_composers.py
```

Result: local unittest `26 OK`; container targeted suite `50 passed`.

Status: Block 2 accepted by user; Block 3 execution completed; Telegram preview
sent and waiting for user review.

## Gate 5 Block 3: Voice Of Customer

Date: `2026-05-27`

Agents used:

- implementation: `019e6a58-9b5b-7f73-8c04-38a380461bbc`;
- preview path: `019e6a58-c4f2-7450-8ba4-bfc7776213e6`;
- LLM3 contract audit: `019e6a58-dbbd-7543-96b8-09df69d0365e`.

What changed:

- `VoiceOfCustomerComposer` now accepts only proof-backed customer/service
  signal material.
- `LLM-3` receives bounded signals with `proof_refs` and `locked_fields`.
- `LLM-3` output is normalized back to source `call_id`, quote, client
  reference, source, signal category and proof refs.
- Raw rows from `LLM-3` are not trusted; rows are rebuilt from normalized
  locked scenes.
- Invented `dialogue_evidence` is discarded unless the text is supported by
  source `quote_context`.
- Renderer removes `Контекст:` from `ГОЛОС КЛИЕНТА`, uses
  `Сторона 1` / `Сторона 2` for unclear dialogue, and removes duplicated
  `Что сделать:` from `Что клиент имеет в виду`.
- `llm_simulation._simulate_llm3_voice_of_customer()` now returns the v2
  schema and returns `insufficient` for empty signals.

Artifacts:

```text
core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/gate5_block3_voice_previews_2026-05-27/
```

Telegram:

- sent summary + 3 PDF previews to test Telegram;
- PDF prefix: `docx_pdf_block3_voice_fixed2_`;
- send log: `telegram_delivery_summary.json`.
- after user formatting comment, resent fixed PDFs with prefix
  `docx_pdf_block3_voice_fixed4_`; `Как с этим работать` is a separate
  subsection and the action body is plain text.

Verification:

```text
python3 -m unittest core.tests.test_voice_of_customer_composer core.tests.test_llm3_simulation_composers
docker compose exec -T api python -m pytest -q /app/tests/test_voice_of_customer_composer.py /app/tests/test_llm3_simulation_composers.py
python3 -m py_compile core/app/agents/calls/report_templates.py core/app/agents/calls/voice_of_customer_composer.py core/app/agents/calls/llm_simulation.py
node --check scripts/generate_docx_report.js
git diff --check
```

Result: local unittest `20 OK`; container targeted suite `20 passed`; syntax
and diff checks passed.
