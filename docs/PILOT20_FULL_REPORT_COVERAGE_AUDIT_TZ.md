# PILOT-20: Audit of Analysis Coverage to Full Report

Дата: 2026-06-10
Статус: phase_2_implemented_first_pass / awaiting controlled rerender
Связанная задача: `docs/PILOT_BACKLOG.md` -> `PILOT-20`

## 1. Контекст

В пилотных дневных прогонах отчеты часто доставляются как `signal_report`, а
не как `full_report`. Это не всегда означает поломку отчета: часть звонков
может быть короткой, без речи, без STT или осознанно исключенной. Но сейчас
нужно точно понимать, где теряется покрытие анализа и какие причины являются
нормальными, а какие мешают полноценному дневному отчету.

Пример контрольного прогона Толегена за `2026-06-04`:

- `raw_calls_total=52`;
- `meaningful_calls_total=24`;
- `meaningful_ready_analysis_total=23`;
- report readiness: `signal_report`;
- `analysis_coverage=44.2%` по readiness scope;
- `28` звонков исключены как `too_short_or_no_speech`;
- `1` содержательный звонок не вошел в коучинговый разбор из-за отсутствия
  готового разбора;
- runner status=`partial`, но manager report был доставлен.

Задача `PILOT-20` нужна, чтобы перестать смотреть только на общий статус
`partial/signal_report` и получить понятную математику по каждому менеджеру и
дню.

## 2. Цель фазы 1

Сделать аудит покрытия без изменения механизма.

Фаза 1 должна ответить:

1. Сколько звонков найдено в телефонии.
2. Сколько звонков корректно исключено из списка дня.
3. Сколько звонков имеют STT.
4. Сколько звонков имеют готовый пригодный анализ.
5. Сколько звонков не дошли до анализа и почему.
6. Почему отчет получил `signal_report`, а не `full_report`.
7. Какие причины требуют исправления механизма, а какие являются нормальными
   исключениями.

Важно: на этой фазе не менять LLM prompts, admission rules, selection rules,
rendering и delivery. Только читать run artifacts / DB / observability и
готовить диагностический вывод.

## 3. Scope аудита

Первый рекомендуемый scope:

- менеджеры: Толеген, Тимур, Алишер;
- даты: `2026-06-04` и `2026-06-05`;
- основной отдел: `[ЭДО] Отдел Продаж`
  (`472cda28-ce71-494c-9068-25d3ffbf7399`);
- режимы: использовать уже сохраненные результаты прогонов и/или
  `report_from_ready_data_only` без business delivery.

Если данных по одному из менеджеров/дней недостаточно, аудит должен явно
зафиксировать `data_missing`, а не достраивать выводы предположениями.

## 4. Что нужно собрать по каждому manager-day

### 4.1. Верхняя математика

| Поле | Что означает | Источник |
| --- | --- | --- |
| `date` | дата отчета | run result / filters |
| `manager_id` | id менеджера | run result / DB |
| `manager_name` | имя менеджера | run result / DB |
| `runner_status` | верхний статус запуска | run result |
| `readiness_outcome` | `full_report`, `signal_report`, `blocked`, etc. | payload/meta/readiness или diagnostics |
| `readiness_reason_codes` | причины readiness | payload/meta/readiness |
| `raw_calls_total` | найдено в телефонии за день | `selection_model` / source funnel |
| `meaningful_calls_total` | содержательные звонки дня | `selection_model` |
| `excluded_calls_total` | исключено из списка дня | `selection_model` |
| `transcript_calls_total` | звонки с STT | `selection_model` |
| `no_transcript_calls_total` | звонки без STT | `selection_model` |
| `meaningful_ready_analysis_total` | содержательные звонки с готовым анализом | `selection_model` |
| `included_in_report_total` | вошло в коучинговый разбор / visible report core | `selection_model` |
| `analysis_coverage` | coverage из readiness | readiness diagnostics |

### 4.2. Причины исключений и непокрытия

Собрать счетчики:

| Группа | Reason codes |
| --- | --- |
| Корректные day exclusions | `too_short_or_no_speech`, `ivr_or_autoanswer` |
| Нет STT | `no_transcript`, `missing_transcript`, source records без audio/STT |
| Нет анализа | `not_enough_analysis`, `analysis_missing` |
| Анализ есть, но не переиспользован | `analysis_reuse_rejected`, `analyses_rejected_for_reuse`, `analysis_reuse_rejected:*` |
| LLM2 admission rejected | `llm2_admission_non_commercial_or_unusable` |
| Ошибка анализа | `analysis_failed`, `provider_error`, `quota`, `timeout`, `invalid_json`, `contract_invalid` |
| Версионный mismatch | `analyses_rejected_for_instruction_version`, instruction/version mismatch |

