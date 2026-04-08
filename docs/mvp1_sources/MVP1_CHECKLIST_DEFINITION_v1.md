# MVP-1 Checklist Definition — AI Анализ звонков

**Document code:** `edo_sales_mvp1_checklist`  
**Version:** `v1`  
**Status:** Approved for implementation  
**Date:** 2026-03-17

## 1. Purpose

This file is the source of truth for **business evaluation logic** in MVP-1.

It defines:

- which sales calls are eligible for deep analysis,
- which stages can appear in a call,
- which criteria must be evaluated inside each stage,
- how scoring is calculated,
- which critical errors must be tracked,
- how overall level is interpreted.

Important:

- **Checklist** = evaluation rules.
- **Contract** = result of applying these rules to a specific call.
- Nothing from this checklist may be silently removed, merged, or “simplified away” in implementation.
- Anything outside MVP-1 must remain optional.

## 2. Scope of MVP-1

MVP-1 covers **sales call quality analysis** for calls related to EDO / Dogovor24 sales workflows.

Deep analysis is intended primarily for:

- first sales contact,
- repeat sales contact,
- webinar / inbound lead follow-up,
- hot incoming sales contact,
- after-signature / post-interest sales continuation,
- mixed calls where sales is still a meaningful part of the conversation.

Non-MVP mandatory modules:

- task automation from agreements,
- product voice clustering and trend digests,
- department-wide non-sales expansion.

These may exist in the contract as optional fields, but they are **not required** for MVP-1 completion.

## 3. Eligibility for deep analysis

### 3.1 Must be deep-analyzed
A call is eligible for deep analysis when **all** conditions below are true:

1. The call is sales-relevant.
2. The call duration is **180 seconds or more**.
3. The transcript quality is sufficient for evaluation.
4. The conversation contains enough manager-client exchange to judge behavior.

### 3.2 Must not be deep-analyzed
A call should remain only at classification level when one or more conditions apply:

- support-only interaction,
- internal call,
- technical / operational call without sales relevance,
- duration below 180 seconds,
- transcript too poor for reliable scoring.

### 3.3 Contract requirement
Even when a call is not deeply analyzed, the system must still return classification and eligibility fields with a clear reason.

## 4. Common dictionaries

### 4.1 `call_type`
Allowed values:

- `sales_primary`
- `sales_repeat`
- `mixed`
- `support`
- `internal`
- `other`

### 4.2 `scenario_type`
Allowed values:

- `cold_outbound`
- `hot_incoming_contact`
- `warm_webinar_or_lead`
- `repeat_contact`
- `after_signed_document`
- `post_sale_follow_up`
- `mixed_scenario`
- `other`

### 4.3 `outcome_code`
Allowed values:

- `agreed`
- `postponed`
- `declined`
- `demo_scheduled`
- `materials_sent`
- `callback_planned`
- `other`

## 5. Scoring scale

Each criterion is scored on a **0–2 scale**.

- **0** — not done / done incorrectly / harmful behavior
- **1** — partially done / weakly done / incomplete
- **2** — clearly done well and relevant to the conversation

### 5.1 Stage score
For each stage:

- `stage_score` = sum of criterion scores inside the stage
- `max_stage_score` = number of criteria in that stage × 2

### 5.2 Overall score
Overall score is calculated only from **applicable stages**:

- `total_points` = sum of all applicable criterion scores
- `max_points` = sum of max points of all applicable stages
- `score_percent` = `(total_points / max_points) * 100`

### 5.3 Level interpretation
Recommended level mapping:

- `0–49.99%` → `problematic`
- `50–69.99%` → `basic`
- `70–84.99%` → `strong`
- `85–100%` → `excellent`

If any confirmed critical error is present, `critical_failure=true` and overall level is capped at `problematic`.

## 6. Stage applicability rules

### Stage 1. Первичный контакт
Applies to almost every external client call.

### Stage 2. Квалификация и первичная потребность
Applies when the manager attempts to understand relevance, context, process, role, size, or trigger.

### Stage 3. Выявление детальных потребностей
Applies when the conversation goes beyond basic qualification and explores current pain, bottlenecks, scenarios, timing, or decision context.

### Stage 4. Формирование предложения (презентация/КП)
Applies when the manager explains the product, sends or discusses КП, or links value to the client’s process.

### Stage 5. Работа с возражениями
Applies when the client raises objections, hesitation, resistance, or doubts.

### Stage 6. Завершение и договорённости
Applies when the conversation approaches a closing, pause, recap, or next-step fixation.

### Stage 7. Оформление продажи (если применимо)
Applies only when the conversation reaches the operational sale / onboarding / document collection stage.

### Stage 8. Продажа (финал) (если применимо)
Applies only when there is a real commitment to purchase / payment / launch / final activation.

### Cross-stage criterion. Переход между этапами
Applies whenever the conversation passes through at least two meaningful stages.

## 7. Stages and criteria

## Stage 1. Первичный контакт
**Stage code:** `contact_start`

### Criterion 1
- **Code:** `cs_intro_and_company`
- **Name:** Представился и обозначил компанию
- **0:** did not introduce self/company or introduced unclearly
- **1:** introduced partially, too quickly, or with weak clarity
- **2:** clearly introduced self and company at the start

