# REPORT_BACKLOG_PRIORITIZATION

## Назначение
Этот документ фиксирует rule-based prioritization для задач по отчёту.
Он нужен, чтобы одинаково решать, какую report task брать сразу, какую ставить вторым этапом, а какую относить только к post-pilot / last-priority layer.

## Три корзины задач по отчёту

### Делать сейчас

Критерии:
- не требуют новых подключений;
- не требуют новых внешних данных;
- не меняют analyzer contract;
- не требуют новой reporting architecture;
- напрямую улучшают то, что видит бизнес.

Сюда относятся:
- structure/layout polish;
- top summary simplification;
- wording/readability;
- visual hierarchy;
- PDF/renderer polish;
- complete and honest list-of-calls presentation;
- consistency between full PDF and short delivery wrapper;
- polish of editable business-facing report blocks.

Это основной scope `Business-ready Report Pack`.

### Делать вторым этапом

Критерии:
- внешние интеграции не нужны;
- используются только уже существующие данные;
- задача достраивает внутренний механизм отчёта;
- задача уже не только про оформление, но ещё не про full redesign.

Сюда относятся:
- richer deterministic assembly from existing fields;
- better focus / key problem / signal selection rules;
- stronger use of `score_by_stage`, `follow_up`, `evidence_fragments`, `product_signals`;
- bounded report-composer over existing payload;
- richer assembly inside existing normalized contract, without new standing schema.

Это второй слой работ. Он допустим только после primary `Business-ready Report Pack` polish и не должен смешиваться с external integrations.

### Делать в последнюю очередь

Критерии:
- нужны новые подключения / новые источники данных;
- нужны новые runtime entities / new reporting schema;
- нужна новая aggregation/coaching architecture;
- лучше делать после пилота.

Сюда относятся:
- CRM / Bitrix / external sums;
- revenue / pricing / amount logic;
- `call_outcome`, `customer_card`, `next_step structure` as new standing reporting layer;
- day-level aggregator;
- history / baseline storage layer;
- coaching / pattern engine;
- full rich daily report mechanism.

Это post-pilot / last-priority layer. Это не относится к `Business-ready Report Pack`.

## Rule For Taking Report Tasks

- если задача про оформление и формулировки, берём сразу;
- если задача про внутренний механизм, но без новых подключений, ставим вторым этапом;
- если задача про внешние данные, CRM, суммы или новую архитектуру, относим в последнюю очередь.

## Relation To Current Roadmap

- `Business-ready Report Pack` = first-priority report work before pilot;
- second-stage report tasks не должны блокировать pilot perception layer;
- full report mechanism upgrade остаётся separate post-pilot track.

## Current Priority Update — 2026-05-21

The 2026-05-19/20 report reviews showed that some report-quality work cannot be
treated as pure layout polish: rigid micro-fields were flattening meaning in
`Ситуация дня`, `Разбор звонка`, `Голос клиента`, and call-list context.

Current first-priority work:
- keep the accepted narrative direction for current semantic blocks;
- refresh LLM2-ready data for one 2026-05-19 manager and rebuild a ready-only
  `manager_daily` preview;
- compare the fresh report artifact with the accepted semantic baseline;
- close DDC-11 residual by making `Ситуация дня` action/examples
  scene-specific;
- clean legacy tests that still assert the old `Разбор звонка` table shape.

Explicitly deferred from the immediate step:
- broad evidence/action consistency for `ДЕНЬГИ НА СТОЛЕ`, warm pipeline,
  `ЧЕЛЛЕНДЖ`, and other non-current blocks;
- external CRM/revenue integrations;
- full rich daily mechanism upgrade.

Rule refinement:
- If a block loses meaning because the final prompt/render shape is too rigid,
  it may be handled inside `Business-ready Report Pack` as bounded
  semantic/report-block work.
- If a task requires new standing entities, external data, historical
  aggregation, or a new coaching engine, it remains post-pilot unless explicitly
  reopened.
