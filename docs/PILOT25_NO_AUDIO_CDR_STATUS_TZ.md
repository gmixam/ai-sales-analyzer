# PILOT-25: no-audio CDR status in split upstream

Дата: 2026-06-16

Статус: `implemented_first_pass`

## Контекст

Первый unattended `call_processing.ensure_daily_upstream` за `2026-06-15`
нашел `91` OnlinePBX interaction в pilot scope и построил `50` STT/LLM1.
Оставшиеся `41` записи не являются STT-failure:

- `source_status=missed`;
- `duration_sec=0`;
- `raw_ref` пустой;
- active `transcript` artifact отсутствует;
- failed `transcript` artifacts нет.

Разбивка за `2026-06-15`:

| source_status | всего | STT ready | STT missing |
| --- | ---: | ---: | ---: |
| `answered` | 50 | 50 | 0 |
| `missed` | 41 | 0 | 41 |

Проблема: split upstream сохраняет targeted CDR через
`OnlinePBXIntake.save_interactions(targeted)`, а `save_interactions()` всем
новым interaction ставит `status="ELIGIBLE"`. Старый путь
`filter_eligible(records)` в этом split-path не применяется. Поэтому
`ELIGIBLE` сейчас означает "сохранено как interaction", а не "пригодно для
STT/downstream".

## Цель

Разделить технические состояния:

- звонок найден в телефонии и нужен для дневной воронки;
- звонок пригоден для STT/LLM1/downstream;
- звонок является CDR-only/no-audio и не должен создавать missing transcript
  requirements.

Это не LLM-задача и не смысловая классификация звонка. Это техническая
классификация доступности аудио.

## Требования

### 1. Не удалять no-audio CDR из базы

`missed`, `duration=0`, `raw_ref` empty записи должны сохраняться как
interactions, чтобы дневная воронка могла показать:

- найдено в телефонии;
- исключено из списка дня;
- причина исключения: missed / без записи / без речи.

Нельзя просто фильтром выкинуть такие CDR до сохранения.

### 2. Не маркировать no-audio как `ELIGIBLE`

Для новых interactions:

- `answered` + `talk_duration > 0` + есть или можно получить запись -> оставить
  `ELIGIBLE`;
- `missed` / `talk_duration=0` / нет записи -> ставить отдельный технический
  статус, например `NO_AUDIO` или `CDR_ONLY`.

Выбор имени статуса должен быть один и последовательный по коду. Предпочтение:
`NO_AUDIO`, потому что причина downstream-blocker понятна оператору.

### 3. Split call-processing не должен считать no-audio как missing STT

`CallProcessingService._find_interactions(...)` или artifact planning должен
исключать `NO_AUDIO` из requirements для:

- `transcript`;
- `transcript_segments`;
- `llm1_first_pass`.

Иначе scheduled upstream снова будет `partial` из-за записей, по которым
физически нечего транскрибировать.

### 4. Report Layer должен видеть no-audio в дневной воронке

Дневной отчет должен по-прежнему учитывать `NO_AUDIO` в "найдено в телефонии" и
"исключено из списка дня". Но такие звонки не должны попадать в:

- содержательные звонки;
- STT coverage denominator;
- analysis coverage denominator;
- "без готового разбора" как будто это технический долг анализа.

Если текущий selection model уже классифицирует `duration=0 + no transcript`
как `too_short_or_no_speech`, нужно убедиться, что новый статус не ломает это
поведение.

### 5. Backfill/cleanup для уже созданных записей

Для уже сохраненных 41 interaction за `2026-06-15` можно сделать bounded
operator migration/update:

- условие: `status='ELIGIBLE'`, `metadata.source_status='missed'`,
  `duration_sec=0`, `raw_ref` пустой, active transcript artifact отсутствует;
- новое состояние: `NO_AUDIO`;
- не удалять records и не создавать failed transcript artifacts.

Перед фактическим update показать dry-run count.

## Где смотреть код

- `core/app/agents/call_processing/service.py`
  - `_discover_source_calls(...)`;
  - `_record_matches_filters(...)`;
  - `_record_is_build_eligible(...)`;
  - `_find_interactions(...)`;
  - `_ensure_artifacts(...)`.
- `core/app/agents/calls/intake.py`
  - `filter_eligible(...)`;
  - `save_interactions(...)`;
  - `_normalize_http_api_record(...)`.
- `core/app/core_shared/workers/tasks.py`
  - `_daily_upstream_scope(...)`;
  - `ensure_daily_call_processing_upstream(...)`.
- `core/app/agents/calls/reporting.py`
  - selection model / meaningful-call classification / no-transcript buckets.

## Acceptance

На свежем split upstream day:

- `answered` calls с аудио получают `ELIGIBLE`, STT и LLM1;
- `missed` / `duration=0` calls сохраняются как `NO_AUDIO`;
- no-audio calls не создают `missing transcript` requirements;
- upstream status не становится `partial` только из-за no-audio CDR;
- дневная воронка включает no-audio в "найдено" и "исключено";
- report не показывает no-audio как "нет готового разбора".

На данных `2026-06-15` после bounded cleanup:

- `50` answered остаются STT-ready;
- `41` missed/no-audio имеют технический статус `NO_AUDIO`;
- active transcript artifacts остаются только `ready`, failed STT не создается.

## Test Plan

- Unit test: split source discovery сохраняет `missed/talk_duration=0` как
  `NO_AUDIO`, но сохраняет запись.
- Unit test: `answered/talk_duration>0` с доступной записью остается
  `ELIGIBLE`.
- Unit test: artifact planning не создает transcript/segments/LLM1 requirements
  для `NO_AUDIO`.
- Reporting test: no-audio входит в day funnel exclusions, но не входит в
  meaningful/analyzed denominators.
- SQL dry-run check для cleanup existing `2026-06-15` rows.

## Implementation notes

- Scope A / call-processing:
  - `OnlinePBXIntake.save_interactions(...)` теперь классифицирует source CDR
    в `ELIGIBLE` или `NO_AUDIO`;
  - `missed`, `talk_duration=0` и записи без downstream audio сохраняются как
    `NO_AUDIO`;
  - answered call, для которого есть или получена recording URL, остается
    `ELIGIBLE`;
  - source discovery больше не запрашивает recording URL для
    `talk_duration <= 0`;
  - `CallProcessingService` не создает `transcript`,
    `transcript_segments` и `llm1_first_pass` requirements для `NO_AUDIO`.
- Scope B / Report Layer: текущее поведение selection model уже исключает
  `status=NO_AUDIO`, `duration_sec=0`, пустой transcript как
  `too_short_or_no_speech`.
- `NO_AUDIO` учитывается в `raw_calls_total` и `excluded_calls_total`, но не
  входит в `meaningful_calls_total`, `meaningful_ready_analysis_total`,
  `analyzed_calls_total` / `included_in_report_total` и не увеличивает
  `not_enough_analysis`.
- Добавлен focused regression test; изменение `reporting.py` не требуется.
- External-service source summary обновлен: `targeted_source_records_total`
  берет полный `source_targeted_total` из call-processing, чтобы no-audio CDR
  не терялись из source observability.
- SQL dry-run cleanup для pilot scope за `2026-06-15` показывает `41`
  candidate row для перевода из `ELIGIBLE` в `NO_AUDIO`; фактический update
  пока не выполнялся.

## Не делать

- Не удалять missed/no-audio звонки из `interactions`.
- Не передавать no-audio в STT.
- Не решать это через LLM.
- Не менять бизнес-смысл статусов звонка в Report Layer.
- Не включать business email/ручной прогон как часть этой задачи.
