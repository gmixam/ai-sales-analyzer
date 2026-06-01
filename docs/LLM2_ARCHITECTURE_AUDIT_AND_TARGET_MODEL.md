# LLM-2: целевая модель анализа и layered backlog

Дата фиксации: `2026-05-27`

Статус: `active_source_of_truth`

Этот документ фиксирует текущую рабочую модель после возврата от Gate 5
block-by-block к аудиту всего механизма анализа. Исторические журналы,
подробности прежних preview и промежуточные решения не дублируются здесь.

Связанные документы:

```text
docs/ACTIVE_WORK_STATE.md
docs/GATE5_AUTONOMOUS_EXECUTION_STATUS.md
docs/PROGRESS.md
docs/DECISIONS.md
docs/TMP_LLM_NODES_ARTIFACTS_MAP.md
docs/LLM_SUBAGENT_TESTING_MODE.md
docs/REPORT_LAYER_LLM3_STRUCTURE_AUDIT_2026-05-27.md
docs/LLM2_CLAIM_EVIDENCE_FIT_AUDIT_2026-05-27.md
```

## Analysis-layer closeout handoff

Status на `2026-05-27`: analysis layer находится в handoff/closeout перед
Report Layer. STT/role attribution и `LLM-1` намеренно отложены и не входят в
текущий scope закрытия.

Что уже закрыто в рамках analysis layer:

- утверждена граница: `LLM-2` владеет смыслом, facts/scenes, scoring, gaps,
  recommendations, evidence и counter-evidence; Report Layer не заменяет
  анализ;
- подготовлены pass contracts/prompts `LLM-2A/2B/2C/2D` и handoff contract
  asset `core/app/agents/calls/prompts/llm2_pass_contracts.md`;
- введен additive `proof_card` / universal evidence contract и isolated
  admission validation;
- registry/router переведены на proof status: legacy candidates без
  `proof_card` остаются hints/diagnostics и не становятся verified source;
- отдельный LLM-node simulation agent создал layered proof artifacts по 9
  звонкам Толегена: `12 verified`, `10 soften`, `3 reject`, quote validation
  errors `0`;
- control runner summary по 9 звонкам завершен: validation `9/9`, load/match
  issues `0`, registry `102` items, router routes:
  `situation_day=4`, `call_breakdown=4`, `voice_of_customer=5`,
  `follow_up=11`, `additional_situations=1`, `challenge=4`.
- runtime path подключен в analyzer runner как default через
  `AI_LLM2_ANALYSIS_MODE=layered`: `LLM-2A -> LLM-2B -> LLM-2C -> LLM-2D`
  собираются в `normalize_llm2_layered_analysis()` и возвращают совместимый
  `scores_detail`;
- legacy monolithic `LLM-2` остается явным fallback при
  `AI_LLM2_ANALYSIS_MODE=monolithic`;
- runtime сохраняет pass artifacts и routing metadata в `scores_detail`, а
  validation/fail-closed path не выпускает weak/rejected claims как
  manager-facing gaps/recommendations;
- bounded runtime smoke по тем же 9 baseline звонкам Толегена завершен:
  `9/9 ok`, complete pass chains `9/9`, proof cards `9 proven`, gaps `9`,
  recommendations `9`; артефакт:
  `core/review_packages/llm2_recalibration_control_sample_2026-05-18_2026-05-20/llm2_layered_runtime_smoke_2026-05-27/summary.md`.

Что остается вне текущего closeout:

1. STT quality / role attribution.
2. `LLM-1` classification/eligibility/card и будущий вынос в отдельный сервис.
3. Report Layer / `LLM-3` / renderer wording поверх уже доказанного proof pool.

Guardrail:

```text
Report Layer / LLM-3 / PDF preview / Telegram preview / Telegram or email
business delivery не запускать до отдельного Report Layer шага поверх
закрытого analysis proof pool.
```

## Текущее решение

Движение идет по слоям, а не по видимым блокам отчета.

Первый активный слой:

```text
LLM-2
```

Остановленные задачи Gate 5 распределены по слоям и возвращаются в отчет только
после стабилизации analysis/evidence/proof механизма.

Основная цель:

```text
Упростить механизм анализа и повысить смысловое качество.
Доказательство является частью смысла: вывод из звонка не может считаться
качественным, если он не подкреплен конкретным моментом разговора, где явно
видна заявленная проблема.
```

Главная цепочка качества:

```text
звонок -> сцена -> claim -> evidence -> counter-evidence -> recommendation -> отчет
```

Если эта цепочка не доказана на уровне анализа, отчет не должен показывать
уверенный coaching claim.

## Почему мы вернулись к механизму

Gate 5 preview показал, что отчет может иметь строгую структуру и при этом
передавать слабый или недоказанный смысл.

Пример проблемы:

```text
СИТУАЦИЯ ДНЯ показывает claim "следующий шаг не закреплен",
но приведенный фрагмент разговора не доказывает этот claim достаточно четко.
```

Вывод:

- проблема не только в Report Layer или `LLM-3`;
- корень находится в цепочке `LLM-2 -> validators -> registry/router`;
- Report Layer и `LLM-3` могут сделать проблему видимой, но не должны
  становиться главным аналитиком;
- нужно сначала стабилизировать смысл и доказательство, потом возвращаться к
  блокам отчета.

## Архитектурная цепочка

Текущая цепочка анализа:

```text
LLM-1
-> LLM-2
-> validators / normalizers
-> report evidence registry
-> report block router
-> Report Layer
-> LLM-3
-> renderer / PDF / Telegram
```

Целевая ответственность:

| Слой | Целевая роль | Не должен делать |
|---|---|---|
| `LLM-1` | классификация, карточка звонка, eligibility/routing | глубокий анализ, coaching claims, report evidence |
| `LLM-2` | смысл звонка, факты, scoring, gaps, recommendations, evidence, counter-evidence | выбирать блоки отчета, готовить report-specific routing |
| Validators / normalizers | admission gate для proof contract | заменять LLM-анализ |
| Registry / router | normalized proof pool и маршрутизация доказанного материала | повышать legacy candidates до verified source |
| Report Layer | дневной фокус, selection, hard gates | собирать смысл из слабых частей |
| `LLM-3` | manager-facing narrative по выбранному материалу | менять факты, усиливать claim, придумывать proof |
| Renderer / PDF / Telegram | показать утвержденный payload | менять смысл или маскировать слабое доказательство |