### Criterion 2
- **Code:** `cs_permission_and_relevance`
- **Name:** Проверил уместность разговора / возможность говорить
- **0:** jumped into pitch without checking whether it is possible to speak
- **1:** checked mechanically but did not adapt to the answer
- **2:** checked and adapted the opening to the client situation

### Criterion 3
- **Code:** `cs_reason_for_call`
- **Name:** Понятно обозначил причину звонка
- **0:** purpose of the call remained vague
- **1:** reason was present but weak / generic
- **2:** reason was clear and understandable for the client

### Criterion 4
- **Code:** `cs_tone_and_clarity`
- **Name:** Сохранил нейтральный, вежливый и понятный тон
- **0:** tone created friction, confusion, pressure, or irritation
- **1:** tone acceptable but uneven / too rushed
- **2:** tone calm, respectful, clear

## Stage 2. Квалификация и первичная потребность
**Stage code:** `qualification_primary`

### Criterion 1
- **Code:** `qp_current_process`
- **Name:** Выяснил, как сейчас устроен процесс / документооборот
- **0:** did not ask about current process
- **1:** touched the process superficially
- **2:** clearly asked how things work now

### Criterion 2
- **Code:** `qp_role_and_scope`
- **Name:** Уточнил роль собеседника и/или масштаб задачи
- **0:** role / company context / scale not clarified
- **1:** partially clarified
- **2:** clearly clarified enough for the conversation stage

### Criterion 3
- **Code:** `qp_need_or_trigger`
- **Name:** Проверил, есть ли реальная задача / триггер / интерес
- **0:** no real check for need or trigger
- **1:** checked weakly or too late
- **2:** clearly checked relevance of the topic

### Criterion 4
- **Code:** `qp_no_early_pitch`
- **Name:** Не ушёл в презентацию слишком рано
- **0:** moved into product explanation before basic qualification
- **1:** partly rushed into presentation
- **2:** kept qualification before pitching

## Stage 3. Выявление детальных потребностей
**Stage code:** `needs_discovery`

### Criterion 1
- **Code:** `nd_use_cases`
- **Name:** Выявил конкретные сценарии использования / типы документов / процессы
- **0:** no concrete scenarios revealed
- **1:** some scenarios touched but shallow
- **2:** concrete scenarios or workflows were identified

### Criterion 2
- **Code:** `nd_pain_and_constraints`
- **Name:** Выявил боль, ограничение, неудобство или риск текущего процесса
- **0:** no pain / friction / limitation identified
- **1:** issue mentioned but not unpacked
- **2:** pain or limitation identified clearly

### Criterion 3
- **Code:** `nd_priority_and_timing`
- **Name:** Понял приоритет и срок возможного движения
- **0:** no understanding of timing / urgency
- **1:** timing touched but vague
- **2:** timing / urgency / later return point identified

### Criterion 4
- **Code:** `nd_decision_context`
- **Name:** Понял, кто влияет на решение и как оно принимается
- **0:** decision context ignored
- **1:** touched partially
- **2:** decision logic or decision makers became clearer

## Stage 4. Формирование предложения (презентация/КП)
**Stage code:** `presentation`

### Criterion 1
- **Code:** `pr_value_linked_to_context`
- **Name:** Связал ценность продукта с контекстом клиента
- **0:** generic pitch not tied to client reality
- **1:** some linkage, but broad or weak
- **2:** explained value through the client’s actual context

### Criterion 2
- **Code:** `pr_adapted_pitch`
- **Name:** Адаптировал подачу под тип клиента / сценарий
- **0:** same generic script regardless of context
- **1:** some adaptation, but limited
- **2:** pitch clearly adapted to scenario

### Criterion 3
- **Code:** `pr_clarity_and_examples`
- **Name:** Объяснил решение ясно, без путаницы
- **0:** explanation confusing, overloaded, or hard to follow
- **1:** understandable but not crisp
- **2:** explanation was clear and client-friendly

### Criterion 4
- **Code:** `pr_no_feature_dump`
- **Name:** Не ушёл в бессвязный список функций
- **0:** dumped features without meaning
- **1:** partly overloaded with features
- **2:** kept explanation selective and relevant

## Stage 5. Работа с возражениями
**Stage code:** `objection_handling`

### Criterion 1
- **Code:** `oh_clarify_reason`
- **Name:** Уточнил реальную причину сомнения / отказа
- **0:** argued against the objection without clarifying it
- **1:** partial clarification only
- **2:** clarified the real reason before responding

### Criterion 2
- **Code:** `oh_reframe_with_value`
- **Name:** Ответил на возражение через пользу / логику клиента
- **0:** response did not address the concern
- **1:** addressed partially
- **2:** response was relevant and grounded in client context

### Criterion 3
- **Code:** `oh_safe_tone`
- **Name:** Отработал возражение экологично, без давления
- **0:** defensive, argumentative, or pressuring tone
- **1:** acceptable but tense
- **2:** calm and respectful objection handling

