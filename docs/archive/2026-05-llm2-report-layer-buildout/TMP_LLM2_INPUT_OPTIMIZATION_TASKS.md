# TMP: LLM2 Input Optimization Tasks

Дата: 2026-06-02
Статус: temporary planning / handoff draft

## Implementation Status 2026-06-02 / updated 2026-06-03

Текущий статус после запуска Codex-агентов на оптимизацию:

- `A1 Inventory/diagnostics` - `partial done`: runtime пишет агрегированную
  диагностику по каждому LLM2 pass в
  `scores_detail.llm2_layered_runtime.pass_diagnostics`: profile, payload keys,
  payload chars, output chars, wall time, provider/account/model, usage tokens
  when provider returns them, repair usage. Не логируются transcript/segments.
- `A2 Compact LLM2A input` - `done for payload shape`: compact profile убирает
  full checklist/contract и оставляет полный transcript/segments, compact LLM1
  snapshot, admission gate и task contract.
- `A3 Compact LLM2B input` - `done for payload shape`: LLM2B получает scenes,
  evidence ledger, business outcome signal и compact scoring rubric вместо
  full checklist/final contract.
- `A4 Compact LLM2C input` - `done for payload shape`: LLM2C получает claims,
  scene index и evidence ledger без полного LLM2A/B artifacts.
- `A5 Compact LLM2D input` - `partial / reopened 2026-06-03`: LLM2D уже не
  получает full A/B/C artifacts и report evidence contract, но новая
  диагностика показала, что payload все еще раздут относительно роли узла.
  Главные источники bloat: полный `scoring_summary.weak_criteria`, дубли в
  `recommendation_sources`, `output_contract` и `quality_rules` в user payload.
  См. новый блок `A11 LLM2D role-fit input optimization`.
- `A6 Deterministic adapter` - `not required yet / pending audit`: текущий
  adapter сохранен, потому compact outputs должны возвращать совместимые поля.
  Следующий тест должен показать, нужно ли отдельное compact adapter path.
- `A7 Universal diagnostics` - `partial done`: добавлены runtime diagnostics
  для size/usage/time/repair и deterministic semantic repair для vague
  availability / recommendation-like factual follow_up. Semantic diagnostics
  вроде non-Russian text, score calibration и empty-evidence warning остаются
  pending.
- `A8 Universal prompt rules` - `partial done`: compact payload включает краткие
  universal quality rules; `analyze_recommendations.md` обновлен под compact
  LLM2D role-fit input. Полная чистка permanent prompt files остается pending.
- `A9 Test plan` - `phase 2 targeted done`: добавлены unit tests на compact
  payload, pass diagnostics, LLM2C no-claims bypass, LLM2C proof-input trim,
  LLM2D role-fit input и semantic repair. Model calls/pipeline не запускались.
- `A10 Permanent docs` - `pending`: не переносить в постоянные документы до
  фактического full vs compact сравнения и решения, делать ли compact default.
- `A11 LLM2D role-fit input optimization` - `implemented / awaiting model
  smoke`: LLM2D input сужен до accepted proof cards, связанных
  claims/evidence, explicit outcome facts и краткого `scoring_context`.
  На сохраненном sample `57292...`: user payload `15 390 -> 10 943 chars`
  (`-28.9%`), полный content input `22 070 -> 18 871 chars` (`-14.5%`).
  Экономия ниже раннего прогноза, потому часть user-level контракта перенесена
  в system prompt и sample содержит длинный evidence/proof контекст.
- `A12 LLM2C no-claims bypass and proof input trim` -
  `implemented / awaiting model smoke`: при `0` claims LLM2C model call
  bypassed детерминированным валидным proof artifact; для non-empty claims
  убраны static quality rules, длинные claim-поля и нерелевантные
  scenes/evidence. На sample `57292...`: user payload `4 490 -> 3 128 chars`
  (`-30.3%`), content input `11 030 -> 9 668 chars` (`-12.3%`).
  Для no-claim calls экономия больше: полный LLM2C provider call не делается.

Изменения в коде:

- `core/app/agents/calls/analyzer.py`
  - `AI_LLM2_INPUT_PROFILE=full|compact`;
  - compact/full payload builders for LLM2A/B/C/D;
  - pass diagnostics in layered runtime;
  - provider usage snapshot copied from `interaction.metadata_.ai_routing.llm2`
    immediately after each pass.
- `core/app/core_shared/config/settings.py`
  - setting `ai_llm2_input_profile`;
  - 2026-06-04: default changed to `compact`.
- Runtime default:
  - `AI_LLM2_INPUT_PROFILE=compact`;
  - `full` remains only as explicit legacy/debug override for temporary
    comparison, not as the normal pilot path.
- `core/tests/test_ai_provider_routing.py` and `tests/test_ai_provider_routing.py`
  - tests for compact payload reduction, non-secret diagnostics, JSON repair
    diagnostics and provider usage capture.

Verification:

- `python3 -m py_compile core/app/agents/calls/analyzer.py core/app/agents/calls/openai_chat_compat.py core/app/core_shared/config/settings.py` - passed.
- `git diff --check` - passed.
- `docker compose exec -T api python -m pytest -q /app/tests/test_ai_provider_routing.py -k 'kimi_k26 or llm2_layered_pass or llm2_compact_profile'` - `5 passed`.

Важно: pipeline/model calls не запускались. Следующий осмысленный шаг - один
контрольный звонок в двух профилях `full` vs `compact` с таблицей фактической
экономии и ручной оценкой качества.

## Implementation Update 2026-06-02: A6/A7/LLM2D Fix

