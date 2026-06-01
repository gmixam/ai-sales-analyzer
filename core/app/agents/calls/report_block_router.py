"""Evidence-to-report-block routing for manager daily report composers.

The router is intentionally small and independent from ``reporting.py``.  It
accepts normalized Evidence Registry-like items and returns block-specific pools
plus item-level routing diagnostics that downstream composers can inspect.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Iterable, Literal


REPORT_BLOCK_ROUTER_VERSION = "report_block_router_v1"

ReportBlock = Literal[
    "situation_day",
    "call_breakdown",
    "voice_of_customer",
    "follow_up",
    "challenge",
    "additional_situations",
    "call_list",
]

BLOCKS: tuple[ReportBlock, ...] = (
    "situation_day",
    "call_breakdown",
    "voice_of_customer",
    "follow_up",
    "challenge",
    "additional_situations",
    "call_list",
)

BLOCK_ALIASES: dict[str, ReportBlock] = {
    "call_tomorrow": "follow_up",
    "tomorrow_follow_up": "follow_up",
    "tomorrow_challenge": "challenge",
    "call_list_context": "call_list",
}

STRONG_OR_MEDIUM_PROOF = {"strong", "medium"}
WEAK_PROOF = {"weak", "low", "insufficient"}
MANAGER_GAP_TYPES = {"manager_gap", "manager_coaching_moment", "stage_gap"}
CUSTOMER_SIGNAL_TYPES = {"customer_signal"}
SERVICE_ISSUE_TYPES = {"service_issue", "tech_service", "support_issue"}
FOLLOW_UP_TYPES = {"follow_up", "follow_up_opportunity", "open_next_step"}
CALL_ESSENCE_TYPES = {"call_essence"}
POSITIVE_CASE_TYPES = {"positive_case", "strong_practice"}
VERIFIED_PROOF_STATUS = "verified_proof_card"
SOFTENED_PROOF_STATUS = "softened_proof_card"
ADMITTED_PROOF_STATUSES = {VERIFIED_PROOF_STATUS, SOFTENED_PROOF_STATUS}
_VERIFIED_CARD_STATUSES = {"verified", "proven"}
_SOFTENED_CARD_STATUSES = {"soften", "softened", "downgrade"}
PROOF_REQUIRED_BLOCKS = {
    "situation_day",
    "call_breakdown",
    "voice_of_customer",
    "follow_up",
    "challenge",
    "additional_situations",
}
LEGACY_PROOF_SOURCES = {
    "report_evidence.block_candidates",
    "report_evidence.semantic_case",
    "report_evidence.manager_coaching_moments",
    "report_evidence.situation_candidates",
    "report_evidence.additional_situations",
    "report_evidence.voice_of_customer",
    "report_evidence.follow_up_candidates",
    "report_evidence.quote_bank",
}


@dataclass(slots=True, frozen=True)
class BlockRoutingDecision:
    """One route/reject diagnostic entry for one item and one block."""

    item_id: str
    block: ReportBlock
    decision: Literal["routed", "rejected"]
    reason: str
    evidence_type: str | None = None
    proof_strength: str | None = None
    call_id: str | None = None
    source: str | None = None
    score: float | None = None
    proof_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "block": self.block,
            "decision": self.decision,
            "reason": self.reason,
            "evidence_type": self.evidence_type,
            "proof_strength": self.proof_strength,
            "call_id": self.call_id,
            "source": self.source,
            "score": self.score,
            "proof_status": self.proof_status,
        }


def route_evidence_items(
    items: Iterable[Any],
    *,
    selected_situation_call_id: str | None = None,
    require_verified_proof: bool = True,
) -> dict[str, Any]:
    """Route Evidence Registry items into report-block pools.

    ``selected_situation_call_id`` means Situation Day is already verified.  In
    that mode Call Breakdown is limited to eligible manager-gap evidence from
    the same call.  Without a verified Situation Day the router chooses the best
    eligible manager coaching moment / manager gap as the Call Breakdown
    fallback.
    """

    normalized_items = [
        _normalize_item(raw_item, fallback_id=f"item_{index}")
        for index, raw_item in enumerate(items)
    ]
    pools: dict[ReportBlock, list[dict[str, Any]]] = {block: [] for block in BLOCKS}
    routed: list[BlockRoutingDecision] = []
    rejected: list[BlockRoutingDecision] = []

    for block in BLOCKS:
        if block == "call_breakdown" and selected_situation_call_id is None:
            _route_call_breakdown_fallback(
                normalized_items=normalized_items,
                pools=pools,
                routed=routed,
                rejected=rejected,
                require_verified_proof=require_verified_proof,
            )
            continue

        for item in normalized_items:
            usable, reason = _evaluate_item_for_block(
                item,
                block,
                selected_situation_call_id=selected_situation_call_id,
                require_verified_proof=require_verified_proof,
            )
            decision = _decision(item, block, "routed" if usable else "rejected", reason)
            if usable:
                pools[block].append(_pool_item(item, block=block, reason=reason))
                routed.append(decision)
            else:
                rejected.append(decision)

    for block in BLOCKS:
        pools[block].sort(key=_sort_key)

    return {
        "routing_version": REPORT_BLOCK_ROUTER_VERSION,
        "selected_situation_call_id": selected_situation_call_id,
        **pools,
        "diagnostics": {
            "proof_gate_mode": "strict" if require_verified_proof else "diagnostics_only",
            "require_verified_proof": require_verified_proof,
            "routed": [item.to_dict() for item in routed],
            "rejected": [item.to_dict() for item in rejected],
            "source_consistency": _source_consistency_diagnostics(pools),
            "summary": {
                "input_count": len(normalized_items),
                "routed_count_by_block": {
                    block: len(pools[block]) for block in BLOCKS
                },
                "rejected_count": len(rejected),
            },
        },
    }


def is_usable_for_block(
    item: Any,
    block: str,
    *,
    require_verified_proof: bool = True,
) -> tuple[bool, str]:
    """Return whether ``item`` can be used for a canonical report block.

    The helper is deliberately fail-closed.  It accepts dicts, dataclasses,
    pydantic-like models, and simple objects.
    """

    canonical_block = _canonical_block(block)
    if canonical_block is None:
        return False, "unknown_block"
    normalized = _normalize_item(item, fallback_id="item")
    return _evaluate_item_for_block(
        normalized,
        canonical_block,
        require_verified_proof=require_verified_proof,
    )


def _route_call_breakdown_fallback(
    *,
    normalized_items: list[dict[str, Any]],
    pools: dict[ReportBlock, list[dict[str, Any]]],
    routed: list[BlockRoutingDecision],
    rejected: list[BlockRoutingDecision],
    require_verified_proof: bool,
) -> None:
    eligible: list[dict[str, Any]] = []
    weak_scene_fallback: list[dict[str, Any]] = []
    for item in normalized_items:
        usable, reason = _evaluate_item_for_block(
            item,
            "call_breakdown",
            require_verified_proof=require_verified_proof,
        )
        if usable:
            eligible.append(item)
            continue
        if (
            reason == "weak_proof"
            and _evidence_type(item) in MANAGER_GAP_TYPES
            and _has_dialogue_scene(item)
            and not _has_counter_evidence(item)
        ):
            weak_scene_fallback.append(item)
            continue
        rejected.append(_decision(item, "call_breakdown", "rejected", reason))

    fallback_reason = "fallback_best_manager_moment"
    if not eligible and weak_scene_fallback:
        eligible = weak_scene_fallback
        fallback_reason = "fallback_weak_scene_manager_moment"

    eligible.sort(key=_sort_key)
    if not eligible:
        return

    selected = eligible[0]
    pools["call_breakdown"].append(
        _pool_item(selected, block="call_breakdown", reason=fallback_reason)
    )
    routed.append(
        _decision(selected, "call_breakdown", "routed", fallback_reason)
    )
    for item in eligible[1:]:
        rejected.append(_decision(item, "call_breakdown", "rejected", "lower_ranked_fallback"))


def _evaluate_item_for_block(
    item: dict[str, Any],
    block: ReportBlock,
    *,
    selected_situation_call_id: str | None = None,
    require_verified_proof: bool = True,
) -> tuple[bool, str]:
    if not _truthy_item(item):
        return False, "not_eligible"
    suitability = _block_suitability(item, block)
    if suitability is not None:
        if suitability.get("eligible") is False:
            reasons = suitability.get("reasons")
            if isinstance(reasons, list) and reasons:
                return False, _text(reasons[0]) or "block_suitability_not_eligible"
            if suitability.get("fit") is False:
                return False, "fit_false"
            return False, "block_suitability_not_eligible"
        if suitability.get("fit") is False:
            return False, "fit_false"

    evidence_type = _evidence_type(item)
    proof_strength = _proof_strength(item)

    if _has_counter_evidence(item) and block in {
        "situation_day",
        "call_breakdown",
        "challenge",
        "additional_situations",
    }:
        return False, "counter_evidence"

    if require_verified_proof and _requires_verified_proof(item, block) and not _has_verified_proof(item):
        return False, "missing_proof_card"

    if evidence_type in SERVICE_ISSUE_TYPES and block in {
        "situation_day",
        "call_breakdown",
        "challenge",
        "additional_situations",
    }:
        return False, "service_issue_forbidden"

    if block == "situation_day":
        if evidence_type in CUSTOMER_SIGNAL_TYPES:
            return False, "customer_signal_routed_elsewhere"
        if evidence_type in SERVICE_ISSUE_TYPES:
            return False, "service_issue_forbidden"
        if evidence_type != "manager_gap":
            return False, "wrong_evidence_type"
        if proof_strength in WEAK_PROOF:
            return False, "weak_proof"
        if proof_strength not in STRONG_OR_MEDIUM_PROOF and not _is_pattern_level(item):
            return False, "weak_proof"
        if not _has_scene(item):
            return False, "no_scene"
        return True, "manager_gap_verified_for_situation_day"

    if block == "call_breakdown":
        if selected_situation_call_id is not None:
            call_id = _text(_field(item, "call_id", "interaction_id"))
            if call_id and call_id != selected_situation_call_id:
                return False, "wrong_call"
        if evidence_type not in MANAGER_GAP_TYPES:
            if evidence_type in CUSTOMER_SIGNAL_TYPES:
                return False, "customer_signal_routed_elsewhere"
            return False, "wrong_evidence_type"
        if proof_strength in WEAK_PROOF:
            return False, "weak_proof"
        if not _has_scene(item):
            return False, "no_scene"
        return True, "eligible_manager_gap"

    if block == "voice_of_customer":
        if evidence_type in SERVICE_ISSUE_TYPES:
            return False, "service_issue_forbidden"
        if evidence_type not in CUSTOMER_SIGNAL_TYPES:
            return False, "wrong_evidence_type"
        if proof_strength in WEAK_PROOF:
            return False, "weak_proof"
        if not _has_scene(item):
            return False, "no_scene"
        return True, "customer_signal"

    if block == "follow_up":
        if _evidence_type(item) in CALL_ESSENCE_TYPES and _norm(
            _field(item, "status", "follow_up_status", "outcome_status", "outcome")
        ) in {"open", "rescheduled", "agreement"} and not _text(
            _field(item, "next_step", "manager_next_action")
        ):
            return False, "missing_next_step"
        if _is_follow_up_item(item):
            if proof_strength in WEAK_PROOF:
                return False, "weak_proof"
            return True, "open_next_step"
        return False, "wrong_evidence_type"

    if block == "challenge":
        if evidence_type not in MANAGER_GAP_TYPES:
            if evidence_type in CUSTOMER_SIGNAL_TYPES:
                return False, "customer_signal_routed_elsewhere"
            return False, "wrong_evidence_type"
        if proof_strength in WEAK_PROOF:
            return False, "weak_proof"
        if not (_is_repeated_gap(item) or _is_stage_gap(item)):
            return False, "not_repeated_or_stage_gap"
        if not _has_scene(item):
            return False, "no_scene"
        return True, "repeated_or_stage_gap"

    if block == "additional_situations":
        if evidence_type not in MANAGER_GAP_TYPES | POSITIVE_CASE_TYPES:
            if evidence_type in CUSTOMER_SIGNAL_TYPES:
                return False, "customer_signal_routed_elsewhere"
            return False, "wrong_evidence_type"
        if proof_strength in WEAK_PROOF:
            return False, "weak_proof"
        if not (_is_secondary(item) or evidence_type in POSITIVE_CASE_TYPES):
            return False, "not_secondary"
        if not _has_scene(item):
            return False, "no_scene"
        return True, "secondary_manager_gap_or_positive_case"

    if block == "call_list":
        if _has_call_list_context(item):
            return True, "call_list_context"
        return False, "wrong_evidence_type"

    return False, "unknown_block"


def _normalize_item(raw_item: Any, *, fallback_id: str) -> dict[str, Any]:
    item = _to_dict(raw_item)
    item.setdefault(
        "item_id",
        _first_text(
            item.get("item_id"),
            item.get("evidence_id"),
            item.get("id"),
            item.get("candidate_id"),
            fallback_id,
        ),
    )
    item.setdefault("evidence_type", _infer_evidence_type(item))
    item.setdefault("proof_strength", _proof_strength(item))
    item.setdefault("score", _score(item))
    return item


def _to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dict(dumped) if isinstance(dumped, dict) else {}
    if hasattr(value, "_asdict"):
        dumped = value._asdict()
        return dict(dumped) if isinstance(dumped, dict) else {}
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict):
        return dict(attrs)
    return {}


def _pool_item(item: dict[str, Any], *, block: ReportBlock, reason: str) -> dict[str, Any]:
    routed_item = dict(item)
    routed_item["router"] = {
        "version": REPORT_BLOCK_ROUTER_VERSION,
        "block": block,
        "reason": reason,
        "score": _score(item),
        "proof_status": _proof_status(item),
    }
    return routed_item


def _source_consistency_diagnostics(
    pools: dict[ReportBlock, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    call_list_by_call = _top_item_by_call_id(pools.get("call_list", []))
    follow_up_by_call = _top_item_by_call_id(pools.get("follow_up", []))
    diagnostics: list[dict[str, Any]] = []
    for call_id in sorted(set(call_list_by_call) | set(follow_up_by_call)):
        call_list_item = call_list_by_call.get(call_id)
        follow_up_item = follow_up_by_call.get(call_id)
        if not call_list_item or not follow_up_item:
            diagnostics.append(
                {
                    "call_id": call_id,
                    "consistent": True,
                    "reason": "single_block_source",
                    "call_list_source": _source_name(call_list_item),
                    "follow_up_source": _source_name(follow_up_item),
                }
            )
            continue
        call_list_source = _source_name(call_list_item)
        follow_up_source = _source_name(follow_up_item)
        consistent = call_list_source == follow_up_source
        diagnostics.append(
            {
                "call_id": call_id,
                "consistent": consistent,
                "reason": "same_source" if consistent else "multiple_sources_available",
                "call_list_source": call_list_source,
                "follow_up_source": follow_up_source,
                "preferred_source": "report_evidence.call_essence"
                if "report_evidence.call_essence" in {call_list_source, follow_up_source}
                else call_list_source,
            }
        )
    return diagnostics


def _top_item_by_call_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in sorted(items, key=_sort_key):
        call_id = _text(_field(item, "call_id", "interaction_id"))
        if call_id and call_id not in result:
            result[call_id] = item
    return result


def _source_name(item: dict[str, Any] | None) -> str | None:
    if not item:
        return None
    return _text(_field(item, "source", "path")) or None


def _decision(
    item: dict[str, Any],
    block: ReportBlock,
    decision: Literal["routed", "rejected"],
    reason: str,
) -> BlockRoutingDecision:
    return BlockRoutingDecision(
        item_id=_text(item.get("item_id")) or "item",
        block=block,
        decision=decision,
        reason=reason,
        evidence_type=_evidence_type(item) or None,
        proof_strength=_proof_strength(item) or None,
        call_id=_text(_field(item, "call_id", "interaction_id")) or None,
        source=_text(_field(item, "source", "path")) or None,
        score=_score(item),
        proof_status=_proof_status(item) or None,
    )


def _canonical_block(block: str) -> ReportBlock | None:
    key = _norm(block)
    if key in BLOCKS:
        return key  # type: ignore[return-value]
    return BLOCK_ALIASES.get(key)


def _field(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item:
            return item.get(key)
    call_essence = item.get("call_essence")
    if isinstance(call_essence, dict):
        for key in keys:
            if key in call_essence:
                return call_essence.get(key)
    return None


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _block_suitability(item: dict[str, Any], block: ReportBlock) -> dict[str, Any] | None:
    suitability = item.get("block_suitability")
    if not isinstance(suitability, dict):
        return None
    direct = suitability.get(block)
    if isinstance(direct, dict):
        return direct
    for alias, canonical in BLOCK_ALIASES.items():
        if canonical == block and isinstance(suitability.get(alias), dict):
            return suitability[alias]
    return None


def _evidence_type(item: dict[str, Any]) -> str:
    return _norm(_field(item, "evidence_type", "type", "case_type", "item_type", "kind"))


def _infer_evidence_type(item: dict[str, Any]) -> str:
    block = _canonical_block(_text(item.get("block") or item.get("target_block")))
    role = _norm(_field(item, "role", "block_role"))
    case_type = _norm(_field(item, "case_type"))
    source = _norm(_field(item, "source", "path"))
    reason = _norm(_field(item, "reason_code", "reason"))
    if (
        block == "voice_of_customer"
        or role == "customer_signal"
        or case_type == "customer_signal"
        or "customer_signal" in reason
    ):
        return "customer_signal"
    if case_type == "call_essence" or role == "call_list_context" or "call_essence" in source:
        return "call_essence"
    if block == "follow_up" or role == "follow_up_action" or "follow_up" in reason:
        return "follow_up"
    if case_type == "service_issue" or "service" in reason or "service" in source:
        return "service_issue"
    if case_type == "insufficient_evidence":
        return "insufficient"
    if role == "strong_practice" or case_type == "strong_practice":
        return "positive_case"
    if block in {"situation_day", "call_breakdown", "challenge", "additional_situations"}:
        return "manager_gap"
    if source.endswith("manager_coaching_moments") or "manager_coaching_moments" in source:
        return "manager_coaching_moment"
    return ""


def _proof_strength(item: dict[str, Any]) -> str:
    explicit = _norm(_field(item, "proof_strength", "evidence_strength"))
    if explicit in {"high", "direct"}:
        return "strong"
    if explicit in {"medium", "indirect"}:
        return "medium"
    if explicit in WEAK_PROOF:
        return "weak"
    if explicit:
        return explicit

    quality = _norm(_field(item, "evidence_quality", "confidence"))
    if quality in {"direct", "high"}:
        return "strong"
    if quality in {"indirect", "medium"}:
        return "medium"
    if quality in {"weak", "low", "insufficient"}:
        return "weak"
    if _is_pattern_level(item):
        return "medium"
    return ""


def _truthy_item(item: dict[str, Any]) -> bool:
    if item.get("usable_in_report") is False:
        return False
    if item.get("fit") is False:
        return False
    status = _norm(_field(item, "status", "evidence_status"))
    if status in {"insufficient", "no_data", "not_eligible", "rejected"}:
        return False
    return True


def _requires_verified_proof(item: dict[str, Any], block: ReportBlock) -> bool:
    if block in {"situation_day", "call_breakdown"}:
        return True
    return block in PROOF_REQUIRED_BLOCKS and _is_legacy_proof_source(item)


def _has_verified_proof(item: dict[str, Any]) -> bool:
    if item.get("verified_source") is True:
        return True
    if _proof_status(item) in ADMITTED_PROOF_STATUSES:
        return True
    return _proof_card_is_verified(item)


def _proof_status(item: dict[str, Any]) -> str:
    status = _text(_field(item, "proof_status", "evidence_status"))
    if status:
        return status
    diagnostics = _as_mapping(item.get("diagnostics"))
    status = _text(diagnostics.get("proof_status"))
    if status:
        return status
    if _as_mapping(item.get("proof_card")):
        if _proof_card_is_verified(item):
            status = _norm(_as_mapping(item.get("proof_card")).get("status"))
            if status in _SOFTENED_CARD_STATUSES:
                return SOFTENED_PROOF_STATUS
            return VERIFIED_PROOF_STATUS
        return "unverified_proof_card"
    if _is_legacy_proof_source(item):
        return "legacy_hint_only"
    return ""


def _proof_card_is_verified(item: dict[str, Any]) -> bool:
    proof_card = _as_mapping(_field(item, "proof_card"))
    if not proof_card:
        return False
    if _text(proof_card.get("reject_reason")):
        return False
    status = _norm(proof_card.get("status"))
    if status and status not in _VERIFIED_CARD_STATUSES | _SOFTENED_CARD_STATUSES:
        return False
    evidence_type = _evidence_type(item)
    if evidence_type in MANAGER_GAP_TYPES and proof_card.get("gap_proven") is False:
        return False
    return True


def _is_legacy_proof_source(item: dict[str, Any]) -> bool:
    source = _norm(_field(item, "source", "path"))
    if not source:
        return False
    return any(
        source == legacy_source
        or source.startswith(f"{legacy_source}.")
        or source.startswith(f"{legacy_source}[")
        for legacy_source in LEGACY_PROOF_SOURCES
    )


def _has_counter_evidence(item: dict[str, Any]) -> bool:
    if _norm(item.get("quote_role")) == "counter_evidence":
        return True
    counter = item.get("counter_evidence")
    if isinstance(counter, list):
        return any(_text(value) for value in counter)
    return bool(_text(counter))


def _has_scene(item: dict[str, Any]) -> bool:
    scene_fields = (
        "evidence_scene",
        "scene",
        "context_text",
        "supporting_quote",
        "quote",
        "transcript_excerpt",
        "what_happened",
        "summary",
    )
    if any(_text(item.get(field)) for field in scene_fields):
        return True
    for list_field in ("dialogue_fragment", "best_dialogue_fragment", "turns", "evidence_refs"):
        value = item.get(list_field)
        if isinstance(value, list) and value:
            return True
    dialogue_scene = item.get("dialogue_scene")
    if isinstance(dialogue_scene, list) and dialogue_scene:
        return True
    return False


def _has_dialogue_scene(item: dict[str, Any]) -> bool:
    for list_field in ("dialogue_scene", "dialogue_fragment", "best_dialogue_fragment", "turns"):
        value = item.get(list_field)
        if isinstance(value, list) and value:
            return True
    return bool(_text(_field(item, "supporting_quote", "quote", "transcript_excerpt")))


def _is_pattern_level(item: dict[str, Any]) -> bool:
    source = _norm(_field(item, "source", "path"))
    level = _norm(_field(item, "level", "evidence_level", "granularity"))
    return (
        bool(item.get("pattern_level"))
        or level in {"pattern", "pattern_level"}
        or "pattern" in source
    )


def _is_follow_up_item(item: dict[str, Any]) -> bool:
    evidence_type = _evidence_type(item)
    role = _norm(_field(item, "role", "block_role"))
    status = _norm(_field(item, "status", "follow_up_status", "outcome_status", "outcome"))
    reason = _norm(_field(item, "reason_code", "reason"))
    return (
        evidence_type in FOLLOW_UP_TYPES
        or (
            evidence_type in CALL_ESSENCE_TYPES
            and status in {"open", "rescheduled", "agreement"}
            and bool(_text(_field(item, "next_step", "manager_next_action")))
        )
        or role == "follow_up_action"
        or (evidence_type not in CALL_ESSENCE_TYPES and status in {"open", "rescheduled", "agreement"})
        or bool(item.get("open_next_steps"))
        or "client_requested_next_action" in reason
    )


def _is_repeated_gap(item: dict[str, Any]) -> bool:
    if item.get("repeated") is True:
        return True
    for key in ("occurrences", "pattern_occurrences", "call_count", "count"):
        value = item.get(key)
        if isinstance(value, (int, float)) and value >= 2:
            return True
    text = _norm(
        " ".join(_text(_field(item, "reason_code", "source", "path", "pattern_code")).split())
    )
    return "repeated" in text or "повтор" in text


def _is_stage_gap(item: dict[str, Any]) -> bool:
    if item.get("stage_gap") is True:
        return True
    if _evidence_type(item) == "stage_gap":
        return True
    stage_code = _text(_field(item, "stage_code", "stage"))
    return bool(stage_code and _evidence_type(item) in MANAGER_GAP_TYPES)


def _is_secondary(item: dict[str, Any]) -> bool:
    if item.get("secondary") is True:
        return True
    role = _norm(_field(item, "role", "block_role"))
    priority = _norm(item.get("priority"))
    source = _norm(_field(item, "source", "path"))
    return (
        role in {"secondary", "growth_zone", "coaching_problem"}
        or priority in {"medium", "low"}
        or "additional" in source
    )


def _has_call_list_context(item: dict[str, Any]) -> bool:
    block = _canonical_block(_text(_field(item, "block", "target_block")))
    role = _norm(_field(item, "role", "block_role"))
    evidence_type = _evidence_type(item)
    return (
        block == "call_list"
        or evidence_type in CALL_ESSENCE_TYPES
        or role in {"call_list_context", "neutral_summary"}
        or bool(
            _text(
                _field(
                    item,
                    "short_topic",
                    "short_context",
                    "call_list_topic",
                    "manager_visible_text",
                )
            )
        )
    )


def _sort_key(item: dict[str, Any]) -> tuple[float, int, str]:
    return (-(_score(item) or 0.0), _proof_rank(_proof_strength(item)), _text(item.get("item_id")))


def _score(item: dict[str, Any]) -> float:
    value = _field(item, "score", "fit_score", "priority_score")
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(_text(value))
    except ValueError:
        pass
    priority = _norm(item.get("priority"))
    if priority == "high":
        return 80.0
    if priority == "medium":
        return 60.0
    if priority == "low":
        return 40.0
    return 0.0


def _proof_rank(value: str) -> int:
    if value == "strong":
        return 0
    if value == "medium":
        return 1
    if value == "weak":
        return 2
    return 3


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        value = value.value
    return str(value).strip()


def _norm(value: Any) -> str:
    return _text(value).lower().strip()