### 4.3. Примеры звонков

По каждой ненулевой проблемной причине дать до 5 примеров:

- `interaction_id`;
- время звонка в `UTC+5`;
- длительность;
- есть ли transcript;
- есть ли analysis;
- последний `analysis_id`, если есть;
- instruction version;
- reason code;
- короткий комментарий аудитора.

Не нужно включать полный transcript в аудитный отчет.

## 5. Классификация причин

Каждую причину нужно отнести к одному из классов:

| Класс | Описание | Что делать дальше |
| --- | --- | --- |
| `normal_exclusion` | звонок корректно не должен анализироваться | не чинить, только считать |
| `technical_gap` | STT/analysis отсутствует или не переиспользован по технической причине | предложить дозаполнение или fix механизма |
| `semantic_admission_gap` | LLM2/admission исключил звонок как непригодный, но нужно проверить бизнес-смысл | вынести в ручной review sample |
| `versioning_gap` | артефакт есть, но не подходит по версии/политике reuse | предложить rebuild/reuse policy decision |
| `unknown_gap` | причина не ясна из artifacts | добавить в backlog как diagnostic gap |

## 6. Ожидаемый артефакт фазы 1

Создать один audit summary в `review_packages/` или вывести в чат по запросу.
Если создается файл, рекомендуемый путь:

```text
review_packages/pilot20_full_report_coverage_audit_<date_or_range>/
  audit_summary.md
  audit_summary.json
```

Markdown должен содержать:

1. Executive summary.
2. Таблицу manager-day coverage.
3. Breakdown причин по manager-day.
4. Top blockers to `full_report`.
5. Примеры звонков по причинам.
6. Рекомендации для фазы 2.

JSON должен быть machine-readable и содержать те же счетчики.

## 7. Что не делать в фазе 1

- Не менять prompts `LLM1/LLM2/LLM3`.
- Не менять admission rules.
- Не менять selection model.
- Не менять report rendering.
- Не запускать business delivery менеджерам.
- Не считать все `signal_report` ошибкой.
- Не объединять короткие/no-speech звонки с содержательными звонками без
  анализа.

## 8. Acceptance Criteria

Фаза 1 считается выполненной, если:

- для каждого выбранного manager-day видно, почему readiness не `full_report`;
- `normal_exclusion` отделен от реальных gaps;
- есть список top blockers, отсортированный по влиянию на coverage;
- есть примеры звонков по каждой проблемной причине;
- можно принять решение, какие исправления делать в фазе 2;
- аудит не менял production/runtime artifacts, кроме создания audit package.

## 9. Предварительные гипотезы для проверки

Проверить, но не считать доказанным до аудита:

1. Часть `signal_report` вызвана нормальными короткими/no-speech звонками,
   которые не должны попадать в анализ.
2. Часть coverage теряется из-за `analysis_reuse_rejected` и старых/неподходящих
   анализов.
3. Часть звонков имеет STT, но не имеет готового LLM2 анализа.
4. Часть звонков отбрасывается как
   `llm2_admission_non_commercial_or_unusable`, и это может быть как корректно,
   так и спорно.
5. Readiness coverage может считать более широкий `relevant_calls`, чем
   manager-facing `meaningful_calls_total`, поэтому нужна явная расшифровка
   denominator.

## 10. Следующий шаг после фазы 1

После аудита дополнить это ТЗ разделом `Фаза 2: Исправления`, где для каждой
подтвержденной причины будет выбран один из вариантов:

- дозаполнить STT;
- дозаполнить LLM2 analysis;
- пересобрать rejected/stale analyses;
- уточнить reuse policy;
- вынести admission спорные звонки в review sample;
- изменить readiness denominator или диагностику, если текущая математика
  вводит в заблуждение.

## 11. Результат фазы 1

Артефакты аудита:

- `review_packages/pilot20_full_report_coverage_audit_2026-06-04_2026-06-05/audit_summary.md`;
- `review_packages/pilot20_full_report_coverage_audit_2026-06-04_2026-06-05/audit_summary.json`;
- mirror из контейнера:
  `core/review_packages/pilot20_full_report_coverage_audit_2026-06-04_2026-06-05/`.