После compact smoke на звонке `9b71f8fa-6f94-4079-8987-32f9a9d36061`
обнаружены два quality blocker:

- `LLM2D.final_normalized_analysis.criteria_results` перезаписывал scoring из
  `LLM2B` и терял `evidence_ids/evidence`; результат: `20/20` criteria без
  текстового evidence.
- фраза менеджера "можете обращаться" снова превращалась в
  `callback_planned`, `follow_up` и `agreements`.

Внесенные изменения:

- `A6 Deterministic adapter` - `done for scoring evidence`: adapter теперь
  считает `LLM2B.criteria_results` source-of-truth для scoring и evidence
  hydration. `LLM2D.criteria_results` используется только как fallback, если
  `LLM2B` не дал criteria.
- `A6 Strength/gap source` - `done for compact`: `LLM2B.strength_claims` и
  `LLM2B.gap_claims` имеют приоритет над повторно сформированными полями из
  `LLM2D.final_normalized_analysis`.
- `A7 Semantic diagnostics/repair` - `partial done`: добавлен deterministic
  non-blocking repair + diagnostics для `vague_availability_not_callback`.
  Фразы вида "можете обращаться" / "если будут вопросы" удаляются из
  `callback/agreement/follow_up`, если рядом нет конкретного срока, действия
  или назначенного созвона.
- `A5 LLM2D compact payload` - `improved`: compact LLM2D больше не получает
  top-level `criteria_results`, `stage_scores`, `proof_cards`; вместо этого
  получает `scoring_summary` и минимальные `recommendation_sources`.
- `A5 LLM2D output contract` - `improved`: compact output contract больше не
  просит `score_by_stage`, `criteria_results`, `strengths`, `gaps` внутри
  `final_normalized_analysis`; эти поля собирает adapter из LLM2B/LLM2C.

Verification:

- `python3 -m py_compile core/app/agents/calls/analyzer.py core/app/agents/calls/llm2_layered_analysis.py core/app/agents/calls/openai_chat_compat.py core/app/core_shared/config/settings.py` - passed.
- `git diff --check` - passed.
- `docker compose exec -T api python -m pytest -q /app/tests/test_llm2_layered_analysis.py` - `10 passed, 2 subtests passed`.
- `docker compose exec -T api python -m pytest -q /app/tests/test_ai_provider_routing.py -k 'llm2_compact_profile or llm2_layered_pass'` - `4 passed`.

Повторный real model compact smoke после этой правки еще не запускался.

## Real Compact Smoke v2 2026-06-02

Повторно запущен тот же звонок после A6/A7/LLM2D fixes:

- Interaction: `9b71f8fa-6f94-4079-8987-32f9a9d36061`
- Instruction version: `llm2_compact_kimi_smoke_v2_20260602`
- Analysis id: `58cdc8c9-7569-48f9-8c5b-84c198eb55d7`
- Output dir: `/tmp/llm2_compact_kimi_smoke_20260602_exact_v2`
- Chain: ready STT -> persisted LLM1 snapshot -> compact LLM2A/B/C/D
- LLM3/report/delivery не запускались.

Technical result:

- validation valid: `true`
- repair count: `0`
- `score_by_stage_count=4`
- `criteria_results_count=16`
- `criteria_empty_evidence=0/16`

Runtime metrics:

| Pass | Payload chars | Total tokens | Wall time |
| --- | ---: | ---: | ---: |
| LLM2A | 8 055 | 11 171 | 66.982 sec |
| LLM2B | 23 490 | 16 021 | 77.897 sec |
| LLM2C | 10 562 | 9 969 | 30.775 sec |
| LLM2D | 12 940 | 13 242 | 76.671 sec |
| Total | - | 50 403 | 253.325 sec |

What improved vs compact smoke v1:

- LLM2D payload: `30 496 -> 12 940 chars`.
- LLM2D total tokens: `21 082 -> 13 242`.
- Total LLM2 tokens: `55 611 -> 50 403`.
- Total wall time: `374.988 sec -> 253.325 sec`.
- `criteria_results.evidence`: `20/20 empty -> 0/16 empty`.
- `agreements`: vague "можете обращаться" no longer persisted as agreement.

Remaining quality blocker:

- `summary.outcome_code` still came back as `callback_planned`.
- `follow_up.next_step` became a recommendation-like action:
  "Обратитесь к клиенту с подробным объяснением преимущества..."
- `cn_fixed_next_step` still scored `2/2` on vague availability evidence:
  "Можете вот обращаться..."
- Score is inflated: `87.5`.

Conclusion:

- A6 evidence hydration fix worked.
- LLM2D compact-size reduction worked.
- A7 semantic repair is too narrow; it catches "можете обращаться" as
  agreement/follow-up, but not broader model wording like
  `callback_planned` / "в случае интереса клиента" / recommendation-like
  next step.
- Next fix should target `LLM2B scoring calibration` and adapter-level
  outcome/follow-up normalization:
  - `cn_fixed_next_step` cannot be `2/2` when the only evidence is vague
    availability;
  - `callback_planned` requires concrete manager/client commitment, timing or
    agreed callback condition;
  - recommendation text must not populate `follow_up.next_step`.

## Diagnostic Full-Day Compact Run 2026-06-02

Запущен весь день Толегена за `2026-06-01` в compact diagnostic mode:

- Instruction version: `llm2_compact_kimi_full_day_diag_v1_20260602`
- Output dir: `/tmp/llm2_compact_kimi_full_day_diag_20260601_tolegen`
- Chain: ready STT -> persisted LLM1 snapshot -> compact LLM2A/B/C/D
- Not run: STT, real LLM1 rerun, LLM3, report, PDF, Telegram delivery

