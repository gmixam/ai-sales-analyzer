# LLM2 Claim / Evidence Fit Audit

Дата: 2026-05-27

Статус: `audit_only`

Причина остановки: пользователь указал, что `СИТУАЦИЯ ДНЯ` показывает
строгую структуру, но доказательный фрагмент не подтверждает заявленный вывод.
До проверки механизма анализа движение по Block 2/3 остановлено.

## Проверяемая проблема

Проблема не в том, что цитата отсутствует в транскрипте. Проблема в том, что
цитата может быть реальной, но не доказывать claim.

Пример класса ошибки:

```text
Claim:
Следующий шаг не был закреплен достаточно конкретно по владельцу и сроку.

Evidence:
Все, тогда я вам счет на оплату скину, после оплаты и поступления в банк я с
вами свяжусь, чтобы помочь подписать и отправить документы.
```

Такой evidence подтверждает часть следующего шага. Он может доказывать более
узкий gap: нет точного срока, нет канала получения счета, нет явной проверки
понимания клиентом. Но он не доказывает общий claim, что следующий шаг не
закреплен.

## Главный вывод

Первичная смысловая проверка должна происходить в `LLM-2` в момент анализа
звонка. Report Layer не должен заново анализировать звонок вместо `LLM-2`, но
должен быть safety gate и не пропускать неподтвержденный claim в отчет.

Целевая ответственность:

```text
LLM-2:
- формулирует manager_gap / customer_signal / outcome;
- прикладывает exact quote / scene;
- объясняет, почему evidence доказывает claim;
- фиксирует counter_evidence, если цитата ослабляет claim;
- не маркирует problem block как fit=true без доказанного gap.

Report Evidence Validator:
- проверяет контракт proof fields;
- отклоняет context-only evidence для problem blocks;
- запускается как runtime gate, а не только как test helper.

Report Layer / LLM-3:
- выбирает только verified evidence items;
- не переанализирует звонок;
- не превращает weak/context evidence в уверенный coaching claim.
```

## Что уже есть в LLM2 prompt

В `core/app/agents/calls/prompts/analyze.md` правила уже описаны:

- quote for `situation_day` / problem `call_breakdown` must prove manager gap;
- если quote показывает, что менеджер сделал allegedly missing action, это
  `counter_evidence`;
- `quote_role=proves_gap` допустим только для `direct_gap`;
- `context_support` недостаточен для problem-oriented blocks;
- `gap_proven=false` должен запрещать problem block.

Это означает: корень не только в prompt. Правила есть, но runtime enforcement
не везде является hard gate.

## Где теряется hard gate

### 1. Analyzer validation

Файл: `core/app/agents/calls/analyzer.py`

Сейчас strict normalization проверяет форму MVP-1, stage codes и semantic
emptiness. Для `report_evidence.block_candidates` hard gate есть только на
`stage_code` у `fit=true`.

Отдельный validator `validate_report_evidence()` существует, но в analyzer
normalization не используется как обязательный gate для fresh LLM2 output.

Практический эффект: shape-valid `LLM-2` output может попасть дальше, даже если
`report_evidence` содержит proof conflicts.

### 2. Report Evidence Validator

Файл: `core/app/agents/calls/report_evidence.py`

Validator умеет ловить важные ошибки:

- `block_candidate_proof_conflict`;
- `block_candidate_context_support_problem_claim`;
- `block_candidate_direct_gap_overclaim`;
- `coaching_moment_proof_conflict`;
- `gap_proven=false` для `situation_day`;
- `quote_role=counter_evidence`.

Но найденный риск: validator не является единым runtime admission gate для всех
путей, по которым evidence затем попадает в отчет.

### 3. Legacy evidence arrays bypass

Файл: `core/app/agents/calls/report_evidence_registry.py`

Рискованные источники:

- `report_evidence.manager_coaching_moments`;
- `report_evidence.situation_candidates`;
- `report_evidence.additional_situations`;
- `evidence_fragments`.

Эти массивы часто не несут полный proof contract:

```text
gap_proven
proof_explanation
quote_role
counter_evidence
```

Registry нормализует их в `ReportEvidenceItem` и может вывести `proof_type` из
`evidence_quality` / наличия `dialogue_scene`. Это удобно для маршрутизации, но
опасно: наличие сцены начинает выглядеть как доказанность claim.

### 4. Router checks evidence presence, not semantic fit

Файл: `core/app/agents/calls/report_block_router.py`

Router fail-closed по типам и слабому proof:

- отсекает `customer_signal` для problem blocks;
- отсекает `service_issue`;
- отсекает weak/insufficient proof;
- отсекает counter_evidence, если оно явно есть;
- требует scene.

Но router не проверяет, что scene доказывает конкретный claim. Если
counter_evidence не заполнен LLM2, router не сможет понять, что цитата
противоречит claim.

### 5. Situation Day evidence packet

