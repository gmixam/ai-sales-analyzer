# Pilot Backlog

Дата актуализации: 2026-06-12

## Назначение

Рабочий список задач этапа пилотирования MVP-1. Использовать этот файл как
оперативный backlog после закрытия основного pass по LLM2 / Report Layer /
delivery.

Связанные source of truth:

- `docs/ACTIVE_WORK_STATE.md` - короткое текущее состояние;
- `docs/PILOT_OPERATIONS.md` - ежедневный порядок запуска;
- `docs/MVP1_PILOT_METRICS_MEASUREMENTS.md` - KPI, замеры и стоимость;
- `docs/MANAGER_REPORT_FEEDBACK.md` - комментарии РОП/менеджеров по отчетам.
- `docs/MANAGER_DAILY_CALL_FEEDBACK_MINI_TZ.md` - draft мини-ТЗ по
  объяснению оценок в таблице звонков.
- `docs/LLM2_STATUS_DETAILS_MINI_TZ.md` - draft мини-ТЗ по статусным деталям
  звонка в `LLM2D`.
- `TMP_PILOT14_EDO_SCOPE_SCORING_TZ.md` - временное ТЗ и реализация первого
  pass по рамкам оценки ЭДО.
- `docs/PILOT18_BALANCED_COACHING_TZ.md` - draft мини-ТЗ по balanced coaching
  и ответственности LLM2D за важность рекомендации.
- `docs/PILOT20_FULL_REPORT_COVERAGE_AUDIT_TZ.md` - ТЗ фазы 1 по аудиту
  покрытия анализа до `full_report`.
- `docs/PILOT22_MANAGER_DAILY_STRICT_REPORT_DAY_TZ.md` - ТЗ по запрету
  подмешивания прошлых дней в менеджерский daily-отчет.
- `docs/PILOT23_MANAGER_DAILY_COMPACT_SUMMARY_TZ.md` - draft мини-ТЗ по
  сокращению служебного текста в верхнем блоке и `БАЛЛЫ ПО ЭТАПАМ`.

## Правило работы

1. Сначала чинить надежность дневного пилотного контура: данные, расписание,
   математика отчета, применимость этапов.
2. Затем добавлять операционную доставку для РОП.
3. Weekly/monthly отчеты делать после стабильной daily-механики.
4. Скрытые блоки возвращать по одному и только при наличии доказуемых данных.
5. Комментарии менеджеров не чинить вручную в PDF. Сначала занести их в
   `docs/MANAGER_REPORT_FEEDBACK.md`, проверить данные, затем при системной
   причине добавить или обновить задачу в этом backlog.
6. После каждого полуавтоматического прогона выполнять post-run audit по
   `docs/PILOT_OPERATIONS.md#post-run-audit`. Если аномалия/ошибка не
   исправлена сразу, добавить ее в раздел `Operational findings` ниже и
   привязать к существующей задаче или создать новую `PILOT-*`.

## Очередность работ

### P1 - Надежность дневного пилота

