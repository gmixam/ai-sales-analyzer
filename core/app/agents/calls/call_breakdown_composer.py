"""Isolated Call Breakdown composer for manager daily reports.

The module deliberately does not import ``reporting.py``.  It works with
ReportArtifact-like objects through small getattr/dict helpers and returns a
payload compatible with the current ``call_breakdown`` report section.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

CALL_BREAKDOWN_COMPOSER_VERSION = "call_breakdown_composer_v2"
CALL_BREAKDOWN_PROMPT_VERSION = "call_breakdown_composer_v2"
CALL_BREAKDOWN_SOURCE = "report_evidence.call_breakdown_composer.v2"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "call_breakdown_composer_v2.md"

_MISSING_FRAGMENT_NOTE = "Нет подтверждающего фрагмента в сохранённых данных."

_B2B_TERMS = (
    "b2b",
    "авр",
    "доступ",
    "интеграц",
    "кабинет",
    "лпр",
    "пользовател",
    "руковод",
    "согласован",
    "сотрудник",
    "филиал",
    "школ",
    "эцп",
    "эдо",
    "юрлиц",
    "юрид",
)

_REQUIREMENT_TERMS = (
    "доступ",
    "кабинет",
    "пользовател",
    "роль",
    "сотрудник",
    "филиал",
    "школ",
    "эцп",
    "юрлиц",
)

_NEXT_STEP_TERMS = (
    "дальше",
    "завтра",
    "следующ",
    "созвон",
    "перезвон",
    "отправ",
    "уточн",
    "время",
)

_USER_ROLE_COUNTER_EVIDENCE_TERMS = (
    "сколько в команде",
    "кто будет пользоваться",
    "кто будет использовать",
    "у кого будет доступ",
    "сколько человек",
    "какие роли",
    "какая роль",
    "кто будет подписывать",
    "кто подключить",
    "кого подключить",
    "планирует пользоваться",
    "будет пользоваться системой",
)

_USER_ROLE_CLAIM_OBJECT_TERMS = (
    "пользовател",
    "участник",
    "роли",
    "роль",
    "команд",
    "кто будет пользоваться",
    "кто будет использовать",
    "кто будет подписывать",
    "у кого будет доступ",
    "кого подключить",
    "кто подключить",
)

_ABSOLUTE_MISSING_QUALIFICATION_TERMS = (
    "не уточнил",
    "не уточнял",
    "не выяснил",
    "не выяснял",
    "не спросил",
    "не спрашивал",
    "не задал",
)


def compose_call_breakdown_from_situation(
    artifacts: Iterable[Any],
    situation_day_evidence_packet: dict[str, Any] | None,
    situation_day_coaching_view: dict[str, Any] | None,
    score_by_stage: list[dict[str, Any]] | None = None,
    enable_llm3: bool = True,
) -> dict[str, Any] | None:
    """Build ``call_breakdown`` for the same verified call as Situation Day.

    The primary pilot path uses LLM3 as a bounded report composer.  The selected
    source packet is normalized into a strict contract; if LLM3 is disabled,
    fails routing, chooses a wrong call, or returns weak structure, the method
    falls back to the deterministic composer.
    """

    packet = _as_dict(situation_day_evidence_packet)
    if packet.get("status") != "verified":
        return None

    view = _as_dict(situation_day_coaching_view)
    excerpt = _as_dict(packet.get("dialogue_excerpt"))
    call_id = _text(excerpt.get("call_id") or packet.get("call_id") or view.get("call_id"))
    if not call_id:
        return None

    artifact = _find_artifact_by_call_id(artifacts, call_id)
    ref = _call_reference(
        call_id=call_id,
        packet_excerpt=excerpt,
        artifact=artifact,
    )
    turns = _normalize_turns(excerpt.get("turns"))
    transcript = _text(_obj_get(_obj_get(artifact, "interaction"), "text")) if artifact is not None else ""
    if not turns and transcript:
        turns = _turns_from_transcript(transcript)
    artifact_turns = _turns_from_artifact_segments(artifact)

    context_text = _compact(
        packet.get("customer_context")
        or _join_turns(turns)
        or view.get("what_happened")
        or packet.get("observed_manager_behavior")
    )
    if not context_text:
        return None

    stage_code = _text(view.get("stage_code") or packet.get("stage_code")) or None
    stage_name = (
        _text(view.get("stage_label") or view.get("stage_name") or packet.get("stage_name"))
        or _stage_name_from_scores(score_by_stage, stage_code)
        or None
    )
    selected_call = {
        **ref,
        "stage_code": stage_code,
        "stage_name": stage_name,
    }
    transcript_scenes = _transcript_scenes_from_packet(
        call_id=call_id,
        stage_code=stage_code,
        context_text=context_text,
        turns=turns,
        packet=packet,
        artifact_turns=artifact_turns,
    )
    contract_turns = _turns_from_scenes(transcript_scenes) or turns
    llm2_facts = _llm2_facts_from_artifact(artifact=artifact, score_by_stage=score_by_stage)
    llm3_payload = build_call_breakdown_llm3_payload(
        selected_call=selected_call,
        transcript_scenes=transcript_scenes,
        situation_evidence_packet=packet,
        llm2_facts=llm2_facts,
    )
    llm3_result, llm3_diagnostics = _try_llm3_call_breakdown(
        llm3_payload,
        force_enabled=None if enable_llm3 else False,
    )
    if llm3_result is not None:
        return llm3_result

    contract = build_llm3_contract_payload(
        call_id=call_id,
        situation_day_evidence_packet=packet,
        situation_day_coaching_view=view,
        context_text=context_text,
        turns=contract_turns,
        score_by_stage=score_by_stage,
    )
    moments = _compose_deterministic_moments(contract)
    if not moments:
        return None

    rows = [
        [
            moment["label"],
            moment["what"],
            moment["fragment"],
            moment["recommendation"],
        ]
        for moment in moments
    ]
    fragment_present = any(_text(row[2]) and row[2] != _MISSING_FRAGMENT_NOTE for row in rows)
    strength = _text(packet.get("proof_strength") or view.get("proof_strength")) or "medium"
    quality = {
        "status": "passed" if fragment_present else "insufficient_evidence",
        "source": CALL_BREAKDOWN_SOURCE,
        "input_rows_count": len(rows),
        "rendered_rows_count": len(rows) if fragment_present else 0,
        "filtered_rows_count": 0,
        "filtered_reasons": {},
        "composer_version": CALL_BREAKDOWN_COMPOSER_VERSION,
        "selection_basis": "verified_situation_day",
    }

    summary_line = (
        f"{ref.get('client_call_reference') or ref.get('client_label') or 'Звонок'}: "
        "разбор той же ситуации, которая выбрана как ключевая для дня."
    )
    selection_diagnostics = {
        "composer_version": CALL_BREAKDOWN_COMPOSER_VERSION,
        "prompt_version": CALL_BREAKDOWN_PROMPT_VERSION,
        "selection_mode": "same_call_as_verified_situation_day",
        "selected_call_id": call_id,
        "situation_day_status": packet.get("status"),
        "situation_day_proof_strength": packet.get("proof_strength"),
        "deterministic_fallback_used": True,
        "llm3_ready": True,
        "llm3_used": False,
        "llm3": llm3_diagnostics,
        "complex_b2b_detected": _is_complex_b2b_context(contract),
        "moment_codes": [moment["code"] for moment in moments],
    }

    return {
        "is_placeholder": False,
        "call_id": call_id,
        "client_label": ref.get("client_label"),
        "client_phone": ref.get("client_phone"),
        "date_label": ref.get("date_label"),
        "time_label": ref.get("time_label"),
        "client_call_reference": ref.get("client_call_reference"),
        "stage_code": stage_code,
        "stage_name": stage_name,
        "stage_steps": [],
        "worked": [],
        "to_fix": [
            {
                "label": moment["title"],
                "interpretation": moment["what"],
            }
            for moment in moments
        ],
        "recommendation": {
            "title": "Как разобрать этот звонок",
            "better_phrasing": moments[0]["recommendation"],
        },
        "rows": rows,
        "moments": moments,
        "summary_line": summary_line,
        "source_note": CALL_BREAKDOWN_SOURCE,
        "call_breakdown_source": CALL_BREAKDOWN_SOURCE,
        "call_breakdown_evidence_strength": strength,
        "call_breakdown_fragment_present": fragment_present,
        "selection_diagnostics": selection_diagnostics,
        "call_breakdown_quality": quality,
        "moment_summary": _text(packet.get("observed_manager_behavior") or view.get("what_happened")) or None,
        "missing_action": _text(packet.get("missing_action") or view.get("what_was_missing")) or None,
        "why_it_matters": _text(packet.get("causal_link") or view.get("meaning")) or None,
        "supporting_quote": context_text,
        "evidence_type": _text(packet.get("proof_type") or view.get("proof_type")) or None,
        "confidence": strength,
        "proof_type": _text(packet.get("proof_type") or view.get("proof_type")) or None,
        "proof_explanation": _text(packet.get("causal_link") or view.get("meaning")) or None,
        "quote_role": _text(packet.get("quote_role") or view.get("quote_role")) or None,
    }


def compose_call_breakdown(
    *,
    selected_call: dict[str, Any],
    transcript_scenes: list[dict[str, Any]],
    situation_evidence_packet: dict[str, Any],
    llm2_facts: dict[str, Any] | None = None,
    llm3_enabled: bool = False,
) -> dict[str, Any]:
    """Compose from an explicit LLM3-style contract payload for tests and future use."""
    call_id = _text(selected_call.get("call_id"))
    if not call_id:
        return {
            "status": "no_data",
            "call_id": None,
            "call_breakdown_source": CALL_BREAKDOWN_SOURCE,
            "source_note": CALL_BREAKDOWN_SOURCE,
            "rows": [],
            "moments": [],
            "selection_diagnostics": {
                "composer_version": CALL_BREAKDOWN_COMPOSER_VERSION,
                "reason": "missing_selected_call_id",
            },
        }
    llm3_payload = build_call_breakdown_llm3_payload(
        selected_call=selected_call,
        transcript_scenes=transcript_scenes,
        situation_evidence_packet=situation_evidence_packet,
        llm2_facts=llm2_facts,
    )
    llm3_result, llm3_diagnostics = _try_llm3_call_breakdown(
        llm3_payload,
        force_enabled=True if llm3_enabled else False,
    )
    if llm3_result is not None:
        return llm3_result

    packet = dict(situation_evidence_packet or {})
    packet.setdefault("dialogue_excerpt", {})
    excerpt = dict(packet.get("dialogue_excerpt") or {})
    excerpt.setdefault("call_id", call_id)
    excerpt.setdefault("client_label", selected_call.get("client_label"))
    excerpt.setdefault("client_phone", selected_call.get("client_phone"))
    excerpt.setdefault("date_label", selected_call.get("date_label"))
    excerpt.setdefault("time_label", selected_call.get("time_label"))
    excerpt.setdefault("client_call_reference", selected_call.get("client_call_reference"))
    turns = []
    for scene in transcript_scenes or []:
        turns.extend(_normalize_turns(_as_dict(scene).get("turns")))
    if turns:
        excerpt["turns"] = turns
    packet["dialogue_excerpt"] = excerpt

    view = {
        "call_id": call_id,
        "stage_code": selected_call.get("stage_code"),
        "stage_label": selected_call.get("stage_name"),
        "pattern_title": packet.get("problem_title") or packet.get("problem_claim"),
        "what_happened": packet.get("observed_manager_behavior") or packet.get("client_context"),
        "what_was_missing": packet.get("missing_action"),
        "next_time_action": packet.get("manager_lesson"),
        "meaning": packet.get("causal_link"),
        "proof_type": packet.get("proof_type"),
        "proof_strength": packet.get("proof_strength"),
    }
    result = compose_call_breakdown_from_situation(
        artifacts=[],
        situation_day_evidence_packet=packet,
        situation_day_coaching_view=view,
        score_by_stage=_as_dict(llm2_facts).get("score_by_stage"),
        enable_llm3=False,
    )
    if result is None:
        return {
            "status": "insufficient",
            "call_id": call_id,
            "call_breakdown_source": CALL_BREAKDOWN_SOURCE,
            "source_note": CALL_BREAKDOWN_SOURCE,
            "rows": [],
            "moments": [],
            "selection_diagnostics": {
                "composer_version": CALL_BREAKDOWN_COMPOSER_VERSION,
                "reason": "deterministic_composer_returned_none",
                "llm3_requested": llm3_enabled,
            },
        }
    result["status"] = "verified"
    result.setdefault("selection_diagnostics", {})["llm3_requested"] = llm3_enabled
    result.setdefault("selection_diagnostics", {})["llm3"] = llm3_diagnostics
    return result


def build_call_breakdown_llm3_payload(
    *,
    selected_call: dict[str, Any],
    transcript_scenes: list[dict[str, Any]],
    situation_evidence_packet: dict[str, Any],
    llm2_facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build explicit LLM3 payload shape used by prompt/tests."""
    selected = dict(selected_call or {})
    packet = dict(situation_evidence_packet or {})
    scenes = list(transcript_scenes or [])
    facts = _bounded_llm2_facts_for_llm3(llm2_facts)
    complex_b2b_detected = _detect_complex_b2b_from_payload_parts(
        selected_call=selected,
        situation_evidence_packet=packet,
        transcript_scenes=scenes,
    )
    return {
        "contract_version": CALL_BREAKDOWN_PROMPT_VERSION,
        "selected_call": selected,
        "situation_evidence_packet": packet,
        "transcript_scenes": scenes,
        "llm2_facts": facts,
        "composition_rules": {
            "complex_b2b_detected": complex_b2b_detected,
            "verified_min_moments": 2 if complex_b2b_detected else 1,
            "verified_target_moments": 3 if complex_b2b_detected else 1,
            "verified_max_moments": 4,
            "rows_required": True,
            "narrative_preferred": True,
            "fragment_context_min_chars": 90,
            "fragment_must_be_mini_scene": True,
            "same_call_only": True,
            "llm2_facts_are_bounded": True,
        },
        "non_duplication_guard": {
            "situation_day_problem_title": _text(
                packet.get("problem_title")
                or packet.get("problem_claim")
            ),
            "situation_day_what_happened": _text(
                packet.get("observed_manager_behavior")
            ),
            "situation_day_recommendation": _text(
                packet.get("manager_lesson")
            ),
        },
        "required_output_keys": [
            "status",
            "call_id",
            "summary_line",
            "source_note",
            "call_breakdown_source",
            "call_story",
            "what_manager_missed",
            "better_path",
            "key_turning_points",
            "moments",
            "rows",
            "selection_diagnostics",
        ],
    }