Run summary:

- analysis candidates: `6`
- created analyses: `5`
- created failed/admission rejected: `1`
- admitted into LLM2: `5`
- rejected before LLM2: `1`
- scored with stage scores: `5`
- JSON repair count: `0`

Per-call diagnostic:

| # | Interaction | Dur | Status | Score | Outcome | Criteria evidence | Tokens | Time | Flags |
| --- | --- | ---: | --- | ---: | --- | --- | ---: | ---: | --- |
| 1 | `db11ca8e` | 126 | created | 93.75 | refusal | 0/8 empty | 41117 | 122.015 | SD-003 high_score_with_weak_outcome |
| 2 | `c4eba985` | 354 | created | 54.17 | rescheduled | 8/24 empty | 48331 | 162.571 | SD-004 empty_criteria_evidence 8/24 |
| 3 | `204aad65` | 16 | created_failed | - | - | 0/0 empty | 0 | 0 | admission rejected |
| 4 | `08bd1671` | 40 | created | 50.0 | rescheduled | 0/12 empty | 37259 | 108.535 | ok |
| 5 | `ac275c55` | 35 | created | 29.17 | refusal | 15/24 empty | 45949 | 206.765 | SD-002 recommendation/vague future in follow_up; SD-004 empty evidence |
| 6 | `9b71f8fa` | 111 | created | 81.25 | open | 0/8 empty | 38625 | 174.37 | SD-002 recommendation/vague future in follow_up; SD-003 high_score_with_weak_outcome |

Conclusion:

- compact full-day runtime is technically stable on this small day: `5/5`
  admitted calls completed, `0` JSON repairs.
- LLM2D compact input remains materially lighter than old v1 one-call issue,
  but total per-call token cost is still high.
- Remaining blockers are semantic/systemic, not pipeline wiring:
  - score inflation on weak/refusal/open outcomes;
  - recommendation/vague future text leaking into factual `follow_up`;
  - absence-based scoring criteria often have no evidence ids/scene context.

Next engineering target:

- close `SD-002`, `SD-003`, `SD-006` in
  `TMP_LLM2_SEMANTIC_DEFECT_REGISTRY.md`;
- add deterministic normalization/tests before next full-day run.

## LLM2D Input Audit 2026-06-03

Контекст: после остановленного full run на `moonshot-v1-128k` была проверена
роль и фактический input узла `LLM2D`.

Фактический вывод:

- `LLM2D` должен быть финальным редактором рекомендаций и evidence-pack, а не
  заново оценивать звонок.
- Ему не нужен полный список всех слабых критериев и не нужны user-level
  правила/контракт, которые уже можно держать в system prompt.
- Даже в compact profile LLM2D user payload остается тяжелым.

Пример сохраненного payload:

- Interaction: `57292ab5-5164-4913-bf84-0be050d4e98c`
- Полный request sample:
  `core/review_packages/full_run_3_managers_20260601_moonshot128/llm2d_full_request_57292ab5-5164-4913-bf84-0be050d4e98c.json`
- User payload sample:
  `core/review_packages/full_run_3_managers_20260601_moonshot128/llm2d_user_payload_57292ab5-5164-4913-bf84-0be050d4e98c.json`

Математика по этому примеру:

| Часть | Символов |
| --- | ---: |
| `llm2_common_runtime` | 2 400 |
| separator | 2 |
| `analyze_recommendations` | 4 278 |
| system content | 6 680 |
| user payload content | 15 390 |
| total content input | 22 070 |

Состав user payload:

| Часть | Символов |
| --- | ---: |
| `input_profile` | 9 |
| `call_id` | 38 |
| `business_outcome_signal` | 223 |
| `scoring_summary` | 7 252 |
| `recommendation_sources` | 4 745 |
| `evidence_ledger` | 1 061 |
| `output_contract` | 660 |
| `quality_rules` | 449 |
| JSON overhead | 953 |
| total user payload | 15 390 |

Прогноз оптимизации по 6 сохраненным LLM2D payload Толегена:

| Метрика | Было | Станет | Разница |
| --- | ---: | ---: | ---: |
| Avg user payload | 12 731 chars | 5 314 chars | -7 418 chars / -58.3% |
| Avg content input with system | 19 411 chars | 11 994 chars | -7 418 chars / -38.2% |
| 25-call day user payload estimate | 318 275 chars | 132 850 chars | -185 425 chars |

Per-call forecast:

| Interaction | Было | Станет | Разница |
| --- | ---: | ---: | ---: |
| `57292...` | 15 390 | 8 138 | -47.1% |
| `41d2...` | 12 833 | 4 064 | -68.3% |
| `f296...` | 15 605 | 6 792 | -56.5% |
| `6f0f...` | 9 316 | 6 197 | -33.5% |
| `3898...` | 9 686 | 2 889 | -70.2% |
| `8381...` | 13 558 | 3 802 | -72.0% |

## Цель

Оптимизировать input для `LLM-2A/2B/2C/2D`, чтобы механизм стал дешевле,
быстрее и устойчивее для разных OpenAI-compatible моделей, но без просадки
качества анализа.

Это не задача "подогнать под Kimi". Цель - универсальный LLM2 runtime contract:
меньше лишнего контекста, меньше дублирования, более компактные JSON outputs,
та же доказательность и та же бизнес-полезность.

## Принципы

