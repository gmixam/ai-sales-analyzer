# MANUAL_REPORTING_PILOT

## Назначение
Этот документ фиксирует новый согласованный промежуточный режим проекта:
`Manual Reporting Pilot`.

Это не automation readiness и не full automated reporting loop.
Это ручной параметрический запуск анализа и отчётности поверх уже подтверждённого core pipeline.
До пилота теперь допускается bounded `scheduled_reviewable_reporting`, но не full automation loop.

## Позиция в roadmap

`Manual Reporting Pilot` находится между:
- `Delivery Ready`
- и будущим automated reporting / automation settings шагом

Смысл этого режима:
- вручную запускать анализ и отчётность по параметрам;
- для `manager_daily` сначала находить целевые звонки во внешнем source system по выбранным фильтрам, затем подтягивать missing cases в локальный pipeline;
- для `rop_weekly` агрегировать только уже persisted artifacts без нового source/build loop;
- повторно использовать уже готовые артефакты там, где они уже есть и остаются актуальными;
- собирать `manager_daily` и `rop_weekly`;
- вручную отправлять отчёты по email;
- тестировать разные AI модели и bounded report-composer behavior до любого scheduler/retry/beat rollout;
- допускать bounded `scheduled_reviewable_reporting`: automatic schedule -> review-required draft -> operator approve.

## Non-goals

На этом шаге не делаем:
- generic scheduler platform;
- retries;
- beat;
- full automation loop;
- full report mechanism upgrade before pilot;
- broad redesign analyzer;
- изменение approved analyzer contract;
- новые provider adapters только ради этого шага;
- monthly reports в первой версии.

## Relation to Pilot Ready / Pilot Live

После закрытия стартовых pilot blockers следующий согласованный шаг не `full mechanism upgrade rich report`.

Следующим bounded step является `Business-ready Report Pack`.
До него допускается отдельный pre-pilot operational block `scheduled_reviewable_reporting`.
Этот шаг относится к business-facing presentation layer.
Полный mechanism upgrade rich report относится уже к post-pilot track.

## Pilot Ready package

### Pilot baseline version

- pilot baseline version = current stable `Manual Reporting Pilot` slice;
- active template versions = `manager_daily_template_v1` and `rop_weekly_template_v1`;
- approved analyzer contract и current scoring baseline остаются без изменений;
- `Business-ready Report Pack` и full report mechanism upgrade в этот baseline не входят.

### Pilot scope in

- `manager_daily` manual source-aware run;
- `rop_weekly` manual persisted-only aggregation;
- bounded `scheduled_reviewable_reporting` with review-required draft in operator UI;
- existing readiness / reuse / PDF rendering rules;
- always-on Telegram test delivery;
- optional business email delivery через existing toggle.

### Pilot scope out

- balance top-up / quota change / billing action;
- `Business-ready Report Pack`;
- full report mechanism upgrade;
- retries / beat / full automation loop / generic scheduler platform;
- broad analyzer redesign.

### Pilot KPI list

- report delivery success;
- delivered PDF artifact availability;
- report open/read feedback;
- manager usefulness feedback;
- ROP usefulness feedback;
- turnaround time from run to final artifact.

### Pilot group and baseline metrics

- pilot group structure = fixed list of `3–5` managers from one agreed pilot department;
- until names are confirmed, repo keeps this as a placeholder for the fixed pilot group;
- before pilot start the baseline metrics package must be captured for that fixed group:
  - calls selected
  - ready analyses
  - analysis coverage
  - `full_report` / `signal_report` / `skip_accumulate` split
  - Telegram test delivery result
  - business email enabled/disabled state

### Manual AI validation rule

- manual AI validation is performed by the pilot operator with business review from the ROP;
- validation sample = one bounded `manager_daily` manager-day run from the fixed pilot group before pilot start;
- an error is any of:
  - wrong manager or wrong call selection in the report
  - unsupported or hallucinated business-facing claim
  - semantically empty analysis treated as successful
  - critical contradiction between transcript and business-facing summary/recommendation
  - missing or misleading list-of-calls presentation

### Delivery success rule

