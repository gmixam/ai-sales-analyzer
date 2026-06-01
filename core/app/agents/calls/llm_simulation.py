"""Temporary LLM simulation executor for report-quality testing.

This module replaces only the runtime model call. Validators, normalizers,
persistence, report selection, and renderers must continue to run unchanged.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

from app.core_shared.config.settings import settings

_ARTIFACT_COUNTER = count(1)


@dataclass(frozen=True, slots=True)
class SubagentLLMResult:
    """Result returned by an external LLM subagent runner."""

    content: str
    metadata: dict[str, Any]


class SubagentRuntimeError(RuntimeError):
    """External LLM subagent runner failed or was unavailable."""

    def __init__(self, message: str, *, metadata: dict[str, Any] | None = None):
        self.metadata = metadata or {}
        super().__init__(message)


def simulation_enabled() -> bool:
    """Return whether temporary LLM simulation mode is active."""
    raw = os.getenv("AI_LLM_SIMULATION_ENABLED")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(settings.ai_llm_simulation_enabled)


def is_llm_simulation_enabled(layer: str | None = None) -> bool:
    """Return whether the shared LLM test/runtime executor should intercept a call."""
    if (layer or "").strip().lower() == "llm3" and subagent_runtime_enabled():
        return True
    return simulation_enabled()


def llm_simulation_enabled(layer: str | None = None) -> bool:
    """Compatibility alias for composer-local adapters."""
    return is_llm_simulation_enabled(layer=layer)


def llm_execution_mode() -> str:
    """Return the configured LLM execution mode."""
    return (
        os.getenv("AI_LLM_EXECUTION_MODE")
        or getattr(settings, "ai_llm_execution_mode", "")
        or "openai_compatible"
    ).strip().lower()


def subagent_runtime_enabled() -> bool:
    """Return whether LLM calls must be executed by an external subagent runner."""
    raw = os.getenv("AI_LLM_SUBAGENT_RUNTIME_ENABLED")
    explicit = (
        raw.strip().lower() in {"1", "true", "yes", "on"}
        if raw is not None
        else bool(getattr(settings, "ai_llm_subagent_runtime_enabled", False))
    )
    return explicit or llm_execution_mode() in {
        "subagent_runtime",
        "agent_runtime",
        "external_subagent",
    }


def request_simulated_llm_content(
    *,
    layer: str,
    request_kind: str,
    messages: list[dict[str, str]],
    subject_key: str,
    instruction_version: str | None = None,
) -> str:
    """Return simulated JSON content for LLM-1 / LLM-2 analyzer calls."""
    input_payload = {
        "layer": layer,
        "request_kind": request_kind,
        "subject_key": subject_key,
        "instruction_version": instruction_version,
        "messages": messages,
    }
    context = _parse_last_user_json(messages)
    if layer == "llm1":
        result = _simulate_llm1(context)
    elif layer == "llm2":
        if str(request_kind or "").startswith("llm2a_"):
            result = _simulate_llm2a(context)
        elif str(request_kind or "").startswith("llm2b_"):
            result = _simulate_llm2b(context)
        elif str(request_kind or "").startswith("llm2c_"):
            result = _simulate_llm2c(context)
        elif str(request_kind or "").startswith("llm2d_"):
            result = _simulate_llm2d(context)
        else:
            result = _simulate_llm2(context, instruction_version=instruction_version)
    else:
        result = {
            "status": "failed",
            "reason": f"unsupported_simulation_layer:{layer}",
        }
    _write_artifacts(
        layer=layer,
        request_kind=request_kind,
        subject_key=subject_key,
        input_payload=input_payload,
        output_payload=result,
    )
    return json.dumps(result, ensure_ascii=False)


def request_simulated_llm3_json(
    *,
    request_kind: str,
    payload: dict[str, Any],
    prompt: str | None = None,
    subject_key: str = "llm3",
) -> dict[str, Any]:
    """Return simulated JSON for LLM-3 composer request functions."""
    if request_kind == "situation_day_daily_composer":
        result = _simulate_llm3_daily_situation(payload)
    elif request_kind == "call_breakdown_composer":
        result = _simulate_llm3_call_breakdown(payload)
    elif request_kind == "voice_of_customer_composer":
        result = _simulate_llm3_voice_of_customer(payload)
    elif request_kind == "call_tomorrow_wording_composer":
        result = _simulate_llm3_call_tomorrow(payload)
    else:
        result = {"status": "failed", "reason": f"unsupported_llm3_request:{request_kind}"}
    result["_routing"] = _simulated_routing_metadata(
        layer="llm3",
        request_kind=request_kind,
        subject_key=subject_key,
    )
    _write_artifacts(
        layer="llm3",
        request_kind=request_kind,
        subject_key=subject_key,
        input_payload={"prompt": prompt, "payload": payload},
        output_payload=result,
    )
    return result


def request_llm3_composer(**kwargs: Any) -> dict[str, Any]:
    """Compatibility wrapper for composer-local LLM-3 adapters."""
    request_kind = str(kwargs.get("request_kind") or kwargs.get("node") or "")
    payload = _as_dict(kwargs.get("payload") or kwargs.get("input_payload"))
    prompt = kwargs.get("prompt") or kwargs.get("system_prompt")
    subject_key = str(kwargs.get("subject_key") or "llm3")
    messages = kwargs.get("messages")
    if subagent_runtime_enabled():
        return request_subagent_llm3_json(
            request_kind=request_kind,
            payload=payload,
            prompt=prompt,
            subject_key=subject_key,
            messages=messages,
        )
    if simulation_enabled():
        return request_simulated_llm3_json(
            request_kind=request_kind,
            payload=payload,
            prompt=prompt,
            subject_key=subject_key,
        )
    return request_openai_compatible_llm3_json(
        request_kind=request_kind,
        payload=payload,
        prompt=prompt,
        subject_key=subject_key,
        messages=messages,
    )


def request_openai_compatible_llm3_json(
    *,
    request_kind: str,
    payload: dict[str, Any],
    prompt: str | None = None,
    subject_key: str = "llm3",
    messages: Any = None,
) -> dict[str, Any]:
    """Execute an LLM-3 composer boundary through the routed OpenAI-compatible API."""
    from openai import OpenAI

    from app.core_shared.ai_routing import AIProviderRouter

    route_plan = AIProviderRouter().build_route_plan(
        layer="llm3",
        subject_key=subject_key,
    )
    while True:
        candidate = route_plan.current_candidate()
        try:
            compatibility_candidate = candidate
            if (candidate.endpoint or "").rstrip("/") == "/chat/completions":
                compatibility_candidate = replace(candidate, endpoint=None)
            AIProviderRouter.ensure_execution_compatibility(
                compatibility_candidate,
                executor_label="LLM-3 OpenAI-compatible composer",
                required_execution_mode="openai_compatible",
            )
            client = OpenAI(
                api_key=candidate.resolved_api_key(),
                base_url=candidate.api_base,
            )
            request_messages = (
                messages if isinstance(messages, list) else _messages(prompt, payload)
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
                        messages=request_messages,
                    )
                    break
                except Exception as exc:
                    last_error = exc
            if response is None:
                raise last_error or RuntimeError("Unknown LLM-3 request failure")
            route_plan.mark_attempt_success()
            parsed = json.loads(_extract_openai_message_content(response))
            result = _as_dict(parsed)
            if not result:
                raise RuntimeError("LLM-3 OpenAI-compatible response is empty or non-object JSON")
            result["_routing"] = route_plan.to_metadata(
                request_kind=request_kind,
                usage=_extract_openai_usage_metadata(response),
                notes="LLM-3 OpenAI-compatible composer request completed.",
            )
            return result
        except Exception as exc:
            can_fallback = route_plan.mark_attempt_failure(str(exc))
            if can_fallback:
                continue
            raise


def request_subagent_llm3_json(
    *,
    request_kind: str,
    payload: dict[str, Any],
    prompt: str | None = None,
    subject_key: str = "llm3",
    messages: Any = None,
) -> dict[str, Any]:
    """Execute an LLM-3 composer boundary through an external subagent runner."""
    input_payload = {
        "layer": "llm3",
        "execution_mode": "subagent_runtime",
        "request_kind": request_kind,
        "subject_key": subject_key,
        "prompt": prompt,
        "payload": payload,
        "messages": messages if isinstance(messages, list) else _messages(prompt, payload),
    }
    input_path, output_path = _subagent_artifact_paths(
        layer="llm3",
        request_kind=request_kind,
        subject_key=subject_key,
    )
    _write_json_file(input_path, input_payload)
    try:
        result = _run_subagent_runner(
            input_payload=input_payload,
            input_path=input_path,
            output_path=output_path,
        )
    except Exception as exc:
        failure_payload = {
            "status": "failed",
            "reason": "subagent_runner_unavailable",
            "error": str(exc),
            "_routing": _subagent_routing_metadata(
                layer="llm3",
                request_kind=request_kind,
                subject_key=subject_key,
                input_path=input_path,
                output_path=output_path,
                execution_status="failed",
                error=str(exc),
            ),
        }
        _write_json_file(output_path, failure_payload)
        raise RuntimeError(f"LLM-3 subagent runtime unavailable: {exc}") from exc
    result = _as_dict(result)
    result.setdefault(
        "_routing",
        _subagent_routing_metadata(
            layer="llm3",
            request_kind=request_kind,
            subject_key=subject_key,
            input_path=input_path,
            output_path=output_path,
            execution_status="completed",
        ),
    )
    _write_json_file(output_path, result)
    return result


def request_subagent_llm_content(
    *,
    layer: str,
    request_kind: str,
    messages: list[dict[str, str]],
    subject_key: str,
    instruction_version: str | None = None,
    input_payload: dict[str, Any] | None = None,
) -> SubagentLLMResult:
    """Execute an LLM-1 / LLM-2 analyzer boundary through an external subagent runner."""
    payload = input_payload or {
        "layer": layer,
        "execution_mode": "subagent_runtime",
        "request_kind": request_kind,
        "subject_key": subject_key,
        "instruction_version": instruction_version,
        "messages": messages,
    }
    payload["execution_mode"] = "subagent_runtime"
    input_path, output_path = _subagent_artifact_paths(
        layer=layer,
        request_kind=request_kind,
        subject_key=subject_key,
    )
    _write_json_file(input_path, payload)
    try:
        result = _run_subagent_runner(
            input_payload=payload,
            input_path=input_path,
            output_path=output_path,
        )
    except Exception as exc:
        failure_payload = {
            "status": "failed",
            "reason": "subagent_runner_unavailable",
            "error": str(exc),
            "_routing": _subagent_routing_metadata(
                layer=layer,
                request_kind=request_kind,
                subject_key=subject_key,
                input_path=input_path,
                output_path=output_path,
                execution_status="failed",
                error=str(exc),
            ),
        }
        _write_json_file(output_path, failure_payload)
        raise SubagentRuntimeError(
            f"{layer.upper()} subagent runtime unavailable: {exc}",
            metadata=_as_dict(failure_payload.get("_routing")),
        ) from exc
    parsed = _as_dict(result)
    if not parsed:
        raise SubagentRuntimeError(
            f"{layer.upper()} subagent returned an empty or non-object JSON result"
        )
    content = _subagent_content_from_result(parsed)
    _write_json_file(output_path, parsed)
    metadata = _subagent_routing_metadata(
        layer=layer,
        request_kind=request_kind,
        subject_key=subject_key,
        input_path=input_path,
        output_path=output_path,
        execution_status="completed",
    )
    return SubagentLLMResult(content=content, metadata=metadata)


def write_simulation_artifact(**kwargs: Any) -> None:
    """Compatibility artifact writer for composer-local simulation adapters."""
    artifact_name = _safe_token(kwargs.get("artifact_name") or kwargs.get("name") or "artifact")
    payload = kwargs.get("data", kwargs.get("value", kwargs.get("payload")))
    base = Path(_artifact_dir())
    run_id = _safe_token(_run_id())
    try:
        run_dir = base / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / artifact_name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        return


def simulated_routing_metadata(
    *,
    layer: str,
    request_kind: str,
    subject_key: str,
) -> dict[str, Any]:
    """Build analyzer-compatible routing metadata for simulated calls."""
    if subagent_runtime_enabled():
        return _subagent_routing_metadata(
            layer=layer,
            request_kind=request_kind,
            subject_key=subject_key,
            input_path=None,
            output_path=None,
            execution_status="completed",
        )
    return _simulated_routing_metadata(
        layer=layer,
        request_kind=request_kind,
        subject_key=subject_key,
    )


def _parse_last_user_json(messages: list[dict[str, str]]) -> dict[str, Any]:
    for message in reversed(messages or []):
        if message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            continue
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _simulate_llm1(context: dict[str, Any]) -> dict[str, Any]:
    interaction = _as_dict(context.get("interaction"))
    transcript = _text(interaction.get("text"))
    expected = _as_dict(context.get("expected_output_shape"))
    classification = _as_dict(expected.get("classification"))
    summary = _as_dict(expected.get("summary"))
    follow_up = _as_dict(expected.get("follow_up"))
    data_quality = _as_dict(expected.get("data_quality"))
    classification.update(
        {
            "call_type": "sales_primary" if transcript else "other",
            "scenario_type": "repeat_contact" if "повтор" in transcript.lower() else "other",
            "channel_context": "phone_call",
            "analysis_eligibility": "eligible" if transcript else "not_eligible",
            "eligibility_reason": (
                "simulated_sales_relevant_transcript"
                if transcript
                else "simulated_empty_transcript"
            ),
            "analysis_confidence": "medium",
        }
    )
    summary.update(
        {
            "short_summary": _summary_sentence(transcript),
            "context": "Симулятор выделил общий контекст звонка из транскрипта.",
            "call_goal": "Понять потребность клиента и согласовать следующий шаг.",
            "outcome_code": "callback_planned",
            "outcome_text": "Следующий шаг требует уточнения после разговора.",
            "next_step_text": "Вернуться к клиенту с конкретным предложением.",
        }
    )
    follow_up.update(
        {
            "next_step_fixed": True,
            "next_step_type": "callback",
            "next_step_text": "Связаться с клиентом и уточнить интерес.",
            "owner": "manager",
            "due_date_text": "следующий рабочий день",
            "reason_not_fixed": None,
        }
    )
    data_quality.update(
        {
            "transcript_quality": "good" if transcript else "empty",
            "classification_quality": "simulated",
            "analysis_quality": "pending_llm2_simulation",
            "needs_manual_review": False,
            "manual_review_reason": None,
        }
    )
    return {
        "classification": classification,
        "summary": summary,
        "follow_up": follow_up,
        "data_quality": data_quality,
        "analysis_focus": [
            "Проверить, насколько менеджер связал предложение с контекстом клиента.",
            "Проверить, закреплен ли следующий шаг.",
        ],
    }


def _simulate_llm2(
    context: dict[str, Any],
    *,
    instruction_version: str | None,
) -> dict[str, Any]:
    interaction = _as_dict(context.get("interaction"))
    transcript = _text(interaction.get("text"))
    template = _as_dict(context.get("analysis_result_contract_template"))
    checklist = _as_dict(context.get("checklist_definition"))
    result = json.loads(json.dumps(template, ensure_ascii=False))
    result["instruction_version"] = instruction_version or result.get("instruction_version")
    result["analysis_timestamp"] = datetime.now(UTC).isoformat()
    result["classification"] = {
        **_as_dict(result.get("classification")),
        "call_type": "sales_primary" if transcript else "other",
        "scenario_type": "repeat_contact",
        "channel_context": "phone_call",
        "analysis_eligibility": "eligible" if transcript else "not_eligible",
        "eligibility_reason": (
            "simulated_sales_relevant_transcript"
            if transcript
            else "simulated_empty_transcript"
        ),
        "analysis_confidence": "medium",
    }
    result["summary"] = {
        **_as_dict(result.get("summary")),
        "short_summary": _summary_sentence(transcript),
        "context": "Клиент обсуждает возможную потребность, менеджер уточняет ситуацию и следующий шаг.",
        "call_goal": "Понять актуальность и договориться о дальнейшем контакте.",
        "outcome_code": "callback_planned",
        "outcome_text": "Контакт остается открытым, требуется следующий шаг.",
        "next_step_text": "Менеджеру нужно вернуться к клиенту с уточнением.",
    }
    score_by_stage = _build_simulated_score_by_stage(checklist, transcript)
    result["score_by_stage"] = score_by_stage
    result["strengths"] = [
        {
            "title": "Контакт поддержан спокойно",
            "impact": "Менеджер не создает лишнего давления и сохраняет рабочий тон.",
            "evidence": _evidence_text(transcript),
            "criterion_code": "cs_tone_and_clarity",
            "criterion_name": "Сохранил нейтральный, вежливый и понятный тон",
        }
    ]
    result["gaps"] = [
        {
            "title": "Следующий шаг требует конкретики",
            "impact": "Без четкого владельца и срока клиенту проще отложить решение.",
            "evidence": _evidence_text(transcript),
            "criterion_code": "cn_owner_and_deadline",
            "criterion_name": "Определил кто делает и когда",
        }
    ]
    result["recommendations"] = [
        {
            "priority": "high",
            "problem": "Следующий шаг требует конкретики",
            "why_it_matters": "Конкретный срок и владелец повышают шанс продолжения сделки.",
            "better_phrase": "Давайте зафиксируем: я отправлю информацию сегодня, а завтра до обеда вернусь к вам за решением.",
            "criterion_code": "cn_owner_and_deadline",
            "criterion_name": "Определил кто делает и когда",
            "evidence": _evidence_text(transcript),
        }
    ]
    result["agreements"] = [
        {
            "agreement_type": "callback",
            "text": "Менеджеру нужно вернуться к клиенту с уточнением.",
            "owner": "manager",
            "due_date_text": "следующий рабочий день",
            "status": "open",
            "evidence": _evidence_text(transcript),
        }
    ]
    result["follow_up"] = {
        **_as_dict(result.get("follow_up")),
        "next_step_fixed": True,
        "next_step_type": "callback",
        "next_step_text": "Вернуться к клиенту с конкретным предложением.",
        "owner": "manager",
        "due_date_text": "следующий рабочий день",
        "due_date_iso": None,
        "reason_not_fixed": None,
    }
    result["product_signals"] = [
        {
            "signal_type": "interest",
            "text": "В разговоре есть признак потенциального интереса или открытого вопроса.",
            "evidence": _evidence_text(transcript),
            "confidence": "medium",
        }
    ]
    result["evidence_fragments"] = [
        {
            "fragment_type": "missed_opportunity",
            "client_text": _evidence_text(transcript),
            "manager_text": None,
            "why": "Фрагмент используется симулятором как grounded evidence для проверки отчета.",
            "better_variant": "Сразу закрепить следующий шаг, владельца и срок.",
        }
    ]
    result["analytics_tags"] = ["llm_simulation", "manager_daily_testing"]
    result["data_quality"] = {
        **_as_dict(result.get("data_quality")),
        "transcript_quality": "good" if transcript else "empty",
        "classification_quality": "simulated",
        "analysis_quality": "simulated",
        "needs_manual_review": False,
        "manual_review_reason": None,
    }
    result["report_evidence_version"] = "v1"
    result["report_evidence"] = _build_simulated_report_evidence(interaction, transcript)
    return result


def _simulate_llm2a(context: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic LLM-2A facts/scenes artifact for layered tests."""
    interaction = _as_dict(context.get("interaction"))
    transcript = _text(interaction.get("text") or context.get("transcript"))
    call_id = _first_text(interaction.get("id"), context.get("call_id")) or "simulated_call"
    admission_gate = _as_dict(context.get("llm2_admission_gate"))
    admitted = admission_gate.get("admitted")
    quote_a, quote_b = _two_evidence_quotes(transcript)
    evidence_ledger = []
    if quote_a:
        evidence_ledger.append(
            {
                "evidence_id": "ev_001",
                "scene_id": "scene_001",
                "kind": "quote",
                "speaker": "client" if "клиент" in quote_a.lower() else "unknown",
                "text": quote_a,
                "is_exact_transcript_quote": True,
                "source_span": None,
                "grounding_note": None,
            }
        )
    if quote_b:
        evidence_ledger.append(
            {
                "evidence_id": "ev_002",
                "scene_id": "scene_001",
                "kind": "quote",
                "speaker": "manager" if "менеджер" in quote_b.lower() else "unknown",
                "text": quote_b,
                "is_exact_transcript_quote": True,
                "source_span": None,
                "grounding_note": None,
            }
        )
    evidence_ids = [str(item["evidence_id"]) for item in evidence_ledger]
    return {
        "pass": "LLM-2A",
        "artifact_version": "llm2_pass_2a_v1",
        "call_id": call_id,
        "analysis_eligibility": "eligible"
        if transcript and admitted is not False
        else "insufficient",
        "eligibility_reason": (
            _first_text(admission_gate.get("reason_code"), "simulated_sales_relevant_exchange")
            if transcript
            else "simulated_empty_transcript"
        ),
        "scenes": [
            {
                "scene_id": "scene_001",
                "order": 1,
                "stage_hint": "completion_next_step",
                "what_happened": "Клиентский запрос остался открытым, менеджеру нужно закрепить следующий шаг.",
                "manager_actions": ["Менеджер согласился отправить информацию."],
                "client_reactions": ["Клиент попросил материалы или продолжение контакта."],
                "observed_commitments": ["Менеджер вернется с информацией."],
                "deadlines_or_timing": [],
                "objections": [],
                "service_or_refusal_signals": [],
                "evidence_ids": evidence_ids,
            }
        ] if evidence_ids else [],
        "evidence_ledger": evidence_ledger,
        "business_outcome_signal": {
            "status": "open" if transcript else "insufficient",
            "confidence": "medium" if transcript else "low",
            "evidence_ids": evidence_ids[:1],
            "reason": "Симулированный открытый исход по grounded-фрагменту.",
        },
        "fail_closed": {
            "insufficient_transcript": not bool(transcript),
            "speaker_roles_uncertain": True,
            "reject_reasons": [] if transcript else ["empty_transcript"],
        },
        "llm2_admission_gate": admission_gate,
    }


