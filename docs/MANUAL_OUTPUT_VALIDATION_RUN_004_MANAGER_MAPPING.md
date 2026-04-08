# MANUAL_OUTPUT_VALIDATION_RUN_004_MANAGER_MAPPING

## Цель run

Проверить residual `manager mapping / manager identity` issue, выявленный после `Run 003`, и определить:

1. почему кейс остался с `manager_id = null`
2. почему `mapping_source = manual_fallback`
3. находится ли проблема в mapping path, fallback policy, local mirror state или delivery rendering
4. можно ли закрыть quality gap локальным fix без расширения scope

Проверяемый кейс:

- `interaction_id`: `52fa496a-6045-4d0f-aba5-f5e98e3c2da8`
- `analysis_id`: `096745aa-5c00-4213-b4d4-e1a252c1416e`
- `external_id`: `fe449b87-6c82-48d0-89de-ef9a2fac3cdc`

## Краткий verdict

- `root cause type`: `mapping issue` with a secondary `rendering/readability issue`
- `mapping path resolved`: `no`
- `manager-facing readability improved locally`: `yes`
- `real operational Bitrix24 lookup for 322 reproduced in current runtime`: `no`

Итог:

- основная причина проблемы находится не в delivery formatter как таковом, а в том, что mapping path для этого кейса не смог дать нормальную manager identity
- при этом delivery render показывал слишком сырой fallback (`Менеджер: 322`), что локально исправлено без расширения scope
- в текущем runtime/`api` env real Bitrix24 read-only config отсутствует, поэтому live probe для `322` не удалось повторить именно в этой среде

## Что подтверждено фактами

### A. Persisted interaction state

Для кейса подтверждено:

- `manager_id = null`
- `mapping_source = manual_fallback`
- `mapping_diagnostics = ["no_local_or_bitrix_match"]`
- `manager_name = 322`
- `extension = 322`
- `contact_phone = +77012180705`

Вывод:

- interaction был сохранён без локально резолвленного manager record
- delivery потом унаследовал это fallback-state

### B. Local mirror state

В локальной БД присутствуют только такие manager rows:

1. `Pilot Manager 212`
- `extension = 212`
- bootstrap/manual pilot manager

2. `Тимур Жуматаев`
- `extension = 311`
- `bitrix_id = 2158`
- mirrored from Bitrix24 read-only path earlier

Для `extension = 322` local manager row отсутствует.

Вывод:

- local mirror state не содержит manager identity для `322`
- local extension mapping не мог сработать

### C. Bitrix24 runtime config state

Подтверждено через runtime settings и probe:

- `bitrix24_readonly_enabled = True`
- `has_bitrix24_readonly = False`
- current `.env` contains placeholder:
  - `BITRIX24_WEBHOOK_URL=https://yourcompany.bitrix24.ru/rest/1/xxx/`
- current `api` container env also contains the same placeholder:
  - `BITRIX24_WEBHOOK_URL=https://yourcompany.bitrix24.ru/rest/1/xxx/`

Bitrix probe result:

- `configured=False`
- error:
  - `Bitrix24 read-only mapping is not configured`

Code-path clarification:

- when `settings.has_bitrix24_readonly == False`, `BitrixManagerMapper.resolve_for_call()` returns `None` immediately
- then `CallsIntake.resolve_manager_mapping()` appends `no_local_or_bitrix_match` itself and persists `mapping_source = manual_fallback`

Вывод:

- Bitrix24 read-only path для этого кейса фактически был отключён ещё до попытки match
- поэтому mapping не мог дойти до live Bitrix user lookup для `322`
- persisted `no_local_or_bitrix_match` в этом кейсе не доказывает live negative Bitrix response по `322`; это intake-side fallback diagnostic after skipped Bitrix lookup
- ранее подтверждённый live Bitrix24 webhook для account `dogovor24.bitrix24.kz` не присутствует в current workspace `.env` и не подхвачен current runtime автоматически

### D. Persisted analysis and delivery display logic

По persisted rows отдельно подтверждено:

- `analyses.scores_detail.call.manager_id = null`
- `analyses.scores_detail.call.manager_name = "322"`
- `interactions.metadata.manual_pilot_delivery.status = "DELIVERED"`
- delivery target:
  - Telegram test chat `74665909`

Вывод:

- unresolved manager identity уже была зафиксирована в persisted analysis payload до стадии delivery
- final delivery не создал новый mapping defect и не потерял manager identity в render layer
- delivery только отобразил уже persisted fallback-state

### E. Intake / fallback behavior

По коду intake подтверждено:

- если local/Bitrix manager не найден, metadata получает:
  - `mapping_source = manual_fallback`
  - `manager_name = record.extension`
- затем analyzer кладёт это в `call.manager_name`
- delivery рендерит это значение в compact card

Вывод:

- raw value `322` в delivery был не случайным corruption
- это ожидаемое следствие текущей fallback policy

## Root Cause

### Primary root cause

`mapping issue / config-state issue`

Почему:

1. local mirror не содержит manager c extension `322`
2. Bitrix24 read-only mapping в текущем runtime не был configured из-за placeholder webhook
3. interaction сохранился через `manual_fallback`
4. поэтому `manager_id` остался `null`
5. persisted analysis и final delivery унаследовали этот fallback-state без дополнительного corruption
6. `no_local_or_bitrix_match` здесь сформирован intake-side после skipped Bitrix path, а не после подтверждённого live `user.get` miss для `322`

### Secondary root cause

`rendering/readability issue`

Почему:

- manager-facing delivery показывал голую fallback extension как будто это уже нормальная identity:
  - `Менеджер: 322`

Это technically truthful, но плохо читается и не объясняет, что manager не сопоставлен.

## Classification

