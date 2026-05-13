# Report Evidence Contract — LLM2 to Reporting Layer

**Status:** design target from Step 8Y; schema/validator implemented in Step 8Z; LLM2 prompt updated in Step 8AA and tightened/verified in Step 8AC; `manager_daily` preferred-source wiring implemented in Step 8AD; semantic-case upgrade target added on 2026-05-12.
**Date:** 2026-05-12
**Milestone:** 6.5 `Business-ready Report Pack`
**Scope:** `manager_daily` first, reusable for weekly/future reports later.

## Purpose

Step 8W made `СИТУАЦИЯ ДНЯ` evidence-based by letting the reporting layer fall back to persisted `evidence_fragments`, `metadata_.segments`, or `interaction.text` when stage-linked evidence is missing.

That fallback is intentionally temporary for legacy analyses. The target architecture is that LLM2 prepares meaningful per-call analysis and report-ready evidence during call analysis, and the reporting layer only selects, aggregates, validates, ranks, and renders already prepared semantic cases and candidates.

The next upgrade changes the role boundary: LLM2 must produce a coherent semantic understanding of the call for the report blocks, not only fragments or block-specific candidate material. Reporting remains deterministic and does not become an AI interpretation layer.

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
LLM2 -> deep call analysis + checklist + semantic case + report-ready evidence package
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
- Produces a coherent `report_evidence.semantic_case` when the call has enough business meaning for report usage.
- Grounds semantic conclusions and evidence in transcript text or marks evidence as insufficient.
- Does not choose which report a call belongs to.
- Does not write final report blocks; it analyzes one call.

**Reporting layer**
- Is deterministic and is not an AI analysis layer.
- Selects report scope, report-day calls, `meaningful_calls`, and `coaching_core`.
- Runs `BusinessOutcomeResolver` for final manager-facing outcome.
- Validates and ranks `report_evidence.semantic_case` and legacy `report_evidence` candidates.
- Falls back to Step 8W legacy evidence logic when `report_evidence` is missing or invalid.

## Additive Contract

`report_evidence` is additive. It must not break or replace the approved MVP-1 call analysis contract. Existing required fields such as `classification`, `summary`, `score_by_stage`, `gaps`, `recommendations`, `follow_up`, and `evidence_fragments` remain valid.

Top-level shape:

```json
{
  "report_evidence_version": "v1",
  "report_evidence": {
    "business_outcome": {},
    "call_report_summary": {},
    "semantic_case": {},
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
client_name_confidence: high | medium | low
summary_hotness: hot | warm | low
semantic_case_type: growth_zone | missed_opportunity | strong_practice | customer_signal | service_issue | insufficient_evidence
report_block_fit.evidence_type: manager_gap | customer_signal | strong_practice | follow_up | service_issue | insufficient | none
report_block_fit.block_role: coaching_problem | customer_signal | follow_up_action | neutral_summary | strong_practice
report_block_fit.title_mode: problem | neutral | positive
report_block_fit.reason_code: manager_gap_with_direct_evidence | manager_gap_with_indirect_evidence | missed_opportunity_with_customer_signal | coachable_manager_moment | direct_customer_signal | client_requested_next_action | strong_manager_practice | service_context | customer_signal_without_manager_gap | positive_diagnosis_not_problem_case | weak_manager_evidence | weak_customer_evidence | insufficient_evidence | not_relevant_for_block | no_follow_up_needed
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

## 2. Call Report Summary

Used later by `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, and manager-facing recommendations in `ГОЛОС КЛИЕНТА`.

```json
{
  "call_report_summary": {
    "short_topic": "Клиент попросил счёт",
    "short_context": "Клиент готов рассмотреть ЭДО, нужно отправить счёт и уточнить сроки оплаты.",
    "client_display_name": "Алия",
    "client_name_confidence": "high",
    "hotness": "warm",
    "hotness_reason": "Клиент попросил материалы и оставил продолжение, но не зафиксировал срок.",
    "manager_next_action": "Отправить счёт и согласовать дату оплаты.",
    "suggested_manager_phrase": "Алия, добрый день. Отправляю счёт, как договорились. Когда удобно сверить сроки оплаты?"
  }
}
```

