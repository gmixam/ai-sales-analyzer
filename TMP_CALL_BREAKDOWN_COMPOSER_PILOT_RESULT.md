# Пилот CallBreakdownComposer

Дата фиксации: 2026-05-18.

## Что сделано

Запущены 3 агента:

- агент интеграции проверил точку подключения в `reporting.py`;
- агент реализации создал изолированный `CallBreakdownComposer`;
- агент prompt/tests подготовил LLM3 prompt и тестовый каркас.

После контроля и интеграции подключено:

- `core/app/agents/calls/call_breakdown_composer.py`
- `core/app/agents/calls/prompts/call_breakdown_composer_v1.md`
- `core/tests/test_call_breakdown_composer.py`
- интеграция в `core/app/agents/calls/reporting.py`

## Как работает

Если `SituationDayComposer` вернул verified `situation_day_evidence_packet`, новый `CallBreakdownComposer` строит `Разбор звонка` по тому же звонку.

Fallback сохранен:

- если нет verified ситуации дня;
- если composer не смог собрать строки;
- если call_id не совпал;
- тогда остается старый путь.

## Проверка на Толегене

Прогон:

```bash
docker compose exec -T api python -m app.agents.calls.llm2_ab_runner \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --manager-id d42e8246-772e-4a04-bbe7-2b88f45db695 \
  --date 2026-05-14 \
  --report-only \
  --output-dir review_packages/call_breakdown_composer_pilot_v2_2026-05-14_Толеген_Жангазиев
```

Результаты:

- отчет: `core/review_packages/call_breakdown_composer_pilot_v2_2026-05-14_Толеген_Жангазиев/report_01/report_preview.txt`;
- payload: `core/review_packages/call_breakdown_composer_pilot_v2_2026-05-14_Толеген_Жангазиев/report_01/payload.json`;
- `Ситуация дня`: звонок `ec7d0d6a-7633-4c41-bafb-1cdafc58e3c7`;
- `Разбор звонка`: тот же звонок;
- source: `report_evidence.call_breakdown_composer.v1`;
- quality: `passed`;
- rows: 3;
- filtered rows: 0.

## Новый Разбор звонка

Composer разложил кейс Эльдара на 3 момента:

1. `Момент 1 - требования`

Менеджер услышал сложный запрос, но не собрал его в короткое резюме: сколько организаций/пользователей, какие роли доступа нужны, кто согласует и какой результат клиент хочет получить.

2. `Момент 2 - следующий шаг`

После выявления потребности разговор не был переведен в управляемый следующий шаг: не закреплены участники, срок возврата, формат продолжения и вопрос, который менеджер берет на проверку.

3. `Момент 3 - ценность`

Менеджер не связал решение с бизнес-риском клиента: контроль доступа, согласование между школами, скорость подписания и снижение ручных ошибок остались без акцента.

## Проверки

```bash
docker compose exec -T api python -m py_compile /app/app/agents/calls/reporting.py /app/app/agents/calls/call_breakdown_composer.py
python3 core/tests/test_call_breakdown_composer.py
docker compose exec -T api pytest -q tests/test_call_breakdown_composer.py tests/test_situation_day_composer.py
docker compose exec -T api pytest -q tests/test_manual_reporting.py -k "situation_day_block_candidate or situation_day_rejects or situation_day_block_candidate_focus_override"
```

Результаты:

- `test_call_breakdown_composer.py`: 3 passed;
- `test_call_breakdown_composer.py + test_situation_day_composer.py`: 9 passed;
- focused manual reporting tests: 4 passed;
- combined focused suite: 7 passed.

## Оценка

Механически следующий шаг выполнен успешно:

- `Разбор звонка` теперь не пустой;
- блок берет тот же звонок, что и `Ситуация дня`;
- есть 3 конкретных момента;
- каждый момент содержит контекст и конкретную рекомендацию;
- quality gate пропустил все строки.

Что еще можно улучшить:

- в текущей версии `CallBreakdownComposer` deterministic, без реального LLM3 вызова;
- фрагменты пока берутся из bounded transcript window и размечены как `Контекст` / `Доказательный фрагмент`, но speaker attribution можно улучшить;
- следующий качественный шаг: включить LLM3 writer для `CallBreakdownComposer`, чтобы он редактировал формулировки и выбирал лучшие 2-4 момента из bounded payload.

## Обновление: LLM3 writer и усиленный quality gate

Дата фиксации: 2026-05-18.

Что добавлено:

- `CallBreakdownComposer` теперь сначала вызывает LLM3 через слой `llm3`;
- LLM3 получает bounded JSON payload: выбранный звонок, verified `situation_day_evidence_packet`, transcript scenes, факты LLM2;
- если LLM3 выбирает не тот `call_id`, возвращает слабую структуру, меньше 2 моментов, строки неправильной формы или слишком короткие фрагменты, Report Layer отклоняет ответ;
- для сложного B2B-кейса добавлен системный gate: verified-разбор должен содержать минимум 3 момента;
- короткие изолированные фразы вроде `Давайте сейчас уточню` больше не проходят как самостоятельное доказательство;
- deterministic composer остается fallback, чтобы отчет не ломался и не деградировал.

