"""Estimated AI cost accounting for call pipeline runs.

The catalog stores USD-denominated provider list prices as USDT-equivalent
values. This keeps pilot reporting in one currency while avoiding online
billing calls inside the pipeline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

PRICING_CATALOG_VERSION = "ai_cost_pricing_usdt_2026-06-04_v1"
PRICING_CURRENCY = "USDT"
USD_TO_USDT_RATE = 1.0


@dataclass(frozen=True, slots=True)
class AIPriceEntry:
    provider: str
    model: str
    input_per_1m_tokens_usdt: float | None = None
    output_per_1m_tokens_usdt: float | None = None
    stt_per_minute_usdt: float | None = None
    source: str = ""
    effective_from: str = "2026-06-04"


_PRICE_CATALOG: tuple[AIPriceEntry, ...] = (
    AIPriceEntry(
        provider="openai",
        model="gpt-5.4-mini",
        input_per_1m_tokens_usdt=0.75,
        output_per_1m_tokens_usdt=4.50,
        source="https://openai.com/api/pricing/",
    ),
    AIPriceEntry(
        provider="openai",
        model="gpt-5.4-nano",
        input_per_1m_tokens_usdt=0.20,
        output_per_1m_tokens_usdt=1.25,
        source="https://developers.openai.com/api/docs/models/gpt-5.4-nano",
    ),
    AIPriceEntry(
        provider="openai",
        model="whisper-1",
        stt_per_minute_usdt=0.006,
        source="https://developers.openai.com/api/docs/models/whisper-1",
    ),
    AIPriceEntry(
        provider="assemblyai",
        model="assemblyai_default",
        stt_per_minute_usdt=0.002833,
        source="https://www.assemblyai.com/pricing/",
    ),
    AIPriceEntry(
        provider="assemblyai",
        model="universal-2",
        stt_per_minute_usdt=0.002833,
        source="https://www.assemblyai.com/pricing/",
    ),
    AIPriceEntry(
        provider="moonshot",
        model="moonshot-v1-32k",
        input_per_1m_tokens_usdt=2.00,
        output_per_1m_tokens_usdt=5.00,
        source="https://platform.moonshot.ai/",
    ),
    AIPriceEntry(
        provider="moonshot",
        model="moonshot-v1-128k",
        input_per_1m_tokens_usdt=2.00,
        output_per_1m_tokens_usdt=5.00,
        source="https://platform.moonshot.ai/",
    ),
)


def estimate_run_ai_costs(
    *,
    build_summary: dict[str, Any],
    artifacts: list[Any],
    reports: list[dict[str, Any]],
    selected_interactions_count: int,
    manager_day_budget_usdt: float | None = None,
    warning_threshold_ratio: float = 0.8,
    over_budget_threshold_ratio: float = 1.0,
) -> dict[str, Any]:
    """Return estimated current-run AI costs in USDT."""
    layer_entries = _estimate_layer_entries(
        build_summary=build_summary,
        artifacts=artifacts,
        reports=reports,
    )
    total = _round_money(sum(_as_float(entry.get("current_run_cost_usdt")) for entry in layer_entries))
    transcribed = int(build_summary.get("transcripts_built") or 0)
    analyzed = int(build_summary.get("analyses_built") or 0)
    return {
        "schema_version": "ai_costs_v1",
        "pricing_catalog_version": PRICING_CATALOG_VERSION,
        "currency": PRICING_CURRENCY,
        "usd_to_usdt_rate": USD_TO_USDT_RATE,
        "cost_status": _resolve_overall_status(layer_entries),
        "budget_status": _resolve_budget_status(
            total,
            manager_day_budget_usdt=manager_day_budget_usdt,
            warning_threshold_ratio=warning_threshold_ratio,
            over_budget_threshold_ratio=over_budget_threshold_ratio,
        ),
        "manager_day_budget_usdt": manager_day_budget_usdt or None,
        "stt_cost_usdt": _layer_total(layer_entries, "stt"),
        "llm1_cost_usdt": _layer_total(layer_entries, "llm1"),
        "llm2_cost_usdt": _layer_total(layer_entries, "llm2"),
        "llm3_cost_usdt": _layer_total(layer_entries, "llm3"),
        "total_current_run_cost_usdt": total,
        "reused_artifact_original_cost_usdt": None,
        "cost_per_transcribed_call_usdt": _divide_money(total, transcribed) if transcribed else None,
        "cost_per_analyzed_call_usdt": _divide_money(total, analyzed) if analyzed else None,
        "cost_per_manager_day_report_usdt": total if selected_interactions_count else None,
        "by_layer": layer_entries,
        "by_request_kind": _summarize_by_request_kind(layer_entries),
        "notes": [
            "Estimated provider list prices are treated as USDT-equivalent at 1 USD = 1 USDT.",
            "Reused STT/analysis artifacts do not add current_run_cost_usdt.",
        ],
    }


def _estimate_layer_entries(
    *,
    build_summary: dict[str, Any],
    artifacts: list[Any],
    reports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    built_transcripts = int(build_summary.get("transcripts_built") or 0)
    built_analyses = int(build_summary.get("analyses_built") or 0)
    if built_transcripts:
        entries.extend(_estimate_stt_entries(artifacts=artifacts, built_limit=built_transcripts))
    if built_analyses:
        entries.extend(_estimate_llm_entries(artifacts=artifacts, layer="llm1", built_limit=built_analyses))
        entries.extend(_estimate_llm_entries(artifacts=artifacts, layer="llm2", built_limit=built_analyses))
    entries.extend(_estimate_llm3_entries(reports=reports))
    return entries


def _estimate_stt_entries(*, artifacts: list[Any], built_limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for artifact in artifacts:
        interaction = getattr(artifact, "interaction", None)
        interaction_id = str(getattr(interaction, "id", "") or "")
        if not interaction_id or interaction_id in seen:
            continue
        route = _route_metadata(interaction, "stt")
        if not _route_executed(route):
            continue
        seen.add(interaction_id)
        route_usage = route.get("usage") if isinstance(route.get("usage"), dict) else {}
        duration_sec = (
            _as_int(route.get("duration_sec"))
            or _as_int(route_usage.get("duration_sec"))
            or _as_int(getattr(interaction, "duration_sec", None))
        )
        entries.append(_make_stt_entry(route=route, interaction_id=interaction_id, duration_sec=duration_sec))
        if len(entries) >= built_limit:
            break
    if entries:
        return entries
    return [_missing_execution_entry(layer="stt", used_count=built_limit, reason="stt_route_metadata_missing")]


def _estimate_llm_entries(*, artifacts: list[Any], layer: str, built_limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        interaction = getattr(artifact, "interaction", None)
        interaction_id = str(getattr(interaction, "id", "") or "")
        if not interaction_id:
            continue
        for route in _iter_interaction_llm_routes(interaction=interaction, layer=layer):
            if not _route_executed(route):
                continue
            key = (interaction_id, str(route.get("request_kind") or layer))
            if key in seen:
                continue
            seen.add(key)
            entries.append(_make_llm_entry(route=route, layer=layer, subject_key=interaction_id))
        if len({item[0] for item in seen}) >= built_limit:
            # LLM-2 may have multiple request_kind entries per interaction; keep them.
            continue
    if entries:
        return entries
    return [_missing_execution_entry(layer=layer, used_count=built_limit, reason=f"{layer}_usage_metadata_missing")]


def _estimate_llm3_entries(*, reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for report in reports:
        payload = report.get("payload") if isinstance(report, dict) else None
        for route in _iter_nested_routes(payload, layer="llm3"):
            if not _route_executed(route):
                continue
            key = (
                str(route.get("subject_key") or ""),
                str(route.get("request_kind") or "llm3"),
                str(route.get("provider_request_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            entries.append(_make_llm_entry(route=route, layer="llm3", subject_key=key[0]))
    return entries


def _make_stt_entry(*, route: dict[str, Any], interaction_id: str, duration_sec: int | None) -> dict[str, Any]:
    provider = _provider_key(route)
    model = str(route.get("selected_model") or "").strip()
    billable_minutes = math.ceil(max(duration_sec or 0, 0) / 60) if duration_sec else None
    price = _find_price(provider=provider, model=model)
    cost_status = "available"
    cost = None
    if price is None or price.stt_per_minute_usdt is None:
        cost_status = "price_missing"
    elif billable_minutes is None:
        cost_status = "usage_missing"
    else:
        cost = _round_money(billable_minutes * price.stt_per_minute_usdt)
    return {
        "layer": "stt",
        "node": "stt",
        "request_kind": route.get("request_kind") or "speech_to_text",
        "subject_key": interaction_id,
        "provider": provider,
        "model": model or None,
        "used": True,
        "used_count": 1,
        "cost_status": cost_status,
        "current_run_cost_usdt": cost,
        "tokens": None,
        "duration_sec": duration_sec,
        "billable_minutes": billable_minutes,
        "pricing": _price_metadata(price),
        "provider_request_id": route.get("provider_request_id"),
    }


def _make_llm_entry(*, route: dict[str, Any], layer: str, subject_key: str) -> dict[str, Any]:
    provider = _provider_key(route)
    model = str(route.get("selected_model") or "").strip()
    usage = _normalize_usage(route.get("usage"))
    price = _find_price(provider=provider, model=model)
    cost_status = "available"
    cost = None
    if price is None or price.input_per_1m_tokens_usdt is None or price.output_per_1m_tokens_usdt is None:
        cost_status = "price_missing"
    elif not usage:
        cost_status = "usage_missing"
    else:
        input_tokens = _as_int(usage.get("prompt_tokens") or usage.get("input_tokens")) or 0
        output_tokens = _as_int(usage.get("completion_tokens") or usage.get("output_tokens")) or 0
        cost = _round_money(
            input_tokens * price.input_per_1m_tokens_usdt / 1_000_000
            + output_tokens * price.output_per_1m_tokens_usdt / 1_000_000
        )
    return {
        "layer": layer,
        "node": route.get("request_kind") or layer,
        "request_kind": route.get("request_kind") or layer,
        "subject_key": route.get("subject_key") or subject_key,
        "provider": provider,
        "model": model or None,
        "used": True,
        "used_count": 1,
        "cost_status": cost_status,
        "current_run_cost_usdt": cost,
        "tokens": usage,
        "duration_sec": None,
        "billable_minutes": None,
        "pricing": _price_metadata(price),
        "provider_request_id": route.get("provider_request_id"),
    }


def _missing_execution_entry(*, layer: str, used_count: int, reason: str) -> dict[str, Any]:
    return {
        "layer": layer,
        "node": layer,
        "request_kind": None,
        "subject_key": None,
        "provider": None,
        "model": None,
        "used": True,
        "used_count": used_count,
        "cost_status": "usage_missing",
        "current_run_cost_usdt": None,
        "tokens": None,
        "duration_sec": None,
        "billable_minutes": None,
        "pricing": None,
        "provider_request_id": None,
        "reason": reason,
    }


def _route_metadata(interaction: Any, layer: str) -> dict[str, Any]:
    metadata = dict(getattr(interaction, "metadata_", None) or {})
    ai_routing = dict(metadata.get("ai_routing") or {})
    route = ai_routing.get(layer)
    return dict(route) if isinstance(route, dict) else {}


def _iter_interaction_llm_routes(*, interaction: Any, layer: str) -> list[dict[str, Any]]:
    metadata = dict(getattr(interaction, "metadata_", None) or {})
    ai_routing = dict(metadata.get("ai_routing") or {})
    routes: list[dict[str, Any]] = []
    route = ai_routing.get(layer)
    if isinstance(route, dict):
        routes.append(dict(route))
    route_history = ai_routing.get(f"{layer}_history")
    if isinstance(route_history, list):
        routes.extend(dict(item) for item in route_history if isinstance(item, dict))
    return routes


def _iter_nested_routes(value: Any, *, layer: str) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("layer") == layer and any(key in value for key in ("selected_model", "usage", "request_kind")):
            routes.append(dict(value))
        for child in value.values():
            routes.extend(_iter_nested_routes(child, layer=layer))
    elif isinstance(value, list):
        for item in value:
            routes.extend(_iter_nested_routes(item, layer=layer))
    return routes


def _route_executed(route: dict[str, Any]) -> bool:
    if not route:
        return False
    if route.get("executed") is False:
        return False
    return str(route.get("execution_status") or "executed") == "executed"


def _provider_key(route: dict[str, Any]) -> str:
    provider = str(route.get("selected_provider") or route.get("provider") or "").strip().lower()
    api_base = str(route.get("selected_api_base") or route.get("api_base") or "").lower()
    model = str(route.get("selected_model") or "").lower()
    if "moonshot" in api_base or model.startswith(("moonshot-", "kimi-")):
        return "moonshot"
    return provider


def _find_price(*, provider: str, model: str) -> AIPriceEntry | None:
    provider_key = provider.strip().lower()
    model_key = model.strip().lower()
    for entry in _PRICE_CATALOG:
        if entry.provider == provider_key and entry.model == model_key:
            return entry
    return None


def _price_metadata(price: AIPriceEntry | None) -> dict[str, Any] | None:
    if price is None:
        return None
    return {
        "currency": PRICING_CURRENCY,
        "input_per_1m_tokens_usdt": price.input_per_1m_tokens_usdt,
        "output_per_1m_tokens_usdt": price.output_per_1m_tokens_usdt,
        "stt_per_minute_usdt": price.stt_per_minute_usdt,
        "effective_from": price.effective_from,
        "source": price.source,
    }


def _normalize_usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    usage = {
        key: _as_int(value.get(key))
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")
        if _as_int(value.get(key)) is not None
    }
    if "total_tokens" not in usage:
        total = (usage.get("prompt_tokens") or usage.get("input_tokens") or 0) + (
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        )
        if total:
            usage["total_tokens"] = total
    return usage or None


def _summarize_by_request_kind(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (str(entry.get("layer") or ""), str(entry.get("request_kind") or entry.get("node") or "unknown"))
        bucket = grouped.setdefault(
            key,
            {
                "layer": key[0],
                "request_kind": key[1],
                "used_count": 0,
                "current_run_cost_usdt": 0.0,
                "cost_statuses": [],
            },
        )
        bucket["used_count"] += int(entry.get("used_count") or 0)
        bucket["current_run_cost_usdt"] += _as_float(entry.get("current_run_cost_usdt"))
        status = entry.get("cost_status")
        if status and status not in bucket["cost_statuses"]:
            bucket["cost_statuses"].append(status)
    return [
        {**bucket, "current_run_cost_usdt": _round_money(bucket["current_run_cost_usdt"])}
        for bucket in grouped.values()
    ]


def _resolve_overall_status(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "not_used"
    statuses = {str(entry.get("cost_status") or "") for entry in entries}
    if statuses <= {"available"}:
        return "available"
    if "available" in statuses:
        return "partial"
    if "price_missing" in statuses:
        return "price_missing"
    return "usage_missing"


def _resolve_budget_status(
    cost: float,
    *,
    manager_day_budget_usdt: float | None,
    warning_threshold_ratio: float,
    over_budget_threshold_ratio: float,
) -> str:
    budget = _as_float(manager_day_budget_usdt)
    if budget <= 0:
        return "no_budget_configured"
    over_threshold = budget * max(over_budget_threshold_ratio, 0)
    warning_threshold = budget * max(warning_threshold_ratio, 0)
    if cost >= over_threshold:
        return "over_budget"
    if cost >= warning_threshold:
        return "warning"
    return "within_budget"


def _layer_total(entries: list[dict[str, Any]], layer: str) -> float | None:
    selected = [entry for entry in entries if entry.get("layer") == layer and entry.get("current_run_cost_usdt") is not None]
    if not selected:
        return None
    return _round_money(sum(_as_float(entry.get("current_run_cost_usdt")) for entry in selected))


def _divide_money(value: float, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return _round_money(value / denominator)


def _round_money(value: float) -> float:
    return round(float(value), 6)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
