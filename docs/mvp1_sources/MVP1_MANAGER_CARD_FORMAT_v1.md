# MVP-1 Manager Card Format — AI Анализ звонков

**Document code:** `edo_sales_manager_card_format`  
**Version:** `v1`  
**Status:** Approved for implementation  
**Date:** 2026-03-17

## 1. Purpose

This file defines the **human-readable reporting format** for manager-level call cards.

It is a presentation layer built from call-level analyses.

Important:

- Card format is **not** the same as the LLM contract.
- The LLM contract stores structured analysis per call.
- The manager card aggregates and renders those results in a readable form.

## 2. Source rules

The card is built from:

1. unique calls after deduplication,
2. classification results,
3. deep analysis results for eligible calls,
4. call metadata from the source system,
5. checklist scores and stage-level data.

## 3. Required card structure

The manager card must contain four parts in this exact order.

### Part A. Header
- `Карточка звонков менеджера — [Имя]`
- Source note with transcript file name or period source
- Short note that the card includes all unique calls for the period

### Part B. Summary table
Columns:

1. `Менеджер`
2. `Период`
3. `Звонков`
4. `Средний балл`
5. `Интерпретация`
6. `Распределение уровней`

Notes:
- `Период` is the min→max datetime of the included call set.
- `Звонков` = count of unique calls in the card.
- `Средний балл` = average of analyzed call scores.
- `Интерпретация` = summarized level for the manager over the period.
- `Распределение уровней` = count by call level, for example `Проблемный: 99, Базовый: 23`.

### Part C. Stage summary table
Columns:

1. `Этап`
2. `Средний балл`
3. `Количество звонков, где этап присутствовал`

Use exact stage labels:

- `Этап 1. Первичный контакт`
- `Этап 2. Квалификация и первичная потребность`
- `Этап 3. Выявление детальных потребностей`
- `Этап 4. Формирование предложения (презентация/КП)`
- `Этап 5. Работа с возражениями`
- `Этап 6. Завершение и договорённости`
- `Этап 7. Оформление продажи (если применимо)`
- `Этап 8. Продажа (финал) (если применимо)`
- `Сквозной критерий. Переход между этапами`

Rules:
- `Средний балл` is aggregated only on calls where that stage was applicable.
- `Количество звонков, где этап присутствовал` counts applicable calls only.
- If a stage has zero applicable calls, it should either be omitted or shown with `0` depending on current output design, but behavior must be consistent.

### Part D. Key findings
A short section called `Ключевые выводы`.

Required behavior:
- 4–6 bullets or short paragraphs
- must mention scenario mix if relevant
- should highlight strongest and weakest stages
- should mention a recurring systemic pattern
- may mention tone risk or weak next-step fixation when recurrent
- must stay evidence-based and not become vague generic coaching

### Part E. Call table
Columns in exact order:

1. `№`
2. `Дата/время`
3. `Длит.`
4. `Контакт`
5. `Тип звонка`
6. `Контекст`
7. `Итог`
8. `След. шаг`
9. `Балл`
10. `Уровень`
11. `Ключевой комментарий`

## 4. Column formatting rules

### `Дата/время`
Use a readable local datetime format, for example:
- `09.02.2026 10:03:18`

### `Длит.`
Show call duration in `M:SS` or `H:MM:SS` when needed.

### `Контакт`
Preferred rendering:
- `[Имя] / [Телефон]`
If name is not available:
- `[Телефон]`

### `Тип звонка`
Use business classification labels, for example:
- `Продажи — первичный`
- `Продажи — повторный`
- `Смешанный`
- `Поддержка`

### `Контекст`
Use short scenario labels, for example:
- `холодный / исходящий обзвон`
- `тёплый / вебинар / заявка`
- `горячий / входящий контакт`
- `тёплый / повторный контакт`
- `тёплый / после подписания документа`

### `Итог`
Use compact human labels:
- `Согласился`
- `Перенёс`
- `Отказался`
- `Демо / встреча`
- `Другое`

### `След. шаг`
Examples:
- `Перезвон`
- `Отправить в WhatsApp`
- `Демо / встреча`
- `—`

### `Балл`
Show compact numeric score, normally with 1–2 decimals.

### `Уровень`
Recommended labels:
- `Проблемный`
- `Базовый`
- `Сильный`
- `Отличный`

### `Ключевой комментарий`
Rules:
- 1–2 concise sentences
- should mention strongest and/or weakest stages
- may mention tone risk or missed next step
- should not repeat the entire analysis
- should remain readable in table format

Good pattern:
- `Сильнее всего выглядят: Этап 6. Завершение и договорённости. Просадка заметна в этапах: Этап 2. Квалификация и первичная потребность; Этап 4. Формирование предложения (презентация/КП).`

## 5. Aggregation rules

### 5.1 Unique call rule
One logical call should appear once in the final card after deduplication.

### 5.2 Calls below deep-analysis threshold
Calls below 180 seconds may still appear in the manager card with classification/meta fields if that is part of the chosen reporting design.
However:
- they must not be falsely treated as fully deep-analyzed sales calls,
- score interpretation must remain consistent with product logic.

### 5.3 Stage averages
Stage averages must be calculated from applicable calls only.

### 5.4 Manager summary
Manager-level interpretation must come from aggregated analyzed calls, not from subjective text.

## 6. Relationship to contract

The card is built from the structured per-call contract.
It must not invent fields that are absent from the contract or call metadata.

## 7. MVP boundary

Required in MVP-1:
- summary table,
- stage summary table,
- key findings,
- per-call table.

Optional after MVP-1:
- richer trend visuals,
- automated task execution views,
- product theme digests embedded into the card.