- Telegram test delivery is always attempted for every manual run;
- business email toggle controls only business email delivery and defaults to `off`;
- for `scheduled_reviewable_reporting`, automatic generation stops at `review_required` and does not auto-send business email;
- business delivery on scheduled runs is counted only after explicit operator approve;
- pilot delivery is counted as successful when the final PDF artifact is built and `telegram_test_delivery=delivered`;
- if `send_email=true`, business email delivery is tracked separately and does not replace Telegram test delivery;
- if Telegram delivery is not delivered, pilot delivery is not successful even when business email is enabled.

### Segmentation rule for call types

- call-type segmentation in the current pilot baseline uses the existing persisted `classification` field only;
- no new call-type segmentation subsystem is introduced before pilot;
- calls without reusable `classification` stay outside the ready subset and must not be silently merged into a typed bucket.

## Pre-pilot report shaping boundary

### Allowed before pilot

- structure/layout polish
- wording/readability polish
- visual hierarchy
- renderer/template polish
- consistent PDF and short delivery wrapper
- complete and honest list-of-calls presentation
- bounded scheduled reviewable generation with manual operator approve
- manual editing only for allowed business-facing report blocks

### Not allowed before pilot

- new mandatory reporting schema redesign
- new extraction/aggregation/coaching architecture
- full rich daily mechanism upgrade
- broad analyzer redesign
- auto-send to business without review
- manual editing of transcript / raw analysis / scores / computed metrics

## Scheduled reviewable reporting boundary

- operating mode = `scheduled_reviewable_reporting`;
- due-scan idempotency is enforced server-side: repeated scan must not create duplicate batches for the same due occurrence;
- disabled or future schedules must not create new batches;
- schedule creates report run automatically and stops at `review_required`;
- result appears in operator UI as draft / review-required artifact;
- batch lifecycle is server-enforced and limited to:
  - `planned`
  - `queued`
  - `running`
  - `review_required`
  - `approved_for_delivery`
  - `delivered`
  - `failed`
  - `paused`;
- operator may edit only business-facing report blocks:
  - `manager_daily`: top summary, focus wording, key problem wording, recommendations wording, final manager-facing note / challenge;
  - `rop_weekly`: executive summary, team risks wording, ROP tasks wording, final managerial commentary;
- operator must not edit transcript, raw extracted facts, raw checklist answers, stage scores, criteria results, raw analyzer JSON, source call-list data or computed metrics;
- before business delivery the system keeps original generated block, edited block, editor and `edited_at`;
- forbidden edit attempts must fail server-side with an explicit structured error;
- business delivery for scheduled runs happens only after explicit operator approve;
- existing Telegram test inspection path may remain active.

## External billing blocker

- the current external blocker is billable quota / balance access for `OPENAI_API_KEY_STT_MAIN` and `OPENAI_API_KEY_LLM1_MAIN`;
- this blocker is not closed in the current task;
- until the user confirms the balance top-up, full closure verification is not complete;
- this blocker is external and operational, not a code defect.

## Closure rerun after top-up

After the user confirms the balance top-up, repeat exactly one bounded rerun:
- preset = `manager_daily`
- mode = `build_missing_and_report`
- department = `472cda28-ce71-494c-9068-25d3ffbf7399`
- manager = `09cae83f-7ac1-4ee0-b1d5-3a76c8053c3f`
- extension = `322`
- period = `2026-04-06`
- delivery mode = always-on Telegram test delivery, business email `off`

This single rerun must confirm in one pass:
- source discovery
- ingest/reuse decision
- audio fetch
- `STT`
- `LLM-1`
- `LLM-2`
- persistence
- report build
- Telegram test delivery

Closure success signs:
- no `429 insufficient_quota` or other billable-access failure on `STT` or `LLM-1`;
- the full chain reaches successful persistence and final report build;
- Telegram test delivery returns `delivered` for the final PDF artifact;
- the run finishes as a bounded runtime confirmation, not as a preview-only or quota-blocked path.

Signs that the external blocker is still not removed:
- `429 insufficient_quota`;
- another billable-access refusal from `OPENAI_API_KEY_STT_MAIN` or `OPENAI_API_KEY_LLM1_MAIN`;
- the run stops before `LLM-2` / persistence / final report build because billable execution cannot proceed;
- Telegram test delivery cannot be reached because the billable stages never complete.

## Первая версия ручного запуска

Первая версия запуска должна поддерживать параметры:
- один или несколько менеджеров;
- период;
- `min_duration`;
- `max_duration`;
- `report_preset`;
- `model` / `version` selection;
- email delivery.

Логика запуска строится не вокруг голых `date_from/date_to`, а вокруг:
- `report_preset`
- периода
- фильтров

