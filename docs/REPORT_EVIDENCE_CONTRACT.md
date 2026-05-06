# Report Evidence Contract — LLM2 to Reporting Layer

**Status:** design target from Step 8Y; schema/validator implemented in Step 8Z; LLM2 prompt updated in Step 8AA.
**Date:** 2026-05-06  
**Milestone:** 6.5 `Business-ready Report Pack`  
**Scope:** `manager_daily` first, reusable for weekly/future reports later.

## Purpose

Step 8W made `СИТУАЦИЯ ДНЯ` evidence-based by letting the reporting layer fall back to persisted `evidence_fragments`, `metadata_.segments`, or `interaction.text` when stage-linked evidence is missing.

That fallback is intentionally temporary for legacy analyses. The target architecture is that LLM2 prepares report-ready evidence during call analysis, and the reporting layer only selects, aggregates, validates, ranks, and renders already prepared candidates.

## Source Documents

- `docs/MANAGER_DAILY_SELECTION_MODEL.md`
- `docs/BUSINESS_READY_REPORT_PACK_TASKS.md`
- `docs/PROMPTS_GUIDE.md`
- `docs/mvp1_sources/MVP1_CALL_ANALYSIS_CONTRACT_v1.md`
- `docs/mvp1_sources/MVP1_CHECKLIST_DEFINITION_v1.md`
- `docs/mvp1_sources/MVP1_MANAGER_CARD_FORMAT_v1.md`

## Target Architecture

```text
STT -> transcript + segments + speaker labels if available
LLM1 -> light classification / routing / analyze-or-skip decision
LLM2 -> deep call analysis + checklist + report-ready evidence package
Reporting layer -> deterministic selection, aggregation, rendering, delivery
```

### Responsibilities

**STT**
- Produces transcript text.
- May produce time-coded segments and speaker labels.
- Does not decide business meaning.

**LLM1**
- Performs light classification, routing, and analyze-or-skip decision.
- Does not produce manager-facing coaching content.

**LLM2**
- Produces the approved call analysis contract.
- Adds a report-ready `report_evidence` package for downstream reports.
- Grounds evidence in transcript text or marks evidence as insufficient.
- Does not choose which report a call belongs to.

**Reporting layer**
- Is deterministic and is not an AI analysis layer.
- Selects report scope, report-day calls, `meaningful_calls`, and `coaching_core`.
- Runs `BusinessOutcomeResolver` for final manager-facing outcome.
- Validates and ranks `report_evidence` candidates.
- Falls back to Step 8W legacy evidence logic when `report_evidence` is missing or invalid.

## Additive Contract

`report_evidence` is additive. It must not break or replace the approved MVP-1 call analysis contract. Existing required fields such as `classification`, `summary`, `score_by_stage`, `gaps`, `recommendations`, `follow_up`, and `evidence_fragments` remain valid.

Top-level shape:

```json
{
  "report_evidence_version": "v1",
  "report_evidence": {
    "business_outcome": {},
    "situation_candidates": [],
    "manager_coaching_moments": [],
    "voice_of_customer": [],
    "additional_situations": [],
    "follow_up_candidates": [],
    "quote_bank": []
  }
}
```

### Shared Enums

```text
priority: high | medium | low
evidence_quality: direct | indirect | weak | insufficient
speaker: manager | client | unknown
business_signal: high | medium | low
```

Canonical `stage_code` values come from `docs/mvp1_sources/MVP1_CHECKLIST_DEFINITION_v1.md`:

```text
contact_start
qualification_primary
needs_discovery
presentation
objection_handling
completion_next_step
sale_processing
sale_final
cross_stage_transition
```

If the checklist changes, the validator must use the canonical checklist dictionary rather than a duplicated stale list.

## 1. Business Outcome Evidence