Цель: каждый дневной прогон должен давать проверяемые цифры и понятный статус
до отправки менеджерам или РОП.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-01 | Bitrix manager sync preflight | `done` | Добавлен CLI `core/report_scripts/bitrix_manager_sync_preflight.py`: выбирает отдел по id/name, запускает `BitrixManagerMapper.sync_department_directory`, печатает active/inactive, email, extension, Bitrix ID, added/deactivated и warnings | Проверено на `[ЭДО] Отдел Продаж` (`472cda28-ce71-494c-9068-25d3ffbf7399`): `synced=6`, `deactivated=7`, active managers email OK, warning только `active_manager_missing_extension:Робот Договор24`; `--help` проверен в контейнере через temporary copy |
| PILOT-02 | Проверка расписания без UI | `baseline_done` | Добавлен CLI `core/report_scripts/scheduled_reporting_preflight.py` с командами `status`, `scan-due`, `create`, `approve`; проверены `status` и безопасный `scan-due` без UI | Текущий факт: активных schedules нет, `scan-due` вернул `processed_count=0`; в review queue есть старые batches Manual Live Validation. Полную цепочку create -> draft -> approve/delivery нужно проверять отдельным controlled schedule на пилотный отдел |
| PILOT-03 | Математика первого блока | `done` | `selection_model` разделяет day-funnel exclusions (`too_short`, `ivr`) и processing/coaching reasons (`support`, `not_enough_analysis`, `not_selected`); `not_enough_analysis` считается только по содержательным звонкам; DOCX/PDF note больше не называет отсутствие анализа причиной исключения из списка дня | Контейнерный focused pytest: `/app/tests/test_manual_reporting.py -k "selection_model or sm2_too_short or sm4 or render_report_email_uses_short_body"` -> `13 passed`; `py_compile` и `node --check scripts/generate_docx_report.js` -> OK |
| PILOT-04 | Применимость этапов в `БАЛЛЫ ПО ЭТАПАМ` | `done` | `applicable=false` критерии больше не создают `score_by_stage` в LLM2 adapter и не попадают в дневную агрегацию persisted `score_by_stage`; слабые наблюдаемые этапы с `applicable=true, score=0` остаются в расчете | Контейнерный focused pytest: `/app/tests/test_llm2_layered_analysis.py /app/tests/test_manual_reporting.py -k "non_applicable_criteria or stage_scores_use_all_ready or stage_scores_ignore_non_dict or stage_scores_expose_low_coverage"` -> `5 passed` |
| PILOT-12 | Видимый список звонков только по готовым разборам | `done` | В `ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ` показывать только звонки с готовым неошибочным анализом; верхняя воронка остается по всему дню и отдельно показывает содержательные звонки без готового разбора | Проверено на Толегене 2026-06-03: воронка `38 / 24 / 14`, строк в таблице `14`, payload сохраняет `24` содержательных и `14` ready-analysis rows; Telegram test delivery `message_id=395`; focused pytest `19 passed` |
| PILOT-13 | ФИО контакта в `Контактах` и merged call list | `implemented_first_pass` | ТЗ: [`docs/PILOT13_CONTACT_NAME_SOURCE_TZ.md`](PILOT13_CONTACT_NAME_SOURCE_TZ.md). First pass внедрен: analyzer не prefill-ит `contact_name` из metadata, LLM input очищается от name-полей, prompt требует имя только из STT, Report Layer/composer не извлекают и не fallback-ят ФИО из STT/Bitrix/telephony metadata | Focused tests: 5 PILOT-13 tests passed, 6 subtests passed. Следующий шаг: controlled rerender свежего manager_daily отчета и визуальная проверка `Контакт`, `РАЗБОР ЗВОНКА`, `ГОЛОС КЛИЕНТА`, `КОНТАКТЫ В РАБОТУ` |
| PILOT-17 | LLM-only semantic reporting | `implemented_first_pass` | Первый pass внедрен по `docs/LLM_ONLY_SEMANTIC_REPORTING_TZ.md`: manager-facing `call_list_status` / `final_manager_status` берутся только из `scores_detail.status_details.status` или `report_evidence.business_outcome.status`; `BusinessOutcomeResolver` оставлен diagnostic-only; отсутствие LLM-статуса отображается как `Статус не подтвержден`; верхняя сводка/email получили отдельный счетчик; `agreement` без LLM action anchor + evidence уходит в `agreement_missing_evidence` | Focused проверки прошли. Следующий шаг - контрольный rerender/прогон Толегена за 2026-06-04: false `Договорённость` из resolver fallback должна исчезнуть; payload должен показывать `missing_llm_semantic_status` / `agreement_missing_evidence`, `business_outcome_resolver_visible_usage_count=0`, `status_not_confirmed_*` counters |
| PILOT-20 | Повышение покрытия анализа до `full_report` | `implemented_first_pass` | Фаза 1 выполнена по `docs/PILOT20_FULL_REPORT_COVERAGE_AUDIT_TZ.md`; audit package: `review_packages/pilot20_full_report_coverage_audit_2026-06-04_2026-06-05/`. First pass фазы 2 внедрен: `_evaluate_manager_daily_readiness` считает `full_report` coverage по содержательным звонкам (`meaningful_ready_analysis_total / meaningful_calls_total`), raw coverage сохранен как диагностика | Проверено focused tests: readiness/group-result `6 passed`, selection_model `9 passed`, `py_compile` и `git diff --check` OK. Следующий шаг: controlled rerender/ready-only проверка на реальных отчетах; `llm2_admission_non_commercial_or_unusable` пока не чинить, а фиксировать на новых звонках |
| PILOT-21 | `КОНТАКТЫ В РАБОТУ` в `signal_report` | `new` | Во время PILOT-20 sweep найден соседний дефект: `test_signal_report_model_uses_manager_facing_polish_rules` падает, потому что `call_tomorrow.rows` пустой в `signal_report`, хотя тест ожидает 1 hot contact. Нужно разобрать, это устаревший тест после LLM-only/status gates или реальный regression в сборке `call_tomorrow` для сигнального отчета | Сначала провести bounded audit без правок: воспроизвести fixture, проверить `payload.call_tomorrow.contacts`, `selection_diagnostics`, `call_tomorrow_quality`, source final status/evidence. Затем либо обновить устаревшее ожидание теста, либо исправить `_build_call_tomorrow` / render path так, чтобы только доказанные контакты попадали в блок |
| PILOT-22 | Строгий отчетный день в `manager_daily` | `implemented_first_pass` | ТЗ: [`docs/PILOT22_MANAGER_DAILY_STRICT_REPORT_DAY_TZ.md`](PILOT22_MANAGER_DAILY_STRICT_REPORT_DAY_TZ.md). Внедрено: `manager_daily` строит только окно report day (`window_days_used=1`), `skip_accumulate` не получает прошлые artifacts, business email блокируется `strict_report_day_gate`, если period/window расширился или `included_in_report_total > meaningful_calls_total` | Проверено focused pytest: strict-day group result, expanded-window email safety, normal full_report path -> `3 passed`. Следующий шаг: controlled rerender Тимура за `2026-06-11`: отчет и письмо должны быть строго за `2026-06-11`, без `10-11 июня`; при `1` содержательном и `0` готовых разборах текст не должен показывать `в разбор вошло — 18` |
| PILOT-23 | Компактный верхний блок и краткие пояснения | `implemented_first_pass` | ТЗ: [`docs/PILOT23_MANAGER_DAILY_COMPACT_SUMMARY_TZ.md`](PILOT23_MANAGER_DAILY_COMPACT_SUMMARY_TZ.md). First pass внедрен: сокращены selection/header note, email summary, строка `Статусы без разбора` и scope note в `БАЛЛЫ ПО ЭТАПАМ`; расчеты readiness/selection/scoring не менялись | Focused pytest `7 passed`, `py_compile`, `node --check scripts/generate_docx_report.js`, `git diff --check` OK. Следующий шаг: controlled rerender Толегена за `2026-06-11` и визуальная проверка верхнего блока/`БАЛЛЫ ПО ЭТАПАМ`; после подтверждения перевести в `done` |

