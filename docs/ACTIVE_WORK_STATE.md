# Активное состояние работ

Дата обновления: 2026-06-14

Статус: `active`

## Назначение

Короткая оперативная карточка текущего этапа. История проекта хранится в
`docs/PROGRESS.md`, решения - в `docs/DECISIONS.md`, режимы запуска - в
`docs/RUNTIME_PROFILES.md`.

Перед началом новой сессии открыть:

```text
docs/ACTIVE_WORK_STATE.md
docs/CONTEXT_INDEX.md
docs/PILOT_OPERATIONS.md
docs/PILOT_BACKLOG.md
docs/RUNTIME_PROFILES.md
docs/MVP1_PILOT_METRICS_MEASUREMENTS.md
docs/PROGRESS.md
docs/DECISIONS.md
```

Если статус станет `waiting_for_user`, агент не должен продолжать реализацию до
ответа пользователя.

## Текущий этап

Тема: MVP-1 pilot operations.

Этап правок механизма закрыт. Начинается пилотирование: ежедневные прогоны,
замеры KPI, контроль стоимости и доставка отчетов после operator review.
Актуальный рабочий backlog пилота: `docs/PILOT_BACKLOG.md`.

Актуальный runtime default:

```text
AI_LLM_EXECUTION_MODE=openai_compatible
AI_LLM_SUBAGENT_RUNTIME_ENABLED=false
AI_LLM_SIMULATION_ENABLED=false
AI_LLM2_ANALYSIS_MODE=layered
AI_LLM2_INPUT_PROFILE=compact
LLM3_ENABLED=true
```

Source of truth по режимам: `docs/RUNTIME_PROFILES.md`.

## Последняя безопасная точка

Последний закрытый пакет:

- локальный commit `a374a4a Prepare repo for MVP1 pilot operations`;
- предыдущая delivery-safe точка: `13995a0 Polish manager daily report delivery`;
- ветка `feature/llm2-block-ready-v15`;
- новых веток, runtime-профилей или delivery-режимов для последних исправлений
  не создавалось;
- использован существующий режим business delivery: `business_email_only`.

Фактическая business-email доставка отчетов за `2026-06-03`:

- Алишер: `g.alisher@dogovor24.kz`, CC `sales@dogovor24.kz`,
  `email_status=delivered`;
- Тимур: `zh.timur@dogovor24.kz`, CC `sales@dogovor24.kz`,
  `email_status=delivered`;
- Толеген: `zh.tolegen@dogovor24.kz`, CC `sales@dogovor24.kz`,
  `email_status=delivered`.

Runner мог возвращать верхний статус `partial` из-за исторических rejected
reuse-записей по mismatch версии анализа; по трем отчетам delivery status был
`delivered`.

Последний operator/test rerender после правок формата:

- Толеген за `2026-06-03`, `report_from_ready_data_only`,
  `telegram_test_only`, последний исправленный Telegram `message_id=398`;
- верхняя воронка в новом формате: `38` найдено, `24` содержательных,
  `14` исключено из списка дня, `10` содержательных без готового разбора,
  `14` вошло в коучинговый разбор;
- `ПРИЛОЖЕНИЕ: ВСЕ ЗВОНКИ ДНЯ` теперь показывает только `14` звонков с готовым
  неошибочным анализом; payload по-прежнему хранит все `24` содержательных
  строки для диагностики и счетчиков;
- `ВСЕ ЗВОНКИ ДНЯ` начинается с новой страницы и рендерится отдельной
  landscape-секцией в DOCX/PDF; после таблицы документ возвращается в portrait.

Последняя внедренная защита пилота:

- `PILOT-22` first pass внедрен 2026-06-12: `manager_daily` больше не
  расширяется rolling-window назад для manager-facing PDF/email/metrics.
- `_build_manager_daily_windows()` возвращает только выбранный report day;
  `skip_accumulate` строится только по artifacts отчетного дня.
- Business email блокируется `strict_report_day_gate`, если period/window
  больше одного дня или `included_in_report_total > meaningful_calls_total`.
- Проверено focused pytest: strict-day group result, expanded-window email
  safety, normal full_report path -> `3 passed`.
- Следующий шаг: controlled rerender Тимура за `2026-06-11` в preview/operator
  mode; business email только после review.

Последний split-service test run:

- 2026-06-14 выполнен полный тестовый прогон за `2026-06-12` для Алишера,
  Тимура и Толегена через разделенный контур:
  `call_processing_api/worker` -> `analysis_api`.
