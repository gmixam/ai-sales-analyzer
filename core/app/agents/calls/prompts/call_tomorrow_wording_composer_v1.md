# CallTomorrowWordingComposer v1 Prompt Contract

Purpose: improve manager-facing wording for the report block
"КОГО ВЗЯТЬ В РАБОТУ ЗАВТРА". This is an LLM3 wording-composition contract,
not a selection or prioritization contract.

The model receives only contacts that the deterministic Report Layer has
already accepted. Do not add, remove, reorder, reprioritize, or reclassify
contacts.

## Input

```json
{
  "contract_version": "call_tomorrow_wording_composer_v1",
  "contacts": [
    {
      "contact_key": "stable string",
      "interaction_id": "string",
      "client_call_reference": "string",
      "status": "agreed | rescheduled | open",
      "priority_code": "hot | rescheduled | warm | low",
      "priority_label": "string",
      "deadline": "string or null",
      "action_profile": "invoice_payment | meeting_demo | materials_request | internal_discussion | rescheduled | trust_barrier | agreement | weak_open",
      "reason": "current deterministic context",
      "next_step": "current deterministic action",
      "opening_script": "current deterministic opening phrase",
      "signal_text": "bounded evidence summary",
      "evidence_signal_text": "bounded evidence text"
    }
  ],
  "output_rules": {
    "same_contacts_same_order": true,
    "do_not_change_priority_status_deadline": true,
    "russian_manager_facing": true,
    "grounded_in_signal_text": true
  }
}
```

## Output

Return exactly one JSON object:

```json
{
  "status": "verified | insufficient",
  "contacts": [
    {
      "contact_key": "same key as input",
      "reason": "why this contact is worth taking tomorrow",
      "next_step": "what the manager should do",
      "opening_script": "one natural first phrase",
      "why_this_wording": "short explanation of why this wording fits the signal"
    }
  ],
  "selection_diagnostics": {}
}
```

## Non-Negotiable Rules

- Return the same number of contacts in the same order.
- Preserve every `contact_key`.
- Do not change or restate priority/status/deadline as a new fact.
- Use only facts present in each contact's `reason`, `next_step`,
  `opening_script`, `signal_text`, and `evidence_signal_text`.
- All manager-facing fields must be in Russian.
- Do not invent client names, roles, meetings, deadlines, amounts, products,
  documents, contracts, invoices, demos, or payment details unless present in
  that exact contact's evidence.
- A refusal/not-now signal must not become a pushy sale. If the evidence shows
  refusal or low need, the wording should clarify reason/return condition, not
  push demo/materials/invoice.
- A service/usage issue should first close the working issue, not force a sale.
- Opening phrase must be short, speakable, and specific to the signal.
- If a contact cannot be improved safely, keep its current deterministic wording
  and still return it.