### P2 - Ежедневный отчет для РОП

Цель: РОП каждый день получает одну управленческую сводку по менеджерам с
приложенными manager_daily PDF.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-05 | `rop_daily_digest` | `planned` | Добавить ежедневный email для РОП: сводка по менеджерам, статусы прогонов, кому отправлено, основные blockers; приложить PDF отчетов менеджеров | Один email РОП содержит 2-3 manager_daily PDF attachments и корректный текстовый summary |

### P3 - Расписание и delivery gate

Цель: ежедневный пилот можно вести по расписанию, но бизнес-доставка остается
под контролем оператора.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-06 | Scheduled daily operating flow | `planned` | Перевести проверенный scheduled flow в понятный Codex/CLI порядок: что запланировано, что готово к review, что approve, что delivered/failed | Codex по запросу может показать состояние расписания и выполнить approve/delivery без UI |

### P4 - Отчеты РОП weekly/monthly

Цель: после стабильных daily-данных дать РОП недельную и месячную управленческую
картину.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-07 | `rop_weekly` pilot-ready | `planned` | Довести существующий persisted-only weekly preset: проверить payload, шаблон, delivery, читаемость выводов и связи с daily reports | Weekly строится только из готовых persisted данных, отправляется РОП после review, не запускает STT/LLM |
| PILOT-08 | `rop_monthly` design/preset | `planned` | Спроектировать monthly как следующий preset на базе weekly/daily: динамика, KPI, GO/NO-GO, системные проблемы, решения РОП | Есть утвержденный контракт monthly и минимальный первый отчет без запуска новых анализов |