Проверочный прогон:

```bash
docker compose exec -T api python -m app.agents.calls.llm2_ab_runner \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --manager-id d42e8246-772e-4a04-bbe7-2b88f45db695 \
  --date 2026-05-14 \
  --report-only \
  --output-dir review_packages/call_breakdown_llm3_quality_gate_2026-05-14_Толеген_Жангазиев
```

Результат:

- отчет: `core/review_packages/call_breakdown_llm3_quality_gate_2026-05-14_Толеген_Жангазиев/report_01/report_preview.txt`;
- payload: `core/review_packages/call_breakdown_llm3_quality_gate_2026-05-14_Толеген_Жангазиев/report_01/payload.json`;
- `Ситуация дня`: source `report_evidence.situation_day_composer.v1`, `llm3_used=true`;
- `Разбор звонка`: source `report_evidence.call_breakdown_composer.v1`, тот же call_id `ec7d0d6a-7633-4c41-bafb-1cdafc58e3c7`;
- LLM3 для `Разбора звонка` был вызван, но отклонен quality gate;
- причина отклонения: `rows_count_out_of_range`;
- финальный `Разбор звонка` собран fallback composer-ом в Report Layer;
- итоговый блок содержит 3 момента и прошел `call_breakdown_quality.status=passed`.

Вывод:

`Ситуация дня` уже реально формируется Report Layer + LLM3.  
`Разбор звонка` уже вынесен из LLM2 в Report Layer; LLM3 подключен как writer, но текущий ответ LLM3 еще нестабилен и не прошел gate, поэтому финальный текст собрала системная страховка.

Это правильное поведение для пилота: слабый LLM3-ответ не попал менеджеру в отчет.

Следующий шаг:

- улучшить LLM3 prompt/output contract для `CallBreakdownComposer`, чтобы модель всегда возвращала полноценные `rows`, а не только `moments`;
- расширить transcript scenes: давать LLM3 не только bounded window из `Ситуации дня`, но 2-3 сцены звонка вокруг потребности, уточнения и закрытия;
- добавить нормализацию speaker attribution, чтобы в отчете были `Клиент` / `Менеджер`, а не общий `Контекст`;
- после этого снова прогнать Толегена и сравнить LLM3 writer против fallback по тем же критериям.

## Обновление: LLM3 прошел gate для "Разбора звонка"

Дата фиксации: 2026-05-18.

Что доработано системно:

- `CallBreakdownComposer` теперь строит для LLM3 несколько `transcript_scenes`, а не один bounded excerpt:
  - `discovery`;
  - `qualification`;
  - `requirements`;
  - `next_step`;
  - `verified_situation_day`;
- если persisted diarization слабая, composer пытается восстановить роли по текстовым признакам;
- если LLM3 выбрал правильный момент, но дал короткий фрагмент, Report Layer расширяет его до мини-сцены из `transcript_scenes`;
- в payload добавлены `composition_rules`: для complex B2B минимум 3 момента, rows обязательны, фрагмент должен быть мини-сценой;
- deterministic fallback остается, но в финальном проверочном прогоне уже не понадобился.

Финальный проверочный прогон:

```bash
docker compose exec -T api python -m app.agents.calls.llm2_ab_runner \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --manager-id d42e8246-772e-4a04-bbe7-2b88f45db695 \
  --date 2026-05-14 \
  --report-only \
  --output-dir review_packages/call_breakdown_llm3_repaired_2026-05-14_Толеген_Жангазиев
```

Результат:

- отчет: `core/review_packages/call_breakdown_llm3_repaired_2026-05-14_Толеген_Жангазиев/report_01/report_preview.txt`;
- `Ситуация дня`: `llm3_used=true`;
- `Разбор звонка`: `llm3_used=true`;
- `deterministic_fallback_used=false`;
- `rows_count=3`;
- `call_breakdown_quality.status=passed`;
- выбран тот же звонок: `ec7d0d6a-7633-4c41-bafb-1cdafc58e3c7`.

Новый результат `Разбора звонка`:

1. `Момент 1 - Требования клиента`

Клиент описал общий кабинет для 16 школ и разграничение доступа. Рекомендация: резюмировать требования в бизнес-языке и зафиксировать роли.

2. `Момент 2 - Квалификация участников`

LLM3 выделил, что нужно уточнить участников принятия решения и использования системы. Это хороший отдельный момент, но в следующей итерации стоит проверить, не противоречит ли он факту, что часть вопросов по пользователям менеджер уже задавал.

3. `Момент 3 - Управляемый следующий шаг`

Короткая фраза `Давайте сейчас уточню` расширена Report Layer до мини-сцены с вопросом клиента про общий кабинет и отсутствием конкретного демо/созвона.

Оценка:

- главный технический критерий достигнут: `Разбор звонка` реально формируется LLM3 и проходит quality gate;
- доказательность стала лучше, потому что короткий фрагмент расширяется до контекста;
- слабое место осталось смысловое: LLM3 может выбрать спорный момент про "квалификацию участников", даже если часть квалификации была в звонке. Следующий gate должен проверять counter-evidence: если менеджер уже задавал вопрос, нельзя формулировать это как полностью отсутствующее действие.

Проверки:

```bash
python3 core/tests/test_call_breakdown_composer.py
docker compose exec -T api pytest -q tests/test_call_breakdown_composer.py tests/test_situation_day_composer.py
docker compose exec -T api pytest -q tests/test_manual_reporting.py -k "situation_day_block_candidate or situation_day_rejects or situation_day_block_candidate_focus_override"
```

Результаты:

- локально `test_call_breakdown_composer.py`: 6 passed;
- контейнерно composer tests: 12 passed;
- focused reporting tests: 4 passed.

## Обновление: counter-evidence gate

Дата фиксации: 2026-05-18.

Что добавлено:

- deterministic counter-evidence gate для LLM3-результата `Разбора звонка`;
- gate ищет абсолютные формулировки вида `менеджер не уточнил пользователей/роли/участников/кто будет использовать`;
- если в `transcript_scenes` есть реплика менеджера, которая частично это уточняет, формулировка смягчается;
- пример repair:
  - было: `Менеджер не уточнил роли и количество пользователей`;
  - стало: `Менеджер начал уточнять пользователей/участников (...), но не зафиксировал роли, кто должен подключиться к следующему шагу, и как это влияет на демонстрацию или продолжение сделки`;
- диагностика пишется в `selection_diagnostics.counter_evidence_gate` и `call_breakdown_quality.counter_evidence_gate`.

Контрольный preview через штатный report runner:

```bash
docker compose exec -T api python -m app.agents.calls.manual_reporting_runner \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --preset manager_daily \
  --mode report_from_ready_data_only \
  --date-from 2026-05-14 \
  --date-to 2026-05-14 \
  --manager-id d42e8246-772e-4a04-bbe7-2b88f45db695 \
  --delivery-mode preview_only
```

Результат:

- PDF artifact сформирован;
- `render_variant=template_docx_first_pdf_manager_daily_template_v2`;
- `page_count=7`;
- `Ситуация дня`: `llm3_used=true`;
- `Разбор звонка`: `llm3_used=true`;
- `deterministic_fallback_used=false`;
- `counter_evidence_gate.status=repaired`;
- `counter_evidence_gate.repairs_count=2`;
- `call_breakdown_quality.status=passed`.

Важно:

- общий run status у штатного runner: `blocked`;
- report status: `review_required`;
- причина не в composer, а в manager-facing completeness/readiness: часть звонков дня не имеет готового анализа;
- PDF при этом рендерится и может быть отправлен в Telegram как operator/test delivery.

Telegram readiness:

- `TELEGRAM_BOT_TOKEN` настроен;
- `TEST_DELIVERY_TELEGRAM_CHAT_ID` настроен;
- `soffice` и `node` доступны в контейнере;
- команда отправки:

```bash
docker compose exec -T api python -m app.agents.calls.manual_reporting_runner \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --preset manager_daily \
  --mode report_from_ready_data_only \
  --date-from 2026-05-14 \
  --date-to 2026-05-14 \
  --manager-id d42e8246-772e-4a04-bbe7-2b88f45db695 \
  --delivery-mode telegram_test_only
```

Рекомендация:

- для проверки качества нового механизма использовать `report_from_ready_data_only`;
- `build_missing_and_report` пока не использовать для сравнения, потому что он может запускать добор звонков, STT и LLM2, что смешает проверку Report Layer с повторным анализом.

## Telegram delivery Толегена

Дата фиксации: 2026-05-18.

Команда:

```bash
docker compose exec -T api python -m app.agents.calls.manual_reporting_runner \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --preset manager_daily \
  --mode report_from_ready_data_only \
  --date-from 2026-05-14 \
  --date-to 2026-05-14 \
  --manager-id d42e8246-772e-4a04-bbe7-2b88f45db695 \
  --delivery-mode telegram_test_only
```

Результат:

- Telegram status: `delivered`;
- Telegram target: `74665909`;
- message_id: `229`;
- document_id: `BQACAgIAAxkDAAPlagsRgT1SafhNtOWVJZKnvhyIjEkAAtWcAALbDllIX5e7n2MSSk87BA`;
- PDF: `manager_daily_d42e8246-772e-4a04-bbe7-2b88f45db695_2026-05-14_manager_daily_template_v2.pdf`;
- page_count: 7;
- render_variant: `template_docx_first_pdf_manager_daily_template_v2`;
- `Ситуация дня`: `llm3_used=true`;
- `Разбор звонка`: `llm3_used=true`;
- `call_breakdown_quality=passed`.

Примечание:

- общий runner status остался `blocked`, report status `review_required`, потому что не все звонки дня имеют готовый анализ;
- несмотря на это, operator/test Telegram delivery успешно отправил PDF.