## Главное правило по слоям

```text
Смысл и доказательство живут прежде всего в LLM-2 и validators.
Registry/router сохраняют и маршрутизируют только доказанный материал.
Report Layer выбирает фокус и применяет safety gates.
LLM-3 и renderer отвечают за понятность формы, но не за истинность вывода.
```

## Дополнение 2026-06-01: admission gate до LLM-2

После full-day проверки Толегена за `2026-05-19` выявлено, что layered
`LLM-2` сам добавил внутренний gate: `LLM-2A` помечал коммерчески релевантные,
но короткие звонки как `analysis_eligibility=not_eligible` из-за
`duration_below_threshold`, а `LLM-2B` затем возвращал `stage_scores=[]`.

Архитектурное решение:

```text
Условия допуска должны жить до входа в LLM-2.
Если звонок уже передан в LLM-2, узлы LLM-2A/2B/2C/2D выполняют свои роли и не
имеют права целиком остановить анализ новым eligibility-условием.
```

Целевая граница:

| Место | Разрешено | Запрещено |
|---|---|---|
| `LLM-2 admission gate` | решить `analyze / do_not_analyze`; исключить мусор, нет речи, IVR, internal, чистую техподдержку, непригодную STT | передавать коммерческий звонок в `LLM-2`, а потом отрезать его по длительности |
| `LLM-2A` | facts, scenes, evidence ledger, reactions, objections, agreements, deadlines, quality notes | ставить stop-condition, который запрещает `LLM-2B` scoring для уже допущенного звонка |
| `LLM-2B` | score applicable stages, gaps/strengths with scene/evidence refs | возвращать пустой `stage_scores=[]` из-за duration/eligibility после допуска |
| `LLM-2C` | проверить claims, proof, counter-evidence; reject/soften конкретные claims | отбрасывать весь звонок как не подлежащий анализу |
| `LLM-2D` | recommendations and universal evidence pack from proven/softened material | менять eligibility, скрывать звонок или усиливать rejected claims |

Правило по длительности:

```text
`CALLS_MIN_DURATION_SEC=180` остается source/intake/config порогом и может
оставаться контекстным сигналом качества, но не является жестким стопом для
коммерчески релевантного звонка, который уже допущен в LLM-2.
```

Если коммерческий звонок короткий, `LLM-2B` оценивает только применимые этапы:
старт контакта, проверка потребности/причины, отказ или возражение, следующий
шаг/договоренность. Неприменимые этапы не получают искусственные нули.

Acceptance для следующего controlled rerun:

- по каждому допущенному коммерчески релевантному звонку есть не пустой
  `score_by_stage`;
- `stage_scores=[]` после допуска считается retry/repair/diagnostic error;
- support/internal/no-speech/IVR/плохая STT остаются исключенными до `LLM-2`;
- `БАЛЛЫ ПО ЭТАПАМ` строятся по всем анализам с числовым `score_by_stage`, без
  дополнительного фильтра по длительности.

Контрольный результат `2026-06-01`:

- LLM2-only rerun по Толегену за `2026-05-19` выполнен на `24` ready STT:
  persisted LLM1 snapshot -> Codex `subagent_runtime` ->
  `LLM-2A/2B/2C/2D`.
- Инструкция: `codex_llm2_gate_v1_20260601`.
- Пакет:
  `/root/ai-sales-analyzer/core/review_packages/codex-llm2-only-tolegen-2026-05-19-2026-06-01`.
- Запрещенные части не запускались: source discovery, STT rebuild, fresh LLM-1,
  LLM-3, report build, Telegram/business delivery.
- Итог: `24/24` processed; `20` admitted and scored with non-empty
  `score_by_stage`; `4` rejected before LLM-2 as
  `llm2_admission_non_commercial_or_unusable`; admitted calls with empty
  `score_by_stage`: `0`; subagent artifacts: `80 input / 80 output`.

Что запускать для проверки:

```text
готовые STT 24 звонков Толегена за 2026-05-19
-> полный layered LLM-2 chain: LLM-2A -> LLM-2B -> LLM-2C -> LLM-2D
-> Report build
-> PDF preview в test/operator Telegram
```

Не запускать:

```text
STT rebuild
source discovery
full pipeline
business delivery менеджерам
изолированный LLM-2B как финальную проверку
```

Почему не достаточно одного `LLM-2B`:

- `LLM-2B` не имеет собственного источника фактов: он скорит только сцены и
  evidence ledger из свежего `LLM-2A`;
- новая проверяемая граница именно `LLM-2A -> LLM-2B`: `LLM-2A` не должен
  закрывать коммерческий звонок, а `LLM-2B` должен оценить применимые этапы;
- `LLM-2C` нужен для proof/counter-evidence по новым claims;
- `LLM-2D` нужен для финального `scores_detail`, recommendations,
  `report_evidence` и compatibility output, которые потребляет Report Layer.

## Где структура вредит

Структура вредит там, где она заставляет слой выполнять не свою работу.

Текущие вредные паттерны:

- `LLM-2` заполняет report-specific поля вместо анализа звонка;
- validators проверяют форму JSON, но недостаточно проверяют доказанность claim;
- legacy arrays проходят как будто это полноценный proof contract;
- registry/router берут кандидатов из нескольких конкурирующих источников;
- Report Layer старается заполнить блок даже при слабом материале;
- `LLM-3` получает много микрополей и пишет форму вместо смысла;
- renderer показывает таблицы, raw labels и обязательные секции так, будто
  доказательство уже есть.

Целевое поведение:

- hard gates остаются только там, где защищают факты, scope, status, deadline,
  stage, score, evidence и counter-evidence;
- форма, wording, row shape, length, optional scripts и compatibility fields
  переносятся в instructions, repair, downgrade или warning;
- отсутствие proof ведет к `insufficient`, soften, retry или reject, а не к
  уверенной manager-facing истории.

## Активный слой: LLM-2

Цель `LLM-2`:

```text
Сначала понять, что произошло в звонке.
Затем оценить по чеклисту.
Затем доказать или отклонить claim.
Только потом дать рекомендацию.
```

Целевой split:

