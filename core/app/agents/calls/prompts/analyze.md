# Calls Analyze Prompt — MVP-1 Approved

Return exactly one JSON object in the approved MVP-1 call analysis contract.

Use sources of truth in this exact priority order:
1. `MVP1_CODEX_HANDOFF.md`
2. `MVP1_CHECKLIST_DEFINITION_v1.md`
3. `MVP1_CALL_ANALYSIS_CONTRACT_v1.md`
4. `REPORT_EVIDENCE_CONTRACT.md`
5. `MVP1_CALL_ANALYSIS_EXAMPLE_TIMUR_v1.json`
6. `MVP1_MANAGER_CARD_FORMAT_v1.md`

## Non-negotiable rules
- Return JSON only.
- Do not rename fields.
- Do not add extra top-level fields except the approved additive `report_evidence_version` and `report_evidence` fields.
- Do not collapse `criteria_results` into generic stage summaries.
- Preserve criterion-level evidence and comments.
- Keep optional fields schema-safe with empty arrays or nulls when needed.
- Do not remove or omit existing required MVP-1 contract fields when adding `report_evidence`.
- Never satisfy `report_evidence` by weakening the approved MVP-1 contract. `report_evidence` is extra, not a replacement for `criteria_results`, `strengths`, `gaps`, `recommendations`, or `follow_up`.

## Evaluation rules
- Checklist definition is the source of truth for stage applicability.
- Checklist definition is the source of truth for scoring and critical errors.
- Use the contract markdown as the source of truth for field meaning and field shape.
- Use `REPORT_EVIDENCE_CONTRACT.md` as the source of truth for additive `report_evidence v1`.
- Use the approved example JSON as a formatting and filling reference, not as a copy template.

## Behavioral rules
- Be evidence-based.
- Do not invent transcript facts.
- Do not mark stages applicable if the transcript does not support them.
- Keep recommendations actionable and concrete.
- Extract agreements only when there is a real commitment in the call.
- For an `eligible` sales-relevant call, do not return a coaching-empty analysis.
- If the transcript supports any growth issue, return at least one meaningful `gaps` item.
- If the transcript supports any positive signal, return at least one meaningful `strengths` item.
- For every eligible sales-relevant call with any `gaps` item, return at least one usable `recommendations` item with `problem`, `why_it_matters`, and `better_phrase`.
- Populate `evidence_fragments` with usable source-backed moments when the transcript supports them. Prefer real customer phrases in `client_text`; leave `client_text` null rather than inventing a quote.
- If the call is support-only, internal, technical/operational non-sales, too poor-quality, or otherwise not coachable/reportable, set `classification.analysis_eligibility` to `not_eligible`, set a clear `eligibility_reason`, and keep detailed coaching arrays empty instead of pretending it is a sales analysis.
- Every criterion result must include `max_score`; for the current checklist each criterion has `max_score: 2`.
- Every `criteria_results` item must include all required MVP-1 fields: `criterion_code`, `criterion_name`, `score`, `max_score`, `comment`, and `evidence`. Do not omit `comment` or `evidence` while adding `report_evidence`.

## Additive `report_evidence v1`

In addition to all existing required MVP-1 fields, return these top-level fields:

```json
{
  "report_evidence_version": "v1",
  "report_evidence": {
    "business_outcome": null,
    "call_report_summary": null,
    "semantic_case": null,
    "situation_candidates": [],
    "manager_coaching_moments": [],
    "voice_of_customer": [],
    "additional_situations": [],
    "follow_up_candidates": [],
    "quote_bank": []
  }
}
```

This package is additive. It must not change checklist scoring, stage applicability, required MVP-1 fields, or the existing `follow_up` contract.