1. Не добавлять model-specific условия в промпты.
2. Не возвращать blocking validators как главный механизм качества.
3. Условия допуска к анализу остаются до входа в LLM2.
4. Если звонок передан в LLM2, LLM2A/B/C/D выполняют свои роли без новых
   stop-conditions.
5. Качество сохраняется через контракт, компактные inputs, deterministic
   adapter, diagnostics и post-run audit.
6. LLM не должен получать полный документ/контракт там, где достаточно
   компактной схемы для текущего pass.
7. Не ограничивать ИИ технически ради экономии: не ставить искусственно низкие
   `max_tokens`, не запрещать нужные рассуждения и не урезать transcript или
   evidence так, чтобы модель теряла смысл звонка.
8. Оптимизация должна быть доказана фактически: до/после сравниваются token
   usage, latency, repair usage, output size и ручная оценка качества.

## Non-Goals

Что нельзя считать успешной оптимизацией:

- уменьшить input так, что LLM перестает видеть смысл звонка;
- сэкономить токены ценой пустых сцен, слабого scoring или отсутствия
  доказательств;
- заменить анализ жесткими эвристиками report layer;
- добавить provider/model-specific ветки вроде "если Kimi, делай иначе";
- поставить слишком маленький output limit и потом считать короткий JSON
  улучшением.

Оптимизация должна убрать лишнее дублирование и нерелевантный контекст, а не
сократить способность LLM выполнить роль.

## Что показал smoke 2026-06-02

Тестовый звонок:

- Менеджер: Толеген Жангазиев
- Дата: `2026-06-01`
- Interaction: `9b71f8fa-6f94-4079-8987-32f9a9d36061`
- External id: `fb2f1ba2-b9e5-425b-bf05-1bb9b77053f7`
- Chain: ready STT -> LLM1 -> LLM2A/B/C/D -> persist
- LLM3/report/delivery не запускались.

Технический результат:

- `LLM1=moonshot-v1-32k`, `LLM2=moonshot-v1-32k`
- Анализ сохранен: `833b7b03-5782-4dee-8ad0-993570af9b6d`
- `score_by_stage_count=4`
- `criteria_results_count=16`
- `validation_valid=true`

Проблемы, которые указывают на необходимость input optimization:

- `moonshot-v1-8k` не вместил LLM1 input.
- `kimi-k2.6` зависал/шел слишком долго на текущем тяжелом LLM2A.
- LLM2D output был слишком длинным и потребовал JSON repair.
- Итоговый анализ имел quality issues:
  - завышенный score `81.25`;
  - неверный outcome `callback_planned`;
  - "можете обращаться" ошибочно трактовано как конкретный следующий шаг;
  - в summary появилась нерусская вставка `客户需求`;
  - рекомендации местами звучат не по-русски;
  - `score_by_stage.criteria_results[*].evidence` пустой, хотя evidence есть в
    `evidence_fragments`.

## Target State

Ввести компактный LLM2 input profile, например:

```env
AI_LLM2_INPUT_PROFILE=compact
```

Профиль должен менять только форму payload для LLM2 pass-ов и output schema
pass-ов. Он не должен менять бизнес-логику допуска, чеклист, report layer или
правила scoring.

Старый режим остается fallback:

```env
AI_LLM2_INPUT_PROFILE=full
```

## Task A1. Inventory Current LLM2 Payloads

Цель: измерить текущий размер input/output по каждому pass.

Что сделать:

- Добавить diagnostic artifact или лог по каждому LLM2 pass:
  - `request_kind`;
  - selected model/account;
  - prompt char length;
  - payload char length;
  - approximate token usage from provider metadata;
  - output char length;
  - repair_used true/false;
  - duration seconds.
- Не логировать секреты и полный transcript в обычный лог.
- Для audit artifacts можно хранить payload локально только в review package.

Acceptance:

- Для одного звонка можно увидеть, где основной input bloat:
  `LLM2A`, `LLM2B`, `LLM2C`, `LLM2D`.
- Можно сравнить full vs compact profile.
- Есть baseline table по текущему full profile:
  - prompt tokens;
  - completion tokens;
  - total tokens;
  - wall-clock seconds;
  - output chars;
  - repair_used;
  - status success/fail.

## Task A2. Compact LLM2A Input

Текущий риск: LLM2A получает слишком много рамочного материала.

Compact input для LLM2A должен содержать:

- `call_id`;
- минимальную metadata:
  - manager_name;
  - call_started_at;
  - duration_sec;
  - direction;
  - contact_phone;
- transcript или segments;
- LLM1 compact snapshot:
  - call_type;
  - analysis_eligibility;
  - eligibility_reason;
  - short_summary;
  - outcome_hint;
  - analysis_focus;
- admission gate result;
- короткую role instruction: scenes, evidence ledger, client reactions,
  objections, agreements, deadlines, service/refusal signals.

Убрать из LLM2A compact input:

- полный checklist;
- полный final contract shape;
- report evidence contract;
- большие approved source fragments.

Output LLM2A compact:

- scenes;
- evidence_ledger;
- business_outcome_signal;
- language/transcript quality notes;
- no scoring;
- no recommendations.

Quality must not drop:

- evidence quotes должны быть exact transcript substrings;
- scenes должны покрывать ключевые смысловые повороты звонка;
- refusal/agreement/next-step signals должны быть явно отмечены.

## Task A3. Compact LLM2B Input

Текущий риск: LLM2B получает большой checklist/context и может переоценивать.

Compact input для LLM2B:

- LLM2A scenes;
- LLM2A evidence_ledger;
- admission gate;
- compact scoring rubric:
  - stage_code;
  - stage_name;
  - applicability_rule;
  - criterion_code;
  - criterion_name;
  - score 0/1/2 meaning.

Не передавать:

- full final contract shape;
- report templates;
- full prompt assets unrelated to scoring.

Output LLM2B compact:

- criteria_results;
- stage_scores;
- strength_claims;
- gap_claims;
- outcome/follow-up scoring flags:
  - concrete_next_step_present;
  - owner_present;
  - deadline_or_timing_present;
  - client_commitment_present.

Quality must not drop:

- Every score > 0 must reference scene_ids/evidence_ids.
- `completion_next_step` cannot be high when there is no concrete action,
  owner, timing or client commitment.
- "Call me if needed" / "можете обращаться" is not a callback agreement.

## Task A4. Compact LLM2C Input

Текущий риск: proof pass получает лишнее и может усиливать broad claims.

Compact input для LLM2C:

- LLM2B claims only;
- LLM2A evidence_ledger;
- minimal scene index:
  - scene_id;
  - stage_hint;
  - what_happened.

Output LLM2C compact:

- proof_cards;
- each proof card:
  - claim_id;
  - proof_status;
  - proof_type;
  - supporting_evidence_ids;
  - counter_evidence_ids;
  - evidence_quote;
  - claim_too_broad;
  - needs_softening;
  - softened_claim;
  - reject_reason.

Quality must not drop:

- Claims without direct or sequence evidence must be softened/rejected.
- Proof must not introduce new facts.
- Counter-evidence must be considered for high-impact claims.

## Task A5. Compact LLM2D Input

Статус 2026-06-03: `partial / reopened`.

Первичная compact-версия уже убрала full A/B/C artifacts и full report evidence
contract. Однако аудит 2026-06-03 показал, что input все еще не соответствует
узкой роли LLM2D и остается дорогим:

- `scoring_summary.weak_criteria` часто занимает 7-11k chars;
- `recommendation_sources` дублирует claims/proof/evidence text;
- `output_contract` и `quality_rules` повторяются в user payload, хотя должны
  жить в system prompt;
- LLM2D получает слишком много оценочной массы и может формально пройти, но
  вернуть пустые `strengths/gaps/recommendations`.

Историческая цель compact input для LLM2D:

Compact input для LLM2D:

- accepted/softened proof_cards;
- stage_scores;
- top gaps only;
- outcome/follow-up flags from LLM2B;
- minimal call essence from LLM2A:
  - topic;
  - client_position;
  - manager_action;
  - outcome;
  - next_step/agreement if proven.

Не передавать:

- полный LLM2A artifact;
- полный LLM2B artifact;
- полный LLM2C artifact;
- full evidence ledger, если достаточно referenced quotes;
- full report evidence contract.

Output LLM2D compact:

- final_summary;
- call_essence;
- recommendations max 2-3;
- agreements only if concrete agreement is proven;
- follow_up only if concrete next step is proven;
- normalized evidence references;
- no repeated full scenes;
- no quote_bank unless explicitly needed.

Quality must not drop:

- Outcome must match evidence.
- No agreement/callback if there is only vague "можете обращаться".
- Russian-only manager-facing text.
- Recommendations must be natural Russian and actionable.

Открытая доработка перенесена в `Task A11`, потому нужна не косметическая
компактизация, а role-fit пересборка input.

## Task A6. Deterministic Adapter From Compact Artifacts

Цель: компактный LLM output разворачивается в текущий `scores_detail` без
потери compatibility с report layer.

Что сделать:

- Add adapter path:
  - `normalize_llm2_layered_analysis(..., input_profile="compact")`
  - or separate `normalize_compact_llm2_layered_analysis()`.
- Adapter должен заполнять:
  - `score_by_stage`;
  - `criteria_results`;
  - `strengths`;
  - `gaps`;
  - `recommendations`;
  - `evidence_fragments`;
  - `summary`;
  - `follow_up`;
  - `agreements`;
  - `report_evidence` compatibility fields where needed.

Important:

- `score_by_stage.criteria_results[*].evidence` should be filled from
  referenced evidence when possible, not left empty.
- Keep legacy report layer compatible.
- Do not make LLM2 choose report blocks.

## Task A7. Universal Quality Diagnostics

Это не hard validators, а diagnostics/repair candidates.

Diagnostics to add:

- non-Russian characters in manager-facing fields;
- outcome/follow-up contradiction:
  - `callback_planned` but no concrete callback evidence;
  - agreement exists but no owner/timing/action;
- score calibration warnings:
  - high `completion_next_step` with no concrete next step;
  - high total score with major unresolved refusal/objection;
- empty criterion evidence despite available evidence_ids;
- output repair usage count;
- token usage and latency per pass.

Acceptance:

- Diagnostics are visible in analysis detail or run summary.
- Diagnostics do not silently discard the analysis.

## Task A8. Prompt Rules That Are Universal, Not Model-Specific

Add concise universal rules to LLM2 pass prompts:

- Return compact JSON only.
- Do not duplicate input artifacts in output.
- Use Russian for manager-facing text.
- Keep exact evidence quotes from transcript.
- Do not mark vague availability as agreement/callback.
- Do not infer deadline, owner or commitment unless spoken.
- Score only applicable criteria and cite scene/evidence ids.

Do not add:

- "If model is Kimi, do X".
- provider-specific wording.
- hidden model-specific branches in prompt text.

## Task A9. Test Plan

Phase 1: no model calls

- Unit tests for compact payload builders.
- Unit tests for compact adapter.
- Unit tests for outcome/follow-up deterministic checks.
- Snapshot test for one known transcript payload size reduction.

