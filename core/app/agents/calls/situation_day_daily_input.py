"""Build compact day-level input for a future SituationDayDailyComposer."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any, Iterable

try:
    from app.agents.calls.report_evidence_registry import build_report_evidence_registry
except ImportError:  # pragma: no cover - supports direct file imports in tests
    from report_evidence_registry import build_report_evidence_registry  # type: ignore


CONTRACT_VERSION = "situation_day_daily_input_v1"
_MANAGER_GAP_TYPES = {"manager_gap"}
_CUSTOMER_SIGNAL_TYPES = {"customer_signal", "service_issue"}
_STRENGTH_RANK = {"strong": 3, "medium": 2, "weak": 1, "insufficient": 0}


def build_situation_day_daily_input(
    artifacts: Any,
    *,
    report_evidence_index: dict[str, dict[str, Any]] | None = None,
    evidence_registry_items: Iterable[Any] | None = None,
    max_calls: int = 12,
    max_scenes_per_call: int = 3,
) -> dict[str, Any]:
    """Return compact day-level LLM input grouped by call.

    The builder intentionally keeps only normalized report evidence scenes,
    supporting quotes and call metadata. It never copies full transcripts.
    """

    artifact_list = _as_list(artifacts)
    call_inputs: dict[str, dict[str, Any]] = {}
    excluded = Counter()

    for artifact in artifact_list:
        call_id = _extract_call_id(artifact)
        if not call_id:
            excluded["missing_call_id"] += 1
            continue
        call_inputs[call_id] = _build_call_shell(
            call_id,
            artifact,
            _indexed_payload(report_evidence_index, call_id),
        )

    registry_items = _collect_registry_items(
        artifact_list,
        report_evidence_index=report_evidence_index,
        evidence_registry_items=evidence_registry_items,
    )

    sources = Counter()
    fragments_count = 0
    by_call: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_evidence: set[tuple[str, str, str, str]] = set()
    for raw_item in registry_items:
        item = _item_as_dict(raw_item)
        call_id = _text(item.get("call_id"))
        if not call_id:
            excluded["missing_call_id"] += 1
            continue
        source = _text(item.get("source")) or "unknown"
        quote = _text(item.get("supporting_quote")) or ""
        evidence_key = (
            call_id,
            _text(item.get("evidence_id")) or source,
            source,
            quote,
        )
        if evidence_key in seen_evidence:
            excluded["duplicate_evidence"] += 1
            continue
        seen_evidence.add(evidence_key)

        sources[source] += 1
        if _as_list(item.get("dialogue_scene")) or quote:
            fragments_count += 1
        by_call[call_id].append(item)
        if call_id not in call_inputs:
            call_inputs[call_id] = _build_call_shell(
                call_id,
                {},
                _indexed_payload(report_evidence_index, call_id),
            )

    calls: list[dict[str, Any]] = []
    for call_id, shell in call_inputs.items():
        normalized = _merge_call_evidence(
            shell,
            by_call.get(call_id, []),
            max_scenes_per_call=max_scenes_per_call,
        )
        if not _has_relevant_content(normalized):
            excluded["no_relevant_content"] += 1
            continue
        calls.append(normalized)

    calls.sort(key=_call_rank, reverse=True)
    if max_calls >= 0 and len(calls) > max_calls:
        excluded["max_calls"] += len(calls) - max_calls
        calls = calls[:max_calls]

    return {
        "contract_version": CONTRACT_VERSION,
        "calls": calls,
        "diagnostics": {
            "input_calls_count": len(call_inputs),
            "included_calls_count": len(calls),
            "fragments_count": fragments_count,
            "sources": dict(sorted(sources.items())),
            "excluded_count_by_reason": dict(sorted(excluded.items())),
        },
    }


def _collect_registry_items(
    artifacts: list[Any],
    *,
    report_evidence_index: dict[str, dict[str, Any]] | None,
    evidence_registry_items: Iterable[Any] | None,
) -> list[Any]:
    items: list[Any] = []
    if evidence_registry_items is not None:
        items.extend(list(evidence_registry_items))
    else:
        items.extend(build_report_evidence_registry(artifacts))

    index_artifacts = []
    for call_id, raw in (report_evidence_index or {}).items():
        payload = _as_dict(raw)
        evidence = _as_dict(payload.get("report_evidence") or payload)
        if evidence:
            index_artifacts.append({"call_id": call_id, "report_evidence": evidence})
    if index_artifacts:
        items.extend(build_report_evidence_registry(index_artifacts))
    return items


def _build_call_shell(
    call_id: str,
    artifact: Any,
    indexed: dict[str, Any],
) -> dict[str, Any]:
    artifact_map = _as_dict(artifact)
    interaction = _as_dict(_get(artifact, "interaction"))
    metadata = {}
    metadata.update(_as_dict(_get(interaction, "metadata_") or _get(interaction, "metadata")))
    metadata.update(_as_dict(artifact_map.get("metadata")))
    metadata.update(_as_dict(indexed.get("metadata")))

    analysis = _extract_analysis(artifact)
    if _as_dict(indexed.get("analysis")):
        analysis.update(_as_dict(indexed.get("analysis")))
    report_evidence = _extract_report_evidence(artifact)
    report_evidence.update(_as_dict(indexed.get("report_evidence")))
    summary = _as_dict(report_evidence.get("call_report_summary"))

    started_at = _first_text(
        _get(artifact, "call_started_at"),
        metadata.get("call_date"),
        metadata.get("started_at"),
        metadata.get("created_at"),
    )
    date_label, time_label = _date_time_labels(started_at)

    return _drop_none(
        {
            "call_id": call_id,
            "client_label": _first_text(
                metadata.get("contact_name"),
                metadata.get("client_name"),
                metadata.get("contact_label"),
                summary.get("client_display_name"),
            ),
            "client_call_reference": _first_text(
                metadata.get("client_call_reference"),
                metadata.get("call_reference"),
                metadata.get("source_call_id"),
                call_id,
            ),
            "date_label": _first_text(metadata.get("date_label"), date_label),
            "time_label": _first_text(metadata.get("time_label"), time_label),
            "outcome": _first_text(
                _path_get(report_evidence, "business_outcome.outcome"),
                _path_get(analysis, "business_outcome.outcome"),
                analysis.get("outcome"),
            ),
            "status": _first_text(
                _path_get(report_evidence, "business_outcome.status"),
                _path_get(analysis, "business_outcome.status"),
                analysis.get("status"),
            ),
            "stage": _first_text(
                _path_get(report_evidence, "stage.stage"),
                _path_get(analysis, "stage"),
                summary.get("stage"),
            ),
            "stage_code": _first_text(
                _path_get(report_evidence, "stage.stage_code"),
                _path_get(analysis, "stage_code"),
                summary.get("stage_code"),
            ),
            "score": _first_present(
                analysis.get("score"),
                analysis.get("total_score"),
                _path_get(analysis, "scores.total"),
            ),
            "llm2_summary": _first_text(
                analysis.get("llm2_summary"),
                summary.get("short_context"),
                summary.get("short_topic"),
            ),
            "call_summary": _first_text(
                analysis.get("call_summary"),
                summary.get("short_topic"),
                summary.get("manager_next_action"),
            ),
            "manager_gaps": [],
            "strengths": [],
            "customer_signals": [],
            "evidence_scenes": [],
            "quality_flags": [],
            "source_fact_ids": [],
        }
    )


def _merge_call_evidence(
    call: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    max_scenes_per_call: int,
) -> dict[str, Any]:
    manager_gaps: list[str] = []
    strengths: list[str] = []
    customer_signals: list[str] = []
    quality_flags: list[str] = []
    source_fact_ids: list[str] = []
    scenes: list[dict[str, Any]] = []

    sorted_items = sorted(items, key=_evidence_rank, reverse=True)
    for item in sorted_items:
        evidence_type = _text(item.get("evidence_type"))
        manager_gap = _text(item.get("manager_gap"))
        customer_context = _text(item.get("customer_context"))
        title = _text(item.get("problem_title"))

        if evidence_type in _MANAGER_GAP_TYPES and manager_gap:
            _append_unique(manager_gaps, manager_gap)
        elif evidence_type == "positive_case":
            _append_unique(strengths, manager_gap or title or customer_context)
        elif evidence_type in _CUSTOMER_SIGNAL_TYPES:
            _append_unique(customer_signals, customer_context or title or _text(item.get("supporting_quote")))
        elif evidence_type == "follow_up_opportunity":
            _append_unique(customer_signals, customer_context or title)

        for reason in _as_list(item.get("rejection_reasons")):
            reason_text = _text(reason)
            if reason_text:
                _append_unique(quality_flags, reason_text)
        for suitability in _as_dict(item.get("block_suitability")).values():
            for reason in _as_list(_as_dict(suitability).get("reasons")):
                reason_text = _text(reason)
                if reason_text:
                    _append_unique(quality_flags, reason_text)
        fact_id = _text(item.get("evidence_id"))
        if fact_id:
            _append_unique(source_fact_ids, fact_id)

        scene = _scene_from_item(item)
        if scene:
            scenes.append(scene)

    call["manager_gaps"] = manager_gaps
    call["strengths"] = strengths
    call["customer_signals"] = customer_signals
    call["evidence_scenes"] = scenes[: max(0, max_scenes_per_call)]
    call["quality_flags"] = quality_flags
    call["source_fact_ids"] = source_fact_ids
    return call


def _scene_from_item(item: dict[str, Any]) -> dict[str, Any] | None:
    turns = [_compact_turn(turn) for turn in _as_list(item.get("dialogue_scene"))]
    turns = [turn for turn in turns if turn]
    quote = _bounded_text(_text(item.get("supporting_quote")), 360)
    if not turns and not quote:
        return None
    summary = _first_text(item.get("manager_gap"), item.get("customer_context"), item.get("problem_title"))
    return _drop_none(
        {
            "scene_id": _text(item.get("evidence_id")),
            "source": _text(item.get("source")),
            "evidence_type": _text(item.get("evidence_type")),
            "proof_type": _text(item.get("proof_type")),
            "proof_strength": _text(item.get("proof_strength")),
            "stage_code": _text(item.get("stage_code")),
            "score": _first_present(
                _path_get(item, "diagnostics.score"),
                item.get("score"),
                item.get("priority_score"),
            ),
            "quote": quote,
            "turns": turns,
            "summary": _bounded_text(summary, 360),
            "next_time_action": _bounded_text(
                _first_text(
                    _path_get(item, "diagnostics.what_better"),
                    item.get("better_next_action"),
                    item.get("recommended_next_action"),
                ),
                360,
            ),
        }
    )


def _compact_turn(raw_turn: Any) -> dict[str, Any]:
    turn = _as_dict(raw_turn)
    text = _bounded_text(_first_text(turn.get("text"), turn.get("quote")), 360)
    if not text:
        return {}
    result: dict[str, Any] = {
        "speaker": _first_text(turn.get("speaker")) or "unknown",
        "text": text,
    }
    for key in ("timestamp_start", "timestamp_end", "start_sec", "end_sec"):
        if key in turn:
            result[key] = turn[key]
    return result


def _call_rank(call: dict[str, Any]) -> tuple[int, int, int, str]:
    scenes = _as_list(call.get("evidence_scenes"))
    manager_scene_count = sum(1 for scene in scenes if scene.get("evidence_type") == "manager_gap")
    return (
        len(_as_list(call.get("manager_gaps"))) * 100 + manager_scene_count * 25,
        len(scenes) * 10,
        len(_as_list(call.get("customer_signals"))),
        _text(call.get("call_id")) or "",
    )


def _evidence_rank(item: dict[str, Any]) -> tuple[int, int, int, str]:
    evidence_type = _text(item.get("evidence_type"))
    has_scene = bool(_as_list(item.get("dialogue_scene")) or _text(item.get("supporting_quote")))
    return (
        100 if evidence_type == "manager_gap" else 40 if evidence_type in _CUSTOMER_SIGNAL_TYPES else 20,
        10 if has_scene else 0,
        _STRENGTH_RANK.get(_text(item.get("proof_strength")) or "", 0),
        _text(item.get("source")) or "",
    )


def _has_relevant_content(call: dict[str, Any]) -> bool:
    return any(
        _as_list(call.get(key))
        for key in ("manager_gaps", "strengths", "customer_signals", "evidence_scenes")
    ) or bool(_first_text(call.get("llm2_summary"), call.get("call_summary")))


def _extract_call_id(artifact: Any) -> str | None:
    evidence = _extract_report_evidence(artifact)
    return _first_text(
        _path_get(artifact, "call_id"),
        _path_get(artifact, "interaction_id"),
        _path_get(artifact, "selected_call.call_id"),
        _path_get(artifact, "interaction.id"),
        _path_get(artifact, "llm2_facts.call_id"),
        evidence.get("call_id"),
    )


def _extract_analysis(artifact: Any) -> dict[str, Any]:
    raw = _as_dict(artifact)
    return _as_dict(
        raw.get("analysis")
        or raw.get("scores_detail")
        or _path_get(artifact, "analysis.scores_detail")
        or _path_get(artifact, "original_analysis.scores_detail")
    )


def _extract_report_evidence(artifact: Any) -> dict[str, Any]:
    raw = _as_dict(artifact)
    analysis = _extract_analysis(artifact)
    evidence = _as_dict(raw.get("report_evidence") or analysis.get("report_evidence"))
    if evidence.get("report_evidence"):
        evidence = _as_dict(evidence.get("report_evidence"))
    return evidence


def _indexed_payload(index: dict[str, dict[str, Any]] | None, call_id: str) -> dict[str, Any]:
    return _as_dict((index or {}).get(call_id))


def _item_as_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if is_dataclass(item):
        return asdict(item)
    return _as_dict(item)


def _date_time_labels(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    if isinstance(value, (datetime, date)):
        dt = value
    else:
        text = str(value).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text[:10] or None, text[11:16] if len(text) >= 16 else None
    if isinstance(dt, datetime):
        return dt.date().isoformat(), dt.strftime("%H:%M")
    return dt.isoformat(), None


def _path_get(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        current = _get(current, part)
        if current is None:
            return None
    return current


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return {}
    if is_dataclass(value):
        return asdict(value)
    namespace = getattr(value, "__dict__", None)
    if isinstance(namespace, dict):
        return dict(namespace)
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (str, bytes, dict)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text(value)
        if text:
            return text
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bounded_text(value: Any, limit: int) -> str | None:
    text = _text(value)
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def _append_unique(items: list[str], value: str | None) -> None:
    if value and value not in items:
        items.append(value)


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


__all__ = ["build_situation_day_daily_input"]