| Pass | Роль | Output | Запрещено |
|---|---|---|---|
| `LLM-2A` | facts / scenes / evidence ledger | нейтральные сцены, цитаты, действия менеджера, реакции клиента, договоренности, сроки, возражения, service/refusal signals | оценивать, писать рекомендации, выбирать блок отчета |
| `LLM-2B` | scoring / gaps | оценки по чеклисту, сильные стороны, слабые места, preliminary claims со ссылками на `scene_id` / `evidence_id` | создавать claim без сцены, готовить report blocks |
| `LLM-2C` | claim proof check | `gap_proven`, `proof_type`, supporting evidence, counter-evidence, `claim_too_broad`, `needs_softening`, `reject_reason` | додумывать факты, писать новые рекомендации |
| `LLM-2D` | recommendations + universal evidence pack | рекомендации только по доказанным gaps, связь recommendation -> proof_card, финальный normalized analysis artifact | выбирать report section, усиливать weak/rejected claims |

Handoff-ready contract asset:

```text
core/app/agents/calls/prompts/llm2_pass_contracts.md
```

Этот файл фиксирует JSON contracts, input/output boundaries, запреты,
fail-closed поведение и mapping из `LLM-2A/2B/2C/2D` в текущий
`Analysis.scores_detail`. Он не подключен к runtime сам по себе: активный
production prompt остается `analyze.md` до отдельного изменения analyzer runner.

Почему порядок именно такой:

```text
сначала факты -> потом оценка
```

Оценка до фактов создает риск, что чеклист начнет диктовать реальность. Модель
может сначала решить, что слабый этап - "следующий шаг", а потом подобрать под
это фрагменты. Нам нужен обратный порядок: сцены ограничивают вывод.

Чеклист можно использовать в `LLM-2A` только как рамку наблюдения:

```text
выдели сцены, релевантные этапам чеклиста, но не оценивай их
```

## Инструкции LLM-2

Активный `analyze.md` перегружен и должен быть разложен на порционные задачи.

Целевая структура инструкций:

```text
analyze_facts_scenes
analyze_scoring_gaps
analyze_claim_proof
analyze_recommendations
```

Инструкция `analyze_facts_scenes`:

- зафиксировать, что произошло;
- выделить сцены и цитаты;
- отметить действия менеджера и реакции клиента;
- отметить договоренности, сроки, отказ, перенос, service issue;
- не оценивать и не рекомендовать.

Инструкция `analyze_scoring_gaps`:

- оценить сцены по чеклисту;
- связать каждый gap с `scene_id` / `evidence_id`;
- не создавать gap без конкретной сцены;
- не выбирать блок отчета.

Инструкция `analyze_claim_proof`:

- проверить каждый claim;
- отметить supporting evidence;
- отметить counter-evidence;
- определить, не слишком ли claim широкий;
- вернуть `gap_proven=false`, если доказательство слабое.

Инструкция `analyze_recommendations`:

- дать рекомендации только по доказанным gaps;
- связать каждую рекомендацию с `proof_card`;
- не создавать новые claims;
- собрать final universal evidence pack.

Главное правило инструкций:

```text
Нет evidence -> нет gap.
Нет доказанного gap -> нет рекомендации.
Нет конкретного момента разговора -> нет уверенного coaching claim.
```

## Proof card

Единый `proof_card` должен стать source of truth для downstream.

Минимальный контракт:

```json
{
  "proof_id": "proof_001",
  "call_id": "...",
  "stage_code": "...",
  "claim": "...",
  "claim_scope": "scene|call|day",
  "claim_type": "manager_gap|customer_signal|follow_up|business_outcome|strong_practice",
  "scene_id": "scene_001",
  "evidence_ids": ["ev_001"],
  "evidence_quote": "...",
  "proof_type": "direct_quote|sequence_inference|absence_based",
  "gap_proven": true,
  "counter_evidence": [],
  "needs_softening": false,
  "reject_reason": null,
  "recommendation_id": "rec_001"
}
```

Правила:

- `proof_card` не является report block;
- `proof_card` не выбирает `СИТУАЦИЮ ДНЯ`, `РАЗБОР ЗВОНКА` или другой блок;
- один claim может быть показан в отчете только если есть допустимый
  `proof_card`;
- `claim_scope=day` требует более сильного evidence, чем `claim_scope=scene`;
- absence-based proof допустим только если понятно, какой ожидаемый элемент
  отсутствует и почему это видно из последовательности разговора.

## Что убрать из активной роли LLM-2

`LLM-2` не должен быть report-template engine.

Следующие поля не должны быть активным источником manager-facing truth:

```text
report_evidence.block_candidates
report_evidence.semantic_case.report_block_fit
report_evidence.situation_candidates
report_evidence.manager_coaching_moments
report_evidence.additional_situations
report_evidence.voice_of_customer
report_evidence.follow_up_candidates
report_evidence.quote_bank
```

Целевой статус этих полей:

- `legacy-compatible`;
- `derived view`;
- или `deprecated`.

Они могут временно существовать для совместимости, но downstream должен
доверять normalized proof pool, а не этим полям напрямую.

## Validators / normalizers

Целевая роль:

```text
проверить, можно ли пропустить заявленную LLM-2 связку
claim -> evidence -> counter-evidence
```

Validators не должны заново анализировать весь звонок как LLM. Они проверяют
контракт, противоречия и обязательные условия.

Обязательные проверки:

- `scene_id` существует;
- `evidence_quote` присутствует в transcript/context;
- `gap_proven=true` не конфликтует с `counter_evidence`;
- `proof_type` соответствует claim;
- claim не шире evidence;
- recommendation ссылается на доказанный gap;
- legacy candidate без `proof_card` не проходит как verified source;
- `claim_scope=day` не ставится на evidence уровня одной сцены без сильного
  основания.

Возможные решения validator:

| Ситуация | Решение |
|---|---|
| нет quote/context | reject |
| quote не из transcript/context | reject |
| proof fields неполные | retry `LLM-2` или reject |
| claim слишком широкий | soften/downgrade |
| есть counter-evidence | reject или soften |
| form/compatibility issue | repair/warning |

Остановленные задачи, относящиеся к этому слою:

- недоказанный claim про следующий шаг;
- слабые или orphan recommendations;
- problem block без `gap_proven=true`;
- counter-evidence, которое ломает уверенный coaching claim.

## Registry / router

Целевая роль:

```text
собрать normalized proof pool и выбрать только доказанный материал
для downstream-блоков
```

Задачи:

- строить pool из `proof_card`;
- сохранять provenance: call, scene, source artifact, stage, score, evidence,
  proof status;