Field intent:
- `short_topic` — краткая суть звонка for `СПИСОК ВСЕХ ЗВОНКОВ ДНЯ`, column `Тип / суть`; max `120` chars.
- `short_context` — short manager-facing context for the call-list `Контекст`; max `280` chars.
- `client_display_name` — name/FIO/name fragment only if explicitly present in transcript or metadata; do not invent; use `null` if uncertain.
- `client_name_confidence` — `high|medium|low`; omit or set `null` when `client_display_name=null`.
- `hotness` — semantic signal only: `hot|warm|low`. `rescheduled` is a final deterministic status/category, not LLM hotness.
- `hotness_reason` — why the model sees this signal; max `280` chars.
- `manager_next_action` — concrete next action for the manager; max `280` chars.
- `suggested_manager_phrase` — phrase from the manager's voice; max `240` chars. It must not copy a client quote. If there is no commercial/service follow-up, set `null`.

Examples:
- `short_topic`: `Клиент попросил счёт`, `Клиент хочет посоветоваться`, `Помощь с подписанием`, `Клиент отказался от услуги`, `Клиент попросил отправить КП`.
- `short_context`: `Клиент попросил материалы в WhatsApp и не зафиксировал срок возврата.`
- `manager_next_action`: `Уточнить, удалось ли обсудить предложение с коллегами.`
- `suggested_manager_phrase`: `Добрый день. Возвращаюсь по материалам: удалось обсудить предложение с коллегами?`

Authority rules:
- Reporting layer remains final authority for final outcome, call-list inclusion/exclusion, and manager-facing tomorrow hotness priority.
- `call_report_summary.hotness` is a semantic signal that future reporting steps may use as input; it must not override deterministic Step 8AH-3 hotness rules by itself.
- Phone/date/time remain the reporting layer's responsibility through the unified client/call reference contract.
- For `refusal`, `tech_service`, and `not_suitable`, `suggested_manager_phrase` should usually be `null`; a non-null phrase is allowed only for explicit service follow-up and should be treated carefully by the validator/reporting layer.

## 3. Semantic Case

Used by `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`, `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА`, and call-list context enrichment as the preferred per-call meaning source when valid.

`semantic_case` is the main LLM2 output for high-quality, meaningful call analysis. It is not a final rendered report block. It is a structured case that lets the Reporting layer choose the best call and render report blocks without re-inventing the meaning from scattered fragments.

```json
{
  "semantic_case": {
    "case_title": "Клиент проявил интерес, но следующий шаг остался слабым",
    "case_type": "growth_zone|missed_opportunity|strong_practice|customer_signal|service_issue|insufficient_evidence",
    "stage_code": "completion_next_step",
    "priority": "high|medium|low",
    "evidence_quality": "direct|indirect|weak|insufficient",
    "core_meaning": "Клиент допустил продолжение после просмотра материалов, но менеджер не закрепил дату и критерий следующего контакта.",
    "why_this_call_matters": "Без конкретного следующего шага открытый интерес может потеряться и не перейти в коммерческое действие.",
    "customer_signal": "Клиент попросил материалы и оставил возможность вернуться к обсуждению.",
    "manager_behavior": "Менеджер согласился отправить информацию, но не уточнил срок возврата и вопрос для следующего контакта.",
    "coaching_diagnosis": "Нужно переводить интерес клиента в проверяемый следующий шаг.",
    "recommended_next_action": "Отправить материалы и сразу согласовать дату возврата к обсуждению.",
    "best_dialogue_fragment": [],
    "report_block_fit": {
      "situation_day": {
        "fit": true,
        "score": 85,
        "reason_code": "manager_gap_with_direct_evidence",
        "evidence_type": "manager_gap",
        "coaching_moment": {
          "summary": "Клиент согласился посмотреть материалы, но следующий контакт остался общим.",
          "missing_action": "Менеджеру стоило согласовать дату возврата и вопрос для следующего контакта.",
          "why_it_matters": "Без конкретного шага открытый интерес может потеряться после отправки материалов.",
          "supporting_quote": null,
          "evidence_type": "absence_in_context",
          "confidence": "medium"
        }
      },
      "call_breakdown": {
        "fit": true,
        "score": 80,
        "reason_code": "coachable_manager_moment",
        "evidence_type": "manager_gap"
      },
      "voice_of_customer": {
        "fit": true,
        "score": 75,
        "reason_code": "direct_customer_signal",
        "evidence_type": "customer_signal"
      },
      "additional_situations": {
        "fit": true,
        "score": 70,
        "reason_code": "missed_opportunity_with_customer_signal",
        "evidence_type": "manager_gap"
      },
      "call_tomorrow": {
        "fit": true,
        "score": 80,
        "reason_code": "client_requested_next_action",
        "evidence_type": "follow_up"
      }
    },
    "usable_in_report": true
  }
}
```

