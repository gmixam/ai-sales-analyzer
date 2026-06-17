# PILOT-31: Weighted focus stage для блока `БАЛЛЫ ПО ЭТАПАМ`

Дата: 2026-06-16
Статус: implemented_second_pass
Связанные задачи: `PILOT-19`, `PILOT-23`, `Report Layer`, `LLM2B scoring`

## Implementation status

First pass реализован 2026-06-16:

- веса этапов добавлены в `core/app/agents/calls/reporting.py`;
- `_aggregate_stage_scores(...)` выбирает priority stage по
  `focus_impact=(10-score)*stage_weight*coverage_factor`;
- `score < 3.0` обрабатывается как отдельный `critical_low_score_signal`,
  но больше не перехватывает фокусный этап;
- диагностические поля добавлены в stage rows;
- `criteria_detail` по-прежнему заполняется только для выбранного priority stage;
- сами оценки этапов, `Балл дня`, применимость этапов и LLM2 scoring не менялись.

Проверки:

```bash
docker compose exec -T api python -m pytest -q /app/tests/test_manual_reporting.py -k "weighted_focus or critical_low_score or stage_scores"
python3 -m py_compile core/app/agents/calls/reporting.py
node --check scripts/generate_docx_report.js
git diff --check
```

Результат: `6 passed, 251 deselected`, static checks OK.

Second pass 2026-06-16 после ручной проверки Толегена за `2026-06-15`:

- снят `critical low-score override`;
- priority stage всегда выбирается по максимальному `focus_impact`;
- критически низкий этап (`score < 3.0`) отображается отдельно как
  `critical_low_score_signal` / `Критический сигнал`, если он не является
  фокусным;
- в DOCX/PDF таблице `БАЛЛЫ ПО ЭТАПАМ` такой этап виден в колонке `Статус`,
  но не подменяет основной фокус.

Следующий шаг: на ближайшем контрольном manager_daily отчете визуально проверить,
что выбранный фокусный этап выглядит управленчески логично, а таблица
`БАЛЛЫ ПО ЭТАПАМ` не изменила сами баллы.

## Контекст

В блоке `БАЛЛЫ ПО ЭТАПАМ` сейчас фокусный этап выбирается грубо:

```text
первый этап по воронке, где средний балл ниже 4.0
```

Текущая логика находится в:

- `core/app/agents/calls/reporting.py`
  - `_aggregate_stage_scores(...)`
  - сейчас `is_priority = not priority_found and avg < 4.0`

Это создает управленческое искажение: ранний этап может стать фокусом только
потому, что он первый в воронке и получил низкий балл, хотя с точки зрения
влияния на результат более важная просадка может быть в середине разговора:
квалификация, выявление потребностей, презентация ценности, работа с
возражениями.

## Принятое решение

Сами оценки и `score_by_stage` **не меняем**.

Меняем только выбор `is_priority` / фокусного этапа в дневном отчете.

Фокусный этап должен выбираться не по минимальному баллу и не просто по первому
этапу ниже порога, а по `focus_impact`:

```text
focus_impact = (10 - stage_score) * stage_weight * coverage_factor
```

Где:

- `stage_score` - текущий средний балл этапа по шкале `0-10`;
- `stage_weight` - экспертный вес влияния этапа на результат;
- `coverage_factor` - надежность базы по количеству оцененных звонков.

## Что не меняем

- Не меняем LLM2B scoring rubric.
- Не меняем баллы этапов.
- Не меняем применимость этапов.
- Не меняем `Балл дня`.
- Не пересчитываем historical analyses.
- Не добавляем LLM-вызовы.
- Не скрываем низкие ранние этапы из таблицы.

## Текущие этапы и веса

Текущая рубрика содержит 9 этапов:

| Stage code | Этап | Вес | Логика веса |
| --- | --- | ---: | --- |
| `contact_start` | Первичный контакт | `0.85` | Важен для входа в разговор, но редко сам по себе определяет исход, если дальше менеджер хорошо ведет клиента |
| `qualification_primary` | Квалификация и первичная потребность | `1.25` | Один из ключевых этапов: без него менеджер продает без достаточного контекста |
| `needs_discovery` | Выявление детальных потребностей | `1.40` | Самый сильный коммерческий слой: сценарии, боль, сроки, ЛПР, контекст решения |
| `presentation` | Формирование предложения / презентация / КП | `1.30` | Высокий вес: ценность должна быть связана с контекстом клиента |
| `objection_handling` | Работа с возражениями | `1.35` | Очень высокий вес, когда возражение реально применимо |
| `completion_next_step` | Завершение и договоренности | `1.15` | Важно для сохранения результата, но часто слабый финал является следствием слабой середины |
| `sale_processing` | Оформление продажи | `0.95` | Больше операционный этап; важен, но не всегда отражает качество продажи |
| `sale_final` | Продажа / финал | `1.00` | Важен, но если клиент уже дошел до commitment, основная сложная работа часто сделана раньше |
| `cross_stage_transition` | Сквозной критерий / переход между этапами | `1.10` | Влияет на связность разговора, но не должен автоматически перехватывать фокус у содержательных этапов |

Веса являются экспертной моделью первого pass. Их нужно хранить как
явную конфигурацию в коде Report Layer, а не зашивать в разрозненные условия.

## Coverage factor

Нужно учесть, что этап мог быть оценен на малом числе звонков.

Рекомендуемая формула:

```text
coverage_factor = 0.6 + 0.4 * (stage_calls / max_stage_calls)
```

Где:

- `stage_calls` - количество звонков, где этап был оценен;
- `max_stage_calls` - максимальное количество оцененных звонков среди этапов
  текущего дня.

Так этап с 1 звонком не исчезает, но и не перехватывает фокус случайно.

Если `max_stage_calls <= 0`, использовать `coverage_factor = 1.0`.

## Critical low-score signal

Критически низкий этап не должен автоматически становиться фокусом дня.

Правило:

```text
Если stage_score < 3.0, этап получает critical_low_score_signal=true.
Priority stage при этом все равно выбирается по максимальному focus_impact.
```

Практически:

- основной фокус выбирается только по weighted impact;
- если этап со `score < 3.0` не является фокусным, он дополнительно
  отображается в таблице как `Критический сигнал`;
- если такой этап одновременно имеет максимальный `focus_impact`, он будет
  обычным фокусным этапом;
- диагностическое поле `critical_low_score_override` сохраняется как `false`,
  чтобы было видно, что override не применяется.

Цель: совсем проваленный первичный контакт или финал нельзя игнорировать, но
они не должны перехватывать фокус дня при малой базе и меньшем weighted impact.

## Требуемое поведение

1. В `score_by_stage` остается только один `is_priority=true`.
2. Priority выбирается по weighted impact.
3. В priority stage добавить диагностические поля:

```json
{
  "stage_weight": 1.4,
  "coverage_factor": 0.92,
  "focus_impact": 6.4,
  "priority_selection_method": "weighted_focus_impact",
  "critical_low_score_signal": false,
  "critical_low_score_override": false
}
```

Можно добавить эти поля ко всем stage rows, если это проще и полезнее для
debug/observability.

4. `criteria_detail` по-прежнему заполняется только для priority stage.
5. Таблица `БАЛЛЫ ПО ЭТАПАМ` продолжает показывать все этапы и их реальные
   оценки.
6. В тексте отчета не писать "самый низкий этап". Формулировка должна быть:

```text
Фокусный этап выбран по сочетанию просадки, веса этапа и количества оцененных звонков.
```

или еще короче, если блок перегружается:

```text
Фокус выбран по просадке, влиянию этапа и базе звонков.
```

## Пример

Дано:

| Этап | Score | Calls | Weight |
| --- | ---: | ---: | ---: |
| Первичный контакт | `3.5` | `10` | `0.85` |
| Выявление потребностей | `5.0` | `10` | `1.40` |

Расчет:

```text
contact_start impact = (10 - 3.5) * 0.85 * 1.0 = 5.53
needs_discovery impact = (10 - 5.0) * 1.40 * 1.0 = 7.00
```

Фокусный этап: `needs_discovery`, несмотря на то, что его score выше.

## Где менять

Основная зона:

- `core/app/agents/calls/reporting.py`
  - `_aggregate_stage_scores(...)`;
  - `_priority_stage_from_scores(...)`, если требуется fallback;
  - связанные builders, которые используют `is_priority`.

Возможно тесты:

- `core/tests/test_manual_reporting.py`
  - добавить focused tests на weighted priority selection.

## Acceptance criteria

1. Этап с самым низким score не всегда становится priority, если другой этап
   имеет больший `focus_impact`.
2. Этап с `score < 3.0` не перехватывает priority автоматически, но получает
   `critical_low_score_signal=true`.
3. `criteria_detail` формируется для weighted priority stage.
4. В payload видны `stage_weight`, `coverage_factor`, `focus_impact`,
   `priority_selection_method`.
5. В report text нет утверждения, что фокусный этап - просто самый низкий.
6. `Балл дня` и сами stage scores не меняются.
7. Existing reports without weighted fields не падают.

## Test plan

Focused tests:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_manual_reporting.py \
  -k "stage_scores or weighted_focus or priority_stage"
```

Static checks:

```bash
python3 -m py_compile core/app/agents/calls/reporting.py
node --check scripts/generate_docx_report.js
git diff --check
```

Manual review:

- пересобрать один дневной отчет с разными просадками по этапам;
- проверить, что таблица `БАЛЛЫ ПО ЭТАПАМ` не изменила баллы;
- проверить, что фокусный этап управленчески выглядит логичнее.

## Разделение по агентам

### Agent A — weighted priority implementation

- Добавить веса этапов;
- реализовать расчет `coverage_factor` и `focus_impact`;
- заменить выбор `is_priority`;
- сохранить диагностические поля.

### Agent B — tests

- Добавить тесты:
  - более важный средний этап перехватывает фокус у раннего низкого этапа;
  - `score < 3.0` срабатывает как separate critical signal, not priority override;
  - `criteria_detail` привязан к выбранному stage.

### Controller

- Проверить, что `Балл дня` и score values не изменились;
- проверить, что текст отчета не говорит "самый низкий";
- прогнать focused tests.

## Риски

- Менеджеру может быть непонятно, почему фокус не на самом низком этапе.
  - Защита: короткая формулировка методики и будущая задача `PILOT-19` по
    прозрачности scoring.
- Веса могут быть спорными.
  - Защита: считать их first-pass экспертной моделью и калибровать после 2-3
    недель пилота.
- `cross_stage_transition` может стать частым фокусом.
  - Защита: вес `1.10`, не выше ключевой середины; при необходимости добавить
    tie-breaker в пользу содержательных этапов.

## Definition of Done

- `PILOT-31` реализован минимум как `implemented_first_pass`;
- priority stage выбирается по weighted focus impact;
- сами оценки не изменились;
- focused tests passed;
- один контрольный отчет визуально проверен.