- использовать legacy fields только как hints;
- не повышать legacy candidates до verified source;
- не создавать новый смысл.

Остановленные задачи, относящиеся к этому слою:

- `Situation Day` не должен выбирать candidate без доказанного gap;
- `Call Breakdown` не должен наследовать слабую `Ситуацию дня`;
- `Additional Situation` не должен дублировать тот же claim/call без нового
  смысла;
- `Voice of Customer` должен брать customer-signal evidence, а не manager-gap
  route.

## Report Layer

Целевая роль:

- выбрать дневной фокус;
- выбрать bounded candidate pool;
- применить hard gates;
- не заменять `LLM-2` анализ.

Hard gates:

```text
call_id
report-day scope
facts
status
deadline
stage
score
evidence
counter-evidence
```

Уже сделано:

- Block 1 принят пользователем;
- введен `final_manager_status`;
- follow-up block переименован в `КОНТАКТЫ В РАБОТУ`;
- status conflicts стали warning.

Остановленные задачи, относящиеся к этому слою:

- Block 2 focus binding для `СИТУАЦИИ ДНЯ`;
- выбор `same_call` vs `best_evidence_by_stage` для `РАЗБОРА ЗВОНКА`;
- скрытие пустого `РАЗБОР ЗВОНКА`;
- скрытие или объединение пустых/повторяющихся блоков.

Эти задачи возвращаются только после того, как Report Layer получает доказанный
proof pool.

## LLM-3

Целевая роль:

- получить bounded facts/proof cards;
- оформить manager-facing narrative;
- сохранить факты неизменными;
- вернуть `insufficient`, если selected proof слабый.

`LLM-3` не может менять:

```text
call_id
client
date
status
deadline
stage
score
quote
claim
proof status
```

Остановленные задачи, относящиеся к этому слою:

- убрать микрополя, которые заставляют писать форму вместо смысла;
- сделать `СИТУАЦИЮ ДНЯ` mini-brief;
- сделать `РАЗБОР ЗВОНКА` narrative по доказанным turning points;
- оформить `ГОЛОС КЛИЕНТА` как клиентский сигнал, а не поиск ошибки менеджера.

## Renderer / PDF / Telegram

Целевая роль:

- показать утвержденный payload;
- убрать raw/debug labels;
- не менять смысл.

Остановленные задачи, относящиеся к этому слою:

- cleanup `Сторона 1/2`, `Контекст`, `document_type`, technical prefixes;
- не показывать пустой `РАЗБОР ЗВОНКА` как полноценный блок;
- не маскировать слабое доказательство строгой таблицей;
- показывать `insufficient` там, где доказательство слабое.

## LLM-1

Целевая роль:

- классификация;
- краткая карточка звонка;
- eligibility/routing;
- reason/audit codes.

Почему последним:

```text
Пока не ясно, какой минимальный материал нужен LLM-2 для качественного proof,
нельзя безопасно отсекать звонки или выносить признаки выше по цепочке.
```

`LLM-1` не должен:

- делать глубокий coaching analysis;
- писать recommendations;
- готовить report evidence;
- выбирать блоки отчета.

## Рабочий порядок

1. `LLM-2`: спроектировать pass contracts `2A/2B/2C/2D`.
2. `LLM-2`: разложить активные инструкции.
3. `LLM-2`: ввести `proof_card` / universal evidence pack.
4. Validators: подключить proof validation как admission gate.
5. Registry/router: перевести selection на normalized proof pool.
6. Report Layer / `LLM-3`: вернуть остановленные Block 2/3/4 задачи поверх
   доказанного материала.
7. Renderer: дочистить форму без изменения смысла.
8. `LLM-1`: закрепить classification/card/eligibility последним.

## Task cards for handoff

Этот раздел переводит решения выше в конкретные задачи для следующего ИИ или
implementation agent. Если агент продолжает работу, он должен брать задачу из
этого раздела, а не интерпретировать архитектурный текст свободно.

### T1. Спроектировать контракты LLM-2A / 2B / 2C / 2D

Handoff status `2026-05-27`: baseline contract staged in:

```text
core/app/agents/calls/prompts/llm2_pass_contracts.md
```

Что делаем:

- описать JSON contracts для четырех pass-ов `LLM-2`;
- определить обязательные поля, optional fields и reject reasons;
- зафиксировать, какие данные каждый pass получает на вход и отдает дальше;
- сохранить backward compatibility с текущим final `Analysis.scores_detail`.

Где смотреть и менять:

```text
core/app/agents/calls/analyzer.py
core/app/agents/calls/prompts/analyze.md
core/app/agents/calls/prompts/analyze_v17_universal_evidence.md
docs/TMP_LLM_NODES_ARTIFACTS_MAP.md
docs/LLM_SUBAGENT_TESTING_MODE.md
```

Результат:

- в документе или prompt assets есть явный contract для `LLM-2A`, `LLM-2B`,
  `LLM-2C`, `LLM-2D`;
- понятно, как из pass artifacts собирается final normalized analysis.

Проверка:

- можно прочитать contract без знания истории чата;
- каждый pass имеет вход, выход, запреты и fail-closed поведение.

Не трогать:

- business delivery;
- scheduler;
- UI;
- `LLM-1` production role.

### T2. Разложить инструкции LLM-2 на порционные задачи

Handoff status `2026-05-27`: prompt split assets are staged and handoff-ready.
They are not wired into analyzer runtime by this task.

```text
core/app/agents/calls/prompts/llm2_pass_contracts.md
core/app/agents/calls/prompts/analyze_facts_scenes.md
core/app/agents/calls/prompts/analyze_scoring_gaps.md
core/app/agents/calls/prompts/analyze_claim_proof.md
core/app/agents/calls/prompts/analyze_recommendations.md
```

Текущий `analyze.md` остается monolithic runtime prompt. Простое добавление
файлов не меняет поведение analyzer; отдельная runtime-задача должна явно
подключить эти prompt assets через runner.

Что делаем:

- вынести из перегруженного `analyze.md` отдельные instruction blocks:
  `facts/scenes`, `scoring/gaps`, `claim_proof`, `recommendations`;
- убрать из активной инструкции обязанность готовить report blocks;
- оставить checklist как рамку оценки, но не как источник заранее выбранного
  claim;
- добавить правило: evidence сначала, recommendation потом.

Где смотреть и менять:

```text
core/app/agents/calls/prompts/analyze.md
core/app/agents/calls/prompts/analyze_v17_universal_evidence.md
core/app/agents/calls/prompts/agreements.md
core/app/agents/calls/prompts/insights.md
docs/mvp1_sources/MVP1_CALL_ANALYSIS_CONTRACT_v1.md
docs/mvp1_sources/MVP1_CHECKLIST_DEFINITION_v1.md
```

Результат:

- `LLM-2` инструкция не просит одновременно анализировать, оценивать,
  доказывать, рекомендовать и готовить отчетные блоки;
- report-specific routing явно исключен из основной задачи `LLM-2`.

Проверка:

- prompt review: нет инструкций вида "выбери блок отчета";
- LLM-node simulation artifact показывает отдельные facts/scenes, gaps,
  proof и recommendations.

Не трогать:

- layout отчета;
- названия отчетных блоков;
- Report Layer selection до появления proof pool.

### T3. Ввести `proof_card` / universal evidence contract

Handoff status `2026-05-27`: implemented for analysis-layer admission in:

```text
core/app/agents/calls/report_evidence.py
core/app/agents/calls/llm2_layered_analysis.py
core/tests/test_report_evidence_proof_card_validation.py
core/tests/test_llm2_layered_analysis.py
```

Current control result: `9/9` Tolеген control calls passed
`validate_report_evidence`; proof-card status split in Registry:
`verified=9`, `unverified/softened/downgraded=13`, `rejected=3`.

Что делаем:

- добавить единый объект `proof_card` для связи
  `claim -> scene/evidence -> counter-evidence -> recommendation`;
- определить enums для `proof_type`, `claim_scope`, proof status и reject
  reasons;
- связать `proof_card` с `stage_code`, `scene_id`, `evidence_id`,
  `recommendation_id`;
- сделать `proof_card` источником truth для downstream.

Где смотреть и менять:

```text
core/app/agents/calls/report_evidence.py
core/app/agents/calls/analyzer.py
core/app/agents/calls/report_evidence_registry.py
core/app/agents/calls/prompts/analyze.md
core/app/agents/calls/prompts/analyze_v17_universal_evidence.md
core/tests/test_report_evidence_registry.py
```

Результат:

- final `LLM-2` artifact содержит proof cards или normalized equivalent;
- каждый сильный coaching claim имеет proof source;
- recommendations ссылаются на доказанные gaps.

Проверка:

- test: claim без `proof_card` не становится verified;
- test: recommendation без доказанного gap отклоняется;
- test: counter-evidence переводит proof в reject/soften.

Не трогать:

- renderer wording;
- Telegram/PDF delivery;
- legacy fields как физические поля, если они нужны для compatibility.

### T4. Перевести legacy report-specific поля LLM-2 в compatibility

Handoff status `2026-05-27`: partially implemented in Registry/Router. Legacy
fields without `proof_card` are now diagnostics/hints and do not route into
verified manager-facing problem blocks. Existing legacy arrays are still kept
for compatibility and old persisted analyses.

Что делаем:

- определить текущие поля `report_evidence.block_candidates`,
  `semantic_case.report_block_fit`, `situation_candidates`,
  `manager_coaching_moments`, `additional_situations`, `voice_of_customer`,
  `follow_up_candidates`, `quote_bank` как legacy/derived/deprecated;
- запретить downstream считать их verified source без `proof_card`;
- оставить временный adapter, если без него ломается текущий отчет.

Где смотреть и менять:

```text
core/app/agents/calls/analyzer.py
core/app/agents/calls/report_evidence_registry.py
core/app/agents/calls/report_block_router.py
core/app/agents/calls/reporting.py
core/tests/test_report_evidence_registry.py
```

Результат:

- legacy arrays не исчезают резко, но теряют статус source of truth;
- registry/router строят основной pool из proof contract.

Проверка:

- test: legacy candidate без proof не попадает в verified problem block;
- existing report smoke не падает из-за отсутствия старого поля.

Не трогать:

- старые persisted analyses в базе;
- исторические artifacts;
- Block 2/3/4 wording до завершения proof pool.

### T5. Усилить validators / normalizers как admission gate

Handoff status `2026-05-27`: implemented for layered LLM-2 artifacts. The
normalizer maps stage aliases to approved checklist codes and fail-closes
invalid proof outcomes: counter-evidence cannot remain `proven`, and thin
sequence inference becomes `retry` instead of a manager-facing claim.

Что делаем:

- подключить proof validation к fresh `LLM-2` outputs;
- проверять наличие scene/evidence, quote grounding, counter-evidence,
  claim scope и recommendation linkage;
- разделить outcomes: `reject`, `retry`, `soften`, `downgrade`, `warning`;
- не превращать validator во второй LLM-анализ.

Где смотреть и менять:

```text
core/app/agents/calls/report_evidence.py
core/app/agents/calls/analyzer.py
core/app/agents/calls/reporting.py
core/tests/test_manual_reporting.py
core/tests/test_report_evidence_registry.py
```

Результат:

- слабый claim не проходит дальше как verified;
- недоказанный "следующий шаг не закреплен" становится reject/soften/retry,
  а не уверенным coaching claim.

Проверка:

- test: quote not in transcript -> reject;
- test: claim broader than evidence -> soften/downgrade;
- test: `gap_proven=true` + counter-evidence -> reject;
- test: form-only issue -> warning/repair, not semantic reject.

Не трогать:

- LLM-3 prompts;
- renderer;
- business delivery.

### T6. Перевести registry/router на normalized proof pool

Handoff status `2026-05-27`: implemented for top-level
`report_evidence.proof_cards`. Control runner routes only validated proof
material: aggregate routes across 9 calls are `situation_day=4`,
`call_breakdown=4`, `voice_of_customer=5`, `follow_up=11`,
`additional_situations=1`, `challenge=4`.

Что делаем:

- собирать candidate pool из validated proof cards;
- сохранять provenance для каждого candidate;
- использовать legacy fields только как hints;
- выбирать material для блоков только из доказанного pool.

Где смотреть и менять:

```text
core/app/agents/calls/report_evidence_registry.py
core/app/agents/calls/report_block_router.py
core/app/agents/calls/situation_day_daily_input.py
core/app/agents/calls/reporting.py
core/tests/test_report_evidence_registry.py
core/tests/test_report_block_router.py
```

Результат:

- `Situation Day`, `Call Breakdown`, `Additional Situation`,
  `Voice of Customer` получают только candidates с proof status;