Field intent:
- `case_title` — short manager-facing title for the meaningful case.
- `case_type` — semantic category, not final business outcome.
- `stage_code` — the main checklist stage the case belongs to, when applicable.
- `priority` — importance of the case for report selection.
- `evidence_quality` — strength of the case evidence.
- `core_meaning` — what the call means as a business/coaching situation.
- `why_this_call_matters` — why this call deserves report attention.
- `customer_signal` — what the client actually signaled; use `null` only when there is no reliable client signal.
- `manager_behavior` — what the manager did, missed, or handled well.
- `coaching_diagnosis` — coaching interpretation of the behavior and signal.
- `recommended_next_action` — concrete next manager action or coaching action.
- `best_dialogue_fragment` — optional best grounded evidence fragment for this case, 1-3 turns when a short exact fragment proves the moment.
- `report_block_fit` — machine-readable block suitability for one call. It does not select final report content; it tells the deterministic Reporting layer which blocks this call can safely support.
- `report_block_fit.*.coaching_moment` — structured meaning for the block: what happened or what was missing, why it matters, optional supporting quote, evidence type, and confidence.
- `usable_in_report` — whether this semantic case is safe for manager-facing rendering.

Rules:
- `semantic_case` is optional for backward compatibility but required for fresh business-meaningful analyzer runs after this upgrade is implemented.
- For sales-like or business-meaningful calls with enough transcript content, LLM2 should return a non-null `semantic_case`.
- If the call is too thin, noisy, support-only, or semantic-empty, LLM2 may return `case_type=insufficient_evidence`, `evidence_quality=insufficient`, and `usable_in_report=false`.
- Strong manager-facing conclusions should use a grounded `best_dialogue_fragment` when a quote proves the moment. When the key issue is absence of an expected manager action, the case may instead use `report_block_fit.*.coaching_moment.evidence_type=absence_in_context` with cautious wording.
- For absence cases, phrase the conclusion as bounded to the evidence: `в доступной записи/фрагменте не зафиксировано...`; do not claim what happened outside the available record.
- `core_meaning`, `customer_signal`, `manager_behavior`, `coaching_diagnosis`, and `recommended_next_action` must not be generic copies of each other.
- Fresh usable semantic cases should include `report_block_fit` with all five block keys: `situation_day`, `call_breakdown`, `voice_of_customer`, `additional_situations`, and `call_tomorrow`.
- `report_block_fit.*.fit=true` means the call is suitable for that specific block; `score` is 0-100 and is used only for deterministic ranking/gating.
- Starting with `edo_sales_mvp1_call_analysis_v11_role_problem_fit`, fresh block-fit items should also include `block_role`, `title_mode`, `problem_fit`, `evidence_target`, and `gap_proven`.
- Starting with `edo_sales_mvp1_call_analysis_v12_coaching_moment`, fresh relevant block-fit items should include `coaching_moment`; `supporting_quote` is optional and must be omitted/null when no short exact transcript quote is needed or available.
- Starting with `edo_sales_mvp1_call_analysis_v13_cm_evidence`, `coaching_moment.evidence_type` is strictly limited to `direct_quote`, `absence_in_context`, or `inferred_from_dialogue`; do not use `none` or `insufficient` there. `direct_quote` requires a non-empty exact transcript substring in `supporting_quote`; otherwise use `supporting_quote=null` with `absence_in_context` / `inferred_from_dialogue`, or `coaching_moment=null` for an irrelevant `fit=false` block.
- `block_role` separates problem blocks from neutral/action blocks: `coaching_problem` explains what went wrong, `customer_signal` shows the client signal as-is, `follow_up_action` shows what to do next, `neutral_summary` shows an important fact, and `strong_practice` shows good manager behavior.
- `problem_fit` describes the concrete problem inside the call. Reporting compares it with the daily focus problem before using the case in `СИТУАЦИЯ ДНЯ` or the main `РАЗБОР ЗВОНКА`.
- `СИТУАЦИЯ ДНЯ` requires `block_role=coaching_problem`, `title_mode=problem`, a manager gap, a missed opportunity or coachable problem, and `gap_proven=true` when a manager gap is claimed. A pure customer signal without manager gap must be `situation_day.fit=false` with `reason_code=customer_signal_without_manager_gap`.
- If the diagnosis is positive, for example "manager responded correctly", the case must not be selected as a problem situation; use `positive_diagnosis_not_problem_case`.
- `РАЗБОР ЗВОНКА` requires a coachable manager moment or strong manager practice with grounded evidence. When the breakdown explains the main problem of the day, it should use `block_role=coaching_problem` and align with the daily focus problem; a client-only quote is usually insufficient for this block.
- `ГОЛОС КЛИЕНТА` requires a grounded client/unknown speaker signal and may be neutral even if the manager handled the moment correctly.
- `КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА` is a follow-up/action block and does not require a manager gap.
- `semantic_case` may overlap with `situation_candidates`, `manager_coaching_moments`, `voice_of_customer`, and `follow_up_candidates`; those older fields remain structured subviews and backward-compatible fallback material.
- Reporting layer may use `semantic_case` as preferred meaning source, but final status, report scope, inclusion/exclusion, hotness priority, and rendering remain deterministic.

