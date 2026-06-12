# Pilot Operations

Дата обновления: 2026-06-09

## Назначение

Короткая инструкция для ежедневного пилотирования MVP-1: как запускать день,
что проверять перед отправкой, какие метрики заполнять и где брать стоимость.

Актуальные задачи пилотного этапа ведутся в `docs/PILOT_BACKLOG.md`.

## Ежедневный порядок

1. Определить менеджера и дату прогона.
2. Проверить актуальные блокеры/задачи в `docs/PILOT_BACKLOG.md`.
3. Проверить runtime-профиль в `docs/RUNTIME_PROFILES.md`.
4. Перед запуском подтвердить route-plan в контейнере:

```bash
docker compose exec -T api python - <<'PY'
from app.core_shared.ai_routing import AIProviderRouter
for layer in ("stt", "llm1", "llm2", "llm3"):
    c = AIProviderRouter().build_route_plan(layer=layer, subject_key=layer).current_candidate()
    print(layer, c.account_alias, c.model, c.api_base, c.endpoint, c.timeout_sec)
PY
```

5. Для полного дня запускать `build_missing_and_report`; для пересборки отчета
   на готовых данных - `report_from_ready_data_only`.
6. Сначала доставлять отчет в operator/test канал или собирать no-delivery
   preview.
7. Проверить PDF/preview:
   - шапка и воронка дня;
   - `Ситуация дня`;
   - `БАЛЛЫ ПО ЭТАПАМ`;
   - `ВСЕ ЗВОНКИ ДНЯ`;
   - пустые блоки не должны выглядеть как незавершенные placeholders;
   - время должно быть report-facing `UTC+5`.
8. Только после review или явного указания пользователя запускать business
   delivery менеджерам.
9. После полного дневного прогона заполнить KPI/стоимость.
10. Выполнить короткий post-run audit: проверить runner status, readiness,
    coverage, missing/rejected artifacts, delivery, cost, аномалии в PDF и
    report-facing блоках.
11. Если аномалия или ошибка не исправлена в рамках текущего запуска, занести
    ее в `docs/PILOT_BACKLOG.md` как `Operational finding` и связать с
    существующей задачей или создать новую задачу.
12. Если РОП/менеджер дал комментарий по отчету, занести его в
    `docs/MANAGER_REPORT_FEEDBACK.md`; если проблема системная, связать ее с
    задачей в `docs/PILOT_BACKLOG.md`.

## Post-run audit

Это обязательный шаг для полуавтоматических прогонов, которые Codex/агенты
запускают здесь без постоянного ручного контроля пользователя.

После каждого `build_missing_and_report` или значимого
`report_from_ready_data_only` agent должен коротко проверить:

- верхний runner status: `delivered`, `partial`, `blocked`, `failed`;
- readiness по каждому manager/report group: `full_report`, `signal_report`,
  `review_required`, `blocked`;
- `analysis_coverage`, `ready_analyses`, `relevant_calls`, rejected/missing
  analyses;
- STT/LLM built/reused/error counts;
- причины `analysis_missing`, `analysis_reuse_rejected`,
  `llm2_admission_non_commercial_or_unusable`, provider failures, quota
  blockers;
- delivery result отдельно по Telegram/email и отсутствие случайной business
  delivery, если был test-only режим;
- `observability.ai_costs` и явные `price_missing` / abnormal cost spikes;
- report-facing аномалии: пустые важные блоки, ложные статусы, обрезанная суть
  звонка, несходящаяся воронка, странные баллы/denominator, placeholders.

Дополнительный обязательный чек для `manager_daily` после PILOT-22:

- `meta.period.date_from == meta.period.date_to == report_day`;
- `window_days_used == 1`, `window_start == window_end == report_day`;
- email subject/body/PDF filename не содержат диапазон дат для однодневного
  запроса;
- `included_in_report_total <= meaningful_calls_total`;
- call list, coaching blocks, status counters and stage scores не содержат
  звонки прошлых дней;
- если любой пункт нарушен, business email должен быть заблокирован
  `strict_report_day_gate`, а finding надо занести в backlog.

Правило фиксации:

- если проблема исправлена сразу в текущем запуске, коротко отметить это в
  финальной сводке;
- если проблема не исправлена, добавить запись в
  `docs/PILOT_BACKLOG.md#operational-findings`;
- если finding повторяется или влияет на доверие к отчету, связать его с
  существующей задачей или создать новую `PILOT-*`;
- если finding пришел от менеджера/РОП, дополнительно завести запись в
  `docs/MANAGER_REPORT_FEEDBACK.md`.

Пример: после прогона 3 менеджеров за `2026-06-05` отчеты были доставлены, но
readiness остался `signal_report` из-за низкого покрытия анализа. Это было
зафиксировано как finding `2026-06-09-coverage-01` и задача `PILOT-20`.