- source path каждого candidate объясним в diagnostics.

Проверка:

- test: candidate вне report-day scope не проходит;
- test: candidate без proof не проходит в manager-gap block;
- test: router reason codes объясняют reject/accept.

Не трогать:

- narrative wording;
- DOCX/PDF templates;
- `LLM-1`.

### T7. Вернуть Report Layer задачи поверх proof pool

Handoff status `2026-05-27`: blocked until runtime `LLM-2` production path is
closed. Existing proof-pool control runner results are sufficient for
analysis-layer design validation, but not yet sufficient to restart Report
Layer/PDF/Telegram work.

Что делаем:

- выбирать дневной фокус из score/gaps/proof pool;
- применять hard gates по facts/scope/status/deadline/stage/score/evidence;
- вернуть Block 2/3/4 только после появления verified proof pool;
- слабый материал переводить в `insufficient`, hide или softer wording.

Где смотреть и менять:

```text
core/app/agents/calls/reporting.py
core/app/agents/calls/situation_day_daily_input.py
core/app/agents/calls/situation_day_daily_composer.py
core/app/agents/calls/call_breakdown_composer.py
core/app/agents/calls/voice_of_customer_composer.py
core/tests/test_manual_reporting.py
core/tests/test_situation_day_daily_input.py
core/tests/test_situation_day_daily_composer.py
```

Результат:

- `СИТУАЦИЯ ДНЯ` не выбирается без доказанного gap;
- `РАЗБОР ЗВОНКА` не наследует слабую ситуацию;
- пустые/повторяющиеся блоки скрываются или объединяются.

Проверка:

- rerender контрольных дат `2026-05-18`, `2026-05-19`, `2026-05-20`;
- diagnostics показывают selected proof и reject reasons.

Не трогать:

- proof contract без отдельного решения;
- `LLM-2` prompts во время report-layer pass.

### T8. Ограничить LLM-3 ролью narrative composer

Что делаем:

- передавать `LLM-3` только bounded facts/proof cards;
- убрать prompt-давление на микрополя, если они заставляют писать форму вместо
  смысла;
- запретить изменение facts, status, deadline, stage, score, quote, claim,
  proof status;
- возвращать `insufficient`, если proof слабый.

Где смотреть и менять:

```text
core/app/agents/calls/prompts/situation_day_daily_composer_v2.md
core/app/agents/calls/prompts/call_breakdown_composer_v2.md
core/app/agents/calls/prompts/voice_of_customer_composer_v2.md
core/app/agents/calls/situation_day_daily_composer.py
core/app/agents/calls/call_breakdown_composer.py
core/app/agents/calls/voice_of_customer_composer.py
core/tests/test_situation_day_daily_composer.py
core/tests/test_call_breakdown_composer.py
core/tests/test_voice_of_customer_composer.py
```

Результат:

- `LLM-3` оформляет выбранный материал, но не переанализирует звонок;
- weak proof не становится сильным manager-facing claim.

Проверка:

- test: `LLM-3` output с измененным claim/status/stage отклоняется;
- test: weak proof -> `insufficient`;
- LLM-node simulation artifacts сохраняют input/output.

Не трогать:

- selection logic;
- validators;
- delivery.

### T9. Дочистить renderer без изменения смысла

Что делаем:

- убрать raw/debug labels из видимого текста;
- не показывать empty block как полноценный смысловой блок;
- показывать insufficient/softened output честно;
- не менять claims, quotes, statuses или deadlines.

Где смотреть и менять:

```text
core/app/agents/calls/report_templates.py
core/app/agents/calls/reporting.py
scripts/generate_docx_report.js
core/app/agents/calls/report_template_assets/manager_daily/manager_daily_template_v2/semantic.json
core/tests/test_manual_reporting.py
tests/test_manual_reporting.py
```

Результат:

- в PDF/Telegram нет `Контекст`, `document_type`, технических markers;
- пустой `РАЗБОР ЗВОНКА` не выглядит как сломанный блок;
- renderer не усиливает weak claim.

Проверка:

- text preview scan по контрольным отчетам;
- `node --check scripts/generate_docx_report.js`;
- targeted render tests.

Не трогать:

- analysis/proof logic;
- LLM prompts.

### T10. Закрепить LLM-1 последним

Что делаем:

- после стабилизации `LLM-2` определить минимальный contract `LLM-1`;
- закрепить classification, short call card, eligibility/routing,
  reason/audit codes;
- не переносить туда deep analysis или proof.

Где смотреть и менять:

```text
core/app/agents/calls/prompts/classify.md
core/app/agents/calls/analyzer.py
core/app/agents/calls/llm_simulation.py
core/tests/test_ai_provider_routing.py
tests/test_ai_provider_routing.py
```

Результат:

- `LLM-1` помогает дешевле и понятнее маршрутизировать звонки;
- `LLM-2` не теряет нужный материал из-за преждевременного отсечения.

Проверка:

- test: rejected call has reason/audit code;
- test: eligible call still reaches `LLM-2`;
- LLM-node simulation agent for `LLM-1` separate from implementation agent.

Не трогать:

- `LLM-1` до завершения `LLM-2` proof model;
- report blocks.

## Acceptance criteria

Analysis layer считается готовым к переходу в Report Layer только если:

- [x] runtime `LLM-2` production path реально использует layered pass artifacts или
  эквивалентный production adapter, а не только staged prompt files;
- [x] bounded control run по 9 звонкам Толегена завершен через этот
  runtime path без STT, без `LLM-1`, без Report Layer preview/PDF/Telegram;
- [x] каждый сильный coaching claim имеет `proof_card`;
- [x] каждый `proof_card` ссылается на конкретный `scene_id` / `evidence_id`;
- [x] recommendation создается только для доказанного gap;
- [x] counter-evidence не игнорируется;
- [x] legacy candidate без proof не попадает в verified report block;
- [x] validators/registry/router показывают fail-closed behavior для
  weak/rejected/legacy-only claims;
- [x] по контрольным датам `2026-05-18`, `2026-05-19`, `2026-05-20` сохранены
  intermediate runtime artifacts и concise control summary;
- [x] явно зафиксированы residual risks, если они не входят в текущий scope
  (`STT/role attribution`, `LLM-1`, Report Layer wording/rendering).

Только после этого можно начинать Report Layer handoff:

