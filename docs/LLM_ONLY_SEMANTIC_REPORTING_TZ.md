# TZ: LLM-only semantic reporting

Дата: 2026-06-05
Дата актуализации: 2026-06-09

Статус: implemented_first_pass / awaiting control rerender

Итог первого pass от 2026-06-10:

- `call_list_status` / `final_manager_status` в manager_daily берутся только из
  LLM semantic fields: `scores_detail.status_details.status` или
  `report_evidence.business_outcome.status`;
- `BusinessOutcomeResolver` оставлен только как diagnostic signal
  (`resolver_status*`) и не может стать manager-facing статусом;
- отсутствие LLM-статуса отображается как `Статус не подтвержден`, а не как
  `Ошибка анализа`, `Открыт` или resolver fallback;
- верхняя сводка и email получили отдельный счетчик
  `СТАТУС НЕ ПОДТВЕРЖДЕН`;
- `agreement` из `business_outcome` требует LLM action anchor
  (`what_agreed` / `agreement_subject` / commitment / `next_step` /
  `deadline` / `condition`) и evidence quote; одного `reason + quote`
  недостаточно;
- payload сохраняет `semantic_status_quality`, `semantic_status_missing_reason`,
  `call_list_display_status`, `call_list_status_quality.*` и
  `call_outcomes_summary.status_not_confirmed_*`.

Следующая проверка: контрольный rerender/прогон Толегена за `2026-06-04` и
post-run audit, что false `Договорённость` из resolver fallback исчезла.

## 1. Контекст

В пилотных ежедневных отчетах обнаружена системная проблема: часть бизнес-смысла
в Report Layer определяется не LLM, а локальными deterministic / heuristic
механизмами. Пример: в отчете Толегена за 4 июня 2026 часть строк получила
статус `ДОГОВОРЕННОСТЬ` через `BusinessOutcomeResolver`, хотя LLM2 не подтвердил
договоренность через `business_outcome` / `status_details`.

Новое базовое требование: если в отчете требуется определить смысл звонка,
сделки, статуса, причины, приоритета, горячести, ситуации дня или рекомендации,
этот смысл должен быть сформирован только LLM. Код может только выбирать из уже
сформированных LLM-полей, валидировать наличие evidence, форматировать,
сортировать и считать.

## 2. Цель

Исключить подмену LLM-смысла deterministic fallback-логикой в manager_daily
Report Layer.

После доработки отчет должен быть честным:

- если LLM дала подтвержденный смысл, отчет его показывает;
- если LLM не дала смысл или evidence, отчет показывает нейтральное состояние
  `не подтверждено LLM` / `нет готового разбора`, а не пытается восстановить
  смысл кодом;
- счетчики и диагностика должны показывать, сколько строк осталось без
  LLM-подтверждения.

## 3. Основной принцип

### 3.1. Fail-neutral, not fail-empty

Цель `PILOT-17` - не ужесточить отчет до пустых разделов, а убрать
deterministic подмену смысла. Если LLM дала смысл, отчет должен использовать
его максимально полно. Если смысл слабый или неполный, отчет должен показывать
осторожное нейтральное состояние, а не скрывать весь раздел и не придумывать
смысл кодом.

Принцип:

- есть LLM-смысл - показываем;
- LLM-смысл неполный или слабый - показываем осторожно с quality/diagnostics;
- LLM-смысла нет - показываем нейтральное состояние;
- код не достраивает бизнес-выводы сам.

Для LLM semantic status использовать мягкую шкалу качества:

| Quality | Когда | Как показывать |
| --- | --- | --- |
| `confirmed` | LLM дала статус и понятное основание / evidence | Показывать обычный бизнес-статус |
| `weak` | LLM дала статус, но evidence или next-step неполные | Показывать осторожно, с diagnostics; для рискованных статусов применять дополнительные правила |
| `missing` | LLM не дала валидный статус | Показывать `Статус не подтвержден` |

Особое правило для `agreement`: ложная договоренность критичнее ложного
нейтрального статуса, поэтому `agreement` должен быть `confirmed`. Если LLM
дала `agreement`, но не дала понятное основание / суть договоренности /
evidence, строка не должна отображаться как `ДОГОВОРЕННОСТЬ`; она переходит в
`Статус не подтвержден` с reason `agreement_missing_evidence`.

