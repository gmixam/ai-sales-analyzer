# PILOT-29: Усиление speaker role attribution на текущем Whisper STT

Дата: 2026-06-16
Статус: implemented_first_pass
Связанные задачи: `PILOT-25`, `PILOT-30`, `call_processing_split`, `LLM1`

## Статус реализации

First pass внедрен 2026-06-16:

- STT route остается OpenAI `whisper-1`; provider/model не менялись.
- Whisper transcript segments больше не трактуются как надежная speaker
  diarization: `speaker_a_is_manager=False`, в metadata сохраняется
  `diarization_source=whisper_time_segments_without_speaker_labels` и warning.
- `llm1_first_pass_v1` получил поле `speaker_role_mapping`.
- LLM1 prompt/context требует определять роли только по доказательствам из STT,
  иначе возвращать `unknown` + low confidence/warnings.
- LLM2 compact/full input получает `speaker_role_mapping` через
  `llm1_first_pass`; compact input ограничивает turns/evidence, чтобы не
  раздувать payload.
- Старые LLM1 artifacts без `speaker_role_mapping` продолжают работать.

До перевода в `done`: controlled sample review на 5-10 реальных звонках после
следующего прогона и ручная проверка, что очевидные роли не перепутаны.

## Контекст

Сейчас основной STT route в runtime настроен через `AI_STT_PROVIDERS_JSON` на
OpenAI `whisper-1`. В коде также есть AssemblyAI adapter, но текущий production
route для STT - Whisper.

Важное ограничение: `whisper-1` не дает полноценную speaker diarization. Он
может вернуть временные `segments`, но это не гарантирует разметку "кто
говорил". В текущем коде Whisper segments нормализуются в общий формат с
`speaker="A"`:

- `core/app/agents/calls/extractor.py`
  - `_transcribe_whisper(...)`
  - `_normalize_whisper_segments(...)`

Из-за этого downstream может получать видимость speaker segments, но без
реального разделения ролей `manager/client`. Для качества LLM2/LLM3 и отчета
важно понимать, кто говорит, но нельзя жестко считать `speaker A = manager`.

## Принятое решение

На этом этапе **не меняем STT model** и **не переключаемся на
`gpt-4o-transcribe-diarize`**.

Основная задача `PILOT-29`: усилить текущий Whisper-контур через LLM1 role
attribution:

```text
Whisper transcript / time segments
  -> LLM1 determines speaker roles / dialogue turns where possible
  -> confidence + evidence + warnings
  -> LLM2 получает более честный контекст ролей
```

Переход на OpenAI diarization model выносится в отдельную optional-задачу
`PILOT-30`.

## Цель

Сделать так, чтобы при использовании `whisper-1` система:

- не притворялась, что технически знает speaker diarization;
- не считала `speaker A = manager` без доказательства;
- на уровне LLM1 определяла роли участников по смыслу и признакам разговора;
- сохраняла confidence/evidence/warnings;
- передавала LLM2 честную информацию: `manager`, `client` или `unknown`.

## Что не делаем

- Не меняем модель STT.
- Не включаем `gpt-4o-transcribe-diarize`.
- Не добавляем AssemblyAI как production route.
- Не делаем deterministic смысловую классификацию ролей.
- Не заставляем Report Layer самостоятельно вытаскивать роли из transcript.
- Не блокируем анализ, если role attribution низкой уверенности.

## Текущая техническая проблема

### Whisper adapter

`_normalize_whisper_segments(...)` сейчас возвращает:

```json
[
  {
    "speaker": "A",
    "text": "...",
    "start_ms": 0,
    "end_ms": 1000
  }
]
```

Это технический placeholder, а не реальная диаризация.

### `speaker_a_is_manager`

В `TranscriptResult` для Whisper сейчас выставляется:

```python
speaker_a_is_manager=True
```

Для Whisper это опасная презумпция: speaker `A` не является доказанным
менеджером.

## Требуемая модель данных

Добавить или расширить LLM1 output так, чтобы он мог возвращать блок:

```json
{
  "speaker_role_mapping": {
    "source": "llm1_role_attribution",
    "stt_provider": "openai",
    "stt_model": "whisper-1",
    "diarization_source": "whisper_time_segments_without_speaker_labels",
    "roles": [
      {
        "raw_speaker": "A",
        "role": "unknown",
        "confidence": "low",
        "evidence": [],
        "notes": "Whisper did not provide speaker diarization"
      }
    ],
    "dialogue_turns": [
      {
        "role": "manager",
        "text": "Добрый день, это Тимур, Договор24...",
        "confidence": "medium",
        "evidence": ["представился как сотрудник Договор24"]
      },
      {
        "role": "client",
        "text": "Да, слушаю...",
        "confidence": "medium",
        "evidence": ["отвечает на входящий контакт"]
      }
    ],
    "quality": {
      "diarization_quality": "low|medium|high",
      "role_attribution_quality": "low|medium|high",
      "warnings": [
        "technical_speaker_labels_unavailable",
        "roles_inferred_from_text_only"
      ]
    }
  }
}
```

Формат можно адаптировать под существующий LLM1 schema, но обязательные идеи:

- `role`: `manager | client | unknown | context`;
- `confidence`: `low | medium | high`;
- `evidence`: короткие фразы/основания;
- `warnings`: почему роль может быть ненадежной;
- raw STT speaker label не превращается в manager/client без доказательства.

## Правила role attribution

LLM1 должен определять роль по смыслу, а не по техническому speaker label.

Сильные признаки менеджера:

- представился как сотрудник `Договор24`;
- называет себя менеджером/представителем компании;
- объясняет продукт/тариф/подписку/процесс сервиса;
- предлагает отправить КП/счет/ссылку/инструкцию;
- ведет клиента по процессу;
- задает вопросы как продавец/саппорт.

Сильные признаки клиента:

- отвечает на звонок;
- описывает свою задачу/компанию/проблему;
- задает вопросы по продукту/цене/сервису;
- принимает или отклоняет предложение;
- просит отправить информацию;
- говорит от лица покупателя/пользователя сервиса.

Если признаки конфликтуют или их мало:

- роль = `unknown`;
- confidence = `low`;
- warning = `role_attribution_uncertain`.

## Как передавать в LLM2

LLM2 должен получать:

- transcript text;
- LLM1 summary/facts;
- `speaker_role_mapping`;
- `dialogue_turns`, если они есть;
- warnings по качеству diarization/role attribution.

LLM2 не должен считать `unknown` как manager/client. Если роль неизвестна,
он должен опираться на содержание реплик и осторожно формулировать выводы.

## Что изменить в коде

Точные места нужно уточнить при реализации, но ожидаемые зоны:

1. `core/app/agents/calls/extractor.py`
   - для Whisper убрать или нейтрализовать презумпцию `speaker_a_is_manager=True`;
   - добавить metadata marker, что diarization недоступна/низкой уверенности;
   - не выдавать `speaker="manager"` на STT level.

2. LLM1 prompt / schema / adapter
   - найти текущий prompt/schema LLM1;
   - добавить задачу role attribution;
   - добавить output contract для `speaker_role_mapping`;
   - сохранить блок в `llm1_first_pass` artifact.

3. Call-processing artifact persistence
   - убедиться, что `llm1_first_pass` сохраняет новый блок;
   - не ломать reuse старых artifacts без этого блока.

4. LLM2 input builder
   - добавить `speaker_role_mapping` в compact/full input;
   - передавать warnings как contextual caveat;
   - не увеличивать input чрезмерно: передавать только короткие dialogue turns и
     evidence, а не весь transcript второй раз.

5. Tests
   - покрыть Whisper path без speaker labels;
   - покрыть LLM1 role attribution contract;
   - покрыть LLM2 input содержит mapping;
   - покрыть старые artifacts без mapping не падают.

## Acceptance criteria

1. При `whisper-1` система не помечает технический `speaker A` как
   `manager` без LLM1 evidence.
2. В `llm1_first_pass` появляется `speaker_role_mapping` или equivalent block.
3. У role mapping есть confidence/evidence/warnings.
4. LLM2 input получает role mapping и warning о качестве diarization.
5. Старые LLM1 artifacts без mapping продолжают работать.
6. Report Layer не делает role attribution самостоятельно.
7. STT model остается `whisper-1`.
8. `gpt-4o-transcribe-diarize` не включается в рамках этой задачи.

## Test plan

Focused tests:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_call_processing_service.py \
  /app/tests/test_call_processing_contracts.py \
  /app/tests/test_call_processing_llm1_external_mode.py \
  /app/tests/test_llm2_layered_runtime.py \
  -k "speaker or role or llm1 or transcript_segments"
```

Факт 2026-06-16: `9 passed, 34 deselected`.

Дополнительно проверен конкретный compact LLM2 input:

```bash
docker compose exec -T api python -m pytest -q \
  /app/tests/test_llm2_layered_runtime.py::LLM2LayeredRuntimeTests::test_compact_payload_passes_coaching_context_to_llm2d
```

Факт 2026-06-16: `1 passed`.

Дополнительно:

```bash
python3 -m py_compile \
  core/app/agents/calls/extractor.py \
  core/app/agents/call_processing/service.py

git diff --check
```

После реализации:

- controlled run на 5-10 звонках с готовым audio/STT;
- проверить несколько call artifacts:
  - transcript;
  - transcript_segments;
  - llm1_first_pass;
  - llm2 input package;
- вручную посмотреть, не перепутаны ли manager/client в очевидных сценах.

## Разделение по агентам

### Agent A — STT/metadata boundary

- Проверить Whisper adapter;
- убрать опасную презумпцию `speaker_a_is_manager=True` для Whisper;
- добавить metadata marker о качестве diarization;
- покрыть тестами.

### Agent B — LLM1 role attribution contract

- Найти LLM1 prompt/schema;
- добавить role attribution block;
- сохранить output в `llm1_first_pass`;
- обеспечить backward compatibility.

### Agent C — LLM2 input propagation

- Добавить role mapping в LLM2 input;
- убедиться, что input не раздувается;
- добавить tests на compact input.

### Controller

- Свести изменения;
- проверить, что STT model не изменилась;
- прогнать focused tests;
- сделать controlled sample review.

## Риски

- LLM1 может ошибаться в ролях на коротких звонках.
  - Защита: confidence/warnings и `unknown`, если нет доказательств.
- Input LLM2 может вырасти.
  - Защита: передавать только mapping + короткие turns/evidence.
- Может возникнуть желание чинить это в Report Layer.
  - Защита: Report Layer только отображает/использует готовые роли, но не
    определяет их.

## Definition of Done

- `PILOT-29` реализован минимум как `implemented_first_pass`;
- текущий STT route остается Whisper;
- role attribution появляется в LLM1 artifacts;
- LLM2 получает role mapping;
- нет жесткой презумпции `speaker A = manager`;
- focused tests passed;
- controlled sample review показывает улучшение или честный `unknown`, если роль
  определить нельзя.