- Важно: это не legacy monolith. `analysis_api` работал с
  `CALL_PROCESSING_MODE=external_service`, `AI_LLM2_INPUT_PROFILE=compact`,
  OpenAI-compatible runtime, subagent/simulation выключены, `LLM3_ENABLED=true`.
- Upstream call-processing: найдено `73` interactions, готово `105/219`
  artifact requirements, отсутствует `114`; provider calls в успешном ensure:
  `101` (`36` source/recording, `32` STT, `33` LLM1). Итоговый статус:
  `partial`, без artifact build failures.
- Analysis/report: LLM1 external artifacts reused for analysis=`35`,
  analyses built=`28`, failed=`7`, причина failed:
  `llm2_admission_non_commercial_or_unusable`.
- По scope 2026-06-12 в БД есть только Алишер (`6` звонков, `4` с STT/LLM1)
  и Толеген (`67` звонков, `31` с STT/LLM1). По Тимуру (`extension=311`) за
  этот день записей не найдено.
- Telegram operator delivery: PDF Алишера доставлен как
  `skip_accumulate/preview`, PDF Толегена доставлен как `full_report`.
  Business email был выключен (`telegram_test_only`, `email_status=skipped`).
- Во время первого split ensure найден и исправлен write-path дефект
  `call_core.call_artifacts`: pending/active duplicate для
  `(interaction_id, artifact_kind, artifact_version)` мог ловить
  `UniqueViolation` до деактивации старой active записи. Исправление в
  `ArtifactRepository.write_active()` деактивирует DB-active и pending-active
  duplicate до insert.
- Остаточная операционная аномалия: две ранние упавшие попытки ensure остались
  в `call_core.call_processing_runs` со статусом `running`, хотя процессов уже
  нет. Требуется отдельный cleanup stale processing runs, чтобы не путать
  будущий мониторинг.

## Пилотный порядок

1. Перед запуском проверить профиль в `docs/RUNTIME_PROFILES.md`.
2. Для полного дневного прогона использовать compact default, если пользователь
   не выбрал иной профиль.
3. Не отправлять менеджерам бизнес-письма без operator review или явного
   указания пользователя.
4. После каждого полного дневного прогона заполнить KPI и стоимость в
   `docs/MVP1_PILOT_METRICS_MEASUREMENTS.md`.
5. После каждого полуавтоматического прогона выполнить post-run audit по
   `docs/PILOT_OPERATIONS.md#post-run-audit`: runner status, readiness,
   coverage, rejected/missing artifacts, delivery, cost и report-facing
   аномалии. Если проблема не исправлена сразу, добавить ее в
   `docs/PILOT_BACKLOG.md#operational-findings`.
6. Если нужны расходы, читать `observability.ai_costs` и отвечать в USDT.

## Текущие критичные задачи пилота

Source of truth по очередности задач: `docs/PILOT_BACKLOG.md`.

Критичный P1 на 2026-06-12:

1. `PILOT-17` - LLM-only semantic reporting: manager-facing статусы, суть,
   приоритеты, рекомендации и ситуации должны идти только из LLM semantic
   fields; deterministic resolver остается только diagnostics.
2. `PILOT-20` - покрытие анализа до `full_report`: полный прогон 3 менеджеров
   за `2026-06-05` доставил отчеты, но все они readiness=`signal_report`
   (`57.1%`, `33.3%`, `41.3%` coverage), поэтому нужно разобрать
   `analysis_missing`, `analysis_reuse_rejected`, failed/non-reusable analyses
   и admission reasons.
3. `PILOT-22` - строгий report-day для manager_daily: first pass внедрен,
   нужен controlled rerender Тимура за `2026-06-11`.
4. `PILOT-23` - компактный верхний блок и краткие пояснения: first pass
   внедрен, focused pytest `7 passed`; следующий шаг - controlled rerender
   Толегена за `2026-06-11` и визуальная проверка верхнего блока /
   `БАЛЛЫ ПО ЭТАПАМ`.
5. `PILOT-19` - прозрачность scoring для менеджера.

P1 baseline закрыт:

- `PILOT-12` закрыт 2026-06-05: visible call-list фильтруется по
  `call_list_analysis_ready=true`.
- Новые задачи по feedback Алишера: `PILOT-14` (рамки обязанностей ЭДО) и
  `PILOT-15` (объяснение оценок в таблице звонков).