## Первая версия presets

Подтверждённые presets:
- `manager_daily`
- `rop_weekly`

`monthly` в первую версию не входит.

## Ручные режимы запуска

Подтверждённые ручные режимы:
- `build_missing_and_report`
- `report_from_ready_data_only`

Назначение:
- `build_missing_and_report` — основной режим для практической работы: source discovery -> ingest missing -> audio fetch -> `STT` -> `LLM-1` -> `LLM-2` -> persistence -> report -> delivery;
- `report_from_ready_data_only` — быстрый повторный запуск для тестов, итераций и model comparison: для `manager_daily` source discovery и ingest missing сохраняются, но new audio / `STT` / `LLM-1` / `LLM-2` build не запускаются; для `rop_weekly` оба режима фактически остаются persisted-only aggregation.

## Current implemented slice

Первый bounded implementation slice уже введён в кодовой базе.

Что уже реализовано:
- manual CLI entrypoint для report run;
- manual API route для bounded report run;
- внутренняя web-страница оператора внутри текущего FastAPI app для ручного запуска report run без CLI;
- lightweight UI-support endpoints для form context, local manager sync и recipient preview;
- bounded `Schedules` block в existing operator UI для future-dated reviewable runs;
- multi-select filters для одного, нескольких или нуля явно выбранных менеджеров/extensions;
- отдельная observability section в operator UI для monitoring текущего run;
- preset resolution для `manager_daily` и `rop_weekly`;
- source-aware discovery по OnlinePBX для `manager_daily` по выбранному периоду и manager filters;
- persistence-check и idempotent ingest для missing source calls без дублей `interactions` только для `manager_daily`;
- reuse-first lookup по persisted `interactions` / `analyses` после source discovery для `manager_daily` и как основной execution model для `rop_weekly`;
- bounded manual full-run path для missing audio / `STT` / `LLM-1` / `LLM-2` только в `manager_daily`, если выбран режим `build_missing_and_report`;
- bounded readiness decision layer только для `manager_daily`: после source discovery / ingest / reuse / optional build и до final render/delivery runtime выбирает `full_report`, `signal_report` или `skip_accumulate`;
- thresholds и window-expansion policy для этого decision layer вынесены в bounded constants/config внутри reporting slice, без изменения analyzer contract и без расширения automation scope;
- normalized payload assembly before rendering;
- versioned report template assets in repo for `manager_daily` / `rop_weekly`, with visual/layout guided by:
  - `docs/report_templates/reference/manager_daily_reference.md`
  - `docs/report_templates/reference/rop_weekly_reference.md`
- final HTML/text preview + PDF rendering from active template version;
- email delivery with `To + Cc + text/html` plus the same final PDF as attachment when enabled;
- structured statuses/errors для:
  - `no_data`
  - `missing_artifacts`
  - `recipient_blocked`
  - `ready`
  - `delivered`
  - `partial`
  - `blocked`

Важно:
- `manager_daily` больше не ограничен только ранее persisted reporting slice;
- `manager_daily` сначала делает source discovery по выбранному периоду и manager filters, затем сверяет найденные calls с локальной базой и ingest/persist missing interactions;
- повторный `manager_daily` run не создаёт дубли `interactions`, потому что source ingest идёт через existing `external_id` idempotency;
- `manager_daily/report_from_ready_data_only` после ingest не строит new audio / `STT` / `LLM-1` / `LLM-2`;
- `manager_daily/build_missing_and_report` после ingest запускает полный upstream chain для fresh/missing cases: audio fetch -> `STT` -> `LLM-1` -> `LLM-2` -> persistence;
- после reuse/build `manager_daily` больше не обязан рендерить full daily PDF любой ценой: сначала оценивается readiness на текущем дне, затем при необходимости на последних `2`, потом `3` рабочих днях; если full readiness не достигнут, runtime может отправить `signal_report`, а при `skip_accumulate` / `no_data` / `missing_artifacts` собрать только operator-facing preview shell вместо обычного deliverable report;
- `rop_weekly` остаётся persisted-only aggregation: weekly path не делает source discovery, не ingest-ит missing calls и не запускает новый audio / `STT` / `LLM-1` / `LLM-2` build;
- это всё ещё bounded pre-pilot path: допускается only `scheduled_reviewable_reporting` with mandatory review/approve, но здесь нет retries, beat, generic workflow builder, auto-approval или auto-send to business outside operator control.

