# VoiceOfCustomerComposer v2 Prompt Contract

Purpose: compose the manager daily "Голос клиента" block from already extracted
customer-signal candidates. This is an LLM3 report-composition contract, not
primary call analysis.

The goal is to preserve meaning. This block answers two manager questions:

1. What does the client actually mean by this phrase or reaction?
2. How should the manager work with that meaning next?

Do not flatten a customer signal into a short table cell if the scene needs a
few sentences to be clear.

## Input

The model receives bounded JSON:

```json
{
  "contract_version": "voice_of_customer_composer_v2",
  "signals": [
    {
      "signal_id": "string",
      "call_id": "string",
      "client_call_reference": "string or null",
      "quote": "short customer quote",
      "quote_context": "mini-scene or contextual excerpt",
      "interpretation": "what this signal means",
      "manager_action": "recommended action",
      "customer_signal": "category or null",
      "source": "string",
      "evidence_refs": []
    }
  ],
  "output_rules": {
    "rows_min": 1,
    "rows_max": 4,
    "narrative_preferred": true,
    "must_use_customer_or_customer_context_signal": true,
    "fragment_must_be_mini_scene": true,
    "recommendation_must_follow_signal": true
  }
}
```

## Output

Return exactly one JSON object compatible with Report Layer:

```json
{
  "status": "verified | insufficient | no_data",
  "is_placeholder": false,
  "customer_scenes": [
    {
      "signal_id": "string",
      "call_id": "string",
      "client_call_reference": "string",
      "scene_summary": "what was happening around the customer signal",
      "quote": "exact customer quote",
      "quote_context": "mini-scene from the provided signal",
      "dialogue_evidence": [
        {"speaker": "client | manager | unknown", "text": "replica"}
      ],
      "customer_meaning": "what the customer signal means",
      "manager_response": "what the manager should do next",
      "why_action_follows": "why this action follows from this signal",
      "customer_signal": "category",
      "source": "voice_of_customer_composer"
    }
  ],
  "situations": [
    {
      "call_id": "string",
      "client_call_reference": "string",
      "quote": "customer quote",
      "quote_context": "mini-scene",
      "context": "meaning plus action",
      "interpretation": "meaning plus action",
      "manager_action": "specific action",
      "customer_signal": "category",
      "source": "voice_of_customer_composer"
    }
  ],
  "rows": [
    ["call reference", "mini-scene", "meaning and action"]
  ],
  "source_note": "report_evidence.voice_of_customer_composer.v2",
  "selection_diagnostics": {}
}
```

## Writing Rules

- All manager-facing fields must be in Russian.
- Write `customer_scenes` as mini-scenes, not as report-table labels.
- Use `scene_summary` to explain what the customer was reacting to.
- Use `customer_meaning` to explain what the customer actually means: need,
  fear, objection, pause, service issue, decision process, trust barrier, or
  buying signal. Do not force a manager mistake.
- Use `manager_response` to explain how to work with that meaning: what to ask,
  clarify, send, fix, or stop doing next.
- Use `why_action_follows` only when it explains why this response matches the
  customer's meaning; keep it grounded.
- Fill `dialogue_evidence` with separate speaker-labelled replicas. If the
  provided context uses unclear sides, use `unknown`; the renderer will display
  it as `Сторона 1/2`.
- Keep `situations` and `rows` as compatibility fields. They can summarize the
  same scenes but must not contradict `customer_scenes`.

## Non-Negotiable Rules

- Use only facts present in `signals` and `evidence_refs`.
- Return 1 to 4 scenes. Prefer 2 to 4 when enough valid signals exist.
- The evidence must be a mini-scene or contextual excerpt, not a short orphan
  quote.
- Do not turn a vague phrase such as "Ладно, хорошо, я перезвоню" into a claim
  about a contract, price, legal issue, or implementation unless that context is
  present in the provided mini-scene.
- If the signal is only "я перезвоню", "позже", or "через некоторое время",
  treat it as an undefined transfer of initiative to the client. Do not write
  that the client will discuss the decision with colleagues, management, or
  another decision-maker unless that is explicit in the scene.
- The recommendation must follow the customer signal. If the customer asks for
  WhatsApp materials, recommend sending materials and fixing follow-up. If the
  customer asks about documents/signature, recommend document-process next step.
  If the customer asks for a proposal, recommend micro-qualification before the
  proposal.
- Do not recommend sending materials, WhatsApp follow-up, a proposal, a
  contract, or a demo unless that exact need is present in the mini-scene.
- Treat phrases about "сценарий подписания договора" as a document/signature
  need, not as a price/proposal request.
- Treat refusal/not-now phrases ("пока не будем подписывать", "сейчас нет",
  "не хотят заключать договор") as refusal or pause signals even if they contain
  contract words. Do not answer them with a document-signing scenario.
- Treat usage/support phrases ("не получилось", "не смогла сохранить",
  "ошибка") as service or usage issues first. Do not turn them into a sales
  recommendation until the support issue is closed.
- Do not invent customer names, volumes, roles, deadlines, products, meetings,
  legal risks, or next steps.
- If no signal has enough context or the action does not match the signal,
  return `status="insufficient"` with diagnostics instead of filling the block.

## Quality Expectations

Each accepted scene should answer:

- what the customer said;
- what was happening in the call around that quote;
- what the customer actually means;
- how the manager should work with that meaning next;
- why the action follows from the quote/context.