Phase 2: one-call smoke

- Use the same Толеген call:
  `9b71f8fa-6f94-4079-8987-32f9a9d36061`.
- Run ready STT -> LLM1 -> compact LLM2 -> persist.
- Do not run LLM3/report/delivery.

Compare full vs compact:

- token usage by pass;
- wall-clock latency;
- repair_used;
- score_by_stage_count;
- criteria_results_count;
- outcome;
- follow_up/agreement;
- Russian-only scan;
- manual human audit.

Phase 3: small quality set

- 5-10 calls:
  - short sales;
  - refusal;
  - clear callback agreement;
  - technical/service;
  - real sale/proposal.

Pass criteria:

- No Chinese/English contamination in manager-facing fields.
- Outcome matches transcript.
- No false agreements.
- Stage scores are not obviously inflated.
- Evidence references remain usable.
- Report layer can render from compact-produced `scores_detail`.

Required factual optimization report:

| Metric | Full profile | Compact profile | Change | Quality note |
| --- | ---: | ---: | ---: | --- |
| LLM2A prompt tokens | TBD | TBD | TBD | scenes/evidence preserved? |
| LLM2A completion tokens | TBD | TBD | TBD | JSON valid? |
| LLM2B prompt tokens | TBD | TBD | TBD | scoring quality preserved? |
| LLM2B completion tokens | TBD | TBD | TBD | evidence refs present? |
| LLM2C prompt tokens | TBD | TBD | TBD | proof quality preserved? |
| LLM2C completion tokens | TBD | TBD | TBD | counter-evidence considered? |
| LLM2D prompt tokens | TBD | TBD | TBD | summary/recommendations quality? |
| LLM2D completion tokens | TBD | TBD | TBD | no output truncation? |
| Total LLM2 tokens | TBD | TBD | TBD | no quality regression? |
| Total LLM2 wall time | TBD | TBD | TBD | stable enough? |
| Repair count | TBD | TBD | TBD | lower is better |
| Manual quality verdict | TBD | TBD | TBD | pass/fail |

Success criteria:

- Token usage and/or latency decreases measurably.
- JSON repair usage decreases or stays controlled.
- Manual audit does not show lower semantic quality.
- Outcome/follow-up quality improves or remains correct.
- Evidence remains traceable from final fields to transcript quotes.

## Task A10. Documentation Updates After Implementation

When implemented, update permanent docs:

- `docs/LLM2_ARCHITECTURE_AUDIT_AND_TARGET_MODEL.md`
- `docs/RUNTIME_PROFILES.md`
- `docs/AI_PROVIDER_ROUTING.md`
- `docs/ACTIVE_WORK_STATE.md`
- `docs/PROGRESS.md`

But keep this file temporary unless the plan is approved.

## Task A11. LLM2D Role-Fit Input Optimization

Статус: `implemented / awaiting model smoke`.

Цель: сделать LLM2D финальным редактором рекомендаций, а не повторным
оценщиком звонка. LLM2D должен получить только то, что нужно для:

- финальных рекомендаций;
- `agreements` / `follow_up`, если они доказаны;
- compact evidence-pack;
- совместимого `final_normalized_analysis`.

Прогноз до реализации по 6 сохраненным LLM2D payload Толегена:

| Метрика | Было | Станет | Разница |
| --- | ---: | ---: | ---: |
| Avg user payload | 12 731 chars | 5 314 chars | -7 418 chars / -58.3% |
| Avg content input with system | 19 411 chars | 11 994 chars | -7 418 chars / -38.2% |
| 25-call day user payload estimate | 318 275 chars | 132 850 chars | -185 425 chars |

Фактический контрольный замер после реализации на сохраненном sample
`57292ab5-5164-4913-bf84-0be050d4e98c`:

| Метрика | Было | Стало | Разница |
| --- | ---: | ---: | ---: |
| System prompt | 6 680 chars | 7 928 chars | +1 248 chars |
| User payload | 15 390 chars | 10 943 chars | -4 447 chars / -28.9% |
| Full content input | 22 070 chars | 18 871 chars | -3 199 chars / -14.5% |

Почему экономия ниже раннего прогноза: static contract/rules убраны из user
payload, но усилены в `analyze_recommendations.md`, поэтому часть экономии
перешла из user payload в system prompt. Дополнительно sample содержит длинные
accepted proof cards и evidence, которые нельзя полностью удалить без риска для
качества рекомендаций.

### A11.1 Move Static Instructions Out Of User Payload

Статус: `implemented / verified by unit test`.

Что сделать:

- убрать `quality_rules` из LLM2D user payload;
- убрать `output_contract` из LLM2D user payload;
- перенести/усилить эти правила в `analyze_recommendations.md` или общий
  system prompt;
- оставить в user payload только данные звонка/артефактов.

Ожидаемый эффект:

- `quality_rules`: минус около `449 chars`;
- `output_contract`: минус около `660 chars`;
- вместе: минус около `1 109 chars` на LLM2D user payload.

Acceptance:

- LLM2D prompt все еще явно задает output shape.
- Unit test подтверждает, что `quality_rules` и `output_contract` отсутствуют
  в compact LLM2D user payload.

### A11.2 Replace Full Weak Criteria With Scoring Context

Статус: `implemented / verified by unit test`.

Проблема: LLM2D сейчас получает весь `scoring_summary.weak_criteria`, включая
длинные `criterion_name`, `comment`, `scene_ids`, `evidence_ids`. Для роли
LLM2D это избыточно: он не должен заново оценивать критерии.

