# SPLIT-COMPLETE-06 — production secret partitioning

Дата подготовки: 2026-06-15
Статус: `implemented_local`

Итог реализации 2026-06-15:

- добавлены service-specific env templates без реальных секретов:
  `.env.split.common.example`, `.env.call-processing.example`,
  `.env.analysis.example`;
- split services в `docker-compose.yml` переведены на role-specific env files,
  monolith/rollback services оставлены на `.env`;
- добавлен `STRICT_SERVICE_SECRET_PARTITIONING` в `Settings`;
- `analysis` strict mode ловит upstream OnlinePBX/STT/LLM1 secrets/config;
- `call-processing` strict mode ловит downstream LLM2/LLM3 provider secrets/config;
- добавлен preflight CLI:
  `python report_scripts/split_secret_partitioning_preflight.py`;
- CLI доступен и в `core/report_scripts`, и в runtime-mounted `scripts`, чтобы
  работать внутри текущего compose mount `/app/report_scripts`;
- focused tests, ruff, py_compile and compose config checks passed.

## Цель

Технически закрепить разделение секретов между split-сервисами перед
production automation:

- `call-processing` владеет OnlinePBX, audio/source intake, STT и LLM1;
- `analysis/reporting` в `CALL_PROCESSING_MODE=external_service` не имеет и не
  требует OnlinePBX/STT/LLM1 secrets;
- `analysis/reporting` использует только готовые upstream artifacts через
  `call-processing` API и выполняет LLM2/LLM3/report/delivery;
- `monolith_legacy` остается rollback-путем и может использовать общий набор
  секретов до cutover.

Ключевой результат: разделение должно быть не только логическим в коде, но и
проверяемым на уровне env/config/docker compose.

## Почему это нужно

Сейчас split-сервисы в `docker-compose.yml` используют общий `env_file: .env`.
Это удобно для локальной разработки, но для production split опасно:

- `analysis` может случайно получить OnlinePBX/STT/LLM1 ключи;
- ошибка настройки может незаметно вернуть часть обработки в legacy path;
- невозможно доказать, что `analysis` действительно работает только с
  готовыми upstream artifacts;
- budget/quota/security границы между сервисами размываются.

Уже существующая settings validation частично поддерживает service boundaries:

- `APP_SERVICE=analysis` требует `CALL_PROCESSING_MODE=external_service`;
- `APP_SERVICE=analysis` требует `CALL_PROCESSING_API_BASE_URL` и
  `CALL_PROCESSING_ACCESS_GRANT_JSON`;
- OnlinePBX/STT secrets обязательны только для `APP_SERVICE=call_processing` или
  `monolith_legacy`.

Нужно довести это до runtime profiles, preflight и тестов.

## Целевая модель

### 1. `call-processing` profile

Сервисы:

- `call_processing_api`;
- `call_processing_worker`;
- future scheduled STT/upstream beat/entrypoint.

Должны иметь:

- DB/Redis;
- OnlinePBX source credentials;
- STT credentials/providers;
- LLM1 credentials/providers;
- cost catalog;
- alert email config для technical alerts, если alert отправляется из
  upstream-service;
- service-to-service access grant validation.

Не должны иметь как обязательные:

- LLM2 credentials;
- LLM3 credentials;
- business delivery credentials для manager-facing report email;
- Telegram test/operator delivery credentials, если доставка остается в
  `analysis/reporting`.

### 2. `analysis/reporting` profile

Сервисы:

- `analysis_api`;
- `analysis_worker`;
- `analysis_beat`.

Должны иметь:

- DB/Redis;
- `APP_SERVICE=analysis`;
- `CALL_PROCESSING_MODE=external_service`;
- `CALL_PROCESSING_API_BASE_URL`;
- `CALL_PROCESSING_ACCESS_GRANT_JSON`;
- LLM2 credentials/providers;
- LLM3 credentials/providers;
- SMTP/Telegram delivery credentials;
- alert email config для reporting/delivery blockers.

Не должны иметь:

- `ONLINEPBX_DOMAIN`;
- `ONLINEPBX_API_KEY`;
- `ASSEMBLYAI_API_KEY`;
- `OPENAI_API_KEY_STT_MAIN`;
- `AI_STT_PROVIDERS_JSON`;
- `OPENAI_API_KEY_LLM1_MAIN`;
- LLM1-only provider aliases/secrets.