Used by `ИТОГ ДНЯ`, `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, and downstream consistency checks.

```json
{
  "business_outcome": {
    "status": "agreement|rescheduled|refusal|open|tech_service|not_suitable",
    "confidence": "high|medium|low",
    "reason": "Client explicitly declined because the service is not relevant now.",
    "evidence_quote": "Сейчас не рассматриваем, нет необходимости.",
    "evidence_speaker": "client",
    "needs_human_review": false
  }
}
```

Rules:
- Current `BusinessOutcomeResolver` remains the deterministic source for final report status.
- `report_evidence.business_outcome` is a structured LLM2 signal, not final authority yet.
- Future resolver versions may use `report_evidence.business_outcome` as the primary semantic signal, but final resolver priority still wins when technical blockers, service/refusal rules, or deterministic conflict rules apply.
- If LLM2 suggests `agreement` but the final resolver finds explicit refusal, final status is `refusal`.
- If LLM2 marks `not_suitable` but transcript/evidence contains service help, final status is `tech_service`.

Allowed statuses:
- `agreement` — real commercial next step.
- `rescheduled` — client asks to return later and leaves continuation possible.
- `refusal` — explicit no / not relevant / no need / found another option.
- `open` — interest or possible continuation without firm commercial commitment.
- `tech_service` — service, signing, document, QR, NCALayer, support or existing-contract help.
- `not_suitable` — semantic-empty, wrong number, noise, or no business signal.

## 2. Situation Day Candidates

Used by `СИТУАЦИЯ ДНЯ`.

```json
{
  "situation_candidates": [
    {
      "stage_code": "qualification_primary",
      "problem_type": "missing_role|missing_process|missing_need|early_presentation|weak_next_step|weak_contact_start|other",
      "situation_title": "Клиент спрашивает про формат, но контекст не уточнён",
      "priority": "high|medium|low",
      "evidence_quality": "direct|indirect|weak|insufficient",
      "dialogue_fragment": [
        {
          "speaker": "client",
          "text": "А как у вас это работает?",
          "timestamp_start": null,
          "timestamp_end": null
        },
        {
          "speaker": "manager",
          "text": "Я сейчас всё расскажу.",
          "timestamp_start": null,
          "timestamp_end": null
        }
      ],
      "what_happened": "Менеджер начал презентацию до уточнения роли и процесса клиента.",
      "what_it_means": "Предложение может звучать общо и не попасть в реальную задачу клиента.",
      "what_was_missing": "Не хватило вопросов о текущем процессе, роли собеседника и причине интереса.",
      "next_time_action": "Сначала уточнить текущий процесс и роль клиента, затем привязать предложение к ответу.",
      "scripts": [
        "Подскажите, как сейчас у вас подписываются документы?",
        "Кто обычно принимает решение по ЭДО?",
        "Что хотите улучшить в текущем процессе?"
      ],
      "usable_in_report": true
    }
  ]
}
```

Rules:
- `dialogue_fragment` should contain 1-3 grounded turns.
- If speaker roles are unreliable, use `speaker=unknown`.
- `usable_in_report=false` is allowed when the issue exists but evidence is too weak for manager-facing proof.
- `what_happened`, `what_it_means`, and `what_was_missing` must be distinct, not repeated text.

## 3. Manager Coaching Moments

Used by `РАЗБОР ЗВОНКА`, stage examples, and coaching blocks.

```json
{
  "manager_coaching_moments": [
    {
      "stage_code": "needs_discovery",
      "moment_type": "worked|missed|risk",
      "priority": "high|medium|low",
      "evidence_quality": "direct|indirect|weak|insufficient",
      "dialogue_fragment": [
        {
          "speaker": "manager",
          "text": "Что сейчас сложнее всего в обмене документами?",
          "timestamp_start": null,
          "timestamp_end": null
        }
      ],
      "what_happened": "Менеджер задал вопрос о текущей сложности клиента.",
      "what_better": "После ответа нужно было уточнить масштаб и срок решения.",
      "usable_in_report": true
    }
  ]
}
```

Rules:
- `moment_type=worked` can support strengths.
- `moment_type=missed` and `risk` can support growth zones and challenge.
- Service/refusal calls should not be rendered as ordinary sales coaching moments unless explicitly selected for a service/refusal-specific example.

## 4. Voice of Customer

Used by `ГОЛОС КЛИЕНТА`.

```json
{
  "voice_of_customer": [
    {
      "quote": "Нам пока не актуально, мы уже нашли другое решение.",
      "speaker": "client",
      "topic": "need|objection|risk|price|process|timing|product_interest|service_issue|refusal",
      "meaning": "Client has an explicit refusal and alternative solution.",
      "business_signal": "high|medium|low",
      "stage_code": "objection_handling",
      "usable_in_report": true
    }
  ]
}
```

Rules:
- Prefer `speaker=client`.
- `speaker=unknown` is allowed only when the quote is useful but role attribution is not reliable.
- Quotes must be transcript-grounded.
- Do not paraphrase as a quote.

## 5. Additional Situations

Used by `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`.

```json
{
  "additional_situations": [
    {
      "type": "strength|growth_zone|risk|missed_opportunity|service_issue|customer_signal",
      "title": "Клиент дал сигнал интереса, но следующий шаг остался слабым",
      "priority": "high|medium|low",
      "evidence_quality": "direct|indirect|weak|insufficient",
      "what_happened": "Клиент попросил отправить информацию и посмотреть позже.",
      "why_it_matters": "Без конкретного следующего шага открытый интерес может потеряться.",
      "recommended_action": "Закрепить срок возврата и конкретный вопрос для следующего контакта.",
      "stage_code": "completion_next_step",
      "usable_in_report": true
    }
  ]
}
```

Rules:
- Avoid duplicating the selected Situation Day candidate.
- Use distinct situation types when possible.
- `service_issue` can be rendered as operational context, not sales coaching failure.

## 6. Follow-Up Candidates

Used by `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`.

```json
{
  "follow_up_candidates": [
    {
      "status": "agreement|rescheduled|open",
      "client_label": "Алия",
      "next_step": "Отправить КП и вернуться с вопросом по подключению.",
      "deadline": "завтра до 12:00",
      "priority": "hot|rescheduled|open",
      "first_phrase": "Алия, добрый день. Возвращаюсь по КП, которое обещал отправить.",
      "why_follow_up": "Клиент допустил продолжение после просмотра информации.",
      "usable_in_report": true
    }
  ]
}
```

Rules:
- Allowed statuses are only `agreement`, `rescheduled`, and `open`.
- Final `BusinessOutcomeResolver` status wins over LLM follow-up if there is a conflict.
- If final status is `refusal`, `tech_service`, `not_suitable`, or any unclassified technical bucket, reporting must exclude this candidate from tomorrow sales actions.
- Do not label final `open` as hot agreement.

## 7. Quote Bank

Reusable quote pool for daily, weekly, and future report formats.

```json
{
  "quote_bank": [
    {
      "quote": "Сейчас нет финансовой возможности.",
      "speaker": "client",
      "topic": "price",
      "stage_code": "objection_handling",
      "evidence_quality": "direct|indirect|weak",
      "usable_in_report": true
    }
  ]
}
```

Rules:
- `quote_bank` can duplicate quotes used in more specific sections.
- It should not contain invented dialogue or generic summaries.
- If role attribution is uncertain, use `speaker=unknown`.

## Validation Rules

Validator requirements:

1. `report_evidence_version` is required when `report_evidence` is present.
2. Supported version for this contract is `v1`.
3. All enums must be valid.
4. `stage_code` must match the canonical checklist stage codes.
5. `speaker` must be `manager`, `client`, or `unknown`.
6. If STT diarization or speaker attribution is unreliable, speaker must be `unknown`.
7. Evidence quote and dialogue text must be grounded in transcript text or the item must have `evidence_quality=insufficient` and `usable_in_report=false`.
8. LLM2 must not fabricate dialogue, timestamps, client names, or manager/client roles.
9. `what_happened` and `what_was_missing` must not be identical.
10. `usable_in_report=false` is allowed for weak or ambiguous evidence.
11. If `evidence_quality=insufficient`, the reporting layer must not render the item as strong proof.
12. Empty arrays are valid; missing arrays should be normalized to empty arrays.
13. Invalid `report_evidence` must not invalidate the whole call analysis unless the future validator explicitly makes it blocking.

### Step 8Z implementation note

Step 8Z implemented the standalone schema and validator in `core/app/agents/calls/report_evidence.py`.

Current strictness:
- missing `report_evidence` is a valid legacy state;
- missing `report_evidence_version` fails when `report_evidence` exists;
- only `v1` is supported;
- enum/schema errors fail validation;
- invalid `stage_code` fails validation against `CHECKLIST_DEFINITION["stages"]` from the approved analyzer checklist source;
- ungrounded dialogue/quote text fails validation unless the item is explicitly `evidence_quality=insufficient` and `usable_in_report=false`;
- `evidence_quality=insufficient` with `usable_in_report=true` fails validation;
- identical `what_happened` / `what_was_missing` in `situation_candidates` emits a warning.

The validator is not yet wired into analysis persistence, report rendering, `BusinessOutcomeResolver`, or delivery. LLM2 prompt instructions were updated in Step 8AA to request the additive package for fresh analyses.

## Prompt Implementation

Step 8AA updated the LLM2 deep-analysis prompt asset `core/app/agents/calls/prompts/analyze.md`.

Prompt behavior:
- all existing MVP-1 required fields remain required;
- the only approved additive top-level fields are `report_evidence_version` and `report_evidence`;
- `REPORT_EVIDENCE_CONTRACT.md` is included in the prompt source priority;
- every quote / `dialogue_fragment[].text` must be copied verbatim from transcript;
- unreliable speaker roles must be `unknown`;
- weak/insufficient evidence must not become strong manager-facing proof;
- follow-up candidates are allowed only for `agreement`, `rescheduled`, or `open`;
- no follow-up candidate should be returned for `refusal`, `tech_service`, or `not_suitable`;
- `business_outcome` is a semantic signal only; deterministic resolver rules remain final authority.

Fresh analyzer runs now use instruction version `edo_sales_mvp1_call_analysis_v2_report_evidence`. This marks the prompt change without changing `schema_version=call_analysis.v1` or checklist scoring.

### Step 8AB runtime verification note

Step 8AB ran a controlled sample on 5 exact persisted `2026-05-04` interactions. Every fresh output included `report_evidence_version="v1"` and `report_evidence`, but only 2 of 5 passed `validate_report_evidence`.

Observed gaps:
- outcome enum drift: LLM2 emitted `postponed` and `declined` instead of contract enums `rescheduled` and `refusal`;
- grounding drift: one tech/service `business_outcome.evidence_quote` was a paraphrase rather than transcript-grounded text;
- richness gap: `situation_candidates` and `manager_coaching_moments` were empty across the sample, including sales-like calls.

Until these gaps are corrected and re-verified, reporting must continue to treat Step 8W legacy evidence fallback as the safe path and must not prefer `report_evidence` for manager-facing rendering.

## BusinessOutcomeResolver Synchronization

Current state:
- `BusinessOutcomeResolver` is the final deterministic source for manager-facing `call_list[]`, `call_outcomes_summary`, money block, and tomorrow filtering.
- It uses persisted transcript, latest analysis, classification, follow-up, fail reason, and metadata.

Target state:
- `report_evidence.business_outcome` becomes the primary semantic input when present and valid.
- Deterministic priority and safety rules remain in the resolver.
- The resolver records the final status plus a reason code showing whether the decision came from `report_evidence`, transcript fallback, classification/follow-up, or technical blocker.

Conflict examples:

| LLM2 signal | Deterministic evidence | Final resolver status |
|---|---|---|
| `open` | explicit refusal quote | `refusal` |
| `not_suitable` | document signing / NCALayer help | `tech_service` |
| `agreement` | no concrete next commercial step | `open` or `rescheduled` |
| any business status | no transcript | `Без транскрипта` |
| any business status | provider/contract error | `Ошибка анализа` / `Ошибка провайдера` |

## Reporting Integration Plan

Reporting layer remains deterministic.

### Situation Day

Choose a `situation_candidates[]` item where:
- final business outcome is sales-like: `agreement`, `rescheduled`, or `open`;
- `stage_code` matches the weakest or focus stage when possible;
- `priority` is `high` or `medium`;
- `evidence_quality` is `direct` or `indirect` preferred;
- `usable_in_report=true`.

If no valid candidate exists, use current Step 8W fallback logic. If fallback also has no evidence, render an explicit insufficient-evidence state.

### Call Breakdown

Choose a `manager_coaching_moments[]` item where:
- priority is highest available;
- evidence is `direct` or `indirect`;
- item is linked to focus or weak stage when possible;
- final outcome is not `tech_service` or `refusal` unless the report explicitly presents a service/refusal example.

### Voice of Customer

Choose 2-3 quotes where:
- `speaker=client`, or `speaker=unknown` with reliable transcript grounding;
- `business_signal` is `high` or `medium`;
- topic is relevant to product, need, objection, risk, process, timing, service issue, or refusal;
- `usable_in_report=true`.

### Additional Situations

Choose top situations where:
- priority is high or medium;
- evidence is direct or indirect;
- types are distinct when possible;
- they do not duplicate Situation Day.

### Follow-Up

Use `report_evidence.follow_up_candidates` plus final resolver status:
- include only final `agreement`, `rescheduled`, or `open`;
- exclude `refusal`, `tech_service`, `not_suitable`, and unclassified technical buckets;
- final resolver status wins over LLM follow-up if conflict;
- final `open` renders as open, not hot agreement.

## Backward Compatibility

Compatibility rule:

```text
If report_evidence exists and passes validation:
    use report_evidence for candidate ranking and evidence rendering