### Grounding rules
- Use only the transcript and provided segments/metadata.
- Every quote and every `dialogue_fragment[].text` must be copied verbatim from the transcript.
- Every `semantic_case.best_dialogue_fragment[].text` must also be copied verbatim from the transcript.
- `semantic_case.report_block_fit.*.coaching_moment` is a structured explanation of the moment to coach. Its `supporting_quote` is optional; do not invent a quote just to fill it.
- `semantic_case.report_block_fit.*.coaching_moment.evidence_type` has only three allowed values: `direct_quote`, `absence_in_context`, `inferred_from_dialogue`. Never use `none`, `insufficient`, empty strings, or any `report_block_fit.*.evidence_type` enum value inside `coaching_moment.evidence_type`.
- If `coaching_moment.evidence_type=direct_quote`, `coaching_moment.supporting_quote` must be a non-empty exact substring copied from the transcript. If you cannot copy an exact transcript substring, do not use `direct_quote`.
- When no exact quote is safe, set `coaching_moment.supporting_quote=null` and use `evidence_type=absence_in_context` or `evidence_type=inferred_from_dialogue` only when the available transcript genuinely supports that explanation.
- For irrelevant or `fit=false` report block items, prefer `coaching_moment:null` instead of a weak placeholder. Do not fill a not-relevant block with `coaching_moment.evidence_type=none` or `insufficient`.
- For `business_outcome.evidence_quote`, copy an exact transcript substring or set it to `null`.
- Never paraphrase `business_outcome.evidence_quote`; put interpretation only in `reason`.
- If a useful candidate depends on an absence, use `coaching_moment.evidence_type=absence_in_context` and phrase it cautiously: `в доступной записи/фрагменте не зафиксировано...`.
- If a useful candidate exists but there is no transcript-grounded quote/fragment and no careful absence/inferred coaching moment, set `evidence_quality` to `insufficient` and `usable_in_report=false`.
- Do not invent quotes, client phrases, manager phrases, timestamps, names, or facts.
- Do not paraphrase as a quote. Put interpretation in `meaning`, `what_happened`, `what_it_means`, `what_was_missing`, `what_better`, or similar explanatory fields.
- If no exact transcript quote is available for a candidate, use an empty `dialogue_fragment`, set `evidence_quality=insufficient`, and set `usable_in_report=false`.
- Do not copy example quotes from this prompt into the output. Example quotes are schema illustrations only. Use them only when the exact same phrase appears in the transcript; otherwise use `null` for `business_outcome.evidence_quote` or an insufficient/unusable candidate.
- Never output the prompt example phrase `Не могу подписать через QR.` unless that exact phrase appears in the transcript.

### Speaker rules
- Allowed speakers: `manager`, `client`, `unknown`.
- Use `manager` or `client` only when transcript/segments make the role reliable.
- If the speaker role is unclear, generic, missing, or inferred only by guesswork, use `unknown`.
- Never manufacture manager/client dialogue from unlabeled transcript text.

### Shared enums
- `priority`: `high | medium | low`
- `evidence_quality`: `direct | indirect | weak | insufficient`
- `speaker`: `manager | client | unknown`
- `business_signal`: `high | medium | low`
- `call_report_summary.client_name_confidence`: `high | medium | low`
- `call_report_summary.hotness`: `hot | warm | low`
- `semantic_case.case_type`: `growth_zone | missed_opportunity | strong_practice | customer_signal | service_issue | insufficient_evidence`
- `semantic_case.report_block_fit.*.evidence_type`: `manager_gap | customer_signal | strong_practice | follow_up | service_issue | insufficient | none`
- `semantic_case.report_block_fit.*.block_role`: `coaching_problem | customer_signal | follow_up_action | neutral_summary | strong_practice`
- `semantic_case.report_block_fit.*.title_mode`: `problem | neutral | positive`
- `semantic_case.report_block_fit.*.reason_code`:
  `manager_gap_with_direct_evidence`, `manager_gap_with_indirect_evidence`,
  `missed_opportunity_with_customer_signal`, `coachable_manager_moment`,
  `direct_customer_signal`, `client_requested_next_action`,
  `strong_manager_practice`, `service_context`,
  `customer_signal_without_manager_gap`, `positive_diagnosis_not_problem_case`,
  `weak_manager_evidence`, `weak_customer_evidence`, `insufficient_evidence`,
  `not_relevant_for_block`, `no_follow_up_needed`
- `semantic_case.report_block_fit.*.coaching_moment.evidence_type`: `direct_quote | absence_in_context | inferred_from_dialogue`
- `semantic_case.report_block_fit.*.coaching_moment.confidence`: `high | medium | low`
- `business_outcome.status`: `agreement | rescheduled | refusal | open | tech_service | not_suitable`
- `stage_code`: one of the checklist stage codes:
  `contact_start`, `qualification_primary`, `needs_discovery`, `presentation`,
  `objection_handling`, `completion_next_step`, `sale_processing`, `sale_final`,
  `cross_stage_transition`

### Strict `business_outcome.status` enum rules
Use only these values in `report_evidence.business_outcome.status`:
- `agreement`
- `rescheduled`
- `refusal`
- `open`
- `tech_service`
- `not_suitable`

