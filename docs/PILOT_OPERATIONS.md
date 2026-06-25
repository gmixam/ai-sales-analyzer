# Pilot Operations

Дата обновления: 2026-06-15

## Назначение

Короткая инструкция для ежедневного пилотирования MVP-1: как запускать день,
что проверять перед отправкой, какие метрики заполнять и где брать стоимость.

Актуальные задачи пилотного этапа ведутся в `docs/PILOT_BACKLOG.md`.

## Постоянная автоматизация пилота

С 2026-06-15 базовый runtime пилота работает без Codex:

- `call_processing_beat` каждый день в `00:00 Asia/Almaty` запускает
  `call_processing.ensure_daily_upstream` за предыдущий локальный день и
  готовит upstream artifacts: `transcript`, `transcript_segments`,
  `llm1_first_pass`;
- `analysis_beat` каждый день в `08:00 Asia/Almaty` сканирует активный
  `manager_daily` schedule, добирает недостающие artifacts через external
  call-processing при необходимости и формирует review-required batch/draft;
- business email менеджерам остается gated: автоматический schedule создан с
  `business_email_enabled=false`, `review_required=true`;
- technical blockers/failures должны уходить в Telegram через
  `ALERT_TELEGRAM_ENABLED=true`, `ALERT_TELEGRAM_CHAT_ID`.

Runtime scope: `[ЭДО] Отдел Продаж`, schedule candidates: Алишер, Илья, Тимур,
Толеген. Технический пользователь `Робот Договор24` исключается из schedule
scope.

Ночной upstream имеет per-run guard
`CALL_PROCESSING_DAILY_UPSTREAM_PROVIDER_CALL_BUDGET=300`. Если budget/quota,
auth, provider или runtime failure блокирует прогон, task должен вернуть
operator-visible payload и попытаться отправить Telegram alert. Success-alerts
выключены, чтобы не спамить штатными ночными прогонами.

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
10. Выполнить короткий post-run audit. Для scheduled `manager_daily` сначала
    использовать read-only CLI `post-run-audit --date YYYY-MM-DD`, затем при
    необходимости допроверить PDF/report-facing аномалии вручную.
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

Для scheduled `manager_daily` после завершения дня запускать read-only audit:

```bash
docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py \
  post-run-audit --date YYYY-MM-DD
```

JSON-вариант для Codex/логирования:

```bash
docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py \
  --json post-run-audit --date YYYY-MM-DD
```

Команда не запускает STT/LLM/report/delivery pipeline и не меняет расписание:
она читает существующие SLA rows, ROP digest diagnostics и open batches.

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
- отчетный scope после Bitrix sync строится только из `active=true`,
  `email` заполнен, `extension` заполнен; inactive/уволенные сотрудники не
  считаются, технический пользователь `Робот Договор24` исключается из
  расписаний и дневных прогонов;
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

Для расписания использовать не весь список `active_managers`, а
`schedule_scope_candidates`: это active-менеджеры отдела с email и внутренним
номером, без технических пользователей. На последней live-сверке 2026-06-15
Bitrix вернул `5` active-пользователей отдела, из них `4` кандидата в
расписание: Алишер, Илья, Тимур, Толеген. `Робот Договор24` остается active в
Bitrix, но исключается из schedule scope.

Утвержденный production pilot scope с 2026-06-15:

| Менеджер | `manager_id` | Extension | Email |
| --- | --- | --- | --- |
| Алишер Гайнидинов | `5638c619-8732-435c-9664-a7188f13effd` | `317` | `g.alisher@dogovor24.kz` |
| Илья Тарасов | `cfba5067-d356-4c8b-895a-0f5808647978` | `350` | `t.ilya@dogovor24.kz` |
| Тимур Жуматаев | `656abe58-7c23-476a-a9f6-d76305cf42e0` | `311` | `zh.timur@dogovor24.kz` |
| Толеген Жангазиев | `d42e8246-772e-4a04-bbe7-2b88f45db695` | `325` | `zh.tolegen@dogovor24.kz` |

Schedule `manager_ids`:

```json
[
  "5638c619-8732-435c-9664-a7188f13effd",
  "cfba5067-d356-4c8b-895a-0f5808647978",
  "656abe58-7c23-476a-a9f6-d76305cf42e0",
  "d42e8246-772e-4a04-bbe7-2b88f45db695"
]
```

### Scheduled reporting без UI

Важно: перед activation smoke не должны одновременно работать legacy `beat` и
split `analysis_beat`. Пока active schedules нет, это не приводит к запуску
отчетов, но после создания schedule одновременная работа двух beat-процессов
может создать дубли или отправить task не в тот runtime path.

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
docker compose exec -T api python /app/report_scripts/scheduled_reporting_preflight.py \
  create-production-manager-daily \
  --department-id 472cda28-ce71-494c-9068-25d3ffbf7399 \
  --first-report-date 2026-06-15 \
  --manager-id 5638c619-8732-435c-9664-a7188f13effd \
  --manager-id cfba5067-d356-4c8b-895a-0f5808647978 \
  --manager-id 656abe58-7c23-476a-a9f6-d76305cf42e0 \
  --manager-id d42e8246-772e-4a04-bbe7-2b88f45db695 \
  --dry-run
```

После dry-run и проверки conflicts убрать `--dry-run` для реального создания
schedule. По умолчанию `business_email_enabled=false`, а значит создание
schedule не отправляет письма менеджерам.

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
