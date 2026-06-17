# PILOT-30: Optional evaluation OpenAI diarization STT model

Дата: 2026-06-16
Статус: optional / deferred
Связанные задачи: `PILOT-29`, `STT`, `call_processing_split`

## Контекст

OpenAI предоставляет модель `gpt-4o-transcribe-diarize`, которая поддерживает
speaker diarization и `diarized_json`. Это потенциально может улучшить speaker
segments по сравнению с текущим `whisper-1`.

Но в рамках текущего этапа принято решение: **не переключать production STT
model** и сначала усилить текущий Whisper-контур через `PILOT-29`.

## Цель optional-задачи

Позже, отдельным controlled experiment, сравнить:

- текущий `whisper-1` + LLM1 role attribution;
- `gpt-4o-transcribe-diarize` + LLM1 role attribution.

## Что не делаем сейчас

- Не меняем `AI_STT_PROVIDERS_JSON`;
- не включаем `gpt-4o-transcribe-diarize` в production;
- не меняем cost catalog;
- не запускаем массовый перерасчет STT;
- не меняем downstream contracts до отдельного утверждения.

## Предварительная гипотеза

`gpt-4o-transcribe-diarize` может дать лучшее техническое разделение speaker
segments, но роль `manager/client` все равно должна подтверждаться LLM1 или
другим semantic role attribution слоем. Speaker label от STT не равен
бизнес-роли.

## Будущий evaluation plan

1. Выбрать 10-20 звонков:
   - короткие;
   - средние;
   - длинные;
   - с техподдержкой;
   - с продажной договоренностью;
   - с плохим качеством связи.
2. Запустить controlled STT только на копии/экспериментальном route.
3. Сравнить:
   - WER/читаемость transcript;
   - количество speaker segments;
   - корректность speaker boundaries;
   - стабильность role attribution после LLM1;
   - стоимость;
   - влияние на LLM2/report.
4. Не переиспользовать экспериментальные artifacts в production без отдельного
   решения.

## Acceptance criteria для будущего решения

Переход можно рассматривать только если:

- качество speaker segmentation заметно лучше на реальных звонках;
- LLM2/report получают меньше ошибок по ролям;
- стоимость приемлема;
- retry/error behavior понятен;
- есть fallback на текущий route;
- обновлены docs/runtime profiles/cost catalog.

## Definition of Done

Для текущего этапа эта задача считается зафиксированной, но не реализуемой.
Следующий шаг возможен только после завершения или проверки `PILOT-29`.