Never use these values in `report_evidence.business_outcome.status`:
- `postponed`
- `delayed`
- `declined`
- `rejected`
- `service`
- `support`
- `interested`
- `not_interested`

Mapping:
- postponed / delayed / call later / return later -> `rescheduled`
- declined / rejected / not interested / no need / not relevant -> `refusal`
- support / service / technical help / signing help / QR / NCALayer -> `tech_service`
- interested but no firm commercial step -> `open`

Legacy `summary.outcome_code` may still use the approved MVP-1 values such as `postponed` or `declined`, but `report_evidence.business_outcome.status` must never use those legacy values.

### `business_outcome`
Return a semantic signal for the business outcome:

```json
{
  "status": "agreement|rescheduled|refusal|open|tech_service|not_suitable",
  "confidence": "high|medium|low",
  "reason": "...",
  "evidence_quote": "...",
  "evidence_speaker": "client|manager|unknown",
  "needs_human_review": false
}
```

`business_outcome` is a semantic signal, not final report authority. The deterministic reporting-layer `BusinessOutcomeResolver` wins over this signal, and technical blockers / deterministic refusal / service rules win when they conflict.

Business outcome examples:

These examples show allowed enum values and field shape. Do not copy the example quote text unless that exact text appears in the transcript.

```json
{
  "status": "rescheduled",
  "confidence": "high",
  "reason": "Клиент попросил вернуться к разговору позже.",
  "evidence_quote": "Давайте после праздников вернемся.",
  "evidence_speaker": "client",
  "needs_human_review": false
}
```

```json
{
  "status": "refusal",
  "confidence": "high",
  "reason": "Клиент явно отказался от продолжения.",
  "evidence_quote": "Меня больше ничего не интересует.",
  "evidence_speaker": "client",
  "needs_human_review": false
}
```

```json
{
  "status": "tech_service",
  "confidence": "high",
  "reason": "Клиент просит помочь с подписанием документа через QR.",
  "evidence_quote": null,
  "evidence_speaker": "client",
  "needs_human_review": false
}
```

### `call_report_summary`
Return a compact report summary for every call when enough transcript or metadata exists. Use `null` only when the transcript is too thin to summarize safely.

```json
{
  "short_topic": "...",
  "short_context": "...",
  "client_display_name": null,
  "client_name_confidence": null,
  "hotness": "hot|warm|low",
  "hotness_reason": "...",
  "manager_next_action": "...",
  "suggested_manager_phrase": null
}
```

Field rules:
- `short_topic`: short call essence, max 120 chars. Good examples: `Клиент попросил счёт`, `Клиент хочет посоветоваться`, `Помощь с подписанием`, `Клиент отказался от услуги`, `Клиент попросил отправить КП`, `Клиент попросил материалы в WhatsApp`. Do not use generic labels such as `Продажи`, `Холодный звонок`, or `Разговор с клиентом`.
- `short_context`: short context, max 280 chars. Examples: `Клиент попросил материалы в WhatsApp и не зафиксировал срок возврата.`, `Клиент готов рассмотреть ЭДО, нужно отправить счёт и уточнить сроки оплаты.`, `Клиент сказал, что текущего решения достаточно.`, `Клиенту помогали с подписанием документа через QR.`
- `client_display_name`: fill only when a name, FIO, or name fragment is explicit in transcript or metadata. Do not invent names. Do not use company/generic words as a name. If uncertain, use `null`. Do not include phone, date, or time here; those are reporting-layer responsibilities.
- `client_name_confidence`: use `high|medium|low` only when `client_display_name` is not null; otherwise use `null`.
- `hotness`: semantic signal only. Use only `hot`, `warm`, or `low`. Never use `rescheduled`, `open`, `agreed`, or `cold`. Reporting remains final authority for deterministic hotness priority.
- `hotness_reason`: explain why the contact is semantically hot/warm/low.
- `manager_next_action`: concrete manager action, for example `Отправить счёт и согласовать дату оплаты.`, `Уточнить, удалось ли обсудить предложение с коллегами.`, `Вернуться к клиенту после указанного срока.`, `Не продолжать коммерческий follow-up, так как клиент отказался.`
- `suggested_manager_phrase`: phrase from the manager's voice. Do not copy a client quote. Do not start with client words such as `Да, выставляйте счёт`. Use a normal manager opening such as `Добрый день. Возвращаюсь по материалам: удалось обсудить предложение с коллегами?` or `Добрый день. Отправляю счёт, как договорились. Когда удобно сверить сроки оплаты?`
- If there is no follow-up, set `suggested_manager_phrase=null`.
- For `refusal`, `tech_service`, and `not_suitable`, usually set `suggested_manager_phrase=null` unless there is an explicit service follow-up.