Для менее рискованных статусов (`open`, `tech_service`, часть `rescheduled` /
`refusal`) допустим `weak`, если LLM явно назвала статус и есть хотя бы краткое
основание. При этом payload должен сохранить quality flag, чтобы в post-run
audit было видно, где статус требует внимания.

### 3.2. Разрешения и запреты для кода

Код имеет право:

- считать количество звонков, STT, анализов, отчетов;
- проверять наличие/валидность LLM-полей;
- проверять наличие evidence / quote / deadline / next step;
- сортировать строки;
- форматировать даты, телефоны, статусы и текст;
- скрывать блоки с недостаточным LLM evidence;
- маркировать строку как `Без подтвержденного статуса`,
  `Суть не сформирована LLM`, `Нет готового разбора`.
- показывать заполненный раздел в осторожном режиме, если LLM дала неполный,
  но usable материал (`semantic_quality=weak`).

Код не имеет права:

- определять бизнес-статус звонка по ключевым словам;
- выводить договоренность, отказ, перенос, открытый контакт или тех/сервис,
  если LLM не дала этот статус;
- формулировать суть звонка из transcript/follow_up/status;
- определять горячесть контакта по ключевым словам;
- создавать ситуацию дня, проблему этапа, рекомендацию или похвалу шаблонными
  фразами, если LLM не дала соответствующий смысл;
- подставлять generic manager-facing смысловые фразы так, как будто они
  подтверждены анализом.

## 4. Затрагиваемые зоны

### 4.1. Общий статус звонка в `Все звонки дня`

Файлы:

- `core/app/agents/calls/reporting.py`
- `core/app/agents/calls/report_templates.py`

Текущая проблема:

- `_build_daily_call_row()` сначала получает `BusinessOutcomeResolver().resolve(...)`;
- если LLM2 `report_evidence.business_outcome` отсутствует, строка использует
  resolver status;
- `BusinessOutcomeResolver` может поставить `agreed`, `rescheduled`, `refusal`,
  `open`, `tech_service` по ключевым словам.

Нужно изменить:

1. Сделать LLM2 единственным источником `call_list_status` /
   `final_manager_status`.
2. Приоритет источников:
   - `scores_detail.status_details.status`, если есть и валиден;
   - `report_evidence.business_outcome.status`, если есть и валиден;
   - иначе `None`.
   Для каждого найденного статуса дополнительно определить
   `semantic_status_quality = confirmed | weak | missing`.
3. Если статус `None`, в payload фиксировать:
   - `call_list_status = None`;
   - `final_manager_status = None`;
   - `call_list_unclassified_status_label = "Без подтвержденного статуса"`;
   - `call_list_status_source = "missing_llm_semantic_status"`;
   - `call_list_status_fallback_reason = "llm_status_missing"`.
4. `BusinessOutcomeResolver` больше не должен быть источником видимого
   `final_manager_status`.
5. `BusinessOutcomeResolver` можно временно оставить только для diagnostics:
   `resolver_status`, `resolver_reason_code`, `resolver_confidence`, но в
   manager-facing статус его не использовать.
6. Для `agreement` дополнительно требовать LLM-поля:
   - статус `agreement`;
   - причина/суть договоренности;
   - evidence;
   - next step или deadline/condition, если есть в звонке.
   Если LLM дала `agreement`, но без доказательства, статус не показывать как
   договоренность, а маркировать как `agreement_missing_evidence`.
7. Для `open`, `tech_service`, `rescheduled`, `refusal` не требовать
   идеального evidence, если LLM явно дала статус и есть хотя бы краткое
   основание. Такие строки можно показывать с `semantic_status_quality=weak`,
   чтобы отчет не стал пустым, а post-run audit видел качество источника.

Ожидаемый эффект:

- ложные договоренности, созданные resolver-ом, исчезают;
- в отчете появляются честные строки без подтвержденного статуса, если LLM2 не
  дала бизнес-исход.

### 4.1.1. Как отображать отсутствие LLM-статуса

Важно: отсутствие LLM-подтвержденного статуса - это не техническая ошибка
анализа. Это отдельное нейтральное состояние: анализ мог быть построен, но LLM
не дала безопасный бизнес-исход с достаточным evidence.

#### Верхняя сводка дня

В верхней сводке дня добавить отдельную категорию:

```text
СТАТУС НЕ ПОДТВЕРЖДЕН
```

Пример:

```text
1 ДОГОВОРЕННОСТЬ
1 ПЕРЕНОС
0 ОТКАЗ
4 ОТКРЫТ
3 ТЕХ/СЕРВИС
2 СТАТУС НЕ ПОДТВЕРЖДЕН
```

Правила:

1. `СТАТУС НЕ ПОДТВЕРЖДЕН` считать только по звонкам с готовым анализом, где
   нет валидного LLM semantic status.
2. Не смешивать эту категорию с:
   - `Ошибка анализа`;
   - `нет готового разбора`;
   - `исключено из списка дня`;
   - `тех/сервис`.
3. Если таких звонков `0`, строку можно не показывать или показывать как
   `0 СТАТУС НЕ ПОДТВЕРЖДЕН` по общему правилу renderer-а для нулевых
   статусов.
4. Воронка дня должна оставаться математически честной:
   - `найдено в телефонии`;
   - `содержательных`;
   - `исключено из списка дня`;
   - `не вошло в коучинговый разбор`;
   - `вошло в коучинговый разбор`.
   Категория `СТАТУС НЕ ПОДТВЕРЖДЕН` относится только к уже
   проанализированным звонкам внутри видимого списка / summary, а не к
   day-funnel exclusions.

#### Таблица `Все звонки дня`

В колонке `Статус` для таких строк показывать:

```text
Статус не подтвержден
```

В payload:

```json
{
  "call_list_status": null,
  "final_manager_status": null,
  "call_list_display_status": "status_not_confirmed",
  "call_list_display_status_label": "Статус не подтвержден",
  "call_list_status_source": "missing_llm_semantic_status",
  "semantic_status_quality": "missing",
  "semantic_status_missing_reason": "llm_status_missing"
}
```

Если LLM дала status, но он не прошел evidence gate, использовать отдельную
причину:

```json
{
  "call_list_status_source": "llm_semantic_status_rejected",
  "semantic_status_quality": "missing",
  "semantic_status_missing_reason": "agreement_missing_evidence"
}
```

#### Колонка `Итог / обратная связь`

Для строки без подтвержденного статуса:

- если есть LLM-комментарий по звонку, показывать его;
- если LLM-комментария нет, показывать нейтрально:

```text
Нет подтвержденного итога звонка
```

Запрещено подставлять generic-фразы вроде:

- `Есть рабочий контакт с клиентом`;
- `Закрепить следующий шаг`;
- `Клиент заинтересован`;
- `Договоренность требует фиксации`.

#### Diagnostics / observability

Добавить или сохранить отдельные счетчики:

- `status_not_confirmed_count`;
- `status_not_confirmed_with_analysis_count`;
- `status_not_confirmed_missing_llm_count`;
- `status_not_confirmed_rejected_evidence_count`;
- `analysis_error_count`.

`status_not_confirmed_count` и `analysis_error_count` должны быть разными
метриками. Если анализ технически сломан, это `analysis_error`. Если анализ
есть, но LLM не дала безопасный статус, это `status_not_confirmed`.

### 4.2. Суть звонка / контекст строки

Файл:

- `core/app/agents/calls/reporting.py`

Текущая проблема:

- `_select_call_list_context()` может собрать контекст через
  `_call_list_status_fallback_context(...)`;
- fallback строит смысл из status, next step, reason, transcript и других
  не-LLM semantic источников.

Нужно изменить:

1. Основные источники для `call_list_context`:
   - `report_evidence.call_report_summary.manager_visible_summary`;
   - `report_evidence.call_essence.manager_visible_text`;
   - `report_evidence.block_candidates.call_list_context`;
   - другие валидные LLM2 поля, если они уже есть в контракте.
2. Если LLM-контекста нет или он rejected quality gate:
   - не генерировать смысловой fallback;
   - ставить `call_list_context = "Суть не сформирована LLM"`;
   - `call_list_context_source = "missing_llm_call_context"`;
   - `call_list_context_fallback_generated = false`;
   - diagnostics: `llm_context_missing = true`.
   Если LLM-контекст есть, но он неполный / короткий, не скрывать строку:
   показывать лучший usable LLM-контекст и помечать
   `call_list_context_quality = "weak"`.
3. Не использовать transcript, status, next_step, reason для генерации нового
   смысла. Их можно использовать только для проверки evidence или отображения
   уже сформированного LLM-вывода.

### 4.3. Итог / обратная связь по звонку

Файл:

- `core/app/agents/calls/reporting.py`

Текущая проблема:

- `_build_call_feedback_summary()` берет LLM2 strengths/gaps/recommendations,
  но если их нет, подставляет generic фразы:
  `Есть рабочий контакт с клиентом`, `Закрепить следующий шаг...`;
- outcome может строиться из status/outcome_reason fallback-логикой.

Нужно изменить:

1. `Итог` брать только из:
   - `scores_detail.status_details`;
   - LLM2 `business_outcome`;
   - LLM2 `follow_up`;
   - LLM2 `call_report_summary`, если оно явно про итог звонка.
2. `Сильное` брать только из LLM2 `strengths` или applicable strong criteria.
3. `Улучшить` брать только из LLM2 `gaps` / `recommendations` /
   weak criteria.
4. Если данных нет:
   - не подставлять generic смысл;
   - показывать `Нет LLM-комментария` или оставлять ячейку пустой по
     утвержденному renderer contract;
   - diagnostics: `call_feedback_missing_fields`.
   Если есть только часть LLM-данных, например `strength` без `gap`, показывать
   эту часть, а не добавлять искусственное улучшение.
5. Для limited/not applicable сценариев не писать продажные generic советы.
   Если LLM не дала сервисный комментарий, строка должна быть нейтральной.

### 4.4. `Кого взять в работу завтра` / hotness / priority

Файл:

- `core/app/agents/calls/reporting.py`

Текущая проблема:

- `_follow_up_hotness()` и `_call_tomorrow_signal_category()` определяют
  горячесть и категорию по deterministic keyword signals;
- код может решить, что контакт hot/warm/low, invoice/payment, meeting/demo,
  materials request и т.д.

Нужно изменить:

1. Включение в блок `Кого взять в работу завтра` должно базироваться только на
   LLM2:
   - `status_details`;
   - `business_outcome`;
   - `follow_up`;
   - `follow_up_candidates`;
   - `call_report_summary.manager_next_action`;
   - `call_report_summary.hotness`, если валидно и применимо.
2. Deterministic hotness/category не использовать как смысловой источник.
3. Если LLM не дала priority/hotness:
   - показывать нейтральный приоритет `не определен LLM`;
   - или исключать из блока, если нет достаточного next step.
4. Код может сортировать по LLM deadline/time, но не придумывать приоритет.

### 4.5. Ситуация дня

Файл:

- `core/app/agents/calls/reporting.py`

Текущая проблема:

- есть deterministic assembly / fallback из evidence registry, stages,
  transcript/dialogue fragments;
- код может собрать ситуацию дня, когда LLM не дала полноценную ситуацию.

Нужно изменить:

1. Ситуация дня показывается только если есть LLM-сформированный блок:
   - valid `report_evidence.situation_candidates`;
   - valid `block_candidates.situation_day`;
   - valid LLM3/report-composer output, если используется.
2. Код может проверить:
   - есть ли client/manager evidence;
   - соответствует ли evidence выбранному stage;
   - нет ли counter-evidence.
3. Код не должен сам формулировать:
   - `what_happened`;
   - `meaning`;
   - `what_was_missing`;
   - `next_time_action`;
   - scripts.
4. Если LLM-ситуации нет, блок скрыть или показать нейтрально:
   `Ситуация дня не сформирована LLM`.
5. Если LLM дала usable, но неполную ситуацию, не обнулять блок автоматически:
   показать осторожную версию с diagnostics `situation_day_quality=weak`, если
   renderer может вывести ее без добавления новых фактов.

### 4.6. Баллы по этапам / комментарий к этапу

Файл:

- `core/app/agents/calls/reporting.py`

Текущая проблема:

- `_stage_problem_fallback()` и соседние normalizer-ы могут подставлять
  типовые проблемы этапов.

Нужно изменить:

1. Числовые баллы можно считать кодом из LLM2 scoring output.
2. Комментарий/проблема по этапу должны идти только из LLM2:
   - `score_by_stage[].main_problem`;
   - criteria comments;
   - gap/recommendation, если evidence-bound.
3. Если комментария нет, показывать:
   `Комментарий LLM не сформирован`.
4. Если комментарий есть, но слабый/короткий, показывать его с diagnostics
   `stage_comment_quality=weak`, а не заменять шаблонной проблемой.
5. Код может нормализовать длину/формат, но не заменять смысл шаблоном.

### 4.7. Разбор звонка

Файл:

- `core/app/agents/calls/reporting.py`

Текущая проблема:

- block selection/ranking нормальны как deterministic операции, но legacy
  fallback может использовать gaps/recommendations/evidence fragments и
  transcript fragments для создания разборов.

Нужно изменить:

1. Разбор звонка показывать только по LLM-сформированным manager coaching
   moments / block candidates / semantic case.
2. Код может:
   - выбрать лучший LLM-кандидат;
   - проверить evidence;
   - проверить role/problem-fit;
   - скрыть слабый блок.
3. Код не должен создавать новый manager-facing разбор из transcript fragment
   или stage fallback.
4. Если кандидата нет, показывать явное:
   `Нет LLM-подтвержденного разбора звонка`.

### 4.8. Голос клиента

Блок сейчас скрыт, но правило нужно зафиксировать до возврата.

Нужно:

1. Voice of customer показывать только из LLM-сформированных:
   - `report_evidence.voice_of_customer`;
   - `quote_bank`;
   - block candidate `voice_of_customer`.
2. Deterministic signal mapping может быть только diagnostics, не
   manager-facing рекомендацией.
3. Manager action по голосу клиента должна идти от LLM или быть скрыта.

## 5. Новые diagnostics

Добавить в payload / observability:

- `semantic_source_policy = "llm_only_v1"`;
- `llm_semantic_status_available_count`;
- `llm_semantic_status_missing_count`;
- `llm_semantic_status_confirmed_count`;
- `llm_semantic_status_weak_count`;
- `status_not_confirmed_count`;
- `status_not_confirmed_with_analysis_count`;
- `status_not_confirmed_missing_llm_count`;
- `status_not_confirmed_rejected_evidence_count`;
- `analysis_error_count`;
- `business_outcome_resolver_visible_usage_count = 0`;
- `call_list_context_missing_llm_count`;
- `call_feedback_missing_llm_count`;
- `tomorrow_priority_missing_llm_count`;
- `situation_day_missing_llm`;
- `stage_comment_missing_llm_count`;
- `legacy_semantic_fallback_blocked_count`.

Для каждой строки `call_list[]` добавить или сохранить:

- `final_manager_status_source`;
- `call_list_status_source`;
- `llm2_business_outcome_status`;
- `status_details_status`;
- `semantic_status_quality`;
- `semantic_status_missing_reason`;
- `call_list_display_status`;
- `call_list_display_status_label`;
- `resolver_status_diagnostic`;
- `resolver_reason_code_diagnostic`.

Важно: если resolver оставлен, поля должны явно называться diagnostic, чтобы
новый агент не использовал их как source of truth.

## 6. Изменения в документации

Обновить:

- `docs/MANAGER_DAILY_SELECTION_MODEL.md`
  - заменить старое правило, где `BusinessOutcomeResolver` финальная власть;
  - зафиксировать `LLM-only semantic policy`;
  - переписать секции про call-list context fallback, tomorrow hotness,
    situation fallback.
- `docs/LLM2_MANAGER_DAILY_INSTRUCTIONS_MAP.md`
  - заменить формулировки `Reporting keeps deterministic final authority`;
  - указать: Reporting validates/selects/renders, but does not infer business
    meaning.
- `docs/MANAGER_REPORT_FEEDBACK.md`
  - зафиксировать проблему 2026-06-05: ложные договоренности Толегена из
    resolver fallback.
- `docs/PILOT_BACKLOG.md`
  - добавить задачу как priority 1 для стабилизации пилота.

## 7. Тест-план

### 7.1. Unit tests

Добавить/обновить tests:

- `test_call_list_status_uses_llm_only`
  - LLM2 `business_outcome=agreement` -> status `agreed`;
  - no LLM2 status + resolver would say `agreed` -> visible status is `None`
    / `Без подтвержденного статуса`;
  - resolver diagnostics are present but not visible source.
- `test_status_not_confirmed_is_not_analysis_error`
  - готовый analysis без LLM semantic status -> visible status
    `Статус не подтвержден`;
  - `status_not_confirmed_count` увеличивается;
  - `analysis_error_count` не увеличивается;
  - верхняя сводка дня показывает отдельную строку
    `СТАТУС НЕ ПОДТВЕРЖДЕН`.
- `test_rejected_llm_agreement_becomes_status_not_confirmed`
  - LLM status `agreement` без evidence / next-step proof не отображается как
    `ДОГОВОРЕННОСТЬ`;
  - строка получает `semantic_status_missing_reason =
    agreement_missing_evidence`;
  - summary учитывает ее как `СТАТУС НЕ ПОДТВЕРЖДЕН`.
