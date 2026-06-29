# PILOT-39B: Universal LLM1 call card

Дата: 2026-06-29
Статус: `implemented_first_pass`

Связанные документы:

- [`docs/PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md`](PILOT39_COMPANY_WIDE_TRANSCRIPTION_SERVICE_TZ.md)
- [`docs/PILOT_BACKLOG.md`](PILOT_BACKLOG.md)
- [`docs/call_processing_split/COMPLETION_ROADMAP.md`](call_processing_split/COMPLETION_ROADMAP.md)

## Цель

После расширения `call-processing` на всю компанию LLM1 должен формировать не
только вход для ЭДО-анализа, но и универсальную карточку звонка. Эта карточка
нужна для поиска, отбора и будущей маршрутизации звонков по темам, продуктам,
отделам, горячести и итогам.

Целевая upstream-цепочка:

```text
OnlinePBX -> STT -> transcript/segments -> LLM1 universal call card
```

LLM2/LLM3 и отчеты при этом не расширяются на всю компанию.

## Принципы

1. **Смысл формирует только LLM.** Код может нормализовать форму, но не должен
   достраивать тему, намерение, outcome или применимость анализа из transcript
   эвристиками.
2. **Не сужать смысл под ЭДО.** Карточка должна подходить для всей компании:
   продажи, сервис, техподдержка, юридические продукты, документы, прочие
   направления.
3. **Не ломать старые артефакты.** Добавление должно быть backward-compatible
   для `llm1_first_pass_v1`; старые artifacts без карточки продолжают читаться.
4. **Не дублировать transcript/segments.** LLM1 artifact хранит смысловую
   карточку и качество, а не полный текст звонка.
5. **Не запускать provider calls в рамках внедрения.** Проверяем код и fake/unit
   paths; реальный прогон будет отдельным rollout-шагом.

## Что добавить в контракт

Добавить в `llm1_first_pass_v1` optional top-level field:

```json
{
  "call_card": {
    "schema_version": "universal_call_card_v1",
    "topic": "короткая тема звонка",
    "product_area": "ЭДО | техподдержка | юр направление | ... | unknown",
    "department_hint": "какой отдел/направление вероятно нужно",
    "request_type": "sales | support | service | legal_product | billing | document_flow | internal | other | unknown",
    "client_intent": "что хотел клиент",
    "manager_intent": "что пытался сделать менеджер",
    "urgency": "hot | warm | cold | service | unknown",
    "business_outcome": "agreement | reschedule | refusal | open | service_resolved | transferred | no_answer | unknown",
    "analysis_eligibility": "eligible | not_eligible | review_required",
    "eligibility_reason": "короткая причина",
    "call_essence": "1-2 предложения: что произошло и чем закончилось",
    "contact_name": "ФИО/имя только если явно прозвучало в STT, иначе null",
    "tags": ["короткие поисковые теги"],
    "evidence": ["короткие фрагменты/сигналы из STT"],
    "confidence": "low | medium | high"
  }
}
```

Поле `contact_name` не должно вытаскиваться из CRM/Битрикс или metadata. Если
в STT нет явного имени клиента, значение должно быть `null`.

## Что изменить

### 1. LLM1 prompt/context

Файлы:

- `core/app/agents/calls/prompts/classify.md`
- `core/app/agents/calls/analyzer.py`

Нужно:

- добавить `call_card` в `expected_output_shape`;
- добавить `call_card` в optional/required instructions так, чтобы LLM1
  возвращал его вместе с текущими `classification`, `summary`, `follow_up`,
  `data_quality`, `analysis_focus`, `speaker_role_mapping`;
- явно указать, что карточка универсальная, не ЭДО-only;
- явно запретить выдумывать факты и contact name;
- в retry prompt добавить `call_card` в список допустимых ключей.

### 2. Schema и persistence

Файлы:

- `core/app/agents/call_processing/schemas.py`
- `core/app/agents/call_processing/service.py`