## Preflight без UI

UI больше не является обязательным операторным интерфейсом. До стабилизации
P1-задач из `docs/PILOT_BACKLOG.md` ежедневный preflight должен проверять:

- актуальность Bitrix manager sync: активные менеджеры, email, extension,
  Bitrix ID, новые/деактивированные сотрудники;
- route-plan для `stt`, `llm1`, `llm2`, `llm3`;
- есть ли due schedules, open batches или review drafts;
- delivery mode: test/preview или business delivery после review;
- нет ли известных блокеров по математике первого блока или применимости
  `score_by_stage`.

### Bitrix manager sync

После пересборки контейнера запускать из `api`:

```bash
docker compose exec -T api python /app/report_scripts/bitrix_manager_sync_preflight.py \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399
```

JSON-вариант для Codex/автоматической проверки:

```bash
docker compose exec -T api python /app/report_scripts/bitrix_manager_sync_preflight.py \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --json
```

Если контейнер еще не пересобран после добавления скрипта, файл может быть
недоступен в `/app/report_scripts`; тогда нужно пересоздать `api/worker/beat`
или запускать временную копию только для проверки.

### Scheduled reporting без UI

Проверить schedules и recent review batches:

```bash
docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py status
```

Запустить один безопасный due-scan:

```bash
docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py scan-due
```

Создать controlled schedule для пилотного отдела:

```bash
docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py create \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --preset manager_daily \
  --mode report_from_ready_data_only \
  --start-date YYYY-MM-DD \
  --start-time HH:MM \
  --timezone Asia/Almaty \
  --period-rule previous_day \
  --no-business-email-enabled
```

Approve запускать только после review и явного решения на доставку:

```bash
docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py approve \
  --batch-id <scheduled_report_batch_id> \
  --editor codex_cli
```

Текущее состояние на 2026-06-04: активных schedules нет; `scan-due` вернул
`processed_count=0`. В review queue есть старые batches Manual Live Validation,
они не являются актуальным пилотным расписанием.

## Runtime defaults

Пилотный default:

```text
AI_LLM_EXECUTION_MODE=openai_compatible
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SIMULATION_ENABLED=false
AI_LLM2_ANALYSIS_MODE=layered
AI_LLM2_INPUT_PROFILE=compact
LLM3_ENABLED=true
```

Если пользователь просит другой режим, сначала сверить его с
`docs/RUNTIME_PROFILES.md`.

## Delivery modes

- `telegram_test_only` - operator/test delivery, безопасно для проверки.
- `preview_only` / `--no-delivery` - сборка без доставки.
- `business_email_only` - отправка менеджерам на рабочую почту; использовать
  только после review или явного указания пользователя.
- `telegram_and_email` - комбинированная доставка; не использовать по умолчанию
  в пилоте без отдельного решения.

## Метрики после полного дня

Заполнять в `docs/MVP1_PILOT_METRICS_MEASUREMENTS.md`:

- дата, менеджер, режим прогона;
- всего звонков, звонков с STT, звонков с анализом;
- `analysis_coverage`;
- STT/analysis built/reused/error;
- статус отчета: `full_report`, `signal_report`, `review_required`, `blocked`;
- delivery status, Telegram/email ids если есть;
- причины провала pipeline;
- стоимость STT/LLM в USDT из `observability.ai_costs`.

## Стоимость

Стоимость берется из run result / observability:

```text
observability.ai_costs.stt_cost_usdt
observability.ai_costs.llm1_cost_usdt
observability.ai_costs.llm2_cost_usdt
observability.ai_costs.llm3_cost_usdt
observability.ai_costs.total_current_run_cost_usdt
```

Reuse-артефакты не добавляют стоимость текущего прогона. USD-прайсы считаются
как USDT-equivalent `1:1`.

## Known operational notes

- `AI_LLM2_INPUT_PROFILE=compact` принят как default.
- Текущий P1-backlog перед дальнейшим rollout: Bitrix sync preflight,
  проверка расписания без UI, математика первого блока, применимость этапов в
  `БАЛЛЫ ПО ЭТАПАМ`.
- Kimi K2.6 подключен, но не принят как готовый LLM2 runtime для полного дня в
  текущем layered contract; см. `docs/KIMI_K26_TRIAL_HANDOFF_2026-06-02.md`.
- Смысловые дефекты LLM2 фиксировать как классы проблем, а не как разовые
  prompt hacks; текущее правило закреплено в `docs/DECISIONS.md`.
- Крупные refactor-задачи перед пилотом не выполнять без отдельного решения:
  дробление `reporting.py`, дробление `report_templates.py`, унификация
  duplicate tests и cleanup legacy template asset dirs.
