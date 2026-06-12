# PILOT-13: ФИО контакта из STT через LLM1

Дата: 2026-06-10
Статус: implemented_first_pass / awaiting controlled report rerender
Связанная задача: `docs/PILOT_BACKLOG.md` -> `PILOT-13`

## 1. Контекст

В manager_daily отчетах в колонке `Контакт`, блоке `КОНТАКТЫ В РАБОТУ`,
`РАЗБОР ЗВОНКА` и других местах иногда есть только телефон и дата звонка, без
ФИО/имени клиента. При этом иногда Report Layer или старые contracts могут
использовать metadata/fallback-поля, что создает риск:

- вывести не ФИО, а мусорную фразу из разговора (`Людмила меня зовут`);
- взять имя из telephony/Bitrix/CRM metadata, хотя на текущем этапе это не
утвержденный источник;
- начать ad hoc извлекать имя в Report Layer из STT.

Целевое правило: за ФИО/имя отвечает LLM1/analyzer слой, который работает с
готовой STT. Report Layer не извлекает ФИО сам, не ходит в Bitrix/CRM и не
достраивает имя из transcript.

## 2. Цель

Сделать единый контракт для отображения контакта:

```text
ФИО/имя из LLM1 analysis · телефон · дата, время
```

Если ФИО/имя не найдено или не прошло safety guard:

```text
телефон · дата, время
```

Если телефона нет, но есть безопасное имя из LLM1:

```text
ФИО/имя · дата, время
```

## 3. Источники данных

### 3.1. Разрешено

Для имени/ФИО:

1. `scores_detail.call.contact_name`;
2. совместимые analysis aliases, если они уже нормализуются в `scores_detail.call`
   (`client_name`, `name`) и были получены LLM1/analyzer из STT.

Для телефона:

1. `scores_detail.call.contact_phone`;
2. `interaction.metadata.contact_phone` / `phone` / `client_phone`, если в
   analysis телефона нет.

Телефон не считается смысловым ФИО, поэтому его можно брать из telephony
metadata для отображения контакта.

### 3.2. Запрещено

Для имени/ФИО нельзя использовать:

- Bitrix/CRM lookup;
- telephony metadata name fields: `metadata.contact_name`, `contact_label`,
  `customer_name`, `client_name`;
- ad hoc extraction в Report Layer из `interaction.text`;
- ad hoc extraction в Report Layer из `metadata.segments`;
- `report_evidence.call_report_summary.client_display_name` как primary label,
  пока нет отдельного утверждения;
- unsafe/generic phrases: `клиент`, `абонент`, `алло`, `да`, `нет`,
  `не знаю`, `договор`, `эдо`, `поддержка`, `продажи`, `техподдержка` и т.п.;
- фразы, которые выглядят как кусок реплики, а не имя.

## 4. Что нужно сделать

### 4.1. Audit текущего пути

Проверить и зафиксировать, где сейчас формируется/используется ФИО:

- `CallAnalyzer.build_contract_template()`:
  сейчас `call.contact_name` может заполняться из `interaction.metadata`.
- LLM1 prompt / contract:
  до first pass `client_display_name` допускал `transcript or metadata`; теперь
  разрешен только STT transcript/segments.
- Report Layer helpers:
  `_artifact_call_metadata`, `_artifact_client_name`,
  `_artifact_client_call_reference`, `_build_client_call_reference`.
- Старые helpers:
  `_safe_persisted_transcript_contact_name`, `_safe_contact_name_candidate`.
- Render paths:
  `call_list`, compact call list, `call_tomorrow`, `call_breakdown`,
  `voice_of_customer`.

Результат аудита: короткий список мест, где имя может попасть в отчет не из
LLM1/STT.

### 4.2. LLM1/analyzer contract

Изменить контракт так, чтобы LLM1/analyzer отвечал за имя клиента:

- `scores_detail.call.contact_name` заполняется только если имя/ФИО явно
  прозвучало в STT;
- если имя не прозвучало или есть сомнение, ставить `null`;
- не использовать metadata name fields как источник имени;
- телефон можно оставить из metadata/telephony;
- сохранить safety guard: имя не должно быть телефоном, фразой, generic label,
  URL/email, слишком длинным или digit-bearing value.

Если текущий analyzer template предварительно заполняет `call.contact_name` из
metadata, это нужно убрать или сделать `null`, чтобы LLM не получала
неутвержденный источник как готовый факт.

### 4.3. Report Layer contract

Report Layer должен:

- только подставлять уже сохраненное `scores_detail.call.contact_name`;
- пропускать его через `_safe_client_display_name`;
- брать телефон из analysis или metadata;
- не извлекать имя из transcript/segments;
- не использовать metadata name fields;
- не использовать Bitrix/CRM;
- при отсутствии безопасного имени показывать `телефон · дата, время`;
- одинаково применять reference во всех manager_daily блоках.