Scope:

- менеджеры: Толеген, Тимур, Алишер;
- даты: `2026-06-04`, `2026-06-05`;
- отдел: `[ЭДО] Отдел Продаж`
  (`472cda28-ce71-494c-9068-25d3ffbf7399`).

Метод:

- использованы persisted DB artifacts и внутренний artifact preparation в
  ready-only режиме;
- STT, LLM1, LLM2, LLM3, render и delivery не запускались;
- business delivery менеджерам/РОП не выполнялась.

Основные выводы:

1. У всех `6/6` manager-day `meaningful coverage >= 75%`, но technical
   readiness coverage `< 75%`.
2. Причина расхождения: readiness denominator считает `raw selected calls`, в
   том числе `73` корректно исключенных short/no-speech звонка.
3. Поэтому `signal_report` сейчас часто отражает не нехватку анализа по
   содержательным звонкам, а denominator mismatch между technical readiness и
   manager-facing selection model.
4. Единственный подтвержденный call-level blocker вне normal exclusions:
   `llm2_admission_non_commercial_or_unusable` - `7` звонков за проверенный
   scope.

Фаза 2 должна быть оформлена отдельным решением перед кодовыми правками:

1. Решить, считать ли `full_report` coverage по `meaningful_calls_total`
   вместо `raw selected calls`, либо оставить текущую математику, но явно
   разделить `technical raw coverage` и `manager-facing coverage`.
2. Проверить sample из `7` admission-rejected звонков и решить, это корректные
   исключения LLM2 или нужна доработка admission / квалификации звонков.

## 12. Фаза 2: readiness denominator для `full_report`

### 12.1. Решение

Для manager_daily `full_report` readiness должен оценивать полноту анализа по
содержательным звонкам дня, а не по всем raw-звонкам телефонии.

Текущая техническая формула:

```text
analysis_coverage = included_in_report_total / raw_calls_total
```

Целевая manager-facing формула для принятия решения о `full_report`:

```text
manager_day_analysis_coverage =
  meaningful_ready_analysis_total / meaningful_calls_total
```

При этом raw-coverage не удаляется: его нужно оставить как диагностическую
метрику, чтобы видеть общую техническую воронку источника.

### 12.2. Почему это нужно

Короткие звонки, звонки без речи и IVR/autoanswer уже корректно исключаются из
списка дня через `selection_model.day_exclusion_reasons`. Они не должны
анализироваться и не должны снижать статус отчета.

Пример из аудита Толегена за `2026-06-04`:

- найдено в телефонии: `52`;
- содержательных звонков: `24`;
- коротких / без речи: `28`;
- готовых анализов по содержательным звонкам: `23`.

Текущая readiness-математика:

```text
23 / 52 = 44.2%
```

Целевая manager-facing математика:

```text
23 / 24 = 95.8%
```

То есть текущий `signal_report` в таких случаях отражает не неполноту бизнес-
отчета, а то, что denominator включает звонки, которые мы сами считаем
некорректными для анализа.

### 12.3. На что это влияет

Изменение влияет на служебный статус качества отчета:

- отчет с высоким покрытием содержательных звонков сможет получить
  `full_report`;
- отчет с реальной нехваткой анализа по содержательным звонкам останется
  `signal_report` / `review_required`;
- `signal_report` станет точнее: он будет означать не просто много коротких
  звонков в телефонии, а реальную неполноту содержательного слоя.

Практическое влияние:

1. Операционный контроль: Codex/оператор не будет считать полноценный отчет
   проблемным только из-за short/no-speech звонков.
2. Будущая scheduled delivery: `full_report` можно использовать как более
   честный delivery gate, а `signal_report` оставлять на ручную проверку.
3. KPI пилота: coverage будет отражать бизнес-полезную полноту анализа, а не
   шум телефонии.
4. Сводка для РОП: статус отчета будет ближе к фактической готовности
   менеджерского отчета.

### 12.4. Что не должно измениться

Эта задача не должна менять:

- LLM1/LLM2/LLM3 prompts;
- admission rules;
- список звонков в PDF;
- содержимое `Ситуация дня`, `Все звонки дня`, `Баллы`, `Рекомендации`;
- правила day exclusions;
- delivery channels;
- STT/LLM execution.