Если эти переменные случайно присутствуют в `analysis` profile, preflight должен
выдать warning или fail, в зависимости от режима.

### 3. `monolith_legacy` profile

Остается rollback path:

- может читать общий `.env`;
- может иметь OnlinePBX/STT/LLM1/LLM2/LLM3/delivery secrets;
- должен быть явно отделен от split production profile, чтобы не смешивать
  режимы.

## Scope

### In scope

- Добавить service-specific env templates/examples без реальных секретов.
- Обновить `docker-compose.yml` или добавить override/profile, чтобы split
  services могли использовать разные env files:
  - base/common env;
  - call-processing env;
  - analysis env.
- Добавить/обновить config validation и preflight:
  - `analysis` стартует без OnlinePBX/STT/LLM1 secrets;
  - `call-processing` стартует без LLM2/LLM3/delivery secrets, если они не
    нужны;
  - `monolith_legacy` не ломается.
- Добавить focused tests на service boundary.
- Обновить runbook/docs.

### Out of scope

- Ротация реальных ключей.
- Изменение самих provider models.
- Полный production cutover.
- Реальный scheduled/pipeline run.
- Новый UI.
- Удаление legacy mode.

## Предлагаемые изменения

### 1. Env files

Рекомендуемый набор:

```text
.env.example
.env.split.common.example
.env.call-processing.example
.env.analysis.example
```

Вариант для production/local secret files, которые не должны попадать в git:

```text
.env.split.common
.env.call-processing
.env.analysis
```

`.gitignore` должен явно игнорировать реальные service-specific env files.

Пример логики:

- `.env.split.common.example`: DB, Redis, app env, cost config, shared non-secret
  defaults.
- `.env.call-processing.example`: OnlinePBX, STT, LLM1, upstream quota.
- `.env.analysis.example`: call-processing API grant, LLM2, LLM3, SMTP/Telegram,
  alert delivery.

### 2. Docker compose split profile

Текущие split services читают общий `.env`. Нужно заменить/расширить это на
service-specific env files для split profile.

Целевая схема:

```yaml
call_processing_api:
  env_file:
    - .env.split.common
    - .env.call-processing

call_processing_worker:
  env_file:
    - .env.split.common
    - .env.call-processing

analysis_api:
  env_file:
    - .env.split.common
    - .env.analysis

analysis_worker:
  env_file:
    - .env.split.common
    - .env.analysis

analysis_beat:
  env_file:
    - .env.split.common
    - .env.analysis
```

Чтобы не сломать локальную разработку, допустим один из двух вариантов:

1. Добавить отдельный `docker-compose.split.yml`.
2. Оставить основной compose совместимым, но в split services использовать
   optional env-file behavior через documented command/runbook.

Выбор нужно сделать при реализации после проверки, какая версия Docker Compose
доступна на сервере и поддерживает ли `required: false` для env files.

### 3. Settings validation

Уточнить `Settings.validate_service_secret_boundaries`:

- `APP_SERVICE=analysis` должен fail-fast, если:
  - `CALL_PROCESSING_MODE != external_service`;
  - нет `CALL_PROCESSING_API_BASE_URL`;
  - нет `CALL_PROCESSING_ACCESS_GRANT_JSON`.
- `APP_SERVICE=analysis` не должен требовать:
  - OnlinePBX;
  - STT;
  - LLM1.
- Добавить optional strict mode:

```text
STRICT_SERVICE_SECRET_PARTITIONING=true
```

В strict mode `APP_SERVICE=analysis` должен падать, если видит upstream secrets:

- `ONLINEPBX_API_KEY`;
- `ASSEMBLYAI_API_KEY`;
- `OPENAI_API_KEY_STT_MAIN`;
- `OPENAI_API_KEY_LLM1_MAIN`;
- enabled STT/LLM1 provider config.

Для `call-processing` strict mode должен падать, если видит явно downstream-only
secrets:

- `OPENAI_API_KEY_LLM2_MAIN`;
- `OPENAI_API_KEY_LLM3_MAIN`;
- business SMTP password, если delivery остается только в analysis.

Если strict mode пока рискован, первый pass может сделать это warning-only в
preflight, но acceptance должен включать хотя бы одну fail-fast проверку для
`analysis`.

### 4. Preflight CLI

Добавить CLI, например:

```bash
python report_scripts/split_secret_partitioning_preflight.py --service analysis
python report_scripts/split_secret_partitioning_preflight.py --service call-processing
```