## 4. Situation Day Candidates

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

## 5. Manager Coaching Moments

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

## 6. Voice of Customer

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

## 7. Additional Situations

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

## 8. Follow-Up Candidates

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

## 9. Quote Bank

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
13. `call_report_summary.short_topic` must fit within `120` chars; `short_context`, `hotness_reason`, and `manager_next_action` within `280`; `suggested_manager_phrase` within `240`.
14. `call_report_summary.hotness` must be `hot`, `warm`, or `low`; `rescheduled` is intentionally not allowed there.
15. `call_report_summary.client_name_confidence` must be `high`, `medium`, or `low`; if `client_display_name=null`, confidence should be omitted or `null`.
16. `call_report_summary.suggested_manager_phrase` must not equal a known client quote from `business_outcome.evidence_quote`, `voice_of_customer[]`, or `quote_bank[]`.
17. If `business_outcome.status` is `refusal`, `tech_service`, or `not_suitable`, a non-null `suggested_manager_phrase` should warn unless there is explicit follow-up/service continuation.
18. Invalid `report_evidence` must not invalidate the whole call analysis unless the future validator explicitly makes it blocking.
19. `semantic_case.case_type` must use only the allowed semantic case enum values.
20. `semantic_case.stage_code`, when present, must match the canonical checklist stage codes.
21. If `semantic_case.usable_in_report=true`, then `case_title`, `core_meaning`, `why_this_call_matters`, `manager_behavior`, `coaching_diagnosis`, and `recommended_next_action` must be non-empty and non-generic.
22. If `semantic_case.usable_in_report=true` and `evidence_quality` is `direct` or `indirect`, `best_dialogue_fragment` must contain grounded transcript text.
23. If `semantic_case.evidence_quality=insufficient`, `usable_in_report` must be `false`.
24. Strong conclusions in `semantic_case` must not be rendered if the validator flags missing evidence, generic wording, or conflict with deterministic final outcome rules.
25. `semantic_case.report_block_fit`, when present, must use only the allowed `evidence_type`, `reason_code`, `block_role`, and `title_mode` enums, and each `score` / `problem_fit.score` must be an integer from `0` to `100`.
26. Block fit is block-specific: a valid `semantic_case` can be suitable for `ГОЛОС КЛИЕНТА` or follow-up while being rejected for `СИТУАЦИЯ ДНЯ`.
27. `semantic_case.report_block_fit.*.coaching_moment`, when present, must use `evidence_type=direct_quote|absence_in_context|inferred_from_dialogue` and `confidence=high|medium|low`; it must never use `none`, `insufficient`, or the parent `report_block_fit.*.evidence_type` enum.
28. `coaching_moment.supporting_quote` is optional for absence/inferred cases, but `direct_quote` requires a non-empty exact transcript substring. When a direct quote cannot be copied exactly, use `supporting_quote=null` with `absence_in_context` / `inferred_from_dialogue`, or `coaching_moment=null` for an irrelevant `fit=false` block.

