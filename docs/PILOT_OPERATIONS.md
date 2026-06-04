# Pilot Operations

Дата обновления: 2026-06-04

## Назначение

Короткая инструкция для ежедневного пилотирования MVP-1: как запускать день,
что проверять перед отправкой, какие метрики заполнять и где брать стоимость.

## Ежедневный порядок

1. Определить менеджера и дату прогона.
2. Проверить runtime-профиль в `docs/RUNTIME_PROFILES.md`.
3. Перед запуском подтвердить route-plan в контейнере:

```bash
docker compose exec -T api python - <<'PY'
from app.core_shared.ai_routing import AIProviderRouter
for layer in ("stt", "llm1", "llm2", "llm3"):
    c = AIProviderRouter().build_route_plan(layer=layer, subject_key=layer).current_candidate()
    print(layer, c.account_alias, c.model, c.api_base, c.endpoint, c.timeout_sec)
PY
```

4. Для полного дня запускать `build_missing_and_report`; для пересборки отчета
   на готовых данных - `report_from_ready_data_only`.
5. Сначала доставлять отчет в operator/test канал или собирать no-delivery
   preview.
6. Проверить PDF/preview:
   - шапка и воронка дня;
   - `Ситуация дня`;
   - `БАЛЛЫ ПО ЭТАПАМ`;
   - `ВСЕ ЗВОНКИ ДНЯ`;
   - пустые блоки не должны выглядеть как незавершенные placeholders;
   - время должно быть report-facing `UTC+5`.
7. Только после review или явного указания пользователя запускать business
   delivery менеджерам.
8. После полного дневного прогона заполнить KPI/стоимость.

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
- Kimi K2.6 подключен, но не принят как готовый LLM2 runtime для полного дня в
  текущем layered contract; см. `docs/KIMI_K26_TRIAL_HANDOFF_2026-06-02.md`.
- Смысловые дефекты LLM2 фиксировать как классы проблем, а не как разовые
  prompt hacks; текущее правило закреплено в `docs/DECISIONS.md`.
- Крупные refactor-задачи перед пилотом не выполнять без отдельного решения:
  дробление `reporting.py`, дробление `report_templates.py`, унификация
  duplicate tests и cleanup legacy template asset dirs.