else:
    use current Step 8W fallback logic
```

Implications:
- Old analyses remain reusable.
- Existing PDFs can still be rebuilt from legacy persisted data.
- Reporting diagnostics may expose `report_evidence_available=true|false`.
- Controlled re-analysis is required only for selected small samples during rollout, not for the whole history.
- `report_evidence` validation failures should be observable but non-blocking until explicitly promoted to a hard gate.

## LLM2 Prompt Update Plan

Prompt update must be a separate bounded step.

1. Keep the approved MVP-1 analysis contract intact.
2. Add a new section asking LLM2 to produce `report_evidence_version` and `report_evidence`.
3. Instruct LLM2 to quote only transcript-grounded text.
4. Instruct LLM2 to use `speaker=unknown` when roles are unreliable.
5. Instruct LLM2 to set `usable_in_report=false` for weak/ambiguous candidates.
6. Instruct LLM2 that `report_evidence.business_outcome` is a signal; final reporting status is resolved deterministically.
7. Add examples for refusal, tech/service, open follow-up, rescheduled, agreement, and insufficient evidence.
8. Add negative examples: invented dialogue, open labeled as agreement, refusal turned into follow-up, service call treated as sales coaching.

## Rollout Plan

1. Step 8Y — design contract only. **Done.**
2. Step 8Z — implement schema / validator. **Done.**
3. Step 8AA — update LLM2 prompt. **Done.**
4. Step 8AB — controlled LLM2 runtime sample for 5 calls from `2026-05-04`. **Done; prompt tightening needed.**
5. Step 8AC — tighten `report_evidence` prompt examples/constraints and rerun a small sample.
6. Step 8AD — wire `manager_daily` to prefer valid `report_evidence`.
7. Step 8AE — rebuild PDFs and compare with Step 8W.
8. Step 8AF — human review.
9. Step 8AI — separate STT diarization/speaker investigation.

## Open Questions / Risks

| Question / risk | Proposed handling |
|---|---|
| Speaker labels may be unreliable. | Keep `speaker=unknown`; never invent roles. Treat diarization as Step 8AI. |
| LLM2 may overproduce candidates. | Validator and reporting ranker cap rendered items and ignore weak/duplicated candidates. |
| LLM2 business outcome may conflict with resolver. | Resolver remains final and records conflict reason. |
| Old analyses have no `report_evidence`. | Step 8W fallback remains the compatibility path. |
| Evidence may be indirect or insufficient. | `evidence_quality` + `usable_in_report` prevent rendering weak evidence as proof. |
| Contract growth could destabilize current analyzer output. | Additive fields only; schema validation introduced before prompt rollout. |
