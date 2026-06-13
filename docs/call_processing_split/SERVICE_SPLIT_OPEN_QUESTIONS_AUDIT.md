# Аудит незакрытых вопросов по отделению call-processing и EDO analysis

Дата: 2026-06-08

## Короткий вывод

Критических концептуальных противоречий в плане отделения сервиса нет: выбранная рамка `call-processing` как upstream-владелец source/audio/STT/LLM-1 и `edo-analysis` как downstream-владелец LLM-2/reporting остается рабочей.

На 2026-06-08 пользователь утвердил большую часть baseline-решений. Оставшиеся вопросы теперь не блокируют концепцию разделения, но требуют точного подтверждения формулировок перед тем, как превращать ТЗ в код.

## Утверждено пользователем 2026-06-08

| Блок | Утвержденное решение |
|---|---|
| БД | Одна PostgreSQL; `call_core`, `call_public`, `analysis`, `org`; transcript backfill сразу; старый LLM-1 не фабрикуется; unique key `(source, external_id)`. |
| LLM-1 contract | Default принят: универсальный версионированный `llm1_first_pass_v1`, downstream-readable, но не финальная истина; пересчет только по версии/запросу. |
| Доступ | Доступ настраивается отдельно для сервиса или сотрудника, не по департаментам. Админ может править и запускать processing actions; остальные только read-only. |
| Auth | Должен следовать новой модели service/employee grants и admin/reader roles. |
| Env/secrets | Default принят: `edo-analysis` без OnlinePBX/STT/LLM-1 secrets; `call-processing` без delivery secrets; service-specific env profiles. |
| Cutover/rollback | Короткое плановое окно переключения допустимо. Rollback без DB rollback остается обязательным. |
| Recovery | `force_retry_failed` только admin. Stale job = 30 минут без heartbeat/progress. STT/LLM-1 = initial + 2 retry только для transient provider/network errors. Отчеты формируются по готовым данным и текущим правилам анализа. Run status должен показывать, что не все звонки были транскрибированы/обогащены, чтобы после добора можно было перезапустить анализ/отчет. |
| Cost/quota | Владелец admin. Только admin запускает billable `ensure`, `dry_run`, retry. При quota exhaustion уведомить admin и приостановить дальнейшую billable обработку. |
| Retention/PII | Все хранить бессрочно, ограничений на retention/masking в текущем релизе не вводить. |
| RAG/vector | Заложить расширяемость, но не включать в release acceptance. |
| Observability | Новый UI не нужен; взаимодействие пока через CLI. |
| Acceptance | Default принят: один полный production-ready release, draft PR до smoke/verification, затем ready. |

## Что уже закрыто достаточно

| Блок | Статус | Основание |
|---|---|---|
| Общая граница сервисов | Закрыто | `call-processing` владеет source/audio/STT/LLM-1; `edo-analysis` владеет EDO LLM-2, отчетами и доставкой. |
| Физическая БД | Закрыто как baseline | Один PostgreSQL допустим, но ownership должен быть сервисным через `call_core`, `call_public`, `analysis`, `org`. |
| Способ добора пропущенных звонков | Закрыто | `POST /call-processing/ensure` + идемпотентный rescan/upsert/rebuild missing artifacts. |
| Пилот ЭДО | Закрыто как требование | `manager_daily/build_missing_and_report` должен идти через `CallProcessingClient`; `rop_weekly` остается persisted-only. |
| Доступ других команд | Закрыто на уровне принципа | Только API или read-only `call_public`; no write access to `call_core`. |
| RAG/vector DB | Закрыто как non-blocker | Не нужен для первичного разделения; можно добавить позже поверх transcript/LLM1 artifacts. |

## P0: вопросы, которые нужно закрыть до начала реализации

### 1. Точный формат ownership в PostgreSQL

**Статус:** утверждено. Делать schema split (`call_core`, `call_public`, `analysis`, `org`) сразу в миграции.

**Почему важно:** сейчас `Interaction` и `Analysis` лежат в общей модели, а `Interaction.external_id` уникален глобально. Для production split нужно решить:

- меняем ли unique key на `(source, external_id)`;
- добавляем ли `department_id` как обязательный фильтр во все public views;
- переносим ли existing `interactions.text` в `call_artifacts` сразу или оставляем dual-read на переходный период;
- как называются активные artifact versions.

**Рекомендация:** делать полноценную миграцию сразу:

- `call_core.call_processing_runs`;
- `call_core.call_artifacts`;
- `call_public.*_v1` views;
- backfill `interactions.text -> transcript artifact`;
- LLM-1 для старых звонков не выдумывать, оставлять `llm1_missing`.

### 2. Контракт LLM-1 artifact

**Что не закрыто:** точная JSON-схема `llm1_first_pass_v1`.

**Почему важно:** сейчас LLM-1 transient inside `CallsAnalyzer._request_llm1_first_pass()`, а LLM-2 получает его как runtime context. После разделения это станет persisted upstream artifact, и EDO LLM-2 должен читать именно его.

**Минимум для фиксации:**