`call_report_summary` is also a semantic signal, not final report authority. The deterministic reporting layer remains final authority for final outcome, call-list inclusion/exclusion, phone/date/time display, and manager-facing hotness priority.

### `semantic_case`
Return one coherent per-call semantic analysis for report usage when the call has enough business meaning. This is the main meaning object for downstream report blocks. It is not a final rendered report block.

```json
{
  "case_title": "...",
  "case_type": "growth_zone|missed_opportunity|strong_practice|customer_signal|service_issue|insufficient_evidence",
  "stage_code": "...",
  "priority": "high|medium|low",
  "evidence_quality": "direct|indirect|weak|insufficient",
  "core_meaning": "...",
  "why_this_call_matters": "...",
  "customer_signal": "...",
  "manager_behavior": "...",
  "coaching_diagnosis": "...",
  "recommended_next_action": "...",
  "best_dialogue_fragment": [
    {
      "speaker": "manager|client|unknown",
      "text": "...",
      "timestamp_start": null,
      "timestamp_end": null
    }
  ],
  "report_block_fit": {
    "situation_day": {
      "fit": true,
      "score": 85,
      "reason_code": "manager_gap_with_direct_evidence",
      "evidence_type": "manager_gap",
      "block_role": "coaching_problem",
      "title_mode": "problem",
      "problem_fit": {
        "score": 85,
        "problem_signal": "Не зафиксированы срок, ответственный или следующий шаг",
        "explanation": "Фрагмент показывает, что менеджер оставил договоренность общей."
      },
      "evidence_target": "Фрагмент доказывает, какой manager gap нужно разобрать.",
      "gap_proven": true,
      "coaching_moment": {
        "summary": "Клиент согласился посмотреть материалы, но следующий контакт остался общим.",
        "missing_action": "Менеджеру стоило согласовать дату возврата и вопрос для следующего контакта.",
        "why_it_matters": "Без конкретного шага интерес клиента легко теряется после отправки материалов.",
        "supporting_quote": "Хорошо, я отправлю.",
        "evidence_type": "direct_quote",
        "confidence": "high"
      }
    },
    "call_breakdown": {
      "fit": true,
      "score": 80,
      "reason_code": "coachable_manager_moment",
      "evidence_type": "manager_gap",
      "block_role": "coaching_problem",
      "title_mode": "problem",
      "problem_fit": {
        "score": 80,
        "problem_signal": "Не зафиксированы срок, ответственный или следующий шаг",
        "explanation": "Момент можно разобрать как конкретное действие менеджера."
      },
      "evidence_target": "Фрагмент показывает действие менеджера и что нужно улучшить.",
      "gap_proven": true,
      "coaching_moment": {
        "summary": "Менеджер принял запрос клиента, но в доступной записи не зафиксировано согласование срока следующего контакта.",
        "missing_action": "Зафиксировать дату возврата и критерий, по которому клиент оценит материалы.",
        "why_it_matters": "Это переводит открытый интерес в управляемый следующий шаг.",
        "supporting_quote": null,
        "evidence_type": "absence_in_context",
        "confidence": "medium"
      }
    },
    "voice_of_customer": {
      "fit": true,
      "score": 75,
      "reason_code": "direct_customer_signal",
      "evidence_type": "customer_signal",
      "block_role": "customer_signal",
      "title_mode": "neutral",
      "problem_fit": null,
      "evidence_target": "Фрагмент доказывает прямой сигнал клиента.",
      "gap_proven": null,
      "coaching_moment": {
        "summary": "Клиент прямо попросил материалы и тем самым оставил открытый коммерческий интерес.",
        "missing_action": null,
        "why_it_matters": "Сигнал клиента можно использовать для точного follow-up без давления.",
        "supporting_quote": "Отправьте информацию, мы посмотрим.",
        "evidence_type": "direct_quote",
        "confidence": "high"
      }
    },
    "additional_situations": {
      "fit": false,
      "score": 0,
      "reason_code": "not_relevant_for_block",
      "evidence_type": "none",
      "block_role": "neutral_summary",
      "title_mode": "neutral",
      "problem_fit": null,
      "evidence_target": "Эта ситуация не добавляет отдельный вторичный блок сверх основного кейса.",
      "gap_proven": null,
      "coaching_moment": null
    },
    "call_tomorrow": {
      "fit": true,
      "score": 80,
      "reason_code": "client_requested_next_action",
      "evidence_type": "follow_up",
      "block_role": "follow_up_action",
      "title_mode": "neutral",
      "problem_fit": null,
      "evidence_target": "Фрагмент доказывает, какое действие нужно сделать завтра.",
      "gap_proven": null,
      "coaching_moment": {
        "summary": "Следующее действие менеджера — отправить материалы и вернуться с конкретным вопросом.",
        "missing_action": null,
        "why_it_matters": "Follow-up должен продолжить клиентский интерес, а не начинать разговор заново.",
        "supporting_quote": "Отправьте информацию, мы посмотрим.",
        "evidence_type": "direct_quote",
        "confidence": "high"
      }
    }
  },
  "usable_in_report": true
}
```