## `manager_daily` readiness policy

`manager_daily` больше не обязан всегда выпускать `full_report`.

После source discovery / ingest / reuse / optional build runtime обязан принять bounded решение:
- `full_report`
- `signal_report`
- `skip_accumulate`

### `full_report`

Разрешён только если одновременно выполнены data-readiness thresholds:
- `relevant_calls >= 6`
- `ready_analyses >= 5`
- `analysis_coverage >= 75%`

И одновременно выполнена content readiness без пустых fallback-блоков для:
- `ИТОГ ДНЯ`
- `РАЗБОР`
- `КЛЮЧЕВАЯ ПРОБЛЕМА ДНЯ`
- `РЕКОМЕНДАЦИИ`

И доступны минимум:
- `1` сильная зона
- `1` зона роста
- `1` главная проблема
- `1` нормальная рекомендация

### `signal_report`

Разрешён, только если `full_report` не готов, но:
- `ready_analyses >= 2`
- найден явный signal:
  - сильный позитивный кейс
  - или критичный негативный кейс
  - или повторяющийся coaching-pattern
- есть минимум `1` понятное действие для менеджера

Это bounded signal artifact, а не ослабленная версия automation loop.

### `skip_accumulate`

Выбирается, если:
- не выполнены условия `full_report`
- и не выполнены условия `signal_report`

В этом случае `manager_daily` не должен рендерить weak PDF и не должен уходить в delivery только ради того, чтобы любой ценой завершить run.

Вместо обычного deliverable artifact reporting layer теперь собирает только operator-facing preview shell:
- сохраняется layout daily report и placeholders основных секций;
- явно показываются counts / coverage / readiness reason codes;
- artifact маркируется как `preview`, `insufficient data`, `not a deliverable manager report`;
- business email delivery остаётся выключенным, preview уходит только в test delivery path.

### Rolling window

Readiness проверяется последовательно:
- сначала на текущем рабочем дне;
- затем на последних `2` рабочих днях;
- затем на последних `3` рабочих днях;
- дальше окно не расширяется.

### Structured reporting result

Для `manager_daily` structured result теперь должен явно показывать:
- `readiness_outcome`
- `readiness_reason_codes`
- `window_days_used`
- `relevant_calls`
- `ready_analyses`
- `analysis_coverage`
- presence/absence key content blocks, используемых в decision layer

Это bounded reporting logic внутри manual pilot, а не переход к scheduler/retries/beat/full automation.

## AI execution audit in manual reporting

Для текущего bounded slice operator-facing observability теперь должна явно различать слои:
- `STT`
- `LLM-1`
- `LLM-2`

Для каждого слоя runtime / reporting observability хранит или показывает:
- selected provider / account / model;
- attempted / executed status;
- skip reason, если слой не запускался из-за `report_from_ready_data_only` или persisted-only weekly semantics;
- bounded usage metadata, когда провайдер его возвращает.

Текущая standing semantics:
- в `manager_daily/build_missing_and_report` fresh/missing cases должны реально пройти через `STT -> LLM-1 -> LLM-2`;
- в `manager_daily/report_from_ready_data_only` reuse-first path допустим, но new `STT / LLM-1 / LLM-2` build запрещён;
- `rop_weekly` остаётся persisted-only и не открывает source/build chain.

## Delivery rules

Для этого шага delivery:
- baseline contract остаётся `email`-oriented с resolved primary recipient + monitoring copy;
- для current operator manual run фактическая semantics split-channel:
  - Telegram test delivery в `TEST_DELIVERY_TELEGRAM_CHAT_ID` выполняется всегда;
  - business email delivery управляется отдельным operator toggle и по умолчанию выключена;
- основной operator artifact теперь `PDF report`, построенный из active versioned template asset;
- resolved email recipients при этом всё равно вычисляются и показываются в preview / run result как reference;
- если operator включил email delivery, тогда поверх always-on Telegram идёт ещё и email to business recipients;
- Telegram test delivery отправляет именно итоговый PDF document, а не text-only dump;
- если Telegram delivery не удался, это возвращается как structured delivery status/reason, а не traceback.

Источник адресатов:
- email менеджера берётся из карточки сотрудника в Bitrix;
- weekly отчёт для РОПа уходит руководителю отдела продаж из Bitrix org structure;
- это считается configurable resolution rule, а не жёстко зашитым значением в коде.

