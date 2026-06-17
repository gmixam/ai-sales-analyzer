# PILOT-32: лучший учебный кейс по фокусному этапу для `СИТУАЦИЯ ДНЯ` и `РАЗБОР ЗВОНКА`

Дата: 2026-06-16
Статус: implemented_first_pass_llm_ownership
Связанные задачи: `PILOT-31`, `PILOT-19`, `Report Layer`, `LLM3 situation/call breakdown`

## Контекст

После внедрения `PILOT-31` фокусный этап в `БАЛЛЫ ПО ЭТАПАМ` выбирается по
weighted impact, а не по первому низкому этапу.

На контрольном отчете Толегена за `2026-06-15` получилось:

- фокусный этап: `Э3 Выявление детальных потребностей`;
- `СИТУАЦИЯ ДНЯ` не была надежно подтверждена:
  `situation_day_quote_not_grounded_in_transcript`;
- `РАЗБОР ЗВОНКА` подтянулся по другому этапу: `Э8 Продажа: финал`;
- в диагностике уже был warning:
  `call_breakdown_stage_mismatch:sale_final`.
- формат `СИТУАЦИИ ДНЯ` отличался от отчетов других менеджеров: вместо
  привычного табличного блока появились текстовые подразделы `Фокусный этап`,
  `Пример из сегодня`, `Что произошло`, `Почему это важно`, `Что делать`,
  `Как сказать`.

Это путает менеджера: отчет показывает один фокус дня, но глубокий разбор
строится по другому смысловому этапу. Дополнительно один и тот же блок
рендерится в разных форматах, хотя тип отчета один.

## Принятое решение

Главное архитектурное правило: **смысл формирует только LLM**.

Report Layer не должен сам выбирать “лучший смысловой кейс”, достраивать
`СИТУАЦИЮ ДНЯ`, объяснять проблему менеджера или формировать содержательный
`РАЗБОР ЗВОНКА` из `gaps`, score rows, transcript text или deterministic
эвристик.

Report Layer может только:

- передать LLM нужный контекст: фокусный этап, stage scores, готовые LLM2
  evidence/cases, call list;
- проверить контракт результата;
- проверить техническую согласованность: stage match, call id, наличие строк,
  evidence refs, status;
- скрыть/заменить блок neutral empty-state, если LLM вернула `weak_blocked` или
  контракт нарушен;
- сохранить diagnostics.

Разделяем два разных решения:

1. **Фокус дня**
   - выбирается по агрегированным баллам и `focus_impact`;
   - может быть показан всегда, если есть валидные stage scores.

2. **Учебный кейс дня**
   - конкретный звонок для `СИТУАЦИЯ ДНЯ` / `РАЗБОР ЗВОНКА`;
   - выбирается LLM3 как лучший доступный кейс по фокусному этапу;
   - может иметь разный уровень доказанности: `strong`, `workable`,
     `weak_blocked`;
   - не должен подменять фокусный этап другим этапом.

Если по фокусному этапу нет идеального proof-case, отчет не должен сразу
скрывать разбор. LLM3 должна выбрать лучший рабочий кейс по этому же этапу и
осмысленно сформировать блоки, с учетом уровня доказанности.

Скрывать / empty-state использовать только если нет даже рабочего кейса:
слабый STT, нет понятной сцены, звонок вне рамок ЭДО или вывод слишком спорный.

## Что меняем

### 0. Перенести смысловую ответственность в LLM

#### LLM2 responsibility

LLM2 по каждому звонку готовит per-call report evidence, но не выбирает
“ситуацию дня” на уровне всего дня:

- `semantic_case`;
- `report_block_fit.situation_day`;
- `report_block_fit.call_breakdown`;
- `block_candidates.situation_day`;
- `block_candidates.call_breakdown`;
- `manager_coaching_moments`;
- evidence/proof/counter-evidence;
- stage code и объяснение, почему звонок подходит или не подходит для report
  block.

LLM2 должна уметь маркировать:

- `evidence_type=direct_quote`;
- `evidence_type=absence_in_context`;
- `evidence_type=inferred_from_dialogue`;
- `case_status_candidate=strong | workable | weak_blocked`, если поле уже есть
  или будет добавлено как additive metadata.

#### LLM3 responsibility

LLM3 на уровне дня получает:

- score-derived `daily_focus.stage_code`;
- список LLM2 candidates/evidence по звонкам;
- call list / statuses;
- запрет на подмену фокусного этапа другим этапом.

