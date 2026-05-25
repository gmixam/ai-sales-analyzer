"""Temporary LLM simulation executor for report-quality testing.

This module replaces only the runtime model call. Validators, normalizers,
persistence, report selection, and renderers must continue to run unchanged.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

from app.core_shared.config.settings import settings

_ARTIFACT_COUNTER = count(1)


def simulation_enabled() -> bool:
    """Return whether temporary LLM simulation mode is active."""
    raw = os.getenv("AI_LLM_SIMULATION_ENABLED")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(settings.ai_llm_simulation_enabled)


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
    """Compatibility wrapper for composer-local simulation adapters."""
    return request_simulated_llm3_json(
        request_kind=str(kwargs.get("request_kind") or kwargs.get("node") or ""),
        payload=_as_dict(kwargs.get("payload") or kwargs.get("input_payload")),
        prompt=kwargs.get("prompt") or kwargs.get("system_prompt"),
        subject_key=str(kwargs.get("subject_key") or "llm3"),
    )


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
    return {
        "status": "verified",
        "selected_call_id": call_id,
        "situation_title": "Закрепить следующий шаг конкретнее",
        "moment_summary": "Менеджер оставил контакт открытым, но следующий шаг требует большей конкретики.",
        "what_happened": f"В выбранном звонке видно, что разговор можно было завершить более управляемо. Опора: {quote}",
        "manager_error": "Следующий шаг не был закреплен достаточно конкретно по владельцу и сроку.",
        "evidence_scene": quote,
        "supporting_quote": quote,
        "why_it_matters": "Без конкретного срока клиенту проще отложить решение.",
        "next_time_action": "В конце разговора назвать действие, владельца и точное время следующего контакта.",
        "scripts": [
            "Давайте зафиксируем следующий шаг: я отправлю информацию сегодня, а завтра до обеда вернусь к вам.",
            "Чтобы не потерять договоренность, согласуем сразу: кто смотрит материалы и когда я возвращаюсь?",
        ],
        "rejected_candidates": [],
        "selection_reason": "Симулятор выбрал первый пригодный кандидат для проверки report pipeline.",
        "source_fact_ids": [call_id],
    }


def _simulate_llm3_call_breakdown(payload: dict[str, Any]) -> dict[str, Any]:
    selected_call = _as_dict(payload.get("selected_call"))
    call_id = _first_text(selected_call.get("call_id")) or "simulated_call"
    quote = _first_quote(selected_call) or _first_quote(payload) or "Короткий подтверждающий фрагмент звонка."
    moment = {
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
        "moments": [moment],
        "rows": [
            [
                "Следующий шаг",
                quote,
                "Финал разговора можно сделать более управляемым.",
                "Закрепить действие, владельца и срок.",
            ]
        ],
        "key_turning_points": [moment],
    }


def _simulate_llm3_voice_of_customer(payload: dict[str, Any]) -> dict[str, Any]:
    signals = [_as_dict(item) for item in payload.get("signals") or [] if isinstance(item, dict)]
    quote = _first_quote(payload) or "Клиентский сигнал требует уточнения."
    return {
        "status": "verified",
        "customer_scenes": [
            {
                "scene": quote,
                "what_customer_means": "Клиент оставляет вопрос открытым и ждет понятного следующего шага.",
                "how_to_work_with_it": "Уточнить актуальность, критерий решения и договориться о следующем контакте.",
                "dialogue_evidence": [{"speaker": "client", "text": quote}],
                "source_signal_id": _first_text(signals[0].get("id")) if signals else None,
            }
        ],
        "signals": signals,
        "summary": "Клиентский сигнал лучше обрабатывать через уточнение и конкретный следующий шаг.",
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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