- По `PILOT-15` первый pass внедрен по мини-ТЗ
  `docs/MANAGER_DAILY_CALL_FEEDBACK_MINI_TZ.md`: 4-я колонка compact call-list
  стала `Итог / обратная связь`, данные берутся из существующих LLM2
  `scores_detail`, новых LLM-вызовов нет. Следующий шаг - контрольный PDF
  review.
- По `PILOT-16` внедрен first pass
  `docs/LLM2_STATUS_DETAILS_MINI_TZ.md`: `LLM2D` prompt/contract и compact
  payload знают `status_details`, adapter сохраняет блок в `scores_detail`,
  simulation возвращает deterministic структуру, Report Layer берет короткий
  `Итог` из status-specific mini-structure при совпадении статуса. Следующий
  шаг - проверить на реальном `LLM2`/`LLM2D` прогоне, что договоренности
  получают конкретику “о чем договорились”.
- По `PILOT-14` внедрен first pass по
  `TMP_PILOT14_EDO_SCOPE_SCORING_TZ.md`: `LLM2A` формирует `edo_scope`,
  `LLM2B` применяет его к sales scoring, `LLM2D` учитывает scope в
  рекомендациях, Report Layer только отображает и считает scope. Следующий шаг
  - контрольный реальный LLM2/Report прогон на звонках с техподдержкой,
  юр-направлением и смешанными сценариями.
- Свежий feedback 2026-06-05:
  - Толеген подтвердил, что `Итог / обратная связь` стал полезнее; это
    позитивная валидация первого pass `PILOT-15`.
  - Толеген отметил, что не везде нужно натягивать “что улучшить”; добавлена
    задача `PILOT-18` про balanced coaching без forced improvement. First pass
    внедрен 2026-06-08: `LLM2D.coaching_decision` выбирает
    `improve|maintain|no_comment`, Report Layer не достраивает рекомендацию
    при `no_comment`.
  - Тимур отметил, что баллы пока выглядят непонятно; добавлена задача
    `PILOT-19` про прозрачность методики scoring для менеджера.

1. `PILOT-04` - применимость этапов в `БАЛЛЫ ПО ЭТАПАМ`: done.
2. `PILOT-03` - математика первого блока: done.
3. `PILOT-01` - Bitrix manager sync preflight без UI: done.
4. `PILOT-02` - scheduled reporting без UI: baseline done; активных schedules
   нет, `scan-due` безопасно возвращает `processed_count=0`. Controlled
   create -> draft -> approve/delivery smoke запускать отдельным решением.

Следующий продуктовый слой: `PILOT-05` - ежедневный отчет для РОП с приложенными
manager_daily PDF.

Комментарии менеджеров/РОП фиксировать в `docs/MANAGER_REPORT_FEEDBACK.md`.
Если комментарий подтверждает системную проблему, связать его с задачей в
`docs/PILOT_BACKLOG.md` или добавить новую.

## Актуальные документы

- `docs/PILOT_OPERATIONS.md` - ежедневный порядок пилота.
- `docs/PILOT_BACKLOG.md` - актуальные задачи пилота и очередность работ.
- `docs/MVP1_PILOT_METRICS_MEASUREMENTS.md` - KPI, GO/NO-GO и экономика.
- `docs/RUNTIME_PROFILES.md` - режимы запуска и subagent/API границы.
- `docs/AI_PROVIDER_ROUTING.md` - provider pools и env.
- `docs/MANUAL_REPORTING_PILOT.md` - manual reporting pipeline.
- `docs/MANAGER_REPORT_FEEDBACK.md` - журнал обратной связи по отчетам.
- `docs/MANAGER_DAILY_CALL_FEEDBACK_MINI_TZ.md` - draft формата обратной связи
  по оценкам в таблице звонков.
- `docs/LLM2_STATUS_DETAILS_MINI_TZ.md` - draft статусных министруктур для
  `LLM2D` и строки `Итог` в таблице звонков.
- `docs/PILOT23_MANAGER_DAILY_COMPACT_SUMMARY_TZ.md` - draft задачи по
  сокращению служебного текста в верхнем блоке и `БАЛЛЫ ПО ЭТАПАМ`.

## Архив

Исторические планы, длинные аудиты, недельные транскрипты и временные рабочие
файлы перенесены в `docs/archive/`. Они нужны только для расследований и не
являются текущей точкой входа в пилот.