LLM3 должна:

- выбрать учебный кейс дня по фокусному этапу;
- определить `case_status=strong | workable | weak_blocked`;
- сформировать содержательную `СИТУАЦИЮ ДНЯ`;
- сформировать содержательный `РАЗБОР ЗВОНКА` или вернуть neutral blocked
  reason;
- если `strong` нет, попробовать `workable`;
- если есть только кейс по другому этапу, не использовать его как обычный
  `РАЗБОР ЗВОНКА`;
- использовать cautious wording для `workable`.

#### Report Layer responsibility

Report Layer не выбирает смысловой кейс сам. Он:

- принимает LLM3 result;
- проверяет `selected_case_stage_code == daily_focus.stage_code`, если выбран
  видимый учебный кейс;
- проверяет, что `selected_call_id` существует в отчете;
- проверяет наличие строк/полей для рендера;
- блокирует render при `blocked_mismatch`, `weak_blocked` или нарушении
  контракта;
- не делает fallback на legacy gaps/text/transcript для смыслового разбора.

### 1. Ввести явную LLM-модель выбора учебного кейса

В LLM3 composer output добавить или выделить единый decision object:

```json
{
  "focus_stage_code": "needs_discovery",
  "focus_stage_source": "score_by_stage.priority",
  "case_status": "strong | workable | weak_blocked | blocked_mismatch",
  "selected_call_id": "uuid-or-null",
  "selected_case_stage_code": "needs_discovery",
  "selection_reason": "best_available_focus_stage_case",
  "evidence_level": "strong | workable | weak",
  "wording_mode": "confident | cautious | blocked",
  "rejection_reasons": []
}
```

Рекомендуемая логика `case_score` для LLM-инструкции:

```text
case_score =
  stage_match
+ evidence_strength
+ coaching_value
+ business_importance
+ transcript_quality
- risk_penalty
```

На первом pass не нужно внедрять сложную числовую модель во все детали. LLM
получает bounded rubric:

- `stage_match`: обязательный gate для обычного `СИТУАЦИЯ ДНЯ` /
  `РАЗБОР ЗВОНКА`;
- `evidence_strength`: direct quote / grounded scene / absence-in-context;
- `coaching_value`: есть понятный урок и корректное действие;
- `business_importance`: договоренность, отказ, перенос, демо, риск потери,
  открытый интерес клиента;
- `transcript_quality`: есть читаемая сцена и понятно, о чем разговор;
- `risk_penalty`: спорная цитата, не тот этап, техподдержка, слабый STT,
  отсутствие связи с фокусом.

### 1.1. Уровни кейса

#### `strong`

Есть:

- звонок по фокусному этапу;
- прямые цитаты или сильная сцена;
- понятная причинно-следственная связь;
- корректный урок для менеджера.

Формулировка может быть уверенной:

```text
В этом звонке менеджер перешел к демо, не раскрыв критерии перехода клиента к покупке.
```

#### `workable`

Есть:

- звонок по фокусному этапу;
- понятная сцена, но ошибка доказана не одной прямой цитатой, а контекстом;
- особенно важно для `needs_discovery`, где проблема часто в отсутствии вопроса.

Формулировка должна быть осторожной:

```text
В доступной сцене не видно, чтобы менеджер отдельно уточнил боль, текущий процесс
и критерии перехода к покупке.
```

#### `weak_blocked`

Нет:

- читаемой сцены;
- связи с фокусным этапом;
- достаточного контекста для коучингового вывода;
- или звонок вне рамок продажной задачи ЭДО.

Только в этом случае `РАЗБОР ЗВОНКА` скрывается или заменяется neutral
empty-state.

### 2. Запретить подмену фокусного этапа

Если:

```text
call_breakdown.stage_code != daily_focus.stage_code
```

то это не warning, а blocker для блока `РАЗБОР ЗВОНКА`.

Ожидаемое поведение:

- `call_breakdown_stage_mismatch:*` должен блокировать render блока;
- блок не должен отображаться как обычный `РАЗБОР ЗВОНКА`;
- в payload сохранить diagnostics, чтобы оператор видел причину.

### 3. Связать `СИТУАЦИЯ ДНЯ` и `РАЗБОР ЗВОНКА`

Обычная manager-facing логика:

```text
СИТУАЦИЯ ДНЯ strong/workable -> РАЗБОР ЗВОНКА строится по тому же selected_call_id.
СИТУАЦИЯ ДНЯ weak_blocked -> РАЗБОР ЗВОНКА не строится по другому этапу.
```

