# Classify Prompt

Purpose: classify incoming call interactions before deeper analysis.

Notes:
- Preserve the JSON contract.
- Do not invent fields.
- Keep prompt revisions traceable via `instruction_version`.

## Speaker role attribution

## Universal call card

Return optional top-level `call_card` together with the first-pass
classification. This card is company-wide and universal: it must work for
sales, service, support, legal products, document flow, billing, internal calls,
and other topics. Do not make it EDO-only.

Use only STT transcript content for semantic fields. Do not infer topic,
intent, urgency, outcome, or analysis eligibility from deterministic rules,
phone numbers, CRM labels, metadata names, or call routing. If evidence is thin,
use `unknown`, `review_required`, or low confidence.

`contact_name` is allowed only when the STT transcript explicitly contains the
client's name. Never copy it from CRM, metadata, phonebook, or labels. If the
name is absent or uncertain, return `null`.

Keep `tags` and `evidence` short. Do not duplicate the full transcript,
segments, or long dialogue fragments.

```json
{
  "call_card": {
    "schema_version": "universal_call_card_v1",
    "topic": "short universal call topic",
    "product_area": "EDO | tech_support | legal_product | billing | document_flow | other | unknown",
    "department_hint": "likely department or business direction",
    "request_type": "sales | support | service | legal_product | billing | document_flow | internal | other | unknown",
    "client_intent": "what the client wanted",
    "manager_intent": "what the manager tried to do",
    "urgency": "hot | warm | cold | service | unknown",
    "business_outcome": "agreement | reschedule | refusal | open | service_resolved | transferred | no_answer | unknown",
    "analysis_eligibility": "eligible | not_eligible | review_required",
    "eligibility_reason": "short reason",
    "call_essence": "1-2 sentences about what happened and how it ended",
    "contact_name": null,
    "tags": ["short searchable tags"],
    "evidence": ["short transcript signals only"],
    "confidence": "low | medium | high"
  }
}
```

The STT layer may provide technical `segments`, but for OpenAI `whisper-1` these
segments are time chunks, not reliable speaker diarization. Never assume
`speaker A = manager` unless the transcript itself proves it.

Return optional `speaker_role_mapping` when roles can be inferred or when role
quality is uncertain:

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
        "text": "Добрый день, это ... Договор24...",
        "confidence": "medium",
        "evidence": ["speaker introduced themself as Dogovor24"]
      }
    ],
    "quality": {
      "diarization_quality": "low",
      "role_attribution_quality": "low",
      "warnings": [
        "technical_speaker_labels_unavailable",
        "roles_inferred_from_text_only"
      ]
    }
  }
}
```

Allowed roles: `manager`, `client`, `unknown`, `context`.
Allowed confidence values: `low`, `medium`, `high`.

Strong manager evidence: introduced as Dogovor24, explains product/tariff,
offers invoice/proposal/link/instructions, leads the process, asks sales or
support questions.

Strong client evidence: answers the call, describes their company/task/problem,
asks about price/product/service, accepts/refuses, requests information, speaks
as buyer/user.

If evidence conflicts or is thin, use `role=unknown`, `confidence=low`, and add
`role_attribution_uncertain`.
