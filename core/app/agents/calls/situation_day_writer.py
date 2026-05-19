"""Report-facing writer for the ``Ситуация дня`` block.

The writer accepts a selected evidence/composer payload and normalizes it into
one stable contract for report rendering.  It is deliberately deterministic:
LLM3 may be enabled by callers, but this module only exposes diagnostics for
that future path and never depends on a model call.
"""

from __future__ import annotations

import re
from typing import Any

SITUATION_DAY_WRITER_VERSION = "situation_day_writer_v1"
DEFAULT_SOURCE = "report_evidence.situation_day_writer.v1"

_ROLE_LABEL_RE = re.compile(
    r"(?i)(^|\s)(клиент|менеджер|client|customer|manager|agent)\s*[:：]"
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")

_MANAGER_SPEAKERS = {"manager", "agent", "seller", "sales", "менеджер", "оператор"}
_CLIENT_SPEAKERS = {"client", "customer", "buyer", "клиент", "заказчик", "покупатель"}


def compose_situation_day_view(
    selected: dict[str, Any],
    *,
    dialogue_turns: list[dict[str, Any]] | None = None,
    call_reference: dict[str, Any] | None = None,
    source_note: str | None = None,
    llm3_enabled: bool = False,
) -> dict[str, Any]:
    """Return the stable report-facing ``Ситуация дня`` contract.

    ``selected`` may be either the selected coaching view itself or a wider
    composer/evidence result containing ``coaching_view`` and
    ``dialogue_excerpt``.  The function never uses raw dialogue as the main
    ``what_happened`` text; turns are only used as bounded evidence snippets.
    """

    selected = _as_dict(selected)
    view = _merged_selected_view(selected)
    turns = _normalize_turns(
        dialogue_turns
        if dialogue_turns is not None
        else _nested_list(selected, ("dialogue_excerpt", "turns"))
        or _nested_list(view, ("dialogue_excerpt", "turns"))
        or _list_value(view.get("dialogue_fragment"))
        or _list_value(view.get("best_dialogue_fragment"))
    )
    role_confidence = _role_confidence(turns)

    pattern_title = _first_text(
        view.get("pattern_title"),
        view.get("problem_title"),
        selected.get("problem_title"),
        selected.get("situation_title"),
        "Ситуация дня",
    )
    moment_summary = _first_text(
        view.get("moment_summary"),
        view.get("summary"),
        view.get("client_context"),
        selected.get("client_context"),
        pattern_title,
    )
    manager_error = _first_text(
        view.get("manager_error"),
        view.get("what_was_missing"),
        view.get("manager_gap"),
        view.get("missing_action"),
        selected.get("manager_gap"),
        "Менеджер не зафиксировал управляемый следующий шаг.",
    )
    what_was_missing = _first_text(
        view.get("what_was_missing"),
        view.get("manager_gap"),
        view.get("missing_action"),
        manager_error,
    )
    next_time_action = _first_text(
        view.get("next_time_action"),
        view.get("better_next_action"),
        view.get("suggested_action"),
        selected.get("next_time_action"),
        "Резюмировать потребность клиента и договориться о конкретном следующем шаге.",
    )
    what_happened = _narrative_what_happened(
        view=view,
        selected=selected,
        turns=turns,
        role_confidence=role_confidence,
        moment_summary=moment_summary,
        manager_error=manager_error,
    )
    scripts = _normalized_scripts(view=view, next_time_action=next_time_action)
    evidence_explanation = _evidence_explanation(
        view=view,
        turns=turns,
        role_confidence=role_confidence,
        what_happened=what_happened,
        manager_error=manager_error,
    )
    source = _first_text(view.get("source"), selected.get("source"), DEFAULT_SOURCE)

    return {
        "pattern_title": pattern_title,
        "moment_summary": moment_summary,
        "what_happened": what_happened,
        "manager_error": manager_error,
        "evidence_explanation": evidence_explanation,
        "what_was_missing": what_was_missing,
        "next_time_action": next_time_action,
        "scripts": scripts,
        "source": source,
        "source_note": source_note
        if source_note is not None
        else _first_text(view.get("source_note"), selected.get("source_note"), source),
        "role_confidence": role_confidence,
        "situation_day_writer_quality": {
            "writer_version": SITUATION_DAY_WRITER_VERSION,
            "mode": "deterministic",
            "llm3_enabled": bool(llm3_enabled),
            "llm3_used": False,
            "role_confidence": role_confidence,
            "scripts_count": len(scripts),
            "raw_dialogue_used_as_what_happened": False,
            "call_reference_present": bool(call_reference),
        },
    }


def _merged_selected_view(selected: dict[str, Any]) -> dict[str, Any]:
    coaching_view = _as_dict(selected.get("coaching_view"))
    if not coaching_view:
        return dict(selected)
    merged = dict(selected)
    merged.update(coaching_view)
    return merged


def _narrative_what_happened(
    *,
    view: dict[str, Any],
    selected: dict[str, Any],
    turns: list[dict[str, str]],
    role_confidence: str,
    moment_summary: str,
    manager_error: str,
) -> str:
    direct = _first_text(
        view.get("what_happened"),
        view.get("evidence_scene"),
        selected.get("evidence_scene"),
        view.get("dialogue_summary"),
    )
    if (
        direct
        and not _looks_like_raw_dialogue(direct)
        and len(direct) >= 160
        and _norm_text(direct) != _norm_text(manager_error)
    ):
        return _ensure_sentence(_bounded_text(direct, 520))

    raw_client_context = _first_text(
        view.get("client_context"),
        selected.get("client_context"),
        view.get("customer_context"),
        selected.get("customer_context"),
        moment_summary,
    )
    client_context = _safe_context_summary(
        raw_client_context=raw_client_context,
        moment_summary=moment_summary,
        manager_error=manager_error,
    )
    if role_confidence == "high":
        client_text = _first_turn_text(turns, "client")
        manager_text = _first_turn_text(turns, "manager")
        if client_text and manager_text:
            return _ensure_sentence(
                "Клиент обозначил потребность: "
                f"{_strip_role_prefix(client_text)}. Ответ менеджера не закрыл риск: "
                f"{_strip_role_prefix(manager_text)}."
            )

    if role_confidence == "low":
        evidence_quote = _first_text(view.get("supporting_quote"), selected.get("supporting_quote"))
        if evidence_quote:
            return _ensure_sentence(
                "Сохраненный фрагмент показывает ситуацию: "
                f"«{_sentence_fragment(_strip_role_prefix(evidence_quote), limit=240)}». "
                f"Проблема для разбора: {_sentence_fragment(_strip_role_prefix(manager_error), limit=260)}"
            )
        return _ensure_sentence(
            "В выбранном фрагменте виден рабочий эпизод по теме: "
            f"{_sentence_fragment(_strip_role_prefix(client_context), limit=260)}. Проблема для разбора: "
            f"{_sentence_fragment(_strip_role_prefix(manager_error), limit=260)}"
        )

    return _ensure_sentence(
        "В разговоре проявилась ситуация: "
        f"{_sentence_fragment(_strip_role_prefix(client_context), limit=260)}. Ключевая ошибка менеджера: "
        f"{_sentence_fragment(_strip_role_prefix(manager_error), limit=260)}"
    )


def _safe_context_summary(
    *,
    raw_client_context: str,
    moment_summary: str,
    manager_error: str,
) -> str:
    """Prefer a readable context phrase over a pasted transcript scene."""
    context = _strip_role_prefix(raw_client_context)
    if not context or _looks_like_raw_dialogue(context) or _norm_text(context) == _norm_text(manager_error):
        context = _strip_role_prefix(moment_summary)
    if not context or _norm_text(context) == _norm_text(manager_error):
        context = "клиентская ситуация требовала уточнения и управляемого следующего шага"
    return _bounded_text(context, 260)


def _evidence_explanation(
    *,
    view: dict[str, Any],
    turns: list[dict[str, str]],
    role_confidence: str,
    what_happened: str,
    manager_error: str,
) -> str:
    if role_confidence == "high":
        labelled: list[str] = []
        for turn in turns:
            label = _role_label(turn["speaker"])
            if label:
                labelled.append(f"{label}: {_strip_role_prefix(turn['text'])}")
            if len(labelled) >= 3:
                break
        if labelled:
            return _bounded_text(" ".join(labelled), 700)

    fragment = _first_text(
        view.get("supporting_quote"),
        view.get("proof_explanation"),
        view.get("evidence_explanation"),
        what_happened,
    )
    prefix = "Фрагмент: " if fragment else ""
    return _bounded_text(f"{prefix}{_strip_role_prefix(fragment)} Подтверждает вывод: {manager_error}", 700)


def _normalized_scripts(*, view: dict[str, Any], next_time_action: str) -> list[str]:
    scripts: list[str] = []
    raw_scripts = view.get("scripts") or view.get("phrases") or view.get("suggested_phrases")
    if isinstance(raw_scripts, list):
        for item in raw_scripts:
            text = _first_text(item)
            if text and text not in scripts:
                scripts.append(_ensure_sentence(text))
    for item in (
        view.get("suggested_phrase"),
        view.get("script"),
        view.get("better_phrase"),
    ):
        text = _first_text(item)
        if text and text not in scripts:
            scripts.append(_ensure_sentence(text))

    fallbacks = [
        f"Давайте зафиксируем следующий шаг: {next_time_action} Кто с вашей стороны участвует и когда удобно вернуться к обсуждению?",
        "Правильно понимаю вашу задачу и критерии решения? Если да, согласуем конкретное время короткого демо или следующего контакта.",
    ]
    for fallback in fallbacks:
        if len(scripts) >= 2:
            break
        if fallback not in scripts:
            scripts.append(_ensure_sentence(fallback))
    return scripts[:4]


def _role_confidence(turns: list[dict[str, str]]) -> str:
    if not turns:
        return "low"
    speakers = {turn["speaker"] for turn in turns}
    if "client" in speakers and "manager" in speakers:
        return "high"
    if speakers <= {"unknown", "context", "evidence"}:
        return "low"
    return "medium"


def _normalize_turns(raw_turns: Any) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for raw in raw_turns or []:
        item = _as_dict(raw)
        text = _first_text(item.get("text"), item.get("quote"), item.get("content"))
        if not text:
            continue
        speaker = _normalize_speaker(item.get("speaker") or item.get("role"))
        turns.append({"speaker": speaker, "text": _bounded_text(text, 360)})
    return turns[:6]


def _normalize_speaker(value: Any) -> str:
    speaker = str(value or "unknown").strip().lower()
    if speaker in _CLIENT_SPEAKERS:
        return "client"
    if speaker in _MANAGER_SPEAKERS:
        return "manager"
    if speaker in {"context", "evidence", "unknown"}:
        return speaker
    return "unknown"


def _role_label(speaker: str) -> str | None:
    if speaker == "client":
        return "Клиент"
    if speaker == "manager":
        return "Менеджер"
    return None


def _first_turn_text(turns: list[dict[str, str]], speaker: str) -> str | None:
    for turn in turns:
        if turn["speaker"] == speaker:
            return turn["text"]
    return None


def _looks_like_raw_dialogue(text: str) -> bool:
    if not text:
        return False
    labels = len(_ROLE_LABEL_RE.findall(text))
    if labels >= 2:
        return True
    sentences = [part for part in _SENTENCE_SPLIT_RE.split(text.strip()) if part]
    if len(text) > 220 and len(sentences) >= 4:
        return True
    return labels == 1 and len(sentences) <= 2


def _strip_role_prefix(text: str) -> str:
    cleaned = re.sub(r"(?i)^\s*(клиент|менеджер|client|customer|manager|agent)\s*[:：]\s*", "", text or "")
    return cleaned.strip()


def _sentence_fragment(text: str, *, limit: int) -> str:
    return _bounded_text(text, limit).rstrip(".!?;: ").strip()


def _norm_text(text: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", str(text or "").lower())


def _bounded_text(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _ensure_sentence(text: str) -> str:
    text = _bounded_text(text, 700)
    if not text:
        return text
    if text[-1] not in ".!?…":
        return f"{text}."
    return text


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return _bounded_text(value, 900)
        if value is not None and not isinstance(value, (dict, list, tuple, set)):
            text = str(value).strip()
            if text:
                return _bounded_text(text, 900)
    return ""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _nested_list(payload: dict[str, Any], path: tuple[str, str]) -> list[Any]:
    current = _as_dict(payload.get(path[0]))
    value = current.get(path[1])
    return value if isinstance(value, list) else []