Исключение можно добавить позже отдельным блоком, но не сейчас:

```text
Отдельный показательный звонок дня
```

Для пилота пока выбран строгий вариант: не смешивать фокус дня и отдельный
разбор другого этапа.

### 4. Поддержать absence-based кейсы через LLM

Для этапов типа `needs_discovery` проблема часто выражена отсутствием действия:

- менеджер не уточнил боль;
- не выяснил текущий процесс;
- не спросил сроки;
- не понял ЛПР / участников решения.

Одна цитата может не доказывать отсутствие вопроса. Поэтому LLM2/LLM3 должны
уметь формировать `absence_in_context` / `sequence_inference`, если есть
grounded scene:

- короткий фрагмент до перехода дальше;
- видно, что менеджер перешел к презентации/завершению;
- нет вопросов по боли/процессу/срокам/ЛПР;
- вывод формулируется как “в доступной сцене не видно”, а не как абсолютный
  факт обо всем звонке.

Важно: это не должно ослаблять proof gate до галлюцинаций. Нужна LLM-описанная
сцена, а не просто низкий балл.

### 5. Как должен выглядеть отчет при `workable` кейсе

Для Толегена за `2026-06-15` ожидаемая модель:

- фокус дня: `Выявление детальных потребностей`;
- выбрать лучший доступный звонок по `needs_discovery`;
- допустимый пример: звонок `+77075324094`, если он используется не как
  `Продажа: финал`, а как учебный кейс по выявлению потребностей:
  клиент обсуждает демо и возможную покупку в будущем, но критерии перехода к
  покупке, текущий процесс и боль не раскрыты достаточно глубоко;
- `Продажа: финал` остается отдельным `Критический сигнал`, но не становится
  темой обычного `РАЗБОР ЗВОНКА`.

Пример формулировки:

```text
Ситуация дня: менеджер перешел к обсуждению демо и дальнейших действий, но в
доступной сцене не видно, чтобы отдельно раскрыл, зачем клиенту демо, какой
процесс он хочет проверить и по каким критериям будет принимать решение о
покупке.
```

Пример строк разбора:

| Момент | Что произошло | Что важно | Как лучше |
| --- | --- | --- | --- |
| Клиент просит демо и объяснение | Клиент хочет, чтобы сотруднику показали работу с документами и договорами | Это вход в потребность, но ее нужно раскрыть глубже | “Что именно хотите проверить на демо: подписание, маршруты, накладные, роли сотрудников?” |
| Клиент говорит про бесплатную версию | Клиент готов сначала посмотреть демо, а покупку отложить на будущее | Не хватает критериев перехода от демо к покупке | “По каким признакам поймете, что сервис подходит и можно переходить на платный тариф?” |
| Следующий шаг остается общим | Интерес есть, но нет условия возврата к покупке | Без критерия демо может остаться консультацией | “Давайте после демо зафиксируем короткий созвон: подходит / не подходит / что мешает покупке.” |

### 6. Neutral empty-state только для `weak_blocked`

Если фокус по баллам есть, но даже рабочий кейс не найден:

```text
Фокус дня определен по агрегированной оценке, но в доступных звонках не найдено
достаточно читаемой сцены для учебного разбора по этому этапу.
```

Для `РАЗБОР ЗВОНКА`:

```text
Подробный разбор не сформирован: нет достаточно читаемого рабочего кейса по
фокусному этапу.
```

Главное: не показывать разбор по другому этапу как связанный с фокусом дня.

### 7. Единый формат `СИТУАЦИИ ДНЯ`

Сейчас DOCX/PDF renderer использует разные визуальные ветки:

- при `situation_day_evidence_status == "insufficient"` в
  `scripts/generate_docx_report.js` срабатывает отдельный текстовый layout с
  подразделами;
- при подтвержденной ситуации используется другой layout с более привычной
  структурой и таблицей;
- в Python renderer также есть отдельная обработка insufficient-state.

Решение: `СИТУАЦИЯ ДНЯ` должна иметь один manager-facing формат независимо от
уровня доказанности (`strong`, `workable`, `weak_blocked`).

Целевой формат:

1. Фокусный этап / краткая причина.
2. Пример из сегодня / звонок, если есть selected case.
3. Короткий абзац `Что произошло`.
4. Единая таблица:

| Поле | Содержание |
| --- | --- |
| Что это значит | смысл ситуации для менеджера |
| Что не хватило в разговоре | недостающее действие или риск |
| Что делать в следующий раз | конкретная рекомендация / фраза |