- `classification`;
- `summary`;
- `follow_up`;
- `data_quality`;
- `analysis_focus`;
- `schema_version`;
- `prompt_version`;
- `provider/model/account_alias`;
- `created_at`;
- `error/status`.

**Рекомендация:** зафиксировать `llm1_first_pass_v1` как отдельный contract file в repo docs и покрыть тестом: EDO analyzer не вызывает LLM-1 напрямую.

### 3. Env/secrets split

**Статус:** baseline утвержден. Нужно реализовать service-specific settings/profile.

**Почему важно:** сейчас один процесс требует OnlinePBX/STT/LLM-1/LLM-2/delivery secrets вместе. После split:

- `edo-analysis` не должен стартовать с OnlinePBX/STT/LLM-1 credentials;
- `call-processing` не должен иметь delivery credentials;
- settings validation не должна падать из-за отсутствия чужих секретов.

**Рекомендация:** ввести service-specific settings/profile:

- `APP_SERVICE=call_processing|analysis|monolith_legacy`;
- lazy/conditional validation per service;
- отдельные env examples для каждого сервиса.

### 4. Runtime split и очереди

**Что не закрыто:** будет ли один code image с разными commands или два отдельных package/app entrypoint.

**Почему важно:** текущий `docker-compose.yml` имеет один `api`, один `worker`, один `beat`; Celery default queue только `default`, а worker слушает `calls,default`.

**Рекомендация:** для первого production split использовать один image, но разные runtime commands:

- `call_processing_api`;
- `call_processing_worker -Q call_processing`;
- `analysis_api`;
- `analysis_worker -Q analysis`;
- `beat` только для scheduled orchestration, без прямого STT/LLM-1 в EDO.

### 5. Service-to-service auth и доступ команд

**Статус:** модель доступа актуализирована пользователем. Доступ назначается по service account или employee account, не по department.

**Почему важно:** просто создать `call_public` views недостаточно. Нужно понимать, кто может читать какой department и кто может запускать `ensure`.

**Рекомендация для пилота:**

- `edo-analysis -> call-processing`: internal API token/header;
- другие команды/сотрудники: read-only access по явному grant;
- admin role может настраивать доступ и запускать processing actions;
- reader role только читает artifacts;
- каждый external client имеет `client_id`, `client_type=service|employee`, `role=admin|reader`, allowed artifact kinds/read surfaces, rate limits.

### 6. Cutover и rollback

**Статус:** короткое плановое окно допустимо; feature flag и rollback остаются обязательными.

**Почему важно:** без флага пилот можно сломать при переключении `manager_daily/build_missing_and_report`.

**Рекомендация:** зафиксировать:

```text
CALL_PROCESSING_MODE=legacy|external_service
```

Правила:

- `legacy` оставляет текущий прямой путь только как rollback;
- `external_service` запрещает прямые STT/LLM-1 вызовы из EDO;
- rollback не требует DB rollback и может читать уже созданные call artifacts;
- на время cutover можно приостановить запуск новых отчетов для migration/smoke/rollback validation.

### 7. Recovery policy

**Статус:** утверждено пользователем 2026-06-08.

**Почему важно:** идея recovery закрыта, но production behavior требует конкретики:

- через сколько считать job stale;
- сколько retry для STT;
- сколько retry для LLM-1;
- какие ошибки ретраить автоматически;
- как именно помечать downstream analysis/report после позднего добора STT/LLM-1.

**Утверждено:** вынести в config:

- `CALL_PROCESSING_JOB_LEASE_SEC`;
- `CALL_PROCESSING_MAX_STT_RETRIES`;
- `CALL_PROCESSING_MAX_LLM1_RETRIES`;
- `CALL_PROCESSING_FORCE_RETRY_ALLOWED_CLIENTS=admin`;
- structured error classes: `quota_insufficient`, `rate_limited`, `auth_error`, `provider_timeout`, `provider_5xx`, `source_audio_expired`.

Approved defaults:

- stale job = no heartbeat/progress for 30 minutes;
- `STT` max attempts = initial + 2 retry;
- `LLM-1` max attempts = initial + 2 retry;
- automatic retry only for `provider_timeout`, `rate_limited`, `provider_5xx`;
- no automatic retry for `quota_insufficient`, `auth_error`, `source_audio_expired`, `source_audio_missing`;
- late transcript/LLM-1 artifacts mark downstream scope as `source_artifacts_updated_after_analysis`; admin manually decides on rerun.

## P1: вопросы, которые можно закрыть параллельно с реализацией, но до production enable

### 8. Source audio retention

**Что не закрыто:** сколько живут recording URLs / raw audio у OnlinePBX и что делать со старыми звонками.

**Почему важно:** старый звонок может быть найден в source, но audio уже недоступен. Это не должно выглядеть как random STT failure.

**Рекомендация:** добавить status/error reason:

- `source_audio_missing`;
- `source_audio_expired`;
- `source_recording_url_refresh_failed`;
- `source_auth_failed`.

### 9. PII/retention/compliance для transcript и LLM artifacts

