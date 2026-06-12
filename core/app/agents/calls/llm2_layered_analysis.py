"""Bounded adapter for future layered LLM-2 analysis artifacts.

This module intentionally does not wire the layered LLM-2 passes into the
production CallsAnalyzer runtime. It only assembles already-produced
LLM-2A/2B/2C/2D artifacts into the current scores_detail-compatible shape and
passes proof cards through the existing report_evidence validator.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.agents.calls.analyzer import (
    APPROVED_CHECKLIST_VERSION,
    APPROVED_SCHEMA_VERSION,
    CHECKLIST_DEFINITION,
)
from app.agents.calls.report_evidence import (
    SUPPORTED_REPORT_EVIDENCE_VERSION,
    ReportEvidenceValidationResult,
    validate_report_evidence,
)


LAYERED_ADAPTER_INSTRUCTION_VERSION = "llm2_layered_analysis_adapter_v1"

_ACCEPTED_PROOF_STATUSES = {"proven", "verified", "soften", "softened"}
_CURRENT_PROOF_STATUS_BY_LAYERED_STATUS = {
    "proven": "proven",
    "verified": "verified",
    "softened": "soften",
    "soften": "soften",
    "rejected": "reject",
    "reject": "reject",
    "insufficient": "retry",
    "retry": "retry",
    "downgrade": "downgrade",
    "warning": "warning",
}
_CURRENT_REJECT_REASON_BY_LAYERED_REASON = {
    "no_scene": "missing_scene",
    "missing_scene": "missing_scene",
    "no_evidence": "missing_evidence",
    "missing_evidence": "missing_evidence",
    "quote_not_exact": "ungrounded_quote",
    "ungrounded_quote": "ungrounded_quote",
    "counter_evidence_stronger": "counter_evidence_conflict",
    "counter_evidence_conflict": "counter_evidence_conflict",
    "claim_too_broad": "claim_too_broad",
    "unsupported_absence": "missing_evidence",
    "missing_recommendation_link": "missing_recommendation_link",
    "not_sales_coaching": "form_only_issue",
    "contradicts_transcript": "counter_evidence_conflict",
}
_VALID_STAGE_CODES = {
    str(stage.get("stage_code"))
    for stage in CHECKLIST_DEFINITION.get("stages", [])
    if stage.get("stage_code")
}
_STAGE_CODE_ALIASES = {
    "qualification_pain": "qualification_primary",
    "qualification": "qualification_primary",
    "need_discovery": "needs_discovery",
    "next_step": "completion_next_step",
    "closing": "completion_next_step",
    "sale": "sale_final",
}
_STATUS_DETAILS_KEYS = ("agreement", "rescheduled", "refusal", "open", "service")
_STATUS_DETAILS_ALIASES = {
    "agreed": "agreement",
    "agreement": "agreement",
    "deal": "agreement",
    "rescheduled": "rescheduled",
    "postponed": "rescheduled",
    "callback": "rescheduled",
    "refusal": "refusal",
    "declined": "refusal",
    "rejected": "refusal",
    "open": "open",
    "tech_service": "service",
    "support": "service",
    "service": "service",
}
_STATUS_DETAILS_FIELDS = {
    "agreement": (
        "type",
        "what_agreed",
        "manager_commitment",
        "client_commitment",
        "owner",
        "deadline",
        "evidence",
    ),
    "rescheduled": (
        "reason",
        "return_when",
        "return_owner",
        "preparation_needed",
        "evidence",
    ),
    "refusal": (
        "type",
        "reason",
        "finality",
        "return_condition",
        "recommended_next_action",
        "evidence",
    ),
    "open": (
        "why_open",
        "missing_to_close",
        "next_action",
        "owner",
        "deadline",
        "evidence",
    ),
    "service": (
        "type",
        "request",
        "action_taken",
        "follow_up_needed",
        "follow_up_action",
        "owner",
        "sales_scoring_applicability",
        "evidence",
    ),
}
_EDO_SALES_SCORING_SCOPES = {"full", "partial", "none", "unclear"}
_EDO_SCOPE_REASONS = {
    "edo_sales",
    "edo_service",
    "legal_direction",
    "tech_support",
    "internal_or_wrong_call",
    "mixed",
    "insufficient_data",
    "other",
}
_EDO_EXPECTED_MANAGER_ACTIONS = {
    "sell",
    "transfer",
    "support",
    "clarify",
    "close_service_issue",
    "keep_relationship",
    "no_action",
    "other",
}
_COACHING_DECISIONS = {"improve", "maintain", "no_comment"}
_COACHING_TITLES_BY_DECISION = {
    "improve": {"Улучшить"},
    "maintain": {"Поддерживать", "Корректно"},
    "no_comment": {None, ""},
}


@dataclass(frozen=True, slots=True)
class LayeredLLM2NormalizationResult:
    """Result of adapting layered LLM-2 artifacts into scores_detail."""

    scores_detail: dict[str, Any]
    report_evidence_validation: ReportEvidenceValidationResult | None

    @property
    def is_valid(self) -> bool:
        """Return whether the report_evidence admission gate passed."""

        if self.report_evidence_validation is None:
            return True
        return self.report_evidence_validation.is_valid


def normalize_llm2_layered_scores_detail(
    artifact: dict[str, Any],
    *,
    transcript: str | None = None,
    validate_evidence: bool = True,
) -> dict[str, Any]:
    """Return only the scores_detail-compatible payload for a layered artifact."""

    return normalize_llm2_layered_analysis(
        artifact,
        transcript=transcript,
        validate_evidence=validate_evidence,
    ).scores_detail


def normalize_llm2_layered_analysis(
    artifact: dict[str, Any],
    *,
    transcript: str | None = None,
    validate_evidence: bool = True,
) -> LayeredLLM2NormalizationResult:
    """Assemble LLM-2A/2B/2C/2D artifacts into a scores_detail-compatible dict."""

    root = _as_dict(artifact)
    llm2a = _extract_pass_artifact(root, "2a")
    llm2b = _extract_pass_artifact(root, "2b")
    llm2c = _extract_pass_artifact(root, "2c")
    llm2d = _extract_pass_artifact(root, "2d")

    final_from_2d = _as_dict(llm2d.get("final_normalized_analysis"))
    scores_detail = _scores_detail_base(
        root=root,
        llm2a=llm2a,
        llm2d=llm2d,
        final_from_2d=final_from_2d,
    )
    edo_scope, edo_scope_warnings = _normalized_edo_scope(llm2a.get("edo_scope"))
    if edo_scope:
        scores_detail["edo_scope"] = edo_scope
    if edo_scope_warnings:
        diagnostics = _as_dict(scores_detail.get("diagnostics"))
        diagnostics.setdefault("edo_scope_validation", []).extend(edo_scope_warnings)
        scores_detail["diagnostics"] = diagnostics

    evidence_by_id = _evidence_ledger_by_id(llm2a)
    scenes_by_id = _scenes_by_id(llm2a)
    proof_cards = _normalized_proof_cards(
        proof_cards=_source_proof_cards(llm2c=llm2c, llm2d=llm2d),
        recommendations=_as_list(llm2d.get("recommendations")),
        evidence_by_id=evidence_by_id,
    )
    accepted_proof_cards = _accepted_proof_cards_by_id(proof_cards)

    criteria_results = _as_list(
        llm2b.get("criteria_results")
        or final_from_2d.get("criteria_results")
        or scores_detail.get("criteria_results")
    )
    scores_detail["criteria_results"] = _normalized_criteria_results(
        criteria_results=criteria_results,
        evidence_by_id=evidence_by_id,
    )
    scores_detail["score_by_stage"] = _score_by_stage_from_criteria(
        scores_detail["criteria_results"]
    )
    scores_detail["strengths"] = _normalized_strengths(
        _as_list(llm2b.get("strength_claims") or final_from_2d.get("strengths")),
        evidence_by_id=evidence_by_id,
    )
    scores_detail["gaps"] = _normalized_gaps(
        gap_claims=_as_list(llm2b.get("gap_claims") or final_from_2d.get("gaps")),
        proof_cards_by_claim_id=_accepted_proof_cards_by_claim_id(proof_cards),
        evidence_by_id=evidence_by_id,
    )
    scores_detail["recommendations"] = _normalized_recommendations(
        _as_list(final_from_2d.get("recommendations") or llm2d.get("recommendations")),
        accepted_proof_cards=accepted_proof_cards,
    )
    status_details = _normalized_status_details(
        final_from_2d.get("status_details") or llm2d.get("status_details")
    )
    if status_details:
        scores_detail["status_details"] = status_details
    else:
        scores_detail.pop("status_details", None)
    coaching_decision = _normalized_coaching_decision(
        final_from_2d.get("coaching_decision") or llm2d.get("coaching_decision"),
        scores_detail=scores_detail,
    )
    if coaching_decision:
        scores_detail["coaching_decision"] = coaching_decision
    else:
        scores_detail.pop("coaching_decision", None)
    if not scores_detail.get("evidence_fragments"):
        scores_detail["evidence_fragments"] = _evidence_fragments_from_scenes(
            scenes_by_id=scenes_by_id,
            evidence_by_id=evidence_by_id,
        )
    _attach_report_evidence(
        scores_detail=scores_detail,
        llm2a=llm2a,
        final_from_2d=final_from_2d,
        proof_cards=proof_cards,
        evidence_by_id=evidence_by_id,
    )
    _attach_layered_analysis_metadata(
        scores_detail=scores_detail,
        llm2a=llm2a,
        llm2b=llm2b,
        llm2c=llm2c,
        llm2d=llm2d,
        proof_cards=proof_cards,
    )
    _populate_checklist_score(scores_detail)
    _repair_vague_availability_follow_up(scores_detail)
    _repair_recommendation_like_follow_up(scores_detail)
    _attach_semantic_diagnostics(scores_detail)

    validation_result = (
        validate_report_evidence(scores_detail, transcript) if validate_evidence else None
    )
    if validation_result is not None and validation_result.normalized:
        scores_detail.update(validation_result.normalized)

    return LayeredLLM2NormalizationResult(
        scores_detail=scores_detail,
        report_evidence_validation=validation_result,
    )


def _scores_detail_base(
    *,
    root: dict[str, Any],
    llm2a: dict[str, Any],
    llm2d: dict[str, Any],
    final_from_2d: dict[str, Any],
) -> dict[str, Any]:
    scores_detail = deepcopy(final_from_2d)
    call_id = _first_non_empty_str(
        scores_detail.get("call_id"),
        _as_dict(scores_detail.get("call")).get("call_id"),
        _as_dict(scores_detail.get("call")).get("id"),
        llm2d.get("call_id"),
        llm2a.get("call_id"),
        root.get("call_id"),
    )
    scores_detail.setdefault("schema_version", APPROVED_SCHEMA_VERSION)
    scores_detail.setdefault("instruction_version", LAYERED_ADAPTER_INSTRUCTION_VERSION)
    scores_detail.setdefault("checklist_version", APPROVED_CHECKLIST_VERSION)
    scores_detail.setdefault("analysis_timestamp", datetime.now(UTC).isoformat())
    call = _as_dict(scores_detail.get("call"))
    if call_id:
        call.setdefault("id", call_id)
        call.setdefault("call_id", call_id)
    scores_detail["call"] = call
    classification = _as_dict(scores_detail.get("classification"))
    classification.setdefault(
        "analysis_eligibility",
        llm2a.get("analysis_eligibility") or "insufficient",
    )
    classification.setdefault("eligibility_reason", llm2a.get("eligibility_reason"))
    admission_gate = _as_dict(root.get("llm2_admission_gate") or root.get("llm2_admission"))
    if admission_gate.get("admitted") is True:
        eligibility = _lower_str(classification.get("analysis_eligibility"))
        if eligibility in {"not_eligible", "insufficient"}:
            original_reason = classification.get("eligibility_reason")
            classification["analysis_eligibility"] = "eligible"
            classification["eligibility_reason"] = "llm2_admission_gate_accepted"
            if original_reason:
                classification["eligibility_reason_before_admission_gate"] = original_reason
            classification["eligibility_overridden_by_admission_gate"] = True
    scores_detail["classification"] = classification
    if admission_gate:
        diagnostics = _as_dict(scores_detail.get("diagnostics"))
        diagnostics["llm2_admission_gate"] = admission_gate
        scores_detail["diagnostics"] = diagnostics
    scores_detail.setdefault("summary", {})
    scores_detail.setdefault("score", {"checklist_score": {}})
    scores_detail.setdefault("agreements", [])
    scores_detail.setdefault("follow_up", {})
    scores_detail.setdefault("product_signals", [])
    scores_detail.setdefault("analytics_tags", [])
    scores_detail.setdefault("data_quality", {})
    return scores_detail


def _extract_pass_artifact(root: dict[str, Any], pass_name: str) -> dict[str, Any]:
    normalized_pass = pass_name.lower().replace("-", "")
    direct_pass = str(root.get("pass") or "").lower().replace("-", "")
    if direct_pass in {f"llm{normalized_pass}", f"llm{normalized_pass.upper()}".lower()}:
        return root
    candidates = (
        f"llm{normalized_pass}_artifact",
        f"llm{normalized_pass}",
        f"LLM-{pass_name.upper()}",
        f"LLM{pass_name.upper()}",
        pass_name.upper(),
        pass_name.lower(),
    )
    for key in candidates:
        value = root.get(key)
        if isinstance(value, dict):
            return value
    nested = _as_dict(root.get("artifacts"))
    for key in candidates:
        value = nested.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _source_proof_cards(*, llm2c: dict[str, Any], llm2d: dict[str, Any]) -> list[dict[str, Any]]:
    universal_pack = _as_dict(llm2d.get("universal_evidence_pack"))
    proof_cards = _as_list(universal_pack.get("proof_cards"))
    if proof_cards:
        proof_cards_by_id = {
            str(card.get("proof_id")): card
            for card in _as_list(llm2c.get("proof_cards"))
            if isinstance(card, dict) and card.get("proof_id")
        }
        merged = []
        for card in proof_cards:
            if not isinstance(card, dict):
                continue
            source = dict(proof_cards_by_id.get(str(card.get("proof_id")) or "", {}))
            source.update(card)
            merged.append(source)
        return merged
    return _as_list(llm2c.get("proof_cards"))


def _normalized_proof_cards(
    *,
    proof_cards: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    recommendation_by_proof_id = {
        str(item.get("proof_id")): item
        for item in recommendations
        if isinstance(item, dict) and item.get("proof_id")
    }
    normalized = []
    for raw_card in proof_cards:
        card = _as_dict(raw_card)
        proof_id = _str_or_none(card.get("proof_id"))
        if not proof_id:
            continue
        supporting_ids = _string_list(
            card.get("supporting_evidence_ids")
            or card.get("evidence_ids")
            or ([card.get("evidence_id")] if card.get("evidence_id") else [])
        )
        counter_ids = _string_list(card.get("counter_evidence_ids"))
        status = _proof_status(card)
        recommendation = recommendation_by_proof_id.get(proof_id, {})
        normalized_card = {
            "_claim_id": card.get("claim_id"),
            "proof_id": _clip(proof_id, 120),
            "claim": _clip(
                card.get("softened_claim")
                if status == "soften" and card.get("softened_claim")
                else card.get("claim"),
                420,
            ),
            "claim_scope": card.get("claim_scope") or "scene",
            "claim_type": card.get("claim_type") or "manager_gap",
            "proof_type": card.get("proof_type") or "sequence_inference",
            "status": status,
            "stage_code": _normalized_stage_code(
                card.get("stage_code") or recommendation.get("stage_code")
            ),
            "scene_id": card.get("scene_id"),
            "evidence_id": card.get("evidence_id")
            or (supporting_ids[0] if supporting_ids else None),
            "evidence_ids": supporting_ids,
            "evidence_quote": _clip(card.get("evidence_quote"), 700),
            "gap_proven": card.get("gap_proven"),
            "recommendation_id": card.get("recommendation_id")
            or recommendation.get("recommendation_id"),
            "supporting_evidence": _proof_card_evidence(
                explicit_items=_as_list(card.get("supporting_evidence")),
                evidence_ids=supporting_ids,
                evidence_by_id=evidence_by_id,
            ),
            "counter_evidence": _proof_card_evidence(
                explicit_items=_as_list(card.get("counter_evidence")),
                evidence_ids=counter_ids,
                evidence_by_id=evidence_by_id,
            ),
            "expected_absent_element": _clip(card.get("expected_absent_element"), 240),
            "reject_reason": _reject_reason(card),
            "outcome_reason": _clip(
                card.get("outcome_reason")
                or card.get("proof_explanation")
                or card.get("reject_reason"),
                360,
            ),
        }
        _fail_closed_on_missing_supporting_evidence(
            normalized_card,
            supporting_ids=supporting_ids,
            evidence_by_id=evidence_by_id,
        )
        if (
            normalized_card["proof_type"] == "absence_based"
            and not normalized_card["expected_absent_element"]
        ):
            normalized_card["expected_absent_element"] = _clip(card.get("claim"), 240)
        _enforce_proof_card_admission_contract(normalized_card)
        if normalized_card["status"] == "reject" and not normalized_card["reject_reason"]:
            normalized_card["reject_reason"] = "missing_evidence"
        if normalized_card["status"] in {"reject", "soften", "downgrade", "retry"}:
            normalized_card["outcome_reason"] = (
                normalized_card["outcome_reason"] or "Proof did not pass as verified."
            )
        normalized.append(
            {key: value for key, value in normalized_card.items() if value is not None}
        )
    return normalized


def _fail_closed_on_missing_supporting_evidence(
    card: dict[str, Any],
    *,
    supporting_ids: list[str],
    evidence_by_id: dict[str, dict[str, Any]],
) -> None:
    if _lower_str(card.get("status")) not in {"verified", "proven"}:
        return
    missing_ids = [
        evidence_id for evidence_id in supporting_ids if evidence_id not in evidence_by_id
    ]
    if not missing_ids:
        return
    card["status"] = "retry"
    card["gap_proven"] = False if card.get("gap_proven") is True else card.get("gap_proven")
    card["outcome_reason"] = (
        card.get("outcome_reason")
        or "Proof references supporting evidence ids that are missing from LLM-2A."
    )


def _enforce_proof_card_admission_contract(card: dict[str, Any]) -> None:
    status = _lower_str(card.get("status"))
    if status not in {"verified", "proven"}:
        return
    counter_evidence = _as_list(card.get("counter_evidence"))
    has_counter_evidence = any(
        _str_or_none(item.get("quote") if isinstance(item, dict) else item)
        or _str_or_none(item.get("evidence_id") if isinstance(item, dict) else None)
        for item in counter_evidence
    )
    if has_counter_evidence:
        card["status"] = "soften"
        card["gap_proven"] = False if card.get("gap_proven") is True else card.get("gap_proven")
        card["outcome_reason"] = (
            card.get("outcome_reason")
            or "Counter-evidence is present, so the claim cannot pass as proven."
        )
        return
    if _lower_str(card.get("proof_type")) != "sequence_inference":
        return
    supporting_evidence = _as_list(card.get("supporting_evidence"))
    evidence_count = sum(
        1
        for item in supporting_evidence
        if isinstance(item, dict)
        and (_str_or_none(item.get("evidence_id")) or _str_or_none(item.get("quote")))
    )
    if evidence_count < 2:
        card["status"] = "retry"
        card["gap_proven"] = False if card.get("gap_proven") is True else card.get("gap_proven")
        card["outcome_reason"] = (
            card.get("outcome_reason")
            or "Sequence inference needs at least two grounded evidence points."
        )


def _proof_card_evidence(
    *,
    explicit_items: list[Any],
    evidence_ids: list[str],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw_item in explicit_items:
        item = _as_dict(raw_item)
        quote = item.get("quote") or item.get("text")
        items.append(
            {
                "evidence_id": item.get("evidence_id"),
                "quote": _clip(quote, 700),
                "speaker": item.get("speaker") or "unknown",
            }
        )
    seen_ids = {_str_or_none(item.get("evidence_id")) for item in items}
    for evidence_id in evidence_ids:
        if evidence_id in seen_ids:
            continue
        evidence = evidence_by_id.get(evidence_id, {})
        items.append(
            {
                "evidence_id": evidence_id,
                "quote": _clip(evidence.get("text"), 700),
                "speaker": evidence.get("speaker") or "unknown",
            }
        )
    return [
        {key: value for key, value in item.items() if value is not None}
        for item in items
        if item.get("evidence_id") or item.get("quote")
    ]


def _proof_status(card: dict[str, Any]) -> str:
    raw_status = _lower_str(card.get("status") or card.get("proof_status"))
    if not raw_status:
        raw_status = "proven" if card.get("gap_proven") is True else "retry"
    return _CURRENT_PROOF_STATUS_BY_LAYERED_STATUS.get(raw_status, "retry")


def _reject_reason(card: dict[str, Any]) -> str | None:
    raw_reason = _lower_str(card.get("reject_reason"))
    if not raw_reason:
        return None
    return _CURRENT_REJECT_REASON_BY_LAYERED_REASON.get(raw_reason, "form_only_issue")


def _accepted_proof_cards_by_id(proof_cards: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(card.get("proof_id")): card
        for card in proof_cards
        if card.get("proof_id") and _lower_str(card.get("status")) in _ACCEPTED_PROOF_STATUSES
    }


def _accepted_proof_cards_by_claim_id(
    proof_cards: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(card.get("_claim_id")): card
        for card in proof_cards
        if card.get("_claim_id") and _lower_str(card.get("status")) in _ACCEPTED_PROOF_STATUSES
    }


def _normalized_criteria_results(
    *,
    criteria_results: list[Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = []
    for raw_item in criteria_results:
        item = _as_dict(raw_item)
        if not item:
            continue
        evidence_ids = _string_list(item.get("evidence_ids"))
        normalized.append(
            {
                "criterion_code": item.get("criterion_code"),
                "criterion_name": item.get("criterion_name"),
                "stage_code": _normalized_stage_code(item.get("stage_code")),
                "applicable": item.get("applicable", True),
                "score": _safe_int(item.get("score")),
                "max_score": _safe_int(item.get("max_score"), default=2),
                "comment": item.get("comment") or item.get("missing_evidence_reason") or "",
                "evidence": item.get("evidence")
                or _joined_evidence_text(evidence_ids, evidence_by_id),
                "scene_ids": _string_list(item.get("scene_ids")),
                "evidence_ids": evidence_ids,
                "missing_evidence_reason": item.get("missing_evidence_reason"),
            }
        )
    return normalized


def _score_by_stage_from_criteria(criteria_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stage_order = _checklist_stage_order()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for criterion in criteria_results:
        if not _criterion_is_applicable(criterion):
            continue
        stage_code = _str_or_none(criterion.get("stage_code"))
        if not stage_code:
            continue
        grouped.setdefault(stage_code, []).append(criterion)
    stages = []
    for stage_code in sorted(grouped, key=lambda code: stage_order.get(code, 10_000)):
        criteria = grouped[stage_code]
        stage_score = sum(_safe_int(item.get("score")) for item in criteria)
        max_stage_score = sum(_safe_int(item.get("max_score")) for item in criteria)
        stages.append(
            {
                "stage_code": stage_code,
                "stage_name": _stage_name(stage_code),
                "stage_score": stage_score,
                "max_stage_score": max_stage_score,
                "criteria_results": criteria,
            }
        )
    return stages


def _criterion_is_applicable(criterion: dict[str, Any]) -> bool:
    value = criterion.get("applicable", True)
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    return str(value).strip().lower() not in {"false", "0", "no", "n", "нет"}


def _normalized_strengths(
    strength_claims: list[Any],
    *,
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = []
    for raw_item in strength_claims:
        item = _as_dict(raw_item)
        if not item:
            continue
        evidence_ids = _string_list(item.get("evidence_ids"))
        normalized.append(
            {
                "claim_id": item.get("claim_id"),
                "stage_code": _normalized_stage_code(item.get("stage_code")),
                "title": item.get("claim"),
                "impact": item.get("comment") or item.get("claim"),
                "evidence": _joined_evidence_text(evidence_ids, evidence_by_id),
                "scene_ids": _string_list(item.get("scene_ids")),
                "evidence_ids": evidence_ids,
                "confidence": item.get("confidence"),
            }
        )
    return normalized


def _normalized_gaps(
    *,
    gap_claims: list[Any],
    proof_cards_by_claim_id: dict[str, dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = []
    for raw_item in gap_claims:
        item = _as_dict(raw_item)
        claim_id = _str_or_none(item.get("claim_id"))
        proof_card = proof_cards_by_claim_id.get(claim_id or "")
        if not proof_card:
            continue
        evidence_ids = _string_list(item.get("evidence_ids") or proof_card.get("evidence_ids"))
        normalized.append(
            {
                "claim_id": claim_id,
                "proof_id": proof_card.get("proof_id"),
                "stage_code": _normalized_stage_code(
                    item.get("stage_code") or proof_card.get("stage_code")
                ),
                "title": proof_card.get("claim") or item.get("claim"),
                "impact": item.get("expected_behavior")
                or item.get("observed_behavior")
                or item.get("claim"),
                "evidence": proof_card.get("evidence_quote")
                or _joined_evidence_text(evidence_ids, evidence_by_id),
                "scene_ids": _string_list(item.get("scene_ids") or [proof_card.get("scene_id")]),
                "evidence_ids": evidence_ids,
                "proof_status": proof_card.get("status"),
            }
        )
    return normalized


def _normalized_recommendations(
    recommendations: list[Any],
    *,
    accepted_proof_cards: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized = []
    for raw_item in recommendations:
        item = _as_dict(raw_item)
        proof_id = _str_or_none(item.get("proof_id"))
        if proof_id not in accepted_proof_cards:
            continue
        proof_card = accepted_proof_cards[proof_id]
        normalized.append(
            {
                "recommendation_id": item.get("recommendation_id"),
                "proof_id": proof_id,
                "stage_code": _normalized_stage_code(
                    item.get("stage_code") or proof_card.get("stage_code")
                ),
                "priority": item.get("priority") or "medium",
                "problem": item.get("problem") or proof_card.get("claim"),
                "why_it_matters": item.get("why_it_matters"),
                "better_phrase": item.get("better_phrase"),
                "next_action": item.get("next_action"),
                "recommendation": item.get("next_action") or item.get("better_phrase"),
            }
        )
    return normalized


def _normalized_status_details(value: Any) -> dict[str, Any] | None:
    raw = _as_dict(value)
    if not raw:
        return None
    status = _normalized_status_detail_status(raw.get("status"))
    if not status:
        for candidate in _STATUS_DETAILS_KEYS:
            if _as_dict(raw.get(candidate)):
                status = candidate
                break
    if not status:
        return None
    result: dict[str, Any] = {"status": status}
    for key in _STATUS_DETAILS_KEYS:
        result[key] = None
    active_raw = _as_dict(raw.get(status))
    if not active_raw:
        active_raw = _as_dict(raw.get("details") or raw.get("detail"))
    active: dict[str, Any] = {}
    for field in _STATUS_DETAILS_FIELDS[status]:
        if field == "follow_up_needed":
            bool_value = _optional_bool(active_raw.get(field))
            if bool_value is not None:
                active[field] = bool_value
            continue
        text = _clip(active_raw.get(field), 420 if field == "evidence" else 240)
        if text is not None:
            active[field] = text
    result[status] = active
    return result


def _normalized_coaching_decision(
    value: Any,
    *,
    scores_detail: dict[str, Any],
) -> dict[str, Any] | None:
    raw = _as_dict(value)
    if not raw:
        return None
    warnings: list[dict[str, Any]] = []
    decision = _lower_str(raw.get("decision")).replace("-", "_")
    if decision not in _COACHING_DECISIONS:
        _append_coaching_decision_diagnostic(
            scores_detail,
            {
                "code": "coaching_decision_invalid_enum",
                "field": "decision",
                "original": raw.get("decision"),
            },
        )
        return None

    title = _normalized_coaching_title(
        raw.get("title"),
        decision=decision,
        warnings=warnings,
    )
    based_on = _normalized_coaching_based_on(raw.get("based_on"))
    normalized: dict[str, Any] = {
        "decision": decision,
        "title": title,
        "text": _clip(raw.get("text"), 360),
        "reason": _clip(raw.get("reason"), 360),
        "based_on": based_on,
    }
    normalized = {key: item for key, item in normalized.items() if item not in ({},)}
    for warning in warnings:
        _append_coaching_decision_diagnostic(scores_detail, warning)
    return normalized


def _normalized_coaching_title(
    value: Any,
    *,
    decision: str,
    warnings: list[dict[str, Any]],
) -> str | None:
    title = _str_or_none(value)
    if title is None:
        return None
    allowed = _COACHING_TITLES_BY_DECISION[decision]
    if title in allowed:
        return title or None
    code = (
        "coaching_decision_title_mismatch"
        if title in {"Улучшить", "Поддерживать", "Корректно"}
        else "coaching_decision_invalid_title"
    )
    warnings.append(
        {
            "code": code,
            "field": "title",
            "decision": decision,
            "original": title,
            "replacement": None,
        }
    )
    return None


def _normalized_coaching_based_on(value: Any) -> dict[str, Any]:
    raw = _as_dict(value)
    if not raw:
        return {}
    based_on: dict[str, Any] = {}
    stage_code = _normalized_stage_code(raw.get("stage_code"))
    if stage_code:
        based_on["stage_code"] = stage_code
    criterion_codes = _string_list(
        raw.get("criterion_codes")
        or ([raw.get("criterion_code")] if raw.get("criterion_code") else [])
    )
    if criterion_codes:
        based_on["criterion_codes"] = criterion_codes
    proof_ids = _string_list(
        raw.get("proof_ids") or ([raw.get("proof_id")] if raw.get("proof_id") else [])
    )
    if proof_ids:
        based_on["proof_ids"] = proof_ids
    evidence_ids = _string_list(
        raw.get("evidence_ids")
        or ([raw.get("evidence_id")] if raw.get("evidence_id") else [])
    )
    if evidence_ids:
        based_on["evidence_ids"] = evidence_ids
    return based_on


def _append_coaching_decision_diagnostic(
    scores_detail: dict[str, Any],
    warning: dict[str, Any],
) -> None:
    diagnostics = _as_dict(scores_detail.get("diagnostics"))
    diagnostics.setdefault("coaching_decision_validation", []).append(warning)
    scores_detail["diagnostics"] = diagnostics


def _normalized_edo_scope(value: Any) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if value is None:
        return None, []
    raw = _as_dict(value)
    if not raw:
        return None, [{"code": "edo_scope_invalid_shape", "field": "edo_scope"}]

    warnings: list[dict[str, Any]] = []
    sales_scoring_scope = _normalized_edo_enum(
        raw.get("sales_scoring_scope"),
        allowed_values=_EDO_SALES_SCORING_SCOPES,
        default="unclear",
        field="sales_scoring_scope",
        warnings=warnings,
    )
    scope_reason = _normalized_edo_enum(
        raw.get("scope_reason"),
        allowed_values=_EDO_SCOPE_REASONS,
        default="other",
        field="scope_reason",
        warnings=warnings,
    )
    expected_manager_action = _normalized_edo_enum(
        raw.get("expected_manager_action"),
        allowed_values=_EDO_EXPECTED_MANAGER_ACTIONS,
        default="other",
        field="expected_manager_action",
        warnings=warnings,
    )
    evidence_ids = _edo_scope_evidence_ids(raw.get("evidence_ids"), warnings=warnings)
    return {
        "sales_scoring_scope": sales_scoring_scope,
        "scope_reason": scope_reason,
        "applicable_part": _clip(raw.get("applicable_part"), 420) or "",
        "expected_manager_action": expected_manager_action,
        "evidence_ids": evidence_ids,
    }, warnings


def _normalized_edo_enum(
    value: Any,
    *,
    allowed_values: set[str],
    default: str,
    field: str,
    warnings: list[dict[str, Any]],
) -> str:
    normalized = _lower_str(value).replace("-", "_")
    if normalized in allowed_values:
        return normalized
    warnings.append(
        {
            "code": "edo_scope_invalid_enum",
            "field": field,
            "original": value,
            "replacement": default,
        }
    )
    return default


def _edo_scope_evidence_ids(
    value: Any,
    *,
    warnings: list[dict[str, Any]],
) -> list[str]:
    if not isinstance(value, list):
        if value not in (None, ""):
            warnings.append(
                {
                    "code": "edo_scope_invalid_evidence_ids_shape",
                    "field": "evidence_ids",
                    "original_type": type(value).__name__,
                    "replacement": [],
                }
            )
        return []
    evidence_ids = []
    invalid_count = 0
    for item in value:
        if not isinstance(item, str):
            invalid_count += 1
            continue
        text = item.strip()
        if text:
            evidence_ids.append(text)
    if invalid_count:
        warnings.append(
            {
                "code": "edo_scope_invalid_evidence_id_item",
                "field": "evidence_ids",
                "invalid_count": invalid_count,
            }
        )
    return evidence_ids


def _normalized_status_detail_status(value: Any) -> str | None:
    text = _lower_str(value).replace("-", "_")
    return _STATUS_DETAILS_ALIASES.get(text)


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _lower_str(value)
    if text in {"true", "yes", "1", "да", "нужен", "требуется"}:
        return True
    if text in {"false", "no", "0", "нет", "не нужен", "не требуется"}:
        return False
    return None


def _attach_report_evidence(
    *,
    scores_detail: dict[str, Any],
    llm2a: dict[str, Any],
    final_from_2d: dict[str, Any],
    proof_cards: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> None:
    report_evidence = _allowed_report_evidence_fields(
        final_from_2d.get("report_evidence") or scores_detail.get("report_evidence")
    )
    if report_evidence.get("quote_bank"):
        report_evidence["quote_bank"] = _normalized_quote_bank(
            report_evidence.get("quote_bank"),
            evidence_by_id=evidence_by_id,
        )
    report_evidence["proof_cards"] = [_public_proof_card(card) for card in proof_cards]
    business_outcome = _business_outcome(llm2a, evidence_by_id)
    if business_outcome:
        report_evidence["business_outcome"] = business_outcome
    if not _as_dict(report_evidence.get("call_essence")):
        call_essence = _call_essence(
            report_evidence=report_evidence,
            business_outcome=business_outcome,
            llm2a=llm2a,
            final_from_2d=scores_detail,
        )
        if call_essence:
            report_evidence["call_essence"] = call_essence
    scores_detail["report_evidence_version"] = SUPPORTED_REPORT_EVIDENCE_VERSION
    scores_detail["report_evidence"] = report_evidence


def _normalized_quote_bank(
    value: Any,
    *,
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in _as_list(value):
        raw = _as_dict(item)
        evidence_id = _first_non_empty_str(raw.get("evidence_id"), raw.get("id"))
        source = evidence_by_id.get(evidence_id or "", {})
        quote = _first_non_empty_str(raw.get("quote"), raw.get("text"), source.get("text"))
        if not quote:
            continue
        normalized.append(
            {
                "quote": quote,
                "speaker": _lower_str(raw.get("speaker") or source.get("speaker")) or "unknown",
                "topic": _first_non_empty_str(raw.get("topic"), evidence_id, "call evidence"),
                "stage_code": _first_non_empty_str(
                    raw.get("stage_code"),
                    source.get("stage_code"),
                    source.get("stage_hint"),
                    "cross_stage_transition",
                ),
                "evidence_quality": _lower_str(raw.get("evidence_quality")) or "direct",
                "usable_in_report": bool(raw.get("usable_in_report", True)),
            }
        )
    return normalized


def _attach_layered_analysis_metadata(
    *,
    scores_detail: dict[str, Any],
    llm2a: dict[str, Any],
    llm2b: dict[str, Any],
    llm2c: dict[str, Any],
    llm2d: dict[str, Any],
    proof_cards: list[dict[str, Any]],
) -> None:
    existing = _as_dict(scores_detail.get("layered_analysis"))
    existing.update(
        {
            "adapter_instruction_version": LAYERED_ADAPTER_INSTRUCTION_VERSION,
            "pass_artifacts": {
                "llm2a": _pass_artifact_metadata(
                    llm2a,
                    required_list_fields=("scenes", "evidence_ledger"),
                ),
                "llm2b": _pass_artifact_metadata(
                    llm2b,
                    required_list_fields=("criteria_results",),
                ),
                "llm2c": _pass_artifact_metadata(
                    llm2c,
                    required_list_fields=("proof_cards",),
                ),
                "llm2d": _pass_artifact_metadata(
                    llm2d,
                    required_any_fields=(
                        "recommendations",
                        "final_normalized_analysis",
                    ),
                ),
            },
            "proof_card_counts": _proof_card_counts(proof_cards),
        }
    )
    scores_detail["layered_analysis"] = existing


def _pass_artifact_metadata(
    artifact: dict[str, Any],
    *,
    required_list_fields: tuple[str, ...] = (),
    required_any_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    present = bool(artifact)
    has_required_lists = all(
        isinstance(artifact.get(field), list) for field in required_list_fields
    )
    has_any_required = (
        True
        if not required_any_fields
        else any(artifact.get(field) not in (None, "") for field in required_any_fields)
    )
    return {
        "present": present,
        "pass": artifact.get("pass"),
        "artifact_version": artifact.get("artifact_version"),
        "call_id": artifact.get("call_id"),
        "valid_shape": present and has_required_lists and has_any_required,
    }


def _proof_card_counts(proof_cards: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "total": len(proof_cards),
        "accepted": 0,
        "verified": 0,
        "proven": 0,
        "soften": 0,
        "retry": 0,
        "reject": 0,
        "downgrade": 0,
        "warning": 0,
    }
    for card in proof_cards:
        status = _lower_str(card.get("status"))
        if status in counts:
            counts[status] += 1
        if status in _ACCEPTED_PROOF_STATUSES:
            counts["accepted"] += 1
    return counts


def _allowed_report_evidence_fields(value: Any) -> dict[str, Any]:
    allowed_keys = {
        "business_outcome",
        "call_essence",
        "call_report_summary",
        "semantic_case",
        "block_candidates",
        "situation_candidates",
        "manager_coaching_moments",
        "voice_of_customer",
        "additional_situations",
        "follow_up_candidates",
        "quote_bank",
    }
    return {
        key: item
        for key, item in _as_dict(value).items()
        if key in allowed_keys
    }


def _public_proof_card(card: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in card.items() if not key.startswith("_")}


def _business_outcome(
    llm2a: dict[str, Any],
    evidence_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    signal = _as_dict(llm2a.get("business_outcome_signal"))
    status = _lower_str(signal.get("status"))
    if status not in {
        "agreement",
        "rescheduled",
        "refusal",
        "open",
        "tech_service",
        "not_suitable",
    }:
        return None
    evidence_ids = _string_list(signal.get("evidence_ids"))
    first_evidence = evidence_by_id.get(evidence_ids[0], {}) if evidence_ids else {}
    return {
        "status": status,
        "confidence": _lower_str(signal.get("confidence")) or "low",
        "reason": signal.get("reason") or "",
        "evidence_quote": first_evidence.get("text"),
        "evidence_speaker": first_evidence.get("speaker") or "unknown",
    }


def _call_essence(
    *,
    report_evidence: dict[str, Any],
    business_outcome: dict[str, Any] | None,
    llm2a: dict[str, Any],
    final_from_2d: dict[str, Any],
) -> dict[str, Any] | None:
    summary = _as_dict(report_evidence.get("call_report_summary"))
    follow_up = _as_dict(final_from_2d.get("follow_up"))
    first_follow_up = _as_dict(_first_list_item(report_evidence.get("follow_up_candidates")))
    first_agreement = _first_list_item(final_from_2d.get("agreements"))
    first_recommendation = _as_dict(_first_list_item(final_from_2d.get("recommendations")))
    agreement_text = _first_non_empty_str(
        _agreement_text(first_agreement),
        first_follow_up.get("why_follow_up"),
        _scene_commitment_text(llm2a),
    )
    topic = _first_non_empty_str(
        summary.get("short_topic"),
        _as_dict(final_from_2d.get("summary")).get("short"),
        _scene_topic_text(llm2a),
    )
    outcome = _first_non_empty_str(
        _as_dict(business_outcome).get("status"),
        first_follow_up.get("status"),
    )
    outcome_reason = _first_non_empty_str(
        _as_dict(business_outcome).get("reason"),
        summary.get("hotness_reason"),
        first_follow_up.get("why_follow_up"),
        _scene_service_or_refusal_text(llm2a),
    )
    next_step = _first_non_empty_str(
        first_follow_up.get("next_step"),
        follow_up.get("next_step_text"),
        follow_up.get("next_step"),
        summary.get("manager_next_action"),
        _as_dict(first_agreement).get("next_step"),
        first_recommendation.get("next_action"),
        first_recommendation.get("recommendation"),
    )
    service_request = (
        _scene_service_or_refusal_text(llm2a)
        if outcome == "tech_service"
        else None
    )
    manager_visible_text = _first_non_empty_str(
        summary.get("manager_visible_summary"),
        summary.get("short_context"),
        _compose_call_essence_text(
            topic=topic,
            outcome=outcome,
            reason=outcome_reason,
            agreement=agreement_text,
            next_step=next_step,
            service_request=service_request,
        ),
    )
    if not any((topic, outcome, outcome_reason, agreement_text, next_step, service_request, manager_visible_text)):
        return None
    essence = {
        "topic": _clip(topic, 160),
        "outcome": outcome if outcome in {
            "agreement",
            "rescheduled",
            "refusal",
            "open",
            "tech_service",
            "not_suitable",
        } else None,
        "refusal_or_interest_reason": _clip(outcome_reason, 280),
        "outcome_reason": _clip(outcome_reason, 280),
        "agreement": _clip(agreement_text, 280),
        "next_step": _clip(next_step, 280),
        "deadline": _clip(first_follow_up.get("deadline"), 120),
        "service_request": _clip(service_request, 280),
        "manager_visible_text": _clip(manager_visible_text, 640),
        "source": "llm2_layered_analysis.derived_call_essence",
        "evidence_quote": _clip(_as_dict(business_outcome).get("evidence_quote"), 700),
        "evidence_speaker": _as_dict(business_outcome).get("evidence_speaker") or "unknown",
    }
    return {key: value for key, value in essence.items() if value is not None}


def _first_list_item(value: Any) -> Any:
    items = _as_list(value)
    return items[0] if items else {}


def _agreement_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    item = _as_dict(value)
    return _first_non_empty_str(
        item.get("agreement"),
        item.get("summary"),
        item.get("description"),
        item.get("what_agreed"),
        item.get("commitment"),
    )


def _scene_topic_text(llm2a: dict[str, Any]) -> str | None:
    scene = _as_dict(_first_list_item(llm2a.get("scenes")))
    return _first_non_empty_str(scene.get("what_happened"), scene.get("stage_hint"))


def _scene_commitment_text(llm2a: dict[str, Any]) -> str | None:
    for scene in _as_list(llm2a.get("scenes")):
        commitments = [
            _str_or_none(item)
            for item in _as_list(_as_dict(scene).get("observed_commitments"))
        ]
        text = "; ".join(item for item in commitments if item)
        if text:
            return text
    return None


def _scene_service_or_refusal_text(llm2a: dict[str, Any]) -> str | None:
    for scene in _as_list(llm2a.get("scenes")):
        signals = [
            _str_or_none(item)
            for item in _as_list(_as_dict(scene).get("service_or_refusal_signals"))
        ]
        text = "; ".join(item for item in signals if item)
        if text:
            return text
    return None


def _compose_call_essence_text(
    *,
    topic: str | None,
    outcome: str | None,
    reason: str | None,
    agreement: str | None,
    next_step: str | None,
    service_request: str | None,
) -> str | None:
    parts = [
        _str_or_none(topic),
        _str_or_none(service_request),
        _str_or_none(reason),
        _str_or_none(agreement),
        _str_or_none(next_step),
    ]
    text = ". ".join(part.rstrip(".") for part in parts if part)
    if outcome and text:
        return text
    return text or None


def _evidence_fragments_from_scenes(
    *,
    scenes_by_id: dict[str, dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    fragments = []
    for evidence_id, evidence in evidence_by_id.items():
        scene = scenes_by_id.get(str(evidence.get("scene_id") or ""), {})
        fragments.append(
            {
                "type": "llm2_scene_evidence",
                "stage_code": scene.get("stage_hint"),
                "scene_id": evidence.get("scene_id"),
                "evidence_id": evidence_id,
                "speaker": evidence.get("speaker") or "unknown",
                "quote": evidence.get("text"),
                "comment": scene.get("what_happened"),
            }
        )
    return fragments


def _populate_checklist_score(scores_detail: dict[str, Any]) -> None:
    total_points = 0
    max_points = 0
    for stage in _as_list(scores_detail.get("score_by_stage")):
        item = _as_dict(stage)
        total_points += _safe_int(item.get("stage_score"))
        max_points += _safe_int(item.get("max_stage_score"))
    percent = round((total_points / max_points) * 100, 2) if max_points else 0.0
    checklist_score = _as_dict(_as_dict(scores_detail.get("score")).get("checklist_score"))
    checklist_score.update(
        {
            "total_points": total_points,
            "max_points": max_points,
            "score_percent": percent,
            "level": _score_level(percent),
        }
    )
    scores_detail["score"] = {"checklist_score": checklist_score}


def _repair_vague_availability_follow_up(scores_detail: dict[str, Any]) -> None:
    """Remove vague availability from callback/agreement fields without rejecting analysis."""

    summary = _as_dict(scores_detail.get("summary"))
    follow_up = _as_dict(scores_detail.get("follow_up"))
    agreements = _as_list(scores_detail.get("agreements"))
    report_evidence = _as_dict(scores_detail.get("report_evidence"))
    call_essence = _as_dict(report_evidence.get("call_essence"))
    candidate_texts = [
        summary.get("outcome_code"),
        summary.get("outcome_text"),
        summary.get("next_step_text"),
        follow_up.get("next_step"),
        follow_up.get("next_step_text"),
        follow_up.get("due_date_text"),
        call_essence.get("agreement"),
        call_essence.get("next_step"),
    ]
    for agreement in agreements:
        item = _as_dict(agreement)
        candidate_texts.extend(
            [
                item.get("action"),
                item.get("agreement"),
                item.get("summary"),
                item.get("description"),
                item.get("timing"),
                item.get("owner"),
            ]
        )
    joined = " ".join(str(item or "") for item in candidate_texts)
    if not _is_vague_availability_text(joined) or _has_concrete_next_step_signal(joined):
        return

    repairs: list[dict[str, Any]] = []
    outcome_code = _lower_str(summary.get("outcome_code"))
    if outcome_code in {"callback_planned", "agreement", "rescheduled"}:
        repairs.append(
            {
                "code": "vague_availability_not_callback",
                "field": "summary.outcome_code",
                "original": summary.get("outcome_code"),
                "replacement": "open",
            }
        )
        summary["outcome_code"] = "open"
        summary["outcome_text"] = "Конкретный следующий шаг не зафиксирован"
        if _is_vague_availability_text(summary.get("next_step_text")):
            summary["next_step_text"] = None

    if _is_vague_availability_text(json_like_text(follow_up)):
        repairs.append(
            {
                "code": "vague_availability_removed_from_follow_up",
                "field": "follow_up",
                "original": deepcopy(follow_up),
            }
        )
        follow_up = {
            "next_step_fixed": False,
            "reason_not_fixed": "vague_availability_not_concrete_next_step",
        }

    kept_agreements = []
    removed_agreements = []
    for agreement in agreements:
        if _is_vague_availability_text(json_like_text(agreement)):
            removed_agreements.append(agreement)
        else:
            kept_agreements.append(agreement)
    if removed_agreements:
        repairs.append(
            {
                "code": "vague_availability_removed_from_agreements",
                "field": "agreements",
                "removed_count": len(removed_agreements),
            }
        )

    if _is_vague_availability_text(call_essence.get("agreement")):
        call_essence.pop("agreement", None)
    if _is_vague_availability_text(call_essence.get("next_step")):
        call_essence.pop("next_step", None)

    scores_detail["summary"] = summary
    scores_detail["follow_up"] = follow_up
    scores_detail["agreements"] = kept_agreements
    if call_essence:
        report_evidence["call_essence"] = call_essence
        scores_detail["report_evidence"] = report_evidence
    if repairs:
        diagnostics = _as_dict(scores_detail.get("diagnostics"))
        diagnostics.setdefault("semantic_repairs", []).extend(repairs)
        scores_detail["diagnostics"] = diagnostics


def _repair_recommendation_like_follow_up(scores_detail: dict[str, Any]) -> None:
    """Keep coaching recommendations out of factual follow-up fields."""

    summary = _as_dict(scores_detail.get("summary"))
    follow_up = _as_dict(scores_detail.get("follow_up"))
    report_evidence = _as_dict(scores_detail.get("report_evidence"))
    call_essence = _as_dict(report_evidence.get("call_essence"))
    candidate_texts = [
        summary.get("next_step_text"),
        follow_up.get("next_step"),
        follow_up.get("next_step_text"),
        follow_up.get("action"),
        call_essence.get("next_step"),
    ]
    joined = " ".join(str(item or "") for item in candidate_texts)
    if not _is_recommendation_like_follow_up(joined):
        return

    repairs: list[dict[str, Any]] = []
    if _is_recommendation_like_follow_up(summary.get("next_step_text")):
        repairs.append(
            {
                "code": "recommendation_like_next_step_removed",
                "field": "summary.next_step_text",
                "original": summary.get("next_step_text"),
            }
        )
        summary["next_step_text"] = None
    if _is_recommendation_like_follow_up(json_like_text(follow_up)):
        repairs.append(
            {
                "code": "recommendation_like_follow_up_removed",
                "field": "follow_up",
                "original": deepcopy(follow_up),
            }
        )
        follow_up = {
            "next_step_fixed": False,
            "reason_not_fixed": "recommendation_not_factual_follow_up",
        }
    if _is_recommendation_like_follow_up(call_essence.get("next_step")):
        repairs.append(
            {
                "code": "recommendation_like_call_essence_next_step_removed",
                "field": "report_evidence.call_essence.next_step",
                "original": call_essence.get("next_step"),
            }
        )
        call_essence.pop("next_step", None)

    scores_detail["summary"] = summary
    scores_detail["follow_up"] = follow_up
    if call_essence:
        report_evidence["call_essence"] = call_essence
        scores_detail["report_evidence"] = report_evidence
    if repairs:
        diagnostics = _as_dict(scores_detail.get("diagnostics"))
        diagnostics.setdefault("semantic_repairs", []).extend(repairs)
        scores_detail["diagnostics"] = diagnostics


def _attach_semantic_diagnostics(scores_detail: dict[str, Any]) -> None:
    diagnostics = _as_dict(scores_detail.get("diagnostics"))
    warnings = list(diagnostics.get("semantic_warnings") or [])
    criteria = _as_list(scores_detail.get("criteria_results"))
    empty_evidence_count = sum(
        1 for item in criteria if not _str_or_none(_as_dict(item).get("evidence"))
    )
    if criteria and empty_evidence_count:
        warnings.append(
            {
                "code": "criteria_evidence_empty",
                "empty_count": empty_evidence_count,
                "total_count": len(criteria),
            }
        )
    if _is_vague_availability_text(json_like_text(scores_detail.get("follow_up"))) or any(
        _is_vague_availability_text(json_like_text(item))
        for item in _as_list(scores_detail.get("agreements"))
    ):
        warnings.append({"code": "vague_availability_present_after_repair"})
    if _is_recommendation_like_follow_up(json_like_text(scores_detail.get("follow_up"))):
        warnings.append({"code": "recommendation_like_follow_up_present_after_repair"})
    if warnings:
        diagnostics["semantic_warnings"] = warnings
        scores_detail["diagnostics"] = diagnostics


def _is_vague_availability_text(value: Any) -> bool:
    text = _lower_str(value).replace("ё", "е")
    if not text:
        return False
    return any(
        phrase in text
        for phrase in (
            "можете обращаться",
            "можете обратиться",
            "можно обращаться",
            "можно обратиться",
            "обращайтесь",
            "если будут вопросы",
            "если возникнут вопросы",
            "в случае возникновения вопросов",
            "при возникновении вопросов",
            "буду подробнее рассказать",
            "буду подробнее рассказать, помочь",
            "помочь если будут вопросы",
            "reach out if",
            "contact us if",
            "if you have questions",
        )
    )


def _has_concrete_next_step_signal(value: Any) -> bool:
    text = _lower_str(value).replace("ё", "е")
    if not text:
        return False
    if any(
        marker in text
        for marker in (
            "завтра",
            "сегодня",
            "послезавтра",
            "понедельник",
            "вторник",
            "среду",
            "среда",
            "четверг",
            "пятницу",
            "пятница",
            "созвон",
            "перезвон",
            "презентац",
            "демо",
            "отправлю",
            "пришлю",
        )
    ):
        return True
    return any(ch.isdigit() for ch in text)


def _is_recommendation_like_follow_up(value: Any) -> bool:
    text = _lower_str(value).replace("ё", "е")
    if not text:
        return False
    recommendation_markers = (
        "обратитесь к клиент",
        "свяжитесь с клиент",
        "уточните у клиент",
        "предложите клиент",
        "объясните клиент",
        "зафиксируйте",
        "добавьте конкрет",
        "рекомендуется",
        "следует",
        "нужно",
        "надо",
        "coach",
        "recommend",
    )
    return any(marker in text for marker in recommendation_markers)


def json_like_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(json_like_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(json_like_text(item) for item in value)
    return str(value or "")


def _score_level(percent: float) -> str:
    if percent >= 85:
        return "excellent"
    if percent >= 70:
        return "strong"
    if percent >= 50:
        return "basic"
    return "problematic"


def _evidence_ledger_by_id(llm2a: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("evidence_id")): item
        for item in _as_list(llm2a.get("evidence_ledger"))
        if isinstance(item, dict) and item.get("evidence_id")
    }


def _scenes_by_id(llm2a: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("scene_id")): item
        for item in _as_list(llm2a.get("scenes"))
        if isinstance(item, dict) and item.get("scene_id")
    }


def _joined_evidence_text(
    evidence_ids: list[str],
    evidence_by_id: dict[str, dict[str, Any]],
) -> str:
    return " / ".join(
        str(evidence_by_id[evidence_id].get("text") or "").strip()
        for evidence_id in evidence_ids
        if evidence_id in evidence_by_id
        and str(evidence_by_id[evidence_id].get("text") or "").strip()
    )


def _stage_name(stage_code: str) -> str:
    for stage in CHECKLIST_DEFINITION.get("stages", []):
        if stage.get("stage_code") == stage_code:
            return str(stage.get("stage_name") or stage_code)
    return stage_code


def _normalized_stage_code(value: Any) -> str:
    stage_code = _lower_str(value)
    if not stage_code:
        return ""
    stage_code = _STAGE_CODE_ALIASES.get(stage_code, stage_code)
    return stage_code if stage_code in _VALID_STAGE_CODES else stage_code


def _checklist_stage_order() -> dict[str, int]:
    return {
        str(stage.get("stage_code")): index
        for index, stage in enumerate(CHECKLIST_DEFINITION.get("stages", []))
        if stage.get("stage_code")
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _str_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _first_non_empty_str(*values: Any) -> str | None:
    for value in values:
        text = _str_or_none(value)
        if text:
            return text
    return None


def _lower_str(value: Any) -> str:
    return str(value or "").strip().lower()


def _clip(value: Any, max_length: int) -> str | None:
    text = _str_or_none(value)
    if text is None:
        return None
    return text[:max_length]


__all__ = [
    "LAYERED_ADAPTER_INSTRUCTION_VERSION",
    "LayeredLLM2NormalizationResult",
    "normalize_llm2_layered_analysis",
    "normalize_llm2_layered_scores_detail",
]