- `LLM-3` получает только bounded proof material;
- отчет не показывает уверенный claim без доказательства;
- PDF/Telegram preview разрешены только как operator/test preview после
  отдельного Report Layer шага;
- business Telegram/email delivery остается выключенной до отдельного approval.

Минимальная цепочка проверки:

```text
transcript
-> LLM-2A facts/scenes
-> LLM-2B scoring/gaps
-> LLM-2C proof cards
-> LLM-2D recommendations/evidence pack
-> validators
-> registry/router
-> runtime artifact summary
```

## Что больше не является активным содержанием этого документа

Этот файл не хранит:

- подробный журнал всех Gate 5 preview;
- длинные block-by-block планы старой фазы;
- повторяющиеся списки acceptance criteria;
- исторические Telegram/PDF artifacts;
- подробный Report Layer / `LLM-3` audit.

Эти сведения остаются в:

```text
docs/PROGRESS.md
docs/GATE5_AUTONOMOUS_EXECUTION_STATUS.md
docs/REPORT_LAYER_LLM3_STRUCTURE_AUDIT_2026-05-27.md
docs/LLM2_CLAIM_EVIDENCE_FIT_AUDIT_2026-05-27.md
```

## Report Layer Handoff Update: Block 3

Дата обновления: `2026-05-27`

Связанный слой: Report Layer / `LLM-3`, но решение опирается на LLM-2 proof
model.

Решение:

- `ГОЛОС КЛИЕНТА` теперь принимает только bounded proof-backed customer/service
  signal material;
- legacy/report_evidence hints без verified `proof_card` / `proof_refs` не
  должны становиться финальными сигналами;
- `LLM-3` получает `proof_refs` + `locked_fields`, а Report Layer
  восстанавливает identity/proof fields из source signal;
- `dialogue_evidence` считается доказательством только если текст поддержан
  source `quote_context`;
- renderer обязан скрывать technical `Контекст:` и показывать неясную диалоговую
  атрибуцию как `Сторона 1` / `Сторона 2`.

Что это значит для LLM-2:

- целевое направление остается прежним: LLM-2 должен отдавать structured
  proof cards / dialogue scenes, а не report-ready prose;
- чем больше LLM-2C/2D будут отдавать `dialogue_scene` turns с speaker/side и
  proof ids, тем меньше Report Layer будет вынужден repair-ить старые строковые
  контексты;
- это не отменяет fail-closed rule: если customer signal не доказан, блок лучше
  скрыть/пометить insufficient, чем писать уверенную интерпретацию.

## Next Full-Day Test Pre-Backlog

Дата обновления: `2026-05-28`

Связанный этап: один свежий full-day test на одном менеджере через готовые STT
и Codex-subagent runtime.

Решение после no-validator прогона:

- semantic/evidence validators не должны блокировать следующий тестовый отчет;
- validators/normalizers на next test работают как repair/normalization и
  diagnostics/warnings слой;
- свежий тест должен заново вызвать Codex-subagent LLM roles, а не только
  rehydrate уже сохраненные artifacts;
- весь manager-facing output должен быть на русском языке;
- PDF доставляется только в test/operator Telegram.

Целевая цепочка next test:

```text
ready STT
-> Codex subagent LLM-2A facts/scenes
-> Codex subagent LLM-2B scoring/gaps
-> Codex subagent LLM-2C claim/proof diagnostics
-> Codex subagent LLM-2D recommendations/evidence pack
-> diagnostics-only normalizers
-> registry/router
-> Report Layer selection
-> LLM-3 Russian narrative
-> renderer / PDF / test Telegram
```

### Full-day Codex-subagent test result

Status: `completed_waiting_for_user_review`.

Run scope:

```text
manager: Толеген Жангазиев
date: 2026-05-19
mode: fresh full-day run
input: ready STT
LLM roles: real Codex subagents via codex exec
delivery: test/operator Telegram only
run_id: codex-full-day-tolegen-2026-05-19-2026-05-28-precise24-ru
```

User-facing acceptance check:

```text
1. PDF не пустой.
2. Manager-facing текст на русском.
3. Виден полный день и coverage.
4. Понятно, какие звонки разобраны глубоко, а какие перечислены в дневном списке.
5. Нет уверенных выводов без доступного материала.
```

Result summary:

- selected calls: `24`;
- transcripts: `24 reused`, `0 built`;
- analyses: `24 built`, `0 reused`;
- readiness: `full_report_ready`;
- ready analyses: `24/24`;
- analysis coverage: `100.0`;
- final PDF scan: `passed=true`;
- Telegram delivery: `sent`, test/operator target `74665909`,
  message id `342`;
- completion ping: `sent`, message id `343`;
- business delivery: `not_run`.

Human review `2026-05-28`:

- `Ситуация дня` accepted: user explicitly noted that the situation capture is
  high-quality and meaningful.
- `Разбор звонка` accepted: user explicitly noted that the call breakdown
  transmits the meaning of the call well.
- New quality gap: `Все звонки дня` has weak context on rows with agreements.
  The row context should briefly communicate the real essence produced by
  LLM-2: refusal reason, topic, agreement, next step, presentation/callback
  context.
- `Контакты в работу` carries stronger context than the full call list.
  Candidate product direction: merge the two blocks into one daily table, or
  use one shared call-essence source for both blocks.

Subagent evidence:

```text
input_files=123
output_files=123
LLM-1 classification first pass: 24
LLM-2A facts/scenes: 24
LLM-2B scoring/gaps: 24
LLM-2C claim/proof: 24
LLM-2D recommendations: 24
LLM-3 situation/call-tomorrow/call-breakdown composers: 3
```

Layer statuses:

#### Validators / normalizers

Status: `completed_for_test`.

- Blocking semantic/evidence validators отключены для report admission:
  `AI_LLM2_REPORT_EVIDENCE_VALIDATION_ENABLED=false`,
  `AI_LLM2_SEMANTIC_VALIDATION_ENABLED=false`.
- Schema/shape repair, enum/stage normalization, DB-safe truncation и
  diagnostics сохранены.

#### LLM-2 / subagent runtime

Status: `completed_for_test`.

- `LLM-2A/2B/2C/2D` выполнены для всех `24` звонков.
- Runtime mode подтвержден как `subagent_runtime`, simulation mode выключен.
- Per-request artifacts сохранены в run package.

#### Registry / router

Status: `completed_for_test`.

- Router работал в diagnostics-only/no-hard-proof режиме.
- Usable report pool собран без старого hard proof gate.
- Readiness итог: `full_report_ready`.

