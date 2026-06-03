# TMP: LLM2 Semantic Defect Registry

Дата создания: 2026-06-02
Статус: temporary working registry

## Назначение

Этот файл собирает смысловые дефекты `LLM-2` не как разрозненные баги, а как
классы проблем, из которых выводятся системные правила анализа.

Цель registry:

- фиксировать реальные примеры, где LLM неверно поняла смысл звонка;
- группировать похожие ошибки в defect classes;
- закрывать классы проблем через универсальные правила, contracts,
  deterministic normalization, diagnostics и tests;
- не добавлять model-specific хаки вроде "если Kimi, делай иначе";
- не возвращать blocking validators как основной механизм качества.

## Принцип

LLM может свободно анализировать звонок, но механизм не обязан публиковать
смысловую ошибку без нормализации.

Правильная архитектура:

```text
LLM2A facts/evidence
  -> LLM2B scoring/claims
  -> LLM2C proof/counter-evidence
  -> LLM2D recommendations
  -> deterministic semantic normalization
  -> diagnostics/warnings
  -> report-ready artifact
```

Semantic normalization не должна выдумывать факты. Она может:

- понижать или очищать unsupported status/follow-up/agreement;
- отделять recommendation от факта звонка;
- подтягивать evidence по existing evidence_ids;
- добавлять diagnostics warning/repair;
- оставлять анализ usable, если факты достаточно доказаны.

## Формат дефекта

Каждый дефект фиксируется так:

```text
ID:
Title:
Status:
Severity:
Observed in:
Source phrase / evidence:
Wrong LLM output:
Correct interpretation:
Affected layers:
Systemic rule:
Fix strategy:
Tests:
Notes:
```

Status values:

- `open` - класс дефекта подтвержден, системное исправление еще не сделано;
- `partial` - часть проявлений закрыта, но класс еще не стабилен;
- `fixed_pending_smoke` - tests есть, нужен real compact/full smoke;
- `fixed` - tests + controlled smoke подтвердили исправление;
- `watch` - дефект не воспроизводится сейчас, но риск остается.

## Systemic Rule Library

### Rule: Concrete Next Step

Следующий шаг считается зафиксированным только если есть доказанное сочетание:

- конкретное действие;
- сторона/владелец действия;
- срок, время или четкое условие;
- подтверждение или принятие второй стороной, если это договоренность между
  менеджером и клиентом.

Фразы вида "можете обращаться", "если будут вопросы", "в случае интереса",
"обращайтесь" являются `polite_close` / vague availability. Они не являются:

- `callback_planned`;
- `agreement`;
- fixed next step;
- основанием для `cn_fixed_next_step=2/2`.

### Rule: Recommendation Is Not Fact

Рекомендация менеджеру не должна попадать в `follow_up.next_step`,
`agreements` или `business_outcome`, если такого шага не было согласовано в
звонке.

Пример:

- Recommendation: "обратитесь к клиенту с объяснением преимущества".
- Fact: в звонке клиент не согласовал такой follow-up.
- Output должен хранить recommendation отдельно, а `follow_up` оставить пустым
  или `next_step_fixed=false`.

### Rule: Scoring Needs Grounded Evidence

Каждый score по критерию должен иметь `evidence_ids` и, после adapter,
manager-readable `evidence`.

Если LLM2D не возвращает scoring evidence, adapter должен брать scoring из
`LLM2B.criteria_results`, а не затирать его финальным LLM2D shell.

### Rule: LLM2D Does Not Re-score

В compact profile `LLM2D` не должен заново формировать `score_by_stage`,
`criteria_results`, `strengths` и `gaps` как source of truth.

Ownership:

- `LLM2B` -> scoring, criteria, strength/gap claims;
- `LLM2C` -> proof cards and counter-evidence;
- `LLM2D` -> recommendations and short final summary only;
- adapter -> final compatible `scores_detail`.

## Defects

### Full-Day Diagnostic Context 2026-06-02

Diagnostic compact run:

- Manager: Толеген Жангазиев
- Date: `2026-06-01`
- Instruction version: `llm2_compact_kimi_full_day_diag_v1_20260602`
- Output dir: `/tmp/llm2_compact_kimi_full_day_diag_20260601_tolegen`
- Candidates: `6`
- Created analyses: `5`
- Admission rejected: `1`
- Repairs: `0`

Confirmed systemic issues:

- `SD-002`: recommendation/vague future text leaked into factual `follow_up`
  on at least `2/5` created analyses.
- `SD-003`: score inflation appeared on weak outcomes:
  `93.75` with refusal, `81.25` with open.
- `SD-006`: absence-based criteria can have empty evidence/scene context:
  `8/24` empty on one call, `15/24` empty on another.