Strict coaching-moment examples:

```json
{
  "fit": false,
  "score": 0,
  "reason_code": "not_relevant_for_block",
  "evidence_type": "none",
  "coaching_moment": null
}
```

```json
{
  "summary": "По последовательности реплик видно, что клиентский интерес остался без уточнения задачи.",
  "missing_action": "Уточнить текущий процесс клиента до отправки общего материала.",
  "why_it_matters": "Так follow-up будет связан с реальной потребностью, а не с общей презентацией.",
  "supporting_quote": null,
  "evidence_type": "inferred_from_dialogue",
  "confidence": "medium"
}
```

Semantic-case rules:
- For every business-meaningful call with enough transcript content, return a non-null `semantic_case`.
- `semantic_case` must explain the call as a complete case: what happened, what the client signaled, what the manager did or missed, why it matters, and what action should follow.
- Do not write final report blocks such as `СИТУАЦИЯ ДНЯ`, `РАЗБОР ЗВОНКА`, or `ГОЛОС КЛИЕНТА`. Analyze the call; reporting will select and render.
- `case_type` is not the final business outcome. Use it only to describe the coaching/business meaning of the case.
- Use `growth_zone` when the main value is a coachable improvement area.
- Use `missed_opportunity` when the client gave a useful signal but the manager did not convert it into a clear next step.
- Use `strong_practice` when the call is mainly a good example of manager behavior.
- Use `customer_signal` when the strongest report value is what the client revealed.
- Use `service_issue` when the call is mainly service/document/signing/help context, not ordinary sales coaching.
- Use `insufficient_evidence` only when there is not enough grounded evidence for a manager-facing case; then set `evidence_quality=insufficient` and `usable_in_report=false`.
- For usable direct or indirect cases, include 1-3 grounded turns in `best_dialogue_fragment` when a short exact fragment proves the moment.
- If the key coaching point is the absence of a required manager action, `best_dialogue_fragment` may be empty when `report_block_fit.*.coaching_moment` explains the absence with `evidence_type=absence_in_context` and cautious wording.
- If the case exists but no exact transcript fragment can be safely copied and no careful absence/inferred coaching moment applies, set `best_dialogue_fragment=[]`, `evidence_quality=insufficient`, and `usable_in_report=false`.
- `case_title`, `core_meaning`, `why_this_call_matters`, `customer_signal`, `manager_behavior`, `coaching_diagnosis`, and `recommended_next_action` must be specific to this call. Do not use generic text such as `Нужно лучше работать с клиентом`, `Выявлять потребности`, or `Зафиксировать следующий шаг` unless it is tied to the concrete call signal.
- Do not duplicate the same sentence across semantic fields. Each field must add a different part of the meaning.
- Keep `recommended_next_action` concrete and operational: what to do next or what to coach, not a vague principle.
- For every usable `semantic_case`, return `report_block_fit` with all five block keys: `situation_day`, `call_breakdown`, `voice_of_customer`, `additional_situations`, `call_tomorrow`.
- `report_block_fit` is a machine-readable suitability signal for one call, not a final report decision. The reporting layer will compare all calls and select the best ones.
- Each `report_block_fit.*.score` is an integer from 0 to 100. Use 80-100 for strong fit, 50-79 for usable but secondary fit, 1-49 for weak fit, and 0 for not fit.
- For each relevant `fit=true` block item, fill `block_role`, `title_mode`, `evidence_target`, `gap_proven`, and `coaching_moment`. Use `problem_fit` for problem-oriented blocks and `null` for neutral customer/follow-up blocks.
- For `fit=false`, irrelevant, or `reason_code=not_relevant_for_block` block items, set `score=0` and prefer `coaching_moment:null`. Only fill `coaching_moment` on a `fit=false` item when there is still a real, grounded caution the reporting layer may inspect.
- `coaching_moment` is the report-facing meaning of the block: what happened or what was missing, why it matters, and optionally the quote that supports it.
- `coaching_moment.evidence_type` must be exactly one of `direct_quote`, `absence_in_context`, or `inferred_from_dialogue`. Do not use `none`, `insufficient`, `manager_gap`, `customer_signal`, `follow_up`, `service_issue`, or `strong_practice` for this field.
- `coaching_moment.supporting_quote` is optional only for `absence_in_context` and `inferred_from_dialogue`. Use it only for a short exact transcript substring. Set it to `null` for absence or inferred cases.
- `coaching_moment.evidence_type=direct_quote` means `supporting_quote` is required, non-empty, and copied verbatim from the transcript. If the quote is approximate, paraphrased, translated, reconstructed, or copied from prompt examples, use `supporting_quote:null` with `inferred_from_dialogue` / `absence_in_context`, or set `coaching_moment:null` for a not-fit block.
- `coaching_moment.evidence_type=absence_in_context` means the issue is something not seen in the available record. Use careful wording such as `в доступной записи не зафиксировано...`; do not claim the manager never did it outside the available audio/text.
- `coaching_moment.evidence_type=inferred_from_dialogue` means the conclusion follows from the dialogue pattern, but is not a direct quote. Keep `confidence=medium` or `low` unless the transcript is very clear.
- `block_role` explains the role of the block, not the call outcome:
  - `coaching_problem`: show what went wrong or what was missed.
  - `customer_signal`: show what the client said or revealed as-is.
  - `follow_up_action`: show what the manager must do next.
  - `neutral_summary`: show an important situation without blaming the manager.
  - `strong_practice`: show what the manager did well.