Для `workable` кейса структура такая же, но текст осторожнее:

```text
В доступной сцене не видно...
Судя по фрагменту...
Этот кейс выбран как рабочий учебный пример...
```

Для `weak_blocked`:

- либо скрыть блок;
- либо показать короткий neutral empty-state внутри того же формата;
- не включать длинные служебные подразделы и диагностику.

Запрещено:

- показывать разные layout-форматы одного блока у разных менеджеров;
- выводить внутренние статусы типа `insufficient` как отдельный визуальный
  формат;
- рендерить текстовую “простыню” вместо таблицы;
- показывать `Фокусный этап: Продажа: финал`, если дневной фокус уже
  `Выявление детальных потребностей`.

## Что не меняем

- Не меняем LLM2 scoring.
- Не меняем stage scores и `Балл дня`.
- Не меняем веса `PILOT-31`.
- Не добавляем новый публичный блок `Отдельный показательный звонок дня`.
- Не используем deterministic смысловые fallback для подмены LLM-смысла.
- Не строим обычный `РАЗБОР ЗВОНКА` по другому этапу.
- Не требуем только ideal direct-proof case: `workable` учебный кейс допустим.

## Где менять

### LLM prompt / contract

- `core/app/agents/calls/prompts/analyze.md`
  - уточнить, что LLM2 готовит per-call report evidence и
    `case_status_candidate`, но не выбирает день;
  - усилить правила для `absence_in_context` и counter-evidence.
- `core/app/agents/calls/prompts/llm2_pass_contracts.md`
  - синхронизировать additive contract для LLM2 report evidence.
- `core/app/agents/calls/prompts/situation_day_daily_composer_v2.md`
  - добавить LLM3 responsibility: выбрать учебный кейс по score-derived focus;
  - явно запретить подмену этапа;
  - описать `strong/workable/weak_blocked`;
  - потребовать готовые manager-facing тексты `СИТУАЦИЯ ДНЯ` и
    `РАЗБОР ЗВОНКА`.
- `core/app/agents/calls/prompts/call_breakdown_composer_v2.md`
  - если composer используется отдельно, он должен принимать выбранный LLM3
    case/focus decision и писать только по нему.

Основные зоны:

- `core/app/agents/calls/reporting.py`
  - `_finalize_daily_coaching_focus(...)`;
  - участок сборки `situation_day_coaching_view`;
  - участок сборки `call_breakdown`;
  - `_apply_call_breakdown_quality_gate(...)`;
  - diagnostics для `daily_coaching_focus_validation`.

- `core/app/agents/calls/prompts/call_breakdown_composer_v2.md`
  - если отдельный breakdown composer вызывается после LLM3 selection, он
    должен принимать выбранный LLM3 case/focus decision;
  - composer не должен выбирать другой смысловой кейс самостоятельно.

- `core/app/agents/calls/situation_day_daily_composer.py`
  - расширить input/output нормализацию под `focus_case_selection`;
  - не выбирать смысл deterministic scoring-ом, кроме технического ranking уже
    сформированных LLM candidates для передачи в prompt;
  - сохранить LLM decision в payload diagnostics.

- `core/app/agents/calls/report_templates.py`
  - отображение `evidence_level` / осторожной формулировки, если кейс
    `workable`;
  - neutral empty-state или hide behavior только для `weak_blocked`;
  - убрать отдельный manager-facing layout для insufficient-state или привести
    его к тому же табличному формату.

- `scripts/generate_docx_report.js`
  - если DOCX/PDF рендерит блок напрямую, повторить hide/empty-state там;
  - убрать специальную ветку
    `s.coaching_view?.situation_day_evidence_status === "insufficient"` как
    отдельный визуальный формат; статус доказанности должен влиять на текст, а
    не на структуру блока.

## Acceptance criteria

1. Если `daily_focus.stage_code = needs_discovery`, то обычный
   `call_breakdown.stage_code` должен быть `needs_discovery`.
2. Если `call_breakdown.stage_code != daily_focus.stage_code`, блок
   `РАЗБОР ЗВОНКА` не рендерится как обычный manager-facing разбор.
3. `call_breakdown_stage_mismatch:*` становится render blocker для блока, а не
   только warning.
4. Если по фокусному этапу нет `strong` кейса, LLM3 пытается выбрать
   `workable` кейс по тому же этапу, а не сразу скрывает блок.
