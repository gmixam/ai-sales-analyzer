# Classify Prompt

Purpose: classify incoming call interactions before deeper analysis.

Notes:
- Preserve the JSON contract.
- Do not invent fields.
- Keep prompt revisions traceable via `instruction_version`.

## Speaker role attribution

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