def _simulate_llm2b(context: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic LLM-2B scoring/gaps artifact."""
    previous = _as_dict(context.get("previous_artifacts"))
    llm2a = _as_dict(previous.get("llm2a") or context.get("llm2a_artifact"))
    call_id = _first_text(llm2a.get("call_id"), context.get("call_id")) or "simulated_call"
    evidence_ids = [
        str(item.get("evidence_id"))
        for item in _as_list(llm2a.get("evidence_ledger"))
        if item.get("evidence_id")
    ]
    if not evidence_ids:
        return {
            "pass": "LLM-2B",
            "artifact_version": "llm2_pass_2b_v1",
            "call_id": call_id,
            "criteria_results": [],
            "stage_scores": [],
            "strength_claims": [],
            "gap_claims": [],
            "fail_closed": {"reject_reasons": ["no_evidence"]},
        }
    return {
        "pass": "LLM-2B",
        "artifact_version": "llm2_pass_2b_v1",
        "call_id": call_id,
        "criteria_results": [
            {
                "criterion_code": "cn_owner_and_deadline",
                "criterion_name": "Определил кто делает и когда",
                "stage_code": "completion_next_step",
                "applicable": True,
                "score": 0,
                "max_score": 2,
                "comment": "Симулятор видит открытый следующий шаг без надежно закрепленного срока.",
                "scene_ids": ["scene_001"],
                "evidence_ids": evidence_ids[:2],
                "missing_evidence_reason": None,
            }
        ],
        "stage_scores": [],
        "strength_claims": [],
        "gap_claims": [
            {
                "claim_id": "claim_001",
                "claim_type": "manager_gap",
                "stage_code": "completion_next_step",
                "claim": "Следующий контакт не закреплен достаточно конкретно.",
                "claim_scope": "scene",
                "scene_ids": ["scene_001"],
                "evidence_ids": evidence_ids[:2],
                "expected_behavior": "Назвать владельца и срок следующего шага.",
                "observed_behavior": "Менеджер оставил продолжение менее конкретным.",
                "confidence": "medium",
            }
        ],
        "fail_closed": {
            "claims_without_scene_rejected": 0,
            "claims_without_evidence_rejected": 0,
            "reject_reasons": [],
        },
    }


def _simulate_llm2c(context: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic LLM-2C proof artifact."""
    previous = _as_dict(context.get("previous_artifacts"))
    llm2b = _as_dict(previous.get("llm2b") or context.get("llm2b_artifact"))
    call_id = _first_text(llm2b.get("call_id"), context.get("call_id")) or "simulated_call"
    claims = _as_list(llm2b.get("gap_claims")) + _as_list(llm2b.get("strength_claims"))
    proof_cards = []
    for index, claim in enumerate(claims, start=1):
        claim = _as_dict(claim)
        evidence_ids = [item for item in _as_list(claim.get("evidence_ids")) if item]
        proof_status = "proven" if len(evidence_ids) >= 2 else "insufficient"
        proof_cards.append(
            {
                "proof_id": f"proof_{index:03d}",
                "claim_id": claim.get("claim_id"),
                "call_id": call_id,
                "stage_code": claim.get("stage_code") or "completion_next_step",
                "claim": claim.get("claim") or "Симулированный claim.",
                "claim_scope": claim.get("claim_scope") or "scene",
                "claim_type": claim.get("claim_type") or "manager_gap",
                "scene_id": (_as_list(claim.get("scene_ids")) or ["scene_001"])[0],
                "supporting_evidence_ids": evidence_ids[:2],
                "counter_evidence_ids": [],
                "evidence_quote": None,
                "proof_type": "sequence_inference",
                "proof_status": proof_status,
                "gap_proven": proof_status == "proven",
                "claim_too_broad": False,
                "needs_softening": False,
                "softened_claim": None,
                "proof_explanation": "Симулятор связывает claim с двумя grounded evidence ids.",
                "reject_reason": None if proof_status == "proven" else "no_evidence",
            }
        )
    return {
        "pass": "LLM-2C",
        "artifact_version": "llm2_pass_2c_v1",
        "call_id": call_id,
        "proof_cards": proof_cards,
        "claim_audit": {
            "input_claim_count": len(claims),
            "proven_count": sum(1 for item in proof_cards if item["proof_status"] == "proven"),
            "softened_count": 0,
            "rejected_count": 0,
            "insufficient_count": sum(1 for item in proof_cards if item["proof_status"] == "insufficient"),
        },
        "fail_closed": {"unmatched_claim_ids": [], "reject_reasons": []},
    }


def _simulate_llm2d(context: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic LLM-2D recommendation/evidence-pack artifact."""
    previous = _as_dict(context.get("previous_artifacts"))
    llm2a = _as_dict(previous.get("llm2a") or context.get("llm2a_artifact"))
    llm2b = _as_dict(previous.get("llm2b") or context.get("llm2b_artifact"))
    llm2c = _as_dict(previous.get("llm2c") or context.get("llm2c_artifact"))
    call_id = _first_text(llm2a.get("call_id"), llm2b.get("call_id"), llm2c.get("call_id")) or "simulated_call"
    admission_gate = _as_dict(
        context.get("llm2_admission_gate") or llm2a.get("llm2_admission_gate")
    )
    accepted_cards = [
        _as_dict(card)
        for card in _as_list(llm2c.get("proof_cards"))
        if str(_as_dict(card).get("proof_status") or "").lower() in {"proven", "softened"}
    ]
    recommendations = [
        {
            "recommendation_id": f"rec_{index:03d}",
            "proof_id": card.get("proof_id"),
            "problem": card.get("claim"),
            "why_it_matters": "Конкретный следующий шаг снижает риск потери контакта.",
            "better_phrase": "Давайте зафиксируем: я отправлю информацию сегодня и вернусь завтра до обеда.",
            "next_action": "Закрепить владельца и срок следующего контакта.",
            "stage_code": card.get("stage_code") or "completion_next_step",
        }
        for index, card in enumerate(accepted_cards, start=1)
        if card.get("claim_type") == "manager_gap"
    ]
    return {
        "pass": "LLM-2D",
        "artifact_version": "llm2_pass_2d_v1",
        "call_id": call_id,
        "recommendations": recommendations,
        "universal_evidence_pack": {
            "proof_cards": _as_list(llm2c.get("proof_cards")),
            "scenes": _as_list(llm2a.get("scenes")),
            "evidence_ledger": _as_list(llm2a.get("evidence_ledger")),
            "business_outcome_signal": _as_dict(llm2a.get("business_outcome_signal")),
            "quote_bank": [
                {
                    "evidence_id": item.get("evidence_id"),
                    "speaker": item.get("speaker") or "unknown",
                    "quote": item.get("text"),
                }
                for item in _as_list(llm2a.get("evidence_ledger"))
                if item.get("text")
            ],
        },
        "final_normalized_analysis": {
            "classification": {
                "call_type": "sales_primary",
                "scenario_type": "repeat_contact",
                "channel_context": "phone_call",
                "analysis_eligibility": "eligible"
                if admission_gate.get("admitted") is not False
                else "not_eligible",
                "eligibility_reason": _first_text(
                    admission_gate.get("reason_code"),
                    llm2a.get("eligibility_reason"),
                    "simulated_layered_sales_relevant_exchange",
                ),
                "analysis_confidence": "medium",
            },
            "summary": {"short_summary": "Симулированный layered-анализ открытого контакта."},
            "criteria_results": _as_list(llm2b.get("criteria_results")),
            "strengths": [],
            "gaps": _as_list(llm2b.get("gap_claims")),
            "recommendations": recommendations,
            "agreements": [],
            "follow_up": {},
            "evidence_fragments": [],
            "report_evidence_version": "v1",
            "report_evidence": {},
        },
        "compatibility_notes": {
            "mvp1_scores_detail_compatible": True,
            "legacy_report_fields_are_derived": True,
            "report_block_selection_excluded": True,
        },
        "fail_closed": {
            "recommendations_without_proof_rejected": 0,
            "proof_cards_not_used": [],
            "reject_reasons": [],
        },
    }


def _build_simulated_score_by_stage(
    checklist: dict[str, Any],
    transcript: str,
) -> list[dict[str, Any]]:
    stages = [_as_dict(item) for item in checklist.get("stages") or [] if isinstance(item, dict)]
    wanted_codes = {"contact_start", "qualification_primary", "completion_next_step"}
    selected = [stage for stage in stages if stage.get("stage_code") in wanted_codes]
    rows: list[dict[str, Any]] = []
    evidence = _evidence_text(transcript)
    for stage in selected:
        criteria_rows = []
        for index, criterion in enumerate(stage.get("criteria") or []):
            criterion = _as_dict(criterion)
            score = 1 if index % 2 else 2
            if criterion.get("criterion_code") == "cn_owner_and_deadline":
                score = 0
            criteria_rows.append(
                {
                    "criterion_code": criterion.get("criterion_code"),
                    "criterion_name": criterion.get("criterion_name"),
                    "score": score,
                    "max_score": 2,
                    "comment": (
                        "Симулированная оценка по текущей инструкции; используется для тестирования механизма."
                    ),
                    "evidence": evidence,
                }
            )
        rows.append(
            {
                "stage_code": stage.get("stage_code"),
                "stage_name": stage.get("stage_name"),
                "stage_score": sum(int(item["score"]) for item in criteria_rows),
                "max_stage_score": sum(int(item["max_score"]) for item in criteria_rows),
                "criteria_results": criteria_rows,
            }
        )
    return rows


def _build_simulated_report_evidence(
    interaction: dict[str, Any],
    transcript: str,
) -> dict[str, Any]:
    call_id = str(interaction.get("id") or "")
    quote = _evidence_text(transcript)
    return {
        "business_outcome": {
            "status": "open",
            "status_reason": "Симулированный открытый исход для проверки report layer.",
            "evidence": quote,
            "confidence": "medium",
        },
        "block_candidates": {
            "situation_day": {
                "fit": True,
                "score": 0.72,
                "stage_code": "completion_next_step",
                "role": "manager_gap",
                "title_mode": "behavior_specific",
                "thesis": "Менеджеру нужно конкретнее закреплять следующий шаг.",
                "what_happened": "Разговор остался открытым, но следующий шаг сформулирован недостаточно твердо.",
                "why_it_matters": "Без срока и владельца сделка может зависнуть.",
                "proof_type": "context_support",
                "proof_explanation": "Симулированный кандидат использует фрагмент транскрипта как проверяемую опору.",
                "quote_role": "supports_context",
                "supporting_quote": quote,
                "counter_evidence": None,
                "evidence_target": "next_step",
                "gap_proven": True,
                "coaching_moment": {
                    "summary": "Следующий шаг нужно закрепить конкретнее.",
                    "missing_action": "Назвать владельца и срок.",
                    "why_it_matters": "Это снижает риск потери контакта.",
                    "supporting_quote": quote,
                    "evidence_type": "inferred_from_dialogue",
                    "confidence": "medium",
                    "gap_claim": "В выбранной сцене следующий шаг звучит недостаточно конкретно.",
                    "proof_type": "context_support",
                    "proof_explanation": "Фрагмент поддерживает контекст открытого следующего шага.",
                    "quote_role": "supports_context",
                    "counter_evidence": None,
                },
            },
            "call_list_context": {
                "fit": True,
                "score": 0.7,
                "stage_code": "completion_next_step",
                "manager_visible_summary": "Открытый контакт: клиентский интерес нужно закрепить конкретным следующим шагом.",
                "call_id": call_id,
                "supporting_quote": quote,
            },
        },
        "manager_coaching_moments": [
            {
                "summary": "Закрепить следующий шаг с владельцем и сроком.",
                "stage_code": "completion_next_step",
                "supporting_quote": quote,
                "evidence_type": "inferred_from_dialogue",
                "confidence": "medium",
            }
        ],
    }


def _simulate_llm3_daily_situation(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = [_as_dict(item) for item in payload.get("candidates") or []]
    selected = candidates[0] if candidates else {}
    call_id = _first_text(selected.get("call_id"), selected.get("interaction_id")) or "simulated_call"
    quote = _first_quote(selected) or "Фрагмент звонка недоступен в симулированном payload."
    title = _first_text(
        selected.get("situation_title"),
        selected.get("moment_summary"),
        selected.get("manager_error"),
        "Ситуация дня",
    )
    manager_error = _first_text(
        selected.get("manager_error"),
        selected.get("moment_summary"),
        "Ошибка менеджера не передана в симулированном payload.",
    )
    what_happened = _first_text(
        selected.get("what_happened"),
        selected.get("moment_summary"),
        f"Сцена подтверждается фрагментом: {quote}",
    )
    next_time_action = _first_text(
        selected.get("next_time_action"),
        "Следующий раз отработать именно этот фокус этапа на основе подтвержденной сцены.",
    )
    scripts = [str(item).strip() for item in selected.get("scripts") or [] if str(item).strip()]
    if len(scripts) < 2:
        scripts.extend(
            [
                next_time_action,
                "Давайте уточню этот момент сейчас, чтобы решение опиралось на вашу реальную ситуацию.",
            ]
        )
    return {
        "status": "verified",
        "selected_call_id": call_id,
        "situation_title": title,
        "moment_summary": _first_text(selected.get("moment_summary"), title),
        "what_happened": what_happened,
        "call_context_summary": _first_text(selected.get("call_context_summary"), selected.get("moment_summary")),
        "manager_error": manager_error,
        "stage_code": _first_text(selected.get("stage_code")),
        "proof_type": _first_text(selected.get("proof_type"), "sequence_inference"),
        "evidence_scene": _first_text(selected.get("evidence_scene"), quote),
        "dialogue_turns": selected.get("dialogue_turns") or [],
        "evidence_quotes": selected.get("evidence_quotes") or ([quote] if quote else []),
        "supporting_quote": quote,
        "why_it_matters": _first_text(
            selected.get("why_it_matters"),
            "Если не разобрать этот фокус, менеджер повторит ту же ошибку в похожем разговоре.",
        ),
        "next_time_action": next_time_action,
        "scripts": scripts[:2],
        "rejected_candidates": [],
        "selection_reason": "llm3_simulation_preserved_focus_candidate",
        "source_fact_ids": selected.get("source_fact_ids") or [call_id],
    }


def _simulate_llm3_call_breakdown(payload: dict[str, Any]) -> dict[str, Any]:
    selected_call = _as_dict(payload.get("selected_call"))
    call_id = _first_text(selected_call.get("call_id")) or "simulated_call"
    scenes = [_as_dict(item) for item in payload.get("transcript_scenes") or []]
    first_scene = scenes[0] if scenes else {}
    turns = [_as_dict(item) for item in first_scene.get("turns") or []]
    fragment_parts = []
    for turn in turns[:4]:
        text = _first_text(turn.get("text"))
        if not text:
            continue
        speaker = _first_text(turn.get("speaker"), "unknown")
        fragment_parts.append(f"{speaker}: {text}")
    quote = (
        " / ".join(fragment_parts)
        or _first_quote(first_scene)
        or _first_quote(payload)
        or "Короткий подтверждающий фрагмент звонка."
    )
    proof_cards = _as_list(_as_dict(payload.get("llm2_facts")).get("proof_cards"))
    proof_card = _as_dict(proof_cards[0]) if proof_cards else {}
    proof_id = _first_text(proof_card.get("proof_id"))
    evidence_refs = _as_list(first_scene.get("evidence_refs")) or [
        {"proof_id": proof_id, "quote": quote, "call_id": call_id}
    ]
    moment = {
        "moment": "Следующий шаг остался недостаточно конкретным",
        "what": "Менеджер поддержал разговор, но мог сильнее закрепить следующий шаг.",
        "moment_summary": "Финал разговора остался менее управляемым, чем мог быть.",
        "supporting_quote": quote,
        "better": "Назвать владельца, срок и формат следующего касания.",
        "proof_id": proof_id,
        "proof_type": _first_text(proof_card.get("proof_type"), "sequence_inference"),
        "proof_explanation": "Симулятор использует только bounded scene/proof-card material из payload.",
        "evidence_refs": evidence_refs,
        "title": "Следующий шаг остался недостаточно конкретным",
        "what_happened": "Менеджер поддержал разговор, но мог сильнее закрепить следующий шаг.",
        "why_it_matters": "Такой финал снижает управляемость дальнейшего контакта.",
        "better_action": "Назвать владельца, срок и формат следующего касания.",
        "dialogue_evidence": [{"speaker": "unknown", "text": quote}],
    }
    return {
        "status": "verified",
        "call_id": call_id,
        "call_story": "Симулированный разбор показывает один проверяемый поворот разговора.",
        "what_manager_missed": "Менеджер мог точнее закрепить следующий шаг по уже выбранной ситуации.",
        "better_path": "Повторить grounded-фрагмент и договориться о конкретном следующем действии.",
        "moments": [moment],
        "rows": [
            [
                "Следующий шаг",
                "Что было не так: Финал разговора можно сделать более управляемым.",
                f"Фрагмент: {quote}",
                "Сказать: закрепить действие, владельца и срок.",
            ]
        ],
        "key_turning_points": [moment],
    }


def _simulate_llm3_voice_of_customer(payload: dict[str, Any]) -> dict[str, Any]:
    signals = [_as_dict(item) for item in payload.get("signals") or [] if isinstance(item, dict)]
    if not signals:
        return {
            "status": "insufficient",
            "customer_scenes": [],
            "situations": [],
            "rows": [],
            "source_note": "report_evidence.voice_of_customer_composer.v2",
            "selection_diagnostics": {
                "composer_version": "voice_of_customer_composer_v2",
                "selection_mode": "llm3_voice_of_customer_simulation",
                "reason": "no_customer_signals",
            },
        }
    signal = signals[0]
    quote = _first_text(signal.get("quote")) or _first_quote(payload) or "Клиентский сигнал требует уточнения."
    quote_context = _first_text(signal.get("quote_context")) or quote
    meaning = (
        _first_text(signal.get("interpretation"))
        or "Клиентский сигнал требует уточнения и понятного следующего шага."
    )
    action = (
        _first_text(signal.get("manager_action"))
        or "Что сделать: уточнить потребность клиента и договориться о следующем контакте."
    )
    scene = {
        "signal_id": signal.get("signal_id"),
        "call_id": signal.get("call_id"),
        "client_call_reference": signal.get("client_call_reference") or "Клиент",
        "scene_summary": quote_context,
        "quote": quote,
        "quote_context": quote_context,
        "dialogue_evidence": [{"speaker": "client", "text": quote}],
        "customer_meaning": meaning,
        "manager_response": action,
        "why_action_follows": "Действие следует из выбранного customer-signal proof material.",
        "customer_signal": signal.get("customer_signal"),
        "source": signal.get("source") or "voice_of_customer_composer",
        "evidence_refs": list(signal.get("evidence_refs") or []),
        "proof_refs": list(signal.get("proof_refs") or signal.get("evidence_refs") or []),
    }
    situation = {
        "signal_id": scene["signal_id"],
        "call_id": scene["call_id"],
        "client_call_reference": scene["client_call_reference"],
        "quote": quote,
        "quote_context": quote_context,
        "context": f"{meaning} {action}".strip(),
        "interpretation": f"{meaning} {action}".strip(),
        "manager_action": action,
        "customer_signal": scene["customer_signal"],
        "source": scene["source"],
        "evidence_refs": list(scene["evidence_refs"]),
        "proof_refs": list(scene["proof_refs"]),
    }
    return {
        "status": "verified",
        "is_placeholder": False,
        "customer_scenes": [scene],
        "situations": [situation],
        "rows": [[scene["client_call_reference"], quote_context, situation["interpretation"]]],
        "source_note": "report_evidence.voice_of_customer_composer.v2",
        "selection_diagnostics": {
            "composer_version": "voice_of_customer_composer_v2",
            "selection_mode": "llm3_voice_of_customer_simulation",
        },
    }


def _simulate_llm3_call_tomorrow(payload: dict[str, Any]) -> dict[str, Any]:
    contacts = []
    for item in payload.get("contacts") or []:
        source = _as_dict(item)
        contacts.append(
            {
                "contact_key": source.get("contact_key"),
                "reason": _first_text(source.get("reason")) or "Открытый контакт требует следующего касания.",
                "next_step": _first_text(source.get("next_step")) or "Связаться и уточнить актуальность.",
                "opening_script": (
                    _first_text(source.get("opening_script"))
                    or "Здравствуйте. Возвращаюсь по нашему разговору, чтобы зафиксировать следующий шаг."
                ),
                "why_this_wording": "Формулировка сохраняет нейтральный тон и закрепляет действие.",
            }
        )
    return {"status": "verified", "contacts": contacts}


def _write_artifacts(
    *,
    layer: str,
    request_kind: str,
    subject_key: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
) -> None:
    base = Path(_artifact_dir())
    run_id = _safe_token(_run_id())
    run_dir = base / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        index = next(_ARTIFACT_COUNTER)
        prefix = f"{index:04d}_{_safe_token(layer)}_{_safe_token(request_kind)}_{_safe_token(subject_key)}"
        (run_dir / f"{prefix}_input.json").write_text(
            json.dumps(input_payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (run_dir / f"{prefix}_output.json").write_text(
            json.dumps(output_payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        return


def _simulated_routing_metadata(
    *,
    layer: str,
    request_kind: str,
    subject_key: str,
) -> dict[str, Any]:
    return {
        "layer": layer,
        "policy": "manual_force",
        "requested_policy": "manual_force",
        "forced_override": True,
        "force_reason": "ai_llm_simulation_enabled",
        "subject_key": subject_key,
        "configured_pool_size": 1,
        "selected_provider": "subagent_simulator",
        "selected_account_alias": "local_llm_simulation",
        "selected_api_key_env": None,
        "selected_model": "subagent_simulator",
        "selected_api_base": None,
        "selected_endpoint": None,
        "selected_timeout_sec": None,
        "selected_max_retries_for_this_provider": 0,
        "selected_execution_mode": "simulation",
        "selected_supports_api_base": False,
        "selected_supports_endpoint": False,
        "selected_supports_model": False,
        "selected_requires_openai_compatible_api": False,
        "fallback_used": False,
        "provider_failure": False,
        "executed": True,
        "execution_status": "simulated",
        "skip_reason": None,
        "request_kind": request_kind,
        "executed_endpoint_path": "local_subagent_simulation",
        "provider_request_id": f"sim_{_safe_token(subject_key)}_{next(_ARTIFACT_COUNTER)}",
        "notes": "Temporary LLM subagent simulation completed.",
        "artifact_dir": str(
            Path(_artifact_dir())
            / _safe_token(_run_id())
        ),
        "simulation_seed": _seed() or None,
        "usage": None,
        "attempted_count": 1,
        "attempted": [
            {
                "layer": layer,
                "provider": "subagent_simulator",
                "account_alias": "local_llm_simulation",
                "model": "subagent_simulator",
                "status": "success",
                "attempt_index": 1,
            }
        ],
    }


def _subagent_runner_command() -> list[str]:
    raw = (
        os.getenv("AI_LLM_SUBAGENT_RUNNER_CMD")
        or os.getenv("AI_LLM_AGENT_RUNNER_CMD")
        or ""
    ).strip()
    if not raw:
        return []
    return shlex.split(raw)


def _subagent_runner_timeout_sec() -> int:
    raw = (
        os.getenv("AI_LLM_SUBAGENT_TIMEOUT_SEC")
        or os.getenv("AI_LLM_SUBAGENT_RUNNER_TIMEOUT_SEC")
        or ""
    ).strip()
    default = int(getattr(settings, "ai_llm_subagent_timeout_sec", 300) or 300)
    try:
        return max(1, int(raw)) if raw else default
    except ValueError:
        return default


def _subagent_content_from_result(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, str):
        return content
    output = result.get("output")
    if isinstance(output, str):
        return output
    response = result.get("response")
    if isinstance(response, str):
        return response
    return json.dumps(result, ensure_ascii=False)


def _extract_openai_message_content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    return str(content or "")


def _extract_openai_usage_metadata(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _summary_sentence(transcript: str) -> str:
    if not transcript:
        return "Транскрипт отсутствует; симулятор не видит содержательного разговора."
    compact = re.sub(r"\s+", " ", transcript).strip()
    if len(compact) > 180:
        compact = compact[:177].rstrip() + "..."
    return f"Симулированное резюме звонка: {compact}"


def _artifact_dir() -> str:
    return os.getenv("AI_LLM_SIMULATION_ARTIFACT_DIR") or settings.ai_llm_simulation_artifact_dir


def _run_id() -> str:
    return os.getenv("AI_LLM_SIMULATION_RUN_ID") or settings.ai_llm_simulation_run_id or "default"


def _seed() -> str:
    return os.getenv("AI_LLM_SIMULATION_SEED") or settings.ai_llm_simulation_seed

def _subagent_run_id() -> str:
    return (
        os.getenv("AI_LLM_SUBAGENT_RUN_ID")
        or os.getenv("AI_LLM_SIMULATION_RUN_ID")
        or getattr(settings, "ai_llm_subagent_run_id", "")
        or getattr(settings, "ai_llm_simulation_run_id", "")
        or "default"
    )


def _subagent_artifact_dir() -> str:
    return (
        os.getenv("AI_LLM_SUBAGENT_ARTIFACT_DIR")
        or os.getenv("AI_LLM_SIMULATION_ARTIFACT_DIR")
        or getattr(settings, "ai_llm_subagent_artifact_dir", "")
        or getattr(settings, "ai_llm_simulation_artifact_dir", "")
        or "/tmp/asa_llm_subagent_runs"
    )


def _subagent_command() -> str:
    return os.getenv("AI_LLM_SUBAGENT_COMMAND") or getattr(settings, "ai_llm_subagent_command", "")


def _subagent_timeout_sec() -> int:
    raw = os.getenv("AI_LLM_SUBAGENT_TIMEOUT_SEC")
    default = int(getattr(settings, "ai_llm_subagent_timeout_sec", 300) or 300)
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            return default
    return default


def _subagent_artifact_paths(
    *,
    layer: str,
    request_kind: str,
    subject_key: str,
) -> tuple[Path, Path]:
    run_dir = Path(_subagent_artifact_dir()) / _safe_token(_subagent_run_id())
    run_dir.mkdir(parents=True, exist_ok=True)
    index = next(_ARTIFACT_COUNTER)
    prefix = f"{index:04d}_{_safe_token(layer)}_{_safe_token(request_kind)}_{_safe_token(subject_key)}"
    return run_dir / f"{prefix}_input.json", run_dir / f"{prefix}_output.json"


def count_subagent_artifacts(artifact_dir: str | Path | None) -> dict[str, Any]:
    """Count runtime subagent artifacts, including indexed ``*_output.json`` files."""
    if not artifact_dir:
        return {"artifact_dir": None, "input_files": 0, "output_files": 0}
    base = Path(artifact_dir)
    if not base.exists():
        return {"artifact_dir": str(base), "input_files": 0, "output_files": 0}
    input_files = sorted(base.rglob("*_input.json"))
    output_files = sorted(base.rglob("*_output.json"))
    legacy_output = base / "output.json"
    if legacy_output.exists() and legacy_output not in output_files:
        output_files.append(legacy_output)
    return {
        "artifact_dir": str(base),
        "input_files": len(input_files),
        "output_files": len(output_files),
    }


def _write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _messages(prompt: str | None, payload: dict[str, Any]) -> list[dict[str, str]]:
    messages = []
    if prompt:
        messages.append({"role": "system", "content": prompt})
    messages.append({"role": "user", "content": json.dumps(payload, ensure_ascii=False)})
    return messages


def _run_subagent_runner(
    *,
    input_payload: dict[str, Any],
    input_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    generic_command = _subagent_runner_command()
    if generic_command:
        env = {
            **os.environ,
            "AI_LLM_SUBAGENT_INPUT_PATH": str(input_path),
            "AI_LLM_SUBAGENT_OUTPUT_PATH": str(output_path),
            "AI_LLM_SUBAGENT_REQUEST_KIND": str(input_payload.get("request_kind") or ""),
            "AI_LLM_SUBAGENT_SUBJECT_KEY": str(input_payload.get("subject_key") or ""),
        }
        completed = subprocess.run(
            generic_command,
            input=json.dumps(input_payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=_subagent_runner_timeout_sec(),
            env=env,
            cwd=os.getenv("AI_LLM_SUBAGENT_RUNNER_CWD") or None,
            check=False,
        )
        raw = ""
        if output_path.exists():
            raw = output_path.read_text(encoding="utf-8").strip()
        if not raw:
            raw = (completed.stdout or "").strip()
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            detail = stderr or raw or f"exit_code={completed.returncode}"
            raise RuntimeError(f"subagent runner failed: {detail[:1000]}")
        return _parse_subagent_json(raw)

    executable = shlex.split(_subagent_command())
    if not executable:
        raise RuntimeError("AI_LLM_SUBAGENT_RUNNER_CMD or AI_LLM_SUBAGENT_COMMAND is required")
    prompt = _build_subagent_prompt(input_payload=input_payload, input_path=input_path)
    args = [
        *executable,
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "-C",
        str(Path.cwd()),
        "--skip-git-repo-check",
        "-o",
        str(output_path),
        "-",
    ]
    completed = subprocess.run(
        args,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=_subagent_timeout_sec(),
        check=False,
    )
    raw = ""
    if output_path.exists():
        raw = output_path.read_text(encoding="utf-8").strip()
    if not raw:
        raw = (completed.stdout or "").strip()
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise RuntimeError(
            f"subagent command failed with exit code {completed.returncode}: {stderr[:1000]}"
        )
    return _parse_subagent_json(raw)


def _build_subagent_prompt(
    *,
    input_payload: dict[str, Any],
    input_path: Path,
) -> str:
    layer = str(input_payload.get("layer") or "").upper()
    request_kind = str(input_payload.get("request_kind") or "")
    return (
        "You are a runtime subagent replacing an LLM node in AI Sales Analyzer.\n"
        "Follow the same instructions and contracts that are included in the input.\n"
        "Return only one valid JSON object. Do not use markdown, comments, or explanations.\n"
        "Do not change files. Do not call external services. Use only the provided input.\n"
        "If evidence is insufficient, still return the required contract shape with guarded, "
        "grounded fields rather than prose outside JSON.\n\n"
        f"Layer: {layer}\n"
        f"Request kind: {request_kind}\n"
        f"Input artifact path: {input_path}\n\n"
        "Input payload JSON:\n"
        f"{json.dumps(input_payload, ensure_ascii=False, indent=2, default=str)}"
    )


def _parse_subagent_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise RuntimeError("subagent returned empty output")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise RuntimeError("subagent output JSON is not an object")
    return parsed


def _subagent_routing_metadata(
    *,
    layer: str,
    request_kind: str,
    subject_key: str,
    input_path: Path | None,
    output_path: Path | None,
    execution_status: str,
    error: str | None = None,
) -> dict[str, Any]:
    run_dir = Path(_subagent_artifact_dir()) / _safe_token(_subagent_run_id())
    artifact_counts = count_subagent_artifacts(run_dir)
    return {
        "layer": layer,
        "policy": "manual_force",
        "requested_policy": "manual_force",
        "forced_override": True,
        "force_reason": "ai_llm_execution_mode=subagent_runtime",
        "provider": "subagent_runtime",
        "simulation": False,
        "subject_key": subject_key,
        "configured_pool_size": 1,
        "selected_provider": "codex_subagent",
        "selected_account_alias": "codex_subagent_runtime",
        "selected_api_key_env": None,
        "selected_model": "codex_exec",
        "selected_api_base": None,
        "selected_endpoint": None,
        "selected_timeout_sec": _subagent_timeout_sec(),
        "selected_max_retries_for_this_provider": 0,
        "selected_execution_mode": "subagent_runtime",
        "selected_supports_api_base": False,
        "selected_supports_endpoint": False,
        "selected_supports_model": False,
        "selected_requires_openai_compatible_api": False,
        "fallback_used": False,
        "provider_failure": bool(error),
        "executed": execution_status == "completed",
        "execution_status": "subagent_executed" if execution_status == "completed" else "failed",
        "skip_reason": None,
        "request_kind": request_kind,
        "executed_endpoint_path": "codex_subagent_runtime",
        "provider_request_id": f"subagent_{_safe_token(subject_key)}_{next(_ARTIFACT_COUNTER)}",
        "notes": "External Codex subagent runtime completed." if not error else error,
        "artifact_dir": str(run_dir),
        "artifact_counts": artifact_counts,
        "input_artifact": str(input_path) if input_path else None,
        "output_artifact": str(output_path) if output_path else None,
        "usage": None,
        "attempted_count": 1,
        "attempted": [
            {
                "layer": layer,
                "provider": "codex_subagent",
                "account_alias": "codex_subagent_runtime",
                "model": "codex_exec",
                "status": "success" if not error else "failed",
                "attempt_index": 1,
            }
        ],
    }


def _evidence_text(transcript: str) -> str:
    compact = re.sub(r"\s+", " ", transcript).strip()
    if not compact:
        return "Симулированный фрагмент: транскрипт пустой."
    return compact[:220].rstrip()


def _first_quote(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in (
            "supporting_quote",
            "quote",
            "evidence_scene",
            "scene",
            "transcript",
            "text",
            "manager_visible_summary",
        ):
            found = _first_text(value.get(key))
            if found:
                return found
        for item in value.values():
            found = _first_quote(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _first_quote(item)
            if found:
                return found
    return None


def _two_evidence_quotes(transcript: str) -> tuple[str | None, str | None]:
    compact = re.sub(r"\s+", " ", transcript).strip()
    if not compact:
        return None, None
    chunks = [
        chunk.strip()
        for chunk in re.split(r"(?<=[.!?])\s+", compact)
        if chunk.strip()
    ]
    if len(chunks) >= 2:
        return chunks[0], chunks[1]
    midpoint = max(1, len(compact) // 2)
    split_at = compact.find(" ", midpoint)
    if split_at <= 0:
        return compact, compact
    return compact[:split_at].strip(), compact[split_at:].strip()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text(value)
        if text:
            return text
    return None


def _safe_token(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return text[:80] or "unknown"