Короткие/no-speech звонки должны продолжать отображаться только в верхней
воронке как исключенные, но не снижать readiness coverage.

### 12.5. Что сделать в коде

1. В `_evaluate_manager_daily_readiness()` рассчитывать два coverage:
   - `raw_analysis_coverage = ready_analyses / raw selected artifacts`;
   - `manager_day_analysis_coverage =
      meaningful_ready_analysis_total / meaningful_calls_total`.
2. Для причины `analysis_coverage_below_full_threshold` использовать
   `manager_day_analysis_coverage`.
3. В readiness payload сохранить оба значения:
   - существующее `analysis_coverage` можно оставить как manager-facing
     coverage или явно переименовать через дополнительные поля;
   - добавить диагностические поля `raw_analysis_coverage`,
     `manager_day_analysis_coverage`, `meaningful_calls_total`,
     `meaningful_ready_analysis_total`, `excluded_calls_total`.
4. В `diagnostics.readiness` и observability сохранить оба coverage, чтобы
   оператор видел, почему отчет стал `full_report` или остался `signal_report`.
5. Обновить тесты manager_daily readiness:
   - raw много, meaningful покрыт >=75% -> `full_report`, если content blocks
     готовы;
   - meaningful coverage <75% -> не `full_report`;
   - zero meaningful calls -> `skip_accumulate` или текущий безопасный outcome,
     без деления на ноль;
   - normal exclusions не создают `analysis_coverage_below_full_threshold`.

### 12.6. Acceptance criteria

Задача считается выполненной, если:

- на audit case Толегена `2026-06-04` coverage для readiness считается как
  `23/24 = 95.8%`, а не `23/52 = 44.2%`;
- raw coverage остается доступным как диагностическая метрика;
- короткие/no-speech звонки остаются в верхней воронке и не попадают в анализ;
- PDF-содержание не меняется от этой правки, кроме возможных служебных
  readiness/status diagnostics;
- focused tests по manager_daily readiness проходят;
- контрольный rerender/ready-only прогон показывает, что отчеты с высоким
  coverage содержательных звонков больше не получают `signal_report` только
  из-за normal exclusions.

### 12.7. Отложено

`llm2_admission_non_commercial_or_unusable` пока не исправлять в рамках этой
задачи. Эти случаи нужно смотреть на новых звонках, фиксировать примеры и
решать отдельно: это корректное исключение LLM2 или потеря полезного звонка.

### 12.8. Реализация first pass

Дата: 2026-06-10

Изменения:

- `_evaluate_manager_daily_readiness()` теперь рассчитывает:
  - `raw_analysis_coverage`;
  - `manager_day_analysis_coverage`;
  - `analysis_coverage` как manager-facing coverage для совместимости;
  - `meaningful_calls_total`;
  - `meaningful_ready_analysis_total`;
  - `excluded_calls_total`.
- Threshold `MANAGER_DAILY_FULL_REPORT_MIN_ANALYSIS_COVERAGE` проверяется по
  `manager_day_analysis_coverage`, то есть по содержательным звонкам.
- Raw coverage сохранен как диагностическая метрика и не используется как
  главный blocker для `full_report`.
- Prompts, STT/LLM execution, delivery, PDF-смысловые блоки и selection model
  не менялись.

Тесты:

- added focused readiness tests в `tests/test_manual_reporting.py` и
  `core/tests/test_manual_reporting.py`;
- case `raw много + normal exclusions много + meaningful coverage 100%`
  получает `full_report`;
- case `meaningful coverage 62.5%` не получает `full_report`;
- zero meaningful calls безопасен и не делит на ноль.

Проверки:

- `py_compile` для `reporting.py` и `test_manual_reporting.py` - OK;
- `pytest /app/tests/test_manual_reporting.py::ManualReportingStatusTests -k "manager_daily_readiness or manager_daily_group_result"` -
  `6 passed`;
- `pytest /app/tests/test_manual_reporting.py -k "selection_model and not signal_report_model"` -
  `9 passed`;
- `git diff --check` - OK.

Остаточный соседний риск:

- широкий sweep с `signal_report` выявил отдельный failing test
  `test_signal_report_model_uses_manager_facing_polish_rules`: пустые
  `call_tomorrow.rows`. Это не относится к denominator readiness и требует
  отдельного разбора, если задача станет актуальной.