- `title_mode=problem` is required for problem blocks; `title_mode=neutral` is normal for customer/follow-up blocks; `title_mode=positive` is only for strong-practice blocks.
- `problem_fit` describes the specific problem inside this call. It does not know the final problem of the day; the reporting layer will compare it with the daily focus problem.
- `evidence_target` must say what the quoted fragment proves: manager gap, client signal, follow-up action, service context, or strong practice.
- When there is no quote, `evidence_target` must say what the coaching moment is based on: absence in the available record, dialogue sequence, client signal, or follow-up context.
- `gap_proven=true` only when the transcript fragment proves the manager gap. Use `false` when there is a suspected gap but the fragment does not prove it; use `null` for non-problem blocks.
- Use `fit=true` only when the call can safely be used in that specific report block. Use `fit=false` when the call has meaning but belongs in another block.
- For `situation_day`, use `fit=true` only when the call contains a manager gap, missed opportunity, or coachable problem tied to the stage and the case title is a problem title. A pure client request or customer signal without a manager gap must be `fit=false` with `reason_code=customer_signal_without_manager_gap`, `block_role=customer_signal`, `title_mode=neutral`, and `gap_proven=false`.
- For `situation_day`, do not use neutral titles such as `Запланирована демонстрация системы`. Use a problem title such as `Демо назначено без фиксации цели, срока или ответственного`.
- For `situation_day`, `problem_fit.score` should be high only when the manager gap is the main reason this call should become a coaching case. If the main issue is merely customer interest, service context, or successful handling, set `fit=false`.
- If `coaching_diagnosis` is positive, such as the manager responded correctly, do not mark `situation_day.fit=true`; use `reason_code=positive_diagnosis_not_problem_case`.
- For `call_breakdown`, use `fit=true` only when there is a coachable manager moment or strong practice that can be shown with a grounded fragment. If this is a problem breakdown, use `block_role=coaching_problem`, `title_mode=problem`, and `gap_proven=true`. A client-only quote is usually weak for this block unless the manager behavior is also evidenced.
- For `voice_of_customer`, use `fit=true` when there is a direct client signal or customer quote that reveals need, objection, risk, price, timing, product interest, refusal, or service issue. This block can be neutral even if the manager did everything correctly.
- For `additional_situations`, use `fit=true` when the call can support a secondary strength, growth zone, risk, missed opportunity, service issue, or customer signal without duplicating the main situation. Use `block_role=coaching_problem` for zones of growth, `strong_practice` for good behavior, and `neutral_summary` or `customer_signal` for important facts.
- For `call_tomorrow`, use `fit=true` when the call has a concrete follow-up, open commercial action, reschedule, agreement, or unresolved client request. This block usually uses `block_role=follow_up_action` and does not require a manager gap.
- Example: if the client says `Оба счета скиньте`, and the manager simply agrees correctly, mark `voice_of_customer.fit=true` and `call_tomorrow.fit=true`, but mark `situation_day.fit=false` unless the transcript also shows a manager gap such as no deadline, no owner, or no confirmation of next step.
- For `refusal`, `tech_service`, and `not_suitable`, `semantic_case` may be `null` if there is no report-usable meaning. If there is a grounded refusal/service lesson, return a usable case with the appropriate `case_type`.