### Criterion 4
- **Code:** `oh_check_remaining_concern`
- **Name:** Проверил, снято ли основное сомнение
- **0:** did not test whether the concern remains
- **1:** touched it weakly
- **2:** checked whether the concern was addressed

## Stage 6. Завершение и договорённости
**Stage code:** `completion_next_step`

### Criterion 1
- **Code:** `cn_fixed_next_step`
- **Name:** Зафиксировал конкретный следующий шаг
- **0:** no concrete next step
- **1:** next step exists but vague
- **2:** next step clearly defined

### Criterion 2
- **Code:** `cn_owner_and_deadline`
- **Name:** Определил кто делает и когда
- **0:** no owner and/or timing
- **1:** only owner or only approximate time
- **2:** owner and timing are clear

### Criterion 3
- **Code:** `cn_recap_and_confirmation`
- **Name:** Подытожил договорённость и убедился, что обе стороны одинаково поняли
- **0:** no recap
- **1:** weak / incomplete recap
- **2:** clear recap and confirmation

### Criterion 4
- **Code:** `cn_polite_close`
- **Name:** Завершил разговор аккуратно и профессионально
- **0:** abrupt, awkward, or friction-heavy close
- **1:** acceptable but weak close
- **2:** professional close

## Stage 7. Оформление продажи (если применимо)
**Stage code:** `sale_processing`

### Criterion 1
- **Code:** `sp_process_explained`
- **Name:** Понятно объяснил следующий операционный шаг продажи
- **0:** process unclear
- **1:** partly explained
- **2:** process explained clearly

### Criterion 2
- **Code:** `sp_documents_or_inputs`
- **Name:** Собрал или запросил необходимые данные / документы / условия
- **0:** did not gather needed inputs
- **1:** gathered partially
- **2:** gathered what was needed for the current step

### Criterion 3
- **Code:** `sp_risks_or_blockers`
- **Name:** Выявил возможные барьеры на этапе оформления
- **0:** ignored blockers
- **1:** touched blockers partially
- **2:** identified blockers or risks explicitly

## Stage 8. Продажа (финал) (если применимо)
**Stage code:** `sale_final`

### Criterion 1
- **Code:** `sf_commitment_received`
- **Name:** Получил или подтвердил реальное обязательство клиента
- **0:** no real commitment
- **1:** weak or ambiguous commitment
- **2:** clear commitment

### Criterion 2
- **Code:** `sf_payment_or_launch_confirmed`
- **Name:** Подтвердил оплату / запуск / переход к активации
- **0:** final step unclear
- **1:** partial clarity
- **2:** final step confirmed

### Criterion 3
- **Code:** `sf_final_recap`
- **Name:** Подвёл итог финальной договорённости
- **0:** no final recap
- **1:** weak recap
- **2:** clear final recap

## Cross-stage criterion. Переход между этапами
**Stage code:** `cross_stage_transition`

### Criterion 1
- **Code:** `ct_flow_consistency`
- **Name:** Переходы между этапами логичны
- **0:** jumps, broken logic, chaotic flow
- **1:** flow partly logical
- **2:** flow coherent and natural

### Criterion 2
- **Code:** `ct_dialog_safety`
- **Name:** Сохранял конструктивность и управляемость разговора
- **0:** conversation became tense, unsafe, or unmanaged
- **1:** some tension / uneven control
- **2:** conversation remained controlled and constructive

## 8. Critical errors

If one of the following is confirmed, add it to `critical_errors[]`.

Suggested codes:

- `ce_false_information` — gave false or unverified product/process information as fact
- `ce_argumentative_tone` — argued with the client or used obviously confrontational phrasing
- `ce_disrespect` — disrespectful or dismissive phrasing
- `ce_ignored_direct_question` — ignored a direct client question in a meaningful moment
- `ce_pressure_without_relevance` — pushed product / meeting / sale with no established relevance
- `ce_no_next_step_on_relevant_call` — relevant call ended without any attempt to fix next step
- `ce_contradictory_statements` — contradicted own explanation materially

Implementation note:
- `critical_errors[]` must be stored as a list of structured items, not only as a boolean.
- `critical_failure=true` if at least one critical error is confirmed.

## 9. Required qualitative outputs

For each deeply analyzed call, the analysis must also produce:

- `strengths[]` — 1–3 strongest behaviors grounded in evidence
- `gaps[]` — 1–3 most important gaps grounded in evidence
- `recommendations[]` — concrete next-call advice, ideally with a better phrase
- `agreements[]` — only actual commitments extracted from the call
- `follow_up` — whether next step was fixed and why/why not
- `evidence_fragments[]` — short evidence-based fragments that explain score or coaching point

## 10. What is optional in MVP-1

These fields may exist in the contract, but must remain optional for MVP-1:

- `product_signals[]`
- broad trend tagging outside direct coaching need
- advanced task automation metadata
- product-digest-specific aggregation fields

## 11. Implementation boundaries

- Do not collapse criteria into one generic stage comment.
- Do not replace `criteria_results` with free text.
- Do not remove stage applicability logic.
- Do not remove evidence-based coaching outputs.
- Do not make non-MVP fields mandatory.