### SD-001: False Next Step From Vague Availability

Status: `partial`

Severity: `high`

Observed in:

- compact smoke v1:
  - analysis id `4e6fe405-8562-4e4a-bb70-4424fcfaf126`
  - interaction `9b71f8fa-6f94-4079-8987-32f9a9d36061`
- compact smoke v2:
  - analysis id `58cdc8c9-7569-48f9-8c5b-84c198eb55d7`
  - same interaction

Source phrase / evidence:

```text
Можете вот обращаться, буду подробнее рассказать, помочь.
```

Wrong LLM output:

- `summary.outcome_code=callback_planned`
- `follow_up.next_step` populated as if a callback/action exists
- v1 also created `agreements=[обратиться в случае возникновения вопросов]`
- `cn_fixed_next_step=2/2` on vague availability evidence

Correct interpretation:

- polite close / vague availability;
- no callback planned;
- no agreement;
- no fixed next step;
- scoring may credit polite close, but not concrete next-step fixation.

Affected layers:

- `LLM2B` scoring;
- `LLM2D` final summary/follow_up;
- adapter semantic normalization.

Systemic rule:

- `Concrete Next Step`.

Fix strategy:

- `partial done`: adapter removes direct vague availability from agreements and
  follow_up when exact vague phrases are present.
- `open`: broaden adapter rule to handle paraphrases like "в случае интереса
  клиента" and `callback_planned` without concrete callback evidence.
- `open`: calibrate `LLM2B` so `cn_fixed_next_step` cannot be `2/2` when the
  only evidence is vague availability.

Tests:

- `core/tests/test_llm2_layered_analysis.py::test_vague_availability_is_not_callback_or_agreement`
  covers direct vague availability in adapter.
- Need tests for paraphrased callback/follow_up and scoring downgrade.

Notes:

- This is not Kimi-specific. Any LLM can over-read polite availability as an
  agreement unless the system defines the invariant.

### SD-002: Recommendation Leaks Into Follow-Up

Status: `open`

Severity: `high`

Observed in:

- compact smoke v2, analysis id `58cdc8c9-7569-48f9-8c5b-84c198eb55d7`.

Source situation:

- Client did not agree to a concrete next contact.
- LLM2D recommendation suggested manager should explain benefits and ask for
  interest.

Wrong LLM output:

```text
follow_up.next_step = "Обратитесь к клиенту с подробным объяснением преимущества..."
```

Correct interpretation:

- This is a recommendation for the manager, not a factual follow-up agreed in
  the call.
- It belongs in `recommendations`, not `follow_up`.

Affected layers:

- `LLM2D`;
- adapter semantic normalization;
- report layer if it consumes follow_up as fact.

Systemic rule:

- `Recommendation Is Not Fact`.

Fix strategy:

- Add adapter check: if `follow_up.next_step` is phrased as manager advice and
  lacks evidence of agreed action/timing/client commitment, clear follow_up and
  add semantic warning.
- Add LLM2D instruction: recommendations must not populate follow_up unless
  the call contains a concrete agreed next step.

Tests:

- Pending.

### SD-003: Score Inflation On Next Step

Status: `open`

Severity: `high`

Observed in:

- compact smoke v2, analysis id `58cdc8c9-7569-48f9-8c5b-84c198eb55d7`.
- full-day compact diagnostic:
  - `db11ca8e-f6ef-4418-8146-c7697834e005`: `score=93.75`,
    `outcome=refusal`;
  - `9b71f8fa-6f94-4079-8987-32f9a9d36061`: `score=81.25`,
    `outcome=open`.

Source phrase / evidence:

```text
Можете вот обращаться, буду подробнее рассказать, помочь.
```

Wrong LLM output:

- `cn_fixed_next_step=2/2`
- `score_percent=87.5`

Correct interpretation:

- The phrase is not a fixed next step.
- `cn_fixed_next_step` should be `0` or at most a weak close-related note,
  depending on checklist ownership.
- Total score should not become excellent when completion/next step is weak.
- Refusal/open outcomes can still have strong manager behavior, but high score
  requires grounded evidence across applicable criteria, not just polite tone or
  a weak close.

Affected layers:

- `LLM2B` scoring;
- adapter score calibration diagnostics.

Systemic rule:

- `Concrete Next Step`;
- `Scoring Needs Grounded Evidence`.

Fix strategy:

- Add deterministic score calibration warning/repair for completion criteria:
  if evidence for `cn_fixed_next_step` is vague availability and no concrete
  timing/action/owner exists, downgrade score and add diagnostic.
- Add test with criterion code `cn_fixed_next_step`.

Tests:

- Pending.

### SD-006: Absence-Based Criteria Without Evidence Context

Status: `open`

Severity: `medium`

Observed in:

- full-day compact diagnostic `llm2_compact_kimi_full_day_diag_v1_20260602`:
  - `c4eba985-a8ce-4be9-9180-3a88b04e8a99`: `8/24` criteria empty evidence;
  - `ac275c55-42a4-47d5-8b30-4f964f582d88`: `15/24` criteria empty evidence.

Source pattern:

- Criteria scored `0` or `1` for absent behavior:
  - "Менеджер не выявил..."
  - "Нет информации..."
  - "Не определены..."
- `LLM2B.criteria_results[*].evidence_ids=[]`.

Wrong output:

- Final `criteria_results.evidence` is empty.
- Adapter cannot hydrate evidence because LLM2B did not cite scene/evidence ids.

Correct interpretation:

- For absence-based scoring, evidence may be "absence in available scene", but
  it still needs scene context.
- Criteria with score `0/1` should include at least:
  - relevant `scene_ids`, or
  - `missing_evidence_reason`, or
  - `absence_context` derived from available scene/evidence.

Affected layers:

- `LLM2B` scoring;
- adapter diagnostics;
- score/report readability.

Systemic rule:

- `Scoring Needs Grounded Evidence`.

Fix strategy:

- Add LLM2B rule: for absent behavior, cite the scene where the absence is
  evaluated and provide `missing_evidence_reason`.
- Add adapter normalization: if `score < max_score` and evidence is empty but
  comment/missing_evidence_reason exists, fill a neutral evidence/context field
  like "Не найдено в доступном фрагменте: ...", and add diagnostic
  `absence_based_evidence_context`.
- Add tests for absence-based criteria.

Tests:

- Pending.

### SD-004: LLM2D Overwrites Scoring Evidence

Status: `fixed_pending_smoke`

Severity: `high`

Observed in:

- compact smoke v1, analysis id `4e6fe405-8562-4e4a-bb70-4424fcfaf126`.

Wrong output:

- `criteria_empty_evidence=20/20`.

Correct interpretation:

- `LLM2B.criteria_results` had `evidence_ids`; adapter should hydrate evidence
  from `LLM2A.evidence_ledger`.
- `LLM2D.final_normalized_analysis.criteria_results` must not be the primary
  source of scoring when LLM2B exists.

Affected layers:

- adapter;
- LLM2D compact output contract.

Systemic rule:

- `LLM2D Does Not Re-score`;
- `Scoring Needs Grounded Evidence`.

Fix strategy:

- Done: adapter prioritizes `LLM2B.criteria_results`.
- Done: compact LLM2D output contract no longer asks for `score_by_stage` or
  `criteria_results`.
- Done: compact LLM2D payload no longer sends top-level full scoring arrays.

Tests:

- `core/tests/test_llm2_layered_analysis.py::test_llm2b_scoring_is_source_of_truth_when_llm2d_omits_evidence`
- `core/tests/test_ai_provider_routing.py::test_llm2_compact_profile_removes_full_contract_from_payloads`

Smoke:

- compact smoke v2 confirmed `criteria_empty_evidence=0/16`.

### SD-005: LLM2D Compact Input Bloat

Status: `fixed_pending_full_comparison`

Severity: `medium`

Observed in:

- compact smoke v1:
  - LLM2D payload `30 496 chars`
  - LLM2D total tokens `21 082`

Correct target:

- LLM2D should get enough information to recommend, not full scoring/proof
  artifacts duplicated at top level.

Affected layers:

- compact LLM2D payload builder.

Systemic rule:

- `LLM2D Does Not Re-score`.

Fix strategy:

- Done: replace top-level `criteria_results`, `stage_scores`, `proof_cards`
  with `scoring_summary` and compact `recommendation_sources`.

Smoke:

- compact smoke v2:
  - LLM2D payload `12 940 chars`
  - LLM2D total tokens `13 242`

Remaining:

- Need full-vs-compact baseline if exact optimization percentage is required.

## Current Open Work

1. Add systemic `Concrete Next Step` score calibration for `LLM2B` output and
   adapter.
2. Add `Recommendation Is Not Fact` normalization for `follow_up`.
3. Add tests for paraphrased false callback:
   - "в случае интереса клиента";
   - "если клиент захочет";
   - recommendation-like manager actions.
4. Run same one-call compact smoke after fixes.
5. Only after one-call quality is acceptable, run small quality set.

## Handoff Notes

Start next work by reading:

```text
/root/ai-sales-analyzer/TMP_LLM2_INPUT_OPTIMIZATION_TASKS.md
/root/ai-sales-analyzer/TMP_LLM2_SEMANTIC_DEFECT_REGISTRY.md
```

Do not treat this registry as a hard validator specification. It is a working
source for systemic semantic invariants and regression tests.