5. Для `needs_discovery` допускается LLM-сформированный
   `absence_in_context` кейс, если есть grounded scene и аккуратная
   формулировка.
6. В отчете Толегена за `2026-06-15` после rerender:
   - фокус остается `Выявление детальных потребностей`;
   - `Продажа: финал` может остаться `Критический сигнал`;
   - `РАЗБОР ЗВОНКА` строится по `needs_discovery`, если найден хотя бы
     `workable` case;
   - если выбран звонок `+77075324094`, он разбирается именно как кейс
     `needs_discovery`, а не `sale_final`;
   - блок использует cautious wording: “в доступной сцене не видно...”.
7. `СИТУАЦИЯ ДНЯ` визуально остается в едином формате у Толегена, Тимура,
   Алишера и других менеджеров:
   - нет отдельного layout для `insufficient`;
   - есть таблица `Что это значит / Что не хватило / Что делать`;
   - уровень доказанности влияет только на формулировки.
8. В DOCX/PDF Толегена больше не появляется формат с длинной последовательностью
   подразделов `Фокусный этап`, `Пример из сегодня`, `Что произошло`,
   `Почему это важно`, `Что делать`, `Как сказать`.

## Test plan

Focused tests:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_manual_reporting.py \
  -k "situation_day or call_breakdown or daily_coaching_focus or stage_mismatch"
```

Static checks:

```bash
python3 -m py_compile core/app/agents/calls/reporting.py core/app/agents/calls/report_templates.py
node --check scripts/generate_docx_report.js
git diff --check
```

Manual verification:

1. Rerender Толегена за `2026-06-15`.
2. Проверить `score_by_stage`: priority `needs_discovery`.
3. Проверить `daily_coaching_focus.validation`.
4. Проверить, что `call_breakdown_stage_mismatch:sale_final` не приводит к
   видимому разбору по `sale_final`.
5. Проверить, что при отсутствии `strong` case выбран `workable` case по
   `needs_discovery`, если он есть.
6. Проверить, что `СИТУАЦИЯ ДНЯ` у Толегена и Тимура использует один и тот же
   layout.
7. Проверить PDF/DOCX визуально.

## Implementation status

First pass выполнен агентами 2026-06-16:

- `core/app/agents/calls/reporting.py`
  - добавлен/расширен `focus_case_selection` diagnostics object;
  - `daily_focus` остается score-derived, а учебный кейс выбирается отдельно;
  - `call_breakdown.stage_code != daily_focus.stage_code` блокируется как
    `blocked_mismatch`;
  - fallback `РАЗБОР ЗВОНКА` через `report_evidence` восстановлен только для
    LLM evidence по фокусному этапу;
  - relaxed selection по другому этапу отключен, если фокусный этап известен;
  - `legacy_fallback` для смыслового разбора из `gaps`/текста без LLM evidence
    остается отключенным.
- `core/app/agents/calls/report_templates.py`
  - `СИТУАЦИЯ ДНЯ` для `insufficient/workable` использует единый табличный
    manager-facing layout.
- `scripts/generate_docx_report.js`
  - отдельная визуальная ветка для insufficient-state убрана.
- `core/tests/test_manual_reporting.py`
  - добавлены focused checks на unified layout;
  - один legacy test актуализирован под явный focus stage.

Проверки:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_manual_reporting.py \
  -k "situation_day_insufficient_uses_unified_review_layout or situation_day_workable_keeps_same_review_layout or situation_day_docx_generator_has_no_insufficient_visual_branch"
# 2 passed, 1 skipped

python3 -m py_compile core/app/agents/calls/reporting.py core/app/agents/calls/report_templates.py
node --check scripts/generate_docx_report.js
```

Second pass под LLM ownership выполнен агентами 2026-06-16:

- `core/app/agents/calls/prompts/analyze.md`
  - LLM2 отвечает за per-call report evidence и `case_status_candidate`, но не
    выбирает кейс дня.
- `core/app/agents/calls/prompts/llm2_pass_contracts.md`
  - добавлены `case_status_candidate`, `report_case_candidates`, граница
    LLM2/LLM3 и правила `absence_in_context`.
- `core/app/agents/calls/prompts/situation_day_daily_composer_v2.md`
  - LLM3 получает score-derived focus и выбирает учебный кейс дня;
  - LLM3 возвращает `focus_case_selection` с
    `strong/workable/weak_blocked/blocked_mismatch`;
  - содержательные тексты `СИТУАЦИИ ДНЯ` и `РАЗБОР ЗВОНКА` формирует LLM3.