def build_llm3_contract_payload(
    *,
    call_id: str,
    situation_day_evidence_packet: dict[str, Any],
    situation_day_coaching_view: dict[str, Any],
    context_text: str,
    turns: list[dict[str, str]],
    score_by_stage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the future LLM3 input contract without making a model call."""

    return {
        "contract_version": CALL_BREAKDOWN_PROMPT_VERSION,
        "task": "call_breakdown_from_verified_situation_day",
        "call_id": call_id,
        "situation_day": {
            "problem_claim": _text(situation_day_evidence_packet.get("problem_claim")),
            "what_happened": _text(
                situation_day_evidence_packet.get("observed_manager_behavior")
                or situation_day_coaching_view.get("what_happened")
            ),
            "missing_action": _text(
                situation_day_evidence_packet.get("missing_action")
                or situation_day_coaching_view.get("what_was_missing")
            ),
            "manager_lesson": _text(
                situation_day_evidence_packet.get("manager_lesson")
                or situation_day_coaching_view.get("next_time_action")
            ),
            "causal_link": _text(
                situation_day_evidence_packet.get("causal_link")
                or situation_day_coaching_view.get("meaning")
            ),
            "proof_type": _text(
                situation_day_evidence_packet.get("proof_type")
                or situation_day_coaching_view.get("proof_type")
            ),
            "proof_strength": _text(situation_day_evidence_packet.get("proof_strength")),
        },
        "call_context": {
            "context_text": context_text,
            "turns": turns[:16],
            "score_by_stage": score_by_stage or [],
        },
        "output_rules": {
            "moments_min": 2,
            "moments_max": 4,
            "must_use_same_call": True,
            "must_include_evidence_fragment": True,
            "must_not_repeat_situation_day_wording_only": True,
        },
    }


def _bounded_llm2_facts_for_llm3(llm2_facts: dict[str, Any] | None) -> dict[str, Any]:
    """Project persisted LLM2 material into bounded facts/proof cards for LLM3."""
    facts = _as_dict(llm2_facts)
    return {
        "business_outcome": _clip(_first_text(facts.get("business_outcome")), limit=420),
        "call_report_summary": _clip(_first_text(facts.get("call_report_summary")), limit=520),
        "score_by_stage": _bounded_score_by_stage(facts.get("score_by_stage")),
        "proof_cards": _bounded_proof_cards_from_facts(facts),
    }


def _bounded_score_by_stage(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in value or []:
        item = _as_dict(raw)
        stage_code = _first_text(item.get("stage_code"), item.get("code"))
        if not stage_code:
            continue
        result.append(
            {
                "stage_code": stage_code,
                "stage_name": _clip(
                    _first_text(item.get("stage_name"), item.get("label"), item.get("name")),
                    limit=120,
                ),
                "score": item.get("score"),
                "max_score": item.get("max_score"),
            }
        )
        if len(result) >= 8:
            break
    return result


def _bounded_proof_cards_from_facts(facts: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for container in (
        facts,
        _as_dict(facts.get("llm2c")),
        _as_dict(facts.get("proof_artifact")),
        _as_dict(facts.get("report_evidence")),
    ):
        for raw_card in container.get("proof_cards") or []:
            card = _as_dict(raw_card)
            proof_id = _first_text(card.get("proof_id"), card.get("proof_card_id"))
            claim = _clip(_first_text(card.get("softened_claim"), card.get("claim")), limit=420)
            proof_status = _first_text(card.get("proof_status"), card.get("status"))
            if not (proof_id or claim or proof_status):
                continue
            cards.append(
                {
                    "proof_id": proof_id,
                    "claim_id": _first_text(card.get("claim_id")),
                    "stage_code": _first_text(card.get("stage_code")),
                    "claim": claim,
                    "proof_status": proof_status,
                    "proof_type": _first_text(card.get("proof_type")),
                    "proof_strength": _first_text(card.get("proof_strength"), card.get("evidence_strength")),
                    "evidence_quote": _clip(_first_text(card.get("evidence_quote")), limit=520),
                    "supporting_evidence_ids": [
                        _first_text(item)
                        for item in (card.get("supporting_evidence_ids") or [])[:8]
                        if _first_text(item)
                    ],
                    "proof_explanation": _clip(_first_text(card.get("proof_explanation")), limit=520),
                    "reject_reason": _first_text(card.get("reject_reason")),
                }
            )
            if len(cards) >= 8:
                return cards
    return cards


def _try_llm3_call_breakdown(
    payload: dict[str, Any],
    *,
    force_enabled: bool | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    diagnostics: dict[str, Any] = {
        "llm3_enabled": _llm3_enabled() if force_enabled is None else force_enabled,
        "llm3_used": False,
        "llm3_prompt_version": CALL_BREAKDOWN_PROMPT_VERSION,
    }
    if not diagnostics["llm3_enabled"]:
        return None, diagnostics

    try:
        raw = _request_llm3_call_breakdown(payload)
        diagnostics["llm3_raw_status"] = raw.get("status")
        if isinstance(raw.get("_routing"), dict):
            diagnostics["llm3_routing"] = raw.get("_routing")
        normalized, rejection_reason = _normalize_llm3_call_breakdown(raw, payload)
        if normalized is None:
            diagnostics["llm3_rejection_reason"] = rejection_reason
            diagnostics["llm3_response"] = _json_safe(raw)
            return None, diagnostics
        diagnostics["llm3_used"] = True
        normalized.setdefault("selection_diagnostics", {})
        normalized["selection_diagnostics"].update(
            {
                "composer_version": CALL_BREAKDOWN_COMPOSER_VERSION,
                "prompt_version": CALL_BREAKDOWN_PROMPT_VERSION,
                "selection_mode": "same_call_as_verified_situation_day",
                "selected_call_id": _text(_as_dict(payload.get("selected_call")).get("call_id")),
                "deterministic_fallback_used": False,
                "llm3_used": True,
                "llm3_routing": diagnostics.get("llm3_routing"),
            }
        )
        return normalized, diagnostics
    except Exception as exc:
        diagnostics["llm3_error"] = str(exc)
        return None, diagnostics


def _request_llm3_call_breakdown(payload: dict[str, Any]) -> dict[str, Any]:
    selected_call = _as_dict(payload.get("selected_call"))
    subject_key = _text(selected_call.get("call_id")) or "call_breakdown_composer"
    prompt = _read_llm3_prompt()
    simulated = _request_llm3_simulation(
        payload=payload,
        prompt=prompt,
        request_kind="call_breakdown_composer",
        subject_key=subject_key,
        input_artifact="llm3_call_breakdown_input.json",
        output_artifact="llm3_call_breakdown_output.json",
        notes="LLM-3 Call Breakdown composer simulated.",
    )
    if simulated is not None:
        return simulated

    from openai import OpenAI

    from app.core_shared.ai_routing import AIProviderRouter
    from app.core_shared.config.settings import settings

    route_plan = AIProviderRouter().build_route_plan(
        layer="llm3",
        subject_key=subject_key,
    )
    candidate = route_plan.current_candidate()
    compatibility_candidate = candidate
    if (candidate.endpoint or "").rstrip("/") == "/chat/completions":
        compatibility_candidate = replace(candidate, endpoint=None)
    AIProviderRouter.ensure_execution_compatibility(
        compatibility_candidate,
        executor_label="LLM-3 Call Breakdown composer",
        required_execution_mode="openai_compatible",
    )
    client = OpenAI(
        api_key=candidate.resolved_api_key(),
        base_url=candidate.api_base,
    )
    response = None
    last_error: Exception | None = None
    attempts_total = max(1, candidate.max_retries_for_this_provider + 1)
    for _ in range(attempts_total):
        try:
            response = client.chat.completions.create(
                model=candidate.model,
                response_format={"type": "json_object"},
                temperature=0.1,
                timeout=candidate.timeout_sec or settings.openai_timeout_sec,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            )
            break
        except Exception as exc:
            last_error = exc
    if response is None:
        route_plan.mark_attempt_failure(str(last_error or "unknown_llm3_error"))
        raise last_error or RuntimeError("Unknown LLM3 request failure")
    route_plan.mark_attempt_success()
    parsed = json.loads(_extract_openai_message_content(response))
    result = _as_dict(parsed)
    result["_routing"] = route_plan.to_metadata(
        request_kind="call_breakdown_composer",
        notes="LLM-3 Call Breakdown composer completed.",
    )
    return result


def _request_llm3_simulation(
    *,
    payload: dict[str, Any],
    prompt: str,
    request_kind: str,
    subject_key: str,
    input_artifact: str,
    output_artifact: str,
    notes: str,
) -> dict[str, Any] | None:
    try:
        from app.agents.calls import llm_simulation
    except Exception:
        return None

    enabled = _llm_simulation_enabled(llm_simulation)
    if enabled is False:
        return None
    executor = _llm_simulation_executor(llm_simulation)
    if executor is None:
        if enabled is True:
            raise RuntimeError("LLM simulation is enabled but no LLM-3 simulation executor is available")
        return None

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    context = {
        "layer": "llm3",
        "node": request_kind,
        "request_kind": request_kind,
        "subject_key": subject_key,
        "prompt": prompt,
        "system_prompt": prompt,
        "payload": payload,
        "input_payload": payload,
        "messages": messages,
        "input_artifact": input_artifact,
        "input_artifact_name": input_artifact,
        "output_artifact": output_artifact,
        "output_artifact_name": output_artifact,
    }
    _write_llm_simulation_artifact(llm_simulation, input_artifact, payload, context)
    raw = _call_llm_simulation_callable(executor, context)
    if raw is None:
        if enabled is True:
            raise RuntimeError("LLM simulation is enabled but executor returned no LLM-3 result")
        return None
    result = _as_dict(raw)
    result.setdefault(
        "_routing",
        {
            "layer": "llm3",
            "provider": "llm_simulation",
            "simulation": True,
            "request_kind": request_kind,
            "subject_key": subject_key,
            "notes": notes,
        },
    )
    _write_llm_simulation_artifact(llm_simulation, output_artifact, result, context)
    return result


def _llm_simulation_enabled(llm_simulation: Any) -> bool | None:
    for name in (
        "is_llm_simulation_enabled",
        "llm_simulation_enabled",
        "simulation_enabled",
        "is_enabled",
        "enabled",
    ):
        value = getattr(llm_simulation, name, None)
        if callable(value):
            try:
                return bool(value(layer="llm3"))
            except TypeError:
                return bool(value())
        if value is not None:
            return bool(value)
    return None


def _llm_simulation_executor(llm_simulation: Any) -> Any | None:
    for name in (
        "request_llm3_composer",
        "request_llm3",
        "request_llm_simulation",
        "run_llm_simulation",
        "simulate_llm_call",
        "simulate",
        "execute",
    ):
        executor = getattr(llm_simulation, name, None)
        if callable(executor):
            return executor
    return None


def _write_llm_simulation_artifact(
    llm_simulation: Any,
    artifact_name: str,
    payload: Any,
    context: dict[str, Any],
) -> None:
    for name in (
        "write_llm_artifact",
        "write_simulation_artifact",
        "save_llm_artifact",
        "save_simulation_artifact",
        "record_llm_artifact",
        "record_artifact",
    ):
        writer = getattr(llm_simulation, name, None)
        if callable(writer):
            _call_llm_simulation_callable(
                writer,
                {
                    **context,
                    "artifact_name": artifact_name,
                    "name": artifact_name,
                    "filename": artifact_name,
                    "data": payload,
                    "value": payload,
                    "payload": payload,
                },
            )
            return


def _call_llm_simulation_callable(func: Any, kwargs: dict[str, Any]) -> Any:
    import inspect

    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(**kwargs)
    parameters = signature.parameters
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return func(**kwargs)
    accepted = {
        name: kwargs[name]
        for name in parameters
        if name in kwargs
    }
    if accepted or not parameters:
        return func(**accepted)
    if len(parameters) == 1:
        return func(kwargs["payload"])
    return func(**accepted)


def _normalize_llm3_call_breakdown(
    raw: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    selected_call = _as_dict(payload.get("selected_call"))
    expected_call_id = _text(selected_call.get("call_id"))
    if _text(raw.get("status")) != "verified":
        return None, "status_not_verified"
    if not expected_call_id or _text(raw.get("call_id")) != expected_call_id:
        return None, "call_id_mismatch"
    raw_stage_code = _first_text(raw.get("stage_code"))
    expected_stage_code = _first_text(selected_call.get("stage_code"))
    if raw_stage_code and expected_stage_code and raw_stage_code != expected_stage_code:
        return None, "stage_code_changed"

    moments = [_as_dict(item) for item in raw.get("moments") or [] if isinstance(item, dict)]
    rows = [row for row in raw.get("rows") or [] if isinstance(row, list)]
    complex_b2b = _payload_is_complex_b2b(payload)
    min_moments = 2 if complex_b2b else 1
    if complex_b2b and len(moments) < 2:
        return None, "complex_b2b_requires_two_moments"
    if not (min_moments <= len(moments) <= 4):
        return None, "moments_count_out_of_range"
    if not (min_moments <= len(rows) <= 4):
        rows = _rows_from_llm3_moments(moments)
    if not (min_moments <= len(rows) <= 4):
        return None, "rows_count_out_of_range"
    if any(len(row) != 4 for row in rows):
        return None, "row_shape_invalid"
    rows = _repair_weak_rows_with_payload_context(rows, moments, payload)
    rows, moments, counter_evidence_diagnostics = _repair_counter_evidence_claims(
        rows=rows,
        moments=moments,
        payload=payload,
    )
    weak_row_index = _first_weak_context_row_index(rows)
    if weak_row_index is not None:
        return None, f"row_{weak_row_index}_fragment_too_short"

    normalized_moments = []
    for index, moment in enumerate(moments[:4], start=1):
        normalized = _normalize_llm3_moment(moment, expected_call_id, index)
        if normalized is None:
            return None, "moment_required_fields_missing"
        normalized_moments.append(normalized)
    proof_support_failure = _llm3_breakdown_proof_support_failure(
        rows=rows[:4],
        moments=normalized_moments,
        payload=payload,
    )
    if proof_support_failure:
        return None, proof_support_failure
    key_turning_points = _normalize_key_turning_points(
        raw_points=raw.get("key_turning_points"),
        moments=normalized_moments,
        rows=rows,
    )
    call_story = _first_text(
        raw.get("call_story"),
        raw.get("narrative"),
        raw.get("summary_line"),
        _narrative_from_moments(normalized_moments),
    )
    what_manager_missed = _first_text(
        raw.get("what_manager_missed"),
        raw.get("missing_action"),
        _as_dict(payload.get("situation_evidence_packet")).get("missing_action"),
        normalized_moments[0].get("moment_summary") if normalized_moments else "",
    )
    better_path = _first_text(
        raw.get("better_path"),
        raw.get("manager_lesson"),
        _as_dict(payload.get("situation_evidence_packet")).get("manager_lesson"),
        normalized_moments[0].get("better") if normalized_moments else "",
    )
    dialogue_evidence = _normalize_dialogue_evidence(
        raw.get("dialogue_evidence"),
        fallback_text=rows[0][2] if rows and len(rows[0]) > 2 else "",
    )
    language_probe = " ".join(
        [
            call_story,
            what_manager_missed,
            better_path,
            " ".join(str(row_item) for row in rows for row_item in row),
        ]
    )
    if not _manager_facing_russian_enough(language_probe):
        return None, "manager_facing_language_not_russian"

    result = dict(raw)
    result.pop("_routing", None)
    result.update(
        {
            "status": "verified",
            "is_placeholder": False,
            "call_id": expected_call_id,
            "client_label": _first_text(raw.get("client_label"), selected_call.get("client_label")),
            "client_phone": _first_text(raw.get("client_phone"), selected_call.get("client_phone")),
            "date_label": _first_text(raw.get("date_label"), selected_call.get("date_label")),
            "time_label": _first_text(raw.get("time_label"), selected_call.get("time_label")),
            "client_call_reference": _first_text(
                raw.get("client_call_reference"),
                selected_call.get("client_call_reference"),
            ),
            "stage_code": _first_text(raw.get("stage_code"), selected_call.get("stage_code")),
            "stage_name": _first_text(raw.get("stage_name"), selected_call.get("stage_name")),
            "source_note": CALL_BREAKDOWN_SOURCE,
            "call_breakdown_source": CALL_BREAKDOWN_SOURCE,
            "call_story": call_story,
            "what_manager_missed": what_manager_missed,
            "better_path": better_path,
            "dialogue_evidence": dialogue_evidence,
            "key_turning_points": key_turning_points,
            "moments": normalized_moments,
            "rows": rows[:4],
            "call_breakdown_evidence_strength": _first_text(
                _as_dict(payload.get("situation_evidence_packet")).get("proof_strength"),
                "medium",
            ),
            "call_breakdown_fragment_present": True,
            "selection_diagnostics": _as_dict(raw.get("selection_diagnostics")),
            "call_breakdown_quality": {
                "status": "passed",
                "source": CALL_BREAKDOWN_SOURCE,
                "input_rows_count": len(rows[:4]),
                "rendered_rows_count": len(rows[:4]),
                "filtered_rows_count": 0,
                "filtered_reasons": {},
                "counter_evidence_gate": counter_evidence_diagnostics,
                "composer_version": CALL_BREAKDOWN_COMPOSER_VERSION,
                "selection_basis": "verified_situation_day_llm3",
            },
        }
    )
    result.setdefault("selection_diagnostics", {})["counter_evidence_gate"] = counter_evidence_diagnostics
    result.setdefault(
        "summary_line",
        f"{result.get('client_call_reference') or result.get('client_label') or 'Звонок'}: разбор ключевых ошибок по выбранной ситуации дня.",
    )
    result.setdefault("worked", [])
    result.setdefault("stage_steps", [])
    result.setdefault(
        "to_fix",
        [
            {"label": item.get("moment"), "interpretation": item.get("moment_summary")}
            for item in normalized_moments
        ],
    )
    result.setdefault(
        "recommendation",
        {
            "title": "Как разобрать этот звонок",
            "better_phrasing": normalized_moments[0].get("better"),
        },
    )
    return result, None


def _narrative_from_moments(moments: list[dict[str, Any]]) -> str:
    parts = []
    for moment in moments[:3]:
        text = _first_text(moment.get("what"), moment.get("moment_summary"))
        if text:
            parts.append(text.rstrip(".") + ".")
    return " ".join(parts)


def _normalize_key_turning_points(
    *,
    raw_points: Any,
    moments: list[dict[str, Any]],
    rows: list[list[Any]],
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for index, raw_point in enumerate(raw_points or [], start=1):
        if not isinstance(raw_point, dict):
            continue
        moment = moments[index - 1] if index - 1 < len(moments) else {}
        row = rows[index - 1] if index - 1 < len(rows) else []
        title = _first_text(raw_point.get("title"), moment.get("moment"), row[0] if len(row) > 0 else "")
        what_happened = _first_text(raw_point.get("what_happened"), moment.get("what"), row[1] if len(row) > 1 else "")
        why_it_matters = _first_text(raw_point.get("why_it_matters"), moment.get("moment_summary"))
        better_action = _first_text(raw_point.get("better_action"), moment.get("better"), row[3] if len(row) > 3 else "")
        evidence_text = _first_text(
            raw_point.get("supporting_quote"),
            moment.get("supporting_quote"),
            row[2] if len(row) > 2 else "",
        )
        points.append(
            {
                "title": title or f"Момент {index}",
                "what_happened": what_happened,
                "why_it_matters": why_it_matters,
                "manager_gap": _first_text(raw_point.get("manager_gap"), moment.get("moment_summary")),
                "better_action": better_action,
                "dialogue_evidence": _normalize_dialogue_evidence(
                    raw_point.get("dialogue_evidence"),
                    fallback_text=evidence_text,
                ),
                "proof_type": _first_text(raw_point.get("proof_type"), moment.get("proof_type")),
                "quote_role": _first_text(raw_point.get("quote_role"), moment.get("quote_role")),
                "proof_explanation": _first_text(raw_point.get("proof_explanation"), moment.get("proof_explanation")),
                "evidence_refs": list(raw_point.get("evidence_refs") or moment.get("evidence_refs") or []),
            }
        )
    if points:
        return points[:4]
    for index, moment in enumerate(moments[:4], start=1):
        row = rows[index - 1] if index - 1 < len(rows) else []
        evidence_text = _first_text(moment.get("supporting_quote"), row[2] if len(row) > 2 else "")
        points.append(
            {
                "title": _first_text(moment.get("moment"), f"Момент {index}"),
                "what_happened": _first_text(moment.get("what"), row[1] if len(row) > 1 else ""),
                "why_it_matters": _first_text(moment.get("moment_summary"), moment.get("proof_explanation")),
                "manager_gap": _first_text(moment.get("moment_summary"), moment.get("what")),
                "better_action": _first_text(moment.get("better"), row[3] if len(row) > 3 else ""),
                "dialogue_evidence": _normalize_dialogue_evidence(None, fallback_text=evidence_text),
                "proof_type": _first_text(moment.get("proof_type")),
                "quote_role": _first_text(moment.get("quote_role")),
                "proof_explanation": _first_text(moment.get("proof_explanation")),
                "evidence_refs": list(moment.get("evidence_refs") or []),
            }
        )
    return points


def _normalize_dialogue_evidence(value: Any, *, fallback_text: Any = "") -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw_item in value or []:
        if isinstance(raw_item, dict):
            text = _strip_fragment_prefix(_first_text(raw_item.get("text"), raw_item.get("quote")))
            if text:
                items.append(
                    {
                        "speaker": _normalize_speaker_label(raw_item.get("speaker")) or "unknown",
                        "text": text,
                    }
                )
        elif isinstance(raw_item, str) and _text(raw_item):
            items.append({"speaker": "unknown", "text": _strip_fragment_prefix(raw_item)})
    if items:
        return items[:8]
    fallback = _strip_fragment_prefix(fallback_text)
    if not fallback:
        return []
    parts = [
        _strip_fragment_prefix(part)
        for part in re.split(r"\s*/\s*|\n+", fallback)
        if _strip_fragment_prefix(part)
    ]
    if len(parts) <= 1:
        return [{"speaker": "unknown", "text": fallback}]
    return [
        {
            "speaker": "side_1" if index % 2 == 0 else "side_2",
            "text": part,
        }
        for index, part in enumerate(parts[:8])
    ]


def _manager_facing_russian_enough(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return cyrillic >= 20 and cyrillic >= latin


def _normalize_llm3_moment(
    moment: dict[str, Any],
    expected_call_id: str,
    index: int,
) -> dict[str, Any] | None:
    required = ("what", "moment_summary", "better", "proof_type", "proof_explanation")
    if any(not _text(moment.get(key)) for key in required):
        return None
    evidence_refs = moment.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        return None
    normalized = dict(moment)
    normalized["call_id"] = expected_call_id
    normalized["moment"] = _first_text(moment.get("moment"), f"Момент {index}")
    normalized["supporting_quote"] = _first_text(
        moment.get("supporting_quote"),
        moment.get("fragment"),
        _first_evidence_quote(evidence_refs),
    )
    if not normalized["supporting_quote"]:
        return None
    normalized["supporting_quote_proof_type"] = _first_text(
        moment.get("supporting_quote_proof_type"),
        moment.get("proof_type"),
        "sequence_inference",
    )
    normalized["quote_role"] = _first_text(moment.get("quote_role"), "supports_context")
    normalized["evidence_strength"] = _first_text(moment.get("evidence_strength"), "medium")
    return normalized


def _llm3_breakdown_proof_support_failure(
    *,
    rows: list[list[Any]],
    moments: list[dict[str, Any]],
    payload: dict[str, Any],
) -> str | None:
    if not rows or not moments:
        return "missing_rows_or_moments"
    for index, row in enumerate(rows, start=1):
        moment = moments[index - 1] if index - 1 < len(moments) else {}
        if _has_proof_id(moment):
            continue
        fragment = _strip_fragment_prefix(row[2] if len(row) > 2 else "")
        supporting_quote = _first_text(
            fragment,
            moment.get("supporting_quote"),
            moment.get("fragment"),
            _first_evidence_quote(moment.get("evidence_refs")),
        )
        if not supporting_quote:
            return f"row_{index}_missing_proof_fragment_or_proof_id"
        if not _proof_fragment_is_grounded_in_payload(supporting_quote, payload):
            return f"row_{index}_ungrounded_proof_fragment"
    if any(_has_proof_id(moment) or _proof_fragment_is_grounded_in_payload(moment.get("supporting_quote"), payload) for moment in moments):
        return None
    return "narrative_missing_proof_fragment_or_proof_id"


def _has_proof_id(value: Any) -> bool:
    item = _as_dict(value)
    if _first_text(item.get("proof_id"), item.get("proof_card_id")):
        return True
    for ref in item.get("evidence_refs") or []:
        ref_item = _as_dict(ref)
        if _first_text(ref_item.get("proof_id"), ref_item.get("proof_card_id")):
            return True
    return False


def _proof_fragment_is_grounded_in_payload(fragment: Any, payload: dict[str, Any]) -> bool:
    fragment_norm = _loose_norm(_strip_fragment_prefix(fragment))
    if not fragment_norm:
        return False
    if fragment_norm == _loose_norm(_MISSING_FRAGMENT_NOTE):
        return False
    payload_texts = _payload_proof_texts(payload)
    for text in payload_texts:
        text_norm = _loose_norm(text)
        if not text_norm:
            continue
        if fragment_norm in text_norm or text_norm in fragment_norm:
            return True
    return False


def _payload_proof_texts(payload: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    packet = _as_dict(payload.get("situation_evidence_packet"))
    for value in (
        packet.get("supporting_quote"),
        packet.get("evidence_scene"),
        _as_dict(packet.get("dialogue_excerpt")).get("quote"),
    ):
        text = _first_text(value)
        if text:
            texts.append(text)
    for turn in _normalize_turns(_as_dict(packet.get("dialogue_excerpt")).get("turns")):
        text = _text(turn.get("text"))
        if text:
            texts.append(text)
    for scene in payload.get("transcript_scenes") or []:
        scene_dict = _as_dict(scene)
        for key in ("summary", "quote", "supporting_quote"):
            text = _first_text(scene_dict.get(key))
            if text:
                texts.append(text)
        for turn in _normalize_turns(scene_dict.get("turns")):
            text = _text(turn.get("text"))
            if text:
                texts.append(text)
        for ref in scene_dict.get("evidence_refs") or []:
            text = _first_text(_as_dict(ref).get("quote"))
            if text:
                texts.append(text)
    return texts


def _rows_from_llm3_moments(moments: list[dict[str, Any]]) -> list[list[str]]:
    rows: list[list[str]] = []
    for index, moment in enumerate(moments[:4], start=1):
        label = _first_text(moment.get("moment"), f"Момент {index}")
        what = _first_text(moment.get("what"), moment.get("moment_summary"))
        fragment = _first_text(
            moment.get("supporting_quote"),
            moment.get("fragment"),
            _first_evidence_quote(moment.get("evidence_refs")),
        )
        better = _first_text(moment.get("better"), moment.get("recommendation"))
        if not (label and what and fragment and better):
            continue
        rows.append(
            [
                label,
                what if _norm(what).startswith("что было") else f"Что было не так: {what}",
                fragment if _norm(fragment).startswith("фрагмент") else f"Фрагмент: {fragment}",
                better if _norm(better).startswith(("сказать", "сделать")) else f"Сказать: {better}",
            ]
        )
    return rows


def _repair_weak_rows_with_payload_context(
    rows: list[list[Any]],
    moments: list[dict[str, Any]],
    payload: dict[str, Any],
) -> list[list[Any]]:
    repaired: list[list[Any]] = []
    for index, row in enumerate(rows):
        next_row = list(row)
        fragment = _strip_fragment_prefix(next_row[2] if len(next_row) > 2 else "")
        if (
            len(fragment) < 90
            or ("уточню" in _norm(fragment) and len(fragment) < 160)
            or not _looks_like_connected_dialogue(fragment)
        ):
            moment = moments[index] if index < len(moments) else {}
            quote = _first_text(
                fragment,
                _as_dict(moment).get("supporting_quote"),
                _first_evidence_quote(_as_dict(moment).get("evidence_refs")),
            )
            expanded = _context_for_quote_from_payload(quote, payload)
            if expanded:
                next_row[2] = expanded
        repaired.append(next_row)
    return repaired


def _repair_counter_evidence_claims(
    *,
    rows: list[list[Any]],
    moments: list[dict[str, Any]],
    payload: dict[str, Any],
) -> tuple[list[list[Any]], list[dict[str, Any]], dict[str, Any]]:
    """Soften absolute LLM3 missing-qualification claims when scenes contradict them."""
    counter_turns = _manager_user_role_counter_evidence_turns(payload)
    diagnostics: dict[str, Any] = {
        "status": "not_applicable",
        "repairs_count": 0,
        "repairs": [],
        "counter_evidence_turns": [
            {
                "scene_id": item.get("scene_id"),
                "turn_index": item.get("turn_index"),
                "quote": item.get("text"),
            }
            for item in counter_turns[:5]
        ],
    }
    if not counter_turns:
        return rows, moments, diagnostics

    repaired_rows = [list(row) for row in rows]
    repaired_moments = [dict(moment) for moment in moments]
    repairs: list[dict[str, Any]] = []

    for index, row in enumerate(repaired_rows):
        claim_text = _text(row[1] if len(row) > 1 else "")
        if not _claims_absolute_missing_user_role_qualification(claim_text):
            continue
        repaired = _soften_user_role_missing_claim(claim_text, counter_turns)
        if repaired == claim_text:
            continue
        row[1] = repaired
        repairs.append(
            {
                "target": "row",
                "index": index + 1,
                "original": claim_text,
                "repaired": repaired,
                "counter_evidence_quote": counter_turns[0]["text"],
            }
        )

    for index, moment in enumerate(repaired_moments):
        for field in ("what", "moment_summary", "proof_explanation"):
            claim_text = _text(moment.get(field))
            if not _claims_absolute_missing_user_role_qualification(claim_text):
                continue
            repaired = _soften_user_role_missing_claim(claim_text, counter_turns)
            if repaired == claim_text:
                continue
            moment[field] = repaired
            repairs.append(
                {
                    "target": f"moment.{field}",
                    "index": index + 1,
                    "original": claim_text,
                    "repaired": repaired,
                    "counter_evidence_quote": counter_turns[0]["text"],
                }
            )
        if any(item["target"].startswith("moment.") and item["index"] == index + 1 for item in repairs):
            moment["counter_evidence_repair"] = {
                "status": "repaired",
                "reason": "manager_user_role_qualification_turn_found",
                "counter_evidence_quotes": [item["text"] for item in counter_turns[:3]],
            }

    if repairs:
        diagnostics.update(
            {
                "status": "repaired",
                "repairs_count": len(repairs),
                "repairs": repairs,
                "reason": "absolute_missing_user_role_qualification_claim_softened",
            }
        )
    else:
        diagnostics["status"] = "passed_no_conflict"
    return repaired_rows, repaired_moments, diagnostics


def _manager_user_role_counter_evidence_turns(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for scene in payload.get("transcript_scenes") or []:
        scene_dict = _as_dict(scene)
        for index, turn in enumerate(scene_dict.get("turns") or []):
            item = _as_dict(turn)
            speaker = _normalize_speaker_label(item.get("speaker"))
            text = _text(item.get("text"))
            if speaker != "manager" or not text:
                continue
            text_norm = _norm(text)
            if any(term in text_norm for term in _USER_ROLE_COUNTER_EVIDENCE_TERMS):
                enriched = dict(item)
                enriched["scene_id"] = scene_dict.get("scene_id")
                enriched["turn_index"] = item.get("turn_index", index)
                enriched["text"] = text
                result.append(enriched)
    return result


def _claims_absolute_missing_user_role_qualification(value: Any) -> bool:
    text = _norm(value)
    if not text:
        return False
    if "начал уточнять" in text or "начала уточнять" in text:
        return False
    has_absolute_missing = any(term in text for term in _ABSOLUTE_MISSING_QUALIFICATION_TERMS)
    has_user_role_object = any(term in text for term in _USER_ROLE_CLAIM_OBJECT_TERMS)
    return has_absolute_missing and has_user_role_object


def _soften_user_role_missing_claim(
    value: Any,
    counter_turns: list[dict[str, Any]],
) -> str:
    text = _text(value)
    if not text:
        return text
    prefix = "Что было не так: "
    body = text
    if _norm(body).startswith("что было не так:"):
        body = body.split(":", 1)[1].strip()
    counter_quote = _text(counter_turns[0].get("text")) if counter_turns else ""
    repaired_body = (
        "Менеджер начал уточнять пользователей/участников, "
        "но не зафиксировал роли, кто должен подключиться к следующему шагу, "
        "и как это влияет на демонстрацию или продолжение сделки."
    )
    if counter_quote:
        repaired_body = (
            f"Менеджер начал уточнять пользователей/участников "
            f"(например: «{counter_quote}»), но не зафиксировал роли, "
            "кто должен подключиться к следующему шагу, и как это влияет на "
            "демонстрацию или продолжение сделки."
        )
    return prefix + repaired_body if _norm(text).startswith("что было не так:") else repaired_body


def _context_for_quote_from_payload(quote: Any, payload: dict[str, Any]) -> str | None:
    quote_norm = _loose_norm(_strip_fragment_prefix(quote))
    if not quote_norm:
        return None
    for scene in payload.get("transcript_scenes") or []:
        raw_turns = [_as_dict(item) for item in _as_dict(scene).get("turns") or []]
        matched_index = None
        for index, turn in enumerate(raw_turns):
            turn_norm = _loose_norm(turn.get("text"))
            if quote_norm and (
                quote_norm in turn_norm
                or turn_norm in quote_norm
                or turn_norm.startswith(quote_norm)
                or quote_norm.startswith(turn_norm)
            ):
                matched_index = index
                break
        if matched_index is None:
            continue
        start = max(0, matched_index - 2)
        end = min(len(raw_turns), matched_index + 3)
        selected = [turn for turn in raw_turns[start:end] if _text(turn.get("text"))]
        if len(selected) < 2:
            continue
        context = _clip(_join_turns(selected), limit=620)
        if len(context) >= 90:
            return context
    return None


def _payload_is_complex_b2b(payload: dict[str, Any]) -> bool:
    rules = _as_dict(payload.get("composition_rules"))
    if rules.get("complex_b2b_detected") is True:
        return True
    text_parts = [
        json.dumps(_as_dict(payload.get("selected_call")), ensure_ascii=False),
        json.dumps(_as_dict(payload.get("situation_evidence_packet")), ensure_ascii=False),
        json.dumps(payload.get("transcript_scenes") or [], ensure_ascii=False),
    ]
    text = _norm(" ".join(text_parts))
    return sum(1 for term in _B2B_TERMS if term in text) >= 2


def _detect_complex_b2b_from_payload_parts(
    *,
    selected_call: dict[str, Any],
    situation_evidence_packet: dict[str, Any],
    transcript_scenes: list[dict[str, Any]],
) -> bool:
    text = _norm(
        " ".join(
            [
                json.dumps(selected_call, ensure_ascii=False),
                json.dumps(situation_evidence_packet, ensure_ascii=False),
                json.dumps(transcript_scenes, ensure_ascii=False),
            ]
        )
    )
    return sum(1 for term in _B2B_TERMS if term in text) >= 2


def _first_weak_context_row_index(rows: list[list[Any]]) -> int | None:
    for index, row in enumerate(rows, start=1):
        fragment = _strip_fragment_prefix(row[2] if len(row) > 2 else "")
        if len(fragment) < 90:
            return index
        if "уточню" in _norm(fragment) and len(fragment) < 160 and not _looks_like_connected_dialogue(fragment):
            return index
    return None


def _looks_like_connected_dialogue(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    speaker_hits = len(re.findall(r"\b(?:клиент|менеджер|оператор|customer|manager)\s*:", text, flags=re.IGNORECASE))
    return speaker_hits >= 2


def _strip_fragment_prefix(value: Any) -> str:
    text = _text(value)
    lowered = text.lower()
    if lowered.startswith("фрагмент:"):
        return text.split(":", 1)[1].strip()
    return text


def _compose_deterministic_moments(contract: dict[str, Any]) -> list[dict[str, str]]:
    situation = _as_dict(contract.get("situation_day"))
    call_context = _as_dict(contract.get("call_context"))
    context_text = _text(call_context.get("context_text"))
    turns = _normalize_turns(call_context.get("turns"))
    if not context_text:
        return []

    is_b2b = _is_complex_b2b_context(contract)
    proof_main = _fragment_from_turns(
        turns=turns,
        preferred_terms=_REQUIREMENT_TERMS if is_b2b else _B2B_TERMS,
        fallback=context_text,
        limit=620,
    )
    proof_next = _fragment_from_turns(
        turns=turns[-8:] if turns else [],
        preferred_terms=(
            "давайте сейчас уточню",
            "уточню",
            "перезвоню",
            "перезвон",
            "созвон",
            "демо",
            "завтра",
            "следующ",
            "дальше",
            "время",
        ),
        fallback=context_text,
        limit=520,
    )
    proof_value = _fragment_from_turns(
        turns=turns,
        preferred_terms=("ценност", "риск", "потер", "контрол", "соглас", "доступ", "кабинет"),
        fallback=context_text,
        limit=540,
    )

    if is_b2b:
        moments = [
            {
                "code": "requirements_summary_missing",
                "title": "Нет резюме требований",
                "label": "Момент 1 - требования",
                "what": (
                    "Менеджер услышал сложный запрос, но не собрал его в короткое резюме: "
                    "сколько организаций/пользователей, какие роли доступа нужны, кто согласует "
                    "и какой результат клиент хочет получить."
                ),
                "fragment": proof_main,
                "recommendation": (
                    "Сначала зафиксировать требования: «Правильно понимаю, у вас несколько школ, "
                    "нужен общий кабинет, разные доступы и понятный порядок подписания? "
                    "Давайте я это запишу и проверю решение по каждому пункту»."
                ),
            },
            {
                "code": "managed_next_step_missing",
                "title": "Нет управляемого следующего шага",
                "label": "Момент 2 - следующий шаг",
                "what": (
                    "После выявления потребности разговор не был переведен в управляемый следующий шаг: "
                    "не закреплены участники, срок возврата, формат продолжения и вопрос, который менеджер "
                    "берет на проверку."
                ),
                "fragment": proof_next,
                "recommendation": (
                    "Закрывать этап договоренностью: «Я проверю сценарий по общему кабинету и доступам, "
                    "вернусь сегодня/завтра с вариантом. Давайте сразу поставим короткий созвон на 15 минут, "
                    "чтобы пройтись по решению и следующим действиям»."
                ),
            },
            {
                "code": "value_risk_not_reinforced",
                "title": "Не усилена ценность и риск",
                "label": "Момент 3 - ценность",
                "what": (
                    "Менеджер не связал решение с бизнес-риском клиента: контроль доступа, согласование "
                    "между школами, скорость подписания и снижение ручных ошибок остались без акцента."
                ),
                "fragment": proof_value,
                "recommendation": (
                    "Показывать ценность через последствия: «Если доступы и роли не настроить сразу, "
                    "документы будут зависать между школами. Я предложу схему, где видно, кто подписывает, "
                    "кто контролирует и где не будет ручной пересылки»."
                ),
            },
        ]
    else:
        missing_action = _text(situation.get("missing_action")) or "не был зафиксирован конкретный следующий шаг"
        manager_lesson = _text(situation.get("manager_lesson")) or "согласовать конкретное продолжение разговора"
        moments = [
            {
                "code": "problem_chain_not_unpacked",
                "title": "Проблема не разложена",
                "label": "Момент 1 - суть проблемы",
                "what": (
                    "Менеджер услышал важный сигнал клиента, но не разложил его до понятной цепочки: "
                    f"что клиенту нужно, что уже ясно и что осталось проверить. Ключевой пробел: {missing_action}."
                ),
                "fragment": proof_main,
                "recommendation": (
                    "Сформулировать вслух короткое резюме ситуации клиента и отдельно назвать один вопрос, "
                    "который нужно закрыть перед следующим шагом."
                ),
            },
            {
                "code": "next_action_not_fixed",
                "title": "Не закреплено действие",
                "label": "Момент 2 - действие",
                "what": "Разговору не хватает конкретного закрепления: кто что делает, в какой срок и зачем.",
                "fragment": proof_next,
                "recommendation": f"В конце звонка явно согласовать действие: «{manager_lesson}» и назначить срок возврата.",
            },
        ]

    call_id = _text(contract.get("call_id"))
    return [
        _with_quality_fields({**moment, "call_id": call_id})
        for moment in moments[:4]
        if _text(moment.get("fragment"))
    ]


def _with_quality_fields(moment: dict[str, str]) -> dict[str, str]:
    result = dict(moment)
    result.setdefault("call_id", "")
    result.setdefault("moment", result.get("label") or result.get("title") or "Момент")
    result.setdefault("moment_summary", result.get("what") or "")
    result.setdefault("supporting_quote", result.get("fragment") or "")
    result.setdefault("supporting_quote_proof_type", result.get("proof_type") or "sequence_inference")
    result.setdefault("better", result.get("recommendation") or "")
    result.setdefault("evidence_strength", "medium")
    result.setdefault("proof_type", "sequence_inference")
    result.setdefault("quote_role", "supports_context")
    result.setdefault("proof_explanation", result.get("what") or "")
    result.setdefault("evidence_refs", [{"source": CALL_BREAKDOWN_SOURCE, "quote": result.get("fragment") or ""}])
    return result


def _is_complex_b2b_context(contract: dict[str, Any]) -> bool:
    text = _norm(
        " ".join(
            [
                _text(_as_dict(contract.get("call_context")).get("context_text")),
                _text(_as_dict(contract.get("situation_day")).get("problem_claim")),
                _text(_as_dict(contract.get("situation_day")).get("what_happened")),
            ]
        )
    )
    return sum(1 for term in _B2B_TERMS if term in text) >= 2


def _transcript_scenes_from_packet(
    *,
    call_id: str,
    stage_code: str | None,
    context_text: str,
    turns: list[dict[str, str]],
    packet: dict[str, Any],
    artifact_turns: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    scenes: list[dict[str, Any]] = []
    source_turns = list(artifact_turns or [])
    if source_turns:
        for scene_id, purpose, terms in (
            (
                "client_context",
                "discovery",
                ("сеть школ", "частных школ", "рассматриваем", "смс", "законодатель", "подписание"),
            ),
            (
                "qualification",
                "qualification",
                ("документов в месяц", "команде", "пользоваться", "доступ", "50 человек", "юристы"),
            ),
            (
                "requirements",
                "requirements",
                (*_REQUIREMENT_TERMS, "головной офис", "общий кабинет", "видели", "все договора"),
            ),
            (
                "closing_next_step",
                "next_step",
                (*_NEXT_STEP_TERMS, "перезвоню", "уточню", "демо", "созвон"),
            ),
        ):
            scene = _scene_around_terms(
                call_id=call_id,
                stage_code=stage_code,
                scene_id=scene_id,
                purpose=purpose,
                turns=source_turns,
                terms=terms,
                before=2,
                after=4,
            )
            if scene is not None:
                scenes.append(scene)

    excerpt = _as_dict(packet.get("dialogue_excerpt"))
    enriched_turns = _enrich_packet_turns_with_segment_roles(turns, source_turns)
    evidence_refs = []
    for index, turn in enumerate(enriched_turns[:12]):
        quote = _text(turn.get("text"))
        if quote:
            evidence_refs.append(
                {
                    "ref_id": f"situation_context:{index}",
                    "call_id": call_id,
                    "scene_id": "situation_context",
                    "turn_indexes": [index],
                    "quote": quote,
                }
            )
    explicit_quote = _first_text(
        excerpt.get("quote"),
        packet.get("supporting_quote"),
        packet.get("evidence_scene"),
    )
    if explicit_quote:
        evidence_refs.append(
            {
                "ref_id": "situation_context:packet_quote",
                "call_id": call_id,
                "scene_id": "situation_context",
                "turn_indexes": [],
                "quote": explicit_quote,
            }
        )
    scenes.append(
        {
            "scene_id": "situation_context",
            "call_id": call_id,
            "stage_code": stage_code,
            "purpose": "verified_situation_day",
            "summary": context_text,
            "turns": enriched_turns[:16],
            "evidence_refs": evidence_refs[:16],
        }
    )
    return _dedupe_scenes(scenes)


def _scene_around_terms(
    *,
    call_id: str,
    stage_code: str | None,
    scene_id: str,
    purpose: str,
    turns: list[dict[str, Any]],
    terms: Iterable[str],
    before: int,
    after: int,
) -> dict[str, Any] | None:
    norm_terms = tuple(_norm(term) for term in terms if _norm(term))
    matched_index = None
    best_score = 0
    for index, turn in enumerate(turns):
        text_norm = _norm(turn.get("text"))
        score = sum(1 for term in norm_terms if term in text_norm)
        if score > best_score:
            best_score = score
            matched_index = index
    if matched_index is None:
        return None
    start = max(0, matched_index - before)
    end = min(len(turns), matched_index + after + 1)
    selected = [dict(item) for item in turns[start:end] if _text(item.get("text"))]
    if len(selected) < 2:
        return None
    evidence_refs = [
        {
            "ref_id": f"{scene_id}:{turn.get('turn_index', start + offset)}",
            "call_id": call_id,
            "scene_id": scene_id,
            "turn_indexes": [turn.get("turn_index", start + offset)],
            "quote": _text(turn.get("text")),
        }
        for offset, turn in enumerate(selected)
        if _text(turn.get("text"))
    ]
    return {
        "scene_id": scene_id,
        "call_id": call_id,
        "stage_code": stage_code,
        "purpose": purpose,
        "summary": _clip(_join_turns(selected), limit=520),
        "turns": selected[:8],
        "evidence_refs": evidence_refs[:8],
    }


def _dedupe_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, ...]] = set()
    for scene in scenes:
        turns = [_text(_as_dict(turn).get("text")) for turn in scene.get("turns") or []]
        key = tuple(_norm(turn)[:80] for turn in turns if turn)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        result.append(scene)
        if len(result) >= 5:
            break
    return result


def _turns_from_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scene in scenes:
        for turn in scene.get("turns") or []:
            item = _as_dict(turn)
            text = _text(item.get("text"))
            key = _norm(text)
            if not text or key in seen:
                continue
            seen.add(key)
            result.append(item)
            if len(result) >= 24:
                return result
    return result


def _llm2_facts_from_artifact(
    *,
    artifact: Any | None,
    score_by_stage: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    analysis_obj = _obj_get(artifact, "analysis") or _obj_get(artifact, "original_analysis")
    scores_detail = _as_dict(_obj_get(analysis_obj, "scores_detail") or _dict_get(artifact, "analysis"))
    report_evidence = _as_dict(_obj_get(analysis_obj, "report_evidence"))
    return {
        "business_outcome": _first_text(
            _dict_get(scores_detail, "business_outcome"),
            _dict_get(_as_dict(scores_detail.get("call")), "business_outcome"),
        ),
        "call_report_summary": _first_text(
            _dict_get(scores_detail, "summary"),
            _dict_get(_as_dict(scores_detail.get("call")), "summary"),
        ),
        "score_by_stage": score_by_stage or scores_detail.get("score_by_stage") or [],
        "report_evidence": report_evidence,
        "semantic_case": _as_dict(scores_detail.get("semantic_case")),
        "manager_coaching_moments": scores_detail.get("manager_coaching_moments") or [],
        "block_candidates": _as_dict(report_evidence.get("block_candidates")),
    }


def _llm3_enabled() -> bool:
    try:
        from app.core_shared.config.settings import settings
    except Exception:
        return False
    return bool(settings.llm3_enabled)


def _read_llm3_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return (
            "Return one JSON object for Call Breakdown. Use only provided facts. "
            "If fewer than two grounded moments are available, return status='insufficient'."
        )


def _extract_openai_message_content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return str(content or "").strip()


def _first_evidence_quote(evidence_refs: Any) -> str | None:
    for ref in evidence_refs or []:
        quote = _text(_as_dict(ref).get("quote"))
        if quote:
            return quote
    return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _find_artifact_by_call_id(artifacts: Iterable[Any], call_id: str) -> Any | None:
    for artifact in artifacts or []:
        interaction = _obj_get(artifact, "interaction")
        candidate_id = _text(
            _obj_get(interaction, "id")
            or _dict_get(artifact, "call_id")
            or _dict_get(artifact, "interaction_id")
            or _dict_get(interaction, "interaction_id")
        )
        if candidate_id == call_id:
            return artifact
    return None


def _call_reference(
    *,
    call_id: str,
    packet_excerpt: dict[str, Any],
    artifact: Any | None,
) -> dict[str, Any]:
    started_at = _coerce_datetime(
        _obj_get(artifact, "call_started_at")
        or _dict_get(artifact, "call_started_at")
        or _metadata_value(artifact, "call_date")
        or _metadata_value(artifact, "started_at")
    )
    client_phone = _first_text(
        packet_excerpt.get("client_phone"),
        _metadata_value(artifact, "contact_phone"),
        _metadata_value(artifact, "client_phone"),
        _metadata_value(artifact, "phone"),
        _analysis_call_value(artifact, "contact_phone"),
        _analysis_call_value(artifact, "client_phone"),
    )
    client_label = _first_text(
        packet_excerpt.get("client_label"),
        _metadata_value(artifact, "contact_name"),
        _metadata_value(artifact, "client_name"),
        _metadata_value(artifact, "contact_label"),
        client_phone,
        "Клиент",
    )
    date_label = _first_text(
        packet_excerpt.get("date_label"),
        started_at.date().isoformat() if started_at is not None else None,
    )
    time_label = _first_text(
        packet_excerpt.get("time_label"),
        started_at.strftime("%H:%M") if started_at is not None else None,
        "—",
    )
    reference = _first_text(
        packet_excerpt.get("client_call_reference"),
        _build_client_call_reference(
            client_label=client_label,
            client_phone=client_phone,
            started_at=started_at,
        ),
    )
    return {
        "call_id": call_id,
        "client_label": client_label,
        "client_phone": client_phone,
        "date_label": date_label,
        "time_label": time_label,
        "client_call_reference": reference,
    }


def _build_client_call_reference(
    *,
    client_label: str | None,
    client_phone: str | None,
    started_at: datetime | None,
) -> str | None:
    label = _text(client_label) or _text(client_phone)
    parts = []
    if label:
        parts.append(label)
    if started_at is not None:
        parts.append(started_at.strftime("%Y-%m-%d %H:%M"))
    return ", ".join(parts) or None


def _stage_name_from_scores(
    score_by_stage: list[dict[str, Any]] | None,
    stage_code: str | None,
) -> str | None:
    if not stage_code:
        return None
    for item in score_by_stage or []:
        raw = _as_dict(item)
        if _text(raw.get("stage_code")) == stage_code:
            return _first_text(raw.get("stage_name"), raw.get("label"), raw.get("name"))
    return None


def _normalize_turns(raw_turns: Any) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for raw in raw_turns or []:
        item = _as_dict(raw)
        text = _compact(item.get("text") or item.get("utterance") or item.get("message"))
        if not text:
            continue
        speaker = _normalize_speaker_label(item.get("speaker") or item.get("role") or "context")
        turn: dict[str, Any] = {"speaker": speaker, "text": text}
        for key in ("start_sec", "end_sec", "start_ms", "end_ms", "turn_index", "raw_speaker"):
            if item.get(key) is not None:
                turn[key] = item.get(key)
        turns.append(turn)
    return turns


def _turns_from_artifact_segments(artifact: Any | None) -> list[dict[str, Any]]:
    interaction = _obj_get(artifact, "interaction")
    metadata = _as_dict(_obj_get(interaction, "metadata_") or _obj_get(interaction, "metadata"))
    segments = [item for item in metadata.get("segments") or [] if isinstance(item, dict)]
    if not segments:
        return []
    raw_turns: list[dict[str, Any]] = []
    raw_speakers = {_text(segment.get("speaker")).upper() for segment in segments if _text(segment.get("speaker"))}
    diarization_is_useful = len(raw_speakers) >= 2
    speaker_map = _speaker_map_from_segments(segments) if diarization_is_useful else {}
    for index, segment in enumerate(segments):
        raw_speaker = _text(segment.get("speaker")).upper()
        text = _compact(segment.get("text"))
        if not text:
            continue
        chunks = _split_segment_text(text)
        if not chunks:
            continue
        for chunk_index, chunk in enumerate(chunks):
            speaker = speaker_map.get(raw_speaker) or _infer_turn_speaker(chunk)
            raw_turns.append(
                {
                    "speaker": speaker,
                    "raw_speaker": raw_speaker or None,
                    "text": chunk,
                    "turn_index": len(raw_turns),
                    "segment_index": index,
                    "start_ms": segment.get("start_ms"),
                    "end_ms": segment.get("end_ms"),
                    "chunk_index": chunk_index,
                }
            )
    return raw_turns


def _turns_from_transcript(transcript: str) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    chunks = transcript.splitlines()
    if len(chunks) <= 1:
        chunks = re.split(r"(?<=[.!?])\s+", transcript)
    for index, line in enumerate(chunks):
        text = _compact(line)
        if not text:
            continue
        speaker = "context"
        body = text
        match = re.match(r"^([^:]{1,40}):\s*(.+)$", text)
        if match:
            speaker = _normalize_speaker_label(match.group(1).strip())
            body = match.group(2).strip()
        elif len(chunks) > 1:
            speaker = _infer_turn_speaker(body)
        turns.append({"speaker": speaker, "text": body, "turn_index": index})
    return turns


def _split_segment_text(text: str) -> list[str]:
    text = _compact(text)
    if not text:
        return []
    pieces = [piece.strip() for piece in re.split(r"(?<=[.!?])\s+", text) if piece.strip()]
    if not pieces:
        pieces = [text]
    result: list[str] = []
    for piece in pieces:
        if len(piece) <= 260:
            result.append(piece)
            continue
        words = piece.split()
        current: list[str] = []
        for word in words:
            current.append(word)
            if len(" ".join(current)) >= 180:
                result.append(" ".join(current))
                current = []
        if current:
            result.append(" ".join(current))
    return result[:6]


def _speaker_map_from_segments(segments: list[dict[str, Any]]) -> dict[str, str]:
    scores: dict[str, dict[str, int]] = {}
    for segment in segments:
        raw_speaker = _text(segment.get("speaker")).upper()
        if not raw_speaker:
            continue
        bucket = scores.setdefault(raw_speaker, {"manager": 0, "client": 0})
        text = _norm(segment.get("text"))
        bucket["manager"] += _speaker_role_score(text, "manager")
        bucket["client"] += _speaker_role_score(text, "client")
    if len(scores) < 2:
        return {}
    ranked_client = sorted(scores.items(), key=lambda item: item[1]["client"] - item[1]["manager"], reverse=True)
    client_speaker = ranked_client[0][0]
    ranked_manager = sorted(
        ((speaker, score) for speaker, score in scores.items() if speaker != client_speaker),
        key=lambda item: item[1]["manager"] - item[1]["client"],
        reverse=True,
    )
    manager_speaker = ranked_manager[0][0] if ranked_manager else None
    result = {client_speaker: "client"}
    if manager_speaker:
        result[manager_speaker] = "manager"
    return result


def _infer_turn_speaker(text: str) -> str:
    normalized = _norm(text)
    manager_score = _speaker_role_score(normalized, "manager")
    client_score = _speaker_role_score(normalized, "client")
    if manager_score > client_score and manager_score >= 1:
        return "manager"
    if client_score > manager_score and client_score >= 1:
        return "client"
    return "unknown"


def _speaker_role_score(text: str, role: str) -> int:
    if role == "manager":
        terms = (
            "компания договор",
            "можно спросить",
            "хотел уточнить",
            "подскажите",
            "понял",
            "услышал",
            "давайте сейчас уточню",
            "перезвоню",
            "сколько у вас",
            "до этого не пользовались",
            "планирует пользоваться",
        )
    else:
        terms = (
            "у нас",
            "нам нужно",
            "мы рассматриваем",
            "сеть школ",
            "частных школ",
            "головной офис",
            "16 школ",
            "до 50 человек",
            "с родителями",
            "не пользовались",
            "такое можно сделать",
        )
    return sum(1 for term in terms if term in text)


def _normalize_speaker_label(value: Any) -> str:
    speaker = _text(value).lower()
    if speaker in {"client", "customer", "клиент"}:
        return "client"
    if speaker in {"manager", "seller", "agent", "менеджер", "оператор"}:
        return "manager"
    if speaker in {"evidence", "доказательный фрагмент"}:
        return "evidence"
    if speaker in {"context", "unknown", "фрагмент", ""}:
        return "context" if speaker == "context" else "unknown"
    return speaker


def _enrich_packet_turns_with_segment_roles(
    packet_turns: list[dict[str, Any]],
    artifact_turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not packet_turns or not artifact_turns:
        return packet_turns
    result: list[dict[str, Any]] = []
    for packet_turn in packet_turns:
        item = dict(packet_turn)
        speaker = _normalize_speaker_label(item.get("speaker"))
        if speaker in {"context", "unknown", "evidence"}:
            matched = _match_artifact_turn(item.get("text"), artifact_turns)
            matched_speaker = _text(_as_dict(matched).get("speaker"))
            if matched_speaker in {"manager", "client"}:
                item["speaker"] = matched_speaker
                item["speaker_inference_source"] = "matched_transcript_segment"
            else:
                item["speaker"] = speaker
        result.append(item)
    return result


def _match_artifact_turn(text: Any, artifact_turns: list[dict[str, Any]]) -> dict[str, Any] | None:
    needle = _norm(text)
    if not needle:
        return None
    for turn in artifact_turns:
        haystack = _norm(turn.get("text"))
        if needle in haystack or haystack in needle:
            return turn
    return None


def _fragment_from_turns(
    *,
    turns: list[dict[str, str]],
    preferred_terms: Iterable[str],
    fallback: str,
    limit: int,
) -> str:
    terms = tuple(preferred_terms)
    selected: list[dict[str, str]] = []
    if turns:
        for index, turn in enumerate(turns):
            turn_norm = _norm(turn.get("text"))
            if any(term in turn_norm for term in terms):
                start = max(0, index - 1)
                end = min(len(turns), index + 3)
                selected = turns[start:end]
                break
        if not selected:
            selected = turns[: min(len(turns), 5)]
    fragment = _join_turns(selected) if selected else fallback
    return _clip(fragment, limit=limit) or _MISSING_FRAGMENT_NOTE


def _join_turns(turns: list[dict[str, str]]) -> str:
    speaker_labels = {
        "client": "Клиент",
        "customer": "Клиент",
        "manager": "Менеджер",
        "evidence": "Доказательный фрагмент",
        "context": "Контекст",
        "unknown": "Контекст",
    }
    parts = []
    for turn in turns:
        speaker = _text(turn.get("speaker")).lower() or "context"
        label = speaker_labels.get(speaker, speaker.capitalize())
        text = _text(turn.get("text"))
        if text:
            parts.append(f"{label}: {text}")
    return _compact(" ".join(parts))


def _metadata_value(artifact: Any | None, key: str) -> Any:
    if artifact is None:
        return None
    interaction = _obj_get(artifact, "interaction")
    metadata = {}
    metadata.update(_as_dict(_obj_get(interaction, "metadata_") or _obj_get(interaction, "metadata")))
    metadata.update(_as_dict(_dict_get(artifact, "metadata")))
    return metadata.get(key)


def _analysis_call_value(artifact: Any | None, key: str) -> Any:
    if artifact is None:
        return None
    analysis_obj = _obj_get(artifact, "analysis") or _obj_get(artifact, "original_analysis")
    detail = _as_dict(_obj_get(analysis_obj, "scores_detail") or _dict_get(artifact, "analysis"))
    return _as_dict(detail.get("call")).get(key)


def _obj_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _dict_get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else default


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text(value)
        if text:
            return text
    return None


def _text(value: Any) -> str:
    return _compact(value)


def _compact(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text.strip()


def _clip(value: Any, *, limit: int) -> str:
    text = _compact(value)
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].strip()
    return f"{clipped}..."


def _norm(value: Any) -> str:
    return _compact(value).lower().replace("ё", "е")


def _loose_norm(value: Any) -> str:
    text = _norm(value)
    return _compact(re.sub(r"[^0-9a-zа-я]+", " ", text))


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = _text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
