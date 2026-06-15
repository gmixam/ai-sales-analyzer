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
    include_llm1_cost: bool = True,
) -> dict[str, Any]:
    """Return estimated current-run AI costs in USDT."""
    layer_entries = _estimate_layer_entries(
        build_summary=build_summary,
        artifacts=artifacts,
        reports=reports,
        include_llm1_cost=include_llm1_cost,
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
        "cost_per_transcribed_call_usdt": (
            _divide_money(total, transcribed) if transcribed else None
        ),
        "cost_per_analyzed_call_usdt": _divide_money(total, analyzed) if analyzed else None,
        "cost_per_manager_day_report_usdt": total if selected_interactions_count else None,
        "by_layer": layer_entries,
        "by_request_kind": _summarize_by_request_kind(layer_entries),
        "notes": [
            "Estimated provider list prices are treated as USDT-equivalent at 1 USD = 1 USDT.",
            "Reused STT/analysis artifacts do not add current_run_cost_usdt.",
        ],
    }


def estimate_call_processing_costs(
    *,
    execution_entries: list[Any] | None = None,
    planned: dict[str, Any] | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Return estimated upstream call-processing current-run costs in USDT.

    `execution_entries` is intentionally lightweight: call-processing can pass
    newly built STT/LLM1 artifact or provider execution dictionaries without
    introducing a second pricing catalog. Reused/backfilled artifacts should be
    either omitted or marked with current_run=False / reused=True / backfilled=True.
    """
    entries = _estimate_call_processing_layer_entries(
        execution_entries=execution_entries or [],
        planned=planned or {},
        mode=mode,
    )
    total = _round_money(sum(_as_float(entry.get("current_run_cost_usdt")) for entry in entries))
    transcribed = _count_used_entries(entries, "stt")
    return {
        "schema_version": "split_upstream_ai_costs_v1",
        "pricing_catalog_version": PRICING_CATALOG_VERSION,
        "currency": PRICING_CURRENCY,
        "usd_to_usdt_rate": USD_TO_USDT_RATE,
        "cost_status": "no_billable_work" if not entries else _resolve_overall_status(entries),
        "stt_cost_usdt": _layer_total(entries, "stt"),
        "llm1_cost_usdt": _layer_total(entries, "llm1"),
        "total_current_run_cost_usdt": total,
        "reused_artifact_original_cost_usdt": None,
        "cost_per_transcribed_call_usdt": (
            _divide_money(total, transcribed) if transcribed else None
        ),
        "by_layer": entries,
        "by_request_kind": _summarize_by_request_kind(entries),
        "notes": [
            "Estimated provider list prices are treated as USDT-equivalent at 1 USD = 1 USDT.",
            "DRY_RUN, backfilled, and reused upstream artifacts do not add current_run_cost_usdt.",
        ],
    }


def merge_split_ai_costs(
    upstream_costs: dict[str, Any] | None,
    downstream_costs: dict[str, Any],
    counters: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
    *,
    manager_day_budget_usdt: float | None = None,
    warning_threshold_ratio: float = 0.8,
    over_budget_threshold_ratio: float = 1.0,
) -> dict[str, Any]:
    """Merge upstream call-processing and downstream reporting costs."""
    if not isinstance(upstream_costs, dict) or not upstream_costs:
        return downstream_costs

    counters = counters or {}
    budget = budget or {}
    resolved_budget = (
        manager_day_budget_usdt
        if manager_day_budget_usdt is not None
        else budget.get("manager_day_budget_usdt")
    )
    warning_ratio = _as_float(budget.get("warning_threshold_ratio") or warning_threshold_ratio)
    over_ratio = _as_float(budget.get("over_budget_threshold_ratio") or over_budget_threshold_ratio)

    upstream_entries = _as_list(upstream_costs.get("by_layer"))
    downstream_entries = _as_list(downstream_costs.get("by_layer"))
    layer_entries = [*upstream_entries, *downstream_entries]
    total = _round_money(
        _as_float(upstream_costs.get("total_current_run_cost_usdt"))
        + _as_float(downstream_costs.get("total_current_run_cost_usdt"))
    )
    transcribed = _first_positive_int(
        counters.get("transcribed_calls"),
        counters.get("transcripts_ready"),
        counters.get("transcripts_built"),
        _count_used_entries(upstream_entries, "stt"),
    )
    analyzed = _first_positive_int(
        counters.get("analyzed_calls"),
        counters.get("ready_analyses"),
        counters.get("analyses_ready"),
        counters.get("analyses_built"),
    )
    manager_day_reports = _first_positive_int(
        counters.get("manager_day_reports"),
        counters.get("reports_built"),
    )
    reused_original_cost = _sum_optional_money(
        upstream_costs.get("reused_artifact_original_cost_usdt"),
        downstream_costs.get("reused_artifact_original_cost_usdt"),
    )
    return {
        "schema_version": "split_ai_costs_v1",
        "pricing_catalog_version": PRICING_CATALOG_VERSION,
        "currency": PRICING_CURRENCY,
        "usd_to_usdt_rate": USD_TO_USDT_RATE,
        "cost_status": _merge_cost_status(
            upstream_costs.get("cost_status"),
            downstream_costs.get("cost_status"),
        ),
        "upstream": upstream_costs,
        "downstream": downstream_costs,
        "budget_status": _resolve_budget_status(
            total,
            manager_day_budget_usdt=_as_float(resolved_budget) or None,
            warning_threshold_ratio=warning_ratio,
            over_budget_threshold_ratio=over_ratio,
        ),
        "manager_day_budget_usdt": _as_float(resolved_budget) or None,
        "stt_cost_usdt": _sum_layer_costs(upstream_costs, downstream_costs, key="stt_cost_usdt"),
        "llm1_cost_usdt": _sum_layer_costs(upstream_costs, downstream_costs, key="llm1_cost_usdt"),
        "llm2_cost_usdt": _sum_layer_costs(upstream_costs, downstream_costs, key="llm2_cost_usdt"),
        "llm3_cost_usdt": _sum_layer_costs(upstream_costs, downstream_costs, key="llm3_cost_usdt"),
        "total_current_run_cost_usdt": total,
        "reused_artifact_original_cost_usdt": reused_original_cost,
        "cost_per_transcribed_call_usdt": _divide_money(total, transcribed) if transcribed else None,
        "cost_per_analyzed_call_usdt": _divide_money(total, analyzed) if analyzed else None,
        "cost_per_manager_day_report_usdt": _divide_money(total, manager_day_reports)
        if manager_day_reports
        else None,
        "by_layer": layer_entries,
        "by_request_kind": _summarize_by_request_kind(layer_entries),
        "notes": [
            (
                "Split cost summary merges upstream call-processing current-run cost "
                "with downstream analysis/reporting current-run cost."
            ),
            *list(upstream_costs.get("notes") or []),
            *list(downstream_costs.get("notes") or []),
        ],
    }


def _estimate_call_processing_layer_entries(
    *,
    execution_entries: list[Any],
    planned: dict[str, Any],
    mode: str | None,
) -> list[dict[str, Any]]:
    if str(mode or "").strip().lower() in {"dry_run", "dry-run", "dryrun"}:
        return []
    entries: list[dict[str, Any]] = []
    for raw_entry in execution_entries:
        item = _entry_as_dict(raw_entry)
        if not item or not _is_current_run_billable_entry(item):
            continue
        layer = _normalize_upstream_layer(item)
        route = _upstream_route(item, layer=layer)
        subject_key = str(item.get("interaction_id") or item.get("subject_key") or "")
        if layer == "stt":
            usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
            duration_sec = _as_int(item.get("duration_sec")) or _as_int(usage.get("duration_sec"))
            entries.append(
                _make_stt_entry(
                    route=route,
                    interaction_id=subject_key,
                    duration_sec=duration_sec,
                )
            )
        elif layer == "llm1":
            entries.append(_make_llm_entry(route=route, layer="llm1", subject_key=subject_key))

    if entries:
        return entries

    missing_entries: list[dict[str, Any]] = []
    transcripts_built = _as_int(planned.get("transcripts_built")) or 0
    llm1_built = _as_int(planned.get("llm1_first_pass_built") or planned.get("llm1_built")) or 0
    if transcripts_built:
        missing_entries.append(
            _missing_execution_entry(
                layer="stt",
                used_count=transcripts_built,
                reason="stt_usage_metadata_missing",
            )
        )
    if llm1_built:
        missing_entries.append(
            _missing_execution_entry(
                layer="llm1",
                used_count=llm1_built,
                reason="llm1_usage_metadata_missing",
            )
        )
    return missing_entries


def _estimate_layer_entries(
    *,
    build_summary: dict[str, Any],
    artifacts: list[Any],
    reports: list[dict[str, Any]],
    include_llm1_cost: bool = True,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    built_transcripts = int(build_summary.get("transcripts_built") or 0)
    built_analyses = int(build_summary.get("analyses_built") or 0)
    if built_transcripts:
        entries.extend(_estimate_stt_entries(artifacts=artifacts, built_limit=built_transcripts))
    if built_analyses:
        if include_llm1_cost:
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


def _make_stt_entry(
    *,
    route: dict[str, Any],
    interaction_id: str,
    duration_sec: int | None,
) -> dict[str, Any]:
    provider = _provider_key(route)
    model = str(route.get("selected_model") or route.get("model") or "").strip()
    route_usage = route.get("usage") if isinstance(route.get("usage"), dict) else {}
    billable_minutes = _as_int(route.get("billable_minutes")) or _as_int(
        route_usage.get("billable_minutes")
    )
    if billable_minutes is None and duration_sec:
        billable_minutes = math.ceil(max(duration_sec or 0, 0) / 60)
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
    model = str(route.get("selected_model") or route.get("model") or "").strip()
    usage = _normalize_usage(route.get("usage"))
    price = _find_price(provider=provider, model=model)
    cost_status = "available"
    cost = None
    if (
        price is None
        or price.input_per_1m_tokens_usdt is None
        or price.output_per_1m_tokens_usdt is None
    ):
        cost_status = "price_missing"
    elif not usage:
        cost_status = "usage_missing"
    else:
        input_tokens = _as_int(usage.get("prompt_tokens") or usage.get("input_tokens")) or 0
        output_tokens = _as_int(usage.get("completion_tokens") or usage.get("output_tokens")) or 0
        if input_tokens + output_tokens <= 0:
            cost_status = "usage_missing"
        else:
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
    model = str(route.get("selected_model") or route.get("model") or "").lower()
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
        key = (
            str(entry.get("layer") or ""),
            str(entry.get("request_kind") or entry.get("node") or "unknown"),
        )
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


def _entry_as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    data: dict[str, Any] = {}
    for key in (
        "artifact_kind",
        "kind",
        "layer",
        "request_kind",
        "interaction_id",
        "subject_key",
        "provider",
        "model",
        "account_alias",
        "api_key_env",
        "raw_response_ref",
        "provider_request_id",
        "duration_sec",
        "usage",
        "current_run",
        "reused",
        "backfilled",
        "status",
    ):
        if hasattr(value, key):
            data[key] = getattr(value, key)
    return data


def _is_current_run_billable_entry(item: dict[str, Any]) -> bool:
    if item.get("current_run") is False:
        return False
    if item.get("reused") is True or item.get("backfilled") is True:
        return False
    status = str(item.get("status") or "ready").strip().lower()
    return status in {"ready", "built", "executed", "success", "succeeded"}


def _normalize_upstream_layer(item: dict[str, Any]) -> str:
    raw = str(
        item.get("layer")
        or item.get("artifact_kind")
        or item.get("kind")
        or item.get("request_kind")
        or ""
    )
    normalized = raw.strip().lower()
    if normalized in {"transcript", "transcript_segments", "speech_to_text", "stt"}:
        return "stt"
    if normalized in {"llm1", "llm1_first_pass", "first_pass"}:
        return "llm1"
    return normalized


def _upstream_route(item: dict[str, Any], *, layer: str) -> dict[str, Any]:
    route = dict(item.get("route") or {}) if isinstance(item.get("route"), dict) else {}
    route.update(
        {
            key: value
            for key, value in item.items()
            if key
            in {
                "selected_provider",
                "provider",
                "selected_model",
                "model",
                "selected_api_base",
                "api_base",
                "usage",
                "request_kind",
                "provider_request_id",
                "raw_response_ref",
            }
            and value is not None
        }
    )
    route.setdefault("layer", layer)
    route.setdefault("request_kind", "speech_to_text" if layer == "stt" else layer)
    if "provider_request_id" not in route and route.get("raw_response_ref"):
        route["provider_request_id"] = route.get("raw_response_ref")
    return route


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _count_used_entries(entries: list[dict[str, Any]], layer: str) -> int:
    return sum(
        int(entry.get("used_count") or 0)
        for entry in entries
        if entry.get("layer") == layer
    )


def _first_positive_int(*values: Any) -> int:
    for value in values:
        parsed = _as_int(value)
        if parsed and parsed > 0:
            return parsed
    return 0


def _sum_optional_money(*values: Any) -> float | None:
    known = [value for value in values if value is not None]
    if not known:
        return None
    return _round_money(sum(_as_float(value) for value in known))


def _sum_layer_costs(*cost_summaries: dict[str, Any], key: str) -> float | None:
    known = [
        summary.get(key)
        for summary in cost_summaries
        if isinstance(summary, dict) and summary.get(key) is not None
    ]
    if not known:
        return None
    return _round_money(sum(_as_float(value) for value in known))


def _merge_cost_status(*statuses: Any) -> str:
    normalized = {
        str(status or "").strip()
        for status in statuses
        if str(status or "").strip()
        and str(status or "").strip() not in {"not_used", "no_billable_work"}
    }
    if not normalized:
        return "available"
    if normalized <= {"available"}:
        return "available"
    if "available" in normalized or "partial" in normalized:
        return "partial"
    if "price_missing" in normalized:
        return "price_missing"
    return "usage_missing"


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
    selected = [
        entry
        for entry in entries
        if entry.get("layer") == layer and entry.get("current_run_cost_usdt") is not None
    ]
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