### P5 - Возврат скрытых блоков

Цель: постепенно вернуть полезные блоки без потери доверия к отчету.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-09 | `Голос клиента` | `planned` | Вернуть блок только при наличии реальных клиентских сцен/сигналов; пустой блок по-прежнему скрывать | В PDF блок появляется только с доказуемыми сигналами и не показывает placeholder |
| PILOT-10 | `Утренняя карточка` | `planned` | Сначала вернуть как Telegram/ROP-внутренний формат, не как обязательный блок manager PDF | Утренняя карточка не раздувает PDF менеджера и может быть отправлена отдельно |
| PILOT-11 | `Деньги на столе` | `deferred` | Возвращать только после CRM-ready или другого доказуемого источника суммы/сделки | Нет выдуманного потенциала по среднему чеку без доказательства |

### P6 - Справедливость оценки по роли менеджера

Цель: отчет не должен оценивать менеджера ЭДО по продажным критериям там, где
правильное действие - передать клиента, решить сервисный вопрос или не вести
продажу по продукту вне зоны ответственности.

| ID | Задача | Статус | Что сделать | Проверка результата |
| --- | --- | --- | --- | --- |
| PILOT-14 | Рамки обязанностей менеджера ЭДО | `implemented_first_pass` | Реализован первый pass по `TMP_PILOT14_EDO_SCOPE_SCORING_TZ.md`: `LLM2A` формирует `edo_scope`, `LLM2B` использует его для применимости sales scoring, `LLM2D` учитывает scope в рекомендациях, adapter сохраняет `scores_detail.edo_scope`, Report Layer только отображает/считает scope и не штрафует `none/unclear` как продажи | Focused проверки пройдены: LLM2 layered/runtime `23 passed, 2 subtests passed`; report regression `PILOT-14` passed. Следующий шаг - проверить на реальном LLM2/Report прогоне: звонки техподдержки/юр-направления не получают sales-push, `БАЛЛЫ ПО ЭТАПАМ` считают только применимые звонки/этапы |
| PILOT-15 | Объяснение оценок в таблице звонков | `implemented_first_pass` | Реализован первый pass по мини-ТЗ `docs/MANAGER_DAILY_CALL_FEEDBACK_MINI_TZ.md`: из существующих `scores_detail.strengths/gaps/recommendations/criteria_results` собирается `call_feedback_summary`, 4-я колонка стала `Итог / обратная связь`, новых LLM-вызовов и изменения scoring нет. Feedback Толегена: формат эффективен | Нужно проверить второй pass по тону: не натягивать улучшения там, где нет доказанного gap; focused tests passed, DOCX smoke подтвердил новый заголовок |
| PILOT-16 | Статусные детали звонка в LLM2D | `implemented_first_pass` | Внедрен первый pass по мини-ТЗ `docs/LLM2_STATUS_DETAILS_MINI_TZ.md`: `LLM2D` prompt/contract и compact payload знают `status_details`, adapter сохраняет блок в `scores_detail`, simulation возвращает deterministic структуру, Report Layer строит короткий `Итог` из status-specific mini-structure при совпадении статуса | Нужно проверить на реальном LLM2/LLM2D прогоне: у договоренностей должна появиться конкретика “о чем договорились”; старые анализы без LLM status details после PILOT-17 должны давать нейтральное состояние или использовать только другой valid LLM semantic source |
| PILOT-18 | Balanced coaching без forced improvement | `implemented_first_pass` | Реализован first pass по `docs/PILOT18_BALANCED_COACHING_TZ.md`: `LLM2D` contract/runtime возвращает `coaching_decision` с `improve|maintain|no_comment`, adapter сохраняет `scores_detail.coaching_decision`, Report Layer отображает `Улучшить` только при `improve`, `Поддерживать/Корректно` при `maintain`, ничего не добавляет при `no_comment`; дневная агрегация не берет legacy recommendations, если LLM2D уже дала `no_comment` | Focused проверки пройдены: LLM2 layered/runtime + report regressions `31 passed, 2 subtests passed`; `git diff --check`, `py_compile`, `node --check` OK. Следующий шаг - контрольный LLM2/Report rerender на реальных звонках Толегена/Алишера и review PDF |
| PILOT-19 | Прозрачность методики scoring для менеджера | `planned` | Добавить понятное объяснение, как считаются `Балл дня` и `БАЛЛЫ ПО ЭТАПАМ`: какие звонки оцениваются, что значит `Оценено`, как применимость этапов влияет на расчет, почему звонок/этап мог не попасть в балл | На отчете Тимура менеджер видит, что именно считается и почему; `БАЛЛЫ ПО ЭТАПАМ` не выглядит как черный ящик |

