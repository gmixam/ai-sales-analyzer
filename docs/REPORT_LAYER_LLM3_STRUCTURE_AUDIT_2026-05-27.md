# Аудит освобождения Report Layer / LLM-3 от жесткой структуры

Дата: `2026-05-27`

Статус: `completed_for_planning`

## Зачем

Перед исправлением багов Block 1 нужно проверить, не закрепим ли мы старую
проблему: отчет может технически проходить gates, но терять смысл из-за слишком
жесткой формы. Цель аудита — отделить защитные ограничения от структурных
ограничений, которые лучше перенести в инструкции `LLM-3` или repair-слой.

Главный вывод:

```text
Факты, scope, статусы, сроки, оценки и evidence остаются жесткими.
Форма объяснения, narrative, порядок раскрытия смысла и manager-facing wording
должны стать свободнее внутри bounded candidate pool.
```

## Проверенные узлы

```text
core/app/agents/calls/reporting.py
core/app/agents/calls/situation_day_daily_composer.py
core/app/agents/calls/call_breakdown_composer.py
core/app/agents/calls/voice_of_customer_composer.py
core/app/agents/calls/call_tomorrow_wording_composer.py
core/app/agents/calls/prompts/situation_day_daily_composer_v2.md
core/app/agents/calls/prompts/call_breakdown_composer_v2.md
core/app/agents/calls/prompts/voice_of_customer_composer_v2.md
core/app/agents/calls/prompts/call_tomorrow_wording_composer_v1.md
core/app/agents/calls/report_template_assets/manager_daily/manager_daily_template_v2/semantic.json
```

## Что оставить жестким

Эти ограничения защищают отчет от hallucination и должны оставаться в Report
Layer / validators:

| Контур | Что остается hard gate | Почему |
|---|---|---|
| Identity/scope | `call_id`, report-day scope, selected call from payload | Иначе отчет может описать не тот звонок |
| Факты | клиент, телефон, дата, срок, статус, stage, score | Это не зона творчества `LLM-3` |
| Evidence | quote/scene должны быть из входного пакета | Нельзя придумывать proof |
| Counter-evidence | claim должен смягчаться или отклоняться при контрдоказательстве | Иначе отчет будет несправедлив к менеджеру |
| Status/action safety | refusal/service issue не превращаются в pushy sales action | Это доверие и бизнес-безопасность |
| Language | manager-facing текст на русском | Это продуктовый формат отчета |

## Что безопасно перенести из структуры в инструкции

| Текущее жесткое место | Где видно в коде | Что сделать |
|---|---|---|
| `ПОЗВОНИ ЗАВТРА` как фиксированный label | `semantic.json`, section `call_tomorrow` | Переименовать в нейтральное `КОНТАКТЫ В РАБОТУ`; срок показывать внутри контакта |
| Follow-up selection читает `row.status` | `_build_call_tomorrow()` берет `status = row.get("status")` | Ввести единый `final_manager_status`, чтобы приложение, summary, follow-up и diagnostics говорили одним статусом |
| `Call Breakdown` требует rows как сильный контракт | `rows_required=True`, `fragment_context_min_chars=90`, `row_*_fragment_too_short` | Narrative и turning points сделать главным output; rows генерировать/чинить из narrative как compatibility substrate |
| `Call Breakdown` всегда `same_call_only` | payload `composition_rules.same_call_only=True` | Для Block 2 отдельно утвердить правило: `same_call` или `best_evidence_by_stage`; не зашивать без продуктового решения |
| `Voice of Customer` режет сигнал по строковому quote/context | `quote_missing_from_context`, `quote_context_too_short` | Grounding проверять через `source evidence refs`, `call_id`, scene refs и context, а не только substring |
| `Situation Day` допускает только manager-gap | `_candidate_is_eligible()` запрещает customer/service types | Для самого coaching-блока это оставить, но не считать единственным "кейсом дня"; customer/service кейсы должны жить в других блоках |
| Scripts count в Situation Day | `_normalize_llm3_daily_situation()` требует минимум 2 scripts | Если narrative grounded, scripts можно repair-ить или downgrade-ить, а не откатывать весь смысловой блок |

## Целевая модель

```text
LLM-2 -> universal evidence pack
Report Layer -> canonical statuses + bounded candidate pool + hard fact/evidence gates
LLM-3 -> смысловая композиция внутри candidate pool
Report Layer -> post-LLM3 validation + repair/warning + render
```

`LLM-3` можно дать больше свободы только внутри уже безопасного коридора:

- выбрать лучший кандидат из bounded candidate pool;
- объяснить сцену живым manager-facing языком;
- сгруппировать evidence в понятную историю;
- сделать wording follow-up естественным;
- вернуть `insufficient`, если смысла/evidence недостаточно.

`LLM-3` нельзя давать право:

- менять `call_id`, клиента, дату, статус, срок, stage или score;
- добавлять цитаты, имена, роли, продукты, суммы или дедлайны;
- выводить звонок за report-day scope;
- превращать отказ/service issue в коммерческий push.

## Матрица внедрения

| Тип проверки | Будущее поведение |
|---|---|
| Fact/scope/evidence violation | fail closed / reject |
| Status/deadline mismatch | reject или blocking diagnostic, если влияет на block selection |
| Counter-evidence | repair claim, soften wording или reject |
| Row shape / short row / length issue | repair row from narrative или warning |
| Missing optional script | repair/fallback wording или warning |
| Weak narrative but facts valid | downgrade/insufficient, не выдумывать |

## Порядок после аудита

1. Block 1: исправить title/status/follow-up selection.
2. Block 1: сделать status conflicts видимыми diagnostics, не `passed`.
3. Block 1: повторно отрендерить `2026-05-18`, `2026-05-19`, `2026-05-20`.
4. Только после acceptance Block 1 перейти к Block 2.
5. Перед Block 2 утвердить правило `same_call` vs `best_evidence_by_stage`.

## Проверочный вывод

Аудит подтверждает: сначала нужно убрать структурную жесткость, которая мешает
смыслу, но не ослаблять fact/evidence границы. Для ближайшего исправления Block
1 это означает:

- исправлять не только частный баг `row.status`, а вводить единый
  manager-facing status source;
- переименовать блок так, чтобы сроки `сегодня`, `завтра`, `через неделю` были
  нормальными данными, а не конфликтом с заголовком;
- оставить `LLM-3` только wording-composer для follow-up, без права менять
  selection, status, deadline или priority.