Текущий bounded config path:
- `manager_daily`:
  - primary recipient = `managers.email`
- `rop_weekly`:
  - primary recipient = `departments.settings.reporting.rop_weekly_email`
  - fallback = live Bitrix `department.UF_HEAD -> active user EMAIL`, если локальный reporting email ещё не задан
- monitoring copy:
  - default = `sales@dogovor24.kz`
  - optional override = `departments.settings.reporting.monitoring_email`

Это пока минимальный bounded runtime rule для ручного пилота.
Отдельный richer Bitrix org-structure resolver может быть добавлен позже без смены `report_preset` contract.
Если фактическая email delivery падает на SMTP/runtime этапе, manual run не должен завершаться stack trace: delivery ошибка возвращается как structured `blocked`, чтобы оператор видел `payload/preview` и причину блокировки.
На 2026-03-27 повторная live delivery validation всё ещё не подтвердила `delivered`: текущий runtime доходит до SMTP login и правильно резолвит primary recipient + monitoring copy, но сам SMTP login в этой среде продолжает отвечать `535`, поэтому фактический happy path остаётся зависимым от отдельного operational credentials fix, а не от reporting code path.
На 2026-03-27 после переключения runtime на `smtp.mail.ru:587` delivered happy path был подтверждён и для CLI, и для API; первый операторский web UI использует тот же delivery path без отдельного frontend-приложения и без смены backend execution contract.
На 2026-03-27 после задания `TEST_DELIVERY_TELEGRAM_CHAT_ID` live operator run подтвердил always-on Telegram test delivery semantics: `manager_daily` и `rop_weekly` manual runs с `send_email=false` всё равно возвращают `delivered` через target `telegram:74665909`, а resolved business recipients сохраняются в response как reference/fallback metadata для optional email channel.
На 2026-03-30 active standard template versions зафиксированы как `manager_daily_template_v1` и `rop_weekly_template_v1`; live API smoke подтвердил для обоих preset’ов, что operator run возвращает final `artifact{kind=pdf_report, template_version=manager_daily_template_v1|rop_weekly_template_v1}` и доставляет в Telegram именно `.pdf` document (`manager_daily_*_manager_daily_template_v1.pdf`, `rop_weekly_*_rop_weekly_template_v1.pdf`).
На 2026-03-30 `manager_daily_template_v1` дополнительно адаптирован прямо от approved HTML reference asset `docs/report_templates/reference/manager_daily_reference_html`: runtime filling теперь держит reference composition (hero, tiles, summary box, signal/focus banners, review grid, recommendation cards, outcomes table, dynamics, memo) и убирает reader-facing service traces вроде raw `not available`, `Note:` и template/debug lines из final report artifact.
На 2026-03-30 corrective visual polish для `manager_daily_template_v1` довёл именно PDF renderer до той же логики композиции: first page теперь собирается как оформленный manager report, `РЕКОМЕНДАЦИИ` остаются карточными даже при скромных данных, `ИТОГИ ЗВОНКОВ` сохраняют table-based presentation со статусной дифференциацией, а fallback states в `РАЗБОР` и `КЛЮЧЕВАЯ ПРОБЛЕМА ДНЯ` формулируются редакторски, без ощущения технической заглушки.

## Operator UI specifics

Текущий internal operator UI:
- показывает менеджеров из локального mirrored справочника `managers`, а не напрямую из live Bitrix;
- умеет вручную обновить локальный список для выбранного отдела через явный sync action в UI;
- после sync показывает уже refreshed local directory и фильтрует selector по active managers;
- поддерживает zero / one / many selected `manager_ids` и `manager_extensions` без изменения reporting execution contract;
- при одновременном выборе менеджеров и extensions использует пересечение этих фильтров, потому что underlying backend selection уже работает через существующий `ReportRunFilters`.
- показывает отдельный run-state indicator для `idle / starting / running / completed / blocked / failed`;
- показывает stage-level monitoring для:
  - `source-discovery`
  - `persistence-check`
  - `ingest-missing`
  - `audio-fetch`
  - `STT`
  - `analysis`
  - `report-build / render`
  - `delivery`