### Step 8Z implementation note

Step 8Z implemented the standalone schema and validator in `core/app/agents/calls/report_evidence.py`.

Current strictness:
- missing `report_evidence` is a valid legacy state;
- missing `report_evidence_version` fails when `report_evidence` exists;
- only `v1` is supported;
- enum/schema errors fail validation;
- `semantic_case` is optional and accepted by the runtime validator;
- invalid `semantic_case.case_type` enum values fail schema validation;
- invalid `semantic_case.stage_code` fails validation against `CHECKLIST_DEFINITION["stages"]`;
- usable direct/indirect `semantic_case` requires grounded `best_dialogue_fragment` or a non-quote `coaching_moment` for absence/inferred evidence;
- `semantic_case.evidence_quality=insufficient` must have `usable_in_report=false`;
- generic usable `semantic_case` fields fail validation;
- optional `semantic_case.report_block_fit` is accepted and schema-validated;
- optional `semantic_case.report_block_fit.*.coaching_moment` is accepted and schema-validated;
- `coaching_moment.supporting_quote` is grounded against transcript when present;
- invalid `report_block_fit.reason_code`, `evidence_type`, `block_role`, `title_mode`, score range, or `problem_fit.score` range fails schema validation;
- `call_report_summary` is optional and missing it remains a valid legacy state;
- invalid `call_report_summary.hotness` / `client_name_confidence` enum values fail validation;
- too-long `call_report_summary.short_topic` / `short_context` fields fail schema validation;
- `suggested_manager_phrase` copied from a known client quote fails validation;
- non-null `suggested_manager_phrase` on `refusal`, `tech_service`, or `not_suitable` without explicit follow-up emits a warning;
- invalid `stage_code` fails validation against `CHECKLIST_DEFINITION["stages"]` from the approved analyzer checklist source;
- ungrounded dialogue/quote text fails validation unless the item is explicitly `evidence_quality=insufficient` and `usable_in_report=false`;
- `evidence_quality=insufficient` with `usable_in_report=true` fails validation;
- identical `what_happened` / `what_was_missing` in `situation_candidates` emits a warning.

The validator is used by `manager_daily` to decide whether `report_evidence` is a valid preferred source. `semantic_case` validation is active and Report Layer now prefers valid semantic cases for the main coaching blocks where the case matches the deterministic daily focus and quality gates. `BusinessOutcomeResolver` and delivery authority remain deterministic.