## Feedback intake

Комментарии РОП/менеджеров проходят через `docs/MANAGER_REPORT_FEEDBACK.md`.

Если комментарий повторяется или подтверждает системную проблему, обновить
соответствующую задачу в этом файле:

| Feedback ID | Связанная задача | Статус связи | Комментарий |
| --- | --- | --- | --- |
| 2026-06-05-Алишер-01 | PILOT-14 | `implemented_first_pass` | Менеджер просит учитывать границы обязанностей ЭДО: юр-направление и техподдержка не должны оцениваться как непроданная продажа. Первый pass внедрен, нужен контрольный реальный прогон |
| 2026-06-05-Алишер-02 | PILOT-15 | `implemented_first_pass` | Менеджеру не хватает объяснения, почему выставлены оценки; первый pass внедрен, следующий шаг - review контрольного PDF |
| 2026-06-05-Толеген-01 | PILOT-17 | `implemented_first_pass` | У Толегена за 2026-06-04 появились false `Договорённость` из resolver fallback при отсутствии LLM-подтверждения через `business_outcome` / `status_details`. Первый pass закрывает resolver fallback для видимого статуса; нужна контрольная проверка на rerender/прогоне |
| 2026-06-05-Толеген-02 | PILOT-15 | `positive_feedback` | Менеджер считает правки по `Итог / обратная связь` эффективными |
| 2026-06-05-Толеген-03 | PILOT-18 | `implemented_first_pass` | Не везде есть целесообразность натягивать “что улучшить”; нужен balanced coaching. First pass внедрен: `LLM2D` выбирает `improve/maintain/no_comment`; Report Layer не достраивает рекомендацию, `LLM3` только компонуeт уже данные LLM2-сигналы |
| 2026-06-05-Тимур-01 | PILOT-19 | `new` | Баллы вызывают вопросы, потому что непонятно, как считается и что считается |
| 2026-06-12-Толеген-01 | PILOT-23 | `implemented_first_pass` | В отчете за `2026-06-11` верхний блок и `БАЛЛЫ ПО ЭТАПАМ` слишком многословны и дублируют объяснение механизма. First pass внедрен, нужна визуальная проверка на rerender отчета |

## Operational findings