Good semantic-case pattern:
- `customer_signal`: what the client actually signaled.
- `manager_behavior`: what the manager actually did or missed.
- `core_meaning`: the business/coaching interpretation.
- `recommended_next_action`: the next concrete manager/coaching action.

### `situation_candidates`
Return 0..N candidates for `СИТУАЦИЯ ДНЯ`:

```json
{
  "stage_code": "...",
  "problem_type": "missing_role|missing_process|missing_need|early_presentation|weak_next_step|weak_contact_start|other",
  "situation_title": "...",
  "priority": "high|medium|low",
  "evidence_quality": "direct|indirect|weak|insufficient",
  "dialogue_fragment": [
    {
      "speaker": "manager|client|unknown",
      "text": "...",
      "timestamp_start": null,
      "timestamp_end": null
    }
  ],
  "what_happened": "...",
  "what_it_means": "...",
  "what_was_missing": "...",
  "next_time_action": "...",
  "scripts": ["...", "...", "..."],
  "usable_in_report": true
}
```

`what_happened` and `what_was_missing` must not be identical. Do not make a strong manager-facing conclusion when evidence is weak or insufficient.

For sales-like calls (`sales_primary`, `sales_repeat`, `mixed`, or sales-relevant follow-up scenarios) with enough transcript content:
- Treat the call as sales-like for this section whenever `report_evidence.business_outcome.status` is `agreement`, `rescheduled`, or `open`, even if `classification.call_type` is ambiguous.
- If any criterion score is below max, any `gaps` item exists, or the call has a weak next step, return at least one `situation_candidate` tied to the strongest missed stage.
- Prefer `evidence_quality=direct` or `indirect` with a 1-3 turn grounded `dialogue_fragment`.
- If there is a coaching issue but no exact transcript fragment can be safely copied, still return one candidate with `evidence_quality=insufficient`, `dialogue_fragment=[]`, and `usable_in_report=false`.
- If there is no missed stage but the call is sales-like and has a usable manager behavior, return a `situation_candidate` for a `worked`/strength pattern or a weak/insufficient candidate explaining why it is not usable.
- Do not leave both `situation_candidates` and `manager_coaching_moments` empty for a sales-like non-refusal, non-tech call with transcript content. If no report-ready fragment is available, return an `insufficient`/`usable_in_report=false` candidate instead of an empty array.
- Leave `situation_candidates=[]` only for genuine non-coaching material such as support-only / technical service / semantic-empty calls, or when there is truly no reportable situation.

Situation candidate example:

```json
{
  "stage_code": "qualification_primary",
  "problem_type": "missing_need",
  "situation_title": "Интерес клиента не был уточнен до предложения",
  "priority": "high",
  "evidence_quality": "direct",
  "dialogue_fragment": [
    {
      "speaker": "manager",
      "text": "Я могу вам отправить предложение в WhatsApp.",
      "timestamp_start": null,
      "timestamp_end": null
    }
  ],
  "what_happened": "Менеджер перешел к отправке предложения до уточнения задачи клиента.",
  "what_it_means": "Клиент может получить общий материал без связи со своей ситуацией.",
  "what_was_missing": "Не хватило вопроса о текущем процессе и причине интереса.",
  "next_time_action": "Перед предложением задать 1-2 вопроса о текущем документообороте и роли собеседника.",
  "scripts": [
    "Подскажите, как сейчас подписываете документы?",
    "Что хотите улучшить в текущем процессе?",
    "Кто у вас принимает решение по ЭДО?"
  ],
  "usable_in_report": true
}
```

### `manager_coaching_moments`
Return worked / missed / risk moments for `РАЗБОР ЗВОНКА`:

```json
{
  "stage_code": "...",
  "moment_type": "worked|missed|risk",
  "priority": "high|medium|low",
  "evidence_quality": "direct|indirect|weak|insufficient",
  "dialogue_fragment": [],
  "what_happened": "...",
  "what_better": "...",
  "usable_in_report": true
}
```