- для каждого stage использует structured `status + summary + optional error` из того же `report-run` response;
- для `rop_weekly` UI явно показывает `execution_model=persisted_only`, а source/build stages приходят как `skipped` с поясняющим summary, а не как runtime failure;
- показывает run summary:
  - `execution_model`
  - `selected_interactions_count`
  - `reused_analyses_count`
  - `rebuilt_analyses_count`
  - `final_report_status`
  - split delivery summary:
    - `telegram_test_delivery`
    - `email_delivery`
    - overall delivery result
  - source summary (`targeted_source_records_total`, `ingest_created_total`, `ingest_skipped_total`)
- показывает cost block только по AI-узлам, которые реально выполнялись в текущем run; если exact cost metadata недоступна, выводит safe fallback `not_available` без выдумывания значений.
- показывает отдельный compact diagnostics block для selection/result transparency на той же странице, без нового layout или history subsystem;
- diagnostics block опирается на structured backend payload и показывает:
  - effective preset / mode / department / period
  - `execution_model`
  - selected `manager_ids` / `manager_extensions`
  - явную пометку про `intersection`, если выбраны оба фильтра
  - source summary (`targeted`, `already persisted`, `ingested`)
  - `interactions_found_before_reuse_build`
  - `ready_transcripts_count`
  - `ready_analyses_count`
  - `final_selected_interactions_count`
  - stable `reason_codes`
- минимальные bounded reason codes текущего operator diagnostics slice:
  - `no_persisted_interactions_for_filters`
  - `filters_intersection_empty`
  - `no_ready_artifacts_for_ready_only_mode`
  - `manager_not_in_local_directory`
  - `date_range_has_no_persisted_calls`
  - `source_discovery_failed`
  - `transcript_build_failed`
  - `analysis_build_failed`
- request-level/operator transport behavior тоже hardened:
  - `/pipeline/calls/report-run` по возможности возвращает JSON error envelope даже для unexpected server failure;
  - UI не предполагает, что любой failed response можно сразу парсить как JSON;
  - если сервер вернул non-JSON body, operator page показывает `http status + error title + raw server snippet + note about non-JSON response` вместо browser-like parse error;
  - transport/request failure отображается отдельно от business-stage failure, который приходит внутри successful structured run response.
- UI semantics текущего operator page:
  - checkbox относится только к business email delivery;
  - default state = off;
  - рядом с формой явно показано, что Telegram test delivery выполняется всегда для manual runs.

## Reuse already-built artifacts

Если уже существуют и остаются актуальными:
- transcript;
- карточка;
- чек-лист;
- промежуточные analysis outputs;
- report inputs;

их не нужно пересчитывать повторно.

Принцип:
- пересчитывается только тот шаг, для которого изменилась версия реально влияющего input.

В текущем implemented slice source-of-truth для reuse:
- для `manager_daily` source calls сначала определяются через OnlinePBX CDR discovery по периоду и manager filters;
- для `manager_daily` missing source calls persistятся в `interactions` по `external_id` без создания дублей;
- transcript из `interactions.text`;
- persisted analysis contract из `analyses.scores_detail`;
- manager identity / recipient data из `managers`;
- department reporting settings из `departments.settings`.

Что теперь считается enough for reuse в reporting path:
- transcript:
  - non-empty `interactions.text`
- analysis:
  - `analyses.is_failed = false`
  - non-empty `instruction_version`
  - `scores_detail` содержит reporting-required shape:
    - `classification`
    - `score.checklist_score.score_percent`
    - `score_by_stage`
    - `strengths`
    - `gaps`
    - `recommendations`
    - `follow_up`
  - analysis не является semantically empty:
    - одновременно не пусты не могут быть все четыре поля `score_by_stage`, `strengths`, `gaps`, `recommendations`
    - canonical rejection reason для этого случая: `semantically_empty_analysis`

Если этих artifacts достаточно, повторный запуск идёт без полного rerun pipeline.
Если части artifacts не хватает:
- в `report_from_ready_data_only` missing calls могут быть ingest/persist, но запуск не строит new audio / `STT` / `LLM-1` / `LLM-2` и поэтому может закончиться `ready` только по подмножеству уже готовых artifacts;
- в `manager_daily/build_missing_and_report` для already selected persisted interactions достраивается полный missing upstream chain: audio fetch -> `STT` -> `LLM-1` -> `LLM-2` -> persistence;
- в `rop_weekly` missing weekly source/build steps не достраиваются вообще: weekly report агрегирует только уже persisted ready artifacts.