| Finding ID | Связанная задача | Статус связи | Наблюдение |
| --- | --- | --- | --- |
| 2026-06-09-coverage-01 | PILOT-20 | `new` | Полный прогон Тимура, Толегена и Алишера за `2026-06-05` завершился доставкой отчетов, но runner status=`partial`, все 3 отчета readiness=`signal_report`: Алишер `analysis_coverage=57.1%` (`4/7`), Тимур `33.3%` (`6/18`), Толеген `41.3%` (`19/46`). В prepared artifacts: `analyses_built=35`, `analyses_reused=66`, `analyses_rejected_for_reuse=17` в build-run и `23` rejected в ready-only delivery-run. Это нужно разобрать как отдельный критичный слой надежности дневного пилота. |
| 2026-06-10-call-tomorrow-01 | PILOT-21 | `new` | После first pass PILOT-20 широкий focused sweep `/app/tests/test_manual_reporting.py -k "manager_daily_readiness or manager_daily_group_result or selection_model or full_report or signal_report"` дал 1 failure: `test_signal_report_model_uses_manager_facing_polish_rules`, `IndexError` на `sections["call_tomorrow"]["rows"][0]`. Это соседний defect/устаревшее ожидание блока `КОНТАКТЫ В РАБОТУ`, не denominator readiness. |
| 2026-06-11-coverage-10jun-01 | PILOT-20 | `observed` | Полный прогон Алишера, Тимура и Толегена за `2026-06-10` завершился доставкой всех 3 отчетов в Telegram и email, но runner status=`partial` из-за неполного анализа. Readiness: Алишер `signal_report` (`2/2` meaningful-ready, raw `50.0%`), Тимур `full_report` (`16/19`, `84.2%`), Толеген `full_report` (`21/24`, `87.5%`). На самом дне 6 failed-анализов, все `llm2_admission_non_commercial_or_unusable` (Тимур 3, Толеген 3); это не provider/quota failure, а зона наблюдения admission gate в рамках PILOT-20. |
| 2026-06-12-coverage-11jun-01 | PILOT-20 / PILOT-22 | `observed` | Полный прогон Алишера, Тимура и Толегена за `2026-06-11` завершился доставкой email всем 3 менеджерам, но runner status=`partial`, все отчеты `signal_report`: Алишер `3/7` meaningful-ready (`42.9%`), Тимур `0/1` (`0.0%`), Толеген `9/15` (`60.0%`). Все 11 failed-анализов за целевой день имеют `llm2_admission_non_commercial_or_unusable`; provider/quota ошибок нет. Дополнительная аномалия: отчет Тимура ушел с расширенным окном `2026-06-10 - 2026-06-11` и некорректной строкой письма `Из 1 содержательных ... в коучинговый разбор вошло — 18`. Решение пользователя: manager-facing daily не должен подмешивать прошлые дни; фиксируется как `PILOT-22`. |

## Следующий рекомендуемый шаг

Начать с P1:

1. PILOT-20 - controlled rerender/ready-only проверка на реальных отчетах после
   denominator fix: убедиться, что отчеты с высоким coverage содержательных
   звонков больше не остаются `signal_report` только из-за normal exclusions.
2. PILOT-22 - controlled rerender после first pass: проверить Тимура за
   `2026-06-11`, что отчет и письмо отражают только выбранный день, даже если
   данных мало.
3. PILOT-23 - controlled rerender после first pass: проверить Толегена за
   `2026-06-11`, что верхний блок и `БАЛЛЫ ПО ЭТАПАМ` стали компактными без
   изменения цифр.
4. PILOT-21 - bounded audit `call_tomorrow` в `signal_report`: понять, это
   устаревший тест или реальный дефект блока `КОНТАКТЫ В РАБОТУ`.
5. PILOT-17 - контрольный rerender/прогон после first pass, потому что false
   `Договорённость` напрямую бьет по доверию к отчету.
6. PILOT-19 - прозрачность scoring, потому что менеджеры должны понимать,
   какие звонки и критерии реально вошли в баллы.
7. PILOT-13 - ФИО контакта, чтобы Report Layer не пытался достраивать имя.
8. PILOT-02 / PILOT-06 - controlled schedule flow без UI.

После закрытия P1 переходить к `rop_daily_digest`.