## Prompt Implementation

Step 8AA updated the LLM2 deep-analysis prompt asset `core/app/agents/calls/prompts/analyze.md`.

Prompt behavior:
- all existing MVP-1 required fields remain required;
- the only approved additive top-level fields are `report_evidence_version` and `report_evidence`;
- `REPORT_EVIDENCE_CONTRACT.md` is included in the prompt source priority;
- fresh business-meaningful calls should include `report_evidence.semantic_case` as the primary coherent per-call semantic analysis for report usage;
- every quote / `dialogue_fragment[].text` must be copied verbatim from transcript;
- every `semantic_case.best_dialogue_fragment[].text` must be copied verbatim from transcript;
- fresh relevant `fit=true` report block fits should include `coaching_moment`; irrelevant `fit=false` block fits should normally use `coaching_moment=null`;
- `coaching_moment.evidence_type` is limited to `direct_quote`, `absence_in_context`, or `inferred_from_dialogue`; never use `none` or `insufficient` there;
- `coaching_moment.evidence_type=direct_quote` requires `supporting_quote` to be a non-empty exact transcript substring; otherwise use `supporting_quote=null` with absence/inferred evidence or make the irrelevant block `coaching_moment=null`;
- absence-based moments must be worded cautiously, for example `в доступной записи/фрагменте не зафиксировано...`;
- unreliable speaker roles must be `unknown`;
- weak/insufficient evidence must not become strong manager-facing proof;
- weak/insufficient semantic cases must use `case_type=insufficient_evidence`, `evidence_quality=insufficient`, `best_dialogue_fragment=[]`, and `usable_in_report=false`;
- usable semantic cases should include `report_block_fit` for all report blocks;
- follow-up candidates are allowed only for `agreement`, `rescheduled`, or `open`;
- no follow-up candidate should be returned for `refusal`, `tech_service`, or `not_suitable`;
- `business_outcome` is a semantic signal only; deterministic resolver rules remain final authority.
- starting with Step 8AH-5, fresh prompts also require `call_report_summary` when enough transcript/metadata exists, with `hotness=hot|warm|low` only and manager-voiced `suggested_manager_phrase` that does not copy client quotes.

Fresh analyzer runs now use instruction version `edo_sales_mvp1_call_analysis_v13_cm_evidence`. This marks the coaching-moment grounding change that keeps `report_evidence.semantic_case.report_block_fit.*.coaching_moment.evidence_type` inside `direct_quote | absence_in_context | inferred_from_dialogue`, requires exact transcript substrings for direct quotes, and prefers `coaching_moment=null` for irrelevant `fit=false` blocks, without changing `schema_version=call_analysis.v1`, `report_evidence_version=v1`, or checklist scoring.

### Step 8AB runtime verification note

Step 8AB ran a controlled sample on 5 exact persisted `2026-05-04` interactions. Every fresh output included `report_evidence_version="v1"` and `report_evidence`, but only 2 of 5 passed `validate_report_evidence`.

Observed gaps:
- outcome enum drift: LLM2 emitted `postponed` and `declined` instead of contract enums `rescheduled` and `refusal`;
- grounding drift: one tech/service `business_outcome.evidence_quote` was a paraphrase rather than transcript-grounded text;
- richness gap: `situation_candidates` and `manager_coaching_moments` were empty across the sample, including sales-like calls.

Until these gaps are corrected and re-verified, reporting must continue to treat Step 8W legacy evidence fallback as the safe path and must not prefer `report_evidence` for manager-facing rendering.

### Step 8AC prompt tightening verification note

Step 8AC tightened the LLM2 prompt and semantic-empty retry instruction, then reran the same 5 exact persisted interactions.