Нужно:

- добавить optional `call_card: dict[str, Any] = Field(default_factory=dict)` в
  `LLM1FirstPassPayload`;
- при записи `llm1_first_pass` artifact сохранять `call_card`;
- не менять `LLM1_FIRST_PASS_SCHEMA_VERSION`, если это можно сделать
  backward-compatible.

### 3. Normalization и compact context

Файл:

- `core/app/agents/calls/analyzer.py`

Нужно:

- нормализовать `call_card` как dict;
- ограничить списки `tags/evidence` разумным количеством элементов, чтобы
  карточка не раздувала input LLM2;
- добавить compact `call_card` в `_compact_llm1_first_pass`;
- при отсутствии `call_card` в старом artifact возвращать пустой dict, не
  падать и не пытаться восстановить смысл из transcript deterministic-кодом.

## Чего не делать

- Не запускать STT/LLM1/LLM2/LLM3 provider calls.
- Не менять scope analysis/reporting.
- Не добавлять отдельный `call_card_v2` artifact kind.
- Не добавлять ЭДО-специфичные обязательные поля в универсальную карточку.
- Не использовать deterministic business outcome resolver для смысловой
  квалификации карточки.

## Acceptance criteria

- Новые LLM1 responses могут содержать `call_card`, и она сохраняется в
  `llm1_first_pass_v1`.
- Старые LLM1 artifacts без `call_card` продолжают валидироваться.
- External-service analysis читает artifacts с `call_card` без ошибок.
- Compact LLM2 input получает короткую карточку, но без transcript/segments
  duplication.
- Unit/focused tests покрывают:
  - schema backward compatibility;
  - artifact persistence with `call_card`;
  - normalizer with missing `call_card`;
  - compact context includes `call_card`;
  - contact name остается `null`, если в LLM output пусто/нет значения.

## Проверки

Минимально:

```bash
python3 -m py_compile \
  core/app/agents/calls/analyzer.py \
  core/app/agents/call_processing/schemas.py \
  core/app/agents/call_processing/service.py

git diff --check

docker compose exec -T api python -m pytest -q \
  /app/tests/test_call_processing_service.py \
  /app/tests/test_call_processing_llm1_external_mode.py \
  /app/tests/test_llm2_layered_runtime.py \
  -k "llm1 or first_pass or compact or call_card"
```

Если часть тестов не существует или keyword выбирает мало кейсов, добавить
точечные unit tests рядом с существующими тестами LLM1/call-processing.

## Результат реализации

Статус: `implemented_first_pass` на 2026-06-29.

Сделано:

- `call_card` добавлен в `llm1_first_pass_v1` как backward-compatible optional
  field без смены `LLM1_FIRST_PASS_SCHEMA_VERSION`;
- LLM1 prompt/context просит универсальную карточку звонка, не ЭДО-only, с
  запретом выдумывать факты и брать `contact_name` из CRM/metadata;
- normalizer принимает старые artifacts без `call_card` как `{}`, нормализует
  только форму, лимитирует `tags/evidence` и не выводит смысл из transcript;
- `call_card` сохраняется в persisted `llm1_first_pass` artifact;
- compact LLM2 context получает короткую `call_card` без transcript/segments
  duplication;
- focused tests покрывают backward compatibility, persistence, missing
  `call_card`, compact context и `contact_name=null` при пустом LLM value.

Проверки:

- `python3 -m py_compile core/app/agents/calls/analyzer.py core/app/agents/call_processing/schemas.py core/app/agents/call_processing/service.py` — OK;
- `git diff --check` — OK;
- `docker compose exec -T api python -m pytest -q /app/tests/test_call_processing_service.py /app/tests/test_call_processing_llm1_external_mode.py /app/tests/test_llm2_layered_runtime.py -k "llm1 or first_pass or compact or call_card"` — `10 passed, 32 deselected`.

Реальные STT/LLM/provider calls, production pipeline, email и Telegram не
запускались.
