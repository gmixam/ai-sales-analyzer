# VoiceOfCustomerComposer v1 Prompt Contract

Purpose: compose the manager daily "Голос клиента" block from already extracted
customer-signal candidates. This is an LLM3 report-composition contract, not
primary call analysis.

## Input

The model receives bounded JSON:

```json
{
  "contract_version": "voice_of_customer_composer_v1",
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
    "prefer_rows": "2-4 when available",
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
  "situations": [
    {
      "call_id": "string",
      "client_call_reference": "string",
      "quote": "customer quote",
      "quote_context": "mini-scene",
      "context": "interpretation plus action",
      "interpretation": "interpretation plus action",
      "manager_action": "specific action",
      "customer_signal": "category",
      "source": "voice_of_customer_composer"
    }
  ],
  "rows": [
    ["call reference", "mini-scene", "meaning and action"]
  ],
  "source_note": "report_evidence.voice_of_customer_composer.v1",
  "selection_diagnostics": {}
}
```

## Non-Negotiable Rules

- Use only facts present in `signals` and `evidence_refs`.
- Return 1 to 4 rows. Prefer 2 to 4 when enough valid signals exist.
- The second row cell must be a mini-scene or contextual excerpt, not a short
  orphan quote.
- Do not turn a vague phrase such as "Ладно, хорошо, я перезвоню" into a claim
  about a contract, price, legal issue, or implementation unless that context is
  present in the provided mini-scene.
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

Each accepted signal should answer:

- what the customer said;
- what business context makes the quote meaningful;
- what the manager should do next;
- why the action follows from the quote/context.