Prompt clarifications now treated as standing report-evidence generation rules:
- `business_outcome.status` must use only `agreement`, `rescheduled`, `refusal`, `open`, `tech_service`, or `not_suitable`;
- drift values such as `postponed`, `delayed`, `declined`, `rejected`, `service`, `support`, `interested`, and `not_interested` are explicitly forbidden in `report_evidence.business_outcome.status`;
- `business_outcome.evidence_quote` must be an exact transcript substring or `null`;
- prompt example quotes must not be copied into output unless the exact phrase appears in transcript;
- sales-like outcomes (`agreement`, `rescheduled`, `open`) must not leave both `situation_candidates` and `manager_coaching_moments` empty; if evidence is too thin, LLM2 must return an explicit `evidence_quality=insufficient`, `usable_in_report=false` item;
- semantic-empty retry instructions must preserve the same additive `report_evidence` requirements.

Controlled v7 result:
- `5/5` outputs included `report_evidence_version="v1"` and `report_evidence`;
- `5/5` passed `validate_report_evidence`;
- invalid enum failures: `0`;
- ungrounded evidence failures: `0`;
- sales-like calls with situation or coaching candidates: `3/3`;
- the tech/service sample remained a persisted `not_coachable_or_reportable` analysis, with valid `report_evidence.business_outcome.status=tech_service`, `evidence_quote=null`, and no follow-up candidate.

Reporting may now proceed to Step 8AD, but valid `report_evidence` must still be treated as preferred evidence input with fallback safeguards, not as a hard replacement for legacy data in older or failed analyses.

### Step 8AD reporting integration note

Step 8AD wired `manager_daily` to prefer valid `report_evidence v1` for evidence candidate selection and text enrichment.