**Статус:** утверждено на текущий релиз: хранить бессрочно, без masking/redaction ограничений.

**Почему важно:** call-processing станет платформенным источником звонков для разных команд, значит blast radius по персональным данным растет.

**Рекомендация:** минимум до production:

- не добавлять automatic deletion;
- не добавлять masking/redaction;
- audit log for artifact reads;
- no secrets/raw provider API keys in public views.

### 10. Cost/quota ownership

**Статус:** утверждено. Владелец cost/quota - admin; только admin запускает billable processing.

**Почему важно:** `ensure` может стать дорогой операцией. Другие команды смогут запускать добор артефактов, а quota blocker ударит и по пилоту ЭДО.

**Рекомендация:** добавить:

- admin-only `dry_run` / estimate mode for `ensure`;
- quota budget per provider/account;
- blocked status, который не делает массовый retry без явного разрешения;
- admin notification on quota exhaustion;
- pause further billable processing until admin action.

### 11. Operator observability

**Статус:** UI не нужен; CLI-first.

**Почему важно:** после разделения EDO UI должен показывать не только "отчет не собрался", а конкретно где остановилось: source, audio, STT, LLM-1, EDO LLM-2, render, delivery.

**Рекомендация:** добавить минимум:

- CLI command and run status endpoint;
- stage counts;
- failed calls with reason;
- retry CLI только для admin;
- no raw stack traces in CLI/API output.

### 12. API-first или SQL-first для внешних команд

**Что не закрыто:** давать ли другим командам SQL read-only уже в первом релизе или оставить только API.

**Почему важно:** SQL быстрее для аналитиков, но сильнее связывает команды с read-model контрактом и RLS.

**Рекомендация:** первый production release делать API-first, SQL read-only давать точечно по service/employee grant после стабилизации `call_public.*_v1`.

### 13. RAG/vector DB

**Что не закрыто:** будут ли embeddings включены в release.

**Рекомендация:** не включать в acceptance criteria. Заложить только расширяемость:

- стабильные `interaction_id`;
- transcript segments;
- artifact versions;
- optional future `pgvector` tables.

## Кодовые evidence points

| Evidence | Что подтверждает |
|---|---|
| `core/app/agents/calls/reporting.py:809-818` | `CallsManualReportingOrchestrator` напрямую создает `OnlinePBXIntake`, `CallsExtractor`, `CallsAnalyzer`, `CallsDelivery`. |
| `core/app/agents/calls/reporting.py:1144-1213` | Reporting layer сам делает source discovery и ingest missing interactions. |
| `core/app/agents/calls/reporting.py:2008-2014` | Текущая диагностика прямо говорит, что `manager_daily` строит source/STT/LLM-1/LLM-2 в одном path. |
| `core/app/agents/calls/analyzer.py:830-849` | `analyze_call()` всегда сначала вызывает LLM-1, затем строит LLM-2 context. |
| `core/app/agents/calls/analyzer.py:1032-1066` | LLM-1 сейчас method внутри `CallsAnalyzer`, а не persisted upstream service artifact. |
| `core/app/agents/calls/extractor.py:363-401` | STT сохраняет transcript прямо в `interaction.text` и routing metadata в `interaction.metadata`. |
| `core/app/core_shared/db/models.py:61-80` | `Interaction` пока общая таблица без service-owned schema и без artifact table. |
| `core/app/core_shared/db/models.py:108-130` | `Analysis` хранит LLM-2 raw/normalized result, но LLM-1 artifact отдельно не persisted. |
| `core/app/core_shared/api/routes/pipeline.py:11-18` | API route layer напрямую импортирует upstream internals и reporting orchestrator. |
| `docker-compose.yml:38-88` | Runtime пока один `api`, один `worker`, один `beat`, без service/queue/env separation. |
| `core/app/core_shared/config/settings.py:39-92` | Settings требуют единый набор OpenAI/STT/OnlinePBX/SMTP/Telegram secrets. |

## Предлагаемый default, если нужно идти в реализацию без новых обсуждений

Если не принимать дополнительных решений, безопасный default такой:

1. Одна физическая PostgreSQL, но с logical schemas/ownership.
2. Один code image, разные runtime services/commands.
3. API-first доступ для внешних команд; SQL read-only только как controlled add-on.
4. `CALL_PROCESSING_MODE=legacy|external_service`.
5. `llm1_first_pass_v1` фиксируется как persisted artifact contract.
6. RAG/vector DB не входит в release.
7. Backfill transcripts обязателен; old LLM-1 не фабрикуется.
8. EDO service не стартует с OnlinePBX/STT/LLM-1 secrets.

## Итоговый статус

Можно переходить к реализации после подтверждения уточненных формулировок ниже. Большая часть baseline уже утверждена.

Все архитектурные вопросы по split baseline утверждены.

Чтобы довести пакет до 100% готовности для раздачи агентам, нужен следующий артефакт: `implementation_task_pack_for_agents.md` с task cards, зависимостями, точными contract files, DoD, test matrix, merge order и handoff rules.