Если persisted analysis есть, но она не проходит stricter reporting reuse checks:
- такая analysis считается неготовой для reporting reuse;
- failed row с `fail_reason=semantically_empty_analysis` также считается non-reusable и остаётся forensic-only artifact, а не ready analysis;
- в `build_missing_and_report` пересобирается только analysis step для этого interaction, если transcript уже reusable;
- в `report_from_ready_data_only` ничего не достраивается, а interaction остаётся outside ready subset.

Forensic persistence для analyzer теперь разводит raw и normalized result:
- `analyses.raw_llm_response` хранит raw `LLM-2` response text;
- `analyses.scores_detail` хранит normalized approved-contract result;
- если output признан `semantically_empty_analysis`, attempt может быть сохранён только как failed analysis (`is_failed=true`, `fail_reason=semantically_empty_analysis`) и не считается reusable для reporting.

## Подтверждённые triggers пересчёта

Пересчёт нужен, если изменилась версия:
- prompt;
- report logic, если в ней используется LLM;
- чек-лист;
- карточка.

Отдельно важно:
- смена модели не означает автоматический полный rerun всего pipeline;
- но должна позволять rerun только model-dependent шага, если пользователь этого хочет.
- в текущем bounded slice reporting-specific steps не переиспользуются между manual runs:
  - payload assembly
  - readiness decision
  - render/PDF artifact
  Эти шаги всегда пересобираются под текущие `report_logic_version`, `reuse_policy_version` и active `template_version`.

## Report-composer direction

Допускается optional bounded `report-composer` LLM step.

Это:
- не redesign analyzer;
- не новый основной AI слой core pipeline;
- не повод пересобирать весь calls pipeline.

Это bounded надстройка над уже готовыми артефактами и может использоваться для:
- `manager_daily` recommendations;
- manager focus summary;
- `rop_weekly` synthesis;
- narrative summary / interpretation blocks.

Текущее состояние implementation slice:
- report-composer metadata slot уже предусмотрен в normalized payload;
- отдельный LLM-based report-composer runtime step пока не активирован;
- current v1 skeleton использует deterministic fallback text для model-dependent sections.

## Payload richness direction in current slice

Текущий bounded шаг усиливает содержательность без смены normalized contract:
- `manager_daily` может богаче собирать уже существующие section values из approved persisted fields:
  - narrative/focus
  - `signal_of_day`
  - `key_problem_of_day`
  - `call_outcomes_summary`
  - `focus_criterion_dynamics`
- `rop_weekly` может богаче собирать:
  - `dashboard_rows`
  - `risk_zone_cards`
  - `systemic_team_problems`
  - `rop_tasks_next_week`
  - commentary внутри `week_over_week_dynamics` без выдумывания historical data

Источник richness в этом bounded slice:
- `score_by_stage`
- `follow_up`
- `product_signals`
- `evidence_fragments`
- already approved `strengths/gaps/recommendations`

Это не меняет analyzer contract и не добавляет новый reporting contract.

## Agreed target report formats

### `manager_daily`

Направление первой версии:
- короткий верх + детали ниже;
- до 5 рекомендаций;
- один главный фокус на день;
- мотивационный тон с пояснением;
- рекомендации по всем звонкам за день, а не по одному звонку;
- примеры формулировок из реальных звонков;
- прогресс относительно среднего за период;
- и балл, и человеческое объяснение;
- блок `что получилось` короче;
- блок `над чем работать` подробнее.

### `rop_weekly`

Направление первой версии:
- гибридный формат;
- сверху общий вывод по команде;
- ниже короткий блок по каждому менеджеру;
- явное ранжирование менеджеров;
- отдельное выделение:
  - новичков;
  - менеджеров с регрессом;
  - менеджеров, которым нужно внимание РОПа на ближайшей неделе;
- weekly более краткий формат.

`monthly` позже может строиться по той же логике, но аналитичнее.

## Architectural boundary

`Manual Reporting Pilot`:
- использует уже подтверждённый core pipeline;
- не переписывает analyzer contract;
- не открывает automation readiness автоматически;
- не меняет closed Track A / Track B;
- не вводит standing backfill subsystem;
- не отменяет reuse-first strategy.

Следующие implementation-задачи этого режима должны опираться именно на:
- `report_preset + period + filters`;
- reuse existing artifacts;
- bounded model/version selection;
- email-only delivery;
- manual operator trigger.