Что сделать:

- оставить `stage_scores`;
- заменить полный `weak_criteria` на:
  - `weak_stage_counts`;
  - `weak_examples_by_stage` максимум 1-2 коротких критерия на этап;
  - priority hints только по доказанным gap proof cards;
- не передавать длинные criterion comments, если claim/proof уже переданы.

Ожидаемый эффект:

- основной источник экономии;
- по 6 payload Толегена средний LLM2D user payload:
  `12 731 -> 5 314 chars` вместе с остальными A11 изменениями;
- только `scoring_summary` в примере `57292...`: `7 252 chars`, target
  около `2 300 chars`.

Acceptance:

- LLM2D все еще может выбрать приоритет рекомендации.
- LLM2D не получает полный список всех слабых критериев.
- Adapter продолжает брать `criteria_results` и `score_by_stage` из LLM2B, а
  не из LLM2D.

### A11.3 Deduplicate Claims / Proof Cards / Evidence

Статус: `implemented / verified by unit test`.

Проблема: цитаты и объяснения частично повторяются в `proof_cards`, `claims` и
`evidence_ledger`.

Что сделать:

- в `accepted_proof_cards` оставить:
  - `proof_id`;
  - `claim_id`;
  - `stage_code`;
  - `proof_status`;
  - `proof_type`;
  - `gap_proven`;
  - `supporting_evidence_ids`;
  - `counter_evidence_ids`;
  - `softened_claim`, если есть;
  - короткий `proof_explanation`, если он не дублирует claim/evidence;
- убрать `evidence_quote` из proof card, если эта цитата уже доступна через
  `evidence_ledger`;
- передавать только claims, связанные с accepted proof cards.

Acceptance:

- Каждая рекомендация может ссылаться на `proof_id`.
- Точная цитата доступна через `evidence_ledger`.
- Нет дублирования одной и той же цитаты в proof card и evidence ledger.

### A11.4 Keep Only Referenced Evidence

Статус: `implemented / verified by unit test`.

Текущий builder уже использует `_evidence_for_referenced_claims(...)`, но нужно
проверить после A11.2/A11.3, что referenced ids не теряются.

Что сделать:

- оставить только evidence ids, которые нужны accepted proof cards / linked
  claims / follow-up facts;
- добавить unit test на случай, когда proof card ссылается на evidence id и
  evidence остается в payload.

Acceptance:

- `evidence_ledger` не пустой, если accepted proof card требует quote.
- LLM2D не получает full evidence ledger всего звонка.

### A11.5 Outcome / Follow-Up Facts As Explicit Input

Статус: `implemented / awaiting model smoke`.

Проблема: LLM2D иногда заполняет `follow_up` рекомендацией, а не фактической
договоренностью.

Что сделать:

- добавить компактный блок `follow_up_evidence` или `outcome_facts`, который
  содержит только доказанные факты:
  - concrete action;
  - owner/side;
  - timing/condition;
  - source evidence ids;
- если такого блока нет, LLM2D должен вернуть пустой factual `follow_up`, а
  coaching action оставить только в `recommendations`.

Acceptance:

- `follow_up.next_step` не заполняется recommendation-like текстом.
- `callback_planned` невозможен без concrete callback evidence.
- "можете обращаться" не становится agreement/follow_up.

### A11.6 Tests And Measurement

Статус: `implemented / targeted tests passed`.

Что сделать:

- unit tests for compact LLM2D payload:
  - no `quality_rules`;
  - no `output_contract`;
  - no full `weak_criteria`;
  - only linked claims;
  - accepted proof cards keep proof linkage;
  - referenced evidence retained.
- snapshot/diagnostic test на один persisted artifact:
  - current chars;
  - optimized chars;
  - delta percent.
- после реализации запустить 3-5 проблемных ready-STT calls:
  - `57292...`;
  - `41d2...`;
  - `19644...`;
  - `f086...`;
  - один звонок с реальной договоренностью, если есть.

Pass criteria:

- average LLM2D user payload reduction >= `45%`;
- no JSON repair increase;
- recommendations remain linked to accepted proof cards;
- no empty successful analysis for commercial admitted call;
- no false factual follow_up/agreement.

## Task A12. LLM2C No-Claims Bypass And Proof Input Trim

Статус: `implemented / awaiting model smoke`.

Контекст аудита:

- Audit file:
  `review_packages/full_run_3_managers_20260601_moonshot128/LLM2C_INPUT_AUDIT_20260603.md`
- Full request sample:
  `core/review_packages/full_run_3_managers_20260601_moonshot128/llm2c_full_request_57292ab5-5164-4913-bf84-0be050d4e98c.json`
- User payload sample:
  `core/review_packages/full_run_3_managers_20260601_moonshot128/llm2c_user_payload_57292ab5-5164-4913-bf84-0be050d4e98c.json`

Ключевой вывод:

- LLM2C легче LLM2D по user payload.
- Но 3 из 6 вызовов LLM2C в сохраненной выборке были с `0` claims.
- При `0` claims модель все равно получала system prompt около `6 540 chars`
  и user payload `1 652-2 370 chars`.
- Это no-op proof pass: если нет claims, доказывать нечего.

Прогноз до реализации по 6 сохраненным payload Толегена:

| Метрика | Было | Станет | Разница |
| --- | ---: | ---: | ---: |
| Avg user payload | 2 960 chars | 1 183 chars | -1 778 chars / -60.0% |
| Avg content input | 9 500 chars | 4 453 chars | -5 048 chars / -53.1% |
| No-claim calls | 3/6 | 0 model calls | full LLM2C call avoided |

