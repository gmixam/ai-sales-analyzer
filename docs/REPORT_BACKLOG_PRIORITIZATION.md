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