### 4.4. Documentation cleanup

Обновить документы, где сейчас разрешен metadata fallback для имени:

- `docs/MANAGER_DAILY_SELECTION_MODEL.md`;
- при необходимости `docs/REPORT_EVIDENCE_CONTRACT.md`;
- prompt docs / analyzer prompt notes.

Нужно явно разделить:

- `contact_name` / ФИО: только LLM1 из STT;
- `contact_phone`: analysis или telephony metadata.

## 5. Что не делать

- Не подключать Bitrix/CRM для поиска ФИО.
- Не делать Report Layer extractor из STT.
- Не добавлять новый LLM-вызов только ради ФИО.
- Не менять смысловые блоки отчета.
- Не менять правила статусов звонков.
- Не делать hard fail отчета, если имя не найдено.

## 6. Acceptance criteria

Задача считается выполненной, если:

1. Если STT содержит явное имя, LLM1 сохраняет безопасное имя в
   `scores_detail.call.contact_name`, и Report Layer отображает:

   ```text
   Имя · телефон · дата, время
   ```

2. Если STT содержит имя, но LLM1 не сохранил его в analysis, Report Layer не
   извлекает имя сам и показывает:

   ```text
   телефон · дата, время
   ```

3. Если telephony/metadata содержит `contact_name`, но analysis
   `contact_name=null`, Report Layer не использует metadata name.

4. Если `contact_name` unsafe (`Ужас`, `алло`, `клиент`, телефон, фраза с
   цифрами, слишком длинная строка), Report Layer скрывает имя и оставляет
   phone/date.

5. Телефон продолжает отображаться даже если имени нет.

6. Все блоки используют один reference:
   - `ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ`;
   - compact call list;
   - `КОНТАКТЫ В РАБОТУ`;
   - `РАЗБОР ЗВОНКА`;
   - `ГОЛОС КЛИЕНТА`.

7. Focused tests проходят в обоих зеркалах:
   - `tests/test_manual_reporting.py`;
   - `core/tests/test_manual_reporting.py`.

## 7. Test plan

Добавить/обновить тесты:

- `contact_name` из analysis отображается;
- metadata `contact_name` не отображается, если analysis name отсутствует;
- transcript/segments name не извлекается Report Layer;
- unsafe names скрываются;
- phone-only reference остается;
- unified reference одинаковый в call_list/call_tomorrow/call_breakdown/
  voice_of_customer.

Дополнительно проверить analyzer/LLM1 contract:

- template не подставляет metadata name как готовый `contact_name`;
- prompt говорит: имя только если явно прозвучало в STT, не из metadata.

## 8. Реализация first pass

Внедрено 2026-06-10:

- `CallsAnalyzer.build_contract_template()` больше не подставляет
  `call.contact_name` из `interaction.metadata`; стартовое значение имени -
  `null`.
- LLM input metadata очищается от name-полей (`contact_name`, `client_name`,
  `customer_name`, `contact_label`, `client_display_name` и совместимые aliases),
  чтобы LLM1 не получала Bitrix/telephony имя как готовый факт.
- `core/app/agents/calls/prompts/analyze.md` теперь явно требует заполнять
  `call.contact_name` и `call_report_summary.client_display_name` только если
  имя/ФИО явно прозвучало в STT transcript/segments.
- Report Layer оставлен в режиме display-only для имени: visible ФИО берется
  из `scores_detail.call.contact_name` / compatible analysis aliases и проходит
  safety guard; телефон может fallback-иться из metadata.
- `_safe_persisted_transcript_contact_name()` переведен в fail-closed shim:
  Report Layer больше не извлекает имя из transcript/segments.
- `call_breakdown_composer` больше не берет visible имя из metadata и строит
  reference в едином формате `Имя · телефон · дата, время`.

Проверка first pass:

- `docker compose exec -T api python -m py_compile /app/app/agents/calls/analyzer.py /app/app/agents/calls/reporting.py /app/app/agents/calls/call_breakdown_composer.py /app/tests/test_manual_reporting.py`;
- `docker compose exec -T api python -m pytest -q ...` по 5 PILOT-13 regression
  tests -> `5 passed, 6 subtests passed`;
- `cmp -s tests/test_manual_reporting.py core/tests/test_manual_reporting.py`;
- `git diff --check`.

## 9. Следующий шаг

Сделать controlled rerender одного свежего manager_daily отчета и проверить
визуально:

- строки с analysis `contact_name` показывают `Имя · телефон · дата, время`;
- строки без analysis `contact_name` остаются phone-only;
- в `РАЗБОР ЗВОНКА` нет старого формата `Имя, yyyy-mm-dd hh:mm`;
- metadata/Bitrix/telephony names не появляются в `Контакт`.