- `test_weak_llm_status_is_rendered_without_deterministic_enrichment`
  - LLM дала `open` или `tech_service` с кратким основанием, но без полного
    evidence package;
  - строка отображает LLM-статус с `semantic_status_quality=weak`;
  - код не добавляет новые reason / recommendation / hotness из transcript.
- `test_call_list_context_no_deterministic_semantic_fallback`
  - no LLM context -> `Суть не сформирована LLM`;
  - no generated business meaning from transcript/status.
- `test_call_feedback_no_generic_semantic_fallback`
  - no strengths/gaps/recommendations/status_details -> no generic
    `Есть рабочий контакт` / `Закрепить следующий шаг`.
- `test_tomorrow_priority_uses_llm_only`
  - keyword `счет` in transcript without LLM follow-up does not create hot
    tomorrow item.
- `test_situation_day_hidden_without_llm_candidate`
  - no LLM situation candidate -> block hidden or explicit missing LLM note.
- `test_stage_comment_missing_without_llm_comment`
  - no LLM comment -> no `_stage_problem_fallback` text.

### 7.2. Regression scenario

Использовать отчет Толегена за 4 июня 2026 как контрольный кейс:

- до правки было 9 `ДОГОВОРЕННОСТЬ`;
- после правки договоренности должны остаться только там, где LLM2 подтвердил
  `agreement` с evidence;
- строки вроде 1-секундной `ПОЛИЦЕЙСКАЯ СИРЕНА` не должны иметь статус
  `ДОГОВОРЕННОСТЬ`.

### 7.3. Pipeline smoke

После внедрения:

1. Прогнать report-only rebuild на уже готовых данных Толегена за 4 июня 2026.
2. Проверить PDF:
   - ложных договоренностей нет;
   - строки без LLM-статуса честно помечены;
   - верхняя математика не противоречит call-list.
3. Затем прогнать один полный manager_daily день в Telegram test only.

## 8. Критерии приемки

Задача считается выполненной, если:

1. В manager-facing отчете нет бизнес-статуса, который пришел только из
   deterministic resolver.
2. `business_outcome_resolver_visible_usage_count = 0`.
3. В `call_list_status_quality` нет policy
   `uses_valid_llm2_business_outcome_else_resolver_fallback`; новая policy:
   `llm_only_semantic_status`.
4. В строках без LLM-статуса виден нейтральный статус, а не выдуманный
   бизнес-исход.
5. Верхняя сводка дня отдельно показывает `СТАТУС НЕ ПОДТВЕРЖДЕН` для готовых
   анализов без безопасного LLM-статуса.
6. `СТАТУС НЕ ПОДТВЕРЖДЕН` не считается `Ошибка анализа` и не попадает в
   day-funnel exclusions.
7. Нет generic смысловых фраз, если LLM не дала corresponding content.
8. `semantic_status_quality=weak` не приводит к пустому отчету: usable
   LLM-статусы и LLM-комментарии отображаются, но без deterministic
   enrichment.
9. Report Layer diagnostics показывают, где LLM-смысл отсутствует или слабый.
10. Тест Толегена за 4 июня 2026 не показывает 9 договоренностей; остаются
   только LLM-подтвержденные договоренности.

## 9. Не делать в рамках этой задачи

- Не менять STT.
- Не менять LLM1 routing, кроме случаев, где явно нужно прокинуть уже
  существующее LLM-поле.
- Не добавлять UI.
- Не создавать отдельный runtime mode.
- Не возвращать скрытые блоки (`Голос клиента`) без отдельного согласования.
- Не удалять `BusinessOutcomeResolver`, если он нужен для diagnostics; но
  запретить его manager-facing использование.

## 10. Рекомендуемая последовательность реализации

1. Добавить diagnostics и feature-neutral helpers для LLM-only semantic status.
2. Перевести `call_list_status` / `final_manager_status` на LLM-only.
3. Отключить deterministic context fallback для manager-facing `Суть звонка`.
4. Отключить generic fallback в `Итог / обратная связь`.
5. Перевести tomorrow hotness/priority на LLM-only или missing state.
6. Отключить semantic fallbacks в Situation Day / stage comments / Call
   Breakdown.
7. Обновить документацию.
8. Прогнать unit tests.
9. Пересобрать отчет Толегена за 4 июня 2026 report-only и проверить
   договоренности.