Фактический контрольный замер после реализации на non-empty sample
`57292ab5-5164-4913-bf84-0be050d4e98c`:

| Метрика | Было | Стало | Разница |
| --- | ---: | ---: | ---: |
| System prompt | 6 540 chars | 6 540 chars | 0 |
| User payload | 4 490 chars | 3 128 chars | -1 362 chars / -30.3% |
| Full content input | 11 030 chars | 9 668 chars | -1 362 chars / -12.3% |

Важно: для no-claim calls экономия считается иначе - provider call не
выполняется совсем, а downstream получает deterministic empty proof artifact.

### A12.1 Deterministic No-Claims Bypass

Статус: `implemented / verified by unit test`.

Что сделать:

- если `strength_claims=[]` и `gap_claims=[]`, не вызывать LLM2C model;
- вернуть deterministic artifact:
  - `pass="LLM-2C"`;
  - `artifact_version="llm2_pass_2c_v1"`;
  - `call_id`;
  - `proof_cards=[]`;
  - `claim_audit.input_claim_count=0`;
  - `claim_audit.proven_count=0`;
  - `claim_audit.softened_count=0`;
  - `claim_audit.rejected_count=0`;
  - `claim_audit.insufficient_count=0`;
  - `counter_evidence_notes=[]`;
  - `quote_grounding_notes=[]`;
  - `absence_proof_notes=[]`;
  - `fail_closed.unmatched_claim_ids=[]`;
  - `fail_closed.reject_reasons=[]`.

Важно:

- это не business stop-condition;
- это не фильтр анализа;
- это no-op proof pass, потому LLM2C нечего доказывать.

Acceptance:

- no-claim call не делает provider request на LLM2C;
- downstream LLM2D/adapter получают валидный пустой proof artifact;
- pass diagnostics явно показывают `bypass_used=true` / `bypass_reason=no_claims`.

### A12.2 Remove Static Task Contract From LLM2C User Payload

Статус: `implemented / verified by unit test`.

Что сделать:

- убрать `task_contract.quality_rules` из LLM2C user payload;
- держать output shape/rules в `analyze_claim_proof.md` и общем system prompt;
- не дублировать static rules в каждом user payload.

Acceptance:

- LLM2C prompt все еще задает output JSON shape.
- Unit test подтверждает отсутствие `task_contract.quality_rules` в compact
  LLM2C user payload.

### A12.3 Trim Claim Fields For Proof Task

Статус: `implemented / verified by unit test`.

Что нужно LLM2C:

- `claim_id`;
- `claim`;
- `stage_code`;
- `claim_scope`;
- `claim_type`;
- `scene_ids`;
- `evidence_ids`.

Что можно убрать/не передавать по умолчанию:

- длинные `expected_behavior`;
- длинные `observed_behavior`;
- `confidence`, если proof decision опирается на evidence, а не на уверенность
  LLM2B;
- любые поля, не участвующие в proof decision.

Acceptance:

- proof card сохраняет связь с исходным `claim_id`;
- LLM2C не получает лишние scoring comments;
- для manager-gap absence claims остается достаточно context, чтобы не ломать
  proof.

### A12.4 Filter Scene Index And Evidence Ledger

Статус: `implemented / verified by unit test`.

Что сделать:

- передавать `scene_index` только по scenes, на которые ссылаются claims;
- передавать `evidence_ledger` только по evidence ids, на которые ссылаются
  claims;
- для absence-based gap claims без `evidence_ids` оставить compact scene
  context по `scene_ids`, потому отсутствие действия может доказываться
  последовательностью сцены.

Acceptance:

- referenced evidence не теряется;
- unreferenced evidence не попадает в LLM2C payload;
- gap claims без direct evidence не становятся автоматически rejected только из
  за trimmed payload.

### A12.5 Tests And Measurement

Статус: `implemented / targeted tests passed`.

Что сделать:

- unit test: no-claims bypass returns deterministic artifact;
- unit test: no-claims bypass does not call provider;
- unit test: non-empty claims still build LLM2C payload;
- unit test: referenced scene/evidence retained;
- unit test: unreferenced evidence omitted;
- diagnostic snapshot:
  - current LLM2C payload chars;
  - optimized LLM2C payload chars;
  - no-claims content avoided.

Pass criteria:

- no-claim LLM2C calls avoided;
- average content input reduction >= `40%` on the 6-call sample;
- proof quality preserved for non-empty claims;
- downstream LLM2D accepts deterministic empty proof artifact.

## Proposed Execution Order

1. A1 inventory current payload sizes.
2. A2 compact LLM2A payload/output.
3. A3 compact LLM2B payload/output.
4. A4 compact LLM2C payload/output.
5. A5 compact LLM2D payload/output.
6. A6 deterministic adapter.
7. A7 diagnostics.
8. A8 universal prompt rules.
9. A9 tests and one-call smoke.
10. A11 LLM2D role-fit input optimization.
11. A12 LLM2C no-claims bypass and proof input trim.
12. A10 permanent docs.

## Open Questions

1. RESOLVED 2026-06-04: `AI_LLM2_INPUT_PROFILE=compact` is the default runtime
   profile for future pilot runs.
2. RESOLVED 2026-06-04: compact profile is used for all providers unless an
   explicit legacy/debug override is set.
3. Should LLM2D remain an LLM pass, or should part of final assembly move to
   deterministic adapter to reduce output size further?
4. Should LLM1 input also be compacted in the same pass, since LLM1 exceeded
   8k with current prompt?