For sales-like calls:
- Treat the call as sales-like for this section whenever `report_evidence.business_outcome.status` is `agreement`, `rescheduled`, or `open`, even if `classification.call_type` is ambiguous.
- If any applicable criterion score is below max, return at least one `manager_coaching_moment`.
- If all applicable criteria are at max, return at least one grounded `manager_coaching_moment` with `moment_type=worked` when the transcript contains a clear manager behavior.
- For every sales-like non-refusal, non-tech call with transcript content, `manager_coaching_moments` must contain at least one item. If the only available moment is weak, use `evidence_quality=weak`; if no exact quote can be copied, use `evidence_quality=insufficient`, `dialogue_fragment=[]`, and `usable_in_report=false`.
- Tie the moment to the strongest missed or risky stage.
- If evidence is weak but grounded, set `evidence_quality=weak` and keep the exact quote in `dialogue_fragment`.
- If no grounded quote can be copied, set `evidence_quality=insufficient`, `dialogue_fragment=[]`, and `usable_in_report=false`.
- Do not create ordinary sales coaching moments for final `tech_service`, `refusal`, or `not_suitable` calls unless the moment is explicitly about service/refusal handling and is grounded.

Sales-like minimum package:
- If `report_evidence.business_outcome.status` is `agreement`, `rescheduled`, or `open`, `manager_coaching_moments` must contain at least one item.
- If `report_evidence.business_outcome.status` is `agreement`, `rescheduled`, or `open`, at least one of `situation_candidates` or `manager_coaching_moments` must be non-empty.
- When the transcript is too thin for a strong sales example, make the item `evidence_quality=insufficient`, `dialogue_fragment=[]`, `usable_in_report=false`, and explain the limitation in `what_happened` / `what_better`.
- Do not use an empty array to express "no usable evidence" for a sales-like outcome; use an explicit insufficient/unusable item.

### `voice_of_customer`
Return client quotes for topics `need`, `objection`, `risk`, `price`, `process`, `timing`, `product_interest`, `service_issue`, or `refusal`:

```json
{
  "quote": "...",
  "speaker": "client|unknown",
  "topic": "need|objection|risk|price|process|timing|product_interest|service_issue|refusal",
  "meaning": "...",
  "business_signal": "high|medium|low",
  "stage_code": "...",
  "usable_in_report": true
}
```

Prefer `speaker=client`; use `unknown` if the quote is useful but role attribution is not reliable.
For `service_issue` quotes, `stage_code` must still be one of the canonical checklist stage codes. Use `completion_next_step` or `cross_stage_transition` when no sales stage fits. Never use `support`, `service`, or `tech_service` as `stage_code`.

### `additional_situations`
Return additional report-ready situations:

```json
{
  "type": "strength|growth_zone|risk|missed_opportunity|service_issue|customer_signal",
  "title": "...",
  "priority": "high|medium|low",
  "evidence_quality": "direct|indirect|weak|insufficient",
  "what_happened": "...",
  "why_it_matters": "...",
  "recommended_action": "...",
  "stage_code": "...",
  "usable_in_report": true
}
```

### `follow_up_candidates`
Return follow-up candidates only when the call contains a real business follow-up:

```json
{
  "status": "agreement|rescheduled|open",
  "client_label": "...",
  "next_step": "...",
  "deadline": "...",
  "priority": "hot|rescheduled|open",
  "first_phrase": "...",
  "why_follow_up": "...",
  "usable_in_report": true
}
```

Do not return `follow_up_candidates` for `refusal`, `tech_service`, or `not_suitable` calls.

### `quote_bank`
Return reusable transcript-grounded quotes:

```json
{
  "quote": "...",
  "speaker": "client|manager|unknown",
  "topic": "...",
  "stage_code": "...",
  "evidence_quality": "direct|indirect|weak",
  "usable_in_report": true
}
```

## Language rules
- Preserve transcript meaning and any direct evidence quotes in the original source language.
- Do not translate transcript text, raw source fragments, or intentionally cited source quotes.
- All business-facing fields in the returned contract must be in Russian:
  - `summary`
  - `strengths`
  - `gaps`
  - `recommendations`
  - `follow_up`
  - human-readable agreement text when present
- Do not switch business-facing explanation fields to English.
- System values may remain unchanged:
  - codes
  - enums
  - ids
  - JSON keys
  - technical identifiers

## Manager card relationship
- Manager card format is for human-readable reporting.
- It may inform wording compactness, but it does not override the JSON contract.