Current implemented source policy:
- validate each report-day `meaningful_calls` analysis with `validate_report_evidence(scores_detail, transcript)`;
- if `report_evidence.semantic_case` exists, is valid, usable, grounded, aligned with the daily focus, and passes the block-specific suitability gate, prefer it for `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, and `ГОЛОС КЛИЕНТА`;
- if no usable semantic case exists, prefer existing valid `report_evidence v1` candidates for `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ`, and follow-up candidate text enrichment;
- if it is missing or invalid, use Step 8W legacy fallback;
- keep `BusinessOutcomeResolver` as final authority for `payload.call_list[]`, outcome counters, money rules, and tomorrow inclusion/exclusion;
- expose diagnostics for availability, validity, errors, warnings, version, semantic-case usage, filter reasons, and selected source.

Current diagnostic source values:
- `semantic_case` — a valid `report_evidence.semantic_case` is available as the preferred semantic source, or a final block used it;
- `report_evidence_v1` — valid legacy `report_evidence` candidates were used because no usable semantic case was available/selected;
- `legacy_fallback` — Report Layer used Step 8W or deterministic fallback because valid report evidence was missing or rejected.

`payload.report_evidence_diagnostics.calls[]` records `semantic_case_available`, `semantic_case_valid`, `semantic_case_report_block_fit`, `semantic_case_used`, `semantic_case_filtered_reason`, and `report_evidence_source` for each report-day meaningful call. `payload.report_evidence_diagnostics.blocks` records source selection plus selected/rejected semantic candidates for `situation_day`, `call_breakdown`, `voice_of_customer`, `additional_situations`, and `call_tomorrow`.

This integration does not make `report_evidence.business_outcome` final authority. It remains a semantic signal until a future resolver step explicitly consumes it under deterministic priority rules.

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

### Semantic source policy

For report blocks that need meaning, source preference is:

```text
valid report_evidence.semantic_case + block-specific suitability
-> existing valid report_evidence v1 candidates
-> Step 8W legacy fallback
```

`semantic_case` is preferred only when it is valid, evidence-grounded, non-generic, block-suitable, and compatible with deterministic report scope and final outcome rules. It does not override `BusinessOutcomeResolver`, report-day scope, `coaching_core`, `data_scope`, or tomorrow inclusion/exclusion.

### Situation Day

Prefer a valid `semantic_case` only when it represents a growth zone or missed opportunity relevant to the daily focus and passes the `situation_day` suitability gate. A customer-signal-only case without manager gap is rejected for this block even if it remains usable in `ГОЛОС КЛИЕНТА` or follow-up.

If no valid semantic case exists, choose a `situation_candidates[]` item where:
- final business outcome is sales-like: `agreement`, `rescheduled`, or `open`;
- `stage_code` matches the weakest or focus stage when possible;
- `priority` is `high` or `medium`;
- `evidence_quality` is `direct` or `indirect` preferred;
- `usable_in_report=true`.

If no valid candidate exists, use current Step 8W fallback logic. If fallback also has no evidence, render an explicit insufficient-evidence state.

### Call Breakdown

Prefer a valid `semantic_case` as the coherent call-level breakdown source when it passes the `call_breakdown` suitability gate and has a grounded dialogue fragment, concrete manager behavior, diagnosis, and recommended action.

If no valid semantic case exists, choose a `manager_coaching_moments[]` item where:
- priority is highest available;
- evidence is `direct` or `indirect`;
- item is linked to focus or weak stage when possible;
- final outcome is not `tech_service` or `refusal` unless the report explicitly presents a service/refusal example.

### Voice of Customer

Prefer `semantic_case.customer_signal` and `best_dialogue_fragment` to align interpretation and manager action when they pass the `voice_of_customer` suitability gate and are grounded in client/unknown speaker evidence.

Still choose 2-3 quotes where:
- `speaker=client`, or `speaker=unknown` with reliable transcript grounding;
- `business_signal` is `high` or `medium`;
- topic is relevant to product, need, objection, risk, process, timing, service issue, or refusal;
- `usable_in_report=true`.

### Additional Situations

Use `semantic_case` only as a ranking/seed signal for additional situations. Do not blindly duplicate the main semantic case as an extra card.

Choose top situations where:
- priority is high or medium;
- evidence is direct or indirect;
- types are distinct when possible;
- they do not duplicate Situation Day.

### Follow-Up

Use `semantic_case.recommended_next_action`, `customer_signal`, and `why_this_call_matters` only for wording enrichment when aligned with the final resolver status.

Use `report_evidence.follow_up_candidates` plus final resolver status:
- include only final `agreement`, `rescheduled`, or `open`;
- exclude `refusal`, `tech_service`, `not_suitable`, and unclassified technical buckets;
- final resolver status wins over LLM follow-up if conflict;
- final `open` renders as open, not hot agreement.

## Backward Compatibility

Compatibility rule:

```text
If report_evidence exists and passes validation:
    use semantic_case first when valid and relevant
    else use existing report_evidence v1 candidates for candidate ranking and evidence rendering
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
3. Add a new section asking LLM2 to produce `report_evidence.semantic_case` as the coherent per-call semantic analysis for report usage.
4. Instruct LLM2 to quote only transcript-grounded text.
5. Instruct LLM2 to use `speaker=unknown` when roles are unreliable.
6. Instruct LLM2 to set `usable_in_report=false` for weak/ambiguous candidates.
7. Instruct LLM2 that `report_evidence.business_outcome` is a signal; final reporting status is resolved deterministically.
8. Add examples for refusal, tech/service, open follow-up, rescheduled, agreement, semantic case, and insufficient evidence.
9. Add negative examples: invented dialogue, generic semantic case, open labeled as agreement, refusal turned into follow-up, service call treated as sales coaching.

## Rollout Plan

1. Step 8Y — design contract only. **Done.**
2. Step 8Z — implement schema / validator. **Done.**
3. Step 8AA — update LLM2 prompt. **Done.**
4. Step 8AB — controlled LLM2 runtime sample for 5 calls from `2026-05-04`. **Done; prompt tightening needed.**
5. Step 8AC — tighten `report_evidence` prompt examples/constraints and rerun a small sample. **Done; ready for bounded Step 8AD with fallback safeguards.**
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
