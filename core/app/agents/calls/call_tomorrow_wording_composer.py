"""LLM3 wording composer for accepted call-tomorrow contacts.

Selection, priority, status, and deadlines stay deterministic in reporting.py.
This module may only improve manager-facing wording for already accepted
contacts and falls back to the original payload on any contract violation.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

CALL_TOMORROW_WORDING_VERSION = "call_tomorrow_wording_composer_v1"
CALL_TOMORROW_WORDING_SOURCE = "report_evidence.call_tomorrow_wording_composer.v1"
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "call_tomorrow_wording_composer_v1.md"

_SALES_PUSH_TERMS = (
    "демо",
    "встреч",
    "презентац",
    "кп",
    "коммерческ",
    "счет",
    "счёт",
    "оплат",
    "договор",
    "подпис",
    "материал",
)
_REFUSAL_TERMS = (
    "не рассматри",
    "не заинтерес",
    "не актуал",
    "не готов",
    "пока нет",
    "сейчас нет",
    "не будем",
    "нет потребности",
    "не такие большие объем",
    "не такие большие объём",
)
_SERVICE_TERMS = ("ошиб", "не получилось", "не смог", "не смогла", "техподдерж", "сервис")


def compose_call_tomorrow_wording(
    call_tomorrow: dict[str, Any],
    *,
    llm3_enabled: bool | None = None,
) -> dict[str, Any]:
    """Return call_tomorrow with optional LLM3 wording applied."""
    original = dict(call_tomorrow or {})
    contacts = [_as_dict(item) for item in original.get("contacts") or []]
    if not contacts:
        return original
    payload = build_call_tomorrow_wording_payload(contacts)
    llm3_result, diagnostics = _try_llm3_call_tomorrow_wording(payload, force_enabled=llm3_enabled)
    original.setdefault("selection_diagnostics", {})["wording_composer"] = diagnostics
    if llm3_result is None:
        return original
    improved_by_key = {
        str(item.get("contact_key") or ""): item
        for item in llm3_result.get("contacts") or []
        if isinstance(item, dict)
    }
    updated_contacts: list[dict[str, Any]] = []
    for index, contact in enumerate(contacts):
        contact_key = _contact_key(contact, index)
        improved = _as_dict(improved_by_key.get(contact_key))
        if not improved:
            updated_contacts.append(contact)
            continue
        updated = dict(contact)
        updated["reason"] = _first_text(improved.get("reason"), contact.get("reason")) or ""
        updated["next_step"] = _ensure_sentence(
            _first_text(improved.get("next_step"), contact.get("next_step")) or ""
        )
        updated["recommendation"] = updated["next_step"]
        updated["opening_script"] = _first_text(
            improved.get("opening_script"),
            contact.get("opening_script"),
        ) or ""
        updated["wording_source"] = CALL_TOMORROW_WORDING_SOURCE
        updated["wording_reason"] = _first_text(improved.get("why_this_wording")) or ""
        updated_contacts.append(updated)
    original["contacts"] = updated_contacts
    original["wording_source_note"] = CALL_TOMORROW_WORDING_SOURCE
    original.setdefault("selection_diagnostics", {})["wording_composer"] = {
        **diagnostics,
        "llm3_used": True,
        "source_note": CALL_TOMORROW_WORDING_SOURCE,
    }
    return original


def build_call_tomorrow_wording_payload(contacts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contract_version": CALL_TOMORROW_WORDING_VERSION,
        "contacts": [
            {
                "contact_key": _contact_key(contact, index),
                "interaction_id": _first_text(contact.get("interaction_id")),
                "client_call_reference": _first_text(
                    contact.get("client_call_reference"),
                    contact.get("client_label"),
                    "Клиент",
                ),
                "status": _first_text(contact.get("status")),
                "priority_code": _first_text(contact.get("priority_code")),
                "priority_label": _first_text(contact.get("priority_label")),
                "deadline": _first_text(contact.get("deadline")),
                "action_profile": _first_text(contact.get("action_profile")),
                "reason": _first_text(contact.get("reason")),
                "next_step": _first_text(contact.get("next_step"), contact.get("recommendation")),
                "opening_script": _first_text(contact.get("opening_script")),
                "signal_text": _first_text(contact.get("signal_text")),
                "evidence_signal_text": _first_text(contact.get("evidence_signal_text")),
            }
            for index, contact in enumerate(contacts[:5])
        ],
        "output_rules": {
            "same_contacts_same_order": True,
            "do_not_change_priority_status_deadline": True,
            "russian_manager_facing": True,
            "grounded_in_signal_text": True,
        },
        "required_output_keys": ["status", "contacts", "selection_diagnostics"],
    }


def _try_llm3_call_tomorrow_wording(
    payload: dict[str, Any],
    *,
    force_enabled: bool | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    diagnostics: dict[str, Any] = {
        "llm3_enabled": _llm3_enabled() if force_enabled is None else bool(force_enabled),
        "llm3_used": False,
        "llm3_prompt_version": CALL_TOMORROW_WORDING_VERSION,
    }
    if not diagnostics["llm3_enabled"]:
        return None, diagnostics
    try:
        raw = _request_llm3_call_tomorrow_wording(payload)
        diagnostics["llm3_raw_status"] = raw.get("status")
        if isinstance(raw.get("_routing"), dict):
            diagnostics["llm3_routing"] = raw.get("_routing")
        normalized, reason = _normalize_llm3_call_tomorrow_wording(raw, payload)
        if normalized is None:
            diagnostics["llm3_rejection_reason"] = reason
            diagnostics["llm3_response"] = _json_safe(raw)
            return None, diagnostics
        diagnostics["llm3_used"] = True
        return normalized, diagnostics
    except Exception as exc:
        diagnostics["llm3_error"] = str(exc)
        return None, diagnostics


def _request_llm3_call_tomorrow_wording(payload: dict[str, Any]) -> dict[str, Any]:
    from openai import OpenAI

    from app.core_shared.ai_routing import AIProviderRouter
    from app.core_shared.config.settings import settings

    prompt = _read_prompt()
    subject_key = "call_tomorrow_wording_composer"
    route_plan = AIProviderRouter().build_route_plan(layer="llm3", subject_key=subject_key)
    candidate = route_plan.current_candidate()
    compatibility_candidate = candidate
    if (candidate.endpoint or "").rstrip("/") == "/chat/completions":
        compatibility_candidate = replace(candidate, endpoint=None)
    AIProviderRouter.ensure_execution_compatibility(
        compatibility_candidate,
        executor_label="LLM-3 Call Tomorrow wording composer",
        required_execution_mode="openai_compatible",
    )
    client = OpenAI(api_key=candidate.resolved_api_key(), base_url=candidate.api_base)
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
        request_kind="call_tomorrow_wording_composer",
        notes="LLM-3 Call Tomorrow wording composer completed.",
    )
    return result


def _normalize_llm3_call_tomorrow_wording(
    raw: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    if _text(raw.get("status")) != "verified":
        return None, "status_not_verified"
    source_contacts = [_as_dict(item) for item in payload.get("contacts") or []]
    raw_contacts = [_as_dict(item) for item in raw.get("contacts") or [] if isinstance(item, dict)]
    if len(raw_contacts) != len(source_contacts):
        return None, "contacts_count_changed"
    normalized: list[dict[str, Any]] = []
    for index, (source, item) in enumerate(zip(source_contacts, raw_contacts, strict=False)):
        expected_key = str(source.get("contact_key") or "")
        if str(item.get("contact_key") or "") != expected_key:
            return None, "contact_key_or_order_changed"
        reason = _first_text(item.get("reason"), source.get("reason")) or ""
        next_step = _ensure_sentence(_first_text(item.get("next_step"), source.get("next_step")) or "")
        opening_script = _first_text(item.get("opening_script"), source.get("opening_script")) or ""
        why = _first_text(item.get("why_this_wording")) or ""
        probe = " ".join([reason, next_step, opening_script, why])
        if not _manager_facing_russian_enough(probe):
            return None, "manager_facing_language_not_russian"
        rejection_reason = _wording_rejection_reason(
            source=source,
            reason=reason,
            next_step=next_step,
            opening_script=opening_script,
        )
        if rejection_reason:
            return None, f"{expected_key}:{rejection_reason}"
        normalized.append(
            {
                "contact_key": expected_key,
                "reason": reason,
                "next_step": next_step,
                "opening_script": opening_script,
                "why_this_wording": why,
            }
        )
    result = dict(raw)
    result.pop("_routing", None)
    result.update(
        {
            "status": "verified",
            "contacts": normalized,
            "selection_diagnostics": {
                **_as_dict(raw.get("selection_diagnostics")),
                "composer_version": CALL_TOMORROW_WORDING_VERSION,
                "selection_mode": "llm3_call_tomorrow_wording",
                "llm3_used": True,
            },
        }
    )
    return result, None


def _wording_rejection_reason(
    *,
    source: dict[str, Any],
    reason: str,
    next_step: str,
    opening_script: str,
) -> str | None:
    evidence = _loose_norm(" ".join(str(source.get(key) or "") for key in ("reason", "next_step", "opening_script", "signal_text", "evidence_signal_text")))
    output = _loose_norm(" ".join([reason, next_step, opening_script]))
    if _has_any(evidence, _REFUSAL_TERMS) and _has_any(output, _SALES_PUSH_TERMS):
        return "sales_push_after_refusal"
    if _has_any(evidence, _SERVICE_TERMS) and _has_any(output, _SALES_PUSH_TERMS):
        return "sales_push_before_service_issue_closed"
    unsupported_terms = _SALES_PUSH_TERMS
    for term in unsupported_terms:
        normalized = _loose_norm(term)
        if normalized and normalized in output and normalized not in evidence:
            return f"unsupported_claim:{normalized}"
    if len(_text(opening_script).split()) > 28:
        return "opening_script_too_long"
    return None


def _contact_key(contact: dict[str, Any], index: int) -> str:
    return (
        _first_text(contact.get("interaction_id"))
        or _first_text(contact.get("client_call_reference"))
        or _first_text(contact.get("client_label"))
        or f"contact_{index + 1}"
    )


def _llm3_enabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    try:
        from app.core_shared.config.settings import settings
    except Exception:
        return False
    return bool(settings.llm3_enabled)


def _read_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return "Improve accepted call-tomorrow wording as JSON. Do not change contacts."


def _extract_openai_message_content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return str(content or "").strip()


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _manager_facing_russian_enough(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return cyrillic >= 20 and cyrillic >= latin


def _ensure_sentence(value: Any) -> str:
    text = _text(value)
    if text and not text.endswith((".", "!", "?")):
        return f"{text}."
    return text


def _has_any(value: str, terms: tuple[str, ...]) -> bool:
    text = _loose_norm(value)
    return any(_loose_norm(term) in text for term in terms if _loose_norm(term))


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text(value)
        if text:
            return text
    return None


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _loose_norm(value: Any) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", " ", _text(value).lower().replace("ё", "е")).strip()