Вывод должен быть машинно и человеко-читаемым:

```json
{
  "service": "analysis",
  "status": "passed",
  "required_present": [...],
  "forbidden_present": [],
  "warnings": [],
  "strict": true
}
```

Для `analysis` preflight должен проверять:

- required: `CALL_PROCESSING_API_BASE_URL`,
  `CALL_PROCESSING_ACCESS_GRANT_JSON`, LLM2/LLM3 provider route;
- forbidden: OnlinePBX/STT/LLM1 secrets;
- runtime: `CALL_PROCESSING_MODE=external_service`,
  `AI_LLM2_INPUT_PROFILE=compact`;
- no subagent/simulation unless explicitly configured.

Для `call-processing` preflight должен проверять:

- required: OnlinePBX, STT, LLM1 route;
- forbidden/warning: LLM2/LLM3/delivery secrets;
- runtime: `APP_SERVICE=call_processing`.

### 5. Tests

Добавить focused tests:

1. `APP_SERVICE=analysis` starts with external-service config and no
   OnlinePBX/STT/LLM1 secrets.
2. `APP_SERVICE=analysis` fails when `CALL_PROCESSING_MODE=legacy`.
3. `APP_SERVICE=analysis` fails without `CALL_PROCESSING_API_BASE_URL`.
4. Strict analysis preflight fails when upstream secrets are present.
5. `APP_SERVICE=call_processing` starts with OnlinePBX/STT/LLM1 and no LLM2/LLM3.
6. Monolith legacy remains compatible with old `.env`.
7. Docker compose config for split profile resolves service-specific env plan.

### 6. Docs

Обновить:

- `docs/call_processing_split/COMPLETION_ROADMAP.md`;
- `docs/call_processing_split/CUTOVER_ROLLBACK_RUNBOOK.md`;
- `docs/call_processing_split/IMPLEMENTATION_STATUS.md`, если используется как
  активный status source;
- `docs/ACTIVE_WORK_STATE.md` после реализации;
- `.env.example` and new env examples.

## Acceptance Criteria

1. Есть documented split env plan: какие env files используются каждым сервисом.
2. В git есть только examples/templates, без реальных секретов.
3. `analysis` profile может пройти config/preflight без OnlinePBX/STT/LLM1
   secrets.
4. `analysis` profile не может стартовать в `CALL_PROCESSING_MODE=legacy`.
5. `call-processing` profile может пройти config/preflight без LLM2/LLM3
   secrets.
6. Strict/preflight режим ловит случайную передачу upstream secrets в
   `analysis`.
7. Legacy/monolith path не сломан.
8. Focused tests and compose config checks pass.

## Test Plan

Минимальные проверки:

```bash
python3 -m py_compile \
  core/app/core_shared/config/settings.py \
  core/report_scripts/split_secret_partitioning_preflight.py

docker compose config >/tmp/asa_compose_config.yml
docker compose --profile split config >/tmp/asa_split_compose_config.yml

docker compose exec -T api python -m pytest -q \
  /app/tests/test_settings.py \
  /app/tests/test_call_processing_runtime_split.py \
  -k "service_secret or app_service or call_processing_mode or split"

git diff --check
```

Если будет добавлен отдельный test file:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_service_secret_partitioning.py
```

Manual smoke без реального pipeline:

```bash
docker compose --profile split run --rm analysis_api \
  python report_scripts/split_secret_partitioning_preflight.py --service analysis

docker compose --profile split run --rm call_processing_api \
  python report_scripts/split_secret_partitioning_preflight.py --service call-processing
```

## Разделение по агентам

### Agent A — config/settings boundary

- Проверить текущую `Settings` validation.
- Добавить strict/warning boundary для forbidden secrets.
- Покрыть unit tests.
- Не менять provider routing behavior шире, чем нужно.

### Agent B — compose/env profiles

- Подготовить service-specific env examples.
- Обновить compose/override/runbook.
- Проверить `docker compose config` and split profile config.
- Не добавлять реальные секреты.

### Agent C — preflight CLI

- Добавить CLI для анализа текущего env.
- Вернуть JSON summary and exit codes.
- Покрыть tests/fakes.

### Main agent — integration

- Проверить, что `analysis` без upstream secrets проходит preflight.
- Проверить, что accidental upstream secrets в strict mode ловятся.
- Прогнать focused tests.
- Обновить roadmap/progress.
- Не запускать реальный pipeline без отдельного approval.
