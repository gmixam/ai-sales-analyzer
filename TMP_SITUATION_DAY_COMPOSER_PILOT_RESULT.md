# Пилот SituationDayComposer

Дата фиксации: 2026-05-18.

## Что реализовано

- Добавлен отдельный `SituationDayComposer` для блока "Ситуация дня".
- Composer работает до старого выбора `report_evidence_situation` и может заменить его только после проверки через текущий Report Layer evidence packet.
- Старый механизм остается fallback: если composer не дал verified-блок, отчет продолжает использовать прежний путь.
- LLM2 не расширялся. Наоборот, новый слой забирает часть report-composition логики из LLM2/Report Layer и делает ее отдельным управляемым механизмом.

## Системные изменения

Файлы:

- `core/app/agents/calls/situation_day_composer.py`
- `core/app/agents/calls/prompts/situation_day_composer_v1.md`
- `core/app/agents/calls/reporting.py`
- `core/tests/test_situation_day_composer.py`

Что изменилось в механике:

1. Composer строит candidate pool из LLM2-фактов и транскрипта.
2. Старые обобщенные выводы LLM2 дополнительно фильтруются quality gate.
3. Для сложных B2B-звонков composer умеет найти паттерн:
   - клиент дает сложный контекст;
   - менеджер отвечает и уточняет;
   - в конце нет управляемого next step: резюме, демо/созвон, участники, время.
4. В отчет попадает только verified-блок, где доказательный фрагмент найден в транскрипте.

## Проверка на Толегене

### 2026-05-14

Команда:

```bash
docker compose exec -T api python -m app.agents.calls.llm2_ab_runner \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --manager-id d42e8246-772e-4a04-bbe7-2b88f45db695 \
  --date 2026-05-14 \
  --report-only \
  --output-dir review_packages/situation_day_composer_pilot_v3_2026-05-14_Толеген_Жангазиев
```

Результат:

- выбран звонок `ec7d0d6a-7633-4c41-bafb-1cdafc58e3c7`;
- источник выбора: `transcript.pattern_inference`;
- статус доказательства: `verified / strong`;
- тема: "Сложный B2B-запрос не переведен в управляемый следующий шаг";
- отчет: `core/review_packages/situation_day_composer_pilot_v3_2026-05-14_Толеген_Жангазиев/report_01/report_preview.txt`.

Это совпадает с ручным эталоном: звонок Эльдара про сеть школ, 16 школ, общий кабинет, разграничение доступов и отсутствие управляемого следующего шага.

### 2026-05-13

Результат:

- отчет собран со статусом `skip_accumulate`;
- полноценный блок "Ситуация дня" не выбран;
- это честное состояние текущей readiness-логики по доступным данным.

### 2026-05-15

Результат:

- отчет собран со статусом `review_required`;
- из расширенной коучинговой базы выбран тот же сильный кейс `2026-05-14`;
- это поведение связано с текущей rolling-window логикой manager_daily, а не с ошибкой composer.

## Проверки

```bash
docker compose exec -T api python -m py_compile /app/app/agents/calls/reporting.py /app/app/agents/calls/situation_day_composer.py
docker compose exec -T api pytest -q tests/test_situation_day_composer.py
docker compose exec -T api pytest -q tests/test_manual_reporting.py -k "situation_day_block_candidate or situation_day_rejects or situation_day_block_candidate_focus_override"
```

Результат:

- `test_situation_day_composer.py`: 6 passed;
- focused `test_manual_reporting.py`: 4 passed.

## Вывод

Пилот подтверждает, что проблема была не только в тексте промпта LLM2. Старый механизм мог выбрать формально verified, но смыслово слабый фрагмент. Новый composer лучше решает задачу выбора и сборки "Ситуации дня", потому что:

- не требует от LLM2 сразу написать готовый отчет;
- отдельно ранжирует ситуации за день;
- фильтрует обобщенные manager gap;
- проверяет доказательство в транскрипте;
- собирает контекст так, чтобы менеджер понял проблему без памяти о звонке.

## Что еще требует доработки

- `Разбор звонка` пока может оставаться слабее "Ситуации дня", потому что он все еще берется из старого `report_evidence.block_candidates.call_breakdown`.
- Для полного эффекта нужен следующий composer для `call_breakdown`, чтобы он раскладывал тот же выбранный звонок по ошибкам и конкретным фразам, а не дублировал или упрощал "Ситуацию дня".
- Нужно отдельно решить правило rolling-window для отчетов вроде 2026-05-15: когда показывать кейс из расширенной базы, а когда требовать ситуацию строго из отчетного дня.