- `core/app/agents/calls/prompts/call_breakdown_composer_v2.md`
  - breakdown composer привязан к тому же LLM3 decision object,
    `selected_call_id` и stage.
- `core/app/agents/calls/situation_day_daily_composer.py`
  - deterministic смысловой fallback убран;
  - composer пакует LLM2 candidates для prompt, нормализует/валидирует LLM3
    `focus_case_selection`, сохраняет decision object и блокирует mismatch.
- `core/app/agents/calls/reporting.py`
  - Report Layer больше не выбирает best/workable case сам;
  - Report Layer применяет только contract/stage/call-id/render gates;
  - legacy/report-evidence/transcript/gaps fallback не строит смысловой
    `РАЗБОР ЗВОНКА`.
- `core/tests/test_situation_day_daily_composer.py` и
  `core/tests/test_manual_reporting.py`
  - focused tests обновлены под LLM-only semantic ownership.

Проверки second pass:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_manual_reporting.py \
  -k "situation_day or call_breakdown or daily_coaching_focus or stage_mismatch"
# 20 passed, 1 skipped

docker compose exec -T api python -m pytest -q \
  /app/tests/test_situation_day_daily_composer.py
# 13 passed

python3 -m py_compile \
  core/app/agents/calls/reporting.py \
  core/app/agents/calls/report_templates.py \
  core/app/agents/calls/situation_day_daily_composer.py \
  core/tests/test_situation_day_daily_composer.py

node --check scripts/generate_docx_report.js
git diff --check -- <PILOT-32 touched files>
```

Открытая часть перед `done`:

- manual verification на rerender Толегена за `2026-06-15`;
- визуально подтвердить, что LLM3-owned `needs_discovery` case отображается
  корректно или показывается neutral empty-state;
- полный suite не запускался в рамках этого pass.

## Разделение по агентам

### Agent A — LLM contract and prompts

- Обновить LLM2/LLM3 prompt contracts;
- зафиксировать, что LLM отвечает за смысловой выбор и содержание блока;
- добавить `focus_case_selection` / `case_status` contract;
- описать `absence_in_context` как LLM-evidence pattern;
- добавить/обновить tests на prompt assets, если такие tests есть.

### Agent B — Report Layer gates and rendering

- Убрать смысловой best-case selection из Report Layer first pass;
- оставить stage/contract/render gates;
- убедиться, что `call_breakdown` не строится из legacy `gaps`/text;
- унифицировать layout `СИТУАЦИИ ДНЯ`;
- синхронизировать DOCX/PDF generator;
- обновить focused tests под LLM-only semantic ownership.

### Controller

- Прогнать focused tests и static checks;
- пересобрать отчет Толегена за `2026-06-15`;
- подтвердить, что LLM3 выбирает лучший доступный учебный кейс по фокусному
  этапу, а Report Layer не смешивает фокусный этап с разбором другого этапа.

## Риски

- Блок `РАЗБОР ЗВОНКА` может стать менее “железобетонным” по proof.
  - Защита: вводим `evidence_level` и cautious wording для `workable` cases.
- Для absence-based проблем может не хватать scene evidence.
  - Тогда задача следующего уровня: усилить LLM2/LLM3 evidence generation для
    `absence_in_context`, но без ослабления proof gate.
- Если слишком часто брать слабые рабочие кейсы, отчет может казаться
  натянутым.
  - Защита: `weak_blocked` остается допустимым outcome, если сцена нечитаема или
    вывод спорный.

## Definition of Done

- `PILOT-32` реализован минимум как `implemented_first_pass_llm_ownership`;
- лучший доступный учебный кейс по фокусному этапу выбирает LLM3, а не Report
  Layer;
- содержательные тексты `СИТУАЦИИ ДНЯ` и `РАЗБОР ЗВОНКА` формирует LLM;
- Report Layer не строит смысловой fallback из `gaps`, score rows, transcript
  text или deterministic эвристик;
- `strong/workable/weak_blocked` сохраняется в diagnostics;
- mismatch между фокусом и breakdown блокирует видимый разбор по другому этапу;
- отсутствие `strong` case по фокусному этапу не приводит к подмене другим
  этапом, а сначала пытается использовать `workable` case;
- `СИТУАЦИЯ ДНЯ` использует единый manager-facing layout независимо от
  evidence status;
- focused tests passed;
- контрольный отчет Толегена за `2026-06-15` проверен.