Файл: `core/app/agents/calls/reporting.py`

`_build_situation_day_evidence_packet()` проверяет:

- есть ли artifact/transcript;
- quote входит в transcript;
- есть ли context window / turns;
- есть ли `what_happened` и problem chain;
- нет ли некоторых известных contradiction cases.

Но это не полноценный semantic-fit gate. В частности, он может принять
`sequence_inference + supports_context` как verified/strong, хотя quote только
поддерживает контекст, а не доказывает manager gap.

## Блоки отчета и уровень риска

| Блок | Риск | Почему |
| --- | --- | --- |
| `СИТУАЦИЯ ДНЯ` | High | Problem-oriented coaching claim; сейчас может брать registry/daily composer path и принимать context evidence как verified. |
| `РАЗБОР ЗВОНКА` | High | Часто наследует claim из Situation Day или manager coaching moments; row quality проверяет наличие фрагмента, но не всегда semantic fit claim->proof. |
| `ДОПОЛНИТЕЛЬНЫЕ СИТУАЦИИ` | High/Medium | Может показывать secondary manager_gap/positive case; нужен тот же proof contract для problem items. |
| `ЧЕЛЛЕНДЖ НА ЗАВТРА` | Medium/High | Если строится из manager gaps, не должен использовать context-only evidence как доказанную проблему. |
| `ГОЛОС КЛИЕНТА` | Medium | Это customer signal, не manager gap; риск не в обвинении менеджера, а в неверной интерпретации смысла цитаты. |
| `КОНТАКТЫ В РАБОТУ` / follow-up | Medium | После Block 1 статус стал более детерминированным, но LLM2 outcome/follow_up evidence все равно должен отличать реальную договоренность от слабого интереса. |
| `БАЛЛЫ ПО ЭТАПАМ` | Medium/High | Focus stage и problem_summary идут из LLM2 criterion evidence/comments; если критерий оценен по слабому evidence, downstream focus тоже уедет. |
| `СПИСОК ЗВОНКОВ` context | Low/Medium | Меньше coaching-risk, но summary тоже не должен превращать контекст в несуществующий outcome. |

## Предварительный вывод по контрольным артефактам

На baseline artifacts 2026-05-18..2026-05-20 `validate_report_evidence()` уже
видит ошибки в части файлов. Примеры классов:

- schema/proof validation errors в `block_candidates`;
- `context_support` / `supports_context` встречаются рядом с problem blocks;
- legacy `situation_candidates` и `manager_coaching_moments` часто не содержат
  `proof_type`, `quote_role`, `gap_proven`, `counter_evidence`.

Это подтверждает гипотезу: validator знает часть проблем, но результаты
валидатора не стали обязательной точкой допуска для всех путей отчета.

## Что не нужно делать

Пока не утвержден механизм, не нужно:

- лечить только renderer;
- переписывать `СИТУАЦИЯ ДНЯ` текстом;
- добавлять еще один LLM3 rewrite;
- продолжать Block 3/4;
- пересобирать approval preview как будто Block 2 закрыт.

## Требуемый механизм

Предлагаемый target gate для LLM2/report evidence:

1. Fresh LLM2 output проходит `validate_report_evidence()` как часть analyzer
   normalization.
2. Для `fit=true` problem blocks обязательно:
   - `block_role=coaching_problem`;
   - `title_mode=problem`;
   - `gap_proven=true`;
   - `proof_type in direct_gap | sequence_inference | absence_in_context`;
   - `context_support` forbidden;
   - `quote_role=counter_evidence` forbidden;
   - `counter_evidence=[]`;
   - `proof_explanation` explains why evidence proves this exact claim.
3. `direct_gap` требует exact quote and `quote_role=proves_gap`.
4. `sequence_inference` требует coherent scene, not a single context quote.
5. `absence_in_context` требует cautious wording: "в доступной записи не
   зафиксировано", not absolute "менеджер не сделал".
6. Legacy arrays without proof fields are downgraded:
   - usable for context/diagnostics;
   - not enough for verified manager-gap blocks unless normalized into a proven
     evidence item.
7. Report Layer consumes only evidence items with explicit proof status:
   `verified_problem_claim | verified_customer_signal | verified_follow_up |
   insufficient`.
8. LLM3 receives only verified evidence IDs and cannot promote context evidence
   to a manager-gap claim.

## Следующий audit step

До реализации нужно согласовать:

1. Делаем ли `validate_report_evidence()` hard gate для fresh LLM2 output или
   сначала warning gate с retry?
2. Как поступать с legacy arrays (`manager_coaching_moments`,
   `situation_candidates`) без proof fields: полностью исключать из
   problem-oriented blocks или разрешить только после deterministic repair?
3. Для `sequence_inference`: какие минимальные поля считать достаточными
   доказательством claim?
4. Должен ли любой problem block без `gap_proven=true` fail-closed в отчете?