#### Report Layer / selection

Status: `needs_post_review_iteration`.

- Coverage funnel собран: `relevant_calls=24`, `ready_analyses=24`.
- Готовы основные blocks: `day_summary`, `review`, `key_problem`,
  `recommendations`.
- Payload сохранен как `payload.json`; локализованная версия финального
  рендера сохранена как `payload_ru_fixed.json`.
- Accepted as good for primary narrative blocks, but call-list context needs a
  post-review pass.
- For `Все звонки дня`, rows with agreements must show the topic and concrete
  agreement, not only a weak generic context.
- `Контакты в работу` and `Все звонки дня` should either be merged or read from
  the same call-essence source.

#### LLM-3 / narrative

Status: `completed_for_test`.

- Сформированы `3` LLM-3 outputs:
  `situation_day`, `call_tomorrow_wording`, `call_breakdown`.
- Output status по LLM-3 artifacts: `verified`.

#### Renderer / PDF / Telegram

Status: `completed_with_followup_bug`.

- Первичный PDF scan остановил отправку из-за английских labels
  `verified / strong`.
- Финальный PDF был перерендерен с русскими labels и успешно прошел scan.
- PDF отправлен только в test/operator Telegram:
  `Ежедневный отчет - Толеген Жангазиев - 19 мая 2026 - RU.pdf`.

#### Observability / verification

Status: `completed_for_test`.

- Run package:
  `core/review_packages/codex-full-day-tolegen-2026-05-19-2026-05-28-precise24-ru/`.
- Key files:
  `summary.json`, `prepare_summary.json`, `payload.json`,
  `payload_ru_fixed.json`, `subagent_artifact_counts_corrected.json`,
  `report_text_scan_ru_fixed.json`, `delivery_result_ru_fixed.json`,
  `completion_telegram_ping.json`.
- Background `codex exec` processes checked after run: none left running.

Known follow-up before next production-grade run:

```text
1. Improve call-list context: each row should show short LLM-2 call essence,
   including topic, refusal reason, agreement, and next step when present.
2. Decide and implement the relation between `Контакты в работу` and
   `Все звонки дня`: merged table or shared source model.
3. Move evidence label localization into report_templates.py so renderer never
   prints raw labels like verified/strong.
4. Move English scan to visible report text, not raw HTML/CSS.
5. Fix subagent artifact counter to count *_output.json artifacts.
```

Post-review task list by layer:

Execution order:

```text
1. LLM-2 / call essence
2. Report Layer / Все звонки дня
3. Report Layer / Контакты в работу
4. Renderer / PDF table shape
5. Validators / normalizers diagnostics
6. Registry / router source consistency
7. LLM-3 wording guardrail, only if needed
8. Observability / regression
9. Controlled rerun after user approval
```

#### LLM-1

Status: `later_not_before_next_report_pass`.

- Do not change before the current report-quality pass is closed.
- Current user gap is not STT, speaker role, or name attribution.
- Later scope: speaker confidence, role attribution, and source-of-truth for
  names/roles.

#### LLM-2 / call essence

Status: `pending`.

- Ensure every call has a concise manager-facing essence field.
- The essence must cover: topic, outcome, refusal/interest reason, agreement,
  and next step when present.
- Inspect and align existing fields:
  `call_report_summary.manager_visible_summary`, `short_context`,
  `business_outcome`, and follow-up fields.
- Acceptance examples:
  `отказался, потому что нет потребности`;
  `договорились созвониться на презентацию`;
  `тема - документы/подписание`.
- Do not regress the accepted `Ситуация дня` and `Разбор звонка`.

#### Validators / normalizers

Status: `small_followup`.

- Do not re-enable blocking semantic/evidence validators.
- Add diagnostics/soft normalization for new call essence quality:
  empty value, technical wording, English wording, and generic low-information
  context.
- Diagnostics should warn and explain; they should not block the business
  report.

#### Registry / router

Status: `small_followup_for_call_list_source`.

- Do not restore old hard proof gate.
- Check whether `call_list_context` / `call_essence` needs a routed source or a
  normalized report-layer source.
- Ensure `Все звонки дня` and `Контакты в работу` do not use inconsistent
  context for the same call.

#### Report Layer / Все звонки дня

Status: `pending_main_focus`.

- Prefer LLM-2 call essence / follow-up essence over weak fallback context.
- Agreement rows must include what was agreed, on what topic, and the next step.
- Refusal rows must include a short reason.
- Service/technical rows must include the actual issue or request.
- Remove weak generic contexts from the visible table.

#### Report Layer / Контакты в работу

Status: `pending_decision`.

- Decide whether to merge with `Все звонки дня`.
- Preferred direction after review: one daily table with columns like
  `Статус`, `В работу`, `Когда`, `Суть звонка / договоренность`.
- If not merged, both blocks must read from the same call-essence source so one
  block cannot have good context while the other has weak context.

#### LLM-3

Status: `mostly_accepted_guardrail_only`.

- Keep accepted `Ситуация дня` and `Разбор звонка` unchanged.
- If LLM-3 is used for call-list/contact wording, it must not change status,
  date, topic, agreement, next step, or LLM-2 meaning.
- Its role in this pass is only Russian compression/wording, if needed.

#### Renderer / PDF

Status: `pending`.

- Support revised table shape without bloating the PDF.
- If blocks are merged, keep the table readable and compact.
- Move evidence label localization into `report_templates.py` so renderer never
  prints raw labels like `verified/strong`.
- Move English scan to visible report text, not raw HTML/CSS.

#### Observability / regression

Status: `pending`.

- Add per-row diagnostics for daily table context: selected source, source
  priority, and rejection reason for weaker candidates.
- Add regression cases for refusal with reason, presentation agreement,
  callback/reschedule, and service/technical call.
- Fix subagent artifact counter to count `*_output.json` artifacts.
- Run a controlled rerun only after explicit user approval.

Current gate:

```text
НУЖНО ВАШЕ УТВЕРЖДЕНИЕ

Human review получен. Primary narrative blocks accepted. Next work is the
post-review call-list / contacts-in-work context pass. Новый full-day прогон не
запускать до реализации этих задач.
```

Out of scope до выполнения post-review pass:

- повторный прогон;
- business Telegram/email delivery;
- STT quality и role attribution;
- production redesign `LLM-1`;
- UI/scheduler expansion.