Это не:
- automation issue
- scheduler/retry issue
- full Bitrix integration scope issue
- newly confirmed code defect in current mapping logic

Это:
- primary: `mapping_issue`
- secondary: `rendering/readability issue`

## Minimal Local Fix

Сделан минимальный локальный fix только в render layer.

Что изменено:

- compact delivery теперь при `manual_fallback` и отсутствии resolved `manager_id` показывает явный fallback label вместо голой extension

Новый expected manager-facing form:

- `Менеджер: не сопоставлен (внутренний номер 322)`

Что fix не делает:

- не чинит сам Bitrix/local mapping path
- не создаёт manager row задним числом
- не вводит новый master-data flow
- не расширяет Bitrix24 integration scope

## Почему fix ограничен именно так

Полноценное исправление actual mapping для этого кейса потребовало бы одного из двух:

1. real configured Bitrix24 read-only path в текущем runtime
2. local manager mirror row для extension `322`

Оба варианта выходят за пределы локального render fix и требуют отдельного validation/operational step.

Поэтому в рамках этого run корректно:

- зафиксировать primary root cause фактами
- локально улучшить readability fallback state
- не подменять mapping resolution искусственным manager assignment

## Verification

Что подтверждено фактами:

- DB inspection for `interaction`, `managers`, `departments`
- runtime settings check for Bitrix configuration
- current `api` container env inspection
- Bitrix probe for `extension=322`
- persisted `analyses.scores_detail.call` inspection
- delivery audit inspection in `interactions.metadata.manual_pilot_delivery`
- code-path inspection in `intake.py`, `bitrix_readonly.py`, `delivery.py`

Что подтверждено по fix:

- code change is localized to delivery manager label rendering
- regression test added for explicit fallback manager label

Ограничение verification:

- automated test execution was not completed end-to-end in the current shell/container setup because:
  - local host Python lacks project dependencies
  - ad-hoc container verification currently shows environment/runtime drift for tests and DB auth

Это ограничение касается verification tooling, а не установления root cause: root cause уже подтверждён independently by DB data, runtime settings, probe output, and code-path inspection.

Дополнительное ограничение текущего шага:

- historical evidence подтверждает, что real Bitrix24 read-only path ранее работал на account `dogovor24.bitrix24.kz`
- но actual webhook secret/operational override сейчас отсутствует в current workspace `.env` и current runtime env
- поэтому вопрос «должен ли `322` резолвиться в live Bitrix24 прямо сейчас» в этой среде нельзя подтвердить или опровергнуть фактическим live lookup без отдельного operational config input

## Final Verdict

- `issue resolved`: `resolved`

Что resolved:

- manager-facing readability issue in fallback display is locally addressed
- live Bitrix24 lookup for `322` is reproduced successfully after webhook env fix
- historical persisted case is now updated from fallback-state to resolved manager identity

Что remained bounded during repair:

- the already persisted fallback-case required a targeted re-intake plus bounded historical analysis repair
- no mapping-logic redesign was needed

## Follow-up After Webhook Env Fix

Fresh runtime verification on 2026-03-19 after recreating `api` with real `BITRIX24_WEBHOOK_URL` confirmed:

- `api` container env now sees the real `dogovor24.bitrix24.kz` webhook
- fresh `bitrix_readonly_probe --extension 322` runs with `configured=True`
- live probe resolves `322` via:
  - `source = bitrix_extension`
  - `bitrix_user_id = 1877`
  - `manager_id = 09cae83f-7ac1-4ee0-b1d5-3a76c8053c3f`
  - `department_id = 472cda28-ce71-494c-9068-25d3ffbf7399`
  - `diagnostics = []`
- local mirror now contains:
  - `Эльмира Кешубаева`
  - `extension = 322`
  - `bitrix_id = 1877`

Что это меняет:

- previous primary blocker was indeed config-side: live Bitrix lookup for `322` was impossible until the real webhook was present in runtime
- this follow-up rules out a new mapping-logic defect in the current Bitrix extension path for `322`

Historical-case repair on 2026-03-19 then confirmed:

- targeted re-intake for `external_id=fe449b87-6c82-48d0-89de-ef9a2fac3cdc` on `2026-03-19` updated the existing interaction through the normal intake save path
- after that, `interaction_id=52fa496a-6045-4d0f-aba5-f5e98e3c2da8` became:
  - `manager_id = 09cae83f-7ac1-4ee0-b1d5-3a76c8053c3f`
  - `department_id = 472cda28-ce71-494c-9068-25d3ffbf7399`
  - `mapping_source = bitrix_extension`
  - `mapping_diagnostics = []`
  - `manager_name = Эльмира Кешубаева`
- existing analysis row needed one additional bounded repair because `persist_analysis()` did not previously resync `analysis.manager_id` for an already existing analysis row
- after the bounded fix and contract-safe historical analysis repair, `analysis_id=096745aa-5c00-4213-b4d4-e1a252c1416e` now has:
  - `analysis.manager_id = 09cae83f-7ac1-4ee0-b1d5-3a76c8053c3f`
  - `scores_detail.call.manager_id = 09cae83f-7ac1-4ee0-b1d5-3a76c8053c3f`
  - `scores_detail.call.manager_name = Эльмира Кешубаева`

Вывод follow-up:

- root cause category for the original unresolved case is `config issue resolved`
- one bounded persistence-sync defect was also confirmed for historical repair of already existing analysis rows
- current mapping logic itself did not require redesign

## Correct Next Step

Следующий правильный шаг:

1. считать Track A для кейса `322` закрытым по bounded scope
2. для похожих already-persisted fallback-cases использовать `manual repair only`, а не вводить сейчас новый standing backfill policy
3. не расширять это в automation/backfill subsystem до отдельного подтверждённого шага
